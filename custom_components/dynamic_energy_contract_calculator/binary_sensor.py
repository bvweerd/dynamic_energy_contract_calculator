"""Binary sensor platform for Dynamic Energy Contract Calculator."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorDeviceClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event

from .const import DOMAIN, SOURCE_TYPE_PRODUCTION
from .solar_bonus import SolarBonusTracker

import logging

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up binary sensors for this entry."""
    entities = []

    configs = entry.data.get("configurations", [])
    price_settings = entry.options.get("price_settings", entry.data.get("price_settings", {}))

    device_info = DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=f"Dynamic Energy Calculator ({entry.entry_id[:8]})",
        manufacturer="Dynamic Energy Contract Calculator",
        model="Energy Cost Calculator",
    )

    # Check if solar bonus is enabled
    solar_bonus_enabled = bool(price_settings.get("solar_bonus_enabled"))
    if solar_bonus_enabled:
        # Get the solar bonus tracker
        solar_bonus_map = hass.data[DOMAIN].get("solar_bonus", {})
        solar_bonus_tracker = solar_bonus_map.get(entry.entry_id)

        if solar_bonus_tracker:
            # Get production price sensor if exists
            production_price_sensor = None
            for config in configs:
                if config.get("source_type") == SOURCE_TYPE_PRODUCTION:
                    production_price_sensor = config.get("price_sensor")
                    break

            entities.append(
                SolarBonusActiveBinarySensor(
                    hass=hass,
                    unique_id=f"{DOMAIN}_solar_bonus_active",
                    device=device_info,
                    solar_bonus_tracker=solar_bonus_tracker,
                    price_sensor=production_price_sensor,
                    price_settings=price_settings,
                )
            )

    # Check if production is configured
    has_production = any(
        config.get("source_type") == SOURCE_TYPE_PRODUCTION
        for config in configs
    )

    if has_production:
        # Get production price sensor
        production_price_sensor = None
        for config in configs:
            if config.get("source_type") == SOURCE_TYPE_PRODUCTION:
                production_price_sensor = config.get("price_sensor")
                break

        entities.append(
            ProductionPricePositiveBinarySensor(
                hass=hass,
                unique_id=f"{DOMAIN}_production_price_positive",
                device=device_info,
                price_sensor=production_price_sensor,
                price_settings=price_settings,
            )
        )

    if entities:
        async_add_entities(entities)


class SolarBonusActiveBinarySensor(BinarySensorEntity):
    """Binary sensor showing if solar bonus is currently active."""

    def __init__(
        self,
        hass: HomeAssistant,
        unique_id: str,
        device: DeviceInfo,
        solar_bonus_tracker: SolarBonusTracker,
        price_sensor: str | None,
        price_settings: dict,
    ):
        """Initialize the binary sensor."""
        self.hass = hass
        self._attr_unique_id = unique_id
        self._attr_name = "Solar Bonus Active"
        self._attr_device_info = device
        self._attr_device_class = None
        self._solar_bonus_tracker = solar_bonus_tracker
        self._price_sensor = price_sensor
        self._price_settings = price_settings
        self._attr_is_on = False

    async def async_added_to_hass(self) -> None:
        """Register state change listener."""
        if self._price_sensor:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass,
                    [self._price_sensor],
                    self._handle_price_change,
                )
            )
        # Initial update
        await self._async_update_state()

    @callback
    def _handle_price_change(self, event) -> None:
        """Handle price sensor state change."""
        self.hass.async_create_task(self._async_update_state())

    async def _async_update_state(self) -> None:
        """Update the binary sensor state."""
        # Check if solar bonus conditions are met
        is_active = False

        # Check if daylight
        if self._solar_bonus_tracker._is_daylight():
            # Check if under annual limit
            annual_limit = self._price_settings.get("solar_bonus_annual_kwh_limit", 7500.0)
            if self._solar_bonus_tracker.year_production_kwh < annual_limit:
                # Check if price is positive
                if self._price_sensor:
                    price_state = self.hass.states.get(self._price_sensor)
                    if price_state and price_state.state not in ("unknown", "unavailable"):
                        try:
                            base_price = float(price_state.state)
                            production_markup = self._price_settings.get(
                                "per_unit_supplier_electricity_production_markup", 0.0
                            )
                            total_price = base_price + production_markup
                            if total_price > 0:
                                is_active = True
                        except (ValueError, TypeError):
                            pass

        self._attr_is_on = is_active
        if self.entity_id:  # Only write state if entity is registered
            self.async_write_ha_state()


class ProductionPricePositiveBinarySensor(BinarySensorEntity):
    """Binary sensor showing if production price is positive."""

    def __init__(
        self,
        hass: HomeAssistant,
        unique_id: str,
        device: DeviceInfo,
        price_sensor: str | None,
        price_settings: dict,
    ):
        """Initialize the binary sensor."""
        self.hass = hass
        self._attr_unique_id = unique_id
        self._attr_name = "Production Price Positive"
        self._attr_device_info = device
        self._attr_device_class = None
        self._price_sensor = price_sensor
        self._price_settings = price_settings
        self._attr_is_on = False

    async def async_added_to_hass(self) -> None:
        """Register state change listener."""
        if self._price_sensor:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass,
                    [self._price_sensor],
                    self._handle_price_change,
                )
            )
        # Initial update
        await self._async_update_state()

    @callback
    def _handle_price_change(self, event) -> None:
        """Handle price sensor state change."""
        self.hass.async_create_task(self._async_update_state())

    async def _async_update_state(self) -> None:
        """Update the binary sensor state."""
        is_positive = False

        if self._price_sensor:
            price_state = self.hass.states.get(self._price_sensor)
            if price_state and price_state.state not in ("unknown", "unavailable"):
                try:
                    base_price = float(price_state.state)
                    production_markup = self._price_settings.get(
                        "per_unit_supplier_electricity_production_markup", 0.0
                    )
                    total_price = base_price + production_markup
                    is_positive = total_price > 0
                except (ValueError, TypeError):
                    pass

        self._attr_is_on = is_positive
        if self.entity_id:  # Only write state if entity is registered
            self.async_write_ha_state()
