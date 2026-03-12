"""Tests for GET /invoices/vat-list endpoint and invoice reporting service."""
import pytest
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.main import app
from app.api import invoice_reporting as ir_module
from app.core.auth import get_current_user, User
from app.core.supabase_admin import CustomerProfile, SupabaseUnavailableError
from app.services.invoice_reporting_service import get_vat_invoice_list


# ── Fixtures ───────────────────────────────────────────────────

@pytest.fixture
def client():
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def valid_user():
    return User(sub="uuid-test", email="test@example.com", role="authenticated")


@pytest.fixture
def active_profile_with_cta():
    return CustomerProfile(erp_clt_prov="X", is_active=True, cta_contable="430000962")


@pytest.fixture
def active_profile_no_cta():
    return CustomerProfile(erp_clt_prov="X", is_active=True, cta_contable=None)


def override_get_current_user(user: User):
    async def _override():
        return user
    return _override


_VALID_PARAMS = {"start_date": "2025-01-01", "end_date": "2025-03-31"}

# Reusable raw rows that mimic repository output
_RAW_ROWS = [
    {
        "fecha_fra": date(2025, 1, 10),
        "num_fra": "FV-001",
        "base_imp": Decimal("100.00"),
        "tipo_iva": Decimal("21.00"),
        "cuota_iva": Decimal("21.00"),
        "tipo_recargo": Decimal("0.00"),
        "cuota_recargo": Decimal("0.00"),
        "imp_total": Decimal("121.00"),
    },
    {
        "fecha_fra": date(2025, 2, 15),
        "num_fra": "FV-002",
        "base_imp": Decimal("200.00"),
        "tipo_iva": Decimal("21.00"),
        "cuota_iva": Decimal("42.00"),
        "tipo_recargo": Decimal("0.00"),
        "cuota_recargo": Decimal("0.00"),
        "imp_total": Decimal("242.00"),
    },
]


# ── Auth / profile guard tests ─────────────────────────────────

class TestVatListAuth:
    """Authentication and authorisation guards on GET /invoices/vat-list."""

    def test_401_without_token(self, client):
        """Request without JWT returns 401."""
        response = client.get("/invoices/vat-list", params=_VALID_PARAMS)
        assert response.status_code == 401

    def test_503_supabase_unavailable(self, client, monkeypatch, valid_user):
        """Supabase 5xx surfaces as 503."""
        app.dependency_overrides[get_current_user] = override_get_current_user(valid_user)
        monkeypatch.setattr(
            ir_module, "fetch_customer_profile",
            AsyncMock(side_effect=SupabaseUnavailableError("down")),
        )
        response = client.get("/invoices/vat-list", params=_VALID_PARAMS)
        assert response.status_code == 503

    def test_403_no_customer_profile(self, client, monkeypatch, valid_user):
        """No profile row → 403."""
        app.dependency_overrides[get_current_user] = override_get_current_user(valid_user)
        monkeypatch.setattr(ir_module, "fetch_customer_profile", AsyncMock(return_value=None))
        response = client.get("/invoices/vat-list", params=_VALID_PARAMS)
        assert response.status_code == 403
        assert response.json()["detail"] == "No customer profile found"

    def test_403_inactive_profile(self, client, monkeypatch, valid_user):
        """Inactive profile → 403."""
        app.dependency_overrides[get_current_user] = override_get_current_user(valid_user)
        inactive = CustomerProfile(erp_clt_prov="X", is_active=False, cta_contable="430000962")
        monkeypatch.setattr(ir_module, "fetch_customer_profile", AsyncMock(return_value=inactive))
        response = client.get("/invoices/vat-list", params=_VALID_PARAMS)
        assert response.status_code == 403
        assert response.json()["detail"] == "Customer profile is not active"

    def test_403_no_cta_contable(self, client, monkeypatch, valid_user, active_profile_no_cta):
        """Profile without cta_contable → 403."""
        app.dependency_overrides[get_current_user] = override_get_current_user(valid_user)
        monkeypatch.setattr(
            ir_module, "fetch_customer_profile",
            AsyncMock(return_value=active_profile_no_cta),
        )
        response = client.get("/invoices/vat-list", params=_VALID_PARAMS)
        assert response.status_code == 403
        assert "accounting account" in response.json()["detail"]

    def test_403_empty_string_cta_contable(self, client, monkeypatch, valid_user):
        """Profile with cta_contable='' → 403."""
        app.dependency_overrides[get_current_user] = override_get_current_user(valid_user)
        profile = CustomerProfile(erp_clt_prov="X", is_active=True, cta_contable="")
        monkeypatch.setattr(ir_module, "fetch_customer_profile", AsyncMock(return_value=profile))
        response = client.get("/invoices/vat-list", params=_VALID_PARAMS)
        assert response.status_code == 403


