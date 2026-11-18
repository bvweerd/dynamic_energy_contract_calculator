"""Tests for the contract-year date helpers."""

from datetime import date

from custom_components.dynamic_energy_contract_calculator.contract import (
    anniversary_in_year,
    is_anniversary,
    latest_anniversary,
    next_anniversary,
    parse_contract_date,
)


async def test_parse_contract_date() -> None:
    assert parse_contract_date("2025-03-15") == date(2025, 3, 15)
    assert parse_contract_date("2025-03-15T10:00:00") == date(2025, 3, 15)
    assert parse_contract_date("") is None
    assert parse_contract_date(None) is None
    assert parse_contract_date("not-a-date") is None


async def test_leap_day_anniversary_falls_back_to_february_28() -> None:
    start = date(2024, 2, 29)
    assert anniversary_in_year(start, 2025) == date(2025, 2, 28)
    assert anniversary_in_year(start, 2028) == date(2028, 2, 29)
    assert is_anniversary(start, date(2025, 2, 28))
    assert not is_anniversary(start, date(2025, 3, 1))


async def test_latest_and_next_anniversary() -> None:
    start = date(2025, 6, 1)
    assert latest_anniversary(start, date(2026, 5, 31)) == date(2025, 6, 1)
    assert latest_anniversary(start, date(2026, 6, 1)) == date(2026, 6, 1)
    assert next_anniversary(start, date(2026, 5, 31)) == date(2026, 6, 1)
    assert next_anniversary(start, date(2026, 6, 1)) == date(2027, 6, 1)
