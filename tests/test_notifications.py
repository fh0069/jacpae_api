"""Tests for GET /notifications and PATCH /notifications/{id}/read."""
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.main import app
from app.api import notifications as notifications_module
from app.core.auth import get_current_user, User
from app.core.supabase_admin import Notification, SupabaseUnavailableError


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


SAMPLE_NOTIFICATIONS = [
    Notification(
        id="n1-uuid",
        type="giro",
        title="Giro pendiente",
        body="El efecto R001 por importe de 1500.00 € vence el 01/03/2026.",
        data={"num_efecto": "R001", "importe": 1500.00},
        read_at=None,
        created_at=datetime(2026, 2, 17, 8, 0, 0, tzinfo=timezone.utc),
    ),
    Notification(
        id="n2-uuid",
        type="giro",
        title="Giro pendiente",
        body="El efecto S002 por importe de 750.50 € vence el 05/03/2026.",
        data={"num_efecto": "S002", "importe": 750.50},
        read_at=datetime(2026, 2, 17, 9, 0, 0, tzinfo=timezone.utc),
        created_at=datetime(2026, 2, 17, 8, 0, 0, tzinfo=timezone.utc),
    ),
]


class TestGetNotificationsAuth:
    """Auth tests for GET /notifications."""

    def test_401_without_token(self, client):
        response = client.get("/notifications")
        assert response.status_code == 401

    def test_503_supabase_unavailable(self, client, monkeypatch, valid_user):
        app.dependency_overrides[get_current_user] = override_get_current_user(valid_user)
        monkeypatch.setattr(
            notifications_module,
            "fetch_notifications",
            AsyncMock(side_effect=SupabaseUnavailableError("down")),
        )
        response = client.get("/notifications")
        assert response.status_code == 503


class TestGetNotificationsData:
    """Data tests for GET /notifications."""

    def test_200_returns_list(self, client, monkeypatch, valid_user):
        app.dependency_overrides[get_current_user] = override_get_current_user(valid_user)
        monkeypatch.setattr(
            notifications_module,
            "fetch_notifications",
            AsyncMock(return_value=SAMPLE_NOTIFICATIONS),
        )

        response = client.get("/notifications")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert data[0]["id"] == "n1-uuid"
        assert data[0]["type"] == "giro"
        assert data[0]["read_at"] is None
        assert data[1]["read_at"] is not None

    def test_200_empty_list(self, client, monkeypatch, valid_user):
        app.dependency_overrides[get_current_user] = override_get_current_user(valid_user)
        monkeypatch.setattr(
            notifications_module,
            "fetch_notifications",
            AsyncMock(return_value=[]),
        )

        response = client.get("/notifications")
        assert response.status_code == 200
        assert response.json() == []

    def test_422_limit_over_100(self, client, valid_user):
        """FastAPI Query validation: limit > 100 returns 422."""
        app.dependency_overrides[get_current_user] = override_get_current_user(valid_user)
        response = client.get("/notifications?limit=101")
        assert response.status_code == 422

    def test_422_negative_offset(self, client, valid_user):
        """FastAPI Query validation: offset < 0 returns 422."""
        app.dependency_overrides[get_current_user] = override_get_current_user(valid_user)
        response = client.get("/notifications?offset=-1")
        assert response.status_code == 422

    def test_passes_limit_offset(self, client, monkeypatch, valid_user):
        """Ensure limit and offset are forwarded to fetch_notifications."""
        app.dependency_overrides[get_current_user] = override_get_current_user(valid_user)
        mock_fetch = AsyncMock(return_value=[])
        monkeypatch.setattr(notifications_module, "fetch_notifications", mock_fetch)

        client.get("/notifications?limit=10&offset=20")

        mock_fetch.assert_called_once_with("uuid-test", 10, 20)


class TestPatchNotificationRead:
    """Tests for PATCH /notifications/{id}/read."""

    def test_401_without_token(self, client):
        response = client.patch("/notifications/some-uuid/read")
        assert response.status_code == 401

    def test_204_success(self, client, monkeypatch, valid_user):
        app.dependency_overrides[get_current_user] = override_get_current_user(valid_user)
        monkeypatch.setattr(
            notifications_module,
            "mark_notification_read",
            AsyncMock(return_value=True),
        )

        response = client.patch("/notifications/n1-uuid/read")
        assert response.status_code == 204
        assert response.content == b""

    def test_404_not_found(self, client, monkeypatch, valid_user):
        app.dependency_overrides[get_current_user] = override_get_current_user(valid_user)
        monkeypatch.setattr(
            notifications_module,
            "mark_notification_read",
            AsyncMock(return_value=False),
        )

        response = client.patch("/notifications/nonexistent/read")
        assert response.status_code == 404
        assert response.json()["detail"] == "Notification not found"

    def test_503_supabase_unavailable(self, client, monkeypatch, valid_user):
        app.dependency_overrides[get_current_user] = override_get_current_user(valid_user)
        monkeypatch.setattr(
            notifications_module,
            "mark_notification_read",
            AsyncMock(side_effect=SupabaseUnavailableError("down")),
        )

        response = client.patch("/notifications/n1-uuid/read")
        assert response.status_code == 503

    def test_passes_user_id_and_notification_id(self, client, monkeypatch, valid_user):
        """Ensure both user_id and notification_id are forwarded."""
        app.dependency_overrides[get_current_user] = override_get_current_user(valid_user)
        mock_mark = AsyncMock(return_value=True)
        monkeypatch.setattr(notifications_module, "mark_notification_read", mock_mark)

        client.patch("/notifications/n1-uuid/read")

        mock_mark.assert_called_once_with("uuid-test", "n1-uuid")
