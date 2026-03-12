"""
Finance service – Business logic for ledger/extracto del cliente.

Responsibility:
  - Own the exercise_start_date business rule (Jan 1 of start_date's fiscal year)
  - Orchestrate the repository call
  - Transform raw DEBE flag into importe_debe / importe_haber
  - Accumulate running saldo from exercise_start_date
  - Filter visible items to [start_date, end_date]
  - Return a dict ready to be serialised as LedgerResponse by the API layer

This layer does NOT know about HTTP or Pydantic – it receives plain Python
types and returns plain dicts.
"""
import logging
from datetime import date
from decimal import Decimal
from typing import Any

from ..repositories.finance_repository import fetch_ledger_entries

logger = logging.getLogger(__name__)

_ZERO = Decimal("0")


def _to_decimal(value: Any) -> Decimal:
    """Safely coerce a numeric DB value to Decimal."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _split_debe_haber(importe: Decimal, debe_flag: Any) -> tuple[Decimal, Decimal]:
    """
    Split IMPORTE into (importe_debe, importe_haber) based on the DEBE column flag.

    Convention from diario_e:
      DEBE=0/"0" → movement is on the debe  side: (importe_debe=IMPORTE, importe_haber=0)
      DEBE=1/"1" → movement is on the haber side: (importe_debe=0,       importe_haber=IMPORTE)

    Args:
        importe: Gross amount of the movement (always positive).
        debe_flag: Value of the DEBE column; must be 0, 1, "0", or "1".

    Returns:
        Tuple of (importe_debe, importe_haber) as Decimal.

    Raises:
        ValueError: if debe_flag is not 0 or 1.
    """
    if debe_flag in (0, "0"):
        return importe, _ZERO
    if debe_flag in (1, "1"):
        return _ZERO, importe
    raise ValueError(f"Unexpected DEBE value: {debe_flag!r}; expected 0 or 1")


async def get_ledger(
    cta_contable: str,
    start_date: date,
    end_date: date,
) -> dict[str, Any]:
    """
    Retrieve the ledger for a customer within the visible range [start_date, end_date].

    Internally fetches from exercise_start_date (Jan 1 of start_date's year) to
    end_date so the running saldo is correctly anchored at the start of the fiscal
    year, even when start_date is mid-year.

    Args:
        cta_contable: Customer accounting account code (never from client).
        start_date: First date of the visible range returned to the client.
        end_date: Last date of the visible range (inclusive).

    Returns:
        Dict matching LedgerResponse:
          {start_date, end_date, exercise_start_date, total_items, items}

    Raises:
        ValueError: if a row contains an unexpected DEBE value.
    """
    exercise_start_date = date(start_date.year, 1, 1)

    rows = await fetch_ledger_entries(
        cta_contable=cta_contable,
        exercise_start_date=exercise_start_date,
        start_date=start_date,
        end_date=end_date,
    )

    running_saldo = _ZERO
    visible_items: list[dict[str, Any]] = []

    for row in rows:
        importe = _to_decimal(row["importe"])
        importe_debe, importe_haber = _split_debe_haber(importe, row["debe"])
        running_saldo = running_saldo + importe_debe - importe_haber

        row_date: date = row["fecha"]
        if row_date < start_date:
            # Pre-period row: contributes to saldo but is not visible to the client.
            continue

        visible_items.append(
            {
                "fecha": row_date,
                "concepto": row["concepto"] or "",
                "importe_debe": importe_debe,
                "importe_haber": importe_haber,
                "saldo": running_saldo,
            }
        )

    return {
        "start_date": start_date,
        "end_date": end_date,
        "exercise_start_date": exercise_start_date,
        "total_items": len(visible_items),
        "items": visible_items,
    }
