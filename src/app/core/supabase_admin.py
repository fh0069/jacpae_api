"""
Supabase Admin Client - Uses SERVICE_ROLE_KEY to query customer_profiles
and manage notifications.

SECURITY: This module uses SUPABASE_SERVICE_ROLE_KEY which bypasses RLS.
           NEVER expose this key in logs, responses, or client-side code.
"""
import logging
from datetime import date, datetime, timezone
from typing import Any, Optional
from dataclasses import dataclass

import httpx
from pydantic import BaseModel

from .config import settings

logger = logging.getLogger(__name__)


class SupabaseUnavailableError(Exception):
    """Raised when Supabase service is unavailable (5xx, timeout, network error)."""
    pass


# ── Models ────────────────────────────────────────────────────

@dataclass
class CustomerProfile:
    erp_clt_prov: str
    is_active: bool


@dataclass
class CustomerProfileGiro:
    user_id: str
    cta_contable: str
    dias_aviso_giro: Optional[int]


@dataclass
class NotificationInsert:
    user_id: str
    type: str
    title: str
    body: str
    event_date: date
    data: dict[str, Any]
    source_key: str


class Notification(BaseModel):
    id: str
    type: str
    title: str
    body: Optional[str] = None
    data: Optional[dict[str, Any]] = None
    read_at: Optional[datetime] = None
    created_at: datetime


# ── Internal helpers ──────────────────────────────────────────

def _get_headers() -> dict[str, str]:
    """Build auth headers for Supabase service-role requests."""
    key = settings.supabase_service_role_key.get_secret_value()
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
    }


def _check_config() -> bool:
    """Return True if Supabase admin config is present."""
    if not settings.supabase_url or settings.supabase_service_role_key is None:
        logger.warning("Supabase admin configuration missing")
        return False
    return True


# ── Existing: single profile lookup ──────────────────────────

