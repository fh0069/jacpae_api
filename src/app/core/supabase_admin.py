"""
Supabase Admin Client - Uses SERVICE_ROLE_KEY to query customer_profiles.

SECURITY: This module uses SUPABASE_SERVICE_ROLE_KEY which bypasses RLS.
           NEVER expose this key in logs, responses, or client-side code.
"""
import logging
from typing import Optional
from dataclasses import dataclass

import httpx

from .config import settings

logger = logging.getLogger(__name__)


class SupabaseUnavailableError(Exception):
    """Raised when Supabase service is unavailable (5xx, timeout, network error)."""
    pass


@dataclass
class CustomerProfile:
    erp_clt_prov: str
    is_active: bool


async def fetch_customer_profile(user_id: str) -> Optional[CustomerProfile]:
    """
    Fetch customer profile from Supabase using SERVICE_ROLE_KEY.

    Args:
        user_id: UUID from JWT 'sub' claim

    Returns:
        CustomerProfile if found, None otherwise
    """
    if not settings.supabase_url or settings.supabase_service_role_key is None:
        logger.warning("Supabase admin configuration missing")
        return None

    key = settings.supabase_service_role_key.get_secret_value()

    url = f"{settings.supabase_url}/rest/v1/customer_profiles"
    params = {
        "user_id": f"eq.{user_id}",
        "select": "erp_clt_prov,is_active",
    }
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(url, params=params, headers=headers)
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
