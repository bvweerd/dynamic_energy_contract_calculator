from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dynamic_energy_contract_calculator.config_flow import (
    DynamicEnergyCalculatorOptionsFlowHandler,
)
from custom_components.dynamic_energy_contract_calculator.const import (
    CONF_PRICE_SETTINGS,
    DOMAIN,
)


async def test_options_flow_init_delegates(hass: HomeAssistant):
    """Test that async_step_init delegates to async_step_user."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, entry_id="1")
    flow = DynamicEnergyCalculatorOptionsFlowHandler(entry)
    flow.hass = hass

    result = await flow.async_step_init()
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"


async def test_options_flow_shows_form_without_input(hass: HomeAssistant):
    """Test that async_step_user shows form when no input given."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, entry_id="1")
    flow = DynamicEnergyCalculatorOptionsFlowHandler(entry)
    flow.hass = hass

    result = await flow.async_step_user()
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"


async def test_options_flow_finish_creates_entry(hass: HomeAssistant):
    """Test that selecting 'finish' creates an options entry."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, entry_id="1")
    flow = DynamicEnergyCalculatorOptionsFlowHandler(entry)
    flow.hass = hass

    result = await flow.async_step_user({"action": "finish"})
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert CONF_PRICE_SETTINGS in result["data"]


async def test_options_flow_price_settings(hass: HomeAssistant):
    """Test the price_settings action updates settings and returns to user menu."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, entry_id="1")
    flow = DynamicEnergyCalculatorOptionsFlowHandler(entry)
    flow.hass = hass

    result = await flow.async_step_user({"action": "price_settings"})
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "price_settings"

    result = await flow.async_step_price_settings({"vat_percentage": 10.0})
    assert flow.price_settings["vat_percentage"] == 10.0
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"


async def test_options_flow_load_preset(hass: HomeAssistant):
    """Test the load_preset action loads a preset and returns to user menu."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, entry_id="1")
    flow = DynamicEnergyCalculatorOptionsFlowHandler(entry)
    flow.hass = hass

    result = await flow.async_step_user({"action": "load_preset"})
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "load_preset"

    result = await flow.async_step_load_preset({"supplier_preset": "zonneplan_2026"})
    assert flow.price_settings["netting_enabled"] is True
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"


async def test_options_flow_load_preset_none(hass: HomeAssistant):
    """Test that selecting 'none' preset keeps current settings."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, entry_id="1")
    flow = DynamicEnergyCalculatorOptionsFlowHandler(entry)
    flow.hass = hass

    original_vat = flow.price_settings.get("vat_percentage")
    result = await flow.async_step_load_preset({"supplier_preset": "none"})
    assert flow.price_settings.get("vat_percentage") == original_vat
    assert result["type"] == FlowResultType.FORM


async def test_options_flow_reads_existing_price_settings(hass: HomeAssistant):
    """Test that options flow initializes from existing entry options."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={},
        options={CONF_PRICE_SETTINGS: {"vat_percentage": 21.0}},
        entry_id="1",
    )
    flow = DynamicEnergyCalculatorOptionsFlowHandler(entry)
    assert flow.price_settings["vat_percentage"] == 21.0