async def fetch_customer_profile(user_id: str) -> Optional[CustomerProfile]:
    """
    Fetch customer profile from Supabase using SERVICE_ROLE_KEY.

    Args:
        user_id: UUID from JWT 'sub' claim

    Returns:
        CustomerProfile if found, None otherwise
    """
    if not _check_config():
        return None

    url = f"{settings.supabase_url}/rest/v1/customer_profiles"
    params = {
        "user_id": f"eq.{user_id}",
        "select": "erp_clt_prov,is_active",
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(url, params=params, headers=_get_headers())
            response.raise_for_status()
            data = response.json()

            if not data or len(data) == 0:
                logger.debug("No customer_profile found for user_id=%s", user_id)
                return None

            row = data[0]
            return CustomerProfile(
                erp_clt_prov=row.get("erp_clt_prov"),
                is_active=row.get("is_active", False),
            )

    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        logger.error("Supabase API error: %s", status)
        if status >= 500:
            raise SupabaseUnavailableError(f"Supabase returned {status}")
        return None
    except (httpx.TimeoutException, httpx.RequestError) as e:
        logger.error("Supabase unavailable: %s", type(e).__name__)
        raise SupabaseUnavailableError("Supabase request failed")


# ── Giro job helpers ──────────────────────────────────────────

async def fetch_giro_profiles() -> list[CustomerProfileGiro]:
    """
    Fetch all customer profiles that have giro notifications enabled.

    Filters: is_active=true, avisar_giro=true, cta_contable not null.
    """
    if not _check_config():
        return []

    url = f"{settings.supabase_url}/rest/v1/customer_profiles"
    params = {
        "select": "user_id,cta_contable,dias_aviso_giro",
        "is_active": "eq.true",
        "avisar_giro": "eq.true",
        "cta_contable": "not.is.null",
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(url, params=params, headers=_get_headers())
            response.raise_for_status()
            data = response.json()

            return [
                CustomerProfileGiro(
                    user_id=row["user_id"],
                    cta_contable=row["cta_contable"],
                    dias_aviso_giro=row.get("dias_aviso_giro"),
                )
                for row in data
                if row.get("cta_contable")  # skip empty strings
            ]

    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        logger.error("Supabase fetch_giro_profiles error: %s", status)
        if status >= 500:
            raise SupabaseUnavailableError(f"Supabase returned {status}")
        return []
    except (httpx.TimeoutException, httpx.RequestError) as e:
        logger.error("Supabase unavailable (giro_profiles): %s", type(e).__name__)
        raise SupabaseUnavailableError("Supabase request failed")


async def insert_notification(notification: NotificationInsert) -> bool:
    """
    Insert a notification into Supabase. Returns True if inserted,
    False if deduplicated (source_key already exists).

    Raises SupabaseUnavailableError on 5xx / network errors.
    """
    if not _check_config():
        return False

    url = f"{settings.supabase_url}/rest/v1/notifications"
    headers = {
        **_get_headers(),
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }
    payload = {
        "user_id": notification.user_id,
        "type": notification.type,
        "title": notification.title,
        "body": notification.body,
        "event_date": notification.event_date.isoformat(),
        "data": notification.data,
        "source_key": notification.source_key,
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(url, json=payload, headers=headers)

            if response.status_code in (200, 201):
                return True

            # 409 Conflict = unique violation on source_key → deduplicated
            if response.status_code == 409:
                return False

            # PostgREST may return 400 with PGRST code for unique violation
            if response.status_code == 400:
                body = response.text
                if "duplicate" in body.lower() or "unique" in body.lower():
                    return False

            response.raise_for_status()
            return True

    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        logger.error("Supabase insert_notification error: %s", status)
        if status >= 500:
            raise SupabaseUnavailableError(f"Supabase returned {status}")
        return False
    except (httpx.TimeoutException, httpx.RequestError) as e:
        logger.error("Supabase unavailable (insert_notification): %s", type(e).__name__)
        raise SupabaseUnavailableError("Supabase request failed")


# ── Notification read helpers ─────────────────────────────────

async def fetch_notifications(
    user_id: str,
    limit: int = 50,
    offset: int = 0,
) -> list[Notification]:
    """
    Fetch notifications for a user, ordered by created_at DESC.

    Uses SERVICE_ROLE_KEY (bypasses RLS) but filters by user_id server-side.
    """
    if not _check_config():
        return []

    limit = min(max(limit, 1), 100)
    offset = max(offset, 0)

    url = f"{settings.supabase_url}/rest/v1/notifications"
    params = {
        "user_id": f"eq.{user_id}",
        "select": "id,type,title,body,data,read_at,created_at",
        "order": "created_at.desc",
        "limit": str(limit),
        "offset": str(offset),
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(url, params=params, headers=_get_headers())
            response.raise_for_status()
            data = response.json()
            return [Notification(**row) for row in data]

    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        logger.error("Supabase fetch_notifications error: %s", status)
        if status >= 500:
            raise SupabaseUnavailableError(f"Supabase returned {status}")
        return []
    except (httpx.TimeoutException, httpx.RequestError) as e:
        logger.error("Supabase unavailable (fetch_notifications): %s", type(e).__name__)
        raise SupabaseUnavailableError("Supabase request failed")


async def mark_notification_read(user_id: str, notification_id: str) -> bool:
    """
    Mark a notification as read. Returns True if updated, False if not found
    or does not belong to user.

    Uses double filter (id + user_id) for safety.
    """
    if not _check_config():
        return False

    url = f"{settings.supabase_url}/rest/v1/notifications"
    params = {
        "id": f"eq.{notification_id}",
        "user_id": f"eq.{user_id}",
    }
    headers = {
        **_get_headers(),
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }
    payload = {
        "read_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.patch(
                url, params=params, json=payload, headers=headers,
            )
            response.raise_for_status()
            data = response.json()
            return len(data) > 0

    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        logger.error("Supabase mark_notification_read error: %s", status)
        if status >= 500:
            raise SupabaseUnavailableError(f"Supabase returned {status}")
        return False
    except (httpx.TimeoutException, httpx.RequestError) as e:
        logger.error("Supabase unavailable (mark_read): %s", type(e).__name__)
        raise SupabaseUnavailableError("Supabase request failed")
