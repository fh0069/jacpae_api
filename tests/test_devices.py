"""Tests for POST /devices/register endpoint and push_service logic."""
import pytest
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.main import app
from app.api import devices as devices_module
from app.core.auth import get_current_user, User
from app.core.supabase_admin import SupabaseUnavailableError
from app.services.push_service import register_device


# ── Fixtures ───────────────────────────────────────────────────

@pytest.fixture
def client():
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def valid_user():
    return User(sub="uuid-test", email="test@example.com", role="authenticated")


def override_get_current_user(user: User):
    async def _override():
        return user
    return _override


_VALID_BODY = {"device_token": "tok_abc123", "platform": "android"}


# ── Auth tests ─────────────────────────────────────────────────

class TestDevicesAuth:
    """Authentication guards on POST /devices/register."""

    def test_401_without_token(self, client):
        """Request without JWT returns 401."""
        response = client.post("/devices/register", json=_VALID_BODY)
        assert response.status_code == 401

    def test_503_supabase_unavailable(self, client, monkeypatch, valid_user):
        """SupabaseUnavailableError surfaces as 503."""
        app.dependency_overrides[get_current_user] = override_get_current_user(valid_user)
        monkeypatch.setattr(
            devices_module, "register_device",
            AsyncMock(side_effect=SupabaseUnavailableError("down")),
        )
        response = client.post("/devices/register", json=_VALID_BODY)
        assert response.status_code == 503


# ── Validation tests ───────────────────────────────────────────

class TestDevicesValidation:
    """Input validation on POST /devices/register."""

    def test_422_invalid_platform(self, client, valid_user):
        """platform not in ('android', 'ios') → 422."""
        app.dependency_overrides[get_current_user] = override_get_current_user(valid_user)
        response = client.post(
            "/devices/register",
            json={"device_token": "tok", "platform": "windows"},
        )
        assert response.status_code == 422

    def test_422_missing_device_token(self, client, valid_user):
        """Missing device_token → 422."""
        app.dependency_overrides[get_current_user] = override_get_current_user(valid_user)
        response = client.post("/devices/register", json={"platform": "ios"})
        assert response.status_code == 422

    def test_422_missing_platform(self, client, valid_user):
        """Missing platform → 422."""
        app.dependency_overrides[get_current_user] = override_get_current_user(valid_user)
        response = client.post("/devices/register", json={"device_token": "tok"})
        assert response.status_code == 422

    def test_422_empty_platform(self, client, valid_user):
        """Empty string platform → 422."""
        app.dependency_overrides[get_current_user] = override_get_current_user(valid_user)
        response = client.post(
            "/devices/register",
            json={"device_token": "tok", "platform": ""},
        )
        assert response.status_code == 422


# ── Endpoint integration tests ─────────────────────────────────

class TestDevicesRegister:
    """Endpoint-level tests mocking at the service boundary."""

    def test_200_new_device(self, client, monkeypatch, valid_user):
        """New token → 200 with status=registered."""
        app.dependency_overrides[get_current_user] = override_get_current_user(valid_user)
        monkeypatch.setattr(devices_module, "register_device", AsyncMock(return_value=None))
        response = client.post("/devices/register", json=_VALID_BODY)
        assert response.status_code == 200
        assert response.json() == {"status": "registered"}

    def test_200_existing_device_reactivated(self, client, monkeypatch, valid_user):
        """Existing token → 200 (service decides insert vs update internally)."""
        app.dependency_overrides[get_current_user] = override_get_current_user(valid_user)
        monkeypatch.setattr(devices_module, "register_device", AsyncMock(return_value=None))
        response = client.post("/devices/register", json=_VALID_BODY)
        assert response.status_code == 200
        assert response.json()["status"] == "registered"

    def test_200_token_owned_by_different_user(self, client, monkeypatch, valid_user):
        """Token belonging to another user → 200 (service updates user_id)."""
        app.dependency_overrides[get_current_user] = override_get_current_user(valid_user)
        monkeypatch.setattr(devices_module, "register_device", AsyncMock(return_value=None))
        response = client.post("/devices/register", json=_VALID_BODY)
        assert response.status_code == 200

    def test_200_ios_platform(self, client, monkeypatch, valid_user):
        """platform=ios is accepted."""
        app.dependency_overrides[get_current_user] = override_get_current_user(valid_user)
        monkeypatch.setattr(devices_module, "register_device", AsyncMock(return_value=None))
        response = client.post(
            "/devices/register",
            json={"device_token": "tok_ios_xyz", "platform": "ios"},
        )
        assert response.status_code == 200

    def test_register_device_called_with_jwt_user_id(self, client, monkeypatch, valid_user):
        """register_device receives user_id from JWT, not from request body."""
        app.dependency_overrides[get_current_user] = override_get_current_user(valid_user)
        mock_register = AsyncMock(return_value=None)
        monkeypatch.setattr(devices_module, "register_device", mock_register)
        client.post("/devices/register", json=_VALID_BODY)
        mock_register.assert_called_once_with(
            user_id="uuid-test",
            device_token="tok_abc123",
            platform="android",
        )

    def test_500_on_unexpected_error(self, client, monkeypatch, valid_user):
        """Unexpected exception from service → 500."""
        app.dependency_overrides[get_current_user] = override_get_current_user(valid_user)
        monkeypatch.setattr(
            devices_module, "register_device",
            AsyncMock(side_effect=RuntimeError("unexpected")),
        )
        response = client.post("/devices/register", json=_VALID_BODY)
        assert response.status_code == 500
        assert response.json()["detail"] == "Error registering device"