# ── Date validation tests ──────────────────────────────────────

class TestVatListDateValidation:
    """Date range validation on GET /invoices/vat-list."""

    def test_422_missing_start_date(self, client, monkeypatch, valid_user, active_profile_with_cta):
        """Missing start_date → 422."""
        app.dependency_overrides[get_current_user] = override_get_current_user(valid_user)
        monkeypatch.setattr(
            ir_module, "fetch_customer_profile",
            AsyncMock(return_value=active_profile_with_cta),
        )
        response = client.get("/invoices/vat-list", params={"end_date": "2025-03-31"})
        assert response.status_code == 422

    def test_422_end_before_start(self, client, monkeypatch, valid_user, active_profile_with_cta):
        """end_date < start_date → 422."""
        app.dependency_overrides[get_current_user] = override_get_current_user(valid_user)
        monkeypatch.setattr(
            ir_module, "fetch_customer_profile",
            AsyncMock(return_value=active_profile_with_cta),
        )
        response = client.get(
            "/invoices/vat-list",
            params={"start_date": "2025-06-01", "end_date": "2025-05-01"},
        )
        assert response.status_code == 422


# ── get_vat_invoice_list service unit tests ────────────────────

class TestGetVatInvoiceListService:
    """Unit tests for get_vat_invoice_list (mocked repository)."""

    @pytest.mark.asyncio
    async def test_correct_field_mapping(self, monkeypatch):
        """All row fields are correctly mapped into items."""
        from app.services import invoice_reporting_service as irs_module

        monkeypatch.setattr(irs_module, "fetch_vat_invoices", AsyncMock(return_value=_RAW_ROWS))

        result = await get_vat_invoice_list("430000962", date(2025, 1, 1), date(2025, 3, 31))

        assert len(result["items"]) == 2
        first = result["items"][0]
        assert first["fecha_fra"] == date(2025, 1, 10)
        assert first["num_fra"] == "FV-001"
        assert first["base_imp"] == Decimal("100.00")
        assert first["tipo_iva"] == Decimal("21.00")
        assert first["cuota_iva"] == Decimal("21.00")
        assert first["tipo_recargo"] == Decimal("0.00")
        assert first["cuota_recargo"] == Decimal("0.00")
        assert first["imp_total"] == Decimal("121.00")

    @pytest.mark.asyncio
    async def test_totals_are_summed_correctly(self, monkeypatch):
        """Totals accumulate base, iva, recargo, factura across all items."""
        from app.services import invoice_reporting_service as irs_module

        monkeypatch.setattr(irs_module, "fetch_vat_invoices", AsyncMock(return_value=_RAW_ROWS))

        result = await get_vat_invoice_list("430000962", date(2025, 1, 1), date(2025, 3, 31))

        totals = result["totals"]
        assert totals["total_base"] == Decimal("300.00")     # 100 + 200
        assert totals["total_iva"] == Decimal("63.00")       # 21 + 42
        assert totals["total_recargo"] == Decimal("0.00")    # 0 + 0
        assert totals["total_factura"] == Decimal("363.00")  # 121 + 242

    @pytest.mark.asyncio
    async def test_empty_rows_returns_zero_totals(self, monkeypatch):
        """Empty repository result gives zero totals and empty items."""
        from app.services import invoice_reporting_service as irs_module

        monkeypatch.setattr(irs_module, "fetch_vat_invoices", AsyncMock(return_value=[]))

        result = await get_vat_invoice_list("430000962", date(2025, 1, 1), date(2025, 3, 31))

        assert result["items"] == []
        assert result["totals"]["total_base"] == Decimal("0")
        assert result["totals"]["total_factura"] == Decimal("0")

    @pytest.mark.asyncio
    async def test_recargo_equivalencia_row_accumulates_correctly(self, monkeypatch):
        """Rows with recargo de equivalencia are handled correctly."""
        from app.services import invoice_reporting_service as irs_module

        rows_with_recargo = [
            {
                "fecha_fra": date(2025, 3, 1),
                "num_fra": "FV-010",
                "base_imp": Decimal("500.00"),
                "tipo_iva": Decimal("21.00"),
                "cuota_iva": Decimal("105.00"),
                "tipo_recargo": Decimal("5.20"),
                "cuota_recargo": Decimal("26.00"),
                "imp_total": Decimal("631.00"),
            }
        ]
        monkeypatch.setattr(irs_module, "fetch_vat_invoices", AsyncMock(return_value=rows_with_recargo))

        result = await get_vat_invoice_list("430000962", date(2025, 3, 1), date(2025, 3, 31))

        totals = result["totals"]
        assert totals["total_base"] == Decimal("500.00")
        assert totals["total_iva"] == Decimal("105.00")
        assert totals["total_recargo"] == Decimal("26.00")
        assert totals["total_factura"] == Decimal("631.00")

    @pytest.mark.asyncio
    async def test_repository_receives_cta_contable(self, monkeypatch):
        """Repository is called with cta_contable, not clt_prov."""
        from app.services import invoice_reporting_service as irs_module

        mock_fetch = AsyncMock(return_value=[])
        monkeypatch.setattr(irs_module, "fetch_vat_invoices", mock_fetch)

        await get_vat_invoice_list("430000962", date(2025, 1, 1), date(2025, 3, 31))

        call_kwargs = mock_fetch.call_args.kwargs
        assert call_kwargs["cta_contable"] == "430000962"
        assert call_kwargs["start_date"] == date(2025, 1, 1)
        assert call_kwargs["end_date"] == date(2025, 3, 31)


