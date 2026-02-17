"""Tests for reparto_job — fully mocked, no real DB or Supabase."""
import pytest
from datetime import date
from unittest.mock import AsyncMock, patch

from app.jobs import reparto_job as job_module
from app.jobs.reparto_job import run_reparto_job, _build_notification, add_business_days
from app.core.supabase_admin import (
    CustomerProfileReparto,
    NotificationInsert,
    SupabaseUnavailableError,
)


def _make_profile(
    user_id="uid-1",
    erp_clt_prov="000962",
    dias_aviso_reparto=2,
) -> CustomerProfileReparto:
    return CustomerProfileReparto(
        user_id=user_id,
        erp_clt_prov=erp_clt_prov,
        dias_aviso_reparto=dias_aviso_reparto,
    )


def _make_reparto(
    clt_prov="000962",
    fecha=date(2026, 2, 19),
    ruta=1,
    subruta=0,
    grupo=10,
    subgrupo=1,
) -> dict:
    return {
        "clt_prov": clt_prov,
        "fecha": fecha,
        "ruta": ruta,
        "subruta": subruta,
        "grupo": grupo,
        "subgrupo": subgrupo,
    }


# ── add_business_days ─────────────────────────────────────────


class TestAddBusinessDays:
    """Test the business-day arithmetic helper."""

    def test_zero_days(self):
        """n=0 returns the same date."""
        assert add_business_days(date(2026, 2, 16), 0) == date(2026, 2, 16)

    def test_monday_plus_1(self):
        """Mon + 1 = Tue."""
        assert add_business_days(date(2026, 2, 16), 1) == date(2026, 2, 17)

    def test_monday_plus_2(self):
        """Mon + 2 = Wed."""
        assert add_business_days(date(2026, 2, 16), 2) == date(2026, 2, 18)

    def test_monday_plus_5(self):
        """Mon + 5 = Mon (next week)."""
        assert add_business_days(date(2026, 2, 16), 5) == date(2026, 2, 23)

    def test_friday_plus_1(self):
        """Fri + 1 = Mon (skips weekend)."""
        assert add_business_days(date(2026, 2, 20), 1) == date(2026, 2, 23)

    def test_friday_plus_2(self):
        """Fri + 2 = Tue (skips weekend)."""
        assert add_business_days(date(2026, 2, 20), 2) == date(2026, 2, 24)

    def test_thursday_plus_2(self):
        """Thu + 2 = Mon (crosses weekend)."""
        assert add_business_days(date(2026, 2, 19), 2) == date(2026, 2, 23)

    def test_saturday_plus_1(self):
        """Sat + 1 = Mon (starts on weekend)."""
        assert add_business_days(date(2026, 2, 21), 1) == date(2026, 2, 23)

    def test_sunday_plus_1(self):
        """Sun + 1 = Mon."""
        assert add_business_days(date(2026, 2, 22), 1) == date(2026, 2, 23)

    def test_wednesday_plus_3(self):
        """Wed + 3 = Mon (crosses weekend)."""
        assert add_business_days(date(2026, 2, 18), 3) == date(2026, 2, 23)

    def test_negative_raises(self):
        """Negative n must raise ValueError."""
        with pytest.raises(ValueError, match="n must be >= 0"):
            add_business_days(date(2026, 2, 16), -1)


# ── _build_notification ───────────────────────────────────────


