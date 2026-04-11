import pytest
from unittest.mock import AsyncMock
from datetime import datetime, timedelta, timezone
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from custom_components.dynamic_energy_contract_calculator.entity import (
    DynamicEnergySensor,
)
from custom_components.dynamic_energy_contract_calculator.sensor import (
    TotalCostSensor,
    DailyElectricityCostSensor,
    DailyGasCostSensor,
    TotalEnergyCostSensor,
    CurrentElectricityPriceSensor,
    SolarBonusStatusSensor,
    async_setup_entry as sensor_async_setup_entry,
)
from homeassistant.helpers import entity_registry as er
from custom_components.dynamic_energy_contract_calculator.const import (
    CONF_PRICE_SENSOR,
    CONF_PRICE_SENSOR_GAS,
    CONF_PRICE_SETTINGS,
    CONF_SOURCE_TYPE,
    CONF_SOURCES,
    DOMAIN,
    SOURCE_TYPE_CONSUMPTION,
    SOURCE_TYPE_GAS,
    SOURCE_TYPE_PRODUCTION,
    SUBENTRY_TYPE_SOURCE,
)
from pytest_homeassistant_custom_component.common import MockConfigEntry
from custom_components.dynamic_energy_contract_calculator import sensor as sensor_module


async def test_dynamic_energy_sensor_modes(hass: HomeAssistant):
    price_settings = {"vat_percentage": 0.0, "production_price_include_vat": False}

    # profit_total with negative price
    sensor_profit = DynamicEnergySensor(
        hass,
        "Profit",
        "p1",
        "sensor.energy",
        SOURCE_TYPE_CONSUMPTION,
        price_settings,
        price_sensor="sensor.price",
        mode="profit_total",
    )
    sensor_profit._last_energy = 0
    hass.states.async_set("sensor.energy", 1)
    hass.states.async_set("sensor.price", -0.2)
    await sensor_profit.async_update()
    assert sensor_profit.native_value == pytest.approx(0.2)

    # kwh_during_cost_total for consumption
    sensor_kwh_cost = DynamicEnergySensor(
        hass,
        "KwhCost",
        "kc1",
        "sensor.energy",
        SOURCE_TYPE_CONSUMPTION,
        price_settings,
        price_sensor="sensor.price",
        mode="kwh_during_cost_total",
    )
    sensor_kwh_cost._last_energy = 0
    hass.states.async_set("sensor.energy", 2)
    hass.states.async_set("sensor.price", 0.5)
    await sensor_kwh_cost.async_update()
    assert sensor_kwh_cost.native_value == pytest.approx(2)

    # kwh_during_profit_total for production (also hits production_price_include_vat False)
    sensor_kwh_profit = DynamicEnergySensor(
        hass,
        "KwhProfit",
        "kp1",
        "sensor.prod",
        SOURCE_TYPE_PRODUCTION,
        price_settings,
        price_sensor="sensor.price",
        mode="kwh_during_profit_total",
    )
    sensor_kwh_profit._last_energy = 0
    hass.states.async_set("sensor.prod", 1)
    hass.states.async_set("sensor.price", 0.5)
    await sensor_kwh_profit.async_update()
    assert sensor_kwh_profit.native_value == pytest.approx(1)


async def test_dynamic_sensor_added_to_hass(hass: HomeAssistant):
    sensor = DynamicEnergySensor(
        hass,
        "Added",
        "aid",
        "sensor.energy",
        SOURCE_TYPE_CONSUMPTION,
        {},
        price_sensor="sensor.price",
        mode="cost_total",
    )

    called = []

    def fake_track(h, e_id, cb):
        called.append(e_id)
        return "unsub"

    sensor.async_on_remove = lambda unsub: called.append("unsub")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "custom_components.dynamic_energy_contract_calculator.entity.async_track_state_change_event",
            fake_track,
        )
        await sensor.async_added_to_hass()

    assert called == ["sensor.energy", "unsub", "sensor.price", "unsub"]


async def test_total_cost_sensor_added(hass: HomeAssistant):
    dummy = DynamicEnergySensor(
        hass,
        "D",
        "d1",
        "sensor.energy",
        SOURCE_TYPE_CONSUMPTION,
        {},
        price_sensor="sensor.price",
        mode="cost_total",
    )
    dummy.entity_id = "sensor.d_cost_d1"
    sensor = TotalCostSensor(
        hass,
        "Total",
        "tid",
        DeviceInfo(identifiers={("d", "1")}),
        source_sensors=[dummy],
    )
    called = []

    def fake_track(h, e_id, cb):
        called.append(e_id)
        return "unsub"

    sensor.async_on_remove = lambda unsub: called.append("unsub")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "custom_components.dynamic_energy_contract_calculator.sensor.async_track_state_change_event",
            fake_track,
        )
        await sensor.async_added_to_hass()

    assert called == [dummy.entity_id, "unsub"]


async def test_daily_cost_sensors(hass: HomeAssistant):
    e = DailyElectricityCostSensor(
        hass,
        "E",
        "eid",
        {
            "per_day_grid_operator_electricity_connection_fee": 0.1,
            "vat_percentage": 0.0,
        },
        DeviceInfo(identifiers={("d", "1")}),
    )
    g = DailyGasCostSensor(
        hass,
        "G",
        "gid",
        {"per_day_supplier_gas_standing_charge": 0.2, "vat_percentage": 0.0},
        DeviceInfo(identifiers={("d", "2")}),
    )
    e.async_write_ha_state = lambda *a, **k: None
    g.async_write_ha_state = lambda *a, **k: None
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "custom_components.dynamic_energy_contract_calculator.sensor.async_track_time_change",
            lambda *a, **k: "unsub",
        )
        await e.async_added_to_hass()
        await g.async_added_to_hass()

    await e.async_update()
    await g.async_update()
    await e._handle_daily_addition(datetime.now())
    await g._handle_daily_addition(datetime.now())
    assert e.native_value > 0
    assert g.native_value > 0


