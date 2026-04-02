from __future__ import annotations

import copy
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import (
    ConfigFlowContext,
    ConfigFlowResult,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import selector

from .const import (
    CONF_PRICE_SENSOR,
    CONF_PRICE_SENSOR_GAS,
    CONF_PRICE_SETTINGS,
    CONF_SOURCE_TYPE,
    CONF_SOURCES,
    DEFAULT_PRICE_SETTINGS,
    DOMAIN,
    SOURCE_TYPE_GAS,
    SOURCE_TYPES,
    SUBENTRY_TYPE_SOURCE,
    SUPPLIER_PRESETS,
)

STEP_SELECT_SOURCES = "select_sources"
STEP_PRICE_SETTINGS = "price_settings"
STEP_LOAD_PRESET = "load_preset"

# Field categories for smart preset loading
GAS_CORE_FIELDS = {
    "per_unit_supplier_gas_markup",
    "per_unit_government_gas_tax",
    "per_day_grid_operator_gas_connection_fee",
    "per_day_supplier_gas_standing_charge",
}

ELECTRICITY_CORE_FIELDS = {
    "per_unit_supplier_electricity_markup",
    "per_unit_supplier_electricity_production_markup",
    "per_unit_government_electricity_tax",
    "per_day_grid_operator_electricity_connection_fee",
    "per_day_supplier_electricity_standing_charge",
    "per_day_government_electricity_tax_rebate",
}

GAS_FIELDS = GAS_CORE_FIELDS

ELECTRICITY_FIELDS = ELECTRICITY_CORE_FIELDS | {
    "production_price_include_vat",
    "netting_enabled",
    "solar_bonus_enabled",
    "solar_bonus_percentage",
    "solar_bonus_annual_kwh_limit",
    "contract_start_date",
    "reset_on_contract_anniversary",
}

GENERAL_FIELDS = {
    "vat_percentage",
    "average_prices_to_hourly",
}


def _get_price_sensors(hass: HomeAssistant) -> list[str]:
    """Return all price sensor entity_ids available in hass."""
    return [
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


async def _get_energy_sensors(
    hass: HomeAssistant, source_type: str | None
) -> list[str]:
    """Return available energy or gas sensors with total state class."""
    device_class = "gas" if source_type == SOURCE_TYPE_GAS else "energy"
    return sorted(
        [
            state.entity_id
            for state in hass.states.async_all("sensor")
            if state.attributes.get("device_class") == device_class
            and state.attributes.get("state_class") in ("total", "total_increasing")
        ]
    )


def _apply_preset(
    price_settings: dict[str, Any], preset: dict[str, Any]
) -> dict[str, Any]:
    """Apply a supplier preset to current price settings.

    Detects the preset type and only updates relevant fields.
    Returns a new dict with the updated settings.
    """
    result = dict(price_settings)
    has_gas = any(preset.get(field, 0) != 0 for field in GAS_CORE_FIELDS)
    has_electricity = any(
        preset.get(field, 0) != 0 for field in ELECTRICITY_CORE_FIELDS
    )
    for key, value in preset.items():
        if has_gas and not has_electricity:
            if key in GAS_FIELDS or key in GENERAL_FIELDS:
                result[key] = value
        elif has_electricity and not has_gas:
            if key in ELECTRICITY_FIELDS or key in GENERAL_FIELDS:
                result[key] = value
        else:
            result[key] = value
    return result


def _build_price_settings_schema(
    price_settings: dict[str, Any],
    all_prices: list[str],
) -> vol.Schema:
    """Build the price settings form schema."""
    current_price_sensor = price_settings.get(CONF_PRICE_SENSOR, [])
    if isinstance(current_price_sensor, str):
        current_price_sensor = [current_price_sensor]
    current_price_sensor_gas = price_settings.get(CONF_PRICE_SENSOR_GAS, [])
    if isinstance(current_price_sensor_gas, str):
        current_price_sensor_gas = [current_price_sensor_gas]

    schema_fields: dict[Any, Any] = {
        vol.Required(CONF_PRICE_SENSOR, default=current_price_sensor): selector(
            {
                "select": {
                    "options": all_prices,
                    "multiple": True,
                    "mode": "dropdown",
                }
            }
        ),
        vol.Required(
            CONF_PRICE_SENSOR_GAS, default=current_price_sensor_gas
        ): selector(
            {
                "select": {
                    "options": all_prices,
                    "multiple": True,
                    "mode": "dropdown",
                }
            }
        ),
    }
    for key, default in DEFAULT_PRICE_SETTINGS.items():
        if key in (CONF_PRICE_SENSOR, CONF_PRICE_SENSOR_GAS):
            continue
        current = price_settings.get(key, default)
        if isinstance(default, bool):
            schema_fields[vol.Required(key, default=current)] = bool
        elif isinstance(default, str):
            if key == "contract_start_date":
                if current and current != "":
                    schema_fields[vol.Optional(key, default=current)] = selector(
                        {"date": {}}
                    )
                else:
                    schema_fields[vol.Optional(key)] = selector({"date": {}})
            else:
                schema_fields[vol.Optional(key, default=current)] = str
        else:
            schema_fields[vol.Required(key, default=current)] = vol.Coerce(float)
    return vol.Schema(schema_fields)


class DynamicEnergyCalculatorConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Dynamic Energy Contract Calculator."""

    VERSION = 2

    def __init__(self) -> None:
        super().__init__()
        self.context: ConfigFlowContext = {}
        self.price_settings: dict[str, Any] = copy.deepcopy(DEFAULT_PRICE_SETTINGS)

    async def async_step_user(
        self, user_input: dict[str, str] | None = None
    ) -> ConfigFlowResult:
        await self.async_set_unique_id(DOMAIN)
        if self._async_current_entries():
            return self.async_abort(reason="already_configured")
        if user_input is not None:
            choice = user_input.get("action", "")
            if choice == "load_preset":
                return await self.async_step_load_preset()
            elif choice == "price_settings":
                return await self.async_step_price_settings()
            elif choice == "finish":
                return self.async_create_entry(
                    title="Dynamic Energy Contract Calculator",
                    data={
                        CONF_PRICE_SENSOR: self.price_settings.get(CONF_PRICE_SENSOR, []),
                        CONF_PRICE_SENSOR_GAS: self.price_settings.get(
                            CONF_PRICE_SENSOR_GAS, []
                        ),
                        CONF_PRICE_SETTINGS: self.price_settings,
                    },
                )
        return self.async_show_form(
            step_id="user", data_schema=self._schema_user()
        )

    def _schema_user(self) -> vol.Schema:
        options = [
            {"value": "load_preset", "label": "Load Supplier Preset"},
            {"value": "price_settings", "label": "Price Settings"},
            {"value": "finish", "label": "Finish"},
        ]
        return vol.Schema(
            {
                vol.Required("action", default="finish"): selector(
                    {
                        "select": {
                            "options": options,
                            "mode": "dropdown",
                            "custom_value": False,
                        }
                    }
                )
            }
        )

    async def async_step_load_preset(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle loading a supplier preset."""
        if user_input is not None:
            selected_preset = user_input.get("supplier_preset")
            if (
                selected_preset
                and selected_preset != "none"
                and selected_preset in SUPPLIER_PRESETS
            ):
                self.price_settings = _apply_preset(
                    self.price_settings, SUPPLIER_PRESETS[selected_preset]
                )
            return await self.async_step_user()

        preset_options = [{"value": "none", "label": "None (keep current settings)"}]
        for preset_key in SUPPLIER_PRESETS:
            preset_options.append(
                {"value": preset_key, "label": preset_key.replace("_", " ").title()}
            )

        return self.async_show_form(
            step_id=STEP_LOAD_PRESET,
            data_schema=vol.Schema(
                {
                    vol.Required("supplier_preset", default="none"): selector(
                        {
                            "select": {
                                "options": preset_options,
                                "mode": "dropdown",
                            }
                        }
                    )
                }
            ),
        )

    async def async_step_price_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self.price_settings = dict(user_input)
            return await self.async_step_user()

        all_prices = _get_price_sensors(self.hass)
        return self.async_show_form(
            step_id=STEP_PRICE_SETTINGS,
            data_schema=_build_price_settings_schema(self.price_settings, all_prices),
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        return DynamicEnergyCalculatorOptionsFlowHandler(config_entry)

    @classmethod
    def async_get_supported_subentry_types(
        cls,
        config_entry: config_entries.ConfigEntry,
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Return supported sub-entry types."""
        return {SUBENTRY_TYPE_SOURCE: SourceSubEntryFlow}


class SourceSubEntryFlow(ConfigSubentryFlow):
    """Flow handler for adding/editing a source sub-entry."""

    def __init__(self) -> None:
        super().__init__()
        self._source_type: str | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Select source type."""
        if user_input is not None:
            self._source_type = user_input[CONF_SOURCE_TYPE]
            return await self.async_step_select_sources()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SOURCE_TYPE): selector(
                        {
                            "select": {
                                "options": [
                                    {"value": t, "label": t.title()}
                                    for t in SOURCE_TYPES
                                ],
                                "mode": "dropdown",
                                "custom_value": False,
                            }
                        }
                    )
                }
            ),
        )

    async def async_step_select_sources(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Select energy sensors for this source."""
        if user_input is not None:
            return self.async_create_entry(
                title=self._source_type or "Source",
                data={
                    CONF_SOURCE_TYPE: self._source_type,
                    CONF_SOURCES: user_input[CONF_SOURCES],
                },
            )

        all_sensors = await _get_energy_sensors(self.hass, self._source_type)

        return self.async_show_form(
            step_id=STEP_SELECT_SOURCES,
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SOURCES): selector(
                        {
                            "select": {
                                "options": all_sensors,
                                "multiple": True,
                                "mode": "dropdown",
                            }
                        }
                    )
                }
            ),
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Handle reconfiguration of an existing sub-entry."""
        entry = self._get_entry()
        subentry = self._get_reconfigure_subentry()
        existing_source_type = subentry.data.get(CONF_SOURCE_TYPE)
        existing_sources = subentry.data.get(CONF_SOURCES, [])

        if user_input is not None:
            source_type = user_input.get(CONF_SOURCE_TYPE, existing_source_type)
            sources = user_input.get(CONF_SOURCES, existing_sources)
            return self.async_update_and_abort(
                entry,
                subentry,
                title=source_type or "Source",
                data={
                    CONF_SOURCE_TYPE: source_type,
                    CONF_SOURCES: sources,
                },
            )

        all_sensors = await _get_energy_sensors(self.hass, existing_source_type)

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SOURCE_TYPE, default=existing_source_type
                    ): selector(
                        {
                            "select": {
                                "options": [
                                    {"value": t, "label": t.title()}
                                    for t in SOURCE_TYPES
                                ],
                                "mode": "dropdown",
                                "custom_value": False,
                            }
                        }
                    ),
                    vol.Required(CONF_SOURCES, default=existing_sources): selector(
                        {
                            "select": {
                                "options": all_sensors,
                                "multiple": True,
                                "mode": "dropdown",
                            }
                        }
                    ),
                }
            ),
        )


class DynamicEnergyCalculatorOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle updates to a config entry (options)."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.price_settings: dict[str, Any] = copy.deepcopy(
            config_entry.options.get(
                CONF_PRICE_SETTINGS,
                config_entry.data.get(CONF_PRICE_SETTINGS, DEFAULT_PRICE_SETTINGS),
            )
        )

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self.async_step_user()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            choice = user_input.get("action", "")
            if choice == "load_preset":
                return await self.async_step_load_preset()
            elif choice == "price_settings":
                return await self.async_step_price_settings()
            elif choice == "finish":
                return self.async_create_entry(
                    title="",
                    data={
                        CONF_PRICE_SENSOR: self.price_settings.get(CONF_PRICE_SENSOR, []),
                        CONF_PRICE_SENSOR_GAS: self.price_settings.get(
                            CONF_PRICE_SENSOR_GAS, []
                        ),
                        CONF_PRICE_SETTINGS: self.price_settings,
                    },
                )
        return self.async_show_form(
            step_id="user", data_schema=self._schema_user()
        )

    def _schema_user(self) -> vol.Schema:
        options = [
            {"value": "load_preset", "label": "Load Supplier Preset"},
            {"value": "price_settings", "label": "Price Settings"},
            {"value": "finish", "label": "Finish"},
        ]
        return vol.Schema(
            {
                vol.Required("action", default="finish"): selector(
                    {
                        "select": {
                            "options": options,
                            "mode": "dropdown",
                            "custom_value": False,
                        }
                    }
                )
            }
        )

    async def async_step_load_preset(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle loading a supplier preset."""
        if user_input is not None:
            selected_preset = user_input.get("supplier_preset")
            if (
                selected_preset
                and selected_preset != "none"
                and selected_preset in SUPPLIER_PRESETS
            ):
                self.price_settings = _apply_preset(
                    self.price_settings, SUPPLIER_PRESETS[selected_preset]
                )
            return await self.async_step_user()

        preset_options = [{"value": "none", "label": "None (keep current settings)"}]
        for preset_key in SUPPLIER_PRESETS:
            preset_options.append(
                {"value": preset_key, "label": preset_key.replace("_", " ").title()}
            )

        return self.async_show_form(
            step_id=STEP_LOAD_PRESET,
            data_schema=vol.Schema(
                {
                    vol.Required("supplier_preset", default="none"): selector(
                        {
                            "select": {
                                "options": preset_options,
                                "mode": "dropdown",
                            }
                        }
                    )
                }
            ),
        )

    async def async_step_price_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self.price_settings = dict(user_input)
            return await self.async_step_user()

        all_prices = _get_price_sensors(self.hass)
        return self.async_show_form(
            step_id=STEP_PRICE_SETTINGS,
            data_schema=_build_price_settings_schema(self.price_settings, all_prices),
        )
