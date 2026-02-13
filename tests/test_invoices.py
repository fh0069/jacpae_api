"""Tests for GET /invoices endpoint."""
import pytest
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.main import app
from app.api import invoices as invoices_module
from app.api.invoices import build_invoice_id, decode_invoice_id
from app.core.auth import get_current_user, User
from app.core.supabase_admin import CustomerProfile, SupabaseUnavailableError


@pytest.fixture
def client():
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def valid_user():
    return User(sub="uuid-test", email="test@example.com", role="authenticated")


@pytest.fixture
def active_profile():
    return CustomerProfile(erp_clt_prov="X", is_active=True)


@pytest.fixture
def inactive_profile():
    return CustomerProfile(erp_clt_prov="X", is_active=False)


def override_get_current_user(user: User):
    """Factory to create a dependency override returning the given user."""
    async def _override():
        return user
    return _override


class TestInvoicesAuth:
    """Tests for authentication/authorization on GET /invoices."""

    def test_401_without_token(self, client):
        """Request without Authorization header returns 401."""
        response = client.get("/invoices")
        assert response.status_code == 401
        assert "detail" in response.json()

    def test_503_supabase_unavailable(self, client, monkeypatch, valid_user):
        """When Supabase is unavailable, returns 503."""
        app.dependency_overrides[get_current_user] = override_get_current_user(valid_user)
        mock_fetch_profile = AsyncMock(side_effect=SupabaseUnavailableError("unavailable"))
        monkeypatch.setattr(invoices_module, "fetch_customer_profile", mock_fetch_profile)

        response = client.get("/invoices")

        assert response.status_code == 503
        assert response.json()["detail"] == "Upstream auth/profile service unavailable"

    def test_403_no_customer_profile(self, client, monkeypatch, valid_user):
        """When customer_profile is None, returns 403."""
        app.dependency_overrides[get_current_user] = override_get_current_user(valid_user)
        mock_fetch_profile = AsyncMock(return_value=None)
        monkeypatch.setattr(invoices_module, "fetch_customer_profile", mock_fetch_profile)

        response = client.get("/invoices")

        assert response.status_code == 403
        assert response.json()["detail"] == "No customer profile found"

    def test_403_inactive_profile(self, client, monkeypatch, valid_user, inactive_profile):
        """When customer profile is_active=False, returns 403."""
        app.dependency_overrides[get_current_user] = override_get_current_user(valid_user)
        mock_fetch_profile = AsyncMock(return_value=inactive_profile)
        monkeypatch.setattr(invoices_module, "fetch_customer_profile", mock_fetch_profile)

        response = client.get("/invoices")

        assert response.status_code == 403
        assert response.json()["detail"] == "Customer profile is not active"


class TestInvoicesData:
    """Tests for data retrieval on GET /invoices."""

    def test_500_database_error(self, client, monkeypatch, valid_user, active_profile):
        """When repository raises exception, returns 500."""
        app.dependency_overrides[get_current_user] = override_get_current_user(valid_user)
        mock_fetch_profile = AsyncMock(return_value=active_profile)
        mock_list_invoices = AsyncMock(side_effect=Exception("DB connection failed"))

        monkeypatch.setattr(invoices_module, "fetch_customer_profile", mock_fetch_profile)
        monkeypatch.setattr(invoices_module, "list_invoices", mock_list_invoices)

        response = client.get("/invoices")

        assert response.status_code == 500
        assert response.json()["detail"] == "Error fetching invoices"

    def test_200_returns_invoices(self, client, monkeypatch, valid_user, active_profile):
        """When all checks pass, returns 200 with invoice list including invoice_id."""
        app.dependency_overrides[get_current_user] = override_get_current_user(valid_user)
        mock_fetch_profile = AsyncMock(return_value=active_profile)

        invoice_data = [
            {
                "ejercicio_factura": 2026,
                "clave_factura": "B",
                "documento_factura": "FV",
                "serie_factura": "",
                "numero_factura": "1",
                "factura": "FV-1",
                "fecha": "2026-01-01",
                "base_imponible": 1.0,
                "importe_iva": 0.21,
                "importe_total": 1.21,
            }
        ]
        mock_list_invoices = AsyncMock(return_value=invoice_data)

        monkeypatch.setattr(invoices_module, "fetch_customer_profile", mock_fetch_profile)
        monkeypatch.setattr(invoices_module, "list_invoices", mock_list_invoices)

        response = client.get("/invoices")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["factura"] == "FV-1"
        assert data[0]["fecha"] == "2026-01-01"
        assert data[0]["base_imponible"] == 1.0
        assert data[0]["importe_iva"] == 0.21
        assert data[0]["importe_total"] == 1.21
        # invoice_id must be present and decodable
        assert "invoice_id" in data[0]
        assert len(data[0]["invoice_id"]) > 0

    def test_200_empty_list(self, client, monkeypatch, valid_user, active_profile):
        """When no invoices found, returns 200 with empty list."""
        app.dependency_overrides[get_current_user] = override_get_current_user(valid_user)
        mock_fetch_profile = AsyncMock(return_value=active_profile)
        mock_list_invoices = AsyncMock(return_value=[])

        monkeypatch.setattr(invoices_module, "fetch_customer_profile", mock_fetch_profile)
        monkeypatch.setattr(invoices_module, "list_invoices", mock_list_invoices)

        response = client.get("/invoices")

        assert response.status_code == 200
        assert response.json() == []


class TestInvoiceId:
    """Tests for invoice_id encoding/decoding."""

    def test_roundtrip(self):
        """build_invoice_id → decode_invoice_id round-trips correctly."""
        row = {
            "ejercicio_factura": 2026,
            "clave_factura": "B",
            "documento_factura": "FV",
            "serie_factura": "",
            "numero_factura": "1",
        }
        token = build_invoice_id(row)
        decoded = decode_invoice_id(token)

        assert decoded["ejercicio"] == "2026"
        assert decoded["clave"] == "B"
        assert decoded["documento"] == "FV"
        assert decoded["serie"] == ""
        assert decoded["numero"] == "1"

    def test_decode_invalid_base64(self):
        """Invalid base64 raises ValueError."""
        with pytest.raises(ValueError, match="Cannot decode"):
            decode_invoice_id("!!!invalid!!!")

    def test_decode_wrong_field_count(self):
        """Base64 with wrong number of fields raises ValueError."""
        import base64
        bad = base64.urlsafe_b64encode(b"a|b|c").decode().rstrip("=")
        with pytest.raises(ValueError, match="Expected 5 fields"):
            decode_invoice_id(bad)