# ── Endpoint integration-level tests ──────────────────────────

class TestVatListEndpoint:
    """Endpoint-level tests mocking at the service boundary."""

    def test_500_on_db_error(self, client, monkeypatch, valid_user, active_profile_with_cta):
        """Generic exception from service → 500."""
        app.dependency_overrides[get_current_user] = override_get_current_user(valid_user)
        monkeypatch.setattr(
            ir_module, "fetch_customer_profile",
            AsyncMock(return_value=active_profile_with_cta),
        )
        monkeypatch.setattr(
            ir_module, "get_vat_invoice_list",
            AsyncMock(side_effect=Exception("DB down")),
        )
        response = client.get("/invoices/vat-list", params=_VALID_PARAMS)
        assert response.status_code == 500
        assert response.json()["detail"] == "Error fetching VAT invoice list"

    def test_200_returns_correct_response_shape(self, client, monkeypatch, valid_user, active_profile_with_cta):
        """Happy path: 200 with correct VatInvoiceListResponse structure."""
        app.dependency_overrides[get_current_user] = override_get_current_user(valid_user)
        monkeypatch.setattr(
            ir_module, "fetch_customer_profile",
            AsyncMock(return_value=active_profile_with_cta),
        )
        mock_result = {
            "items": [
                {
                    "fecha_fra": date(2025, 1, 10),
                    "num_fra": "FV-001",
                    "base_imp": Decimal("100.00"),
                    "tipo_iva": Decimal("21.00"),
                    "cuota_iva": Decimal("21.00"),
                    "tipo_recargo": Decimal("0.00"),
                    "cuota_recargo": Decimal("0.00"),
                    "imp_total": Decimal("121.00"),
                }
            ],
            "totals": {
                "total_base": Decimal("100.00"),
                "total_iva": Decimal("21.00"),
                "total_recargo": Decimal("0.00"),
                "total_factura": Decimal("121.00"),
            },
        }
        monkeypatch.setattr(ir_module, "get_vat_invoice_list", AsyncMock(return_value=mock_result))

        response = client.get("/invoices/vat-list", params=_VALID_PARAMS)

        assert response.status_code == 200
        data = response.json()

        assert len(data["items"]) == 1
        item = data["items"][0]
        assert item["fecha_fra"] == "2025-01-10"
        assert item["num_fra"] == "FV-001"
        assert item["base_imp"] == pytest.approx(100.0)
        assert item["tipo_iva"] == pytest.approx(21.0)
        assert item["cuota_iva"] == pytest.approx(21.0)
        assert item["tipo_recargo"] == pytest.approx(0.0)
        assert item["cuota_recargo"] == pytest.approx(0.0)
        assert item["imp_total"] == pytest.approx(121.0)

        totals = data["totals"]
        assert totals["total_base"] == pytest.approx(100.0)
        assert totals["total_iva"] == pytest.approx(21.0)
        assert totals["total_recargo"] == pytest.approx(0.0)
        assert totals["total_factura"] == pytest.approx(121.0)

    def test_200_empty_items_with_zero_totals(self, client, monkeypatch, valid_user, active_profile_with_cta):
        """Empty result returns empty items and zero totals."""
        app.dependency_overrides[get_current_user] = override_get_current_user(valid_user)
        monkeypatch.setattr(
            ir_module, "fetch_customer_profile",
            AsyncMock(return_value=active_profile_with_cta),
        )
        mock_result = {
            "items": [],
            "totals": {
                "total_base": Decimal("0"),
                "total_iva": Decimal("0"),
                "total_recargo": Decimal("0"),
                "total_factura": Decimal("0"),
            },
        }
        monkeypatch.setattr(ir_module, "get_vat_invoice_list", AsyncMock(return_value=mock_result))

        response = client.get("/invoices/vat-list", params=_VALID_PARAMS)

        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []
        assert data["totals"]["total_base"] == pytest.approx(0.0)
        assert data["totals"]["total_factura"] == pytest.approx(0.0)
