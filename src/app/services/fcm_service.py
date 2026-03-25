"""
FCM push notification sender.

Uses FCM HTTP v1 API with OAuth2 service account authentication via google-auth.
Token refresh is delegated to google-auth, wrapped with asyncio.to_thread() for
async compatibility. httpx handles all FCM API calls.

Architecture:
  - Credentials loaded once from firebase_credentials_path (lazy, on first call)
  - Access token cached at module level; refreshed when google-auth marks it invalid
  - send_push_to_user() never raises — all failures captured in PushResult
  - Tokens confirmed invalid by FCM are deactivated in push_devices (not deleted)

SECURITY: credentials file path never logged after startup check.
          Access token never logged or returned to callers.
          device_token logged only as 8-char prefix for diagnostics.
"""
import asyncio
import logging
from dataclasses import dataclass

import httpx
from google.auth.transport.requests import Request
from google.oauth2 import service_account

from ..core.config import settings
from ..core.supabase_admin import SupabaseUnavailableError
from ..repositories.push_repository import (
    deactivate_device_by_token,
    fetch_active_devices_by_user_id,
)

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────

_FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
_FCM_SEND_URL = "https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"

# FCM errorCodes that confirm a token is permanently invalid → deactivate
_INVALIDATING_ERROR_CODES = frozenset({"UNREGISTERED", "INVALID_ARGUMENT"})

# ── Module-level state ────────────────────────────────────────

_credentials: service_account.Credentials | None = None
_creds_lock: asyncio.Lock = asyncio.Lock()
_fcm_warning_emitted: bool = False


# ── Data model ────────────────────────────────────────────────

@dataclass
class PushResult:
    tokens_queried: int = 0
    sent: int = 0
    failed: int = 0        # transient or unrecognized FCM errors
    invalidated: int = 0   # tokens confirmed invalid by FCM, deactivated in DB


# ── Internal helpers ──────────────────────────────────────────

def _is_fcm_configured() -> bool:
    """
    Return True if both firebase_credentials_path and firebase_project_id are set.
    Emits a single WARNING if not configured (suppressed on subsequent calls).
    """
    global _fcm_warning_emitted
    configured = bool(
        settings.firebase_credentials_path and settings.firebase_project_id
    )
    if not configured and not _fcm_warning_emitted:
        logger.warning(
            "FCM disabled: FIREBASE_CREDENTIALS_PATH or FIREBASE_PROJECT_ID not set"
        )
        _fcm_warning_emitted = True
    return configured


def _get_credentials() -> service_account.Credentials:
    """
    Load service account credentials from firebase_credentials_path.
    Synchronous — called inside asyncio.to_thread() from _get_access_token().

    Raises: FileNotFoundError if the path does not exist.
            ValueError if the JSON is invalid or missing required fields.
    """
    return service_account.Credentials.from_service_account_file(
        settings.firebase_credentials_path,
        scopes=[_FCM_SCOPE],
    )


async def _get_access_token() -> str:
    """
    Return a valid FCM OAuth2 access token.

    Lazy-loads credentials on first call. Refreshes when credentials.valid is
    False (google-auth handles expiry + safety buffer internally).

    asyncio.Lock with double-check prevents concurrent refresh races.
    asyncio.to_thread() prevents blocking the event loop during the HTTP
    token exchange (~200 ms; happens at most once per hour).

    Raises: Exception on FileNotFoundError, network error, or invalid credentials.
            NOT caught here — caller (send_push_to_user) handles all exceptions.
    """
    global _credentials

    # Fast path: valid credentials already loaded
    if _credentials is not None and _credentials.valid:
        return _credentials.token

    async with _creds_lock:
        # Double-check after acquiring lock
        if _credentials is not None and _credentials.valid:
            return _credentials.token

        if _credentials is None:
            _credentials = await asyncio.to_thread(_get_credentials)

        if not _credentials.valid:
            request = Request()
            await asyncio.to_thread(_credentials.refresh, request)

        return _credentials.token


