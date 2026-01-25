import pytest
from datetime import datetime
from homeassistant.core import HomeAssistant
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import UnitOfEnergy, UnitOfVolume
from homeassistant.helpers.entity import DeviceInfo

from custom_components.dynamic_energy_contract_calculator.entity import (
    BaseUtilitySensor,
    DynamicEnergySensor,
)
from custom_components.dynamic_energy_contract_calculator.sensor import (
    TotalCostSensor,
    TotalEnergyCostSensor,
    DailyGasCostSensor,
    DailyElectricityCostSensor,
    CurrentElectricityPriceSensor,
    UTILITY_ENTITIES,
)
from homeassistant.helpers import entity_registry as er
from custom_components.dynamic_energy_contract_calculator.const import (
    DOMAIN,
    SOURCE_TYPE_CONSUMPTION,
    SOURCE_TYPE_GAS,
    SOURCE_TYPE_PRODUCTION,
)
from custom_components.dynamic_energy_contract_calculator.netting import (
    NettingTracker,
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
    await sensor.async_reset()
    assert sensor.native_value == 0
    await sensor.async_set_value(3.14)
    assert sensor.native_value == pytest.approx(3.14)


async def test_dynamic_energy_sensor_cost(hass: HomeAssistant):
    price_settings = {
        "per_unit_supplier_electricity_markup": 0.0,
        "per_unit_government_electricity_tax": 0.0,
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


async def test_dynamic_energy_sensor_multiple_prices(hass: HomeAssistant):
    price_settings = {
        "per_unit_supplier_electricity_markup": 0.0,
        "per_unit_government_electricity_tax": 0.0,
        "vat_percentage": 0.0,
    }
    sensor = DynamicEnergySensor(
        hass,
        "TestMulti",
        "uidmulti",
        "sensor.energy",
        SOURCE_TYPE_CONSUMPTION,
        price_settings,
        price_sensor=["sensor.price1", "sensor.price2"],
        mode="cost_total",
    )
    sensor._last_energy = 0
    hass.states.async_set("sensor.energy", 1)
    hass.states.async_set("sensor.price1", 0.3)
    hass.states.async_set("sensor.price2", 0.2)
    await sensor.async_update()
    assert sensor.native_value == pytest.approx(0.5)


async def test_dynamic_gas_sensor_cost(hass: HomeAssistant):
    price_settings = {
        "per_unit_supplier_gas_markup": 0.0,
        "per_unit_government_gas_tax": 0.0,
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
    total = TotalCostSensor(
        hass,
        "Total",
        "t1",
        None,
        netting_tracker=None,
    )
    await total.async_update()
    assert total.native_value == pytest.approx(3)
    assert total.extra_state_attributes == {"netting_enabled": False}


async def test_daily_gas_cost_sensor(hass: HomeAssistant):
    sensor = DailyGasCostSensor(
        hass,
        "Gas Fixed",
        "gid",
        {"per_day_supplier_gas_standing_charge": 0.5, "vat_percentage": 0.0},
        DeviceInfo(identifiers={("dec", "test")}),
    )
    assert sensor.entity_category is None
    assert sensor._calculate_daily_cost() == pytest.approx(0.5)
    # Gas sensor should not have netting attributes
    assert sensor.extra_state_attributes is None


async def test_daily_electricity_cost_sensor(hass: HomeAssistant):
    sensor = DailyElectricityCostSensor(
        hass,
        "Electric Fixed",
        "eid",
        {
            "per_day_grid_operator_electricity_connection_fee": 0.5,
            "per_day_supplier_electricity_standing_charge": 0.2,
            "per_day_government_electricity_tax_rebate": 0.1,
            "vat_percentage": 0.0,
        },
        DeviceInfo(identifiers={("dec", "test")}),
    )
    assert sensor.entity_category is None
    assert sensor._calculate_daily_cost() == pytest.approx(0.6)
    assert sensor.extra_state_attributes == {"netting_enabled": False}


async def test_current_gas_consumption_price(hass: HomeAssistant):
    price_settings = {
        "per_unit_supplier_gas_markup": 0.0,
        "per_unit_government_gas_tax": 0.0,
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
    assert sensor.state_class == SensorStateClass.MEASUREMENT


async def test_dynamic_energy_sensor_state_class(hass: HomeAssistant):
    sensor_kwh = DynamicEnergySensor(
        hass,
        "Energy",
        "eidkwh",
        "sensor.energy",
        SOURCE_TYPE_CONSUMPTION,
        {},
        mode="kwh_total",
    )
    assert sensor_kwh.state_class == SensorStateClass.TOTAL_INCREASING

    sensor_m3 = DynamicEnergySensor(
        hass,
        "Gas",
        "eidgas",
        "sensor.gas",
        SOURCE_TYPE_GAS,
        {},
        mode="m3_total",
        unit=UnitOfVolume.CUBIC_METERS,
    )
    assert sensor_m3.state_class == SensorStateClass.TOTAL_INCREASING


async def test_total_energy_cost_multiple(hass: HomeAssistant):
    er_reg = er.async_get(hass)
    er_reg.async_get_or_create("sensor", DOMAIN, "net_uid", suggested_object_id="net")
    er_reg.async_get_or_create(
        "sensor", DOMAIN, "fixed1_uid", suggested_object_id="fixed1"
    )
    er_reg.async_get_or_create(
        "sensor", DOMAIN, "fixed2_uid", suggested_object_id="fixed2"
    )
    hass.states.async_set("sensor.net", 5)
    hass.states.async_set("sensor.fixed1", 1)
    hass.states.async_set("sensor.fixed2", 2)
    sensor = TotalEnergyCostSensor(
        hass,
        "Total",
        "uid",
        net_cost_unique_id="net_uid",
        fixed_cost_unique_ids=["fixed1_uid", "fixed2_uid"],
        device=DeviceInfo(identifiers={("dec", "test")}),
    )
    await sensor.async_added_to_hass()
    await sensor.async_update()
    assert sensor.native_value == pytest.approx(8)


async def test_production_sensor_cost_and_profit(hass: HomeAssistant):
    price_settings = {
        "per_unit_supplier_electricity_production_markup": 0.0,
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
        "per_unit_supplier_electricity_production_markup": 0.0,
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


async def test_netting_applies_tax_credit(hass: HomeAssistant):
    tracker = await NettingTracker.async_create(hass, "entry_netting_credit")
    await tracker.async_reset_all()
    price_settings = {
        "per_unit_supplier_electricity_markup": 0.0,
        "per_unit_government_electricity_tax": 0.1,
        "vat_percentage": 21.0,
        "production_price_include_vat": True,
    }

    consumption = DynamicEnergySensor(
        hass,
        "Consumption Cost",
        "consumption_cost",
        "sensor.consumption_energy",
        SOURCE_TYPE_CONSUMPTION,
        price_settings,
        price_sensor="sensor.price",
        mode="cost_total",
        netting_tracker=tracker,
    )
    production = DynamicEnergySensor(
        hass,
        "Production Profit",
        "production_profit",
        "sensor.production_energy",
        SOURCE_TYPE_PRODUCTION,
        price_settings,
        price_sensor="sensor.price",
        mode="profit_total",
        netting_tracker=tracker,
    )

    consumption.async_write_ha_state = lambda *args, **kwargs: None
    production.async_write_ha_state = lambda *args, **kwargs: None

    await tracker.async_register_sensor(consumption)

    consumption._last_energy = 0.0
    hass.states.async_set("sensor.consumption_energy", 1.0)
    hass.states.async_set("sensor.price", 0.0)
    await consumption.async_update()

    assert consumption.native_value == pytest.approx(0.121, rel=1e-6)
    assert tracker.net_consumption_kwh == pytest.approx(1.0, rel=1e-6)

    production._last_energy = 0.0
    hass.states.async_set("sensor.production_energy", 1.0)
    await production.async_update()

    assert consumption.native_value == pytest.approx(0.0, abs=1e-6)
    assert tracker.net_consumption_kwh == pytest.approx(0.0, abs=1e-6)

    production._last_energy = 1.0
    hass.states.async_set("sensor.production_energy", 2.0)
    await production.async_update()

    assert consumption.native_value == pytest.approx(0.0, abs=1e-6)
    assert tracker.net_consumption_kwh == pytest.approx(-1.0, rel=1e-6)


async def test_summary_sensor_netting_attributes(hass: HomeAssistant):
    tracker = await NettingTracker.async_create(hass, "entry_netting_summary")
    await tracker.async_reset_all()
    price_settings = {
        "per_unit_supplier_electricity_markup": 0.0,
        "per_unit_government_electricity_tax": 0.1,
        "vat_percentage": 21.0,
    }

    cost_sensor = DynamicEnergySensor(
        hass,
        "Cost",
        "cost_uid",
        "sensor.energy",
        SOURCE_TYPE_CONSUMPTION,
        price_settings,
        price_sensor="sensor.price",
        mode="cost_total",
        netting_tracker=tracker,
    )
    cost_sensor.async_write_ha_state = lambda *args, **kwargs: None
    await tracker.async_register_sensor(cost_sensor)
    UTILITY_ENTITIES.clear()
    UTILITY_ENTITIES.append(cost_sensor)

    cost_sensor._last_energy = 0.0
    hass.states.async_set("sensor.energy", 1.0)
    hass.states.async_set("sensor.price", 0.0)
    await cost_sensor.async_update()

    summary = TotalCostSensor(
        hass,
        "Summary Total",
        "summary_uid",
        DeviceInfo(identifiers={("dec", "summary")}),
        netting_tracker=tracker,
    )
    summary.async_write_ha_state = lambda *args, **kwargs: None
    await summary.async_update()

    attrs = summary.extra_state_attributes
    assert attrs["netting_enabled"] is True
    assert attrs["netting_net_consumption_kwh"] == pytest.approx(1.0, rel=1e-6)
    assert attrs["netting_tax_balance_eur"] == pytest.approx(0.121, rel=1e-6)
    UTILITY_ENTITIES.clear()


async def test_missing_price_sensor_no_issue(hass: HomeAssistant):
    price_settings = {}
    sensor = DynamicEnergySensor(
        hass,
        "Test",
        "uid",
        "sensor.energy",
        SOURCE_TYPE_CONSUMPTION,
        price_settings,
        price_sensor=None,
        mode="cost_total",
    )
    sensor._last_energy = 0
    hass.states.async_set("sensor.energy", 1)
    called = {}
    with pytest.MonkeyPatch.context() as mp:

        def fake_issue(hass_arg, issue_id, translation_key, placeholders=None):
            called["issue_id"] = issue_id
            called["key"] = translation_key

        mp.setattr(
            "custom_components.dynamic_energy_contract_calculator.entity.async_report_issue",
            fake_issue,
        )
        await sensor.async_update()
    assert not called


async def test_base_sensor_restore_state(hass: HomeAssistant):
    sensor = BaseUtilitySensor("Restore", "uid1", "€", None, "mdi:flash", True)
    sensor.hass = hass
    sensor.async_write_ha_state = lambda *a, **k: None

    class LastState:
        state = "5.5"

    async def get_last_state():
        return LastState()

    sensor.async_get_last_state = get_last_state
    await sensor.async_added_to_hass()
    assert sensor.native_value == pytest.approx(5.5)


async def test_base_sensor_restore_invalid_state(hass: HomeAssistant):
    sensor = BaseUtilitySensor("Restore Bad", "uid2", "€", None, "mdi:flash", True)
    sensor.hass = hass
    sensor.async_write_ha_state = lambda *a, **k: None

    class LastState:
        state = "bad"

    async def get_last_state():
        return LastState()

    sensor.async_get_last_state = get_last_state
    await sensor.async_added_to_hass()
    assert sensor.native_value == 0


async def test_total_cost_sensor_handle_event(hass: HomeAssistant):
    sensor = TotalCostSensor(hass, "Total", "uid", None)
    sensor.hass = hass
    sensor.async_write_ha_state = lambda *a, **k: called.update({"write": True})

    called = {}

    async def fake_update():
        sensor._attr_native_value = 42

    sensor.async_update = fake_update

    event = type("Event", (), {"data": {"entity_id": "dummy"}})()
    await sensor._handle_input_event(event)
    assert sensor.native_value == pytest.approx(42)
    assert called.get("write")


async def test_daily_electricity_cost_handle_addition(hass: HomeAssistant):
    sensor = DailyElectricityCostSensor(
        hass,
        "Elec Fixed",
        "eid2",
        {
            "per_day_grid_operator_electricity_connection_fee": 0.5,
            "vat_percentage": 0.0,
        },
        DeviceInfo(identifiers={("dec", "test")}),
    )
    sensor.async_write_ha_state = lambda *a, **k: called.update({"write": True})
    called = {}
    await sensor._handle_daily_addition(datetime.now())
    assert sensor.native_value == pytest.approx(sensor._calculate_daily_cost())
    assert called.get("write")


async def test_current_price_handle_price_change(hass: HomeAssistant):
    sensor = CurrentElectricityPriceSensor(
        hass,
        "Current Price",
        "cid",
        price_sensor="sensor.price",
        source_type=SOURCE_TYPE_CONSUMPTION,
        price_settings={"vat_percentage": 0.0},
        icon="mdi:flash",
        device=DeviceInfo(identifiers={("dec", "test")}),
    )
    called = {}

    async def fake_update():
        sensor._attr_native_value = 1.23

    sensor.async_update = fake_update
    sensor.async_write_ha_state = lambda *a, **k: called.update({"write": True})
    event = type(
        "Event", (), {"data": {"new_state": type("S", (), {"state": "0.5"})()}}
    )()
    await sensor._handle_price_change(event)
    assert sensor.native_value == pytest.approx(1.23)
    assert called.get("write")


async def test_current_price_handle_price_change_unavailable(hass: HomeAssistant):
    sensor = CurrentElectricityPriceSensor(
        hass,
        "Current Price",
        "cid2",
        price_sensor="sensor.price",
        source_type=SOURCE_TYPE_CONSUMPTION,
        price_settings={"vat_percentage": 0.0},
        icon="mdi:flash",
        device=DeviceInfo(identifiers={("dec", "test")}),
    )
    called = {}
    sensor.async_write_ha_state = lambda *a, **k: called.update({"write": True})
    event = type("Event", (), {"data": {"new_state": None}})()
    await sensor._handle_price_change(event)
    assert not called
    assert not sensor.available


async def test_total_cost_sensor_handles_invalid_values(hass: HomeAssistant):
    from custom_components.dynamic_energy_contract_calculator.sensor import (
        TotalCostSensor,
        UTILITY_ENTITIES,
    )

    UTILITY_ENTITIES.clear()

    class BadValueSensor(DynamicEnergySensor):
        @property
        def native_value(self):
            return "bad"

    bad_cost = BadValueSensor(
        hass,
        "BadCost",
        "bc1",
        "sensor.energy",
        SOURCE_TYPE_CONSUMPTION,
        {},
        mode="cost_total",
    )
    bad_profit = BadValueSensor(
        hass,
        "BadProfit",
        "bp1",
        "sensor.energy",
        SOURCE_TYPE_CONSUMPTION,
        {},
        mode="profit_total",
    )
    UTILITY_ENTITIES.extend([bad_cost, bad_profit])
    sensor = TotalCostSensor(hass, "Total", "t_invalid", None)
    await sensor.async_update()
    assert sensor.native_value == 0


async def test_current_price_attributes(hass: HomeAssistant):
    sensor = CurrentElectricityPriceSensor(
        hass,
        "Attr Price",
        "attrid",
        price_sensor="sensor.price",
        source_type=SOURCE_TYPE_CONSUMPTION,
        price_settings={"vat_percentage": 0.0},
        icon="mdi:flash",
        device=DeviceInfo(identifiers={("dec", "attr")}),
    )

    raw_today = [
        {
            "start": "2025-07-25T00:00:00+02:00",
            "end": "2025-07-25T01:00:00+02:00",
            "value": 0.1,
        }
    ]
    raw_tomorrow = [
        {
            "start": "2025-07-26T00:00:00+02:00",
            "end": "2025-07-26T01:00:00+02:00",
            "value": 0.2,
        }
    ]

    hass.states.async_set(
        "sensor.price",
        0.1,
        {"raw_today": raw_today, "raw_tomorrow": raw_tomorrow},
    )
    await sensor.async_update()

    expected_today = [
        {"start": raw_today[0]["start"], "end": raw_today[0]["end"], "value": 0.1}
    ]
    expected_tomorrow = [
        {"start": raw_tomorrow[0]["start"], "end": raw_tomorrow[0]["end"], "value": 0.2}
    ]

    assert sensor.extra_state_attributes["net_prices_today"] == expected_today
    assert sensor.extra_state_attributes["net_prices_tomorrow"] == expected_tomorrow


async def test_current_price_attributes_entsoe(hass: HomeAssistant):
    sensor = CurrentElectricityPriceSensor(
        hass,
        "Attr Price Entsoe",
        "attrid_entsoe",
        price_sensor="sensor.price",
        source_type=SOURCE_TYPE_CONSUMPTION,
        price_settings={"vat_percentage": 0.0},
        icon="mdi:flash",
        device=DeviceInfo(identifiers={("dec", "attr_entsoe")}),
    )

    prices_today = [
        {"time": "2025-10-28 00:00:00+01:00", "price": "0.077"},
        {"time": "2025-10-28 00:15:00+01:00", "price": 0.0551},
    ]
    prices_tomorrow = [
        {"time": "2025-10-29 00:00:00+01:00", "price": 0.06591},
        {"time": "2025-10-29 00:15:00+01:00", "price": 0.06426},
    ]

    hass.states.async_set(
        "sensor.price",
        "0.077",
        {"prices_today": prices_today, "prices_tomorrow": prices_tomorrow},
    )

    await sensor.async_update()

    attrs_today = sensor.extra_state_attributes["net_prices_today"]
    attrs_tomorrow = sensor.extra_state_attributes["net_prices_tomorrow"]

    assert attrs_today is not None
    assert attrs_tomorrow is not None
    # With averaging enabled (default), quarter-hour entries are averaged to hourly
    assert len(attrs_today) == 1
    assert len(attrs_tomorrow) == 1
    # Check that the average price is correct: (0.077 + 0.0551) / 2 = 0.06605
    assert attrs_today[0]["value"] == pytest.approx(0.06605)
    assert attrs_today[0]["price"] == pytest.approx(0.06605)
    # Check that timezone is preserved in ISO format
    assert attrs_today[0]["time"].startswith("2025-10-28T00:00:00")
    assert "+01:00" in attrs_today[0]["time"]
    # Check tomorrow's average: (0.06591 + 0.06426) / 2 = 0.065085
    assert attrs_tomorrow[0]["value"] == pytest.approx(0.065085)
    assert attrs_tomorrow[0]["price"] == pytest.approx(0.065085)
    assert attrs_tomorrow[0]["time"].startswith("2025-10-29T00:00:00")
    assert "+01:00" in attrs_tomorrow[0]["time"]
    # Current value comes from sensor state, not the averaged values
    assert sensor.native_value == pytest.approx(0.077)


async def test_current_price_attributes_multiple_sensors(hass: HomeAssistant):
    sensor = CurrentElectricityPriceSensor(
        hass,
        "Attr Price Multi",
        "attrid_multi",
        price_sensor=["sensor.price1", "sensor.price2"],
        source_type=SOURCE_TYPE_CONSUMPTION,
        price_settings={"vat_percentage": 0.0},
        icon="mdi:flash",
        device=DeviceInfo(identifiers={("dec", "attr_multi")}),
    )

    raw_today_1 = [
        {
            "start": "2025-07-25T00:00:00+02:00",
            "end": "2025-07-25T01:00:00+02:00",
            "value": 0.1,
        },
        {
            "start": "2025-07-25T01:00:00+02:00",
            "end": "2025-07-25T02:00:00+02:00",
            "value": 0.2,
        },
    ]
    raw_today_2 = [
        {
            "start": "2025-07-25T00:00:00+02:00",
            "end": "2025-07-25T01:00:00+02:00",
            "value": 0.4,
        },
        {
            "start": "2025-07-25T01:00:00+02:00",
            "end": "2025-07-25T02:00:00+02:00",
            "value": 0.5,
        },
    ]
    raw_tomorrow_1 = [
        {
            "start": "2025-07-26T00:00:00+02:00",
            "end": "2025-07-26T01:00:00+02:00",
            "value": 0.3,
        }
    ]
    raw_tomorrow_2 = [
        {
            "start": "2025-07-26T00:00:00+02:00",
            "end": "2025-07-26T01:00:00+02:00",
            "value": 0.6,
        }
    ]

    hass.states.async_set(
        "sensor.price1",
        0.1,
        {"raw_today": raw_today_1, "raw_tomorrow": raw_tomorrow_1},
    )
    hass.states.async_set(
        "sensor.price2",
        0.4,
        {"raw_today": raw_today_2, "raw_tomorrow": raw_tomorrow_2},
    )

    await sensor.async_update()

    expected_today = [
        {
            "start": raw_today_1[0]["start"],
            "end": raw_today_1[0]["end"],
            "value": 0.5,
        },
        {
            "start": raw_today_1[1]["start"],
            "end": raw_today_1[1]["end"],
            "value": 0.7,
        },
    ]
    expected_tomorrow = [
        {
            "start": raw_tomorrow_1[0]["start"],
            "end": raw_tomorrow_1[0]["end"],
            "value": 0.9,
        }
    ]

    assert sensor.extra_state_attributes["net_prices_today"] == expected_today
    assert sensor.extra_state_attributes["net_prices_tomorrow"] == expected_tomorrow
    assert sensor.native_value == pytest.approx(0.5)


async def test_production_negative_price_no_solar_bonus(hass: HomeAssistant):
    """Test that solar bonus is NOT applied when EPEX price is negative."""
    price_settings = {
        "per_unit_supplier_electricity_production_markup": 0.02,  # €0.02 production compensation
        "vat_percentage": 0.0,
        "production_price_include_vat": False,
        "solar_bonus_enabled": True,
        "solar_bonus_percentage": 10.0,
    }

    sensor = CurrentElectricityPriceSensor(
        hass,
        "Production Negative Price",
        "prod_neg",
        price_sensor="sensor.price",
        source_type=SOURCE_TYPE_PRODUCTION,
        price_settings=price_settings,
        icon="mdi:flash",
        device=DeviceInfo(identifiers={("dec", "prod_neg")}),
    )

    # EPEX price is -0.05, so with production markup of 0.02:
    # Final price = -0.05 + 0.02 = -0.03 (negative)
    # Solar bonus should NOT be applied because final price is negative
    raw_today = [
        {
            "start": "2025-07-25T12:00:00+02:00",  # Noon - definitely daylight
            "end": "2025-07-25T13:00:00+02:00",
            "value": -0.05,
        }
    ]

    hass.states.async_set(
        "sensor.price",
        -0.05,
        {"raw_today": raw_today, "raw_tomorrow": []},
    )
    await sensor.async_update()

    net_prices = sensor.extra_state_attributes["net_prices_today"]
    assert len(net_prices) == 1
    # Should be -0.05 + 0.02 = -0.03, no solar bonus applied
    assert net_prices[0]["value"] == pytest.approx(-0.03)


async def test_production_small_negative_price_becomes_positive_with_markup(
    hass: HomeAssistant,
):
    """Test solar bonus IS applied when negative EPEX becomes positive with production markup."""
    price_settings = {
        "per_unit_supplier_electricity_production_markup": 0.05,  # €0.05 production compensation
        "vat_percentage": 0.0,
        "production_price_include_vat": False,
        "solar_bonus_enabled": True,
        "solar_bonus_percentage": 10.0,
    }

    sensor = CurrentElectricityPriceSensor(
        hass,
        "Production Small Negative",
        "prod_small_neg",
        price_sensor="sensor.price",
        source_type=SOURCE_TYPE_PRODUCTION,
        price_settings=price_settings,
        icon="mdi:flash",
        device=DeviceInfo(identifiers={("dec", "prod_small_neg")}),
    )

    # EPEX price is -0.02, but with production markup of 0.05:
    # Base price = -0.02 + 0.05 = 0.03 (positive!)
    # Solar bonus should be applied: 0.03 * 1.10 = 0.033
    raw_today = [
        {
            "start": "2025-07-25T12:00:00+02:00",  # Noon - definitely daylight
            "end": "2025-07-25T13:00:00+02:00",
            "value": -0.02,
        }
    ]

    hass.states.async_set(
        "sensor.price",
        -0.02,
        {"raw_today": raw_today, "raw_tomorrow": []},
    )
    await sensor.async_update()

    net_prices = sensor.extra_state_attributes["net_prices_today"]
    assert len(net_prices) == 1
    # Should be (-0.02 + 0.05) * 1.10 = 0.03 * 1.10 = 0.033
    assert net_prices[0]["value"] == pytest.approx(0.033)


async def test_production_positive_price_with_solar_bonus(hass: HomeAssistant):
    """Test that solar bonus IS applied for positive prices during daylight."""
    price_settings = {
        "per_unit_supplier_electricity_production_markup": 0.02,
        "vat_percentage": 0.0,
        "production_price_include_vat": False,
        "solar_bonus_enabled": True,
        "solar_bonus_percentage": 10.0,
    }

    sensor = CurrentElectricityPriceSensor(
        hass,
        "Production Positive Price",
        "prod_pos",
        price_sensor="sensor.price",
        source_type=SOURCE_TYPE_PRODUCTION,
        price_settings=price_settings,
        icon="mdi:flash",
        device=DeviceInfo(identifiers={("dec", "prod_pos")}),
    )

    # EPEX price is 0.10, with production markup of 0.02:
    # Base price = 0.10 + 0.02 = 0.12
    # Solar bonus: 0.12 * 1.10 = 0.132
    raw_today = [
        {
            "start": "2025-07-25T12:00:00+02:00",  # Noon - definitely daylight
            "end": "2025-07-25T13:00:00+02:00",
            "value": 0.10,
        }
    ]

    hass.states.async_set(
        "sensor.price",
        0.10,
        {"raw_today": raw_today, "raw_tomorrow": []},
    )
    await sensor.async_update()

    net_prices = sensor.extra_state_attributes["net_prices_today"]
    assert len(net_prices) == 1
    # Should be (0.10 + 0.02) * 1.10 = 0.132
    assert net_prices[0]["value"] == pytest.approx(0.132)


async def test_production_night_time_no_solar_bonus(hass: HomeAssistant):
    """Test that solar bonus is NOT applied during night time even with positive price."""
    price_settings = {
        "per_unit_supplier_electricity_production_markup": 0.02,
        "vat_percentage": 0.0,
        "production_price_include_vat": False,
        "solar_bonus_enabled": True,
        "solar_bonus_percentage": 10.0,
    }

    sensor = CurrentElectricityPriceSensor(
        hass,
        "Production Night",
        "prod_night",
        price_sensor="sensor.price",
        source_type=SOURCE_TYPE_PRODUCTION,
        price_settings=price_settings,
        icon="mdi:flash",
        device=DeviceInfo(identifiers={("dec", "prod_night")}),
    )

    # EPEX price is 0.10 at night
    # Base price = 0.10 + 0.02 = 0.12
    # Solar bonus should NOT be applied at night: result = 0.12
    raw_today = [
        {
            "start": "2025-07-25T02:00:00+02:00",  # 2 AM - night time
            "end": "2025-07-25T03:00:00+02:00",
            "value": 0.10,
        }
    ]

    hass.states.async_set(
        "sensor.price",
        0.10,
        {"raw_today": raw_today, "raw_tomorrow": []},
    )
    await sensor.async_update()

    net_prices = sensor.extra_state_attributes["net_prices_today"]
    assert len(net_prices) == 1
    # Should be 0.10 + 0.02 = 0.12 (no solar bonus at night)
    assert net_prices[0]["value"] == pytest.approx(0.12)
