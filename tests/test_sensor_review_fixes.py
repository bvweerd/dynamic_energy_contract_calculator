"""Regression tests for sensor platform fixes from the full code review."""

from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import DeviceInfo
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dynamic_energy_contract_calculator import RuntimeData
from custom_components.dynamic_energy_contract_calculator import sensor as sensor_module
from custom_components.dynamic_energy_contract_calculator.const import (
    CONF_PRICE_SENSOR,
    CONF_PRICE_SETTINGS,
    CONF_SOURCE_TYPE,
    CONF_SOURCES,
    DOMAIN,
    SOURCE_TYPE_CONSUMPTION,
    SOURCE_TYPE_PRODUCTION,
    SUBENTRY_TYPE_SOURCE,
)
from custom_components.dynamic_energy_contract_calculator.device_compat import (
    device_in_main_entry,
    device_subentry_ids,
)
from custom_components.dynamic_energy_contract_calculator.sensor import (
    CurrentElectricityPriceSensor,
    DailyElectricityCostSensor,
    SolarBonusStatusSensor,
    _ContractYearReset,
    async_setup_entry,
)
from custom_components.dynamic_energy_contract_calculator.solar_bonus import (
    SolarBonusTracker,
)

DEVICE = DeviceInfo(identifiers={("d", "review")})


def _price_sensor(hass, source_type=SOURCE_TYPE_PRODUCTION, **kwargs):
    settings = {"vat_percentage": 21.0, **kwargs.pop("settings", {})}
    return CurrentElectricityPriceSensor(
        hass,
        "Review Price",
        "review-price",
        price_sensor=kwargs.pop("price_sensor", "sensor.price"),
        source_type=source_type,
        price_settings=settings,
        icon="mdi:flash",
        device=DEVICE,
        **kwargs,
    )


class _LimitTracker:
    def __init__(self, reached: bool) -> None:
        self.reached = reached

    def limit_reached(self, annual_limit_kwh: float) -> bool:
        return self.reached


async def test_price_bonus_is_on_the_price_without_vat(hass: HomeAssistant):
    """The tracker books the bonus on base + markup without VAT; so must the price."""
    sensor = _price_sensor(
        hass,
        settings={
            "production_price_include_vat": True,
            "per_unit_supplier_electricity_production_markup": 0.02,
            "solar_bonus_enabled": True,
            "solar_bonus_percentage": 10.0,
        },
    )
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(sensor, "_is_in_bonus_window_at", lambda ts: True)
        price = sensor._price_with_solar_bonus(0.10)
    # 0.12 * 1.21 compensation plus 10% of 0.12 bonus (what the tracker pays)
    assert price == pytest.approx(0.12 * 1.21 + 0.012)


async def test_price_has_no_bonus_once_limit_reached(hass: HomeAssistant):
    settings = {
        "production_price_include_vat": False,
        "vat_percentage": 0.0,
        "solar_bonus_enabled": True,
        "solar_bonus_percentage": 10.0,
    }
    raw = [
        {
            "start": "2026-06-01T12:00:00+00:00",
            "end": "2026-06-01T13:00:00+00:00",
            "value": 0.10,
        }
    ]
    for reached, expected in ((False, 0.11), (True, 0.10)):
        sensor = _price_sensor(
            hass, settings=settings, solar_bonus_tracker=_LimitTracker(reached)
        )
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(sensor, "_is_in_bonus_window_at", lambda ts: True)
            assert sensor._price_with_solar_bonus(0.10) == pytest.approx(expected)
            converted = sensor._convert_raw_prices(raw)
        assert converted[0]["value"] == pytest.approx(expected)
        assert converted[0]["solar_bonus_applied"] is (not reached)


async def test_price_rebuilds_when_limit_state_flips(hass: HomeAssistant):
    tracker = _LimitTracker(False)
    sensor = _price_sensor(
        hass, settings={"solar_bonus_enabled": True}, solar_bonus_tracker=tracker
    )
    scheduled = []
    sensor.async_schedule_update_ha_state = lambda force=False: scheduled.append(force)

    sensor._handle_solar_bonus_update()
    assert scheduled == []  # no change, no rebuild on every booking
    tracker.reached = True
    sensor._handle_solar_bonus_update()
    assert scheduled == [True]


