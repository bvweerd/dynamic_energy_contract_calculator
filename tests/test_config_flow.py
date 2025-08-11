from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.dynamic_energy_contract_calculator.config_flow import (
    DynamicEnergyCalculatorConfigFlow,
)
from custom_components.dynamic_energy_contract_calculator.const import (
    CONF_CONFIGS,
    CONF_SOURCE_TYPE,
    CONF_SOURCES,
    DOMAIN,
    SOURCE_TYPE_CONSUMPTION,
    SOURCE_TYPE_GAS,
)
from pytest_homeassistant_custom_component.common import MockConfigEntry


async def test_flow_no_blocks(hass: HomeAssistant):
    flow = DynamicEnergyCalculatorConfigFlow()
    flow.hass = hass
    flow.context = {}

    result = await flow.async_step_user({CONF_SOURCE_TYPE: "finish"})
    assert result["type"] == FlowResultType.FORM
    assert result["errors"]["base"] == "no_blocks"


async def test_full_flow(hass: HomeAssistant):
    flow = DynamicEnergyCalculatorConfigFlow()
    flow.hass = hass
    flow.context = {}

    result = await flow.async_step_user({CONF_SOURCE_TYPE: SOURCE_TYPE_CONSUMPTION})
    assert result["type"] == FlowResultType.FORM

    result = await flow.async_step_select_sources({CONF_SOURCES: ["sensor.energy"]})
    assert result["type"] == FlowResultType.FORM

    result = await flow.async_step_user({CONF_SOURCE_TYPE: "finish"})
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_CONFIGS] == [
        {CONF_SOURCE_TYPE: SOURCE_TYPE_CONSUMPTION, CONF_SOURCES: ["sensor.energy"]}
    ]


async def test_single_instance_abort(hass: HomeAssistant):
    flow = DynamicEnergyCalculatorConfigFlow()
    flow.hass = hass
    flow.context = {}

    entry = MockConfigEntry(domain=DOMAIN, data={}, entry_id="1")
    entry.add_to_hass(hass)

    result = await flow.async_step_user()
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_edit_source_replaces_existing_config(hass: HomeAssistant):
    flow = DynamicEnergyCalculatorConfigFlow()
    flow.hass = hass
    flow.context = {}

    result = await flow.async_step_user({CONF_SOURCE_TYPE: SOURCE_TYPE_CONSUMPTION})
    assert result["type"] == FlowResultType.FORM

    result = await flow.async_step_select_sources({CONF_SOURCES: ["sensor.energy"]})
    assert result["type"] == FlowResultType.FORM

    result = await flow.async_step_user({CONF_SOURCE_TYPE: SOURCE_TYPE_CONSUMPTION})
    assert result["type"] == FlowResultType.FORM

    result = await flow.async_step_select_sources({CONF_SOURCES: ["sensor.energy_2"]})
    assert result["type"] == FlowResultType.FORM

    result = await flow.async_step_user({CONF_SOURCE_TYPE: "finish"})
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_CONFIGS] == [
        {
            CONF_SOURCE_TYPE: SOURCE_TYPE_CONSUMPTION,
            CONF_SOURCES: ["sensor.energy_2"],
        }
    ]


async def test_get_energy_sensors_filters_electricity(hass: HomeAssistant):
    from custom_components.dynamic_energy_contract_calculator.config_flow import (
        _get_energy_sensors,
    )

    hass.states.async_set(
        "sensor.energy_total",
        0,
        {"device_class": "energy", "state_class": "total"},
    )
    hass.states.async_set(
        "sensor.energy_measure",
        0,
        {"device_class": "energy", "state_class": "measurement"},
    )
    hass.states.async_set(
        "sensor.gas_total",
        0,
        {"device_class": "gas", "state_class": "total"},
    )

    sensors = await _get_energy_sensors(hass, SOURCE_TYPE_CONSUMPTION)
    assert sensors == ["sensor.energy_total"]


async def test_get_energy_sensors_filters_gas(hass: HomeAssistant):
    from custom_components.dynamic_energy_contract_calculator.config_flow import (
        _get_energy_sensors,
    )

    hass.states.async_set(
        "sensor.energy_total",
        0,
        {"device_class": "energy", "state_class": "total"},
    )
    hass.states.async_set(
        "sensor.gas_total",
        0,
        {"device_class": "gas", "state_class": "total"},
    )
    hass.states.async_set(
        "sensor.gas_measure",
        0,
        {"device_class": "gas", "state_class": "measurement"},
    )

    sensors = await _get_energy_sensors(hass, SOURCE_TYPE_GAS)
    assert sensors == ["sensor.gas_total"]
