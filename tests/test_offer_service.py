"""Tests for offer_service.get_active_offer_path — fully mocked filesystem."""
import pytest
from datetime import date
from pathlib import Path

import app.services.offer_service as offer_module
from app.services.offer_service import get_active_offer_path


# ── helpers ───────────────────────────────────────────────────

def _fake_today(frozen: date):
    """
    Return a drop-in replacement for the `date` class that freezes today().

    Must be a real subclass of `date` so that `date(year, month, day)`
    constructor calls inside the service still work correctly.
    """
    class FakeDate(date):
        @classmethod
        def today(cls):
            return frozen

    return FakeDate


def _setup(monkeypatch, tmp_path) -> Path:
    """Point pdf_base_dir at tmp_path and return the offers sub-directory."""
    monkeypatch.setattr(offer_module.settings, "pdf_base_dir", str(tmp_path))
    offers_dir = tmp_path / "offers"
    offers_dir.mkdir()
    return offers_dir


# ── test cases ────────────────────────────────────────────────


class TestGetActiveOfferPath:
    """Full coverage of the discovery + selection logic."""

    # ── folder-existence edge cases ───────────────────────────

    @pytest.mark.asyncio
    async def test_no_folder_returns_none(self, monkeypatch, tmp_path):
        """offers/ directory does not exist → None, no exception raised."""
        # Point base_dir at tmp_path which has NO 'offers' sub-dir
        monkeypatch.setattr(offer_module.settings, "pdf_base_dir", str(tmp_path / "absent"))

        result = await get_active_offer_path()

        assert result is None

    @pytest.mark.asyncio
    async def test_empty_folder_returns_none(self, monkeypatch, tmp_path):
        """offers/ exists but contains no files → None."""
        _setup(monkeypatch, tmp_path)

        result = await get_active_offer_path()

        assert result is None

    # ── single-offer cases ────────────────────────────────────

    @pytest.mark.asyncio
    async def test_single_valid_offer(self, monkeypatch, tmp_path):
        """One offer with expiry > today → its path is returned."""
        offers_dir = _setup(monkeypatch, tmp_path)
        monkeypatch.setattr(offer_module, "date", _fake_today(date(2026, 2, 18)))

        pdf = offers_dir / "oferta_20260301.pdf"
        pdf.write_bytes(b"%PDF")

        result = await get_active_offer_path()

        assert result == pdf

    @pytest.mark.asyncio
    async def test_offer_valid_on_expiry_day(self, monkeypatch, tmp_path):
        """Offer whose expiry == today is still active (>= today)."""
        offers_dir = _setup(monkeypatch, tmp_path)
        today = date(2026, 2, 18)
        monkeypatch.setattr(offer_module, "date", _fake_today(today))

        pdf = offers_dir / "oferta_20260218.pdf"
        pdf.write_bytes(b"%PDF")

        result = await get_active_offer_path()

        assert result == pdf

    @pytest.mark.asyncio
    async def test_expired_offer_returns_none(self, monkeypatch, tmp_path):
        """Offer with expiry < today → None."""
        offers_dir = _setup(monkeypatch, tmp_path)
        monkeypatch.setattr(offer_module, "date", _fake_today(date(2026, 2, 18)))

        (offers_dir / "oferta_20260101.pdf").write_bytes(b"%PDF")

        result = await get_active_offer_path()

        assert result is None

    # ── multi-offer selection ─────────────────────────────────

    @pytest.mark.asyncio
    async def test_multiple_valid_returns_nearest(self, monkeypatch, tmp_path):
        """Multiple valid offers → the one with the nearest (earliest) expiry wins."""
        offers_dir = _setup(monkeypatch, tmp_path)
        monkeypatch.setattr(offer_module, "date", _fake_today(date(2026, 2, 18)))

        near = offers_dir / "oferta_20260225.pdf"
        far = offers_dir / "oferta_20260310.pdf"
        near.write_bytes(b"%PDF")
        far.write_bytes(b"%PDF")

        result = await get_active_offer_path()

        assert result == near

    @pytest.mark.asyncio
    async def test_mix_valid_and_expired_returns_best_valid(self, monkeypatch, tmp_path):
        """Mix of valid and expired → only the valid one is a candidate."""
        offers_dir = _setup(monkeypatch, tmp_path)
        monkeypatch.setattr(offer_module, "date", _fake_today(date(2026, 2, 18)))

        (offers_dir / "oferta_20260101.pdf").write_bytes(b"%PDF")  # expired
        valid = offers_dir / "oferta_20260301.pdf"
        valid.write_bytes(b"%PDF")

        result = await get_active_offer_path()

        assert result == valid

    @pytest.mark.asyncio
    async def test_three_valid_returns_closest(self, monkeypatch, tmp_path):
        """Three valid offers with different expiries → closest is selected."""
        offers_dir = _setup(monkeypatch, tmp_path)
        monkeypatch.setattr(offer_module, "date", _fake_today(date(2026, 2, 18)))

        (offers_dir / "oferta_20260401.pdf").write_bytes(b"%PDF")
        closest = offers_dir / "oferta_20260220.pdf"
        closest.write_bytes(b"%PDF")
        (offers_dir / "oferta_20260315.pdf").write_bytes(b"%PDF")

        result = await get_active_offer_path()

        assert result == closest

    # ── naming / pattern edge cases ───────────────────────────

    @pytest.mark.asyncio
    async def test_invalid_filenames_ignored(self, monkeypatch, tmp_path):
        """Files that don't match oferta_YYYYMMDD.pdf are silently ignored."""
        offers_dir = _setup(monkeypatch, tmp_path)
        monkeypatch.setattr(offer_module, "date", _fake_today(date(2026, 2, 18)))

        # Various wrong names
        (offers_dir / "oferta.pdf").write_bytes(b"%PDF")
        (offers_dir / "promo_20260301.pdf").write_bytes(b"%PDF")
        (offers_dir / "oferta_2026030.pdf").write_bytes(b"%PDF")    # 7 digits
        (offers_dir / "oferta_202603011.pdf").write_bytes(b"%PDF")  # 9 digits
        (offers_dir / "OFERTA_20260301.pdf").write_bytes(b"%PDF")   # wrong case
        (offers_dir / "oferta_20260301.PDF").write_bytes(b"%PDF")   # wrong extension case
        (offers_dir / "thumbnail.png").write_bytes(b"\x89PNG")

        result = await get_active_offer_path()

        assert result is None

    @pytest.mark.asyncio
    async def test_invalid_date_digits_ignored(self, monkeypatch, tmp_path):
        """8 digits that form an impossible date (month=13) are skipped with a warning."""
        offers_dir = _setup(monkeypatch, tmp_path)
        monkeypatch.setattr(offer_module, "date", _fake_today(date(2026, 2, 18)))

        (offers_dir / "oferta_20261399.pdf").write_bytes(b"%PDF")

        result = await get_active_offer_path()

        assert result is None

    @pytest.mark.asyncio
    async def test_invalid_date_day_zero_ignored(self, monkeypatch, tmp_path):
        """Day=00 is also an impossible date and must be skipped."""
        offers_dir = _setup(monkeypatch, tmp_path)
        monkeypatch.setattr(offer_module, "date", _fake_today(date(2026, 2, 18)))

        (offers_dir / "oferta_20260200.pdf").write_bytes(b"%PDF")

        result = await get_active_offer_path()

        assert result is None

    # ── non-file entries ──────────────────────────────────────

    @pytest.mark.asyncio
    async def test_subdirectory_not_treated_as_offer(self, monkeypatch, tmp_path):
        """A subdirectory whose name matches the pattern is not returned."""
        offers_dir = _setup(monkeypatch, tmp_path)
        monkeypatch.setattr(offer_module, "date", _fake_today(date(2026, 2, 18)))

        subdir = offers_dir / "oferta_20260301.pdf"
        subdir.mkdir()  # same name as a valid offer but it's a directory

        result = await get_active_offer_path()

        assert result is None
