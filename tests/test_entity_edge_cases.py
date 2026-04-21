import pytest
from unittest.mock import AsyncMock
from homeassistant.core import HomeAssistant
from homeassistant.components.sensor import SensorDeviceClass

from custom_components.dynamic_energy_contract_calculator.entity import (
    BaseUtilitySensor,
    DynamicEnergySensor,
)
from custom_components.dynamic_energy_contract_calculator.const import (
    SOURCE_TYPE_GAS,
    SOURCE_TYPE_CONSUMPTION,
    SOURCE_TYPE_PRODUCTION,
)


async def _make_sensor(hass: HomeAssistant, **kwargs) -> DynamicEnergySensor:
    defaults = dict(
        name="Test",
        unique_id="uid",
        energy_sensor="sensor.energy",
        source_type=SOURCE_TYPE_CONSUMPTION,
        price_settings={},
        price_sensor="sensor.price",
        mode="cost_total",
    )
    defaults.update(kwargs)
    sensor = DynamicEnergySensor(hass, **defaults)
    return sensor


async def test_energy_unavailable(hass: HomeAssistant):
    sensor = await _make_sensor(hass)
    called = {}
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "custom_components.dynamic_energy_contract_calculator.entity.UNAVAILABLE_GRACE_SECONDS",
            0,
        )

        def issue(hass_arg, issue_id, translation_key, placeholders=None):
            called["key"] = translation_key

        mp.setattr(
            "custom_components.dynamic_energy_contract_calculator.entity.async_report_issue",
            issue,
        )
        await sensor.async_update()
    assert called["key"] == "energy_source_unavailable"
    assert not sensor.available


async def test_energy_invalid(hass: HomeAssistant):
    sensor = await _make_sensor(hass)
    hass.states.async_set("sensor.energy", "bad")
    called = {}
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "custom_components.dynamic_energy_contract_calculator.entity.UNAVAILABLE_GRACE_SECONDS",
            0,
        )
        mp.setattr(
            "custom_components.dynamic_energy_contract_calculator.entity.async_report_issue",
            lambda *a, **k: called.update(ok=True),
        )
        await sensor.async_update()
    assert called.get("ok")
    assert not sensor.available


async def test_delta_negative(hass: HomeAssistant):
    sensor = await _make_sensor(hass, mode="kwh_total", price_sensor=None)
    sensor._last_energy = 5
    hass.states.async_set("sensor.energy", 4)
    await sensor.async_update()
    assert sensor.native_value == 0


async def test_missing_price_sensor_no_issue(hass: HomeAssistant):
    sensor = await _make_sensor(hass, price_sensor=None)
    sensor._last_energy = 0
    hass.states.async_set("sensor.energy", 1)
    called = {}
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "custom_components.dynamic_energy_contract_calculator.entity.async_report_issue",
            lambda *a, **k: called.update(missing=True),
        )
        await sensor.async_update()
    assert not called


async def test_price_unavailable(hass: HomeAssistant):
    sensor = await _make_sensor(hass)
    sensor._last_energy = 0
    hass.states.async_set("sensor.energy", 1)
    # price sensor unavailable
    hass.states.async_set("sensor.price", "unavailable")
    called = {}
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "custom_components.dynamic_energy_contract_calculator.entity.UNAVAILABLE_GRACE_SECONDS",
            0,
        )
        mp.setattr(
            "custom_components.dynamic_energy_contract_calculator.entity.async_report_issue",
            lambda *a, **k: called.update(price=True),
        )
        await sensor.async_update()
    assert called.get("price")
    assert not sensor.available


async def test_price_invalid(hass: HomeAssistant):
    sensor = await _make_sensor(hass)
    sensor._last_energy = 0
    hass.states.async_set("sensor.energy", 1)
    hass.states.async_set("sensor.price", "bad")
    called = {}
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "custom_components.dynamic_energy_contract_calculator.entity.UNAVAILABLE_GRACE_SECONDS",
            0,
        )
        mp.setattr(
            "custom_components.dynamic_energy_contract_calculator.entity.async_report_issue",
            lambda *a, **k: called.update(price=True),
        )
        await sensor.async_update()
    assert called.get("price")
    assert not sensor.available


