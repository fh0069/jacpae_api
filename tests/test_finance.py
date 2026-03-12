"""Tests for GET /finance/ledger endpoint and finance service logic."""
import pytest
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.main import app
from app.api import finance as finance_module
from app.core.auth import get_current_user, User
from app.core.supabase_admin import CustomerProfile, SupabaseUnavailableError
from app.services.finance_service import _split_debe_haber, get_ledger


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


# ── Auth / profile guard tests ─────────────────────────────────

class TestLedgerAuth:
    """Authentication and authorisation guards on GET /finance/ledger."""

    def test_401_without_token(self, client):
        """Request without JWT returns 401."""
        response = client.get("/finance/ledger", params=_VALID_PARAMS)
        assert response.status_code == 401

    def test_503_supabase_unavailable(self, client, monkeypatch, valid_user):
        """Supabase 5xx surfaces as 503."""
        app.dependency_overrides[get_current_user] = override_get_current_user(valid_user)
        monkeypatch.setattr(
            finance_module, "fetch_customer_profile",
            AsyncMock(side_effect=SupabaseUnavailableError("down")),
        )
        response = client.get("/finance/ledger", params=_VALID_PARAMS)
        assert response.status_code == 503

    def test_403_no_customer_profile(self, client, monkeypatch, valid_user):
        """No profile row → 403."""
        app.dependency_overrides[get_current_user] = override_get_current_user(valid_user)
        monkeypatch.setattr(finance_module, "fetch_customer_profile", AsyncMock(return_value=None))
        response = client.get("/finance/ledger", params=_VALID_PARAMS)
        assert response.status_code == 403
        assert response.json()["detail"] == "No customer profile found"

    def test_403_inactive_profile(self, client, monkeypatch, valid_user):
        """Inactive profile → 403."""
        app.dependency_overrides[get_current_user] = override_get_current_user(valid_user)
        inactive = CustomerProfile(erp_clt_prov="X", is_active=False, cta_contable="430000962")
        monkeypatch.setattr(finance_module, "fetch_customer_profile", AsyncMock(return_value=inactive))
        response = client.get("/finance/ledger", params=_VALID_PARAMS)
        assert response.status_code == 403
        assert response.json()["detail"] == "Customer profile is not active"

    def test_403_no_cta_contable(self, client, monkeypatch, valid_user, active_profile_no_cta):
        """Profile with cta_contable=None → 403."""
        app.dependency_overrides[get_current_user] = override_get_current_user(valid_user)
        monkeypatch.setattr(
            finance_module, "fetch_customer_profile",
            AsyncMock(return_value=active_profile_no_cta),
        )
        response = client.get("/finance/ledger", params=_VALID_PARAMS)
        assert response.status_code == 403
        assert "accounting account" in response.json()["detail"]

    def test_403_empty_string_cta_contable(self, client, monkeypatch, valid_user):
        """Profile with cta_contable='' (empty string) also → 403."""
        app.dependency_overrides[get_current_user] = override_get_current_user(valid_user)
        profile = CustomerProfile(erp_clt_prov="X", is_active=True, cta_contable="")
        monkeypatch.setattr(finance_module, "fetch_customer_profile", AsyncMock(return_value=profile))
        response = client.get("/finance/ledger", params=_VALID_PARAMS)
        assert response.status_code == 403


# ── Date validation tests ──────────────────────────────────────

class TestLedgerDateValidation:
    """Date range validation on GET /finance/ledger."""

    def test_422_missing_start_date(self, client, monkeypatch, valid_user, active_profile_with_cta):
        """Missing start_date → 422 (FastAPI query param validation)."""
        app.dependency_overrides[get_current_user] = override_get_current_user(valid_user)
        monkeypatch.setattr(
            finance_module, "fetch_customer_profile",
            AsyncMock(return_value=active_profile_with_cta),
        )
        response = client.get("/finance/ledger", params={"end_date": "2025-03-31"})
        assert response.status_code == 422

    def test_422_end_before_start(self, client, monkeypatch, valid_user, active_profile_with_cta):
        """end_date < start_date → 422."""
        app.dependency_overrides[get_current_user] = override_get_current_user(valid_user)
        monkeypatch.setattr(
            finance_module, "fetch_customer_profile",
            AsyncMock(return_value=active_profile_with_cta),
        )
        response = client.get(
            "/finance/ledger",
            params={"start_date": "2025-06-01", "end_date": "2025-05-01"},
        )
        assert response.status_code == 422


# ── _split_debe_haber unit tests ───────────────────────────────

