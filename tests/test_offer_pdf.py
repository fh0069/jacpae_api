"""Tests for GET /offers/current endpoint."""
import pytest
from pathlib import Path
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.main import app
from app.api import offer_pdf as offer_pdf_module
from app.core.auth import get_current_user, User


# ── fixtures ──────────────────────────────────────────────────


@pytest.fixture
def client():
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def valid_user():
    return User(sub="uuid-test", email="test@example.com", role="authenticated")


def _override_user(user: User):
    async def _inner():
        return user
    return _inner


# ── auth ──────────────────────────────────────────────────────


class TestOfferPdfAuth:
    """Authentication guard tests."""

    def test_401_without_token(self, client):
        """Request without Authorization header → 401."""
        response = client.get("/offers/current")
        assert response.status_code == 401


# ── no active offer ───────────────────────────────────────────


class TestOfferPdfNoOffer:
    """Tests when the offer service finds nothing."""

    def test_404_when_service_returns_none(self, client, valid_user, monkeypatch):
        """get_active_offer_path() → None  ⇒  404 with clear detail."""
        app.dependency_overrides[get_current_user] = _override_user(valid_user)
        monkeypatch.setattr(
            offer_pdf_module, "get_active_offer_path", AsyncMock(return_value=None)
        )

        response = client.get("/offers/current")

        assert response.status_code == 404
        assert response.json()["detail"] == "No active offer available"


# ── happy path ────────────────────────────────────────────────


class TestOfferPdfSuccess:
    """Happy-path tests: offer exists and is streamed correctly."""

    def test_200_streams_pdf_content(self, client, valid_user, monkeypatch, tmp_path):
        """When an offer file exists, body equals the file content."""
        pdf_content = b"%PDF-1.4 offer dummy"
        pdf_file = tmp_path / "oferta_20260301.pdf"
        pdf_file.write_bytes(pdf_content)

        app.dependency_overrides[get_current_user] = _override_user(valid_user)
        monkeypatch.setattr(
            offer_pdf_module, "get_active_offer_path", AsyncMock(return_value=pdf_file)
        )

        response = client.get("/offers/current")

        assert response.status_code == 200
        assert response.content == pdf_content

    def test_200_content_type_is_pdf(self, client, valid_user, monkeypatch, tmp_path):
        """Content-Type must be application/pdf."""
        pdf_file = tmp_path / "oferta_20260301.pdf"
        pdf_file.write_bytes(b"%PDF")

        app.dependency_overrides[get_current_user] = _override_user(valid_user)
        monkeypatch.setattr(
            offer_pdf_module, "get_active_offer_path", AsyncMock(return_value=pdf_file)
        )

        response = client.get("/offers/current")

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"

    def test_content_disposition_contains_filename(
        self, client, valid_user, monkeypatch, tmp_path
    ):
        """Content-Disposition must include the offer filename (oferta_YYYYMMDD.pdf)."""
        pdf_file = tmp_path / "oferta_20260301.pdf"
        pdf_file.write_bytes(b"%PDF")

        app.dependency_overrides[get_current_user] = _override_user(valid_user)
        monkeypatch.setattr(
            offer_pdf_module, "get_active_offer_path", AsyncMock(return_value=pdf_file)
        )

        response = client.get("/offers/current")

        assert "oferta_20260301.pdf" in response.headers["content-disposition"]

    def test_no_internal_path_leaked_in_headers(
        self, client, valid_user, monkeypatch, tmp_path
    ):
        """The full NAS/filesystem path must never appear in any response header."""
        pdf_file = tmp_path / "oferta_20260301.pdf"
        pdf_file.write_bytes(b"%PDF-safe")

        app.dependency_overrides[get_current_user] = _override_user(valid_user)
        monkeypatch.setattr(
            offer_pdf_module, "get_active_offer_path", AsyncMock(return_value=pdf_file)
        )

        response = client.get("/offers/current")

        full_dir = str(tmp_path)
        for header_value in response.headers.values():
            assert full_dir not in header_value

    def test_no_internal_path_leaked_in_body(
        self, client, valid_user, monkeypatch, tmp_path
    ):
        """The binary body must not contain the internal directory path."""
        pdf_file = tmp_path / "oferta_20260301.pdf"
        pdf_file.write_bytes(b"%PDF-safe")

        app.dependency_overrides[get_current_user] = _override_user(valid_user)
        monkeypatch.setattr(
            offer_pdf_module, "get_active_offer_path", AsyncMock(return_value=pdf_file)
        )

        response = client.get("/offers/current")

        assert str(tmp_path).encode() not in response.content