async def test_total_energy_cost_sensor_branches(hass: HomeAssistant):
    er_reg = er.async_get(hass)
    er_reg.async_get_or_create("sensor", DOMAIN, "net_uid", suggested_object_id="net")
    er_reg.async_get_or_create(
        "sensor", DOMAIN, "fixed_uid", suggested_object_id="fixed"
    )
    hass.states.async_set("sensor.net", "bad")
    hass.states.async_set("sensor.fixed", "bad")
    sensor = TotalEnergyCostSensor(
        hass,
        "Total",
        "teid",
        net_cost_unique_id="net_uid",
        fixed_cost_unique_ids=["fixed_uid"],
        device=DeviceInfo(identifiers={("d", "3")}),
    )
    await sensor.async_update()
    assert sensor.native_value == 0

    called = []

    def fake_track(h, e_id, cb):
        called.append(e_id)
        return "unsub"

    sensor.async_on_remove = lambda unsub: called.append("unsub")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "custom_components.dynamic_energy_contract_calculator.sensor.async_track_state_change_event",
            fake_track,
        )
        await sensor.async_added_to_hass()
    assert set(called) == {"sensor.net", "sensor.fixed", "unsub"}

    called_event = {}
    sensor.async_write_ha_state = lambda *a, **k: called_event.setdefault("write", True)

    async def fake_update():
        called_event.setdefault("update", True)

    sensor.async_update = fake_update
    event = type("E", (), {"data": {"entity_id": "sensor.net"}})()
    await sensor._handle_input_event(event)
    assert called_event == {"update": True, "write": True}


async def test_current_price_sensor_update_branches(hass: HomeAssistant):
    price = CurrentElectricityPriceSensor(
        hass,
        "Price",
        "cp1",
        price_sensor="sensor.p",
        source_type=SOURCE_TYPE_CONSUMPTION,
        price_settings={"vat_percentage": 0.0},
        icon="mdi:flash",
        device=DeviceInfo(identifiers={("d", "4")}),
    )
    # unavailable
    await price.async_update()
    assert not price.available
    hass.states.async_set("sensor.p", "bad")
    await price.async_update()
    assert not price.available

    hass.states.async_set("sensor.p", 1.0)
    await price.async_update()
    assert price.native_value == pytest.approx(1.0)

    gas = CurrentElectricityPriceSensor(
        hass,
        "Gas",
        "cp2",
        price_sensor="sensor.gp",
        source_type=SOURCE_TYPE_GAS,
        price_settings={
            "per_unit_supplier_gas_markup": 0.1,
            "per_unit_government_gas_tax": 0.1,
            "vat_percentage": 0.0,
        },
        icon="mdi:gas-burner",
        device=DeviceInfo(identifiers={("d", "5")}),
    )
    hass.states.async_set("sensor.gp", 1.0)
    await gas.async_update()
    assert gas.native_value == pytest.approx(1.2)

    prod = CurrentElectricityPriceSensor(
        hass,
        "Prod",
        "cp3",
        price_sensor="sensor.pp",
        source_type=SOURCE_TYPE_PRODUCTION,
        price_settings={"production_price_include_vat": True, "vat_percentage": 0.0},
        icon="mdi:flash",
        device=DeviceInfo(identifiers={("d", "6")}),
    )
    hass.states.async_set("sensor.pp", 2.0)
    await prod.async_update()
    assert prod.native_value == pytest.approx(2.0)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "custom_components.dynamic_energy_contract_calculator.sensor.async_track_state_change_event",
            lambda *a, **k: "unsub",
        )
        await prod.async_added_to_hass()


async def test_async_setup_entry_gas(hass: HomeAssistant):
    from custom_components.dynamic_energy_contract_calculator.sensor import (
        async_setup_entry,
    )
    from custom_components.dynamic_energy_contract_calculator import async_setup

    await async_setup(hass, {})
    hass.states.async_set("sensor.gas", 0)
    hass.states.async_set("sensor.gprice", 0)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_PRICE_SENSOR_GAS: ["sensor.gprice"]},
        options={CONF_PRICE_SETTINGS: {}},
        subentries_data=[
            {
                "subentry_type": SUBENTRY_TYPE_SOURCE,
                "data": {
                    CONF_SOURCE_TYPE: SOURCE_TYPE_GAS,
                    CONF_SOURCES: ["sensor.gas"],
                },
                "title": SOURCE_TYPE_GAS,
                "unique_id": None,
            }
        ],
    )
    entry.add_to_hass(hass)
    from custom_components.dynamic_energy_contract_calculator import RuntimeData

    entry.runtime_data = RuntimeData()
    added = []

    async def add_entities(entities, update=False):
        added.extend(entities)

    await async_setup_entry(hass, entry, add_entities)
    await hass.async_block_till_done()
    assert isinstance(added, list)


