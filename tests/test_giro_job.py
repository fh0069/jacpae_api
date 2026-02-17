"""Tests for giro_job — fully mocked, no real DB or Supabase."""
import pytest
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

from app.jobs import giro_job as job_module
from app.jobs.giro_job import run_giro_job, _build_notification
from app.core.supabase_admin import (
    CustomerProfileGiro,
    NotificationInsert,
    SupabaseUnavailableError,
)


def _make_profile(
    user_id="uid-1",
    cta_contable="430000962",
    dias_aviso_giro=5,
) -> CustomerProfileGiro:
    return CustomerProfileGiro(
        user_id=user_id,
        cta_contable=cta_contable,
        dias_aviso_giro=dias_aviso_giro,
    )


def _make_giro(
    cta_contable="430000962",
    num_efecto="R001",
    vencimiento=date(2026, 3, 1),
    importe=1500.00,
) -> dict:
    return {
        "cta_contable": cta_contable,
        "num_efecto": num_efecto,
        "vencimiento": vencimiento,
        "importe": importe,
    }


class TestBuildNotification:
    """Test the notification builder helper."""

    def test_fields(self):
        profile = _make_profile()
        giro = _make_giro()
        n = _build_notification(profile, giro)

        assert n.user_id == "uid-1"
        assert n.type == "giro"
        assert n.title == "Giro pendiente"
        assert "R001" in n.body
        assert "1500.00" in n.body
        assert "01/03/2026" in n.body
        assert n.event_date == date(2026, 3, 1)
        assert n.data["num_efecto"] == "R001"
        assert n.data["importe"] == 1500.00
        assert n.source_key == "giro:430000962:R001:2026-03-01"


class TestRunGiroJob:
    """Test the main job function with mocked dependencies."""

    @pytest.mark.asyncio
    async def test_one_profile_two_giros_all_inserted(self, monkeypatch):
        """1 profile, 2 giros → inserted=2."""
        profiles = [_make_profile()]
        giros = [_make_giro(num_efecto="R001"), _make_giro(num_efecto="S002")]

        monkeypatch.setattr(job_module, "fetch_giro_profiles", AsyncMock(return_value=profiles))
        monkeypatch.setattr(job_module, "fetch_giros_by_cta_contable", AsyncMock(return_value=giros))
        monkeypatch.setattr(job_module, "insert_notification", AsyncMock(return_value=True))

        result = await run_giro_job()

        assert result["total_profiles"] == 1
        assert result["total_rows"] == 2
        assert result["inserted"] == 2
        assert result["deduped"] == 0
        assert result["errors"] == 0

    @pytest.mark.asyncio
    async def test_one_profile_two_giros_one_deduped(self, monkeypatch):
        """1 profile, 2 giros, 1 duplicate → inserted=1, deduped=1."""
        profiles = [_make_profile()]
        giros = [_make_giro(num_efecto="R001"), _make_giro(num_efecto="S002")]

        mock_insert = AsyncMock(side_effect=[True, False])

        monkeypatch.setattr(job_module, "fetch_giro_profiles", AsyncMock(return_value=profiles))
        monkeypatch.setattr(job_module, "fetch_giros_by_cta_contable", AsyncMock(return_value=giros))
        monkeypatch.setattr(job_module, "insert_notification", mock_insert)

        result = await run_giro_job()

        assert result["inserted"] == 1
        assert result["deduped"] == 1
        assert result["errors"] == 0

    @pytest.mark.asyncio
    async def test_no_profiles(self, monkeypatch):
        """No profiles → inserted=0, no errors."""
        monkeypatch.setattr(job_module, "fetch_giro_profiles", AsyncMock(return_value=[]))

        result = await run_giro_job()

        assert result["total_profiles"] == 0
        assert result["inserted"] == 0
        assert result["errors"] == 0

    @pytest.mark.asyncio
    async def test_uses_default_dias_when_none(self, monkeypatch):
        """Profile with dias_aviso_giro=None uses settings.giro_default_dias_aviso."""
        profile = _make_profile(dias_aviso_giro=None)
        mock_fetch_giros = AsyncMock(return_value=[])

        monkeypatch.setattr(job_module, "fetch_giro_profiles", AsyncMock(return_value=[profile]))
        monkeypatch.setattr(job_module, "fetch_giros_by_cta_contable", mock_fetch_giros)

        # settings.giro_default_dias_aviso defaults to 5
        await run_giro_job()

        call_args = mock_fetch_giros.call_args
        from_date = call_args[0][1]
        to_date = call_args[0][2]
        assert (to_date - from_date).days == 5

    @pytest.mark.asyncio
    async def test_uses_profile_dias(self, monkeypatch):
        """Profile with dias_aviso_giro=10 uses that value."""
        profile = _make_profile(dias_aviso_giro=10)
        mock_fetch_giros = AsyncMock(return_value=[])

        monkeypatch.setattr(job_module, "fetch_giro_profiles", AsyncMock(return_value=[profile]))
        monkeypatch.setattr(job_module, "fetch_giros_by_cta_contable", mock_fetch_giros)

        await run_giro_job()

        call_args = mock_fetch_giros.call_args
        from_date = call_args[0][1]
        to_date = call_args[0][2]
        assert (to_date - from_date).days == 10

    @pytest.mark.asyncio
    async def test_supabase_unavailable_on_profiles(self, monkeypatch):
        """SupabaseUnavailableError on fetch_profiles → errors=1, no crash."""
        monkeypatch.setattr(
            job_module,
            "fetch_giro_profiles",
            AsyncMock(side_effect=SupabaseUnavailableError("down")),
        )

        result = await run_giro_job()

        assert result["errors"] == 1
        assert result["total_profiles"] == 0

    @pytest.mark.asyncio
    async def test_mariadb_error_skips_profile(self, monkeypatch):
        """DB error on one profile doesn't crash the whole job."""
        profiles = [_make_profile(user_id="uid-1"), _make_profile(user_id="uid-2")]

        mock_fetch_giros = AsyncMock(
            side_effect=[Exception("DB down"), [_make_giro()]]
        )
        monkeypatch.setattr(job_module, "fetch_giro_profiles", AsyncMock(return_value=profiles))
        monkeypatch.setattr(job_module, "fetch_giros_by_cta_contable", mock_fetch_giros)
        monkeypatch.setattr(job_module, "insert_notification", AsyncMock(return_value=True))

        result = await run_giro_job()

        assert result["total_profiles"] == 2
        assert result["errors"] == 1
        assert result["inserted"] == 1