async def test_price_sensor_is_not_reset(hass: HomeAssistant):
    sensor = _price_sensor(hass)
    sensor._attr_native_value = 0.25
    await sensor.async_reset()
    assert sensor.native_value == 0.25
    assert sensor._resets_with_contract_year is False


async def test_solar_bonus_status_reset_shows_tracker_value(hass: HomeAssistant):
    tracker = await SolarBonusTracker.async_create(hass, "status-reset")
    tracker._total_bonus_euro = 3.5
    sensor = SolarBonusStatusSensor(hass, "Bonus", "status-reset", DEVICE, tracker)
    sensor.async_write_ha_state = lambda: None
    sensor._attr_native_value = 0.0

    await sensor.async_reset()

    assert sensor.native_value == 3.5
    assert sensor._resets_with_contract_year is False


async def test_price_lists_are_summed_by_time(hass: HomeAssistant):
    """Quarter-hour and hourly sources line up by timestamp, not by index."""
    sensor = _price_sensor(hass, price_sensor=["sensor.a", "sensor.b"])
    quarters = [
        {
            "start": (
                datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc)
                + timedelta(minutes=15 * i)
            ).isoformat(),
            "end": (
                datetime(2026, 6, 1, 0, 15, tzinfo=timezone.utc)
                + timedelta(minutes=15 * i)
            ).isoformat(),
            "value": 0.01 * i,
        }
        for i in range(8)
    ]
    hours = [
        {"start": "2026-06-01T00:00:00+00:00", "value": 1.0},
        {"start": "2026-06-01T01:00:00+00:00", "value": 2.0},
    ]
    merged = sensor._sum_price_lists([quarters, hours])

    assert len(merged) == 8
    assert [round(entry["value"], 6) for entry in merged] == [
        1.0,
        1.01,
        1.02,
        1.03,
        2.04,
        2.05,
        2.06,
        2.07,
    ]
    assert merged[4]["start"] == "2026-06-01T01:00:00+00:00"
    assert merged[4]["end"] == "2026-06-01T01:15:00+00:00"


async def test_price_lists_constant_and_unknown_day(hass: HomeAssistant):
    """A sensor without lists adds a constant; a missing day makes it unknown."""
    sensor = _price_sensor(
        hass,
        source_type=SOURCE_TYPE_CONSUMPTION,
        price_sensor=["sensor.epex", "sensor.dynamic", "sensor.fixed"],
        settings={"vat_percentage": 0.0},
    )
    today = [
        {
            "start": "2026-06-01T00:00:00+00:00",
            "end": "2026-06-01T01:00:00+00:00",
            "value": 0.10,
        }
    ]
    hass.states.async_set(
        "sensor.epex", 0.10, {"raw_today": today, "raw_tomorrow": today}
    )
    hass.states.async_set("sensor.dynamic", 0.05, {"raw_today": today})
    hass.states.async_set("sensor.fixed", 0.03)

    raw_today, raw_tomorrow = sensor._collect_raw_prices()

    assert raw_today[0]["value"] == pytest.approx(0.23)
    # sensor.dynamic has no prices for tomorrow yet: a partial sum is wrong
    assert raw_tomorrow is None


async def test_unparseable_lists_fall_back_to_index_merge(hass: HomeAssistant):
    sensor = _price_sensor(hass, price_sensor=["sensor.a", "sensor.b"])
    merged = sensor._sum_price_lists([[{"value": 1.0}], [{"value": 2.0}]])
    assert merged == [{"value": 3.0}]
    assert sensor._sum_price_lists([]) is None


async def test_average_to_hourly_keeps_both_hours_when_dst_ends(hass: HomeAssistant):
    sensor = _price_sensor(hass, source_type=SOURCE_TYPE_CONSUMPTION)
    raw = []
    for offset, value in (("+02:00", 1.0), ("+01:00", 3.0)):
        for minute in (0, 15, 30, 45):
            raw.append(
                {
                    "start": f"2026-10-25T02:{minute:02d}:00{offset}",
                    "end": "x",
                    "value": value,
                }
            )

    averaged = sensor._average_to_hourly(raw)

    assert [entry["value"] for entry in averaged] == [1.0, 3.0]
    assert averaged[0]["start"] == "2026-10-25T02:00:00+02:00"
    assert averaged[1]["start"] == "2026-10-25T02:00:00+01:00"


