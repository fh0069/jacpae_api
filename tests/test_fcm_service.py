"""Tests for fcm_service — fully mocked, no real Firebase or Supabase."""
import pytest
from unittest.mock import AsyncMock, MagicMock

import app.services.fcm_service as fcm_module
from app.services.fcm_service import (
    PushResult,
    _parse_fcm_error_code,
    _send_to_token,
    send_push_to_user,
)
from app.core.supabase_admin import SupabaseUnavailableError


# ── Helpers ───────────────────────────────────────────────────

def _make_mock_httpx_client(status_code: int, body: dict | None = None):
    """Return an async context manager mock for httpx.AsyncClient."""
    mock_response = MagicMock()
    mock_response.status_code = status_code
    mock_response.json.return_value = body or {}

    class MockClient:
        def __init__(self):
            self.post = AsyncMock(return_value=mock_response)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    return MockClient, mock_response


def _fcm_error_body(error_code: str | None = None, status: str | None = None) -> dict:
    """Build a minimal FCM v1 error response body."""
    body: dict = {"error": {}}
    if status:
        body["error"]["status"] = status
    if error_code:
        body["error"]["details"] = [{"errorCode": error_code}]
    return body


# ── TestFcmNotConfigured ──────────────────────────────────────


class TestFcmNotConfigured:
    """send_push_to_user returns empty PushResult when FCM is not configured."""

    @pytest.mark.asyncio
    async def test_returns_empty_result(self, monkeypatch):
        """No Firebase settings → PushResult() with all zeros, no exception."""
        monkeypatch.setattr(fcm_module, "_is_fcm_configured", lambda: False)
        mock_fetch = AsyncMock()
        monkeypatch.setattr(fcm_module, "fetch_active_devices_by_user_id", mock_fetch)

        result = await send_push_to_user("uid-1", "title", "", {"type": "giro"})

        assert result.tokens_queried == 0
        assert result.sent == 0
        assert result.failed == 0
        assert result.invalidated == 0

    @pytest.mark.asyncio
    async def test_no_supabase_call_when_not_configured(self, monkeypatch):
        """fetch_active_devices_by_user_id must not be called when FCM is off."""
        monkeypatch.setattr(fcm_module, "_is_fcm_configured", lambda: False)
        mock_fetch = AsyncMock()
        monkeypatch.setattr(fcm_module, "fetch_active_devices_by_user_id", mock_fetch)

        await send_push_to_user("uid-1", "title", "", {"type": "giro"})

        mock_fetch.assert_not_called()

    @pytest.mark.asyncio
    async def test_warning_emitted_only_once(self, monkeypatch, caplog):
        """The 'FCM disabled' WARNING is emitted at most once across calls."""
        # Reset module state
        fcm_module._fcm_warning_emitted = False
        monkeypatch.setattr(fcm_module.settings, "firebase_credentials_path", None)
        monkeypatch.setattr(fcm_module.settings, "firebase_project_id", None)
        monkeypatch.setattr(fcm_module, "fetch_active_devices_by_user_id", AsyncMock())

        import logging
        with caplog.at_level(logging.WARNING, logger="app.services.fcm_service"):
            await send_push_to_user("uid-1", "t", "", {"type": "giro"})
            await send_push_to_user("uid-2", "t", "", {"type": "giro"})

        warnings = [r for r in caplog.records if "FCM disabled" in r.message]
        assert len(warnings) == 1

        # Cleanup
        fcm_module._fcm_warning_emitted = False


# ── TestParseFcmErrorCode ─────────────────────────────────────