async def test_additional_branches(hass: HomeAssistant):
    price_settings = {"vat_percentage": 0.0, "production_price_include_vat": False}

    prod_sensor = DynamicEnergySensor(
        hass,
        "ProdCost",
        "pc3",
        "sensor.prod",
        SOURCE_TYPE_PRODUCTION,
        price_settings,
        price_sensor="sensor.price",
        mode="kwh_during_cost_total",
    )
    prod_sensor._last_energy = 0
    hass.states.async_set("sensor.prod", 2)
    hass.states.async_set("sensor.price", -0.5)
    await prod_sensor.async_update()
    assert prod_sensor.native_value == pytest.approx(2)

    cons_sensor = DynamicEnergySensor(
        hass,
        "ConsProfit",
        "cp4",
        "sensor.energy",
        SOURCE_TYPE_CONSUMPTION,
        price_settings,
        price_sensor="sensor.price",
        mode="kwh_during_profit_total",
    )
    cons_sensor._last_energy = 0
    hass.states.async_set("sensor.energy", 3)
    hass.states.async_set("sensor.price", -0.1)
    await cons_sensor.async_update()
    assert cons_sensor.native_value == pytest.approx(3)


async def test_current_price_invalid_source(hass: HomeAssistant):
    sensor = CurrentElectricityPriceSensor(
        hass,
        "Bad",
        "bid",
        price_sensor="sensor.p",
        source_type="other",
        price_settings={"vat_percentage": 0.0},
        icon="mdi:flash",
        device=DeviceInfo(identifiers={("d", "bad")}),
    )
    hass.states.async_set("sensor.p", 1)
    await sensor.async_update()
    assert sensor.native_value == 0


async def test_current_price_helper_methods_cover_edge_cases(hass: HomeAssistant):
    sensor = CurrentElectricityPriceSensor(
        hass,
        "Helper",
        "helper-id",
        price_sensor="sensor.price",
        source_type=SOURCE_TYPE_PRODUCTION,
        price_settings={
            "production_price_include_vat": False,
            "average_prices_to_hourly": True,
            "solar_bonus_enabled": True,
            "solar_bonus_percentage": 10.0,
            "vat_percentage": 0.0,
        },
        icon="mdi:flash",
        device=DeviceInfo(identifiers={("d", "helper")}),
    )

    assert sensor._merge_price_lists(None, None) is None
    merged = sensor._merge_price_lists(
        [{"value": "bad"}, {"value": 1.0}],
        [{"value": 2.5, "price": 2.5}, {"value": 3.0}, {"value": 4.0, "price": 4.0}],
    )
    assert merged == [
        {"value": 2.5, "price": 2.5},
        {"value": 4.0},
        {"value": 4.0, "price": 4.0},
    ]

    assert sensor._is_daylight_at("not-a-timestamp") is False

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(sensor_module, "_ASTRAL_AVAILABLE", False)
        assert sensor._is_daylight_at(datetime(2026, 1, 1, 12, 0, 0)) is True
        assert sensor._get_sunrise_sunset_times(datetime(2026, 1, 1).date()) == (
            None,
            None,
        )

    split_entry = {
        "start": "2026-01-01T06:00:00+00:00",
        "end": "2026-01-01T09:00:00+00:00",
        "price": 0.5,
    }
    split = sensor._split_entry_at_sunrise_sunset(
        split_entry,
        datetime(2026, 1, 1, 7, 0, tzinfo=timezone.utc),
        datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc),
    )
    assert [entry["start"] for entry in split] == [
        "2026-01-01T06:00:00+00:00",
        "2026-01-01T07:00:00+00:00",
        "2026-01-01T08:00:00+00:00",
    ]
    assert sensor._split_entry_at_sunrise_sunset({"price": 1.0}, None, None) == [
        {"price": 1.0}
    ]


async def test_current_price_average_and_convert_helpers(hass: HomeAssistant):
    sensor = CurrentElectricityPriceSensor(
        hass,
        "Helper",
        "helper-convert",
        price_sensor="sensor.price",
        source_type=SOURCE_TYPE_PRODUCTION,
        price_settings={
            "production_price_include_vat": False,
            "average_prices_to_hourly": True,
            "solar_bonus_enabled": True,
            "solar_bonus_percentage": 10.0,
            "vat_percentage": 0.0,
        },
        icon="mdi:flash",
        device=DeviceInfo(identifiers={("d", "helper-convert")}),
    )

    averaged = sensor._average_to_hourly(
        [
            {
                "start": "2026-01-01T10:00:00+00:00",
                "end": "2026-01-01T10:15:00+00:00",
                "value": 1,
            },
            {
                "start": "2026-01-01T10:15:00+00:00",
                "end": "2026-01-01T10:30:00+00:00",
                "price": 3,
            },
            {
                "start": "2026-01-01T10:30:00+00:00",
                "end": "2026-01-01T10:45:00+00:00",
                "value": "bad",
            },
            {"foo": "bar"},
        ]
    )
    assert averaged[0]["start"] == "2026-01-01T10:00:00+00:00"
    assert averaged[0]["end"] == "2026-01-01T11:00:00+00:00"
    assert averaged[0]["value"] == pytest.approx(2.0)

    sensor.price_settings["average_prices_to_hourly"] = False
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(sensor, "_get_sunrise_sunset_times", lambda _date: (None, None))
        mp.setattr(sensor, "_is_daylight_at", lambda timestamp: "10:" in str(timestamp))
        converted = sensor._convert_raw_prices(
            [
                {
                    "start": "2026-01-01T10:00:00+00:00",
                    "end": "2026-01-01T10:30:00+00:00",
                    "value": 1,
                },
                {
                    "start": "2026-01-01T11:00:00+00:00",
                    "end": "2026-01-01T11:30:00+00:00",
                    "price": "bad",
                },
                {"start": "invalid", "end": "2026-01-01T12:30:00+00:00", "value": 2},
                {"foo": "bar"},
            ]
        )

    assert converted[0]["value"] == pytest.approx(1.1)
    assert converted[0]["solar_bonus_applied"] is True
    assert converted[1]["value"] == pytest.approx(2.0)
    assert converted[1]["solar_bonus_applied"] is False
    assert sensor._convert_raw_prices("invalid") is None


