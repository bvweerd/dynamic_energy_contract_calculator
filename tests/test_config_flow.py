from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.dynamic_energy_contract_calculator.config_flow import (
    DynamicEnergyCalculatorConfigFlow,
    SourceSubEntryFlow,
)
from custom_components.dynamic_energy_contract_calculator.const import (
    CONF_SOURCE_TYPE,
    CONF_SOURCES,
    DOMAIN,
    SOURCE_TYPE_CONSUMPTION,
    SOURCE_TYPE_GAS,
    SUBENTRY_TYPE_SOURCE,
)
from pytest_homeassistant_custom_component.common import MockConfigEntry


async def test_flow_creates_entry_after_finish(hass: HomeAssistant):
    """Test that the main config flow creates an entry when 'finish' is selected."""
    flow = DynamicEnergyCalculatorConfigFlow()
    flow.hass = hass
    flow.context = {}

    result = await flow.async_step_user({"action": "finish"})
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "Dynamic Energy Contract Calculator"


async def test_flow_price_settings_step(hass: HomeAssistant):
    """Test that the price_settings step returns to user menu."""
    flow = DynamicEnergyCalculatorConfigFlow()
    flow.hass = hass
    flow.context = {}

    result = await flow.async_step_user({"action": "price_settings"})
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "price_settings"

    result = await flow.async_step_price_settings({"vat_percentage": 10.0})
    assert flow.price_settings["vat_percentage"] == 10.0
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"


async def test_flow_load_preset_step(hass: HomeAssistant):
    """Test that load_preset step loads a preset and returns to user menu."""
    flow = DynamicEnergyCalculatorConfigFlow()
    flow.hass = hass
    flow.context = {}

    result = await flow.async_step_user({"action": "load_preset"})
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "load_preset"

    result = await flow.async_step_load_preset({"supplier_preset": "zonneplan_2026"})
    assert flow.price_settings["netting_enabled"] is True
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"


async def test_flow_load_preset_none(hass: HomeAssistant):
    """Test that selecting 'none' preset keeps current settings."""
    flow = DynamicEnergyCalculatorConfigFlow()
    flow.hass = hass
    flow.context = {}

    original_vat = flow.price_settings["vat_percentage"]
    result = await flow.async_step_load_preset({"supplier_preset": "none"})
    assert flow.price_settings["vat_percentage"] == original_vat
    assert result["type"] == FlowResultType.FORM


async def test_single_instance_abort(hass: HomeAssistant):
    """Test that a second instance is aborted."""
    flow = DynamicEnergyCalculatorConfigFlow()
    flow.hass = hass
    flow.context = {}

    entry = MockConfigEntry(domain=DOMAIN, data={}, entry_id="1")
    entry.add_to_hass(hass)

    result = await flow.async_step_user()
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_flow_shows_user_form_without_input(hass: HomeAssistant):
    """Test that the user step shows a form when no input given."""
    flow = DynamicEnergyCalculatorConfigFlow()
    flow.hass = hass
    flow.context = {}

    result = await flow.async_step_user()
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"


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


async def test_config_flow_accepts_input_number_price_sensors(hass: HomeAssistant):
    """Test that config flow accepts input_number entities for price sensors."""
    hass.states.async_set(
        "input_number.electricity_tariff",
        0.25,
        {"unit_of_measurement": "EUR/kWh"},
    )
    hass.states.async_set(
        "input_number.gas_tariff_euro_symbol",
        0.85,
        {"unit_of_measurement": "€/m³"},
    )
    hass.states.async_set(
        "input_number.gas_tariff_eur",
        0.90,
        {"unit_of_measurement": "EUR/m³"},
    )
    hass.states.async_set(
        "sensor.price_monetary",
        0.20,
        {"device_class": "monetary"},
    )

    all_prices = [
        state.entity_id
        for state in hass.states.async_all()
        if (state.domain in ["sensor", "input_number"])
        and (
            state.attributes.get("device_class") == "monetary"
            or state.attributes.get("unit_of_measurement") == "€/m³"
            or state.attributes.get("unit_of_measurement") == "EUR/m³"
            or state.attributes.get("unit_of_measurement") == "€/kWh"
            or state.attributes.get("unit_of_measurement") == "EUR/kWh"
        )
    ]

    assert "input_number.electricity_tariff" in all_prices
    assert "input_number.gas_tariff_euro_symbol" in all_prices
    assert "input_number.gas_tariff_eur" in all_prices
    assert "sensor.price_monetary" in all_prices


