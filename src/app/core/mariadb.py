"""
MariaDB connection pool using asyncmy.

Provides async database access with connection pooling.
"""
import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Any

import asyncmy
from asyncmy.cursors import DictCursor

from .config import settings

logger = logging.getLogger(__name__)

_pool: asyncmy.Pool | None = None


async def get_pool() -> asyncmy.Pool:
    """Get or create the connection pool."""
    global _pool
    if _pool is None:
        logger.info("Creating MariaDB connection pool")
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


async def close_pool() -> None:
    """Close the connection pool."""
    global _pool
    if _pool is not None:
        _pool.close()
        await _pool.wait_closed()
        _pool = None
        logger.info("MariaDB connection pool closed")


@asynccontextmanager
async def get_connection() -> AsyncGenerator[asyncmy.Connection, None]:
    """Get a connection from the pool."""
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


async def execute_query(query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """
    Execute a SELECT query and return results as list of dicts.

    Args:
        query: SQL query with named parameters (e.g., :param_name)
        params: Dictionary of parameters

    Returns:
        List of row dictionaries
    """
    import re

    async with get_connection() as conn:
        async with conn.cursor(DictCursor) as cursor:
            if params:
                # Find all :param_name in order of appearance
                param_pattern = re.compile(r":(\w+)")
                param_names = param_pattern.findall(query)
                # Build values list in order of appearance
                param_values = [params[name] for name in param_names]
                # Replace :name with %s
                converted_query = param_pattern.sub("%s", query)
                await cursor.execute(converted_query, param_values)
            else:
                await cursor.execute(query)
            rows = await cursor.fetchall()
            return list(rows)