class TestParseFcmErrorCode:
    """Unit tests for the defensive FCM error code parser."""

    def test_details_errorcode_takes_priority(self):
        """details[0].errorCode is returned first when present."""
        body = _fcm_error_body(error_code="UNREGISTERED", status="NOT_FOUND")
        assert _parse_fcm_error_code(body, 404) == "UNREGISTERED"

    def test_fallback_to_error_status(self):
        """error.status returned when no details.errorCode."""
        body = _fcm_error_body(status="NOT_FOUND")
        assert _parse_fcm_error_code(body, 200) == "NOT_FOUND"

    def test_fallback_to_404_status_code(self):
        """Empty body + 404 status_code → infers UNREGISTERED."""
        assert _parse_fcm_error_code({}, 404) == "UNREGISTERED"

    def test_unknown_returns_empty_string(self):
        """Empty body + non-404 status_code → empty string."""
        assert _parse_fcm_error_code({}, 500) == ""

    def test_empty_details_list_falls_through(self):
        """details=[] skips to error.status."""
        body = {"error": {"details": [], "status": "QUOTA_EXCEEDED"}}
        assert _parse_fcm_error_code(body, 429) == "QUOTA_EXCEEDED"

    def test_details_without_errorcode_falls_through(self):
        """details[0] with no errorCode key falls to error.status."""
        body = {"error": {"details": [{"otherField": "x"}], "status": "UNAVAILABLE"}}
        assert _parse_fcm_error_code(body, 503) == "UNAVAILABLE"

    def test_malformed_body_returns_empty(self):
        """None body does not raise; returns empty string."""
        assert _parse_fcm_error_code(None, 500) == ""  # type: ignore[arg-type]

    def test_invalid_argument_code(self):
        """INVALID_ARGUMENT is extracted correctly from details."""
        body = _fcm_error_body(error_code="INVALID_ARGUMENT")
        assert _parse_fcm_error_code(body, 400) == "INVALID_ARGUMENT"


# ── TestSendToToken ───────────────────────────────────────────


class TestSendToToken:
    """Tests for _send_to_token — mocks httpx at the module level."""

    @pytest.mark.asyncio
    async def test_200_returns_sent_true(self, monkeypatch):
        """HTTP 200 → (True, False)."""
        MockClient, _ = _make_mock_httpx_client(200)
        monkeypatch.setattr(fcm_module.httpx, "AsyncClient", lambda **kw: MockClient())

        sent, deactivate = await _send_to_token(
            "tok", "proj", "device-abc", "title", "body", {"type": "giro"}
        )
        assert sent is True
        assert deactivate is False

    @pytest.mark.asyncio
    async def test_unregistered_returns_deactivate_true(self, monkeypatch):
        """FCM UNREGISTERED → (False, True)."""
        body = _fcm_error_body(error_code="UNREGISTERED")
        MockClient, _ = _make_mock_httpx_client(404, body)
        monkeypatch.setattr(fcm_module.httpx, "AsyncClient", lambda **kw: MockClient())

        sent, deactivate = await _send_to_token(
            "tok", "proj", "device-abc", "title", "", {"type": "giro"}
        )
        assert sent is False
        assert deactivate is True

    @pytest.mark.asyncio
    async def test_invalid_argument_returns_deactivate_true(self, monkeypatch):
        """FCM INVALID_ARGUMENT → (False, True)."""
        body = _fcm_error_body(error_code="INVALID_ARGUMENT")
        MockClient, _ = _make_mock_httpx_client(400, body)
        monkeypatch.setattr(fcm_module.httpx, "AsyncClient", lambda **kw: MockClient())

        sent, deactivate = await _send_to_token(
            "tok", "proj", "device-abc", "title", "", {"type": "giro"}
        )
        assert sent is False
        assert deactivate is True

    @pytest.mark.asyncio
    async def test_quota_exceeded_returns_failed(self, monkeypatch):
        """FCM QUOTA_EXCEEDED → (False, False) — do not deactivate."""
        body = _fcm_error_body(error_code="QUOTA_EXCEEDED")
        MockClient, _ = _make_mock_httpx_client(429, body)
        monkeypatch.setattr(fcm_module.httpx, "AsyncClient", lambda **kw: MockClient())

        sent, deactivate = await _send_to_token(
            "tok", "proj", "device-abc", "title", "", {"type": "giro"}
        )
        assert sent is False
        assert deactivate is False

    @pytest.mark.asyncio
    async def test_not_found_status_only_is_conservative(self, monkeypatch):
        """
        error.status=NOT_FOUND without details.errorCode → (False, False).
        Conservative: only deactivate when FCM explicitly confirms via errorCode.
        """
        body = _fcm_error_body(status="NOT_FOUND")
        # status_code=404 no activa la inferencia UNREGISTERED porque el paso 2
        # (error.status) devuelve "NOT_FOUND" antes de llegar al paso 3 (status_code==404).
        # "NOT_FOUND" no está en _INVALIDATING_ERROR_CODES → should_deactivate=False.
        MockClient, _ = _make_mock_httpx_client(404, body)
        monkeypatch.setattr(fcm_module.httpx, "AsyncClient", lambda **kw: MockClient())

        sent, deactivate = await _send_to_token(
            "tok", "proj", "device-abc", "title", "", {"type": "giro"}
        )
        assert sent is False
        assert deactivate is False

    @pytest.mark.asyncio
    async def test_unknown_error_code_returns_failed(self, monkeypatch):
        """Unrecognized error code → (False, False)."""
        body = _fcm_error_body(error_code="INTERNAL")
        MockClient, _ = _make_mock_httpx_client(500, body)
        monkeypatch.setattr(fcm_module.httpx, "AsyncClient", lambda **kw: MockClient())

        sent, deactivate = await _send_to_token(
            "tok", "proj", "device-abc", "title", "", {"type": "giro"}
        )
        assert sent is False
        assert deactivate is False

    @pytest.mark.asyncio
    async def test_network_timeout_returns_failed(self, monkeypatch):
        """httpx.TimeoutException → (False, False), no exception raised."""
        import httpx

        class MockClientTimeout:
            async def __aenter__(self): return self
            async def __aexit__(self, *a): pass
            post = AsyncMock(side_effect=httpx.TimeoutException("timeout"))

        monkeypatch.setattr(fcm_module.httpx, "AsyncClient", lambda **kw: MockClientTimeout())

        sent, deactivate = await _send_to_token(
            "tok", "proj", "device-abc", "title", "", {"type": "giro"}
        )
        assert sent is False
        assert deactivate is False

    @pytest.mark.asyncio
    async def test_network_request_error_returns_failed(self, monkeypatch):
        """httpx.RequestError → (False, False), no exception raised."""
        import httpx

        class MockClientReqErr:
            async def __aenter__(self): return self
            async def __aexit__(self, *a): pass
            post = AsyncMock(side_effect=httpx.RequestError("conn refused"))

        monkeypatch.setattr(fcm_module.httpx, "AsyncClient", lambda **kw: MockClientReqErr())

        sent, deactivate = await _send_to_token(
            "tok", "proj", "device-abc", "title", "", {"type": "giro"}
        )
        assert sent is False
        assert deactivate is False


