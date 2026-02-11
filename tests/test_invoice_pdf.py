"""Tests for GET /invoices/{invoice_id}/pdf endpoint."""
import base64

import pytest
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.main import app
from app.api import invoice_pdf as pdf_module
from app.api.invoices import build_invoice_id
from app.core.auth import get_current_user, User
from app.core.supabase_admin import CustomerProfile


@pytest.fixture
def client():
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def valid_user():
    return User(sub="uuid-test", email="test@example.com", role="authenticated")


@pytest.fixture
def active_profile():
    return CustomerProfile(erp_clt_prov="443", is_active=True)


@pytest.fixture
def sample_invoice_id():
    """A well-formed invoice_id for ejercicio=2026, clave=B, documento=SV, serie='', numero=6355."""
    row = {
        "ejercicio_factura": 2026,
        "clave_factura": "B",
        "documento_factura": "SV",
        "serie_factura": "",
        "numero_factura": "6355",
    }
    return build_invoice_id(row)


def override_get_current_user(user: User):
    async def _override():
        return user
    return _override


class TestInvoicePdfAuth:
    """Authentication tests for PDF endpoint."""

    def test_401_without_token(self, client, sample_invoice_id):
        response = client.get(f"/invoices/{sample_invoice_id}/pdf")
        assert response.status_code == 401


class TestInvoicePdfValidation:
    """Validation and authorization tests."""

    def test_400_invalid_invoice_id(self, client, valid_user, monkeypatch, active_profile):
        """Malformed invoice_id returns 400."""
        app.dependency_overrides[get_current_user] = override_get_current_user(valid_user)
        monkeypatch.setattr(pdf_module, "fetch_customer_profile", AsyncMock(return_value=active_profile))

        response = client.get("/invoices/!!!not-valid!!!/pdf")
        assert response.status_code == 400
        assert response.json()["detail"] == "Invalid invoice_id"

    def test_400_wrong_field_count(self, client, valid_user, monkeypatch, active_profile):
        """Base64 with wrong number of pipe-separated fields returns 400."""
        app.dependency_overrides[get_current_user] = override_get_current_user(valid_user)
        monkeypatch.setattr(pdf_module, "fetch_customer_profile", AsyncMock(return_value=active_profile))

        bad_id = base64.urlsafe_b64encode(b"a|b|c").decode().rstrip("=")
        response = client.get(f"/invoices/{bad_id}/pdf")
        assert response.status_code == 400

    def test_404_invoice_not_in_db(self, client, monkeypatch, valid_user, active_profile, sample_invoice_id):
        """Invoice not found in database returns 404."""
        app.dependency_overrides[get_current_user] = override_get_current_user(valid_user)
        monkeypatch.setattr(pdf_module, "fetch_customer_profile", AsyncMock(return_value=active_profile))
        monkeypatch.setattr(pdf_module, "check_invoice_ownership", AsyncMock(return_value=None))

        response = client.get(f"/invoices/{sample_invoice_id}/pdf")
        assert response.status_code == 404
        assert response.json()["detail"] == "Invoice not found"

    def test_403_invoice_belongs_to_other_customer(
        self, client, monkeypatch, valid_user, active_profile, sample_invoice_id
    ):
        """Invoice exists but belongs to another customer returns 403."""
        app.dependency_overrides[get_current_user] = override_get_current_user(valid_user)
        monkeypatch.setattr(pdf_module, "fetch_customer_profile", AsyncMock(return_value=active_profile))
        # Owner is "999", but active_profile.erp_clt_prov is "443"
        monkeypatch.setattr(pdf_module, "check_invoice_ownership", AsyncMock(return_value="999"))

        response = client.get(f"/invoices/{sample_invoice_id}/pdf")
        assert response.status_code == 403
        assert response.json()["detail"] == "Invoice does not belong to customer"

    def test_409_pdf_not_generated(
        self, client, monkeypatch, valid_user, active_profile, sample_invoice_id, tmp_path
    ):
        """Invoice exists and belongs to customer but PDF file missing returns 409."""
        app.dependency_overrides[get_current_user] = override_get_current_user(valid_user)
        monkeypatch.setattr(pdf_module, "fetch_customer_profile", AsyncMock(return_value=active_profile))
        monkeypatch.setattr(pdf_module, "check_invoice_ownership", AsyncMock(return_value="443"))

        # Point pdf_base_dir to an empty tmp directory (no PDF file created)
        monkeypatch.setattr(pdf_module.settings, "pdf_base_dir", str(tmp_path / "invoices_issued"))

        response = client.get(f"/invoices/{sample_invoice_id}/pdf")
        assert response.status_code == 409
        assert response.json()["detail"] == "Invoice PDF not generated yet"


class TestInvoicePdfSuccess:
    """Happy-path test: PDF exists and is streamed."""

    def test_200_returns_pdf(
        self, client, monkeypatch, valid_user, active_profile, sample_invoice_id, tmp_path
    ):
        """When everything is valid and file exists, returns 200 with PDF content."""
        app.dependency_overrides[get_current_user] = override_get_current_user(valid_user)
        monkeypatch.setattr(pdf_module, "fetch_customer_profile", AsyncMock(return_value=active_profile))
        monkeypatch.setattr(pdf_module, "check_invoice_ownership", AsyncMock(return_value="443"))

        # Create the expected directory structure and a dummy PDF
        pdf_dir = tmp_path / "invoices_issued" / "2026" / "443"
        pdf_dir.mkdir(parents=True)
        pdf_file = pdf_dir / "Factura_SV6355.pdf"
        pdf_content = b"%PDF-1.4 dummy content"
        pdf_file.write_bytes(pdf_content)

        monkeypatch.setattr(pdf_module.settings, "pdf_base_dir", str(tmp_path / "invoices_issued"))

        response = client.get(f"/invoices/{sample_invoice_id}/pdf")

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        assert "Factura_SV6355.pdf" in response.headers["content-disposition"]
        assert response.content == pdf_content
