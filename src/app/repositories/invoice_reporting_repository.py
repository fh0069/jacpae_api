"""
Invoice Reporting repository – Data access layer for fiscal/VAT invoice queries.

Uses the contabilidad pool (get_pool_finan) — MARIADB_FINAN_DB query.
The customer identifier in iva_e is CLI_PRO, which maps to
customer_profiles.cta_contable (confirmed).
"""
from datetime import date
from typing import Any

from ..core.mariadb import execute_query, get_pool_finan

VAT_LIST_SQL = """
SELECT
    i.FECHA         AS fecha_fra,
    i.NUM_FACTURA   AS num_fra,
    i.CONCEPTO      AS cliente,
    i.BASE          AS base_imp,
    t.TIPO_IVA      AS tipo_iva,
    i.CUOTA         AS cuota_iva,
    t.TIPO_RECARGO  AS tipo_recargo,
    i.CUOTAREC      AS cuota_recargo,
    (i.BASE + i.CUOTA + i.CUOTAREC) AS imp_total
FROM iva_e i
INNER JOIN tipo_iva t ON i.TIPO = t.CODIGO
WHERE
    i.EMPRESA = 1
    AND i.SOP_REP = 1
    AND i.CLI_PRO = %(cta_contable)s
    AND i.FECHA BETWEEN %(start_date)s AND %(end_date)s
ORDER BY
    i.FECHA ASC,
    i.NUM_FACTURA ASC
"""


async def fetch_vat_invoices(
    cta_contable: str,
    start_date: date,
    end_date: date,
) -> list[dict[str, Any]]:
    """
    Fetch the VAT invoice list for a customer from MARIADB_FINAN_DB.

    Joins iva_e with tipo_iva to include IVA and recargo rates alongside amounts.
    Fixed filters: EMPRESA=1, SOP_REP=1 (facturas emitidas/IVA repercutido).

    Raw row keys (stable lowercase aliases):
      fecha_fra, num_fra, base_imp, tipo_iva, cuota_iva,
      tipo_recargo, cuota_recargo, imp_total

    Args:
        cta_contable: Customer accounting account code (iva_e.CLI_PRO).
                      Resolved server-side from customer_profiles; never from client.
        start_date: Start of the fiscal date range (inclusive)
        end_date: End of the fiscal date range (inclusive)

    Returns:
        List of raw VAT invoice dicts with lowercase keys.
    """
    pool = await get_pool_finan()
    return await execute_query(
        VAT_LIST_SQL,
        {
            "cta_contable": cta_contable,
            "start_date": start_date,
            "end_date": end_date,
        },
        pool=pool,
    )
