"""
Invoice Reporting repository – Data access layer for fiscal/VAT invoice queries.

Uses the contabilidad pool (get_pool_finan), same as finance_repository,
because the VAT invoice list is a MARIADB_FINAN_DB query.

SQL is intentionally absent: column and table names for the listado fiscal
must be confirmed against the MARIADB_FINAN_DB schema before writing queries.

Note: the identifier passed to MARIADB_FINAN_DB (erp_clt_prov, cta_contable, or other)
is not yet confirmed and must be resolved when the SQL is implemented.
"""
from datetime import date
from typing import Any

from ..core.mariadb import execute_query, get_pool_finan


async def fetch_vat_invoices(
    clt_prov: str,
    start_date: date,
    end_date: date,
) -> list[dict[str, Any]]:
    """
    Fetch the VAT invoice list for a customer from MARIADB_FINAN_DB.

    Expected keys in each returned dict:
      num_fra, fecha_fra, base_imp, iva, imp_total

    Args:
        clt_prov: Customer ERP code passed from the service layer.
                  The exact MARIADB_FINAN_DB identifier (clt_prov, cta_contable, or other)
                  must be confirmed when SQL is implemented.
        start_date: Start of the fiscal date range (inclusive)
        end_date: End of the fiscal date range (inclusive)

    Returns:
        List of raw VAT invoice dicts.

    Raises:
        NotImplementedError: SQL implementation pending – table/column names TBD.
    """
    raise NotImplementedError(
        "VAT invoice list SQL not yet implemented – table, column names, and "
        "the correct MARIADB_FINAN_DB customer identifier must be confirmed before writing queries."
    )

    # Skeleton – do not remove; shows intended usage of the finan pool:
    # pool = await get_pool_finan()
    # return await execute_query(VAT_LIST_SQL, {...}, pool=pool)
