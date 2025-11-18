import pytest
from homeassistant.core import HomeAssistant

from custom_components.dynamic_energy_contract_calculator.entity import (
    DynamicEnergySensor,
)
from custom_components.dynamic_energy_contract_calculator.const import (
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


async def test_base_utility_sensor_device_class_string(hass: HomeAssistant):
    """Test device class conversion from string."""
    from custom_components.dynamic_energy_contract_calculator.entity import (
        BaseUtilitySensor,
    )

    sensor = BaseUtilitySensor(
        name="Test",
        unique_id="uid",
        unit="kWh",
        device_class="energy",  # string instead of SensorDeviceClass
        icon="mdi:flash",
        visible=True,
    )
    from homeassistant.components.sensor import SensorDeviceClass
    assert sensor._attr_device_class == SensorDeviceClass.ENERGY


async def test_base_utility_sensor_async_reset(hass: HomeAssistant):
    """Test async_reset method."""
    from custom_components.dynamic_energy_contract_calculator.entity import (
        BaseUtilitySensor,
    )

    sensor = BaseUtilitySensor(
        name="Test",
        unique_id="uid",
        unit="kWh",
        device_class=None,
        icon="mdi:flash",
        visible=True,
    )
    sensor.hass = hass
    sensor._attr_native_value = 10.0
    sensor.async_write_ha_state = lambda: None

    await sensor.async_reset()
    assert sensor._attr_native_value == 0.0


async def test_base_utility_sensor_async_set_value(hass: HomeAssistant):
    """Test async_set_value method."""
    from custom_components.dynamic_energy_contract_calculator.entity import (
        BaseUtilitySensor,
    )

    sensor = BaseUtilitySensor(
        name="Test",
        unique_id="uid",
        unit="kWh",
        device_class=None,
        icon="mdi:flash",
        visible=True,
    )
    sensor.hass = hass
    sensor.async_write_ha_state = lambda: None

    await sensor.async_set_value(25.5)
    assert sensor._attr_native_value == 25.5


async def test_production_sensor_update(hass: HomeAssistant):
    """Test production sensor update."""
    from custom_components.dynamic_energy_contract_calculator.const import (
        SOURCE_TYPE_PRODUCTION,
    )

    sensor = await _make_sensor(
        hass,
        source_type=SOURCE_TYPE_PRODUCTION,
        mode="cost_total",
    )
    sensor._last_energy = 0
    hass.states.async_set("sensor.energy", 5.0)
    hass.states.async_set("sensor.price", 0.10)

    await sensor.async_update()
    # Should update with production calculation
    assert sensor._last_energy == 5.0


async def test_gas_sensor_update(hass: HomeAssistant):
    """Test gas sensor update."""
    from custom_components.dynamic_energy_contract_calculator.const import (
        SOURCE_TYPE_GAS,
    )

    sensor = await _make_sensor(
        hass,
        source_type=SOURCE_TYPE_GAS,
        mode="cost_total",
        price_settings={
            "per_unit_supplier_gas_consumption_markup": 0.05,
            "per_unit_gas_tax": 0.40,
            "vat_percentage": 21.0,
        },
    )
    sensor._last_energy = 0
    hass.states.async_set("sensor.energy", 5.0)
    hass.states.async_set("sensor.price", 0.50)

    await sensor.async_update()
    assert sensor._last_energy == 5.0


async def test_production_with_netting(hass: HomeAssistant):
    """Test production sensor with netting enabled."""
    from unittest.mock import MagicMock, AsyncMock
    from custom_components.dynamic_energy_contract_calculator.const import (
        SOURCE_TYPE_PRODUCTION,
    )

    sensor = await _make_sensor(
        hass,
        source_type=SOURCE_TYPE_PRODUCTION,
        mode="profit_total",  # netting only works in profit_total mode
        price_settings={
            "netting_enabled": True,
            "per_unit_electricity_tax": 0.10,
            "vat_percentage": 21.0,
        },
    )

    # Mock the netting tracker
    tracker = MagicMock()
    tracker.async_record_production = AsyncMock(return_value=(5.0, 0.5, []))
    sensor._netting_tracker = tracker

    sensor._last_energy = 0
    hass.states.async_set("sensor.energy", 5.0)
    hass.states.async_set("sensor.price", 0.10)

    await sensor.async_update()
    tracker.async_record_production.assert_called_once()


async def test_production_with_price_settings(hass: HomeAssistant):
    """Test production sensor with various price settings."""
    from custom_components.dynamic_energy_contract_calculator.const import (
        SOURCE_TYPE_PRODUCTION,
    )

    sensor = await _make_sensor(
        hass,
        source_type=SOURCE_TYPE_PRODUCTION,
        mode="cost_total",
        price_settings={
            "per_unit_supplier_electricity_production_markup": 0.02,
            "production_price_include_vat": True,
            "vat_percentage": 21.0,
        },
    )

    sensor._last_energy = 0
    hass.states.async_set("sensor.energy", 5.0)
    hass.states.async_set("sensor.price", 0.10)

    await sensor.async_update()
    assert sensor._last_energy == 5.0


async def test_production_without_vat(hass: HomeAssistant):
    """Test production sensor without VAT."""
    from custom_components.dynamic_energy_contract_calculator.const import (
        SOURCE_TYPE_PRODUCTION,
    )

    sensor = await _make_sensor(
        hass,
        source_type=SOURCE_TYPE_PRODUCTION,
        mode="cost_total",
        price_settings={
            "per_unit_supplier_electricity_production_markup": 0.02,
            "production_price_include_vat": False,
            "vat_percentage": 21.0,
        },
    )

    sensor._last_energy = 0
    hass.states.async_set("sensor.energy", 5.0)
    hass.states.async_set("sensor.price", 0.10)

    await sensor.async_update()
    assert sensor._last_energy == 5.0


async def test_sensor_apply_tax_adjustment(hass: HomeAssistant):
    """Test applying tax adjustment."""
    sensor = await _make_sensor(hass, mode="cost_total")
    sensor._attr_native_value = 10.0
    sensor.async_write_ha_state = lambda: None

    await sensor.async_apply_tax_adjustment(0.5)
    assert sensor._attr_native_value == 9.5