async def test_current_price_scheduling_and_cleanup(hass: HomeAssistant):
    sensor = CurrentElectricityPriceSensor(
        hass,
        "Schedule",
        "schedule-id",
        price_sensor="sensor.price",
        source_type=SOURCE_TYPE_CONSUMPTION,
        price_settings={"vat_percentage": 0.0},
        icon="mdi:flash",
        device=DeviceInfo(identifiers={("d", "schedule")}),
    )
    now = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
    sensor._net_today = [
        {
            "start": "2026-01-01T11:00:00+00:00",
            "end": "2026-01-01T12:00:00+00:00",
            "value": 1.2,
        }
    ]
    sensor._net_tomorrow = [
        {
            "start": "2026-01-02T09:00:00+00:00",
            "end": "2026-01-02T10:00:00+00:00",
            "value": 2.2,
        }
    ]

    scheduled = {}

    def fake_track_point_in_time(hass_arg, callback, when):
        scheduled["when"] = when
        scheduled["callback"] = callback
        return lambda: scheduled.setdefault("unsub_called", True)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(sensor_module.dt_util, "now", lambda: now)
        mp.setattr(
            sensor_module,
            "async_track_point_in_time",
            fake_track_point_in_time,
        )
        sensor._schedule_next_price_change()
        assert scheduled["when"] == datetime(2026, 1, 1, 11, 0, tzinfo=timezone.utc)

        sensor._price_change_unsub = lambda: scheduled.setdefault(
            "cleanup_called", True
        )
        await sensor.async_will_remove_from_hass()

    assert scheduled["cleanup_called"] is True


async def test_current_price_schedule_sunrise_sunset_update(hass: HomeAssistant):
    sensor = CurrentElectricityPriceSensor(
        hass,
        "Sun",
        "sun-id",
        price_sensor="sensor.price",
        source_type=SOURCE_TYPE_PRODUCTION,
        price_settings={
            "production_price_include_vat": False,
            "solar_bonus_enabled": True,
            "average_prices_to_hourly": False,
            "vat_percentage": 0.0,
        },
        icon="mdi:flash",
        device=DeviceInfo(identifiers={("d", "sun")}),
    )
    hass.states.async_set("sensor.price", 1.5)
    now = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
    sunrise = now + timedelta(hours=1)
    sunset = now + timedelta(hours=5)
    tomorrow_sunrise = now + timedelta(days=1, hours=1)
    tomorrow_sunset = now + timedelta(days=1, hours=5)
    calls = {}
    sensor.async_write_ha_state = lambda *args, **kwargs: calls.setdefault(
        "write", 0
    ) or calls.__setitem__("write", calls.get("write", 0) + 1)

    def fake_track_point_in_time(hass_arg, callback, when):
        calls["when"] = when
        calls["callback"] = callback
        return lambda: calls.setdefault("unsub", True)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(sensor_module.dt_util, "now", lambda: now)
        mp.setattr(
            sensor,
            "_get_sunrise_sunset_times",
            lambda date_obj: (
                (sunrise, sunset)
                if date_obj == now.date()
                else (tomorrow_sunrise, tomorrow_sunset)
            ),
        )
        mp.setattr(
            sensor_module,
            "async_track_point_in_time",
            fake_track_point_in_time,
        )

        sensor._schedule_sunrise_sunset_updates()
        assert calls["when"] == sunrise

        await calls["callback"](sunrise)

    assert sensor.native_value == pytest.approx(1.5)


async def test_solar_bonus_status_sensor_update(hass: HomeAssistant):
    tracker = type(
        "Tracker",
        (),
        {"year_production_kwh": 12.345, "total_bonus_euro": 6.789},
    )()
    sensor = SolarBonusStatusSensor(
        hass,
        "Solar Bonus",
        "solar-status",
        DeviceInfo(identifiers={("d", "solar-status")}),
        tracker,
    )

    await sensor.async_update()

    assert sensor.native_value == pytest.approx(6.789)
    assert sensor.extra_state_attributes == {
        "year_production_kwh": 12.35,
        "total_bonus_euro": 6.79,
    }


async def test_total_cost_sensor_added_with_platform_updates(hass: HomeAssistant):
    sensor = TotalCostSensor(
        hass,
        "Total",
        "with-platform",
        DeviceInfo(identifiers={("d", "platform")}),
        source_sensors=[],
    )
    sensor.platform = object()
    calls = {}
    sensor.async_write_ha_state = lambda *a, **k: calls.setdefault(
        "write", 0
    ) or calls.__setitem__("write", calls.get("write", 0) + 1)

    async def fake_update():
        calls["updated"] = True

    sensor.async_update = fake_update
    await sensor.async_added_to_hass()
    assert calls["updated"] is True


async def test_total_energy_cost_invalid_fixed_and_net_values(hass: HomeAssistant):
    er_reg = er.async_get(hass)
    er_reg.async_get_or_create(
        "sensor", DOMAIN, "net_uid_bad", suggested_object_id="net_bad"
    )
    er_reg.async_get_or_create(
        "sensor", DOMAIN, "fixed_uid_bad", suggested_object_id="fixed_bad"
    )
    hass.states.async_set("sensor.net_bad", "bad")
    hass.states.async_set("sensor.fixed_bad", "bad")
    sensor = TotalEnergyCostSensor(
        hass,
        "Total",
        "bad-values",
        net_cost_unique_id="net_uid_bad",
        fixed_cost_unique_ids=["fixed_uid_bad"],
        device=DeviceInfo(identifiers={("d", "bad-values")}),
    )
    await sensor.async_update()
    assert sensor.native_value == 0


