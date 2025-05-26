# custom_components/dynamic_energy_calculator/number.py

from __future__ import annotations

from typing import Any
from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.components.number import NumberEntity, RestoreNumber
from homeassistant.helpers.entity import EntityCategory

from .entity import DynamicEnergyEntity
from .const import DOMAIN

# Four settings with logical defaults
NUMBER_SETTINGS = [
    {
        "key": "electricity_consumption_markup_per_kwh",
        "name": "Electricity Consumption Markup Per kWh",
        "min": 0.0,
        "max": 1.0,
        "step": 0.00001,
        "unit": "€",
        "mode": "box",
        "default": 0.0,
    },
    {
        "key": "electricity_production_markup_per_kwh",
        "name": "Electricity Production Markup Per kWh",
        "min": 0.0,
        "max": 1.0,
        "step": 0.00001,
        "unit": "€",
        "mode": "box",
        "default": 0.0,
    },
    {
        "key": "electricity_tax_per_kwh",
        "name": "Electricity Tax Per kWh",
        "min": 0.0,
        "max": 1.0,
        "step": 0.00001,
        "unit": "€",
        "mode": "box",
        "default": 0.0,
    },
    {
        "key": "tax_percentage",
        "name": "Tax Percentage",
        "min": 0.0,
        "max": 30.0,
        "step": 0.1,
        "unit": "%",
        "mode": "box",
        "default": 21.0,
    },
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up one RestoreNumber per setting under the single “general” device."""
    entities: list[NumberEntity] = []

    for setting in NUMBER_SETTINGS:
        key = setting["key"]
        name = setting["name"]
        min_v = setting["min"]
        max_v = setting["max"]
        step = setting["step"]
        unit = setting["unit"]
        mode = setting["mode"]
        default = setting["default"]

        entities.append(
            DynamicEnergyRestoreNumber(
                hass,
                entry,
                key,
                name,
                f"{entry.entry_id}_general",
                "Dynamic Energy Calculator General",
                "Settings",
                min_v,
                max_v,
                step,
                unit,
                mode,
                default,
            )
        )

    async_add_entities(entities, update_before_add=True)


class DynamicEnergyRestoreNumber(
    DynamicEnergyEntity, RestoreNumber, NumberEntity
):
    """Number inputs (markups/taxes) grouped under “General” device."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        setting_id: str,
        name: str,
        device_id: str,
        device_name: str,
        device_model: str,
        min_value: float,
        max_value: float,
        step: float,
        unit: str,
        mode: str,
        default_value: float,
    ) -> None:
        super().__init__(hass, entry, setting_id, name, device_id, device_name, device_model)

        # NumberEntity configuration
        self._attr_native_min_value = min_value
        self._attr_native_max_value = max_value
        self._attr_native_step = step
        self._attr_native_unit_of_measurement = unit
        self._attr_mode = mode

        # Show default immediately
        self._default = default_value
        self._attr_native_value = default_value

    async def async_added_to_hass(self) -> None:
        """Restore last saved value, or keep the default."""
        await super().async_added_to_hass()  # runs RestoreNumber logic
        last = await self.async_get_last_number_data()
        if last and last.native_value is not None:
            self._attr_native_value = last.native_value

    @callback
    async def async_set_native_value(self, value: float) -> None:
        """Save new user-set value."""
        self._attr_native_value = value
        self.async_write_ha_state()
