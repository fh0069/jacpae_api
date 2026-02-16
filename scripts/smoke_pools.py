"""
Smoke test: verify both MariaDB pools can be created.
Run from project root:
    python -m scripts.smoke_pools
"""
import asyncio
import sys
from pathlib import Path

# Ensure src is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from app.core.config import settings
from app.core.mariadb import get_pool, get_pool_finan, close_pools


async def main() -> None:
    print(f"mariadb_db       = {settings.mariadb_db}")
    print(f"mariadb_finan_db = {settings.mariadb_finan_db}")
    print(f"giro_job_enabled = {settings.giro_job_enabled}")

    pool_ventas = await get_pool()
    print(f"Pool ventas OK   — size={pool_ventas.size}")

    pool_finan = await get_pool_finan()
    print(f"Pool finan OK    — size={pool_finan.size}")

    assert pool_ventas is not pool_finan, "Pools must be distinct objects"
    print("Pools are distinct objects ✓")

    await close_pools()
    print("Both pools closed ✓")


if __name__ == "__main__":
    asyncio.run(main())