async def test_total_energy_cost_invalid_value_branches(hass: HomeAssistant):
    sensor = TotalEnergyCostSensor(
        hass,
        "Total",
        "invalid-branches",
        net_cost_unique_id="",
        fixed_cost_unique_ids=[],
        device=DeviceInfo(identifiers={("d", "invalid-branches")}),
    )
    sensor.net_cost_entity_id = "sensor.net_invalid"
    sensor.fixed_cost_entity_ids = ["sensor.fixed_invalid"]
    hass.states.async_set("sensor.net_invalid", "not-a-number")
    hass.states.async_set("sensor.fixed_invalid", "not-a-number")
    await sensor.async_update()
    assert sensor.native_value == 0


async def test_total_energy_cost_added_with_platform_updates(hass: HomeAssistant):
    sensor = TotalEnergyCostSensor(
        hass,
        "Total",
        "platform-energy",
        net_cost_unique_id="",
        fixed_cost_unique_ids=[],
        device=DeviceInfo(identifiers={("d", "platform-energy")}),
    )
    sensor.platform = object()
    calls = {}
    sensor.async_write_ha_state = lambda *a, **k: calls.setdefault(
        "writes", 0
    ) or calls.__setitem__("writes", calls.get("writes", 0) + 1)

    async def fake_update():
        calls["updated"] = True

    sensor.async_update = fake_update
    await sensor.async_added_to_hass()
    assert calls["updated"] is True


async def test_current_price_more_helper_branches(hass: HomeAssistant):
    sensor = CurrentElectricityPriceSensor(
        hass,
        "More Helpers",
        "more-helpers",
        price_sensor="sensor.price",
        source_type=SOURCE_TYPE_CONSUMPTION,
        price_settings={"vat_percentage": 0.0},
        icon="mdi:flash",
        device=DeviceInfo(identifiers={("d", "more-helpers")}),
    )

    assert sensor._normalize_price_entries("bad") is None
    assert (
        sensor._normalize_price_entries(["bad", {"foo": "bar"}, {"value": "bad"}])
        is None
    )
    assert sensor._extract_price_entries(None, ("raw_today",)) is None
    assert (
        sensor._extract_price_entries(
            type("State", (), {"attributes": {"raw_today": "bad"}})(), ("raw_today",)
        )
        is None
    )

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(sensor_module, "_ASTRAL_AVAILABLE", True)
        mp.setattr(
            sensor_module,
            "_astral_sun",
            lambda *a, **k: (_ for _ in ()).throw(ValueError("boom")),
        )
        assert sensor._is_daylight_at(datetime(2026, 1, 1, 8, 0, 0)) is True

    assert sensor._average_to_hourly([]) == []
    fallback_prices = [{"foo": "bar"}]
    assert sensor._average_to_hourly(fallback_prices) == fallback_prices
    assert sensor._get_sunrise_sunset_times("bad-date") == (None, None)
    assert sensor._split_entry_at_sunrise_sunset(
        {"start": "bad", "end": "2026-01-01T09:00:00+00:00"},
        None,
        None,
    ) == [{"start": "bad", "end": "2026-01-01T09:00:00+00:00"}]

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(sensor_module, "_ASTRAL_AVAILABLE", True)
        mp.setattr(sensor.hass.config, "latitude", None)
        assert (
            sensor._is_daylight_at(datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc))
            is True
        )

    merged = sensor._merge_price_lists(
        [{"value": "bad"}],
        [{"value": 1.5}, {"value": 2.0, "price": 2.0}],
    )
    assert merged[0]["value"] == pytest.approx(1.5)
    assert merged[1]["price"] == pytest.approx(2.0)
    merged_existing_price = sensor._merge_price_lists(
        [{"value": 1.0, "price": 1.0}],
        [{"value": 2.0}, {"value": "bad"}],
    )
    assert merged_existing_price[0]["price"] == pytest.approx(3.0)

    avg = sensor._average_to_hourly(
        [
            "bad",
            {"time": datetime(2026, 1, 1, 10, 15), "price": 1.0},
            {"time": object(), "price": 2.0},
            {"time": datetime(2026, 1, 1, 10, 30), "price": 3.0},
            {"time": datetime(2026, 1, 1, 10, 45), "foo": 1},
            {
                "time": type(
                    "FakeTime",
                    (),
                    {"year": 2026, "month": 1, "day": 1, "hour": 11},
                )(),
                "value": 4.0,
            },
        ]
    )
    assert avg[0]["time"].startswith("2026-01-01T10:00:00")
    assert avg[1]["value"] == pytest.approx(4.0)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(sensor_module, "_ASTRAL_AVAILABLE", True)
        mp.setattr(
            sensor_module,
            "_astral_sun",
            lambda *a, **k: {
                "sunrise": datetime(2026, 1, 1, 7, 0, tzinfo=timezone.utc),
                "sunset": datetime(2026, 1, 1, 17, 0, tzinfo=timezone.utc),
            },
        )
        assert sensor._is_daylight_at(datetime(2026, 1, 1, 8, 0, 0)) is True

    split = sensor._split_entry_at_sunrise_sunset(
        {
            "time": "2026-01-01T06:00:00+00:00",
            "end": "2026-01-01T09:00:00+00:00",
            "price": 1.0,
        },
        datetime(2026, 1, 1, 7, 0, tzinfo=timezone.utc),
        None,
    )
    assert split[0]["time"] == "2026-01-01T06:00:00+00:00"

    split_obj = sensor._split_entry_at_sunrise_sunset(
        {
            "start": datetime(2026, 1, 1, 6, 0, tzinfo=timezone.utc),
            "end": datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc),
            "price": 1.0,
        },
        None,
        datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc),
    )
    assert split_obj[-1]["end"] == "2026-01-01T09:00:00+00:00"