async def test_unknown_source_type(hass: HomeAssistant):
    sensor = await _make_sensor(hass, source_type="other")
    sensor._last_energy = 0
    hass.states.async_set("sensor.energy", 1)
    hass.states.async_set("sensor.price", 1.0)
    await sensor.async_update()
    assert sensor.native_value == 0


async def test_handle_input_event(hass: HomeAssistant):
    sensor = await _make_sensor(hass, mode="kwh_total", price_sensor=None)
    sensor.async_write_ha_state = lambda *a, **k: None
    # unavailable state
    event = type("E", (), {"data": {"new_state": None}})()
    await sensor._handle_input_event(event)
    assert not sensor.available
    # valid state triggers update
    hass.states.async_set("sensor.energy", 1)
    updated = {}

    async def fake_update():
        updated["u"] = True

    sensor.async_update = fake_update
    event = type("E", (), {"data": {"new_state": hass.states.get("sensor.energy")}})()
    await sensor._handle_input_event(event)
    assert updated.get("u")


async def test_update_listener(hass: HomeAssistant):
    from custom_components.dynamic_energy_contract_calculator import _update_listener

    called = {}
    with pytest.MonkeyPatch.context() as mp:

        async def reload(entry_id):
            called["reloaded"] = entry_id

        mp.setattr(hass.config_entries, "async_reload", reload)
        entry = type("Entry", (), {"entry_id": "1"})()
        await _update_listener(hass, entry)
    assert called.get("reloaded") == "1"


async def test_issue_removed_on_recovery(hass: HomeAssistant):
    sensor = await _make_sensor(hass)
    issued = {}
    cleared = {}
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "custom_components.dynamic_energy_contract_calculator.entity.UNAVAILABLE_GRACE_SECONDS",
            0,
        )
        mp.setattr(
            "custom_components.dynamic_energy_contract_calculator.entity.async_report_issue",
            lambda *a, **k: issued.setdefault("called", True),
        )
        mp.setattr(
            "custom_components.dynamic_energy_contract_calculator.entity.async_clear_issue",
            lambda *a, **k: cleared.setdefault("called", True),
        )
        await sensor.async_update()
        assert issued.get("called")
        hass.states.async_set("sensor.energy", 1)
        hass.states.async_set("sensor.price", 0)
        await sensor.async_update()
        assert cleared.get("called")
        assert sensor.available


async def test_base_sensor_device_class_conversion_and_restore_invalid(
    hass: HomeAssistant,
):
    sensor = BaseUtilitySensor(
        "Test",
        "uid-device-class",
        "kWh",
        "energy",
        "mdi:flash",
        True,
    )
    assert sensor.device_class == SensorDeviceClass.ENERGY

    async def get_last_state():
        return type("State", (), {"state": "not-a-number"})()

    sensor.async_get_last_state = get_last_state
    await sensor.async_added_to_hass()
    assert sensor.native_value == 0.0


async def test_price_issue_removed_on_recovery(hass: HomeAssistant):
    sensor = await _make_sensor(hass)
    sensor._last_energy = 0
    hass.states.async_set("sensor.energy", 1)
    hass.states.async_set("sensor.price", "unavailable")
    cleared = {}

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "custom_components.dynamic_energy_contract_calculator.entity.UNAVAILABLE_GRACE_SECONDS",
            0,
        )
        mp.setattr(
            "custom_components.dynamic_energy_contract_calculator.entity.async_clear_issue",
            lambda *a, **k: cleared.setdefault("called", []).append(a[1]),
        )
        await sensor.async_update()
        hass.states.async_set("sensor.energy", 2)
        hass.states.async_set("sensor.price", 0.5)
        await sensor.async_update()

    assert cleared["called"] == [
        "price_unavailable_sensor.price",
        "price_invalid_sensor.price",
    ]
    assert sensor.available


