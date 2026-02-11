"""
Invoice repository - Data access layer for invoice queries.
"""
from typing import Any

from ..core.mariadb import execute_query

INVOICES_SQL = """
SELECT
  CONCAT(c.documento_factura, '-', c.numero_factura) AS factura,
  MAX(c.fecha_factura) AS fecha,
  MAX(p.imp_base) AS base_imponible,
  MAX(p.imp_iva) AS importe_iva,
  MAX(p.imp_total) AS importe_total
FROM cab_venta c
INNER JOIN pie_venta_e p ON
  c.ejercicio_factura = p.ejercicio AND
  c.clave_factura = p.clave AND
  c.documento_factura = p.documento AND
  c.serie_factura = p.serie AND
  c.numero_factura = p.numero
WHERE
  c.ejercicio_factura IN (%(ejercicio_actual)s, %(ejercicio_anterior)s)
  AND c.clave_factura = 'B'
  AND c.documento_factura NOT LIKE 'J%%'
  AND c.clt_prov = %(clt_prov)s
GROUP BY
  c.documento_factura,
  c.numero_factura
ORDER BY
  fecha DESC,
  factura ASC
LIMIT %(limit)s OFFSET %(offset)s
"""


async def list_invoices(
    clt_prov: str,
    ejercicio_actual: int,
    ejercicio_anterior: int,
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    """
    Fetch invoices for a customer from MariaDB.

    Args:
        clt_prov: Customer code from ERP
        ejercicio_actual: Current fiscal year
        ejercicio_anterior: Previous fiscal year
        limit: Max rows to return
        offset: Rows to skip

    Returns:
        List of invoice dicts
    """
    params = {
        "ejercicio_actual": ejercicio_actual,
        "ejercicio_anterior": ejercicio_anterior,
        "clt_prov": clt_prov,
        "limit": limit,
        "offset": offset,
    }
    return await execute_query(INVOICES_SQL, params)