async def test_current_price_update_current_price_fallback_and_tomorrow(
    hass: HomeAssistant,
):
    sensor = CurrentElectricityPriceSensor(
        hass,
        "Update Current",
        "update-current",
        price_sensor=["sensor.a", "sensor.b"],
        source_type=SOURCE_TYPE_CONSUMPTION,
        price_settings={"vat_percentage": 0.0},
        icon="mdi:flash",
        device=DeviceInfo(identifiers={("d", "update-current")}),
    )
    now = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
    sensor._net_today = [{"start": "bad", "end": "bad", "value": 1.0}]
    sensor._net_tomorrow = [
        {
            "start": "2026-01-01T09:00:00+00:00",
            "end": "2026-01-01T11:00:00+00:00",
            "value": 2.5,
        }
    ]

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(sensor_module.dt_util, "now", lambda: now)
        sensor._update_current_price()
    assert sensor.native_value == pytest.approx(2.5)

    sensor._net_today = [
        {
            "start": "2026-01-01T09:00:00+00:00",
            "end": "2026-01-01T11:00:00+00:00",
            "value": 4.2,
        }
    ]
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(sensor_module.dt_util, "now", lambda: now)
        sensor._update_current_price()
    assert sensor.native_value == pytest.approx(4.2)

    sensor._net_today = [
        {"start": "2026-01-01T09:00:00+00:00", "end": None, "value": 9.0}
    ]
    sensor._net_tomorrow = [{"start": "bad", "end": "bad", "value": 3.0}]
    hass.states.async_set("sensor.a", "bad")
    hass.states.async_set("sensor.b", 1.2)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(sensor_module.dt_util, "now", lambda: now)
        sensor._update_current_price()
    assert sensor.native_value == pytest.approx(1.2)


async def test_current_price_schedule_next_change_no_future_event(hass: HomeAssistant):
    sensor = CurrentElectricityPriceSensor(
        hass,
        "No Future",
        "no-future",
        price_sensor="sensor.price",
        source_type=SOURCE_TYPE_CONSUMPTION,
        price_settings={"vat_percentage": 0.0},
        icon="mdi:flash",
        device=DeviceInfo(identifiers={("d", "no-future")}),
    )
    sensor._price_change_unsub = lambda: None
    sensor._net_today = [{"start": "bad"}]
    sensor._net_tomorrow = [{"end": "2026-01-01T11:00:00+00:00"}]
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            sensor_module.dt_util,
            "now",
            lambda: datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
        )
        sensor._schedule_next_price_change()
    assert sensor._price_change_unsub is None


async def test_current_price_next_change_callback_runs(hass: HomeAssistant):
    sensor = CurrentElectricityPriceSensor(
        hass,
        "Next Change",
        "next-change",
        price_sensor="sensor.price",
        source_type=SOURCE_TYPE_CONSUMPTION,
        price_settings={"vat_percentage": 0.0},
        icon="mdi:flash",
        device=DeviceInfo(identifiers={("d", "next-change")}),
    )
    now = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
    sensor._net_today = [
        {
            "start": "2026-01-01T11:00:00+00:00",
            "end": "2026-01-01T12:00:00+00:00",
            "value": 1.0,
        }
    ]
    called = {"writes": 0, "updates": 0, "reschedules": 0}
    sensor.async_write_ha_state = lambda *a, **k: called.__setitem__(
        "writes", called["writes"] + 1
    )
    sensor._update_current_price = lambda: called.__setitem__(
        "updates", called["updates"] + 1
    )

    def fake_reschedule():
        called["reschedules"] += 1

    def fake_track_point_in_time(hass_arg, callback, when):
        called["callback"] = callback
        return lambda: None

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(sensor_module.dt_util, "now", lambda: now)
        mp.setattr(sensor_module, "async_track_point_in_time", fake_track_point_in_time)
        sensor._schedule_next_price_change()
        sensor._schedule_next_price_change = fake_reschedule
        await called["callback"](now + timedelta(hours=1))

    assert called["writes"] == 1
    assert called["updates"] == 1
    assert called["reschedules"] == 1


async def test_current_price_convert_non_averaged_branches(hass: HomeAssistant):
    sensor = CurrentElectricityPriceSensor(
        hass,
        "Convert More",
        "convert-more",
        price_sensor="sensor.price",
        source_type=SOURCE_TYPE_PRODUCTION,
        price_settings={
            "production_price_include_vat": False,
            "average_prices_to_hourly": False,
            "solar_bonus_enabled": True,
            "solar_bonus_percentage": 10.0,
            "vat_percentage": 0.0,
        },
        icon="mdi:flash",
        device=DeviceInfo(identifiers={("d", "convert-more")}),
    )
    fake_dt = type(
        "FakeDt",
        (),
        {
            "year": 2026,
            "month": 1,
            "day": 1,
            "hour": 12,
            "date": lambda self: datetime(2026, 1, 1).date(),
        },
    )()

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(sensor, "_get_sunrise_sunset_times", lambda date_obj: (None, None))
        mp.setattr(
            sensor,
            "_split_entry_at_sunrise_sunset",
            lambda entry, sunrise, sunset: [entry],
        )
        mp.setattr(sensor, "_is_daylight_at", lambda timestamp: True)
        converted = sensor._convert_raw_prices(
            [
                {"start": fake_dt, "end": "2026-01-01T13:00:00+00:00", "value": 1.0},
                {"start": "bad", "end": "2026-01-01T13:00:00+00:00", "value": 2.0},
                {"foo": "bar"},
                "bad",
            ]
        )

    assert len(converted) == 2
    assert all(entry["solar_bonus_applied"] is True for entry in converted)


