from __future__ import annotations

import copy
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowContext, ConfigFlowResult
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import selector

from .const import (
    CONF_CONFIGS,
    CONF_PRICE_SENSOR,
    CONF_PRICE_SENSOR_GAS,
    CONF_PRICE_SETTINGS,
    CONF_SOURCE_TYPE,
    CONF_SOURCES,
    DEFAULT_PRICE_SETTINGS,
    DOMAIN,
    SOURCE_TYPE_GAS,
    SOURCE_TYPES,
    SUPPLIER_PRESETS,
)

STEP_SELECT_SOURCES = "select_sources"
STEP_PRICE_SETTINGS = "price_settings"
STEP_LOAD_PRESET = "load_preset"

# Field categories for smart preset loading
GAS_FIELDS = {
    "per_unit_supplier_gas_markup",
    "per_unit_government_gas_tax",
    "per_day_grid_operator_gas_connection_fee",
    "per_day_supplier_gas_standing_charge",
}

ELECTRICITY_FIELDS = {
    "per_unit_supplier_electricity_markup",
    "per_unit_supplier_electricity_production_markup",
    "per_unit_government_electricity_tax",
    "per_day_grid_operator_electricity_connection_fee",
    "per_day_supplier_electricity_standing_charge",
    "per_day_government_electricity_tax_rebate",
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


class DynamicEnergyCalculatorConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):  # type: ignore[call-arg]
    """Handle a config flow for Dynamic Energy Contract Calculator."""

    VERSION = 1

    def __init__(self) -> None:
        super().__init__()

        self.context: ConfigFlowContext = {}
        self.configs: list[dict] = []
        self.source_type: str | None = None
        self.sources: list[str] | None = None
        self.price_settings: dict = copy.deepcopy(DEFAULT_PRICE_SETTINGS)

    async def async_step_user(
        self, user_input: dict[str, str] | None = None
    ) -> ConfigFlowResult:
        await self.async_set_unique_id(DOMAIN)
        if self._async_current_entries():
            return self.async_abort(reason="already_configured")
        if user_input is not None:
            choice = user_input[CONF_SOURCE_TYPE]
            if choice == "finish":
                if not self.configs:
                    return self.async_show_form(
                        step_id="user",
                        data_schema=self._schema_user(),
                        errors={"base": "no_blocks"},
                    )
                return self.async_create_entry(
                    title="Dynamic Energy Contract Calculator",
                    data={
                        CONF_CONFIGS: self.configs,
                        CONF_PRICE_SENSOR: self.price_settings.get(CONF_PRICE_SENSOR),
                        CONF_PRICE_SENSOR_GAS: self.price_settings.get(
                            CONF_PRICE_SENSOR_GAS
                        ),
                        CONF_PRICE_SETTINGS: self.price_settings,
                    },
                )
            elif choice == "load_preset":
                return await self.async_step_load_preset()
            elif choice == "price_settings":
                return await self.async_step_price_settings()

            self.source_type = choice
            return await self.async_step_select_sources()

        return self.async_show_form(step_id="user", data_schema=self._schema_user())

    def _schema_user(self) -> vol.Schema:
        options = [{"value": t, "label": t.title()} for t in SOURCE_TYPES]
        options.append({"value": "load_preset", "label": "Load Supplier Preset"})
        options.append({"value": "price_settings", "label": "Price Settings"})
        options.append({"value": "finish", "label": "Finish"})

        return vol.Schema(
            {
                vol.Required(CONF_SOURCE_TYPE): selector(
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

    async def async_step_select_sources(self, user_input=None) -> ConfigFlowResult:
        if user_input is not None:
            self.sources = user_input[CONF_SOURCES]

            existing = next(
                (
                    config
                    for config in self.configs
                    if config[CONF_SOURCE_TYPE] == self.source_type
                ),
                None,
            )
            if existing is not None:
                existing[CONF_SOURCES] = self.sources
            else:
                self.configs.append(
                    {
                        CONF_SOURCE_TYPE: self.source_type,
                        CONF_SOURCES: self.sources,
                    }
                )

            return await self.async_step_user()
        all_sensors = await _get_energy_sensors(self.hass, self.source_type)

        last = next(
            (
                block
                for block in reversed(self.configs)
                if block[CONF_SOURCE_TYPE] == self.source_type
            ),
            None,
        )
        default_sources = last[CONF_SOURCES] if last else []

        return self.async_show_form(
            step_id=STEP_SELECT_SOURCES,
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SOURCES, default=default_sources): selector(
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

    async def async_step_load_preset(self, user_input=None) -> ConfigFlowResult:
        """Handle loading a supplier preset."""
        if user_input is not None:
            selected_preset = user_input.get("supplier_preset")
            if selected_preset and selected_preset != "none" and selected_preset in SUPPLIER_PRESETS:
                preset = SUPPLIER_PRESETS[selected_preset]

                # Detect preset type by checking which fields have non-zero values
                has_gas = any(
                    preset.get(field, 0) != 0
                    for field in GAS_FIELDS
                    if isinstance(preset.get(field), (int, float))
                )
                has_electricity = any(
                    preset.get(field, 0) != 0
                    for field in ELECTRICITY_FIELDS
                    if isinstance(preset.get(field), (int, float))
                )

                # Smart update: only update relevant fields
                for key, value in preset.items():
                    if has_gas and not has_electricity:
                        # Gas-only preset: update gas + general fields
                        if key in GAS_FIELDS or key in GENERAL_FIELDS:
                            self.price_settings[key] = value
                    elif has_electricity and not has_gas:
                        # Electricity-only preset: update electricity + general fields
                        if key in ELECTRICITY_FIELDS or key in GENERAL_FIELDS:
                            self.price_settings[key] = value
                    else:
                        # Combined preset: update all
                        self.price_settings[key] = value
            return await self.async_step_user()

        # Create preset options
        preset_options = [{"value": "none", "label": "None (keep current settings)"}]
        for preset_key in SUPPLIER_PRESETS:
            preset_options.append({
                "value": preset_key,
                "label": preset_key.replace("_", " ").title()
            })

        return self.async_show_form(
            step_id=STEP_LOAD_PRESET,
            data_schema=vol.Schema({
                vol.Required("supplier_preset", default="none"): selector({
                    "select": {
                        "options": preset_options,
                        "mode": "dropdown",
                    }
                })
            }),
        )

    async def async_step_price_settings(self, user_input=None) -> ConfigFlowResult:
        if user_input is not None:
            self.price_settings = dict(user_input)
            return await self.async_step_user()

        all_prices = [
            state.entity_id
            for state in self.hass.states.async_all()
            if (state.domain in ["sensor", "input_number"])
            and (
                state.attributes.get("device_class") == "monetary"
                or state.attributes.get("unit_of_measurement") == "€/m³"
                or state.attributes.get("unit_of_measurement") == "EUR/m³"
                or state.attributes.get("unit_of_measurement") == "€/kWh"
                or state.attributes.get("unit_of_measurement") == "EUR/kWh"
            )
        ]
        current_price_sensor = self.price_settings.get(CONF_PRICE_SENSOR, [])
        if isinstance(current_price_sensor, str):
            current_price_sensor = [current_price_sensor]
        current_price_sensor_gas = self.price_settings.get(CONF_PRICE_SENSOR_GAS, [])
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
            current = self.price_settings.get(key, default)
            if isinstance(default, bool):
                schema_fields[vol.Required(key, default=current)] = bool
            elif isinstance(default, str):
                # Use date selector for contract_start_date
                if key == "contract_start_date":
                    # Only set default if there's a valid date
                    if current and current != "":
                        schema_fields[vol.Optional(key, default=current)] = selector({
                            "date": {}
                        })
                    else:
                        schema_fields[vol.Optional(key)] = selector({
                            "date": {}
                        })
                else:
                    schema_fields[vol.Optional(key, default=current)] = str
            else:
                schema_fields[vol.Required(key, default=current)] = vol.Coerce(float)

        return self.async_show_form(
            step_id=STEP_PRICE_SETTINGS,
            data_schema=vol.Schema(schema_fields),
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        return DynamicEnergyCalculatorOptionsFlowHandler(config_entry)


class DynamicEnergyCalculatorOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle updates to a config entry (options)."""

    def __init__(self, config_entry):
        self.configs = list(
            config_entry.options.get(
                CONF_CONFIGS, config_entry.data.get(CONF_CONFIGS, [])
            )
        )
        self.price_settings = copy.deepcopy(
            config_entry.options.get(
                CONF_PRICE_SETTINGS,
                config_entry.data.get(CONF_PRICE_SETTINGS, DEFAULT_PRICE_SETTINGS),
            )
        )
        self.source_type: str | None = None
        self.sources: list[str] | None = None

    async def async_step_init(self, user_input=None):
        return await self.async_step_user()

    async def async_step_user(self, user_input=None):
        if user_input and CONF_SOURCE_TYPE in user_input:
            choice = user_input[CONF_SOURCE_TYPE]
            if choice == "finish":
                if not self.configs:
                    return self.async_show_form(
                        step_id="user",
                        data_schema=self._schema_user(),
                        errors={"base": "no_blocks"},
                    )
                return self.async_create_entry(
                    title="",
                    data={
                        CONF_CONFIGS: self.configs,
                        CONF_PRICE_SENSOR: self.price_settings.get(CONF_PRICE_SENSOR),
                        CONF_PRICE_SENSOR_GAS: self.price_settings.get(
                            CONF_PRICE_SENSOR_GAS
                        ),
                        CONF_PRICE_SETTINGS: self.price_settings,
                    },
                )
            elif choice == "load_preset":
                return await self.async_step_load_preset()
            elif choice == "price_settings":
                return await self.async_step_price_settings()
            self.source_type = choice
            return await self.async_step_select_sources()

        return self.async_show_form(step_id="user", data_schema=self._schema_user())

    def _schema_user(self) -> vol.Schema:
        options = [{"value": t, "label": t.title()} for t in SOURCE_TYPES]
        options.append({"value": "load_preset", "label": "Load Supplier Preset"})
        options.append({"value": "price_settings", "label": "Price Settings"})
        options.append({"value": "finish", "label": "Finish"})

        return vol.Schema(
            {
                vol.Required(CONF_SOURCE_TYPE): selector(
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

    async def async_step_select_sources(self, user_input=None):
        if user_input and CONF_SOURCES in user_input:
            self.sources = user_input[CONF_SOURCES]

            existing = next(
                (
                    config
                    for config in self.configs
                    if config[CONF_SOURCE_TYPE] == self.source_type
                ),
                None,
            )
            if existing is not None:
                existing[CONF_SOURCES] = self.sources
            else:
                self.configs.append(
                    {
                        CONF_SOURCE_TYPE: self.source_type,
                        CONF_SOURCES: self.sources,
                    }
                )

            return await self.async_step_user()

        all_sensors = await _get_energy_sensors(self.hass, self.source_type)

        last = next(
            (
                block
                for block in reversed(self.configs)
                if block[CONF_SOURCE_TYPE] == self.source_type
            ),
            None,
        )
        default_sources = last[CONF_SOURCES] if last else []

        return self.async_show_form(
            step_id=STEP_SELECT_SOURCES,
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SOURCES, default=default_sources): selector(
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

    async def async_step_load_preset(self, user_input=None):
        """Handle loading a supplier preset."""
        if user_input is not None:
            selected_preset = user_input.get("supplier_preset")
            if selected_preset and selected_preset != "none" and selected_preset in SUPPLIER_PRESETS:
                preset = SUPPLIER_PRESETS[selected_preset]

                # Detect preset type by checking which fields have non-zero values
                has_gas = any(
                    preset.get(field, 0) != 0
                    for field in GAS_FIELDS
                    if isinstance(preset.get(field), (int, float))
                )
                has_electricity = any(
                    preset.get(field, 0) != 0
                    for field in ELECTRICITY_FIELDS
                    if isinstance(preset.get(field), (int, float))
                )

                # Smart update: only update relevant fields
                for key, value in preset.items():
                    if has_gas and not has_electricity:
                        # Gas-only preset: update gas + general fields
                        if key in GAS_FIELDS or key in GENERAL_FIELDS:
                            self.price_settings[key] = value
                    elif has_electricity and not has_gas:
                        # Electricity-only preset: update electricity + general fields
                        if key in ELECTRICITY_FIELDS or key in GENERAL_FIELDS:
                            self.price_settings[key] = value
                    else:
                        # Combined preset: update all
                        self.price_settings[key] = value
            return await self.async_step_user()

        # Create preset options
        preset_options = [{"value": "none", "label": "None (keep current settings)"}]
        for preset_key in SUPPLIER_PRESETS:
            preset_options.append({
                "value": preset_key,
                "label": preset_key.replace("_", " ").title()
            })

        return self.async_show_form(
            step_id=STEP_LOAD_PRESET,
            data_schema=vol.Schema({
                vol.Required("supplier_preset", default="none"): selector({
                    "select": {
                        "options": preset_options,
                        "mode": "dropdown",
                    }
                })
            }),
        )

    async def async_step_price_settings(self, user_input=None):
        if user_input is not None:
            self.price_settings = dict(user_input)
            return await self.async_step_user()

        all_prices = [
            state.entity_id
            for state in self.hass.states.async_all()
            if (state.domain in ["sensor", "input_number"])
            and (
                state.attributes.get("device_class") == "monetary"
                or state.attributes.get("unit_of_measurement") == "€/m³"
                or state.attributes.get("unit_of_measurement") == "EUR/m³"
                or state.attributes.get("unit_of_measurement") == "€/kWh"
                or state.attributes.get("unit_of_measurement") == "EUR/kWh"
            )
        ]
        current_price_sensor = self.price_settings.get(CONF_PRICE_SENSOR, [])
        if isinstance(current_price_sensor, str):
            current_price_sensor = [current_price_sensor]
        current_price_sensor_gas = self.price_settings.get(CONF_PRICE_SENSOR_GAS, [])
        if isinstance(current_price_sensor_gas, str):
            current_price_sensor_gas = [current_price_sensor_gas]

        schema_fields = {
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
            current = self.price_settings.get(key, default)
            if isinstance(default, bool):
                schema_fields[vol.Required(key, default=current)] = bool
            elif isinstance(default, str):
                # Use date selector for contract_start_date
                if key == "contract_start_date":
                    # Only set default if there's a valid date
                    if current and current != "":
                        schema_fields[vol.Optional(key, default=current)] = selector({
                            "date": {}
                        })
                    else:
                        schema_fields[vol.Optional(key)] = selector({
                            "date": {}
                        })
                else:
                    schema_fields[vol.Optional(key, default=current)] = str
            else:
                schema_fields[vol.Required(key, default=current)] = vol.Coerce(float)

        return self.async_show_form(
            step_id=STEP_PRICE_SETTINGS,
            data_schema=vol.Schema(schema_fields),
        )
