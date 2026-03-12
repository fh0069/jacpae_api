"""
Invoice Reporting service – Business logic for fiscal/VAT invoice list.

Responsibility:
  - Orchestrate repository calls for the listado fiscal
  - Optionally compute aggregated totals (VatTotals) if repository returns them
  - Return a dict ready to be serialised as VatInvoiceListResponse by the API layer

This layer does NOT know about HTTP or Pydantic – it receives plain Python
types and returns plain dicts.
"""
import logging
from datetime import date
from typing import Any

from ..repositories.invoice_reporting_repository import fetch_vat_invoices

logger = logging.getLogger(__name__)


async def get_vat_invoice_list(
    clt_prov: str,
    start_date: date,
    end_date: date,
) -> dict[str, Any]:
    """
    Retrieve the VAT invoice list for a customer within [start_date, end_date].

    Args:
        clt_prov: Customer ERP code (never from client – resolved in API layer)
        start_date: Start of the fiscal date range (inclusive)
        end_date: End of the fiscal date range (inclusive)

    Returns:
        Dict matching the VatInvoiceListResponse schema:
          {start_date, end_date, total_items, items, totals}
        totals is None until the repository implementation computes them.

    Raises:
        NotImplementedError: SQL implementation is pending (table/column names TBD).
    """
    rows = await fetch_vat_invoices(
        clt_prov=clt_prov,
        start_date=start_date,
        end_date=end_date,
    )

    # TODO: build VatTotals once SQL is implemented
    items = [
        {
            "num_fra": row["num_fra"],
            "fecha_fra": row["fecha_fra"],
            "base_imp": row["base_imp"],
            "iva": row["iva"],
            "imp_total": row["imp_total"],
        }
        for row in rows
    ]

    return {
        "start_date": start_date,
        "end_date": end_date,
        "total_items": len(items),
        "items": items,
        "totals": None,
    }
