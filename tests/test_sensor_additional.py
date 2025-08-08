import pytest
from datetime import datetime
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
    UTILITY_ENTITIES,
)
from homeassistant.helpers import entity_registry as er
from custom_components.dynamic_energy_contract_calculator.const import (
    SOURCE_TYPE_CONSUMPTION,
    SOURCE_TYPE_PRODUCTION,
    SOURCE_TYPE_GAS,
    CONF_CONFIGS,
    CONF_SOURCE_TYPE,
    CONF_SOURCES,
    CONF_PRICE_SENSOR_GAS,
    CONF_PRICE_SETTINGS,
    DOMAIN,
)
from pytest_homeassistant_custom_component.common import MockConfigEntry


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
    UTILITY_ENTITIES.clear()
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
    UTILITY_ENTITIES.append(dummy)
    sensor = TotalCostSensor(hass, "Total", "tid", DeviceInfo(identifiers={("d", "1")}))
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


async def test_daily_cost_sensors_initial_value(hass: HomeAssistant):
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

    assert e.native_value == pytest.approx(e._calculate_daily_cost())
    assert g.native_value == pytest.approx(g._calculate_daily_cost())


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
        data={
            CONF_CONFIGS: [
                {CONF_SOURCE_TYPE: SOURCE_TYPE_GAS, CONF_SOURCES: ["sensor.gas"]}
            ],
            CONF_PRICE_SENSOR_GAS: ["sensor.gprice"],
        },
        options={CONF_PRICE_SETTINGS: {}},
    )
    entry.add_to_hass(hass)
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
