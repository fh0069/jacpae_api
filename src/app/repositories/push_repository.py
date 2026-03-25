"""
Push repository – Supabase push_devices table access via SERVICE_ROLE_KEY.

Uses the same httpx + service-role-key pattern as supabase_admin.py.
RLS is bypassed intentionally; all filtering is enforced server-side.
"""
import logging
from datetime import datetime, timezone
from typing import Optional

import httpx

from ..core.config import settings
from ..core.supabase_admin import SupabaseUnavailableError

logger = logging.getLogger(__name__)


def _get_headers() -> dict[str, str]:
    key = settings.supabase_service_role_key.get_secret_value()
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
    }


def _check_config() -> bool:
    if not settings.supabase_url or settings.supabase_service_role_key is None:
        logger.warning("Supabase admin configuration missing")
        return False
    return True


async def get_device_by_token(device_token: str) -> Optional[dict]:
    """
    Fetch a push_devices row by device_token.

    Returns a dict with 'id' and 'user_id', or None if not found.
    Raises SupabaseUnavailableError on 5xx / network errors or missing config.
    """
    if not _check_config():
        raise SupabaseUnavailableError("Supabase admin configuration missing")

    url = f"{settings.supabase_url}/rest/v1/push_devices"
    params = {
        "device_token": f"eq.{device_token}",
        "select": "id,user_id",
        "limit": "1",
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(url, params=params, headers=_get_headers())
            response.raise_for_status()
            data = response.json()
            return data[0] if data else None

    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        logger.error("Supabase get_device_by_token error: %s", status)
        if status >= 500:
            raise SupabaseUnavailableError(f"Supabase returned {status}")
        return None
    except (httpx.TimeoutException, httpx.RequestError) as e:
        logger.error("Supabase unavailable (get_device_by_token): %s", type(e).__name__)
        raise SupabaseUnavailableError("Supabase request failed")


async def insert_device(user_id: str, device_token: str, platform: str) -> None:
    """
    Insert a new push_devices row with is_active=True and all timestamps set to now().

    Raises SupabaseUnavailableError on 5xx / network errors.
    """
    if not _check_config():
        raise SupabaseUnavailableError("Supabase admin configuration missing")

    url = f"{settings.supabase_url}/rest/v1/push_devices"
    now = datetime.now(timezone.utc).isoformat()
    headers = {
        **_get_headers(),
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }
    payload = {
        "user_id": user_id,
        "device_token": device_token,
        "platform": platform,
        "is_active": True,
        "created_at": now,
        "updated_at": now,
        "last_seen_at": now,
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()

    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        logger.error("Supabase insert_device error: %s", status)
        if status >= 500:
            raise SupabaseUnavailableError(f"Supabase returned {status}")
    except (httpx.TimeoutException, httpx.RequestError) as e:
        logger.error("Supabase unavailable (insert_device): %s", type(e).__name__)
        raise SupabaseUnavailableError("Supabase request failed")


async def update_device(device_id: str, user_id: str) -> None:
    """
    Update an existing push_devices row: set user_id, is_active=True,
    updated_at and last_seen_at to now().

    Covers reinstall, user change, and reactivation cases.
    Raises SupabaseUnavailableError on 5xx / network errors.
    """
    if not _check_config():
        raise SupabaseUnavailableError("Supabase admin configuration missing")

    url = f"{settings.supabase_url}/rest/v1/push_devices"
    now = datetime.now(timezone.utc).isoformat()
    params = {"id": f"eq.{device_id}"}
    headers = {
        **_get_headers(),
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }
    payload = {
        "user_id": user_id,
        "is_active": True,
        "updated_at": now,
        "last_seen_at": now,
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.patch(url, params=params, json=payload, headers=headers)
            response.raise_for_status()

    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        logger.error("Supabase update_device error: %s", status)
        if status >= 500:
            raise SupabaseUnavailableError(f"Supabase returned {status}")
    except (httpx.TimeoutException, httpx.RequestError) as e:
        logger.error("Supabase unavailable (update_device): %s", type(e).__name__)
        raise SupabaseUnavailableError("Supabase request failed")


async def fetch_active_devices_by_user_id(user_id: str) -> list[dict]:
    """
    Return list of {"device_token": str} dicts for active devices of a user.

    Returns an empty list if the user has no active devices.
    Raises SupabaseUnavailableError on 5xx / network error / missing config.

    Supabase REST:
      GET /rest/v1/push_devices
      params: user_id=eq.{user_id}, is_active=eq.true, select=device_token
    """
    if not _check_config():
        raise SupabaseUnavailableError("Supabase admin configuration missing")

    url = f"{settings.supabase_url}/rest/v1/push_devices"
    params = {
        "user_id": f"eq.{user_id}",
        "is_active": "eq.true",
        "select": "device_token",
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(url, params=params, headers=_get_headers())
            response.raise_for_status()
            return response.json()

    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        logger.error("Supabase fetch_active_devices_by_user_id error: %s", status)
        if status >= 500:
            raise SupabaseUnavailableError(f"Supabase returned {status}")
        return []
    except (httpx.TimeoutException, httpx.RequestError) as e:
        logger.error(
            "Supabase unavailable (fetch_active_devices_by_user_id): %s",
            type(e).__name__,
        )
        raise SupabaseUnavailableError("Supabase request failed")


async def deactivate_device_by_token(device_token: str) -> None:
    """
    Set is_active=False for the given device_token. Row is preserved.

    Preserves the row for auditability (history of invalid tokens).
    Updates updated_at to now(). Does NOT delete the row.
    Raises SupabaseUnavailableError on 5xx / network error.

    Supabase REST:
      PATCH /rest/v1/push_devices
      params: device_token=eq.{device_token}
      body: {is_active: false, updated_at: <ISO now>}
      headers: Prefer: return=minimal
    """
    if not _check_config():
        raise SupabaseUnavailableError("Supabase admin configuration missing")

    url = f"{settings.supabase_url}/rest/v1/push_devices"
    now = datetime.now(timezone.utc).isoformat()
    params = {"device_token": f"eq.{device_token}"}
    headers = {
        **_get_headers(),
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }
    payload = {
        "is_active": False,
        "updated_at": now,
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.patch(
                url, params=params, json=payload, headers=headers
            )
            response.raise_for_status()

    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        logger.error("Supabase deactivate_device_by_token error: %s", status)
        if status >= 500:
            raise SupabaseUnavailableError(f"Supabase returned {status}")
    except (httpx.TimeoutException, httpx.RequestError) as e:
        logger.error(
            "Supabase unavailable (deactivate_device_by_token): %s",
            type(e).__name__,
        )
        raise SupabaseUnavailableError("Supabase request failed")
