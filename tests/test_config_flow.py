import pytest
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.dynamic_energy_contract_calculator.config_flow import (
    DynamicEnergyCalculatorConfigFlow,
    SourceSubEntryFlow,
    _apply_preset,
    _build_price_settings_schema,
)
from custom_components.dynamic_energy_contract_calculator.const import (
    CONF_PRICE_SENSOR,
    CONF_PRICE_SENSOR_GAS,
    CONF_SOURCE_TYPE,
    CONF_SOURCES,
    DEFAULT_PRICE_SETTINGS,
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

    result = await flow.async_step_user({CONF_SOURCE_TYPE: SOURCE_TYPE_CONSUMPTION})
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
    supported = DynamicEnergyCalculatorConfigFlow.async_get_supported_subentry_types(
        entry
    )
    assert SUBENTRY_TYPE_SOURCE in supported
    assert supported[SUBENTRY_TYPE_SOURCE] is SourceSubEntryFlow


async def test_apply_preset_updates_only_matching_fields() -> None:
    original = {
        **DEFAULT_PRICE_SETTINGS,
        "per_unit_supplier_electricity_markup": 1.0,
        "per_unit_supplier_gas_markup": 2.0,
    }

    gas_only = _apply_preset(
        original,
        {
            "per_unit_supplier_gas_markup": 0.4,
            "vat_percentage": 9.0,
            "per_unit_supplier_electricity_markup": 0.0,
        },
    )
    assert gas_only["per_unit_supplier_gas_markup"] == pytest.approx(0.4)
    assert gas_only["per_unit_supplier_electricity_markup"] == pytest.approx(1.0)
    assert gas_only["vat_percentage"] == pytest.approx(9.0)

    electricity_only = _apply_preset(
        original,
        {
            "per_unit_supplier_electricity_markup": 0.2,
            "netting_enabled": True,
            "per_unit_supplier_gas_markup": 0.0,
        },
    )
    assert electricity_only["per_unit_supplier_electricity_markup"] == pytest.approx(
        0.2
    )
    assert electricity_only["per_unit_supplier_gas_markup"] == pytest.approx(2.0)
    assert electricity_only["netting_enabled"] is True

    mixed = _apply_preset(
        original,
        {
            "per_unit_supplier_electricity_markup": 0.3,
            "per_unit_supplier_gas_markup": 0.6,
        },
    )
    assert mixed["per_unit_supplier_electricity_markup"] == pytest.approx(0.3)
    assert mixed["per_unit_supplier_gas_markup"] == pytest.approx(0.6)


async def test_build_price_settings_schema_normalizes_string_price_sensor() -> None:
    schema = _build_price_settings_schema(
        {
            CONF_PRICE_SENSOR: "sensor.price",
            CONF_PRICE_SENSOR_GAS: "sensor.gas_price",
            "contract_start_date": "",
        },
        ["sensor.price", "sensor.gas_price"],
    )

    result = schema(
        {
            CONF_PRICE_SENSOR: ["sensor.price"],
            CONF_PRICE_SENSOR_GAS: ["sensor.gas_price"],
            **{
                key: value
                for key, value in DEFAULT_PRICE_SETTINGS.items()
                if key
                not in (
                    CONF_PRICE_SENSOR,
                    CONF_PRICE_SENSOR_GAS,
                    "contract_start_date",
                )
            },
        }
    )

    assert result[CONF_PRICE_SENSOR] == ["sensor.price"]
    assert result[CONF_PRICE_SENSOR_GAS] == ["sensor.gas_price"]
    assert "contract_start_date" not in result


async def test_build_price_settings_schema_with_contract_date_and_string_option() -> (
    None
):
    schema = _build_price_settings_schema(
        {
            CONF_PRICE_SENSOR: [],
            CONF_PRICE_SENSOR_GAS: [],
            "contract_start_date": "2025-01-15",
            "custom_string": "abc",
        },
        [],
    )

    result = schema(
        {
            CONF_PRICE_SENSOR: [],
            CONF_PRICE_SENSOR_GAS: [],
            "contract_start_date": "2025-01-15",
            **{
                key: value
                for key, value in DEFAULT_PRICE_SETTINGS.items()
                if key
                not in (CONF_PRICE_SENSOR, CONF_PRICE_SENSOR_GAS, "contract_start_date")
            },
        }
    )

    assert result["contract_start_date"] == "2025-01-15"


async def test_build_price_settings_schema_custom_string_branch(monkeypatch) -> None:
    monkeypatch.setattr(
        "custom_components.dynamic_energy_contract_calculator.config_flow.DEFAULT_PRICE_SETTINGS",
        {
            **DEFAULT_PRICE_SETTINGS,
            CONF_PRICE_SENSOR: [],
            CONF_PRICE_SENSOR_GAS: [],
            "custom_string_setting": "hello",
        },
    )

    schema = _build_price_settings_schema(
        {"custom_string_setting": "world"},
        [],
    )
    result = schema(
        {
            "custom_string_setting": "value",
            **{
                key: value
                for key, value in DEFAULT_PRICE_SETTINGS.items()
                if key not in ("contract_start_date",)
            },
        }
    )

    assert result["custom_string_setting"] == "value"


async def test_source_subentry_flow_reconfigure_form_and_submit(hass: HomeAssistant):
    hass.states.async_set(
        "sensor.energy_1",
        0,
        {"device_class": "energy", "state_class": "total"},
    )
    hass.states.async_set(
        "sensor.energy_2",
        0,
        {"device_class": "energy", "state_class": "total_increasing"},
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={},
        entry_id="reconfigure-entry",
        subentries_data=[
            {
                "subentry_type": SUBENTRY_TYPE_SOURCE,
                "data": {
                    CONF_SOURCE_TYPE: SOURCE_TYPE_CONSUMPTION,
                    CONF_SOURCES: ["sensor.energy_1"],
                },
                "title": SOURCE_TYPE_CONSUMPTION,
                "unique_id": None,
            }
        ],
    )
    entry.add_to_hass(hass)
    subentry = next(iter(entry.subentries.values()))
    flow = SourceSubEntryFlow()
    flow.hass = hass
    flow.handler = DOMAIN
    flow.context = {}
    flow._get_entry = lambda: entry
    flow._get_reconfigure_subentry = lambda: subentry
    flow.async_update_and_abort = lambda entry_arg, subentry_arg, **kwargs: {
        "type": FlowResultType.ABORT,
        "entry": entry_arg,
        "subentry": subentry_arg,
        **kwargs,
    }

    result = await flow.async_step_reconfigure()
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    result = await flow.async_step_reconfigure(
        {
            CONF_SOURCE_TYPE: SOURCE_TYPE_GAS,
            CONF_SOURCES: ["sensor.energy_2"],
        }
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["title"] == SOURCE_TYPE_GAS
    assert result["data"][CONF_SOURCES] == ["sensor.energy_2"]
