import pytest
from homeassistant.core import HomeAssistant
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import UnitOfEnergy, UnitOfVolume
from homeassistant.helpers.entity import DeviceInfo, EntityCategory

from custom_components.dynamic_energy_calculator.sensor import (
    BaseUtilitySensor,
    DynamicEnergySensor,
    TotalCostSensor,
    TotalEnergyCostSensor,
    DailyGasCostSensor,
    DailyElectricityCostSensor,
    CurrentElectricityPriceSensor,
    UTILITY_ENTITIES,
)
from custom_components.dynamic_energy_calculator.const import (
    SOURCE_TYPE_CONSUMPTION,
    SOURCE_TYPE_GAS,
    SOURCE_TYPE_PRODUCTION,
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


async def test_dynamic_gas_sensor_cost(hass: HomeAssistant):
    price_settings = {
        "gas_markup_per_m3": 0.0,
        "gas_surcharge_per_m3": 0.0,
        "vat_percentage": 0.0,
    }
    sensor = DynamicEnergySensor(
        hass,
        "Gas",
        "gid",
        "sensor.gas",
        SOURCE_TYPE_GAS,
        price_settings,
        price_sensor="sensor.gas_price",
        mode="cost_total",
        unit=UnitOfVolume.CUBIC_METERS,
    )
    sensor._last_energy = 0
    hass.states.async_set("sensor.gas", 2)
    hass.states.async_set("sensor.gas_price", 1.2)
    await sensor.async_update()
    assert sensor.native_value == pytest.approx(2.4)


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


async def test_daily_gas_cost_sensor(hass: HomeAssistant):
    sensor = DailyGasCostSensor(
        hass,
        "Gas Fixed",
        "gid",
        {"gas_standing_charge_per_day": 0.5, "vat_percentage": 0.0},
        DeviceInfo(identifiers={("dec", "test")}),
    )
    assert sensor.entity_category is EntityCategory.DIAGNOSTIC
    assert sensor._calculate_daily_cost() == pytest.approx(0.5)


async def test_daily_electricity_cost_sensor(hass: HomeAssistant):
    sensor = DailyElectricityCostSensor(
        hass,
        "Electric Fixed",
        "eid",
        {
            "electricity_surcharge_per_day": 0.5,
            "electricity_standing_charge_per_day": 0.2,
            "electricity_tax_rebate_per_day": 0.1,
            "vat_percentage": 0.0,
        },
        DeviceInfo(identifiers={("dec", "test")}),
    )
    assert sensor.entity_category is EntityCategory.DIAGNOSTIC
    assert sensor._calculate_daily_cost() == pytest.approx(0.6)


async def test_current_gas_consumption_price(hass: HomeAssistant):
    price_settings = {
        "gas_markup_per_m3": 0.0,
        "gas_surcharge_per_m3": 0.0,
        "vat_percentage": 0.0,
    }
    sensor = CurrentElectricityPriceSensor(
        hass,
        "Gas Price",
        "gid",
        price_sensor="sensor.price",
        source_type=SOURCE_TYPE_GAS,
        price_settings=price_settings,
        icon="mdi:gas-burner",
        device=DeviceInfo(identifiers={("dec", "test")}),
    )
    assert sensor.native_unit_of_measurement == "€/m³"


async def test_current_electricity_price(hass: HomeAssistant):
    sensor = CurrentElectricityPriceSensor(
        hass,
        "Elec Price",
        "eid",
        price_sensor="sensor.price",
        source_type=SOURCE_TYPE_CONSUMPTION,
        price_settings={"vat_percentage": 0.0},
        icon="mdi:flash",
        device=DeviceInfo(identifiers={("dec", "test")}),
    )
    assert sensor.native_unit_of_measurement == "€/kWh"


async def test_total_energy_cost_multiple(hass: HomeAssistant):
    hass.states.async_set("sensor.net", 5)
    hass.states.async_set("sensor.fixed1", 1)
    hass.states.async_set("sensor.fixed2", 2)
    sensor = TotalEnergyCostSensor(
        hass,
        "Total",
        "uid",
        net_cost_entity_id="sensor.net",
        fixed_cost_entity_ids=["sensor.fixed1", "sensor.fixed2"],
        device=DeviceInfo(identifiers={("dec", "test")}),
    )
    await sensor.async_update()
    assert sensor.native_value == pytest.approx(8)


async def test_production_sensor_cost_and_profit(hass: HomeAssistant):
    price_settings = {
        "electricity_production_markup_per_kwh": 0.0,
        "vat_percentage": 0.0,
    }

    cost_sensor = DynamicEnergySensor(
        hass,
        "Production Cost",
        "pc1",
        "sensor.prod_energy",
        SOURCE_TYPE_PRODUCTION,
        price_settings,
        price_sensor="sensor.price",
        mode="cost_total",
    )

    profit_sensor = DynamicEnergySensor(
        hass,
        "Production Profit",
        "pp1",
        "sensor.prod_energy",
        SOURCE_TYPE_PRODUCTION,
        price_settings,
        price_sensor="sensor.price",
        mode="profit_total",
    )

    # Positive price should contribute to profit
    cost_sensor._last_energy = 0
    profit_sensor._last_energy = 0
    hass.states.async_set("sensor.prod_energy", 1)
    hass.states.async_set("sensor.price", 0.5)
    await cost_sensor.async_update()
    await profit_sensor.async_update()
    assert cost_sensor.native_value == pytest.approx(0.0)
    assert profit_sensor.native_value == pytest.approx(0.5)

    # Negative price should contribute to cost
    cost_sensor_neg = DynamicEnergySensor(
        hass,
        "Production Cost Neg",
        "pc2",
        "sensor.prod_energy",
        SOURCE_TYPE_PRODUCTION,
        price_settings,
        price_sensor="sensor.price",
        mode="cost_total",
    )

    profit_sensor_neg = DynamicEnergySensor(
        hass,
        "Production Profit Neg",
        "pp2",
        "sensor.prod_energy",
        SOURCE_TYPE_PRODUCTION,
        price_settings,
        price_sensor="sensor.price",
        mode="profit_total",
    )

    cost_sensor_neg._last_energy = 0
    profit_sensor_neg._last_energy = 0
    hass.states.async_set("sensor.prod_energy", 1)
    hass.states.async_set("sensor.price", -0.2)
    await cost_sensor_neg.async_update()
    await profit_sensor_neg.async_update()
    assert cost_sensor_neg.native_value == pytest.approx(0.2)
    assert profit_sensor_neg.native_value == pytest.approx(0.0)


async def test_production_price_no_vat(hass: HomeAssistant):
    price_settings = {
        "electricity_production_markup_per_kwh": 0.0,
        "vat_percentage": 21.0,
        "production_price_include_vat": False,
    }

    sensor = CurrentElectricityPriceSensor(
        hass,
        "Prod Price",
        "pp3",
        price_sensor="sensor.price",
        source_type=SOURCE_TYPE_PRODUCTION,
        price_settings=price_settings,
        icon="mdi:flash",
        device=DeviceInfo(identifiers={("dec", "test")}),
    )

    hass.states.async_set("sensor.price", 1.0)
    await sensor.async_update()
    assert sensor.native_value == pytest.approx(1.0)
