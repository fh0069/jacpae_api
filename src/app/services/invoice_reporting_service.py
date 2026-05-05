"""
Invoice Reporting service – Business logic for fiscal/VAT invoice list.

Responsibility:
  - Orchestrate the repository call
  - Coerce raw Decimal values safely
  - Accumulate period totals (total_base, total_iva, total_recargo, total_factura)
  - Return a dict ready to be serialised as VatInvoiceListResponse by the API layer

This layer does NOT know about HTTP or Pydantic – it receives plain Python
types and returns plain dicts.
"""
import logging
from datetime import date
from decimal import Decimal
from typing import Any

from ..repositories.invoice_reporting_repository import fetch_vat_invoices

logger = logging.getLogger(__name__)

_ZERO = Decimal("0")


def _to_decimal(value: Any) -> Decimal:
    """Safely coerce a numeric DB value to Decimal."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


async def get_vat_invoice_list(
    cta_contable: str,
    start_date: date,
    end_date: date,
) -> dict[str, Any]:
    """
    Retrieve the VAT invoice list for a customer within [start_date, end_date].

    Accumulates period totals in Python — no SQL aggregation needed.

    Args:
        cta_contable: Customer accounting account code (never from client).
        start_date: Start of the fiscal date range (inclusive).
        end_date: End of the fiscal date range (inclusive).

    Returns:
        Dict matching VatInvoiceListResponse:
          {items: [...], totals: {total_base, total_iva, total_recargo, total_factura}}
    """
    rows = await fetch_vat_invoices(
        cta_contable=cta_contable,
        start_date=start_date,
        end_date=end_date,
    )

    items: list[dict[str, Any]] = []
    total_base = _ZERO
    total_iva = _ZERO
    total_recargo = _ZERO
    total_factura = _ZERO

    for row in rows:
        base_imp = _to_decimal(row["base_imp"])
        tipo_iva = _to_decimal(row["tipo_iva"])
        cuota_iva = _to_decimal(row["cuota_iva"])
        tipo_recargo = _to_decimal(row["tipo_recargo"])
        cuota_recargo = _to_decimal(row["cuota_recargo"])
        imp_total = _to_decimal(row["imp_total"])

        total_base += base_imp
        total_iva += cuota_iva
        total_recargo += cuota_recargo
        total_factura += imp_total

        items.append(
            {
                "fecha_fra": row["fecha_fra"],
                "num_fra": row["num_fra"],
                "cliente": row.get("cliente", ""),
                "base_imp": base_imp,
                "tipo_iva": tipo_iva,
                "cuota_iva": cuota_iva,
                "tipo_recargo": tipo_recargo,
                "cuota_recargo": cuota_recargo,
                "imp_total": imp_total,
            }
        )

    return {
        "items": items,
        "totals": {
            "total_base": total_base,
            "total_iva": total_iva,
            "total_recargo": total_recargo,
            "total_factura": total_factura,
        },
    }
