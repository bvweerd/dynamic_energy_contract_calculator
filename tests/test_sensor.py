import pytest
from homeassistant.core import HomeAssistant
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import UnitOfEnergy

from custom_components.dynamic_energy_calculator.sensor import (
    BaseUtilitySensor,
    DynamicEnergySensor,
    TotalCostSensor,
    UTILITY_ENTITIES,
)
from custom_components.dynamic_energy_calculator.const import (
    SOURCE_TYPE_CONSUMPTION,
)


async def test_base_sensor_reset_and_set(hass: HomeAssistant):
    sensor = BaseUtilitySensor(
        "Test",
        "uid",
        UnitOfEnergy.KILO_WATT_HOUR,
        SensorDeviceClass.ENERGY,
        "mdi:flash",
        True,
    )
    sensor.hass = hass
    sensor.async_write_ha_state = lambda *args, **kwargs: None
    sensor._attr_native_value = 5
    sensor.reset()
    assert sensor.native_value == 0
    sensor.set_value(3.14)
    assert sensor.native_value == pytest.approx(3.14)


async def test_dynamic_energy_sensor_cost(hass: HomeAssistant):
    price_settings = {
        "electricity_consumption_markup_per_kwh": 0.0,
        "electricity_surcharge_per_kwh": 0.0,
        "vat_percentage": 0.0,
    }
    sensor = DynamicEnergySensor(
        hass,
        "Test",
        "uid",
        "sensor.energy",
        SOURCE_TYPE_CONSUMPTION,
        price_settings,
        price_sensor="sensor.price",
        mode="cost_total",
    )
    sensor._last_energy = 0
    hass.states.async_set("sensor.energy", 1)
    hass.states.async_set("sensor.price", 0.5)
    await sensor.async_update()
    assert sensor.native_value == pytest.approx(0.5)


async def test_total_cost_sensor(hass: HomeAssistant):
    UTILITY_ENTITIES.clear()
    cost = DynamicEnergySensor(
        hass,
        "Cost",
        "c1",
        "sensor.energy",
        SOURCE_TYPE_CONSUMPTION,
        {},
        mode="cost_total",
    )
    profit = DynamicEnergySensor(
        hass,
        "Profit",
        "p1",
        "sensor.energy",
        SOURCE_TYPE_CONSUMPTION,
        {},
        mode="profit_total",
    )
    UTILITY_ENTITIES.extend([cost, profit])
    cost._attr_native_value = 5
    profit._attr_native_value = 2
    total = TotalCostSensor(hass, "Total", "t1", None)
    await total.async_update()
    assert total.native_value == pytest.approx(3)