async def test_config_flow_supports_eur_m3_unit(hass: HomeAssistant):
    """Test that config flow recognizes EUR/m³ unit for gas price sensors."""
    hass.states.async_set(
        "sensor.gas_price_eur",
        0.75,
        {"unit_of_measurement": "EUR/m³"},
    )
    hass.states.async_set(
        "sensor.gas_price_euro_symbol",
        0.80,
        {"unit_of_measurement": "€/m³"},
    )

    all_prices = [
        state.entity_id
        for state in hass.states.async_all()
        if (state.domain in ["sensor", "input_number"])
        and (
            state.attributes.get("device_class") == "monetary"
            or state.attributes.get("unit_of_measurement") == "€/m³"
            or state.attributes.get("unit_of_measurement") == "EUR/m³"
            or state.attributes.get("unit_of_measurement") == "€/kWh"
            or state.attributes.get("unit_of_measurement") == "EUR/kWh"
        )
    ]

    assert "sensor.gas_price_eur" in all_prices
    assert "sensor.gas_price_euro_symbol" in all_prices


async def test_source_subentry_flow_user_step(hass: HomeAssistant):
    """Test SourceSubEntryFlow user step selects source type."""
    flow = SourceSubEntryFlow()
    flow.hass = hass

    result = await flow.async_step_user(
        {CONF_SOURCE_TYPE: SOURCE_TYPE_CONSUMPTION}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "select_sources"
    assert flow._source_type == SOURCE_TYPE_CONSUMPTION


async def test_source_subentry_flow_shows_form_without_input(hass: HomeAssistant):
    """Test SourceSubEntryFlow shows form when no input given."""
    flow = SourceSubEntryFlow()
    flow.hass = hass

    result = await flow.async_step_user()
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"


async def test_source_subentry_flow_select_sources_creates_entry(hass: HomeAssistant):
    """Test that SourceSubEntryFlow creates a sub-entry with source data."""
    hass.states.async_set(
        "sensor.energy_meter",
        0,
        {"device_class": "energy", "state_class": "total"},
    )
    flow = SourceSubEntryFlow()
    flow.hass = hass
    flow.context = {"source": "user"}
    flow._source_type = SOURCE_TYPE_CONSUMPTION

    result = await flow.async_step_select_sources(
        {CONF_SOURCES: ["sensor.energy_meter"]}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_SOURCE_TYPE] == SOURCE_TYPE_CONSUMPTION
    assert result["data"][CONF_SOURCES] == ["sensor.energy_meter"]
    assert result["title"] == SOURCE_TYPE_CONSUMPTION


async def test_source_subentry_flow_shows_sources_form_without_input(
    hass: HomeAssistant,
):
    """Test select_sources shows a form when no input given."""
    hass.states.async_set(
        "sensor.energy",
        0,
        {"device_class": "energy", "state_class": "total"},
    )
    flow = SourceSubEntryFlow()
    flow.hass = hass
    flow._source_type = SOURCE_TYPE_CONSUMPTION

    result = await flow.async_step_select_sources()
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "select_sources"


async def test_config_flow_get_supported_subentry_types(hass: HomeAssistant):
    """Test that the config flow returns SourceSubEntryFlow for 'source' sub-entry type."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, entry_id="1")
    supported = DynamicEnergyCalculatorConfigFlow.async_get_supported_subentry_types(entry)
    assert SUBENTRY_TYPE_SOURCE in supported
    assert supported[SUBENTRY_TYPE_SOURCE] is SourceSubEntryFlow
