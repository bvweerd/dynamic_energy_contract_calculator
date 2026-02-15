"""Binary sensor platform for Dynamic Energy Contract Calculator."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo

from .const import DOMAIN, DOMAIN_ABBREVIATION, SOURCE_TYPE_PRODUCTION
from .solar_bonus import SolarBonusTracker

import logging

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up binary sensors for this entry."""
    entities: list[BinarySensorEntity] = []

    configs = entry.data.get("configurations", [])
    price_settings = entry.options.get(
        "price_settings", entry.data.get("price_settings", {})
    )

    # Get the price sensor from entry data (used for production price calculations)
    price_sensor_list = entry.options.get(
        "price_sensor", entry.data.get("price_sensor", [])
    )
    production_price_sensor = price_sensor_list[0] if price_sensor_list else None

    # Check if production is configured
    has_production = any(
        config.get("source_type") == SOURCE_TYPE_PRODUCTION for config in configs
    )

    # Create device info for Summary Sensors device (same as in sensor.py)
    base_id = "daily_electricity_cost"
    device_info = DeviceInfo(
        identifiers={(DOMAIN, base_id)},
        name=f"{DOMAIN_ABBREVIATION}: Summary Sensors",
        entry_type=DeviceEntryType.SERVICE,
        manufacturer="DynamicEnergyCalc",
        model="summary",
    )

    # Check if solar bonus is enabled
    solar_bonus_enabled = bool(price_settings.get("solar_bonus_enabled"))
    if solar_bonus_enabled and has_production:
        # Get or create the solar bonus tracker
        solar_bonus_map = hass.data[DOMAIN].setdefault("solar_bonus", {})
        solar_bonus_tracker = solar_bonus_map.get(entry.entry_id)

        # Create tracker if it doesn't exist yet
        if solar_bonus_tracker is None:
            contract_start_date = price_settings.get("contract_start_date", "")
            solar_bonus_tracker = await SolarBonusTracker.async_create(
                hass, entry.entry_id, contract_start_date
            )
            solar_bonus_map[entry.entry_id] = solar_bonus_tracker

        entities.append(
            SolarBonusActiveBinarySensor(
                hass=hass,
                unique_id=f"{entry.entry_id}_solar_bonus_active",
                entry_id=entry.entry_id,
                solar_bonus_tracker=solar_bonus_tracker,
                price_sensor=production_price_sensor,
                price_settings=price_settings,
                device_info=device_info,
            )
        )

    if has_production and production_price_sensor:
        entities.append(
            ProductionPricePositiveBinarySensor(
                hass=hass,
                unique_id=f"{entry.entry_id}_production_price_positive",
                entry_id=entry.entry_id,
                price_sensor=production_price_sensor,
                price_settings=price_settings,
                device_info=device_info,
            )
        )

    if entities:
        async_add_entities(entities)


class SolarBonusActiveBinarySensor(BinarySensorEntity):  # type: ignore[misc]
    """Binary sensor showing if solar bonus is currently active."""

    def __init__(
        self,
        hass: HomeAssistant,
        unique_id: str,
        entry_id: str,
        solar_bonus_tracker: SolarBonusTracker,
        price_sensor: str | None,
        price_settings: dict[str, Any],
        device_info: DeviceInfo,
    ):
        """Initialize the binary sensor."""
        self.hass = hass
        self._attr_unique_id = unique_id
        self._attr_name = "Solar Bonus Active"
        self._attr_has_entity_name = False
        self._attr_translation_key = "solar_bonus_active"
        self._attr_device_info = device_info
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

    @callback  # type: ignore[misc]
    def _handle_price_change(self, event: Event) -> None:
        """Handle price sensor state change."""
        self.hass.async_create_task(self._async_update_state())

    async def _async_update_state(self) -> None:
        """Update the binary sensor state."""
        # Check if solar bonus conditions are met
        is_active = False

        # Check if daylight
        if self._solar_bonus_tracker._is_daylight():
            # Check if under annual limit
            annual_limit = self._price_settings.get(
                "solar_bonus_annual_kwh_limit", 7500.0
            )
            if self._solar_bonus_tracker.year_production_kwh < annual_limit:
                # Check if price is positive
                if self._price_sensor:
                    price_state = self.hass.states.get(self._price_sensor)
                    if price_state and price_state.state not in (
                        "unknown",
                        "unavailable",
                    ):
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


class ProductionPricePositiveBinarySensor(BinarySensorEntity):  # type: ignore[misc]
    """Binary sensor showing if production price is positive."""

    def __init__(
        self,
        hass: HomeAssistant,
        unique_id: str,
        entry_id: str,
        price_sensor: str | None,
        price_settings: dict[str, Any],
        device_info: DeviceInfo,
    ):
        """Initialize the binary sensor."""
        self.hass = hass
        self._attr_unique_id = unique_id
        self._attr_name = "Production Price Positive"
        self._attr_has_entity_name = False
        self._attr_translation_key = "production_price_positive"
        self._attr_device_info = device_info
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

    @callback  # type: ignore[misc]
    def _handle_price_change(self, event: Event) -> None:
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
