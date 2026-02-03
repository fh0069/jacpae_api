import logging

from fastapi import APIRouter
from pydantic import BaseModel
from starlette.responses import JSONResponse
import httpx

from ..core.config import settings
from ..core.mariadb import ping_db

logger = logging.getLogger(__name__)


class HealthResponse(BaseModel):
    status: str = "ok"


router = APIRouter()


@router.get("/health", response_model=HealthResponse, tags=["health"])
async def health():
    """Liveness check: always returns 200 without external calls."""
    return HealthResponse()


@router.get("/health/ready", tags=["health"])
async def health_ready():
    """Readiness check: verifies DB and optionally JWKS endpoint.

    - Public endpoint
    - DB: executes SELECT 1 to verify connectivity
    - JWKS: if SUPABASE_JWKS_URL is configured, fetches with short timeout
    - Returns 200 if all required checks pass, 503 otherwise
    """
    checks: dict[str, str] = {}
    all_ok = True

    # Check DB
    db_ok = await ping_db()
    if db_ok:
        checks["db"] = "ok"
    else:
        checks["db"] = "unreachable"
        all_ok = False
        logger.warning("Readiness check failed: DB unreachable")

    # Check JWKS
    if not settings.supabase_jwks_url:
        checks["jwks"] = "skipped"
    else:
        timeout = float(settings.jwks_ready_timeout or 2)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.get(settings.supabase_jwks_url)
                r.raise_for_status()
            checks["jwks"] = "ok"
        except (httpx.TimeoutException, httpx.RequestError, httpx.HTTPStatusError):
            checks["jwks"] = "unreachable"
            all_ok = False
            logger.warning("Readiness check failed: JWKS unreachable")

    if all_ok:
        logger.info("Readiness check passed")
        return {"status": "ok", "checks": checks}
    else:
        return JSONResponse(
            status_code=503,
            content={"status": "fail", "checks": checks, "detail": "Dependency check failed"},
        )
