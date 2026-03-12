"""
Finance repository – Data access layer for MARIADB_FINAN_DB ledger queries.

Uses the contabilidad pool (get_pool_finan), not the default ventas pool.
"""
from datetime import date
from typing import Any

from ..core.mariadb import execute_query, get_pool_finan

LEDGER_SQL = """
SELECT
    d.FECHA     AS fecha,
    d.CONCEPTO  AS concepto,
    d.IMPORTE   AS importe,
    d.DEBE      AS debe
FROM diario_e d
WHERE
    d.EMPRESA = 1
    AND d.DIARIO = '00'
    AND d.NCUENTA = %(cta_contable)s
    AND d.FECHA BETWEEN %(exercise_start_date)s AND %(end_date)s
ORDER BY
    d.FECHA ASC,
    d.ASIENTO ASC,
    d.APUNTE ASC
"""


async def fetch_ledger_entries(
    cta_contable: str,
    exercise_start_date: date,
    start_date: date,
    end_date: date,
) -> list[dict[str, Any]]:
    """
    Fetch ledger movements for a customer from MARIADB_FINAN_DB.

    Retrieves all movements from exercise_start_date through end_date so the
    service layer can compute the correct opening balance for start_date entries.

    Raw row keys (stable lowercase aliases): fecha, concepto, importe, debe

    Note: start_date is not used in the SQL – filtering to the visible range is
    intentionally left to the service layer so it can accumulate the running saldo
    from exercise_start_date before the client's requested window begins.

    Args:
        cta_contable: Customer accounting account code (from customer_profiles)
        exercise_start_date: Jan 1 of the fiscal year (first date fetched)
        start_date: First visible date (used by service layer for filtering)
        end_date: Last date of the requested range (inclusive, used in SQL)

    Returns:
        List of raw ledger entry dicts with lowercase keys.
    """
    pool = await get_pool_finan()
    return await execute_query(
        LEDGER_SQL,
        {
            "cta_contable": cta_contable,
            "exercise_start_date": exercise_start_date,
            "end_date": end_date,
        },
        pool=pool,
    )