# ── TestSendPushToUser ────────────────────────────────────────


class TestSendPushToUser:
    """Integration tests for send_push_to_user — mocked at boundaries."""

    @pytest.mark.asyncio
    async def test_no_active_devices_returns_zero_tokens(self, monkeypatch):
        """User with no active devices → PushResult(tokens_queried=0)."""
        monkeypatch.setattr(fcm_module, "_is_fcm_configured", lambda: True)
        monkeypatch.setattr(
            fcm_module, "fetch_active_devices_by_user_id", AsyncMock(return_value=[])
        )

        result = await send_push_to_user("uid-1", "title", "", {"type": "giro"})

        assert result.tokens_queried == 0
        assert result.sent == 0
        assert result.failed == 0
        assert result.invalidated == 0

    @pytest.mark.asyncio
    async def test_one_device_success(self, monkeypatch):
        """1 token, FCM 200 → PushResult(tokens=1, sent=1, failed=0, invalidated=0)."""
        monkeypatch.setattr(fcm_module, "_is_fcm_configured", lambda: True)
        monkeypatch.setattr(
            fcm_module,
            "fetch_active_devices_by_user_id",
            AsyncMock(return_value=[{"device_token": "tok-abc"}]),
        )
        monkeypatch.setattr(fcm_module, "_get_access_token", AsyncMock(return_value="at"))
        monkeypatch.setattr(
            fcm_module, "_send_to_token", AsyncMock(return_value=(True, False))
        )
        monkeypatch.setattr(fcm_module.settings, "firebase_project_id", "proj")

        result = await send_push_to_user("uid-1", "title", "", {"type": "giro"})

        assert result.tokens_queried == 1
        assert result.sent == 1
        assert result.failed == 0
        assert result.invalidated == 0

    @pytest.mark.asyncio
    async def test_one_device_unregistered_deactivates(self, monkeypatch):
        """UNREGISTERED token → deactivate_device_by_token called, invalidated=1."""
        monkeypatch.setattr(fcm_module, "_is_fcm_configured", lambda: True)
        monkeypatch.setattr(
            fcm_module,
            "fetch_active_devices_by_user_id",
            AsyncMock(return_value=[{"device_token": "tok-old"}]),
        )
        monkeypatch.setattr(fcm_module, "_get_access_token", AsyncMock(return_value="at"))
        monkeypatch.setattr(
            fcm_module, "_send_to_token", AsyncMock(return_value=(False, True))
        )
        mock_deactivate = AsyncMock()
        monkeypatch.setattr(fcm_module, "deactivate_device_by_token", mock_deactivate)
        monkeypatch.setattr(fcm_module.settings, "firebase_project_id", "proj")

        result = await send_push_to_user("uid-1", "title", "", {"type": "giro"})

        mock_deactivate.assert_called_once_with("tok-old")
        assert result.invalidated == 1
        assert result.failed == 0
        assert result.sent == 0

    @pytest.mark.asyncio
    async def test_three_devices_mixed_results(self, monkeypatch):
        """3 tokens: [sent, unregistered, timeout] → sent=1, failed=1, invalidated=1."""
        monkeypatch.setattr(fcm_module, "_is_fcm_configured", lambda: True)
        monkeypatch.setattr(
            fcm_module,
            "fetch_active_devices_by_user_id",
            AsyncMock(return_value=[
                {"device_token": "tok-1"},
                {"device_token": "tok-2"},
                {"device_token": "tok-3"},
            ]),
        )
        monkeypatch.setattr(fcm_module, "_get_access_token", AsyncMock(return_value="at"))
        monkeypatch.setattr(
            fcm_module,
            "_send_to_token",
            AsyncMock(side_effect=[(True, False), (False, True), (False, False)]),
        )
        monkeypatch.setattr(fcm_module, "deactivate_device_by_token", AsyncMock())
        monkeypatch.setattr(fcm_module.settings, "firebase_project_id", "proj")

        result = await send_push_to_user("uid-1", "title", "", {"type": "giro"})

        assert result.tokens_queried == 3
        assert result.sent == 1
        assert result.failed == 1
        assert result.invalidated == 1

    @pytest.mark.asyncio
    async def test_failed_and_invalidated_are_independent(self, monkeypatch):
        """failed counter must not include invalidated tokens."""
        monkeypatch.setattr(fcm_module, "_is_fcm_configured", lambda: True)
        monkeypatch.setattr(
            fcm_module,
            "fetch_active_devices_by_user_id",
            AsyncMock(return_value=[
                {"device_token": "tok-inv"},
                {"device_token": "tok-fail"},
            ]),
        )
        monkeypatch.setattr(fcm_module, "_get_access_token", AsyncMock(return_value="at"))
        # First token: invalid. Second: transient failure.
        monkeypatch.setattr(
            fcm_module,
            "_send_to_token",
            AsyncMock(side_effect=[(False, True), (False, False)]),
        )
        monkeypatch.setattr(fcm_module, "deactivate_device_by_token", AsyncMock())
        monkeypatch.setattr(fcm_module.settings, "firebase_project_id", "proj")

        result = await send_push_to_user("uid-1", "title", "", {"type": "giro"})

        assert result.failed == 1
        assert result.invalidated == 1
        assert result.sent == 0

    @pytest.mark.asyncio
    async def test_supabase_unavailable_on_fetch_returns_failed(self, monkeypatch):
        """SupabaseUnavailableError fetching devices → PushResult(failed=1), no raise."""
        monkeypatch.setattr(fcm_module, "_is_fcm_configured", lambda: True)
        monkeypatch.setattr(
            fcm_module,
            "fetch_active_devices_by_user_id",
            AsyncMock(side_effect=SupabaseUnavailableError("down")),
        )

        result = await send_push_to_user("uid-1", "title", "", {"type": "giro"})

        assert result.failed == 1
        assert result.sent == 0
        assert result.invalidated == 0

    @pytest.mark.asyncio
    async def test_access_token_failure_returns_failed(self, monkeypatch):
        """_get_access_token raises → PushResult(failed=len(devices)), no raise."""
        monkeypatch.setattr(fcm_module, "_is_fcm_configured", lambda: True)
        monkeypatch.setattr(
            fcm_module,
            "fetch_active_devices_by_user_id",
            AsyncMock(return_value=[
                {"device_token": "tok-1"},
                {"device_token": "tok-2"},
            ]),
        )
        monkeypatch.setattr(
            fcm_module,
            "_get_access_token",
            AsyncMock(side_effect=Exception("creds not found")),
        )

        result = await send_push_to_user("uid-1", "title", "", {"type": "giro"})

        assert result.failed == 2
        assert result.sent == 0
        assert result.invalidated == 0

    @pytest.mark.asyncio
    async def test_deactivation_failure_does_not_raise(self, monkeypatch):
        """deactivate_device_by_token raises → invalidated still counted, no raise."""
        monkeypatch.setattr(fcm_module, "_is_fcm_configured", lambda: True)
        monkeypatch.setattr(
            fcm_module,
            "fetch_active_devices_by_user_id",
            AsyncMock(return_value=[{"device_token": "tok-bad"}]),
        )
        monkeypatch.setattr(fcm_module, "_get_access_token", AsyncMock(return_value="at"))
        monkeypatch.setattr(
            fcm_module, "_send_to_token", AsyncMock(return_value=(False, True))
        )
        monkeypatch.setattr(
            fcm_module,
            "deactivate_device_by_token",
            AsyncMock(side_effect=SupabaseUnavailableError("down")),
        )
        monkeypatch.setattr(fcm_module.settings, "firebase_project_id", "proj")

        result = await send_push_to_user("uid-1", "title", "", {"type": "giro"})

        assert result.invalidated == 1
        assert result.failed == 0

    @pytest.mark.asyncio
    async def test_data_type_preserved(self, monkeypatch):
        """data={"type": "reparto"} is passed unchanged to _send_to_token."""
        monkeypatch.setattr(fcm_module, "_is_fcm_configured", lambda: True)
        monkeypatch.setattr(
            fcm_module,
            "fetch_active_devices_by_user_id",
            AsyncMock(return_value=[{"device_token": "tok-1"}]),
        )
        monkeypatch.setattr(fcm_module, "_get_access_token", AsyncMock(return_value="at"))
        mock_send = AsyncMock(return_value=(True, False))
        monkeypatch.setattr(fcm_module, "_send_to_token", mock_send)
        monkeypatch.setattr(fcm_module.settings, "firebase_project_id", "proj")

        await send_push_to_user("uid-1", "title", "", {"type": "reparto"})

        call_kwargs = mock_send.call_args
        assert call_kwargs[0][5] == {"type": "reparto"}  # data is the 6th positional arg


