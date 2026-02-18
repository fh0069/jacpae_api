"""Tests for offer_job — fully mocked, no real filesystem or Supabase."""
import pytest
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock

import app.jobs.offer_job as job_module
from app.jobs.offer_job import run_offer_job, _build_notification, _parse_expiry
from app.core.supabase_admin import SupabaseUnavailableError


# ── helpers ───────────────────────────────────────────────────

def _fake_path(date_str: str = "20260301") -> Path:
    """Return a Path that matches the oferta_YYYYMMDD.pdf convention."""
    return Path(f"/fake/offers/oferta_{date_str}.pdf")


# ── _parse_expiry ─────────────────────────────────────────────


class TestParseExpiry:
    """Unit tests for the filename → date parser."""

    def test_standard_date(self):
        assert _parse_expiry(_fake_path("20260301")) == date(2026, 3, 1)

    def test_year_boundary(self):
        assert _parse_expiry(_fake_path("20261231")) == date(2026, 12, 31)

    def test_january(self):
        assert _parse_expiry(_fake_path("20260101")) == date(2026, 1, 1)


# ── _build_notification ───────────────────────────────────────


class TestBuildNotification:
    """Unit tests for the notification builder."""

    def test_all_fields(self):
        expiry = date(2026, 3, 1)
        n = _build_notification("uid-1", expiry)

        assert n.user_id == "uid-1"
        assert n.type == "oferta"
        assert n.title == "🎉 Nueva oferta disponible"
        assert n.event_date == expiry
        assert n.source_key == "oferta:2026-03-01"
        assert n.data["expiry"] == "2026-03-01"

    def test_body_exact_spanish(self):
        """Body must match the exact agreed wording."""
        n = _build_notification("uid-1", date(2026, 3, 5))
        expected = "Hay una nueva oferta disponible hasta el 05/03/2026."
        assert n.body == expected

    def test_source_key_format(self):
        """source_key is always 'oferta:YYYY-MM-DD'."""
        n = _build_notification("uid-x", date(2026, 12, 31))
        assert n.source_key == "oferta:2026-12-31"

    def test_source_key_is_same_for_all_users(self):
        """Two users notified for the same offer share the same source_key."""
        expiry = date(2026, 3, 1)
        n1 = _build_notification("uid-1", expiry)
        n2 = _build_notification("uid-2", expiry)
        assert n1.source_key == n2.source_key


# ── run_offer_job ─────────────────────────────────────────────