class TestSplitDebeHaber:
    """Unit tests for the DEBE flag transformation helper."""

    def test_debe_flag_0_goes_to_debe_column(self):
        """DEBE=0 → importe_debe=IMPORTE, importe_haber=0."""
        debe, haber = _split_debe_haber(Decimal("100.00"), 0)
        assert debe == Decimal("100.00")
        assert haber == Decimal("0")

    def test_debe_flag_1_goes_to_haber_column(self):
        """DEBE=1 → importe_debe=0, importe_haber=IMPORTE."""
        debe, haber = _split_debe_haber(Decimal("50.00"), 1)
        assert debe == Decimal("0")
        assert haber == Decimal("50.00")

    def test_debe_string_zero_is_normalised(self):
        """DEBE='0' (string) is accepted and treated as debe side."""
        debe, haber = _split_debe_haber(Decimal("100.00"), "0")
        assert debe == Decimal("100.00")
        assert haber == Decimal("0")

    def test_debe_string_one_is_normalised(self):
        """DEBE='1' (string) is accepted and treated as haber side."""
        debe, haber = _split_debe_haber(Decimal("50.00"), "1")
        assert debe == Decimal("0")
        assert haber == Decimal("50.00")

    def test_unexpected_integer_raises(self):
        """DEBE value outside 0/1 raises ValueError with descriptive message."""
        with pytest.raises(ValueError, match="Unexpected DEBE"):
            _split_debe_haber(Decimal("10.00"), 2)

    def test_none_raises(self):
        """DEBE=None raises ValueError."""
        with pytest.raises(ValueError, match="Unexpected DEBE"):
            _split_debe_haber(Decimal("10.00"), None)


# ── get_ledger service unit tests ──────────────────────────────

class TestGetLedgerService:
    """Unit tests for get_ledger service function (mocked repository)."""

    @pytest.mark.asyncio
    async def test_exercise_start_date_is_jan_first(self, monkeypatch):
        """exercise_start_date is always Jan 1 of start_date's year."""
        from app.services import finance_service as fs_module

        mock_fetch = AsyncMock(return_value=[])
        monkeypatch.setattr(fs_module, "fetch_ledger_entries", mock_fetch)

        result = await get_ledger(
            cta_contable="430000962",
            start_date=date(2025, 6, 1),
            end_date=date(2025, 6, 30),
        )

        assert result["exercise_start_date"] == date(2025, 1, 1)
        assert mock_fetch.call_args.kwargs["exercise_start_date"] == date(2025, 1, 1)

    @pytest.mark.asyncio
    async def test_pre_period_rows_affect_saldo_but_are_not_visible(self, monkeypatch):
        """Rows before start_date accumulate into saldo but are not returned."""
        from app.services import finance_service as fs_module

        rows = [
            # Jan row: pre-period, saldo += 200 but should NOT appear in items
            {"fecha": date(2025, 1, 15), "concepto": "Factura enero", "importe": Decimal("200.00"), "debe": 0},
            # Jun row: visible, saldo += 100 → total 300
            {"fecha": date(2025, 6, 1), "concepto": "Factura junio", "importe": Decimal("100.00"), "debe": 0},
        ]
        monkeypatch.setattr(fs_module, "fetch_ledger_entries", AsyncMock(return_value=rows))

        result = await get_ledger(
            cta_contable="430000962",
            start_date=date(2025, 6, 1),
            end_date=date(2025, 6, 30),
        )

        assert result["total_items"] == 1
        assert result["items"][0]["fecha"] == date(2025, 6, 1)
        assert result["items"][0]["saldo"] == Decimal("300.00")

    @pytest.mark.asyncio
    async def test_running_saldo_accumulates_correctly(self, monkeypatch):
        """saldo = previous_saldo + importe_debe − importe_haber for each row."""
        from app.services import finance_service as fs_module

        rows = [
            {"fecha": date(2025, 3, 1),  "concepto": "A", "importe": Decimal("1000.00"), "debe": 0},
            {"fecha": date(2025, 3, 5),  "concepto": "B", "importe": Decimal("400.00"),  "debe": 1},
            {"fecha": date(2025, 3, 10), "concepto": "C", "importe": Decimal("200.00"),  "debe": 0},
        ]
        monkeypatch.setattr(fs_module, "fetch_ledger_entries", AsyncMock(return_value=rows))

        result = await get_ledger(
            cta_contable="430000962",
            start_date=date(2025, 3, 1),
            end_date=date(2025, 3, 31),
        )

        items = result["items"]
        assert len(items) == 3
        assert items[0]["saldo"] == Decimal("1000.00")   # +1000
        assert items[1]["saldo"] == Decimal("600.00")    # 1000 - 400
        assert items[2]["saldo"] == Decimal("800.00")    # 600 + 200

    @pytest.mark.asyncio
    async def test_empty_repository_returns_empty_items(self, monkeypatch):
        """Empty result from repository returns zero total_items."""
        from app.services import finance_service as fs_module

        monkeypatch.setattr(fs_module, "fetch_ledger_entries", AsyncMock(return_value=[]))

        result = await get_ledger("430000962", date(2025, 1, 1), date(2025, 3, 31))

        assert result["total_items"] == 0
        assert result["items"] == []

    @pytest.mark.asyncio
    async def test_unexpected_debe_propagates_value_error(self, monkeypatch):
        """Row with unexpected DEBE value raises ValueError."""
        from app.services import finance_service as fs_module

        rows = [{"fecha": date(2025, 3, 1), "concepto": "X", "importe": Decimal("100.00"), "debe": 99}]
        monkeypatch.setattr(fs_module, "fetch_ledger_entries", AsyncMock(return_value=rows))

        with pytest.raises(ValueError, match="Unexpected DEBE"):
            await get_ledger("430000962", date(2025, 3, 1), date(2025, 3, 31))

    @pytest.mark.asyncio
    async def test_none_concepto_becomes_empty_string(self, monkeypatch):
        """CONCEPTO=None in raw row is normalised to empty string."""
        from app.services import finance_service as fs_module

        rows = [{"fecha": date(2025, 3, 1), "concepto": None, "importe": Decimal("50.00"), "debe": 0}]
        monkeypatch.setattr(fs_module, "fetch_ledger_entries", AsyncMock(return_value=rows))

        result = await get_ledger("430000962", date(2025, 3, 1), date(2025, 3, 31))

        assert result["items"][0]["concepto"] == ""

    @pytest.mark.asyncio
    async def test_importe_as_float_is_coerced_to_decimal(self, monkeypatch):
        """IMPORTE arriving as float (not Decimal) is handled without error."""
        from app.services import finance_service as fs_module

        rows = [{"fecha": date(2025, 3, 1), "concepto": "X", "importe": 75.5, "debe": 0}]
        monkeypatch.setattr(fs_module, "fetch_ledger_entries", AsyncMock(return_value=rows))

        result = await get_ledger("430000962", date(2025, 3, 1), date(2025, 3, 31))

        assert result["items"][0]["importe_debe"] == Decimal("75.5")
        assert result["items"][0]["importe_haber"] == Decimal("0")


