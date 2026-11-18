"""Binary sensor platform for Dynamic Energy Contract Calculator."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_change,
)

from .const import (
    CONF_PRICE_SENSOR,
    CONF_PRICE_SETTINGS,
    DOMAIN,
    DOMAIN_ABBREVIATION,
    SOLAR_BONUS_BASE_MARKET_ONLY,
    SOLAR_BONUS_BASE_MARKET_PLUS_MARKUP,
    SOLAR_BONUS_WINDOW_FIXED_HOURS,
    SOLAR_BONUS_WINDOW_SUNRISE_SUNSET,
    SOURCE_TYPE_PRODUCTION,
    SUBENTRY_TYPE_SOURCE,
)
from .entity import read_price_sum
from .solar_bonus import SolarBonusTracker, async_get_solar_bonus_tracker

_LOGGER = logging.getLogger(__name__)


def _as_sensor_list(price_sensor: str | list[str] | None) -> list[str]:
    if price_sensor is None:
        return []
    if isinstance(price_sensor, str):
        return [price_sensor]
    return list(price_sensor)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up binary sensors for this entry."""
    entities: list[BinarySensorEntity] = []

    price_settings = entry.options.get(
        CONF_PRICE_SETTINGS, entry.data.get(CONF_PRICE_SETTINGS, {})
    )

    # Get the price sensor from entry data (used for production price calculations)
    # The configured price is the sum of all price sensors, as in the
    # cost sensors, so every binary sensor uses all of them.
    price_sensor_list = _as_sensor_list(
        entry.options.get(CONF_PRICE_SENSOR, entry.data.get(CONF_PRICE_SENSOR, []))
    )

    # Check if production is configured via sub-entries
    has_production = any(
        subentry.data.get("source_type") == SOURCE_TYPE_PRODUCTION
        for subentry in entry.subentries.values()
        if subentry.subentry_type == SUBENTRY_TYPE_SOURCE
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
        # Shared with the sensor platform, which is set up concurrently
        solar_bonus_tracker = await async_get_solar_bonus_tracker(
            hass, entry.entry_id, price_settings
        )

        entities.append(
            SolarBonusActiveBinarySensor(
                hass=hass,
                unique_id=f"{entry.entry_id}_solar_bonus_active",
                entry_id=entry.entry_id,
                solar_bonus_tracker=solar_bonus_tracker,
                price_sensor=price_sensor_list,
                price_settings=price_settings,
                device_info=device_info,
            )
        )

    if has_production and price_sensor_list:
        entities.append(
            ProductionPricePositiveBinarySensor(
                hass=hass,
                unique_id=f"{entry.entry_id}_production_price_positive",
                entry_id=entry.entry_id,
                price_sensor=price_sensor_list,
                price_settings=price_settings,
                device_info=device_info,
            )
        )

    if price_sensor_list:
        entities.append(
            DeliveryPricePositiveBinarySensor(
                hass=hass,
                unique_id=f"{entry.entry_id}_delivery_price_positive",
                entry_id=entry.entry_id,
                price_sensors=price_sensor_list,
                price_settings=price_settings,
                device_info=device_info,
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
        entry_id: str,
        solar_bonus_tracker: SolarBonusTracker,
        price_sensor: str | list[str] | None,
        price_settings: dict[str, Any],
        device_info: DeviceInfo,
    ):
        """Initialize the binary sensor."""
        self.hass = hass
        self._attr_unique_id = unique_id
        self._attr_has_entity_name = True
        self._attr_translation_key = "solar_bonus_active"
        self._attr_device_info = device_info
        self._solar_bonus_tracker = solar_bonus_tracker
        self._price_sensors = _as_sensor_list(price_sensor)
        self._price_settings = price_settings
        self._attr_is_on = False

    async def async_added_to_hass(self) -> None:
        """Re-evaluate on price changes, window edges and limit changes."""
        # sun.sun drives the sunrise-to-sunset window
        self.async_on_remove(
            async_track_state_change_event(
                self.hass,
                [*self._price_sensors, "sun.sun"],
                self._handle_price_change,
            )
        )
        # Fixed windows start and end on whole hours
        if (
            self._price_settings.get("solar_bonus_window_mode")
            == SOLAR_BONUS_WINDOW_FIXED_HOURS
        ):
            self.async_on_remove(
                async_track_time_change(
                    self.hass, self._handle_time_change, minute=0, second=0
                )
            )
        # Reaching the annual limit, a new period, or a reset
        self.async_on_remove(
            self._solar_bonus_tracker.async_add_listener(self._handle_tracker_update)
        )
        # Initial update
        await self._async_update_state()

    async def _handle_price_change(self, event: Event[EventStateChangedData]) -> None:
        """Handle price sensor state change."""
        await self._async_update_state()

    async def _handle_time_change(self, now: datetime) -> None:
        await self._async_update_state(only_if_changed=True)

    @callback
    def _handle_tracker_update(self) -> None:
        # The tracker reports every bonus booking; only write on a change.
        if self._is_active() != self._attr_is_on:
            self._attr_is_on = not self._attr_is_on
            if self.entity_id:
                self.async_write_ha_state()

    def _is_active(self) -> bool:
        """Return whether a kWh fed in right now would earn the bonus."""
        if not self._solar_bonus_tracker.is_in_bonus_window(
            self._price_settings.get(
                "solar_bonus_window_mode", SOLAR_BONUS_WINDOW_SUNRISE_SUNSET
            ),
            self._price_settings.get("solar_bonus_start_hour", 6.0),
            self._price_settings.get("solar_bonus_end_hour", 22.0),
        ):
            return False
        if self._solar_bonus_tracker.limit_reached(
            self._price_settings.get("solar_bonus_annual_kwh_limit", 7500.0)
        ):
            return False
        base_price, _problems = read_price_sum(self.hass, self._price_sensors)
        if base_price is None:
            return False
        # Mirror the tracker: a market-only bonus ignores the production
        # markup for this condition too.
        if (
            self._price_settings.get(
                "solar_bonus_base", SOLAR_BONUS_BASE_MARKET_PLUS_MARKUP
            )
            == SOLAR_BONUS_BASE_MARKET_ONLY
        ):
            return base_price > 0
        production_markup = float(
            self._price_settings.get(
                "per_unit_supplier_electricity_production_markup", 0.0
            )
        )
        return base_price + production_markup > 0

    async def _async_update_state(self, only_if_changed: bool = False) -> None:
        """Update the binary sensor state."""
        is_active = self._is_active()
        if only_if_changed and is_active == self._attr_is_on:
            return
        self._attr_is_on = is_active
        if self.entity_id:  # Only write state if entity is registered
            self.async_write_ha_state()


class ProductionPricePositiveBinarySensor(BinarySensorEntity):
    """Binary sensor showing if production price is positive."""

    def __init__(
        self,
        hass: HomeAssistant,
        unique_id: str,
        entry_id: str,
        price_sensor: str | list[str] | None,
        price_settings: dict[str, Any],
        device_info: DeviceInfo,
    ):
        """Initialize the binary sensor."""
        self.hass = hass
        self._attr_unique_id = unique_id
        self._attr_has_entity_name = True
        self._attr_translation_key = "production_price_positive"
        self._attr_device_info = device_info
        self._price_sensors = _as_sensor_list(price_sensor)
        self._price_settings = price_settings
        self._attr_is_on = False

    async def async_added_to_hass(self) -> None:
        """Register state change listener."""
        if self._price_sensors:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass,
                    self._price_sensors,
                    self._handle_price_change,
                )
            )
        # Initial update
        await self._async_update_state()

    async def _handle_price_change(self, event: Event[EventStateChangedData]) -> None:
        """Handle price sensor state change."""
        await self._async_update_state()

    async def _async_update_state(self) -> None:
        """Update the binary sensor state."""
        is_positive = False
        base_price, _problems = read_price_sum(self.hass, self._price_sensors)
        if base_price is not None:
            production_markup = self._price_settings.get(
                "per_unit_supplier_electricity_production_markup", 0.0
            )
            is_positive = base_price + production_markup > 0

        self._attr_is_on = is_positive
        if self.entity_id:  # Only write state if entity is registered
            self.async_write_ha_state()


