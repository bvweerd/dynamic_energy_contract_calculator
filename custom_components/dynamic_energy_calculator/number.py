"""
Platform for Dynamic Energy Calculator number inputs using RestoreNumber, defined in code (no YAML).
"""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.components.number import RestoreNumber, NumberEntityDescription

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Define static number settings
NUMBER_SETTINGS: list[NumberEntityDescription] = [
    NumberEntityDescription(
        key="electricity_consumption_markup_per_kwh",
        name="Electricity Consumption Markup Per kWh",
        native_min_value=0.0,
        native_max_value=1.0,
        native_step=0.00001,
        native_unit_of_measurement="€",
        mode="box",
    ),
    NumberEntityDescription(
        key="electricity_production_markup_per_kwh",
        name="Electricity Production Markup Per kWh",
        native_min_value=0.0,
        native_max_value=1.0,
        native_step=0.00001,
        native_unit_of_measurement="€",
        mode="box",
    ),
    NumberEntityDescription(
        key="electricity_tax_per_kwh",
        name="Electricity Tax Per kWh",
        native_min_value=0.0,
        native_max_value=1.0,
        native_step=0.00001,
        native_unit_of_measurement="€",
        mode="box",
    ),
    NumberEntityDescription(
        key="tax_percentage",
        name="Tax Percentage",
        native_min_value=0.0,
        native_max_value=30.0,
        native_step=0.1,
        native_unit_of_measurement="%",
        mode="box",
    ),
]

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up static RestoreNumber entities for dynamic energy settings."""
    entities: list[DynamicEnergyRestoreNumber] = []
    entry_id = entry.entry_id

    for desc in NUMBER_SETTINGS:
        unique_id = f"{entry_id}_{desc.key}"
        entities.append(
            DynamicEnergyRestoreNumber(
                description=desc,
                unique_id=unique_id,
            )
        )

    async_add_entities(entities)

class DynamicEnergyRestoreNumber(RestoreNumber):
    """RestoreNumber entity for static dynamic energy settings."""

    def __init__(
        self,
        description: NumberEntityDescription,
        unique_id: str,
    ) -> None:
        """Initialize the RestoreNumber entity with static description."""
        self.entity_description = description
        self._attr_name = description.name
        self._attr_unique_id = unique_id
        self._attr_native_min_value = description.native_min_value
        self._attr_native_max_value = description.native_max_value
        self._attr_native_step = description.native_step
        self._attr_native_unit_of_measurement = description.native_unit_of_measurement
        if hasattr(description, 'mode') and description.mode is not None:
            self._attr_mode = description.mode
        self._value: float | None = None

    async def async_added_to_hass(self) -> None:
        """Restore the last saved state on startup."""
        await super().async_added_to_hass()
        last = await self.async_get_last_number_data()
        if last and last.native_value is not None:
            self._value = last.native_value

    @property
    def value(self) -> float | None:
        """Return the current value of the number."""
        return self._value

    async def async_set_value(self, value: float) -> None:
        """Set a new value and persist it."""
        self._value = value
        self.async_write_ha_state()
