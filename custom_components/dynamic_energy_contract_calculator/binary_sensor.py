"""Binary sensor platform for Dynamic Energy Contract Calculator."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorDeviceClass,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (
    DOMAIN,
    DOMAIN_ABBREVIATION,
    CONF_PRICE_SENSOR,
    CONF_PRICE_SETTINGS,
    SOURCE_TYPE_PRODUCTION,
)

import logging

_LOGGER = logging.getLogger(__name__)


class ReturnCostsBinarySensor(BinarySensorEntity, RestoreEntity):
    """Binary sensor that indicates if returning energy costs money.

    This sensor is True when the current production price is negative,
    meaning you would have to pay to return energy to the grid.

    Note: This sensor does not account for netting (saldering), as that
    can only be determined after the annual settlement with your energy
    supplier. It only looks at the instantaneous return price.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        unique_id: str,
        price_sensor: str | list[str],
        price_settings: dict[str, float],
        device: DeviceInfo,
    ):
        """Initialize the binary sensor."""
        self._attr_unique_id = unique_id
        self._attr_translation_key = "return_costs_money"
        self._attr_has_entity_name = True
        self._attr_device_class = BinarySensorDeviceClass.PROBLEM
        self._attr_icon = "mdi:cash-remove"
        self._attr_device_info = device

        self.hass = hass
        if isinstance(price_sensor, list):
            self.price_sensors = price_sensor
        else:
            self.price_sensors = [price_sensor]
        self.price_settings = price_settings
        self._attr_is_on = False
        self._attr_available = True
        self._current_price: float | None = None

    @property
    def extra_state_attributes(self) -> dict[str, float | None]:
        """Return additional state attributes."""
        return {
            "current_production_price": self._current_price,
        }

    def _calculate_production_price(self, base_price: float) -> float:
        """Calculate the production price using the same formula as CurrentElectricityPriceSensor."""
        markup_production = self.price_settings.get(
            "per_unit_supplier_electricity_production_markup", 0.0
        )
        vat_factor = self.price_settings.get("vat_percentage", 21.0) / 100.0 + 1.0

        if self.price_settings.get("production_price_include_vat", True):
            price = (base_price - markup_production) * vat_factor
        else:
            price = base_price - markup_production

        return round(price, 8)

    async def async_update(self):
        """Update the binary sensor state."""
        total_price = 0.0
        valid = False

        for sensor in self.price_sensors:
            state = self.hass.states.get(sensor)
            if state is None or state.state in ("unknown", "unavailable"):
                _LOGGER.warning("Price sensor %s is unavailable", sensor)
                continue
            try:
                total_price += float(state.state)
                valid = True
            except ValueError:
                _LOGGER.warning("Price sensor %s has invalid state", sensor)
                continue

        if not valid:
            self._attr_available = False
            return

        self._attr_available = True
        self._current_price = self._calculate_production_price(total_price)

        # Return costs money when the production price is negative
        self._attr_is_on = self._current_price < 0

    async def async_added_to_hass(self):
        """Handle entity being added to hass."""
        await super().async_added_to_hass()

        # Restore previous state
        last_state = await self.async_get_last_state()
        if last_state is not None:
            self._attr_is_on = last_state.state == "on"
            if "current_production_price" in last_state.attributes:
                self._current_price = last_state.attributes.get(
                    "current_production_price"
                )

        # Track price sensor changes
        for sensor in self.price_sensors:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass,
                    sensor,
                    self._handle_price_change,
                )
            )

    async def _handle_price_change(self, event):
        """Handle price sensor state changes."""
        new_state = event.data.get("new_state")
        if new_state is None or new_state.state in ("unknown", "unavailable"):
            self._attr_available = False
            _LOGGER.warning(
                "Price sensor %s is unavailable", event.data.get("entity_id")
            )
            return
        await self.async_update()
        self.async_write_ha_state()


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the binary sensor platform."""
    price_settings = entry.options.get(
        CONF_PRICE_SETTINGS, entry.data.get(CONF_PRICE_SETTINGS, {})
    )
    price_sensor = entry.options.get(
        CONF_PRICE_SENSOR, entry.data.get(CONF_PRICE_SENSOR)
    )

    if isinstance(price_sensor, str):
        price_sensor = [price_sensor]

    # Only create the binary sensor if we have an electricity price sensor
    if not price_sensor:
        return

    entities: list[BinarySensorEntity] = []

    # Use the same device as summary sensors
    base_id = "daily_electricity_cost"
    device_info = DeviceInfo(
        identifiers={(DOMAIN, base_id)},
        name=f"{DOMAIN_ABBREVIATION}: Summary Sensors",
        entry_type=DeviceEntryType.SERVICE,
        manufacturer="DynamicEnergyCalc",
        model="summary",
    )

    entities.append(
        ReturnCostsBinarySensor(
            hass=hass,
            unique_id=f"{DOMAIN}_return_costs_money",
            price_sensor=price_sensor,
            price_settings=price_settings,
            device=device_info,
        )
    )

    async_add_entities(entities, True)
