"""
Invoice repository - Data access layer for invoice queries.
"""
from typing import Any

from ..core.mariadb import execute_query

INVOICES_SQL = """
SELECT
  c.ejercicio_factura,
  c.clave_factura,
  c.documento_factura,
  c.serie_factura,
  c.numero_factura,
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
  c.ejercicio_factura,
  c.clave_factura,
  c.documento_factura,
  c.serie_factura,
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


OWNERSHIP_SQL = """
SELECT c.clt_prov
FROM cab_venta c
WHERE c.ejercicio_factura = %(ejercicio)s
  AND c.clave_factura     = %(clave)s
  AND c.documento_factura = %(documento)s
  AND c.serie_factura     = %(serie)s
  AND c.numero_factura    = %(numero)s
LIMIT 1
"""


async def check_invoice_ownership(
    ejercicio: str,
    clave: str,
    documento: str,
    serie: str,
    numero: str,
) -> str | None:
    """
    Return the clt_prov that owns the invoice, or None if it doesn't exist.
    """
    params = {
        "ejercicio": ejercicio,
        "clave": clave,
        "documento": documento,
        "serie": serie,
        "numero": numero,
    }
    rows = await execute_query(OWNERSHIP_SQL, params)
    if not rows:
        return None
    return rows[0]["clt_prov"]
