"""
Reparto repository - Data access layer for scheduled route queries.

Reads from MariaDB gestión (g4) via the default ventas pool.
"""
from datetime import date
from typing import Any

from ..core.mariadb import execute_query, get_pool

REPARTOS_BY_CLIENT_SQL = """
SELECT
  c.codigo       AS clt_prov,
  r.fecha,
  l.ruta,
  l.subruta,
  l.grupo,
  l.subgrupo
FROM cliente c
INNER JOIN lin_rutas_grupo l
  ON c.grupo = l.grupo AND c.subgrupo = l.subgrupo
INNER JOIN rutas_programacion r
  ON l.ruta = r.ruta AND l.subruta = r.subruta
WHERE
  c.baja_comercial = 'N'
  AND c.codigo = %(clt_prov)s
  AND r.fecha  = %(target_date)s
ORDER BY r.fecha ASC, c.codigo ASC, l.ruta ASC, l.subruta ASC
"""


async def fetch_repartos_by_client(
    clt_prov: str,
    target_date: date,
) -> list[dict[str, Any]]:
    """
    Fetch scheduled routes for a single client on a specific date.

    Args:
        clt_prov: Customer code (e.g. '000962')
        target_date: Target date to check for routes

    Returns:
        List of dicts with keys: clt_prov, fecha, ruta, subruta, grupo, subgrupo
    """
    pool = await get_pool()
    return await execute_query(
        REPARTOS_BY_CLIENT_SQL,
        {"clt_prov": clt_prov, "target_date": target_date},
        pool=pool,
    )
