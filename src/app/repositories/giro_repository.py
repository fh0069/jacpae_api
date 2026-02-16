"""
Giro repository - Data access layer for upcoming giro/vencimiento queries.

Reads from MariaDB contabilidad (g4finan) via the finan pool.
"""
from datetime import date
from typing import Any

from ..core.mariadb import execute_query, get_pool_finan

GIROS_BY_CTA_SQL = """
SELECT
  cli_pro   AS cta_contable,
  num_efecto,
  vencimiento,
  importe
FROM efectos_e
WHERE
  empresa    = 1
  AND giro_rec   = 0
  AND cobro_pago = 1
  AND (num_efecto LIKE 'R%%' OR num_efecto LIKE 'S%%')
  AND cli_pro = %(cta_contable)s
  AND vencimiento BETWEEN %(from_date)s AND %(to_date)s
ORDER BY vencimiento ASC, num_efecto ASC
"""

GIROS_WINDOW_SQL = """
SELECT
  cli_pro   AS cta_contable,
  num_efecto,
  vencimiento,
  importe
FROM efectos_e
WHERE
  empresa    = 1
  AND giro_rec   = 0
  AND cobro_pago = 1
  AND (num_efecto LIKE 'R%%' OR num_efecto LIKE 'S%%')
  AND vencimiento BETWEEN %(from_date)s AND %(to_date)s
ORDER BY vencimiento ASC, num_efecto ASC
"""


async def fetch_giros_by_cta_contable(
    cta_contable: str,
    from_date: date,
    to_date: date,
) -> list[dict[str, Any]]:
    """
    Fetch upcoming giros for a single cuenta contable.

    Args:
        cta_contable: Account code (e.g. '430000962')
        from_date: Start of window (inclusive)
        to_date: End of window (inclusive)

    Returns:
        List of dicts with keys: cta_contable, num_efecto, vencimiento, importe
    """
    pool = await get_pool_finan()
    return await execute_query(
        GIROS_BY_CTA_SQL,
        {"cta_contable": cta_contable, "from_date": from_date, "to_date": to_date},
        pool=pool,
    )


async def fetch_giros_window(
    from_date: date,
    to_date: date,
) -> list[dict[str, Any]]:
    """
    Fetch all upcoming giros in a date window (all accounts).

    Useful for batch notification generation.

    Args:
        from_date: Start of window (inclusive)
        to_date: End of window (inclusive)

    Returns:
        List of dicts with keys: cta_contable, num_efecto, vencimiento, importe
    """
    pool = await get_pool_finan()
    return await execute_query(
        GIROS_WINDOW_SQL,
        {"from_date": from_date, "to_date": to_date},
        pool=pool,
    )
