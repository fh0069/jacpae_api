"""
Devices API – Registration of push notification devices.

Security flow:
1. Validate JWT → get user_id (sub claim)
2. Call push_service.register_device → upsert in Supabase push_devices

The user_id is always taken from the JWT; it is never accepted as a client parameter.
"""
import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..core.auth import get_current_user, User
from ..core.supabase_admin import SupabaseUnavailableError
from ..services.push_service import register_device

logger = logging.getLogger(__name__)

router = APIRouter(tags=["devices"])


# ── Schemas ────────────────────────────────────────────────────

class DeviceRegisterRequest(BaseModel):
    device_token: str
    platform: Literal["android", "ios"]


class DeviceRegisterResponse(BaseModel):
    status: str


# ── Endpoint ───────────────────────────────────────────────────

@router.post("/devices/register", response_model=DeviceRegisterResponse)
async def post_register_device(
    body: DeviceRegisterRequest,
    current_user: User = Depends(get_current_user),
) -> DeviceRegisterResponse:
    """
    Register or reactivate a push notification device.

    - Requires valid Supabase JWT.
    - If the device_token is new, a new row is inserted (is_active=True).
    - If the device_token already exists, the row is updated with the current
      user_id and is_active=True (covers reinstall, user change, reactivation).
    - platform must be 'android' or 'ios'.
    """
    try:
        await register_device(
            user_id=current_user.sub,
            device_token=body.device_token,
            platform=body.platform,
        )
    except SupabaseUnavailableError:
        raise HTTPException(status_code=503, detail="Upstream service unavailable")
    except Exception as e:
        logger.error("Error registering device: %s", type(e).__name__)
        raise HTTPException(status_code=500, detail="Error registering device")

    return DeviceRegisterResponse(status="registered")
