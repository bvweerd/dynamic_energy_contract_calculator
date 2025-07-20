import pytest
from homeassistant.core import HomeAssistant

from custom_components.dynamic_energy_calculator.entity import DynamicEnergySensor
from custom_components.dynamic_energy_calculator.const import (
    SOURCE_TYPE_CONSUMPTION,
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

        def issue(hass_arg, issue_id, translation_key, placeholders=None):
            called["key"] = translation_key

        mp.setattr(
            "custom_components.dynamic_energy_calculator.entity.async_report_issue",
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
            "custom_components.dynamic_energy_calculator.entity.async_report_issue",
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


async def test_missing_price_sensor(hass: HomeAssistant):
    sensor = await _make_sensor(hass, price_sensor=None)
    sensor._last_energy = 0
    hass.states.async_set("sensor.energy", 1)
    called = {}
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "custom_components.dynamic_energy_calculator.entity.async_report_issue",
            lambda *a, **k: called.update(missing=True),
        )
        await sensor.async_update()
    assert called.get("missing")


async def test_price_unavailable(hass: HomeAssistant):
    sensor = await _make_sensor(hass)
    sensor._last_energy = 0
    hass.states.async_set("sensor.energy", 1)
    # price sensor unavailable
    hass.states.async_set("sensor.price", "unavailable")
    called = {}
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "custom_components.dynamic_energy_calculator.entity.async_report_issue",
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
            "custom_components.dynamic_energy_calculator.entity.async_report_issue",
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
    from custom_components.dynamic_energy_calculator import _update_listener

    called = {}
    with pytest.MonkeyPatch.context() as mp:

        async def reload(entry_id):
            called["reloaded"] = entry_id

        mp.setattr(hass.config_entries, "async_reload", reload)
        entry = type("Entry", (), {"entry_id": "1"})()
        await _update_listener(hass, entry)
    assert called.get("reloaded") == "1"
