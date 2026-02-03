"""Tests for health endpoints."""
import pytest
from unittest.mock import AsyncMock, MagicMock

import httpx
from fastapi.testclient import TestClient

from app.main import app
from app.api import health as health_module


@pytest.fixture
def client():
    return TestClient(app)


class TestHealthLiveness:
    """Tests for GET /health (liveness)."""

    def test_health_returns_200_ok(self, client):
        """GET /health always returns 200 with status ok."""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestHealthReady:
    """Tests for GET /health/ready (readiness)."""

    def test_ready_db_ok_jwks_skipped(self, client, monkeypatch):
        """When DB ok and JWKS URL not configured, returns 200 with jwks=skipped."""
        mock_ping = AsyncMock(return_value=True)
        monkeypatch.setattr(health_module, "ping_db", mock_ping)
        monkeypatch.setattr(health_module.settings, "supabase_jwks_url", None)
        monkeypatch.setattr(health_module.settings, "jwks_ready_timeout", 2)

        response = client.get("/health/ready")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["checks"]["db"] == "ok"
        assert data["checks"]["jwks"] == "skipped"

    def test_ready_db_unreachable_returns_503(self, client, monkeypatch):
        """When DB fails, returns 503 with db=unreachable."""
        mock_ping = AsyncMock(return_value=False)
        monkeypatch.setattr(health_module, "ping_db", mock_ping)
        monkeypatch.setattr(health_module.settings, "supabase_jwks_url", None)
        monkeypatch.setattr(health_module.settings, "jwks_ready_timeout", 2)

        response = client.get("/health/ready")

        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "fail"
        assert data["checks"]["db"] == "unreachable"
        assert data["detail"] == "Dependency check failed"

    def test_ready_db_ok_jwks_ok(self, client, monkeypatch):
        """When DB ok and JWKS fetch succeeds, returns 200."""
        mock_ping = AsyncMock(return_value=True)
        monkeypatch.setattr(health_module, "ping_db", mock_ping)
        monkeypatch.setattr(health_module.settings, "supabase_jwks_url", "https://example.com/.well-known/jwks.json")
        monkeypatch.setattr(health_module.settings, "jwks_ready_timeout", 2)

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()

        mock_client_instance = AsyncMock()
        mock_client_instance.get.return_value = mock_response
        mock_client_instance.__aenter__.return_value = mock_client_instance
        mock_client_instance.__aexit__.return_value = None

        mock_client_class = MagicMock(return_value=mock_client_instance)
        monkeypatch.setattr(health_module.httpx, "AsyncClient", mock_client_class)

        response = client.get("/health/ready")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["checks"]["db"] == "ok"
        assert data["checks"]["jwks"] == "ok"

    def test_ready_db_ok_jwks_unreachable(self, client, monkeypatch):
        """When DB ok but JWKS fetch fails, returns 503."""
        mock_ping = AsyncMock(return_value=True)
        monkeypatch.setattr(health_module, "ping_db", mock_ping)
        monkeypatch.setattr(health_module.settings, "supabase_jwks_url", "https://example.com/.well-known/jwks.json")
        monkeypatch.setattr(health_module.settings, "jwks_ready_timeout", 2)

        mock_client_instance = AsyncMock()
        mock_client_instance.get.side_effect = httpx.TimeoutException("timeout")
        mock_client_instance.__aenter__.return_value = mock_client_instance
        mock_client_instance.__aexit__.return_value = None

        mock_client_class = MagicMock(return_value=mock_client_instance)
        monkeypatch.setattr(health_module.httpx, "AsyncClient", mock_client_class)

        response = client.get("/health/ready")

        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "fail"
        assert data["checks"]["db"] == "ok"
        assert data["checks"]["jwks"] == "unreachable"
        assert data["detail"] == "Dependency check failed"

    def test_ready_db_ok_jwks_request_error(self, client, monkeypatch):
        """When DB ok but JWKS has request error, returns 503."""
        mock_ping = AsyncMock(return_value=True)
        monkeypatch.setattr(health_module, "ping_db", mock_ping)
        monkeypatch.setattr(health_module.settings, "supabase_jwks_url", "https://example.com/.well-known/jwks.json")
        monkeypatch.setattr(health_module.settings, "jwks_ready_timeout", 2)

        mock_client_instance = AsyncMock()
        mock_client_instance.get.side_effect = httpx.RequestError("connection failed")
        mock_client_instance.__aenter__.return_value = mock_client_instance
        mock_client_instance.__aexit__.return_value = None

        mock_client_class = MagicMock(return_value=mock_client_instance)
        monkeypatch.setattr(health_module.httpx, "AsyncClient", mock_client_class)

        response = client.get("/health/ready")

        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "fail"
        assert data["checks"]["jwks"] == "unreachable"