async def test_consumption_sensor_with_netting_tracker(hass: HomeAssistant):
    tracker = type(
        "Tracker",
        (),
        {
            "async_record_consumption": AsyncMock(return_value=(1.0, 0.12)),
            "async_register_sensor": AsyncMock(),
            "async_unregister_sensor": AsyncMock(),
        },
    )()
    sensor = await _make_sensor(
        hass,
        unique_id="netting-sensor",
        price_settings={
            "per_unit_supplier_electricity_markup": 0.1,
            "per_unit_government_electricity_tax": 0.2,
            "vat_percentage": 0.0,
        },
        netting_tracker=tracker,
    )
    sensor._last_energy = 0
    hass.states.async_set("sensor.energy", 1)
    hass.states.async_set("sensor.price", 0.5)

    await sensor.async_update()
    assert sensor.native_value == pytest.approx(0.72)

    sensor.async_on_remove = lambda unsub: None
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "custom_components.dynamic_energy_contract_calculator.entity.async_track_state_change_event",
            lambda *a, **k: "unsub",
        )
        await sensor.async_added_to_hass()
    tracker.async_register_sensor.assert_awaited_once_with(sensor)

    await sensor.async_will_remove_from_hass()
    tracker.async_unregister_sensor.assert_awaited_once_with(sensor)


async def test_production_sensor_solar_bonus_and_netting(hass: HomeAssistant):
    netting_tracker = type(
        "Tracker",
        (),
        {"async_record_production": AsyncMock(return_value=(1.0, 0.2, []))},
    )()
    solar_bonus_tracker = type(
        "SolarTracker",
        (),
        {"async_calculate_bonus": AsyncMock(return_value=(0.3, 1.5))},
    )()
    sensor = await _make_sensor(
        hass,
        source_type=SOURCE_TYPE_PRODUCTION,
        mode="profit_total",
        price_settings={
            "per_unit_supplier_electricity_production_markup": 0.05,
            "production_price_include_vat": False,
            "solar_bonus_enabled": True,
            "solar_bonus_percentage": 10.0,
            "solar_bonus_annual_kwh_limit": 7500.0,
        },
        netting_tracker=netting_tracker,
        solar_bonus_tracker=solar_bonus_tracker,
    )
    sensor._last_energy = 0
    hass.states.async_set("sensor.energy", 2)
    hass.states.async_set("sensor.price", 0.4)

    await sensor.async_update()

    solar_bonus_tracker.async_calculate_bonus.assert_awaited_once()
    netting_tracker.async_record_production.assert_awaited_once()
    assert sensor.native_value == pytest.approx(1.4)


async def test_gas_sensor_cost_and_tax_adjustment(hass: HomeAssistant):
    sensor = await _make_sensor(
        hass,
        source_type=SOURCE_TYPE_GAS,
        energy_sensor="sensor.gas",
        price_sensor="sensor.gas_price",
        price_settings={
            "per_unit_supplier_gas_markup": 0.1,
            "per_unit_government_gas_tax": 0.2,
            "vat_percentage": 0.0,
        },
        mode="cost_total",
    )
    sensor._last_energy = 0
    hass.states.async_set("sensor.gas", 2)
    hass.states.async_set("sensor.gas_price", 0.5)

    await sensor.async_update()
    assert sensor.native_value == pytest.approx(1.6)

    sensor.async_write_ha_state = lambda *a, **k: None
    await sensor.async_apply_tax_adjustment(0)
    assert sensor.native_value == pytest.approx(1.6)
    await sensor.async_apply_tax_adjustment(2.0)
    assert sensor.native_value == 0.0


async def test_dynamic_energy_sensor_reset_and_set_value_wrappers(hass: HomeAssistant):
    sensor = await _make_sensor(hass)
    sensor.async_write_ha_state = lambda *a, **k: None
    sensor._attr_native_value = 5.0
    await sensor.async_reset()
    assert sensor.native_value == 0.0
    await sensor.async_set_value(3.333333333)
    assert sensor.native_value == pytest.approx(3.33333333)