class TestBuildNotification:
    """Test the notification builder helper."""

    def test_fields(self):
        profile = _make_profile()
        row = _make_reparto()
        target = date(2026, 2, 19)
        n = _build_notification(profile, row, target)

        assert n.user_id == "uid-1"
        assert n.type == "reparto"
        assert n.title == "🚚 Reparto programado"
        assert "19/02/2026" in n.body
        assert n.event_date == target
        assert n.data["clt_prov"] == "000962"
        assert n.data["fecha"] == "2026-02-19"
        assert n.data["ruta"] == 1
        assert n.data["subruta"] == 0
        assert n.data["grupo"] == 10
        assert n.data["subgrupo"] == 1
        assert n.source_key == "reparto:000962:1:0:2026-02-19"

    def test_body_in_spanish(self):
        profile = _make_profile()
        row = _make_reparto()
        n = _build_notification(profile, row, date(2026, 3, 5))
        assert n.body == "Cargamos para su zona el 05/03/2026.\nRealice su pedido antes de las 23:59 del día anterior."

    def test_source_key_includes_ruta_subruta(self):
        """source_key must distinguish different rutas for the same client+date."""
        profile = _make_profile()
        n1 = _build_notification(profile, _make_reparto(ruta=1, subruta=0), date(2026, 2, 19))
        n2 = _build_notification(profile, _make_reparto(ruta=2, subruta=1), date(2026, 2, 19))
        assert n1.source_key != n2.source_key


# ── run_reparto_job ──────────────────────────────────────────


