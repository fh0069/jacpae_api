"""
Financial date range utilities.

Provides reusable date validation logic aligned with Flutter client semantics:
  - start_date >= first day of the previous year (min_allowed_date)
  - end_date <= today
  - end_date >= start_date
  - dates formatted as YYYY-MM-DD

These functions are pure (no side effects) to keep them easily testable.
"""
from datetime import date


def min_allowed_date() -> date:
    """Return the minimum allowed start_date for financial queries.

    Always the 1st of January of the year prior to today.
    Example: in 2026 → 2025-01-01
    """
    today = date.today()
    return date(today.year - 1, 1, 1)


def validate_date_range(start_date: date, end_date: date) -> None:
    """Validate a financial date range against business rules.

    Checks (in order):
      1. start_date >= min_allowed_date()
      2. end_date <= today
      3. end_date >= start_date

    Raises:
        ValueError: with a descriptive message on the first violation found.
    """
    today = date.today()
    min_date = min_allowed_date()

    if start_date < min_date:
        raise ValueError(
            f"start_date {start_date.isoformat()} is before the minimum allowed date "
            f"{min_date.isoformat()}"
        )

    if end_date > today:
        raise ValueError(
            f"end_date {end_date.isoformat()} cannot be in the future"
        )

    if end_date < start_date:
        raise ValueError(
            f"end_date {end_date.isoformat()} must be >= start_date {start_date.isoformat()}"
        )
