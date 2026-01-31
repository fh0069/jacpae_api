from fastapi import APIRouter, Depends
from pydantic import BaseModel
from starlette.responses import JSONResponse
import httpx

from ..core.config import Settings

class HealthResponse(BaseModel):
    status: str = "ok"

router = APIRouter()

@router.get("/health", response_model=HealthResponse, tags=["health"])
async def health():
    return HealthResponse()


@router.get("/health/ready", tags=["health"])
async def health_ready(settings: Settings = Depends(Settings)):
    """Readiness check: optionally verifies JWKS endpoint with a short timeout.

    - Public endpoint
    - If SUPABASE_JWKS_URL is not configured we return 200 and mark jwks as skipped
    - If configured, attempt to fetch with short timeout; on failure return 503 with controlled detail
    """
    checks = {}
    if not settings.supabase_jwks_url:
        checks["jwks"] = "skipped"
        return {"status": "ok", "checks": checks}

    timeout = float(settings.jwks_ready_timeout or 2)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(settings.supabase_jwks_url)
            r.raise_for_status()
        checks["jwks"] = "ok"
        return {"status": "ok", "checks": checks}
    except Exception:
        # Controlled failure information (no URLs/secrets)
        checks["jwks"] = "unreachable"
        return JSONResponse(status_code=503, content={"status": "fail", "checks": checks, "detail": "JWKS unreachable"})
