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

from .const import DOMAIN, CONF_CONFIGS, CONF_SOURCE_TYPE, CONF_SOURCES, CONF_PRICE_SENSOR, SOURCE_TYPE_CONSUMPTION, SOURCE_TYPE_PRODUCTION

import logging

_LOGGER = logging.getLogger(__name__)

SENSOR_MODES = [
    {
        "key": "kwh_total",
        "name": "Total kWh",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "icon": "mdi:counter",
        "visible": True,
    },
    {
        "key": "kwh_hourly",
        "name": "Hourly kWh",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "icon": "mdi:clock-outline",
        "visible": False,
    },
    {
        "key": "cost_total",
        "name": "Total Cost",
        "unit": "€",
        "icon": "mdi:cash",
        "visible": True,
    },
    {
        "key": "cost_hourly",
        "name": "Hourly Cost",
        "unit": "€",
        "icon": "mdi:cash-clock",
        "visible": False,
    },
    {
        "key": "profit_total",
        "name": "Total Profit",
        "unit": "€",
        "icon": "mdi:cash-plus",
        "visible": True,
    },
    {
        "key": "profit_hourly",
        "name": "Hourly Profit",
        "unit": "€",
        "icon": "mdi:clock-plus-outline",
        "visible": False,
    },
    {
        "key": "kwh_during_cost_total",
        "name": "kWh During Cost",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "icon": "mdi:transmission-tower-export",
        "visible": True,
    },
    {
        "key": "kwh_during_profit_total",
        "name": "kWh During Profit",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "icon": "mdi:transmission-tower-import",
        "visible": True,
    },
]

UTILITY_ENTITIES: list[BaseUtilitySensor] = []

class BaseUtilitySensor(SensorEntity, RestoreEntity):
    def __init__(self, name: str, unique_id: str, unit: str, icon: str, visible: bool, device: DeviceInfo | None = None):
        self._attr_name = name
        self._attr_unique_id = unique_id
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = "energy"
        self._attr_state_class = "total"
        self._attr_native_value = 0.0
        self._attr_icon = icon
        self._attr_entity_registry_enabled_default = visible
        self._attr_device_info = device

    @property
    def native_value(self) -> float:
        return round(self._attr_native_value, 5)

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
        self._attr_native_value = round(value, 5)
        self.async_write_ha_state()


class DynamicEnergySensor(BaseUtilitySensor):
    def __init__(
        self,
        hass: HomeAssistant,
        name: str,
        unique_id: str,
        energy_sensor: str,
        source_type: str,
        price_sensor: str | None = None,
        mode: str = "kwh_total",
        unit: str = UnitOfEnergy.KILO_WATT_HOUR,
        icon: str = "mdi:flash",
        visible: bool = True,
        device: DeviceInfo | None = None,
    ):
        super().__init__(name, unique_id, unit=unit, icon=icon, visible=visible, device=device)
        self.hass = hass
        self.energy_sensor = energy_sensor
        self.price_sensor = price_sensor
        self.mode = mode
        self.source_type = source_type
        self._last_energy = None
        self._last_updated = datetime.now()

    def _get_number(self, key: str) -> float:
        """Helper for reading number-entity."""
        entity_id = f"number.{key}"
        state = self.hass.states.get(entity_id)
        return float(state.state) if state and state.state not in (None, "unknown") else 0.0

    async def async_update(self):
        markup_cons  = self._get_number("electricity_consumption_markup_per_kwh")
        markup_inj   = self._get_number("electricity_production_markup_per_kwh")
        tax_kwh      = self._get_number("electricity_tax_per_kwh")
        vat_factor   = self._get_number("tax_percentage") / 100.0 + 1.0

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

            # consumption meter
            if self.source_type == SOURCE_TYPE_CONSUMPTION:
                adjusted_price_cons = (price + markup_cons + tax_kwh) * vat_factor
                price = delta * adjusted_price_cons
            # production meter
            elif self.source_type == SOURCE_TYPE_PRODUCTION:
                adjusted_price_inj = ((price + markup_inj) * vat_factor) * -1
                price = delta * adjusted_price_inj
            else:
                _LOGGER.error("Unknown source_type: %s", self.source_type)
                return

            value = delta * price

            if (self.mode == "cost_total" or self.mode == "cost_hourly") and price >= 0:
                if self.mode == "cost_hourly" and datetime.now() - self._last_updated >= timedelta(hours=1):
                    self._attr_native_value = 0.0
                    self._last_updated = datetime.now()
                self._attr_native_value += value

            elif (self.mode == "profit_total" or self.mode == "profit_hourly") and price < 0:
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

            for mode_def in SENSOR_MODES:
                mode = mode_def["key"]
                name = mode_def["name"]
                uid = f"{DOMAIN}_{base_id}_{mode}"
                entities.append(
                    DynamicEnergySensor(
                        hass=hass,
                        name=name,
                        unique_id=uid,
                        energy_sensor=sensor,
                        price_sensor=price_sensor,
                        mode=mode,
                        source_type=source_type,
                        unit=mode_def["unit"],
                        icon=mode_def["icon"],
                        visible=mode_def["visible"],
                        device=device_info,
                    )
                )

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
