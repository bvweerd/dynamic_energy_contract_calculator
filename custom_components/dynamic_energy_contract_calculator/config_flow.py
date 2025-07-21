from __future__ import annotations

import voluptuous as vol
import copy

from typing import Any

from homeassistant import config_entries

try:
    from homeassistant.config_entries import ConfigFlowContext
except ImportError:  # pragma: no cover - older HA versions
    ConfigFlowContext = dict
from homeassistant.core import callback

try:
    from homeassistant.config_entries import ConfigFlowResult as FlowResult
except ImportError:  # pragma: no cover - older HA versions
    from homeassistant.config_entries import FlowResult
from homeassistant.helpers.selector import selector

from .const import (
    DOMAIN,
    CONF_CONFIGS,
    CONF_SOURCE_TYPE,
    CONF_SOURCES,
    CONF_PRICE_SENSOR,
    CONF_PRICE_SENSOR_GAS,
    CONF_PRICE_SETTINGS,
    SOURCE_TYPES,
    DEFAULT_PRICE_SETTINGS,
)

STEP_SELECT_SOURCES = "select_sources"
STEP_PRICE_SETTINGS = "price_settings"


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
    ) -> FlowResult:
        # Multiple entries are allowed; no unique ID enforced
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
            elif choice == "price_settings":
                return await self.async_step_price_settings()

            self.source_type = choice
            return await self.async_step_select_sources()

        return self.async_show_form(step_id="user", data_schema=self._schema_user())

    def _schema_user(self) -> vol.Schema:
        options = [{"value": t, "label": t.title()} for t in SOURCE_TYPES]
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

    async def _get_energy_sensors(self) -> list[str]:
        return sorted(
            [
                state.entity_id
                for state in self.hass.states.async_all("sensor")
                if state.attributes.get("device_class") == "energy"
                or state.attributes.get("device_class") == "gas"
            ]
        )

    async def async_step_select_sources(self, user_input=None) -> FlowResult:
        if user_input is not None:
            self.sources = user_input[CONF_SOURCES]
            self.configs.append(
                {
                    CONF_SOURCE_TYPE: self.source_type,
                    CONF_SOURCES: self.sources,
                }
            )
            return await self.async_step_user()

        all_sensors = await self._get_energy_sensors()

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

    async def async_step_price_settings(self, user_input=None) -> FlowResult:
        if user_input is not None:
            self.price_settings = dict(user_input)
            return await self.async_step_user()

        all_prices = [
            state.entity_id
            for state in self.hass.states.async_all("sensor")
            if state.attributes.get("device_class") == "monetary"
            or state.attributes.get("unit_of_measurement") == "€/m³"
            or state.attributes.get("unit_of_measurement") == "€/kWh"
        ]
        current_price_sensor = self.price_settings.get(CONF_PRICE_SENSOR, "")
        current_price_sensor_gas = self.price_settings.get(CONF_PRICE_SENSOR_GAS, "")

        include_gas = self.source_type == SOURCE_TYPE_GAS or any(
            c[CONF_SOURCE_TYPE] == SOURCE_TYPE_GAS for c in self.configs
        )

        schema_fields: dict[Any, Any] = {
            vol.Required(CONF_PRICE_SENSOR, default=current_price_sensor): selector(
                {
                    "select": {
                        "options": all_prices,
                        "multiple": False,
                        "mode": "dropdown",
                    }
                }
            )
        }
        if include_gas:
            schema_fields[
                vol.Required(CONF_PRICE_SENSOR_GAS, default=current_price_sensor_gas)
            ] = selector(
                {
                    "select": {
                        "options": all_prices,
                        "multiple": False,
                        "mode": "dropdown",
                    }
                }
            )
        gas_keys = {
            "per_unit_supplier_gas_markup",
            "per_unit_government_gas_tax",
            "per_day_grid_operator_gas_connection_fee",
            "per_day_supplier_gas_standing_charge",
        }
        for key, default in DEFAULT_PRICE_SETTINGS.items():
            if key in (CONF_PRICE_SENSOR, CONF_PRICE_SENSOR_GAS):
                continue
            if not include_gas and key in gas_keys:
                continue
            current = self.price_settings.get(key, default)
            if isinstance(default, bool):
                schema_fields[vol.Required(key, default=current)] = bool
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
            elif choice == "price_settings":
                return await self.async_step_price_settings()
            self.source_type = choice
            return await self.async_step_select_sources()

        return self.async_show_form(step_id="user", data_schema=self._schema_user())

    def _schema_user(self) -> vol.Schema:
        options = [{"value": t, "label": t.title()} for t in SOURCE_TYPES]
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
            self.configs.append(
                {
                    CONF_SOURCE_TYPE: self.source_type,
                    CONF_SOURCES: self.sources,
                }
            )
            return await self.async_step_user()

        all_sensors = [
            state.entity_id
            for state in self.hass.states.async_all("sensor")
            if state.attributes.get("device_class") == "energy"
            or state.attributes.get("device_class") == "gas"
        ]

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

    async def async_step_price_settings(self, user_input=None):
        if user_input is not None:
            self.price_settings = dict(user_input)
            return await self.async_step_user()

        all_prices = [
            state.entity_id
            for state in self.hass.states.async_all("sensor")
            if state.attributes.get("device_class") == "monetary"
            or state.attributes.get("unit_of_measurement") == "€/m³"
            or state.attributes.get("unit_of_measurement") == "€/kWh"
        ]
        current_price_sensor = self.price_settings.get(CONF_PRICE_SENSOR, "")
        current_price_sensor_gas = self.price_settings.get(CONF_PRICE_SENSOR_GAS, "")

        include_gas = any(c[CONF_SOURCE_TYPE] == SOURCE_TYPE_GAS for c in self.configs)

        schema_fields = {
            vol.Required(CONF_PRICE_SENSOR, default=current_price_sensor): selector(
                {
                    "select": {
                        "options": all_prices,
                        "multiple": False,
                        "mode": "dropdown",
                    }
                }
            )
        }
        if include_gas:
            schema_fields[
                vol.Required(CONF_PRICE_SENSOR_GAS, default=current_price_sensor_gas)
            ] = selector(
                {
                    "select": {
                        "options": all_prices,
                        "multiple": False,
                        "mode": "dropdown",
                    }
                }
            )
        gas_keys = {
            "per_unit_supplier_gas_markup",
            "per_unit_government_gas_tax",
            "per_day_grid_operator_gas_connection_fee",
            "per_day_supplier_gas_standing_charge",
        }
        for key, default in DEFAULT_PRICE_SETTINGS.items():
            if key in (CONF_PRICE_SENSOR, CONF_PRICE_SENSOR_GAS):
                continue
            if not include_gas and key in gas_keys:
                continue
            current = self.price_settings.get(key, default)
            if isinstance(default, bool):
                schema_fields[vol.Required(key, default=current)] = bool
            else:
                schema_fields[vol.Required(key, default=current)] = vol.Coerce(float)

        return self.async_show_form(
            step_id=STEP_PRICE_SETTINGS,
            data_schema=vol.Schema(schema_fields),
        )
