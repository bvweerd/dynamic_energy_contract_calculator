"""Tests for the NetworkTariffCalculator."""

from datetime import datetime, timedelta, timezone

import pytest

from custom_components.dynamic_energy_contract_calculator.network_tariff import (
    BAND_SUMMER_OFFPEAK,
    BAND_SUMMER_PEAK,
    BAND_WINTER_OFFPEAK,
    BAND_WINTER_PEAK,
    NetworkTariffCalculator,
    NetworkTariffResult,
)

# Use a fixed UTC+1 offset (representative of Netherlands in winter)
_TZ = timezone(timedelta(hours=1))

# Jan 1, 2029 is a Monday (weekday=0). Use that as a reference.
_MONDAY_JAN_2029 = datetime(2029, 1, 7, 0, 0, 0, tzinfo=_TZ)  # Monday


def _dt(month: int, hour: int, weekday: int) -> datetime:
    """Build a datetime in 2029 with the given month, hour, and weekday (0=Mon, 6=Sun)."""
    base = datetime(2029, month, 1, 0, 0, 0, tzinfo=_TZ)
    days_offset = (weekday - base.weekday()) % 7
    return (base + timedelta(days=days_offset)).replace(hour=hour)


_SETTINGS: dict = {
    "network_tariff_enabled": True,
    "network_tariff_winter_peak_per_kwh": 0.09,
    "network_tariff_winter_offpeak_per_kwh": 0.025,
    "network_tariff_summer_peak_per_kwh": 0.045,
    "network_tariff_summer_offpeak_per_kwh": 0.013,
    "network_tariff_peak_start_hour": 7,
    "network_tariff_peak_end_hour": 23,
    "network_tariff_winter_start_month": 11,
    "network_tariff_winter_end_month": 3,
}


# ---------------------------------------------------------------------------
# Disabled state
# ---------------------------------------------------------------------------


async def test_disabled_returns_zero_rate() -> None:
    calc = NetworkTariffCalculator({"network_tariff_enabled": False})
    result = calc.get_tariff_for_datetime(_dt(month=1, hour=12, weekday=0))
    assert result.band == "disabled"
    assert result.tariff_per_kwh == 0.0


async def test_disabled_by_default() -> None:
    calc = NetworkTariffCalculator({})
    result = calc.get_tariff_for_datetime(_dt(month=1, hour=12, weekday=0))
    assert result.band == "disabled"


# ---------------------------------------------------------------------------
# Band assignment — all four quadrants
# ---------------------------------------------------------------------------


async def test_winter_peak_weekday_midday() -> None:
    calc = NetworkTariffCalculator(_SETTINGS)
    result = calc.get_tariff_for_datetime(_dt(month=1, hour=12, weekday=0))
    assert result.band == BAND_WINTER_PEAK
    assert result.tariff_per_kwh == pytest.approx(0.09)


async def test_winter_offpeak_night_weekday() -> None:
    calc = NetworkTariffCalculator(_SETTINGS)
    result = calc.get_tariff_for_datetime(_dt(month=1, hour=3, weekday=0))
    assert result.band == BAND_WINTER_OFFPEAK
    assert result.tariff_per_kwh == pytest.approx(0.025)


async def test_winter_offpeak_weekend() -> None:
    calc = NetworkTariffCalculator(_SETTINGS)
    # Saturday midday — no peak tariff on weekends
    result = calc.get_tariff_for_datetime(_dt(month=1, hour=12, weekday=5))
    assert result.band == BAND_WINTER_OFFPEAK
    assert result.tariff_per_kwh == pytest.approx(0.025)


async def test_winter_offpeak_sunday() -> None:
    calc = NetworkTariffCalculator(_SETTINGS)
    result = calc.get_tariff_for_datetime(_dt(month=1, hour=15, weekday=6))
    assert result.band == BAND_WINTER_OFFPEAK


async def test_summer_peak_weekday() -> None:
    calc = NetworkTariffCalculator(_SETTINGS)
    result = calc.get_tariff_for_datetime(_dt(month=7, hour=15, weekday=2))
    assert result.band == BAND_SUMMER_PEAK
    assert result.tariff_per_kwh == pytest.approx(0.045)


async def test_summer_offpeak_weekend() -> None:
    calc = NetworkTariffCalculator(_SETTINGS)
    result = calc.get_tariff_for_datetime(_dt(month=7, hour=15, weekday=5))
    assert result.band == BAND_SUMMER_OFFPEAK
    assert result.tariff_per_kwh == pytest.approx(0.013)


async def test_summer_offpeak_night() -> None:
    calc = NetworkTariffCalculator(_SETTINGS)
    result = calc.get_tariff_for_datetime(_dt(month=6, hour=2, weekday=1))
    assert result.band == BAND_SUMMER_OFFPEAK


