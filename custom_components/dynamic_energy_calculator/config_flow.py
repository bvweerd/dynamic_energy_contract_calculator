"""Config flow for Dynamic Energy Calculator integration."""

from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import selector

from .const import DOMAIN, CONF_SOURCES, CONF_SOURCE_TYPE, CONF_PRICE_SENSOR

class SourceType:
    """Types of energy sources."""
    CONSUMPTION = "consumption"
    PRODUCTION = "production"

@config_entries.HANDLERS.register(DOMAIN)
class DynamicEnergyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for the Dynamic Energy integration."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Initial step: choose whether this entry is for consumption or production."""
        if user_input is None:
            data_schema = vol.Schema({
                vol.Required(CONF_SOURCE_TYPE): selector({
                    "select": {
                        "options": [
                            {"value": SourceType.CONSUMPTION, "label": "Consumption"},
                            {"value": SourceType.PRODUCTION, "label": "Production"},
                        ],
                    }
                })
            })
            return self.async_show_form(step_id="user", data_schema=data_schema)

        self.source_type = user_input[CONF_SOURCE_TYPE]
        return await self.async_step_select_sensors()

    async def async_step_select_sensors(self, user_input=None):
        """Step where user selects one or more source sensors."""
        if user_input is None:
            data_schema = vol.Schema({
                vol.Required(CONF_SOURCES): selector({
                    "entity": {
                        "domain": "sensor",
                        "multiple": True,
                        "filter": [
                            {"unit_of_measurement": ["kWh"]},
                            {"state_class": ["total_increasing"]},
                        ],
                    }
                })
            })
            return self.async_show_form(
                step_id="select_sensors", data_schema=data_schema
            )

        self.selected_sources = user_input[CONF_SOURCES]
        return await self.async_step_select_price()

    async def async_step_select_price(self, user_input=None):
        """Step where user selects the electricity price sensor."""
        if user_input is None:
            data_schema = vol.Schema({
                vol.Required(CONF_PRICE_SENSOR): selector({
                    "entity": {
                        "domain": "sensor",
                        "multiple": False,
                        "filter": [
                            {"unit_of_measurement": ["€"]},
                        ],
                    }
                })
            })
            return self.async_show_form(
                step_id="select_price", data_schema=data_schema
            )

        entry_data = {
            CONF_SOURCE_TYPE: self.source_type,
            CONF_SOURCES: self.selected_sources,
            CONF_PRICE_SENSOR: user_input[CONF_PRICE_SENSOR],
        }
        title = f"{DOMAIN} - {self.source_type.capitalize()}"
        return self.async_create_entry(title=title, data=entry_data)