class TestRunOfferJob:
    """Integration tests for the main job function (all dependencies mocked)."""

    @pytest.mark.asyncio
    async def test_no_offer_returns_zeros(self, monkeypatch):
        """No active offer → job exits early, all counters are 0."""
        monkeypatch.setattr(
            job_module, "get_active_offer_path", AsyncMock(return_value=None)
        )

        result = await run_offer_job()

        assert result == {"total_users": 0, "inserted": 0, "deduped": 0, "errors": 0}

    @pytest.mark.asyncio
    async def test_offer_three_users_all_inserted(self, monkeypatch):
        """Offer + 3 active users → inserted=3, deduped=0, errors=0."""
        monkeypatch.setattr(
            job_module, "get_active_offer_path", AsyncMock(return_value=_fake_path())
        )
        monkeypatch.setattr(
            job_module,
            "fetch_active_user_ids",
            AsyncMock(return_value=["uid-1", "uid-2", "uid-3"]),
        )
        monkeypatch.setattr(job_module, "insert_notification", AsyncMock(return_value=True))

        result = await run_offer_job()

        assert result["total_users"] == 3
        assert result["inserted"] == 3
        assert result["deduped"] == 0
        assert result["errors"] == 0

    @pytest.mark.asyncio
    async def test_deduplication_partial(self, monkeypatch):
        """3 users, 2 already notified → inserted=1, deduped=2."""
        monkeypatch.setattr(
            job_module, "get_active_offer_path", AsyncMock(return_value=_fake_path())
        )
        monkeypatch.setattr(
            job_module,
            "fetch_active_user_ids",
            AsyncMock(return_value=["uid-1", "uid-2", "uid-3"]),
        )
        monkeypatch.setattr(
            job_module,
            "insert_notification",
            AsyncMock(side_effect=[False, False, True]),
        )

        result = await run_offer_job()

        assert result["inserted"] == 1
        assert result["deduped"] == 2
        assert result["errors"] == 0

    @pytest.mark.asyncio
    async def test_deduplication_all(self, monkeypatch):
        """All users already notified → inserted=0, deduped=3."""
        monkeypatch.setattr(
            job_module, "get_active_offer_path", AsyncMock(return_value=_fake_path())
        )
        monkeypatch.setattr(
            job_module,
            "fetch_active_user_ids",
            AsyncMock(return_value=["uid-1", "uid-2", "uid-3"]),
        )
        monkeypatch.setattr(job_module, "insert_notification", AsyncMock(return_value=False))

        result = await run_offer_job()

        assert result["inserted"] == 0
        assert result["deduped"] == 3
        assert result["errors"] == 0

    @pytest.mark.asyncio
    async def test_supabase_unavailable_on_fetch_users(self, monkeypatch):
        """SupabaseUnavailableError fetching users → errors=1, no crash."""
        monkeypatch.setattr(
            job_module, "get_active_offer_path", AsyncMock(return_value=_fake_path())
        )
        monkeypatch.setattr(
            job_module,
            "fetch_active_user_ids",
            AsyncMock(side_effect=SupabaseUnavailableError("down")),
        )

        result = await run_offer_job()

        assert result["errors"] == 1
        assert result["total_users"] == 0
        assert result["inserted"] == 0

    @pytest.mark.asyncio
    async def test_supabase_unavailable_on_insert_continues(self, monkeypatch):
        """SupabaseUnavailableError on one insert → errors++ but job continues."""
        monkeypatch.setattr(
            job_module, "get_active_offer_path", AsyncMock(return_value=_fake_path())
        )
        monkeypatch.setattr(
            job_module,
            "fetch_active_user_ids",
            AsyncMock(return_value=["uid-1", "uid-2"]),
        )
        monkeypatch.setattr(
            job_module,
            "insert_notification",
            AsyncMock(side_effect=[SupabaseUnavailableError("down"), True]),
        )

        result = await run_offer_job()

        assert result["errors"] == 1
        assert result["inserted"] == 1
        assert result["total_users"] == 2

    @pytest.mark.asyncio
    async def test_no_active_users(self, monkeypatch):
        """Offer exists but no active users → total_users=0, insert never called."""
        monkeypatch.setattr(
            job_module, "get_active_offer_path", AsyncMock(return_value=_fake_path())
        )
        monkeypatch.setattr(
            job_module, "fetch_active_user_ids", AsyncMock(return_value=[])
        )
        mock_insert = AsyncMock(return_value=True)
        monkeypatch.setattr(job_module, "insert_notification", mock_insert)

        result = await run_offer_job()

        assert result["total_users"] == 0
        assert result["inserted"] == 0
        mock_insert.assert_not_called()

    @pytest.mark.asyncio
    async def test_source_key_matches_expiry_date(self, monkeypatch):
        """Each notification carries source_key == 'oferta:YYYY-MM-DD'."""
        mock_insert = AsyncMock(return_value=True)
        monkeypatch.setattr(
            job_module,
            "get_active_offer_path",
            AsyncMock(return_value=_fake_path("20260301")),
        )
        monkeypatch.setattr(
            job_module, "fetch_active_user_ids", AsyncMock(return_value=["uid-1"])
        )
        monkeypatch.setattr(job_module, "insert_notification", mock_insert)

        await run_offer_job()

        inserted_notification = mock_insert.call_args[0][0]
        assert inserted_notification.source_key == "oferta:2026-03-01"

    @pytest.mark.asyncio
    async def test_notification_body_exact_wording(self, monkeypatch):
        """Body of each notification matches the exact agreed Spanish text."""
        mock_insert = AsyncMock(return_value=True)
        monkeypatch.setattr(
            job_module,
            "get_active_offer_path",
            AsyncMock(return_value=_fake_path("20260305")),
        )
        monkeypatch.setattr(
            job_module, "fetch_active_user_ids", AsyncMock(return_value=["uid-1"])
        )
        monkeypatch.setattr(job_module, "insert_notification", mock_insert)

        await run_offer_job()

        n = mock_insert.call_args[0][0]
        expected_body = "Hay una nueva oferta disponible hasta el 05/03/2026."
        assert n.body == expected_body
