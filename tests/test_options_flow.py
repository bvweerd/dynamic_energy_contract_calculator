from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dynamic_energy_calculator.config_flow import (
    DynamicEnergyCalculatorOptionsFlowHandler,
)
from custom_components.dynamic_energy_calculator.const import (
    CONF_CONFIGS,
    CONF_SOURCE_TYPE,
    CONF_SOURCES,
    SOURCE_TYPE_CONSUMPTION,
)


async def test_options_flow_no_blocks(hass: HomeAssistant):
    entry = MockConfigEntry(domain="dynamic_energy_calculator", data={}, entry_id="1")
    flow = DynamicEnergyCalculatorOptionsFlowHandler(entry)
    flow.hass = hass

    result = await flow.async_step_user({CONF_SOURCE_TYPE: "finish"})
    assert result["type"] == FlowResultType.FORM
    assert result["errors"]["base"] == "no_blocks"


async def test_options_flow_full_flow(hass: HomeAssistant):
    entry = MockConfigEntry(domain="dynamic_energy_calculator", data={}, entry_id="1")
    flow = DynamicEnergyCalculatorOptionsFlowHandler(entry)
    flow.hass = hass

    result = await flow.async_step_user({CONF_SOURCE_TYPE: SOURCE_TYPE_CONSUMPTION})
    assert result["type"] == FlowResultType.FORM

    result = await flow.async_step_select_sources({CONF_SOURCES: ["sensor.energy"]})
    assert result["type"] == FlowResultType.FORM

    result = await flow.async_step_user({CONF_SOURCE_TYPE: "finish"})
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_CONFIGS] == [
        {CONF_SOURCE_TYPE: SOURCE_TYPE_CONSUMPTION, CONF_SOURCES: ["sensor.energy"]}
    ]


async def test_options_flow_price_settings(hass: HomeAssistant):
    entry = MockConfigEntry(domain="dynamic_energy_calculator", data={}, entry_id="1")
    flow = DynamicEnergyCalculatorOptionsFlowHandler(entry)
    flow.hass = hass

    result = await flow.async_step_user({CONF_SOURCE_TYPE: "price_settings"})
    assert result["type"] == FlowResultType.FORM

    result = await flow.async_step_price_settings({"vat_percentage": 10.0})
    assert flow.price_settings["vat_percentage"] == 10.0
    assert result["type"] == FlowResultType.FORM


async def test_options_flow_init_delegates(hass: HomeAssistant):
    entry = MockConfigEntry(domain="dynamic_energy_calculator", data={}, entry_id="1")
    flow = DynamicEnergyCalculatorOptionsFlowHandler(entry)
    flow.hass = hass
    result = await flow.async_step_init()
    assert result["type"] == FlowResultType.FORM