class DeliveryPricePositiveBinarySensor(BinarySensorEntity):
    """Binary sensor showing if delivery (consumption) price is positive."""

    def __init__(
        self,
        hass: HomeAssistant,
        unique_id: str,
        entry_id: str,
        price_sensors: list[str],
        price_settings: dict[str, Any],
        device_info: DeviceInfo,
    ):
        """Initialize the binary sensor."""
        self.hass = hass
        self._attr_unique_id = unique_id
        self._attr_has_entity_name = True
        self._attr_translation_key = "delivery_price_positive"
        self._attr_device_info = device_info
        self._price_sensors = price_sensors
        self._price_settings = price_settings
        self._attr_is_on = False

    async def async_added_to_hass(self) -> None:
        """Register state change listener."""
        if self._price_sensors:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass,
                    self._price_sensors,
                    self._handle_price_change,
                )
            )
        await self._async_update_state()

    async def _handle_price_change(self, event: Event[EventStateChangedData]) -> None:
        """Handle price sensor state change."""
        await self._async_update_state()

    async def _async_update_state(self) -> None:
        """Update the binary sensor state."""
        is_positive = False

        total_price, _problems = read_price_sum(self.hass, self._price_sensors)
        if total_price is not None:
            markup = self._price_settings.get(
                "per_unit_supplier_electricity_markup", 0.0
            )
            tax = self._price_settings.get("per_unit_government_electricity_tax", 0.0)
            is_positive = (total_price + markup + tax) > 0

        self._attr_is_on = is_positive
        if self.entity_id:  # Only write state if entity is registered
            self.async_write_ha_state()
