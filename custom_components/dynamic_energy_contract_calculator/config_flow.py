from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any

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
    DEFAULT_NETWORK_TARIFF_SETTINGS,
    DEFAULT_PRICE_SETTINGS,
    DOMAIN,
    NETWORK_TARIFF_PRESETS,
    SOURCE_TYPE_GAS,
    SOURCE_TYPES,
    SUBENTRY_TYPE_SOURCE,
    SUPPLIER_PRESETS,
)

STEP_SELECT_SOURCES = "select_sources"
STEP_PRICE_SETTINGS = "price_settings"
STEP_LOAD_PRESET = "load_preset"
STEP_NETWORK_TARIFF = "network_tariff"
STEP_LOAD_NETWORK_TARIFF_PRESET = "load_network_tariff_preset"

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

NETWORK_TARIFF_FIELDS = {
    "network_tariff_enabled",
    "network_tariff_winter_peak_per_kwh",
    "network_tariff_winter_offpeak_per_kwh",
    "network_tariff_summer_peak_per_kwh",
    "network_tariff_summer_offpeak_per_kwh",
    "network_tariff_peak_start_hour",
    "network_tariff_peak_end_hour",
    "network_tariff_winter_start_month",
    "network_tariff_winter_end_month",
}

ELECTRICITY_FIELDS = ELECTRICITY_CORE_FIELDS | {
    "production_price_include_vat",
    "netting_enabled",
    "solar_bonus_enabled",
    "solar_bonus_percentage",
    "solar_bonus_annual_kwh_limit",
    "contract_start_date",
    "reset_on_contract_anniversary",
} | NETWORK_TARIFF_FIELDS

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
        vol.Required(CONF_PRICE_SENSOR_GAS, default=current_price_sensor_gas): selector(
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


class _PriceSettingsMixin:
    """Shared price-settings steps used by both config and options flows."""

    price_settings: dict[str, Any]

    if TYPE_CHECKING:
        hass: HomeAssistant

        async def async_step_user(
            self, user_input: dict[str, Any] | None = None
        ) -> ConfigFlowResult: ...

    def _schema_user(self) -> vol.Schema:
        options = [
            {"value": "load_preset", "label": "Load Supplier Preset"},
            {"value": "price_settings", "label": "Price Settings"},
            {"value": "load_network_tariff_preset", "label": "Load Network Tariff Preset (2029)"},
            {"value": "network_tariff", "label": "Network Tariff Settings (2029)"},
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

        return self.async_show_form(  # type: ignore[attr-defined, no-any-return]
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
            # Merge into existing settings so network tariff settings are preserved
            new_settings = dict(self.price_settings)
            new_settings.update(user_input)
            self.price_settings = new_settings
            return await self.async_step_user()

        all_prices = _get_price_sensors(self.hass)
        return self.async_show_form(  # type: ignore[attr-defined, no-any-return]
            step_id=STEP_PRICE_SETTINGS,
            data_schema=_build_price_settings_schema(self.price_settings, all_prices),
        )


    async def async_step_load_network_tariff_preset(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle loading a network tariff preset for a Dutch grid operator."""
        if user_input is not None:
            selected = user_input.get("network_tariff_preset")
            if selected and selected != "none" and selected in NETWORK_TARIFF_PRESETS:
                preset = NETWORK_TARIFF_PRESETS[selected]
                for key, value in preset.items():
                    self.price_settings[key] = value
            return await self.async_step_user()

        preset_options = [{"value": "none", "label": "None (keep current settings)"}]
        for preset_key in NETWORK_TARIFF_PRESETS:
            preset_options.append(
                {"value": preset_key, "label": preset_key.replace("_", " ").title()}
            )

        return self.async_show_form(  # type: ignore[attr-defined, no-any-return]
            step_id=STEP_LOAD_NETWORK_TARIFF_PRESET,
            data_schema=vol.Schema(
                {
                    vol.Required("network_tariff_preset", default="none"): selector(
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

    async def async_step_network_tariff(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure time-dependent network tariff bands and rates."""
        if user_input is not None:
            for key in DEFAULT_NETWORK_TARIFF_SETTINGS:
                if key in user_input:
                    self.price_settings[key] = user_input[key]
            return await self.async_step_user()

        settings = self.price_settings
        schema_fields: dict[Any, Any] = {
            vol.Required(
                "network_tariff_enabled",
                default=bool(settings.get("network_tariff_enabled", False)),
            ): bool,
            vol.Required(
                "network_tariff_winter_peak_per_kwh",
                default=float(settings.get("network_tariff_winter_peak_per_kwh", 0.0)),
            ): vol.Coerce(float),
            vol.Required(
                "network_tariff_winter_offpeak_per_kwh",
                default=float(
                    settings.get("network_tariff_winter_offpeak_per_kwh", 0.0)
                ),
            ): vol.Coerce(float),
            vol.Required(
                "network_tariff_summer_peak_per_kwh",
                default=float(settings.get("network_tariff_summer_peak_per_kwh", 0.0)),
            ): vol.Coerce(float),
            vol.Required(
                "network_tariff_summer_offpeak_per_kwh",
                default=float(
                    settings.get("network_tariff_summer_offpeak_per_kwh", 0.0)
                ),
            ): vol.Coerce(float),
            vol.Required(
                "network_tariff_peak_start_hour",
                default=int(settings.get("network_tariff_peak_start_hour", 7)),
            ): selector(
                {
                    "number": {
                        "min": 0,
                        "max": 23,
                        "mode": "box",
                        "step": 1,
                    }
                }
            ),
            vol.Required(
                "network_tariff_peak_end_hour",
                default=int(settings.get("network_tariff_peak_end_hour", 23)),
            ): selector(
                {
                    "number": {
                        "min": 1,
                        "max": 24,
                        "mode": "box",
                        "step": 1,
                    }
                }
            ),
            vol.Required(
                "network_tariff_winter_start_month",
                default=int(settings.get("network_tariff_winter_start_month", 11)),
            ): selector(
                {
                    "number": {
                        "min": 1,
                        "max": 12,
                        "mode": "box",
                        "step": 1,
                    }
                }
            ),
            vol.Required(
                "network_tariff_winter_end_month",
                default=int(settings.get("network_tariff_winter_end_month", 3)),
            ): selector(
                {
                    "number": {
                        "min": 1,
                        "max": 12,
                        "mode": "box",
                        "step": 1,
                    }
                }
            ),
        }
        return self.async_show_form(  # type: ignore[attr-defined, no-any-return]
            step_id=STEP_NETWORK_TARIFF,
            data_schema=vol.Schema(schema_fields),
        )


class DynamicEnergyCalculatorConfigFlow(
    _PriceSettingsMixin, config_entries.ConfigFlow, domain=DOMAIN
):
    """Handle a config flow for Dynamic Energy Contract Calculator."""

    VERSION = 2

    def __init__(self) -> None:
        super().__init__()
        self.context: ConfigFlowContext = {}
        self.price_settings: dict[str, Any] = {
            **copy.deepcopy(DEFAULT_PRICE_SETTINGS),
            **DEFAULT_NETWORK_TARIFF_SETTINGS,
        }

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
            elif choice == "load_network_tariff_preset":
                return await self.async_step_load_network_tariff_preset()
            elif choice == "network_tariff":
                return await self.async_step_network_tariff()
            elif choice == "finish":
                return self.async_create_entry(
                    title="Dynamic Energy Contract Calculator",
                    data={
                        CONF_PRICE_SENSOR: self.price_settings.get(
                            CONF_PRICE_SENSOR, []
                        ),
                        CONF_PRICE_SENSOR_GAS: self.price_settings.get(
                            CONF_PRICE_SENSOR_GAS, []
                        ),
                        CONF_PRICE_SETTINGS: self.price_settings,
                    },
                )
        return self.async_show_form(step_id="user", data_schema=self._schema_user())

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


class DynamicEnergyCalculatorOptionsFlowHandler(
    _PriceSettingsMixin, config_entries.OptionsFlow
):
    """Handle updates to a config entry (options)."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        stored = copy.deepcopy(
            config_entry.options.get(
                CONF_PRICE_SETTINGS,
                config_entry.data.get(CONF_PRICE_SETTINGS, DEFAULT_PRICE_SETTINGS),
            )
        )
        # Seed network tariff defaults for entries created before this feature existed
        self.price_settings: dict[str, Any] = {
            **DEFAULT_NETWORK_TARIFF_SETTINGS,
            **stored,
        }

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
            elif choice == "load_network_tariff_preset":
                return await self.async_step_load_network_tariff_preset()
            elif choice == "network_tariff":
                return await self.async_step_network_tariff()
            elif choice == "finish":
                return self.async_create_entry(
                    title="",
                    data={
                        CONF_PRICE_SENSOR: self.price_settings.get(
                            CONF_PRICE_SENSOR, []
                        ),
                        CONF_PRICE_SENSOR_GAS: self.price_settings.get(
                            CONF_PRICE_SENSOR_GAS, []
                        ),
                        CONF_PRICE_SETTINGS: self.price_settings,
                    },
                )
        return self.async_show_form(step_id="user", data_schema=self._schema_user())