def _parse_fcm_error_code(body: dict, status_code: int) -> str:
    """
    Extract FCM error code from response body. Never raises.

    Priority order:
      1. body["error"]["details"][0]["errorCode"]  — most specific FCM code
      2. body["error"]["status"]                   — HTTP-level status string
      3. status_code == 404                        — infer UNREGISTERED
      4. ""                                        — unknown / unrecognized

    Conservative: callers treat "" as failed (not invalidated) so that
    a token is only deactivated when FCM explicitly confirms it is invalid.
    """
    try:
        details = body.get("error", {}).get("details", [])
        if details:
            code = details[0].get("errorCode", "")
            if code:
                return code
    except Exception:
        pass

    try:
        status = body.get("error", {}).get("status", "")
        if status:
            return status
    except Exception:
        pass

    if status_code == 404:
        return "UNREGISTERED"

    return ""


async def _send_to_token(
    access_token: str,
    project_id: str,
    device_token: str,
    title: str,
    body: str,
    data: dict[str, str],
) -> tuple[bool, bool]:
    """
    Send one FCM message to one device token via FCM HTTP v1 API.

    Returns: (sent: bool, should_deactivate: bool)
      (True,  False) → 200 OK — message delivered
      (False, True)  → FCM confirmed token is invalid → caller should deactivate
      (False, False) → transient or unrecognized error → do not deactivate

    Conservative default: if error code is empty or unrecognized → (False, False).
    A token is only marked for deactivation when FCM confirms it is invalid.

    Never raises.
    """
    url = _FCM_SEND_URL.format(project_id=project_id)
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    payload = {
        "message": {
            "token": device_token,
            "notification": {
                "title": title,
                "body": body,
            },
            "data": data,
        }
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(url, json=payload, headers=headers)

        if response.status_code == 200:
            return True, False

        try:
            body_json = response.json()
        except Exception:
            body_json = {}

        error_code = _parse_fcm_error_code(body_json, response.status_code)

        if error_code in _INVALIDATING_ERROR_CODES:
            logger.info(
                "FCM: token invalidated (code=%s) prefix=%s...",
                error_code,
                device_token[:8],
            )
            return False, True

        logger.warning(
            "FCM: transient error code=%s status=%d prefix=%s...",
            error_code or "(unknown)",
            response.status_code,
            device_token[:8],
        )
        return False, False

    except (httpx.TimeoutException, httpx.RequestError) as exc:
        logger.error(
            "FCM: network error for prefix=%s...: %s",
            device_token[:8],
            type(exc).__name__,
        )
        return False, False


# ── Public API ────────────────────────────────────────────────

async def send_push_to_user(
    user_id: str,
    title: str,
    body: str,
    data: dict[str, str],
) -> PushResult:
    """
    Send FCM push notification to all active devices of a user.

    Never raises. All failures are captured in PushResult.

    Args:
        user_id: Target user UUID (from JWT)
        title:   Push title shown on device
        body:    Push body (may be empty string)
        data:    Extra payload — ALL values MUST be strings (FCM v1 requirement).
                 MVP: {"type": "giro"} | {"type": "reparto"} | {"type": "oferta"}

    Returns:
        PushResult(tokens_queried, sent, failed, invalidated)
        - sent:        tokens reached successfully
        - failed:      transient or unrecognized FCM errors (not token invalidity)
        - invalidated: tokens confirmed invalid by FCM, deactivated in push_devices
    """
    result = PushResult()

    if not _is_fcm_configured():
        return result

    # Fetch active device tokens for this user
    try:
        devices = await fetch_active_devices_by_user_id(user_id)
    except SupabaseUnavailableError:
        logger.error(
            "FCM: Supabase unavailable fetching devices for user_id=%s", user_id
        )
        result.failed = 1
        return result

    result.tokens_queried = len(devices)

    if not devices:
        logger.debug("FCM: no active devices for user_id=%s", user_id)
        return result

    # Obtain access token (cached, refreshed lazily by google-auth)
    try:
        access_token = await _get_access_token()
    except Exception:
        logger.exception("FCM: failed to obtain access token")
        result.failed = len(devices)
        return result

    project_id = settings.firebase_project_id

    for device in devices:
        token = device["device_token"]
        sent, should_deactivate = await _send_to_token(
            access_token, project_id, token, title, body, data
        )

        if sent:
            result.sent += 1
        elif should_deactivate:
            result.invalidated += 1
            try:
                await deactivate_device_by_token(token)
            except Exception:
                logger.warning(
                    "FCM: could not deactivate token for user_id=%s", user_id
                )
        else:
            result.failed += 1

    logger.info(
        "FCM send: user_id=%s tokens=%d sent=%d failed=%d invalidated=%d",
        user_id,
        result.tokens_queried,
        result.sent,
        result.failed,
        result.invalidated,
    )

    return result
