from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.sensor import SensorEntity, RestoreEntity
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN, CONF_CONFIGS, CONF_SOURCE_TYPE, CONF_SOURCES, CONF_PRICE_SENSOR

import logging

_LOGGER = logging.getLogger(__name__)

UTILITY_ENTITIES: list[BaseUtilitySensor] = []

class BaseUtilitySensor(SensorEntity, RestoreEntity):
    def __init__(self, name: str, unique_id: str, unit: str = UnitOfEnergy.KILO_WATT_HOUR, device: DeviceInfo | None = None):
        self._attr_name = name
        self._attr_unique_id = unique_id
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = "energy"
        self._attr_state_class = "total"
        self._attr_native_value = 0.0
        self._attr_device_info = device

    async def async_added_to_hass(self):
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state not in ("unknown", "unavailable"):
            try:
                self._attr_native_value = float(last_state.state)
            except ValueError:
                self._attr_native_value = 0.0

    def reset(self):
        self._attr_native_value = 0.0
        self.async_write_ha_state()

    def set_value(self, value: float):
        self._attr_native_value = round(value, 3)
        self.async_write_ha_state()


class DynamicEnergySensor(BaseUtilitySensor):
    def __init__(
        self,
        hass: HomeAssistant,
        name: str,
        unique_id: str,
        energy_sensor: str,
        price_sensor: str | None = None,
        mode: str = "kwh_total",
        device: DeviceInfo | None = None,
    ):
        super().__init__(name, unique_id, device=device)
        self.hass = hass
        self.energy_sensor = energy_sensor
        self.price_sensor = price_sensor
        self.mode = mode
        self._last_energy = None
        self._last_updated = datetime.now()

    async def async_update(self):
        energy_state = self.hass.states.get(self.energy_sensor)
        if energy_state is None or energy_state.state in ("unknown", "unavailable"):
            return

        try:
            current_energy = float(energy_state.state)
        except ValueError:
            return

        delta = 0.0
        if self._last_energy is not None:
            delta = current_energy - self._last_energy
            if delta < 0:
                delta = 0.0

        self._last_energy = current_energy

        if self.mode in ("kwh_total", "kwh_hourly"):
            if self.mode == "kwh_hourly" and datetime.now() - self._last_updated >= timedelta(hours=1):
                self._attr_native_value = 0.0
                self._last_updated = datetime.now()
            self._attr_native_value += delta

        elif self.price_sensor:
            price_state = self.hass.states.get(self.price_sensor)
            if price_state is None or price_state.state in ("unknown", "unavailable"):
                return
            try:
                price = float(price_state.state)
            except ValueError:
                return

            value = delta * price

            if self.mode == "cost_total" or self.mode == "cost_hourly":
                if self.mode == "cost_hourly" and datetime.now() - self._last_updated >= timedelta(hours=1):
                    self._attr_native_value = 0.0
                    self._last_updated = datetime.now()
                self._attr_native_value += value

            elif self.mode == "profit_total" or self.mode == "profit_hourly":
                if price >= 0:
                    return
                if self.mode == "profit_hourly" and datetime.now() - self._last_updated >= timedelta(hours=1):
                    self._attr_native_value = 0.0
                    self._last_updated = datetime.now()
                self._attr_native_value += abs(value)

            elif self.mode == "kwh_during_profit_total" and price < 0:
                self._attr_native_value += delta

            elif self.mode == "kwh_during_cost_total" and price >= 0:
                self._attr_native_value += delta

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback
) -> None:
    configs = entry.data.get(CONF_CONFIGS, [])
    entities: list[BaseUtilitySensor] = []

    for block in configs:
        source_type = block[CONF_SOURCE_TYPE]
        sources = block[CONF_SOURCES]
        price_sensor = block.get(CONF_PRICE_SENSOR)

        for sensor in sources:
            base_id = sensor.replace(".", "_")
            device_info = DeviceInfo(
                identifiers={(DOMAIN, base_id)},
                name=f"Dynamic Energy Meter: {sensor}",
                entry_type="service",
                manufacturer="DynamicEnergyCalc",
                model=source_type,
            )

            for mode in [
                "kwh_total",
                "kwh_hourly",
                "cost_total",
                "cost_hourly",
                "profit_total",
                "profit_hourly",
                "kwh_during_cost_total",
                "kwh_during_profit_total",
            ]:
                name = f"{base_id}_{mode}"
                uid = f"{DOMAIN}_{base_id}_{mode}"
                sensor_entity = DynamicEnergySensor(
                    hass,
                    name,
                    uid,
                    energy_sensor=sensor,
                    price_sensor=price_sensor,
                    mode=mode,
                    device=device_info,
                )
                entities.append(sensor_entity)

    UTILITY_ENTITIES.extend(entities)
    async_add_entities(entities, True)

    async def handle_reset_all(call: ServiceCall):
        for ent in UTILITY_ENTITIES:
            ent.reset()

    async def handle_reset_selected(call: ServiceCall):
        ids = call.data.get("entity_ids", [])
        for ent in UTILITY_ENTITIES:
            if ent.entity_id in ids:
                ent.reset()

    async def handle_set_value(call: ServiceCall):
        entity_id = call.data.get("entity_id")
        value = call.data.get("value", 0.0)
        for ent in UTILITY_ENTITIES:
            if ent.entity_id == entity_id:
                ent.set_value(value)

    hass.services.async_register(DOMAIN, "reset_all_meters", handle_reset_all)
    hass.services.async_register(DOMAIN, "reset_selected_meters", handle_reset_selected)
    hass.services.async_register(DOMAIN, "set_meter_value", handle_set_value)

    hass.data[DOMAIN]["entities"] = entities