class TestRunRepartoJob:
    """Test the main job function with mocked dependencies."""

    @pytest.mark.asyncio
    async def test_one_profile_two_repartos_all_inserted(self, monkeypatch):
        """1 profile, 2 routes → inserted=2."""
        profiles = [_make_profile()]
        repartos = [_make_reparto(ruta=1), _make_reparto(ruta=2)]

        monkeypatch.setattr(job_module, "fetch_reparto_profiles", AsyncMock(return_value=profiles))
        monkeypatch.setattr(job_module, "fetch_repartos_by_client", AsyncMock(return_value=repartos))
        monkeypatch.setattr(job_module, "insert_notification", AsyncMock(return_value=True))

        result = await run_reparto_job()

        assert result["total_profiles"] == 1
        assert result["total_rows"] == 2
        assert result["inserted"] == 2
        assert result["deduped"] == 0
        assert result["errors"] == 0

    @pytest.mark.asyncio
    async def test_one_profile_two_repartos_one_deduped(self, monkeypatch):
        """1 profile, 2 routes, 1 duplicate → inserted=1, deduped=1."""
        profiles = [_make_profile()]
        repartos = [_make_reparto(ruta=1), _make_reparto(ruta=2)]

        mock_insert = AsyncMock(side_effect=[True, False])

        monkeypatch.setattr(job_module, "fetch_reparto_profiles", AsyncMock(return_value=profiles))
        monkeypatch.setattr(job_module, "fetch_repartos_by_client", AsyncMock(return_value=repartos))
        monkeypatch.setattr(job_module, "insert_notification", mock_insert)

        result = await run_reparto_job()

        assert result["inserted"] == 1
        assert result["deduped"] == 1
        assert result["errors"] == 0

    @pytest.mark.asyncio
    async def test_no_profiles(self, monkeypatch):
        """No profiles → inserted=0, no errors."""
        monkeypatch.setattr(job_module, "fetch_reparto_profiles", AsyncMock(return_value=[]))

        result = await run_reparto_job()

        assert result["total_profiles"] == 0
        assert result["inserted"] == 0
        assert result["errors"] == 0

    @pytest.mark.asyncio
    async def test_uses_default_dias_when_none(self, monkeypatch):
        """Profile with dias_aviso_reparto=None uses settings.reparto_default_dias_aviso."""
        profile = _make_profile(dias_aviso_reparto=None)
        mock_fetch_repartos = AsyncMock(return_value=[])

        monkeypatch.setattr(job_module, "fetch_reparto_profiles", AsyncMock(return_value=[profile]))
        monkeypatch.setattr(job_module, "fetch_repartos_by_client", mock_fetch_repartos)

        today = date(2026, 2, 16)  # Monday
        monkeypatch.setattr(job_module, "date", type("FakeDate", (), {
            "today": staticmethod(lambda: today),
        }))

        await run_reparto_job()

        call_args = mock_fetch_repartos.call_args
        target_date = call_args[0][1]
        # default is 2 business days: Mon + 2 = Wed
        assert target_date == date(2026, 2, 18)

    @pytest.mark.asyncio
    async def test_uses_profile_dias(self, monkeypatch):
        """Profile with dias_aviso_reparto=5 uses that value."""
        profile = _make_profile(dias_aviso_reparto=5)
        mock_fetch_repartos = AsyncMock(return_value=[])

        monkeypatch.setattr(job_module, "fetch_reparto_profiles", AsyncMock(return_value=[profile]))
        monkeypatch.setattr(job_module, "fetch_repartos_by_client", mock_fetch_repartos)

        today = date(2026, 2, 16)  # Monday
        monkeypatch.setattr(job_module, "date", type("FakeDate", (), {
            "today": staticmethod(lambda: today),
        }))

        await run_reparto_job()

        call_args = mock_fetch_repartos.call_args
        target_date = call_args[0][1]
        # Mon + 5 business days = Mon next week
        assert target_date == date(2026, 2, 23)

    @pytest.mark.asyncio
    async def test_supabase_unavailable_on_profiles(self, monkeypatch):
        """SupabaseUnavailableError on fetch_profiles → errors=1, no crash."""
        monkeypatch.setattr(
            job_module,
            "fetch_reparto_profiles",
            AsyncMock(side_effect=SupabaseUnavailableError("down")),
        )

        result = await run_reparto_job()

        assert result["errors"] == 1
        assert result["total_profiles"] == 0

    @pytest.mark.asyncio
    async def test_mariadb_error_skips_profile(self, monkeypatch):
        """DB error on one profile doesn't crash the whole job."""
        profiles = [_make_profile(user_id="uid-1"), _make_profile(user_id="uid-2")]

        mock_fetch_repartos = AsyncMock(
            side_effect=[Exception("DB down"), [_make_reparto()]]
        )
        monkeypatch.setattr(job_module, "fetch_reparto_profiles", AsyncMock(return_value=profiles))
        monkeypatch.setattr(job_module, "fetch_repartos_by_client", mock_fetch_repartos)
        monkeypatch.setattr(job_module, "insert_notification", AsyncMock(return_value=True))

        result = await run_reparto_job()

        assert result["total_profiles"] == 2
        assert result["errors"] == 1
        assert result["inserted"] == 1

    @pytest.mark.asyncio
    async def test_no_repartos_for_profile(self, monkeypatch):
        """Profile with no routes for target_date → total_rows=0, no errors."""
        profiles = [_make_profile()]

        monkeypatch.setattr(job_module, "fetch_reparto_profiles", AsyncMock(return_value=profiles))
        monkeypatch.setattr(job_module, "fetch_repartos_by_client", AsyncMock(return_value=[]))
        # insert_notification should never be called
        mock_insert = AsyncMock(return_value=True)
        monkeypatch.setattr(job_module, "insert_notification", mock_insert)

        result = await run_reparto_job()

        assert result["total_profiles"] == 1
        assert result["total_rows"] == 0
        assert result["inserted"] == 0
        mock_insert.assert_not_called()

    @pytest.mark.asyncio
    async def test_supabase_unavailable_on_insert(self, monkeypatch):
        """SupabaseUnavailableError on insert → errors++, doesn't crash."""
        profiles = [_make_profile()]
        repartos = [_make_reparto()]

        monkeypatch.setattr(job_module, "fetch_reparto_profiles", AsyncMock(return_value=profiles))
        monkeypatch.setattr(job_module, "fetch_repartos_by_client", AsyncMock(return_value=repartos))
        monkeypatch.setattr(
            job_module,
            "insert_notification",
            AsyncMock(side_effect=SupabaseUnavailableError("down")),
        )

        result = await run_reparto_job()

        assert result["errors"] == 1
        assert result["inserted"] == 0