async def test_current_price_convert_averaged_split_defensive_branches(
    hass: HomeAssistant,
):
    sensor = CurrentElectricityPriceSensor(
        hass,
        "Convert Split",
        "convert-split",
        price_sensor="sensor.price",
        source_type=SOURCE_TYPE_PRODUCTION,
        price_settings={
            "production_price_include_vat": False,
            "average_prices_to_hourly": True,
            "solar_bonus_enabled": True,
            "solar_bonus_percentage": 10.0,
            "vat_percentage": 0.0,
        },
        icon="mdi:flash",
        device=DeviceInfo(identifiers={("d", "convert-split")}),
    )
    fake_dt = type(
        "FakeDt",
        (),
        {
            "date": lambda self: datetime(2026, 1, 1).date(),
            "year": 2026,
            "month": 1,
            "day": 1,
            "hour": 12,
        },
    )()

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(sensor, "_get_sunrise_sunset_times", lambda date_obj: (None, None))
        mp.setattr(
            sensor,
            "_split_entry_at_sunrise_sunset",
            lambda entry, sunrise, sunset: [entry],
        )
        mp.setattr(sensor, "_is_daylight_at", lambda timestamp: True)
        converted = sensor._convert_raw_prices(
            [
                {"start": fake_dt, "end": "2026-01-01T13:00:00+00:00", "value": 1.0},
                {"start": "bad", "end": "2026-01-01T13:00:00+00:00", "value": 2.0},
                {"value": 3.0},
                "bad",
            ]
        )

    assert len(converted) >= 1


async def test_current_price_convert_split_timestamp_defensive_branches(
    hass: HomeAssistant,
):
    sensor = CurrentElectricityPriceSensor(
        hass,
        "Convert Split Defensive",
        "convert-split-defensive",
        price_sensor="sensor.price",
        source_type=SOURCE_TYPE_PRODUCTION,
        price_settings={
            "production_price_include_vat": False,
            "average_prices_to_hourly": True,
            "solar_bonus_enabled": True,
            "solar_bonus_percentage": 10.0,
            "vat_percentage": 0.0,
        },
        icon="mdi:flash",
        device=DeviceInfo(identifiers={("d", "convert-split-defensive")}),
    )

    fake_dt = type(
        "FakeDt",
        (),
        {
            "date": lambda self: datetime(2026, 1, 1).date(),
        },
    )()

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(sensor, "_average_to_hourly", lambda raw_prices: raw_prices)
        mp.setattr(sensor, "_get_sunrise_sunset_times", lambda date_obj: (None, None))
        mp.setattr(
            sensor,
            "_split_entry_at_sunrise_sunset",
            lambda entry, sunrise, sunset: [entry],
        )
        mp.setattr(sensor, "_is_daylight_at", lambda timestamp: True)
        converted = sensor._convert_raw_prices(
            [
                {"start": fake_dt, "end": "2026-01-01T13:00:00+00:00", "value": 1.0},
                {"start": "bad", "end": "2026-01-01T13:00:00+00:00", "value": 2.0},
                {"end": "2026-01-01T13:00:00+00:00", "value": 3.0},
            ]
        )

    assert converted[0]["solar_bonus_applied"] is True


async def test_current_price_async_update_without_averaging_schedules_sunrise(
    hass: HomeAssistant,
):
    sensor = CurrentElectricityPriceSensor(
        hass,
        "No Averaging",
        "no-averaging",
        price_sensor="sensor.price",
        source_type=SOURCE_TYPE_PRODUCTION,
        price_settings={
            "production_price_include_vat": False,
            "average_prices_to_hourly": False,
            "solar_bonus_enabled": True,
            "vat_percentage": 0.0,
        },
        icon="mdi:flash",
        device=DeviceInfo(identifiers={("d", "no-averaging")}),
    )
    hass.states.async_set("sensor.price", 1.0, {"raw_today": [], "raw_tomorrow": []})
    called = {}
    sensor._schedule_sunrise_sunset_updates = lambda: called.setdefault(
        "scheduled", True
    )

    await sensor.async_update()

    assert sensor.native_value == pytest.approx(1.0)
    assert called["scheduled"] is True


async def test_sensor_async_setup_entry_creates_new_trackers(hass: HomeAssistant):
    from custom_components.dynamic_energy_contract_calculator import RuntimeData

    hass.data.setdefault(DOMAIN, {})
    hass.states.async_set("sensor.energy", 0, {"friendly_name": "Energy Meter"})
    hass.states.async_set("sensor.price", 0)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_PRICE_SENSOR: ["sensor.price"]},
        options={
            CONF_PRICE_SETTINGS: {
                "netting_enabled": True,
                "solar_bonus_enabled": True,
                "contract_start_date": "2025-01-01",
            }
        },
        entry_id="entry-create",
        subentries_data=[
            {
                "subentry_type": SUBENTRY_TYPE_SOURCE,
                "data": {
                    CONF_SOURCE_TYPE: SOURCE_TYPE_PRODUCTION,
                    CONF_SOURCES: ["sensor.energy"],
                },
                "title": SOURCE_TYPE_PRODUCTION,
                "unique_id": None,
            }
        ],
    )
    entry.add_to_hass(hass)
    entry.runtime_data = RuntimeData()
    added = []

    async def add_entities(entities, update=False):
        added.extend(entities)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            sensor_module.NettingTracker,
            "async_create",
            AsyncMock(
                return_value=type(
                    "Netting",
                    (),
                    {"tax_balance_per_sensor": {}, "net_consumption_kwh": 0.0},
                )()
            ),
        )
        mp.setattr(
            sensor_module.SolarBonusTracker,
            "async_create",
            AsyncMock(
                return_value=type(
                    "Solar", (), {"year_production_kwh": 0.0, "total_bonus_euro": 0.0}
                )()
            ),
        )
        await sensor_async_setup_entry(hass, entry, add_entities)

    assert "entry-create" in hass.data[DOMAIN]["netting"]
    assert "entry-create" in hass.data[DOMAIN]["solar_bonus"]