async def test_forecast_cap_fits_the_day_dst_ends(hass: HomeAssistant):
    assert sensor_module._MAX_NET_PRICE_STEPS >= 25 * 4


async def test_daily_cost_catches_up_missed_midnights(hass: HomeAssistant):
    sensor = DailyElectricityCostSensor(
        hass,
        "Fixed",
        "fixed-catch-up",
        {"per_day_supplier_electricity_standing_charge": 1.0, "vat_percentage": 0.0},
        DEVICE,
    )
    today = date(2026, 6, 10)
    three_days_ago = (today - timedelta(days=3)).isoformat()
    data = type(
        "Extra", (), {"as_dict": lambda self: {"last_charged_date": three_days_ago}}
    )()
    sensor.async_get_last_extra_data = AsyncMock(return_value=data)
    sensor.async_get_last_sensor_data = AsyncMock(return_value=None)
    sensor.async_get_last_state = AsyncMock(
        return_value=type("State", (), {"state": "10.0"})()
    )
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            sensor_module.dt_util,
            "now",
            lambda: datetime(2026, 6, 10, 8, 0, tzinfo=timezone.utc),
        )
        await sensor.async_added_to_hass()

    assert sensor.native_value == pytest.approx(13.0)
    assert sensor.extra_restore_state_data.as_dict()["last_charged_date"] == (
        today.isoformat()
    )

    # The same midnight is never charged twice
    sensor.async_write_ha_state = lambda: None
    await sensor._handle_daily_addition(datetime(2026, 6, 10, 0, 0))
    assert sensor.native_value == pytest.approx(13.0)


async def test_daily_cost_after_missed_reset_charges_only_new_year(hass: HomeAssistant):
    sensor = DailyElectricityCostSensor(
        hass,
        "Fixed",
        "fixed-reset",
        {"per_day_supplier_electricity_standing_charge": 1.0, "vat_percentage": 0.0},
        DEVICE,
    )
    sensor._reset_on_restore = date(2026, 6, 9)
    data = type(
        "Extra", (), {"as_dict": lambda self: {"last_charged_date": "2026-06-01"}}
    )()
    sensor.async_get_last_extra_data = AsyncMock(return_value=data)
    sensor.async_get_last_sensor_data = AsyncMock(return_value=None)
    sensor.async_get_last_state = AsyncMock(
        return_value=type("State", (), {"state": "50.0"})()
    )
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            sensor_module.dt_util,
            "now",
            lambda: datetime(2026, 6, 10, 8, 0, tzinfo=timezone.utc),
        )
        await sensor.async_added_to_hass()

    # Reset to zero, then June 9 and June 10 of the new contract year
    assert sensor.native_value == pytest.approx(2.0)


class _Tracker:
    def __init__(self, limit_period: str = "calendar_year") -> None:
        self.limit_period = limit_period
        self.year_resets = 0
        self.all_resets = 0

    async def async_reset_year(self) -> None:
        self.year_resets += 1

    async def async_reset_all(self) -> None:
        self.all_resets += 1


async def test_contract_year_resets_solar_only_for_contract_year_limit(
    hass: HomeAssistant,
):
    settings = {
        "reset_on_contract_anniversary": True,
        "contract_start_date": "2025-06-01",
    }
    for limit_period, expected in (("calendar_year", 0), ("contract_year", 1)):
        netting, solar = _Tracker(), _Tracker(limit_period)
        reset = _ContractYearReset(hass, f"cy-{limit_period}", settings, netting, solar)
        meter = type(
            "Meter",
            (),
            {"_resets_with_contract_year": True, "async_reset": AsyncMock()},
        )()
        price = type(
            "Price",
            (),
            {"_resets_with_contract_year": False, "async_reset": AsyncMock()},
        )()

        await reset.async_handle_midnight(date(2026, 5, 31), [meter, price])
        assert netting.all_resets == 0

        await reset.async_handle_midnight(date(2026, 6, 1), [meter, price])
        assert netting.all_resets == 1
        assert solar.year_resets == expected
        meter.async_reset.assert_awaited_once()
        price.async_reset.assert_not_awaited()