# ── TestGetAccessToken ────────────────────────────────────────


class TestGetAccessToken:
    """Tests for token caching and refresh behavior."""

    @pytest.fixture(autouse=True)
    def mock_request_class(self, monkeypatch):
        """Patch Request so no real requests.Session is created during tests."""
        monkeypatch.setattr(fcm_module, "Request", MagicMock)

    @pytest.mark.asyncio
    async def test_credentials_loaded_on_first_call(self, monkeypatch):
        """_get_credentials is called exactly once on first token acquisition."""
        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_creds.token = "access-token-xyz"

        mock_get_creds = MagicMock(return_value=mock_creds)
        monkeypatch.setattr(fcm_module, "_get_credentials", mock_get_creds)

        async def fake_to_thread(fn, *args, **kwargs):
            if args:
                return fn(*args)
            return fn()

        monkeypatch.setattr(fcm_module.asyncio, "to_thread", fake_to_thread)

        token = await fcm_module._get_access_token()

        assert token == "access-token-xyz"
        mock_get_creds.assert_called_once()

    @pytest.mark.asyncio
    async def test_token_reused_on_second_call(self, monkeypatch):
        """Second call returns cached token; _get_credentials called only once."""
        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_creds.token = "cached-token"

        mock_get_creds = MagicMock(return_value=mock_creds)
        monkeypatch.setattr(fcm_module, "_get_credentials", mock_get_creds)

        async def fake_to_thread(fn, *args, **kwargs):
            if args:
                return fn(*args)
            return fn()

        monkeypatch.setattr(fcm_module.asyncio, "to_thread", fake_to_thread)

        token1 = await fcm_module._get_access_token()
        token2 = await fcm_module._get_access_token()

        assert token1 == token2 == "cached-token"
        assert mock_get_creds.call_count == 1

    @pytest.mark.asyncio
    async def test_token_refreshed_when_not_valid(self, monkeypatch):
        """credentials.refresh() called when credentials.valid is False."""
        mock_creds = MagicMock()
        mock_creds.valid = False  # expired
        mock_creds.token = "refreshed-token"

        mock_get_creds = MagicMock(return_value=mock_creds)
        monkeypatch.setattr(fcm_module, "_get_credentials", mock_get_creds)

        refresh_calls = []

        async def fake_to_thread(fn, *args, **kwargs):
            if args:
                refresh_calls.append(fn)
                # Simulate refresh making credentials valid
                mock_creds.valid = True
                return fn(*args)
            return fn()

        monkeypatch.setattr(fcm_module.asyncio, "to_thread", fake_to_thread)

        token = await fcm_module._get_access_token()

        assert token == "refreshed-token"
        # refresh was called (one call to to_thread with args = refresh)
        assert any(fn == mock_creds.refresh for fn in refresh_calls)
