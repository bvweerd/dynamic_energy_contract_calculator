"""Contract-year date helpers shared by the sensor platform and trackers."""

from __future__ import annotations

import logging
from datetime import date, datetime

_LOGGER = logging.getLogger(__name__)


def parse_contract_date(value: str | None) -> date | None:
    """Parse an ISO date (or datetime) string, returning None when invalid."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).date()
    except (ValueError, TypeError, AttributeError):
        _LOGGER.debug("Ignoring invalid contract date %r", value)
        return None


def anniversary_in_year(start: date, year: int) -> date:
    """Return the contract anniversary in *year*.

    A contract that started on February 29 has its anniversary on February 28
    in years without a leap day.
    """
    try:
        return start.replace(year=year)
    except ValueError:
        return start.replace(year=year, day=28)


def latest_anniversary(start: date, today: date) -> date:
    """Return the most recent anniversary on or before *today*."""
    this_year = anniversary_in_year(start, today.year)
    if today >= this_year:
        return this_year
    return anniversary_in_year(start, today.year - 1)


def next_anniversary(start: date, today: date) -> date:
    """Return the first anniversary strictly after *today*."""
    this_year = anniversary_in_year(start, today.year)
    if today < this_year:
        return this_year
    return anniversary_in_year(start, today.year + 1)


def is_anniversary(start: date, check_date: date) -> bool:
    """Return whether *check_date* is a contract anniversary."""
    return check_date == anniversary_in_year(start, check_date.year)
