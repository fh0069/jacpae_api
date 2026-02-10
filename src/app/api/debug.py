"""
DEBUG endpoints - ONLY available when APP_ENV=development.

These endpoints are TEMPORARY and will be removed after testing.
"""
from fastapi import APIRouter, HTTPException, Query

from ..core.config import settings
from ..core.supabase_admin import fetch_customer_profile

router = APIRouter(prefix="/debug", tags=["debug"])


@router.get("/customer-profile")
async def get_customer_profile(user_id: str = Query(..., description="UUID of user")):
    """
    TEMPORARY DEBUG ENDPOINT - Fetch customer_profile by user_id.

    Only available in development mode.
    """
    if settings.app_env != "development":
        raise HTTPException(status_code=404, detail="Not found")

    profile = await fetch_customer_profile(user_id)

    if profile is None:
        return {"found": False, "user_id": user_id}

    return {
        "found": True,
        "user_id": user_id,
        "erp_clt_prov": profile.erp_clt_prov,
        "is_active": profile.is_active,
    }