# ---------------------------------------------------------------------------
# Season boundaries
# ---------------------------------------------------------------------------


async def test_november_is_winter() -> None:
    calc = NetworkTariffCalculator(_SETTINGS)
    assert calc.get_tariff_for_datetime(_dt(month=11, hour=12, weekday=0)).band == BAND_WINTER_PEAK


async def test_december_is_winter() -> None:
    calc = NetworkTariffCalculator(_SETTINGS)
    assert calc.get_tariff_for_datetime(_dt(month=12, hour=12, weekday=0)).band == BAND_WINTER_PEAK


async def test_january_is_winter() -> None:
    calc = NetworkTariffCalculator(_SETTINGS)
    assert calc.get_tariff_for_datetime(_dt(month=1, hour=12, weekday=0)).band == BAND_WINTER_PEAK


async def test_march_is_winter() -> None:
    calc = NetworkTariffCalculator(_SETTINGS)
    assert calc.get_tariff_for_datetime(_dt(month=3, hour=12, weekday=0)).band == BAND_WINTER_PEAK


async def test_april_is_summer() -> None:
    calc = NetworkTariffCalculator(_SETTINGS)
    assert calc.get_tariff_for_datetime(_dt(month=4, hour=12, weekday=0)).band == BAND_SUMMER_PEAK


async def test_october_is_summer() -> None:
    calc = NetworkTariffCalculator(_SETTINGS)
    assert calc.get_tariff_for_datetime(_dt(month=10, hour=12, weekday=0)).band == BAND_SUMMER_PEAK


# ---------------------------------------------------------------------------
# Peak hour boundaries
# ---------------------------------------------------------------------------


async def test_peak_starts_at_configured_hour() -> None:
    calc = NetworkTariffCalculator(_SETTINGS)
    # Hour 7 is included (start_hour=7 inclusive)
    assert calc.get_tariff_for_datetime(_dt(month=1, hour=7, weekday=0)).band == BAND_WINTER_PEAK


async def test_before_peak_is_offpeak() -> None:
    calc = NetworkTariffCalculator(_SETTINGS)
    assert calc.get_tariff_for_datetime(_dt(month=1, hour=6, weekday=0)).band == BAND_WINTER_OFFPEAK


async def test_last_peak_hour() -> None:
    calc = NetworkTariffCalculator(_SETTINGS)
    # end_hour=23 exclusive → hour 22 is peak, hour 23 is off-peak
    assert calc.get_tariff_for_datetime(_dt(month=1, hour=22, weekday=0)).band == BAND_WINTER_PEAK


async def test_end_hour_is_offpeak() -> None:
    calc = NetworkTariffCalculator(_SETTINGS)
    assert calc.get_tariff_for_datetime(_dt(month=1, hour=23, weekday=0)).band == BAND_WINTER_OFFPEAK


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


async def test_missing_rates_default_to_zero() -> None:
    calc = NetworkTariffCalculator({"network_tariff_enabled": True})
    result = calc.get_tariff_for_datetime(_dt(month=1, hour=12, weekday=0))
    assert result.band == BAND_WINTER_PEAK
    assert result.tariff_per_kwh == 0.0


async def test_update_price_settings_enables_tariff() -> None:
    calc = NetworkTariffCalculator({"network_tariff_enabled": False})
    assert not calc.enabled
    calc.update_price_settings(_SETTINGS)
    assert calc.enabled
    result = calc.get_tariff_for_datetime(_dt(month=1, hour=12, weekday=0))
    assert result.band == BAND_WINTER_PEAK
    assert result.tariff_per_kwh == pytest.approx(0.09)


async def test_winter_wraps_year_boundary() -> None:
    """Season Nov–Mar wraps the year; a summer start/end without wrapping would fail."""
    # Custom settings: winter = Aug–Feb (wraps)
    settings = {**_SETTINGS, "network_tariff_winter_start_month": 8, "network_tariff_winter_end_month": 2}
    calc = NetworkTariffCalculator(settings)
    # December should be winter
    assert calc.get_tariff_for_datetime(_dt(month=12, hour=12, weekday=0)).band == BAND_WINTER_PEAK
    # March should now be summer
    assert calc.get_tariff_for_datetime(_dt(month=3, hour=12, weekday=0)).band == BAND_SUMMER_PEAK


async def test_network_tariff_result_dataclass() -> None:
    result = NetworkTariffResult(band=BAND_WINTER_PEAK, tariff_per_kwh=0.09)
    assert result.band == BAND_WINTER_PEAK
    assert result.tariff_per_kwh == pytest.approx(0.09)