# ── Endpoint integration-level tests ──────────────────────────

class TestLedgerEndpoint:
    """Endpoint-level tests mocking at the service boundary."""

    def test_500_on_db_error(self, client, monkeypatch, valid_user, active_profile_with_cta):
        """Generic exception from service → 500."""
        app.dependency_overrides[get_current_user] = override_get_current_user(valid_user)
        monkeypatch.setattr(
            finance_module, "fetch_customer_profile",
            AsyncMock(return_value=active_profile_with_cta),
        )
        monkeypatch.setattr(finance_module, "get_ledger", AsyncMock(side_effect=Exception("DB down")))

        response = client.get("/finance/ledger", params=_VALID_PARAMS)

        assert response.status_code == 500
        assert response.json()["detail"] == "Error fetching ledger"

    def test_200_returns_correct_ledger_response_shape(self, client, monkeypatch, valid_user, active_profile_with_cta):
        """Happy path: 200 with correct LedgerResponse structure."""
        app.dependency_overrides[get_current_user] = override_get_current_user(valid_user)
        monkeypatch.setattr(
            finance_module, "fetch_customer_profile",
            AsyncMock(return_value=active_profile_with_cta),
        )
        ledger_data = {
            "start_date": date(2025, 1, 1),
            "end_date": date(2025, 3, 31),
            "exercise_start_date": date(2025, 1, 1),
            "total_items": 1,
            "items": [
                {
                    "fecha": date(2025, 2, 10),
                    "concepto": "Factura",
                    "importe_debe": 500.0,
                    "importe_haber": 0.0,
                    "saldo": 500.0,
                }
            ],
        }
        monkeypatch.setattr(finance_module, "get_ledger", AsyncMock(return_value=ledger_data))

        response = client.get("/finance/ledger", params=_VALID_PARAMS)

        assert response.status_code == 200
        data = response.json()
        assert data["start_date"] == "2025-01-01"
        assert data["end_date"] == "2025-03-31"
        assert data["exercise_start_date"] == "2025-01-01"
        assert data["total_items"] == 1
        assert len(data["items"]) == 1
        item = data["items"][0]
        assert item["fecha"] == "2025-02-10"
        assert item["concepto"] == "Factura"
        assert item["importe_debe"] == 500.0
        assert item["importe_haber"] == 0.0
        assert item["saldo"] == 500.0