async def test_contract_year_reset_missed_while_down(hass: HomeAssistant):
    settings = {
        "reset_on_contract_anniversary": True,
        "contract_start_date": "2025-06-01",
    }
    now = datetime(2026, 6, 3, 9, 0, tzinfo=timezone.utc)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(sensor_module.dt_util, "now", lambda: now)

        # First run: nothing stored, so nothing is assumed missed
        netting = _Tracker()
        first = _ContractYearReset(hass, "cy-missed", settings, netting, None)
        assert await first.async_catch_up() is None
        assert netting.all_resets == 0

        # A year later the anniversary passed while Home Assistant was down
        await first._store.async_save({"last_reset": "2025-06-01"})
        second = _ContractYearReset(hass, "cy-missed", settings, netting, None)
        assert await second.async_catch_up() == date(2026, 6, 1)
        assert netting.all_resets == 1

        # Applied once only
        third = _ContractYearReset(hass, "cy-missed", settings, netting, None)
        assert await third.async_catch_up() is None
        assert netting.all_resets == 1

    disabled = _ContractYearReset(hass, "cy-off", {}, None, None)
    assert await disabled.async_catch_up() is None
    await disabled.async_handle_midnight(date(2026, 6, 1), [])


def _entry(hass: HomeAssistant, sources: list[str]) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_PRICE_SENSOR: ["sensor.price"]},
        options={CONF_PRICE_SETTINGS: {}},
        entry_id="registry-entry",
        subentries_data=[
            {
                "subentry_type": SUBENTRY_TYPE_SOURCE,
                "data": {
                    CONF_SOURCE_TYPE: SOURCE_TYPE_CONSUMPTION,
                    CONF_SOURCES: sources,
                },
                "title": SOURCE_TYPE_CONSUMPTION,
                "unique_id": None,
            }
        ],
    )
    entry.add_to_hass(hass)
    entry.runtime_data = RuntimeData()
    return entry


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    def add_entities(entities, update=False, config_subentry_id=None):
        return None

    await async_setup_entry(hass, entry, add_entities)
    await entry._async_process_on_unload(hass)


async def test_main_entry_device_moves_to_its_subentry(hass: HomeAssistant):
    hass.states.async_set("sensor.price", 0.1)
    entry = _entry(hass, ["sensor.energy"])
    subentry_id = next(iter(entry.subentries))
    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, "sensor_energy")}
    )
    assert device_in_main_entry(device, entry.entry_id)

    await _setup(hass, entry)

    moved = dev_reg.async_get(device.id)
    assert device_subentry_ids(moved, entry.entry_id) == {subentry_id}


async def test_reconfigured_away_sources_are_removed(hass: HomeAssistant):
    hass.states.async_set("sensor.price", 0.1)
    entry = _entry(hass, ["sensor.energy"])
    subentry_id = next(iter(entry.subentries))
    dev_reg = dr.async_get(hass)
    ent_reg = er.async_get(hass)
    stale_device = dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        config_subentry_id=subentry_id,
        identifiers={(DOMAIN, "sensor_removed")},
    )
    stale = ent_reg.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{DOMAIN}_sensor_removed_kwh_total",
        config_entry=entry,
        config_subentry_id=subentry_id,
        device_id=stale_device.id,
    )
    kept = ent_reg.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{DOMAIN}_sensor_energy_kwh_total",
        config_entry=entry,
        config_subentry_id=subentry_id,
    )
    summary_device = dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, "daily_electricity_cost")},
    )

    await _setup(hass, entry)

    assert ent_reg.async_get(stale.entity_id) is None
    assert dev_reg.async_get(stale_device.id) is None
    assert ent_reg.async_get(kept.entity_id) is not None
    assert dev_reg.async_get(summary_device.id) is not None
