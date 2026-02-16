"""
MariaDB connection pools using asyncmy.

Two independent pools:
  - ventas (g4):       get_pool()       — used by invoices, existing endpoints
  - contabilidad (g4finan): get_pool_finan() — used by giro notifications job
"""
import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Any

import asyncmy
from asyncmy.cursors import DictCursor

from .config import settings

logger = logging.getLogger(__name__)

# ── Ventas pool (g4) ─────────────────────────────────────────

_pool: asyncmy.Pool | None = None


async def get_pool() -> asyncmy.Pool:
    """Get or create the ventas (g4) connection pool."""
    global _pool
    if _pool is None:
        logger.info("Creating MariaDB pool [ventas] db=%s", settings.mariadb_db)
        _pool = await asyncmy.create_pool(
            host=settings.mariadb_host,
            port=settings.mariadb_port,
            user=settings.mariadb_user,
            password=settings.mariadb_password.get_secret_value(),
            db=settings.mariadb_db,
            minsize=1,
            maxsize=10,
            autocommit=True,
        )
    return _pool


# ── Contabilidad pool (g4finan) ──────────────────────────────

_pool_finan: asyncmy.Pool | None = None


async def get_pool_finan() -> asyncmy.Pool:
    """Get or create the contabilidad (g4finan) connection pool."""
    global _pool_finan
    if _pool_finan is None:
        logger.info("Creating MariaDB pool [finan] db=%s", settings.mariadb_finan_db)
        _pool_finan = await asyncmy.create_pool(
            host=settings.mariadb_host,
            port=settings.mariadb_port,
            user=settings.mariadb_user,
            password=settings.mariadb_password.get_secret_value(),
            db=settings.mariadb_finan_db,
            minsize=1,
            maxsize=5,
            autocommit=True,
        )
    return _pool_finan


# ── Lifecycle ─────────────────────────────────────────────────

async def close_pools() -> None:
    """Close all connection pools."""
    global _pool, _pool_finan
    for name, p in [("ventas", _pool), ("finan", _pool_finan)]:
        if p is not None:
            p.close()
            await p.wait_closed()
            logger.info("MariaDB pool [%s] closed", name)
    _pool = None
    _pool_finan = None


async def close_pool() -> None:
    """Close the ventas pool (backwards compat)."""
    await close_pools()


# ── Helpers ───────────────────────────────────────────────────

@asynccontextmanager
async def get_connection(pool: asyncmy.Pool | None = None) -> AsyncGenerator[asyncmy.Connection, None]:
    """Get a connection from the given pool (defaults to ventas)."""
    if pool is None:
        pool = await get_pool()
    async with pool.acquire() as conn:
        yield conn


async def ping_db() -> bool:
    """Execute SELECT 1 to verify database connectivity."""
    timeout = getattr(settings, "jwks_ready_timeout", 2) or 2

    async def _ping() -> bool:
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("SELECT 1")
                await cursor.fetchone()
        return True

    try:
        return await asyncio.wait_for(_ping(), timeout=float(timeout))
    except (asyncio.TimeoutError, Exception):
        return False


async def execute_query(
    query: str,
    params: dict[str, Any] | None = None,
    pool: asyncmy.Pool | None = None,
) -> list[dict[str, Any]]:
    """
    Execute a SELECT query and return results as list of dicts.

    Args:
        query: SQL query with pyformat parameters (e.g., %(param_name)s)
        params: Dictionary of parameters
        pool: Connection pool to use (defaults to ventas/g4)

    Returns:
        List of row dictionaries
    """
    async with get_connection(pool) as conn:
        async with conn.cursor(DictCursor) as cursor:
            await cursor.execute(query, params or {})
            rows = await cursor.fetchall()
            return list(rows)