# ── Service unit tests ─────────────────────────────────────────

class TestPushService:
    """Unit tests for push_service.register_device (mocked repository)."""

    @pytest.mark.asyncio
    async def test_new_token_calls_insert(self, monkeypatch):
        """When token not found, insert_device is called with correct args."""
        from app.services import push_service as ps_module

        mock_get = AsyncMock(return_value=None)
        mock_insert = AsyncMock()
        mock_update = AsyncMock()
        monkeypatch.setattr(ps_module, "get_device_by_token", mock_get)
        monkeypatch.setattr(ps_module, "insert_device", mock_insert)
        monkeypatch.setattr(ps_module, "update_device", mock_update)

        await register_device("user-1", "tok_new", "android")

        mock_get.assert_called_once_with("tok_new")
        mock_insert.assert_called_once_with(
            user_id="user-1", device_token="tok_new", platform="android"
        )
        mock_update.assert_not_called()

    @pytest.mark.asyncio
    async def test_existing_token_calls_update(self, monkeypatch):
        """When token already exists, update_device is called with its id."""
        from app.services import push_service as ps_module

        existing = {"id": "device-uuid-1", "user_id": "same-user"}
        monkeypatch.setattr(ps_module, "get_device_by_token", AsyncMock(return_value=existing))
        mock_insert = AsyncMock()
        mock_update = AsyncMock()
        monkeypatch.setattr(ps_module, "insert_device", mock_insert)
        monkeypatch.setattr(ps_module, "update_device", mock_update)

        await register_device("same-user", "tok_existing", "ios")

        mock_update.assert_called_once_with(device_id="device-uuid-1", user_id="same-user")
        mock_insert.assert_not_called()

    @pytest.mark.asyncio
    async def test_existing_token_updates_user_id(self, monkeypatch):
        """Token owned by a different user → update_device receives new user_id."""
        from app.services import push_service as ps_module

        existing = {"id": "device-uuid-2", "user_id": "original-user"}
        monkeypatch.setattr(ps_module, "get_device_by_token", AsyncMock(return_value=existing))
        mock_update = AsyncMock()
        monkeypatch.setattr(ps_module, "insert_device", AsyncMock())
        monkeypatch.setattr(ps_module, "update_device", mock_update)

        await register_device("new-user", "tok_abc", "android")

        call_kwargs = mock_update.call_args.kwargs
        assert call_kwargs["user_id"] == "new-user"
        assert call_kwargs["device_id"] == "device-uuid-2"

    @pytest.mark.asyncio
    async def test_supabase_error_propagates(self, monkeypatch):
        """SupabaseUnavailableError from repository propagates to caller."""
        from app.services import push_service as ps_module

        monkeypatch.setattr(
            ps_module, "get_device_by_token",
            AsyncMock(side_effect=SupabaseUnavailableError("down")),
        )

        with pytest.raises(SupabaseUnavailableError):
            await register_device("user-1", "tok_err", "ios")
