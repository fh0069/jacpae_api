"""
Unit tests for src/app/core/date_utils.py

Covers:
  - min_allowed_date calculation
  - validate_date_range acceptance and rejection cases
"""
import pytest
from datetime import date
from unittest.mock import patch

from app.core.date_utils import min_allowed_date, validate_date_range


class TestMinAllowedDate:
    """Tests for min_allowed_date()."""

    def test_returns_jan_first_of_previous_year(self):
        """min_allowed_date returns Jan 1 of (current_year - 1)."""
        with patch("app.core.date_utils.date") as mock_date:
            mock_date.today.return_value = date(2026, 3, 12)
            mock_date.side_effect = lambda *args, **kwargs: date(*args, **kwargs)

            result = min_allowed_date()

        assert result == date(2025, 1, 1)

    def test_correct_year_boundary(self):
        """On Jan 1 of any year, min_allowed_date still points to Jan 1 previous year."""
        with patch("app.core.date_utils.date") as mock_date:
            mock_date.today.return_value = date(2026, 1, 1)
            mock_date.side_effect = lambda *args, **kwargs: date(*args, **kwargs)

            result = min_allowed_date()

        assert result == date(2025, 1, 1)

    def test_is_always_january_first(self):
        """min_allowed_date is always month=1, day=1."""
        result = min_allowed_date()
        assert result.month == 1
        assert result.day == 1


class TestValidateDateRange:
    """Tests for validate_date_range()."""

    def _today(self) -> date:
        return date.today()

    def _min_date(self) -> date:
        return min_allowed_date()

    def test_valid_range_is_accepted(self):
        """A start/end within allowed bounds raises no exception."""
        min_date = self._min_date()
        start = date(min_date.year, 6, 1)
        end = date(min_date.year, 6, 30)
        # Should not raise
        validate_date_range(start, end)

    def test_start_date_equals_min_allowed(self):
        """start_date == min_allowed_date is accepted."""
        start = self._min_date()
        end = date(start.year, 3, 31)
        validate_date_range(start, end)

    def test_start_date_before_min_allowed_raises(self):
        """start_date before min_allowed_date raises ValueError."""
        too_early = date(self._min_date().year - 1, 12, 31)
        end = date(self._today().year, 1, 31)

        with pytest.raises(ValueError, match="minimum allowed date"):
            validate_date_range(too_early, end)

    def test_end_date_in_future_raises(self):
        """end_date after today raises ValueError."""
        today = self._today()
        start = self._min_date()
        future = date(today.year + 1, 1, 1)

        with pytest.raises(ValueError, match="cannot be in the future"):
            validate_date_range(start, future)

    def test_end_date_before_start_date_raises(self):
        """end_date < start_date raises ValueError."""
        min_date = self._min_date()
        start = date(min_date.year, 6, 15)
        end = date(min_date.year, 6, 14)

        with pytest.raises(ValueError, match="must be >="):
            validate_date_range(start, end)

    def test_start_equals_end_is_valid(self):
        """start_date == end_date (same day range) is accepted."""
        today = self._today()
        validate_date_range(today, today)

    def test_end_date_equals_today_is_valid(self):
        """end_date == today is accepted."""
        today = self._today()
        start = self._min_date()
        validate_date_range(start, today)