async def test_current_price_handle_sunrise_sunset_callback_invalid_float(
    hass: HomeAssistant,
):
    sensor = CurrentElectricityPriceSensor(
        hass,
        "Sun Invalid",
        "sun-invalid",
        price_sensor="sensor.price",
        source_type=SOURCE_TYPE_PRODUCTION,
        price_settings={
            "production_price_include_vat": False,
            "solar_bonus_enabled": True,
            "average_prices_to_hourly": False,
            "vat_percentage": 0.0,
        },
        icon="mdi:flash",
        device=DeviceInfo(identifiers={("d", "sun-invalid")}),
    )
    hass.states.async_set("sensor.price", "bad")
    now = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
    calls = {"writes": 0}
    sensor.async_write_ha_state = lambda *a, **k: calls.__setitem__(
        "writes", calls["writes"] + 1
    )

    def fake_track_point_in_time(hass_arg, callback, when):
        calls["callback"] = callback
        return lambda: None

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(sensor_module.dt_util, "now", lambda: now)
        mp.setattr(
            sensor,
            "_get_sunrise_sunset_times",
            lambda date_obj: (now + timedelta(hours=1), None),
        )
        mp.setattr(sensor_module, "async_track_point_in_time", fake_track_point_in_time)
        sensor._schedule_sunrise_sunset_updates()
        await calls["callback"](now + timedelta(hours=1))

    assert calls["writes"] == 1


async def test_sensor_async_setup_entry_reuses_trackers_and_anniversary_callback(
    hass: HomeAssistant,
):
    from custom_components.dynamic_energy_contract_calculator import RuntimeData

    class DummyTracker:
        def __init__(self):
            self.updated = None
            self.reset = 0
            self.next_anniversary = datetime(2026, 1, 2, tzinfo=timezone.utc).date()
            self.tax_balance_per_sensor = {}
            self.net_consumption_kwh = 0.0

        def update_price_settings(self, price_settings):
            self.updated = price_settings

        async def async_reset_year(self):
            self.reset += 1

        def get_next_anniversary_date(self):
            return self.next_anniversary

    existing_netting = DummyTracker()
    existing_solar = DummyTracker()
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN]["netting"] = {"entry-reuse": existing_netting}
    hass.data[DOMAIN]["solar_bonus"] = {"entry-reuse": existing_solar}
    hass.states.async_set("sensor.energy", 0, {"friendly_name": "Energy Meter"})
    hass.states.async_set("sensor.gas", 0, {"friendly_name": "Gas Meter"})
    hass.states.async_set("sensor.price", 0)
    hass.states.async_set("sensor.gas_price", 0)

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_PRICE_SENSOR_GAS: "sensor.gas_price",
            CONF_PRICE_SENSOR: "sensor.price",
        },
        options={
            CONF_PRICE_SETTINGS: {
                "netting_enabled": True,
                "solar_bonus_enabled": True,
                "reset_on_contract_anniversary": True,
                "contract_start_date": "2025-01-01",
            }
        },
        entry_id="entry-reuse",
        subentries_data=[
            {
                "subentry_type": SUBENTRY_TYPE_SOURCE,
                "data": {
                    CONF_SOURCE_TYPE: SOURCE_TYPE_CONSUMPTION,
                    CONF_SOURCES: ["sensor.energy"],
                },
                "title": SOURCE_TYPE_CONSUMPTION,
                "unique_id": None,
            },
            {
                "subentry_type": SUBENTRY_TYPE_SOURCE,
                "data": {
                    CONF_SOURCE_TYPE: SOURCE_TYPE_GAS,
                    CONF_SOURCES: ["sensor.gas"],
                },
                "title": SOURCE_TYPE_GAS,
                "unique_id": None,
            },
            {
                "subentry_type": SUBENTRY_TYPE_SOURCE,
                "data": {
                    CONF_SOURCE_TYPE: SOURCE_TYPE_PRODUCTION,
                    CONF_SOURCES: ["sensor.energy"],
                },
                "title": SOURCE_TYPE_PRODUCTION,
                "unique_id": None,
            },
        ],
    )
    entry.add_to_hass(hass)
    entry.runtime_data = RuntimeData()
    added = []
    unloads = []

    def add_entities(entities, update=False):
        added.extend(entities)

    entry.async_on_unload = lambda unsub: unloads.append(unsub)

    scheduled = {}

    def fake_track_time_change(hass_arg, callback, **kwargs):
        scheduled["callback"] = callback
        return "unsub"

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(sensor_module, "async_track_time_change", fake_track_time_change)
        await sensor_async_setup_entry(hass, entry, add_entities)

    assert existing_netting.updated == entry.options[CONF_PRICE_SETTINGS]
    assert entry.runtime_data.netting_tracker is existing_netting
    assert entry.runtime_data.solar_bonus_tracker is existing_solar
    assert any(entity.unique_id == f"{DOMAIN}_solar_bonus_total" for entity in added)
    assert any(
        entity.unique_id == f"{DOMAIN}_current_gas_consumption_price"
        for entity in added
    )
    assert unloads == ["unsub"]

    for entity in added:
        entity.async_reset = AsyncMock()

    await scheduled["callback"](datetime(2026, 1, 2, 0, 0, tzinfo=timezone.utc))
    assert existing_solar.reset == 1
