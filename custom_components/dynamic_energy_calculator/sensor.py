from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.sensor import SensorEntity, RestoreEntity
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN, DOMAIN_ABBREVIATION, CONF_CONFIGS, CONF_SOURCE_TYPE, CONF_SOURCES, CONF_PRICE_SENSOR, SOURCE_TYPE_CONSUMPTION, SOURCE_TYPE_PRODUCTION

import logging

_LOGGER = logging.getLogger(__name__)

SENSOR_MODES = [
    {
        "key": "kwh_total",
        "name": "Total kWh",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "icon": "mdi:counter",
        "visible": True,
    },
    {
        "key": "kwh_hourly",
        "name": "Hourly kWh",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "icon": "mdi:clock-outline",
        "visible": False,
    },
    {
        "key": "cost_total",
        "name": "Total Cost",
        "unit": "€",
        "device_class": None,
        "icon": "mdi:cash",
        "visible": True,
    },
    {
        "key": "cost_hourly",
        "name": "Hourly Cost",
        "unit": "€",
        "device_class": None,
        "icon": "mdi:cash-clock",
        "visible": False,
    },
    {
        "key": "profit_total",
        "name": "Total Profit",
        "unit": "€",
        "device_class": None,
        "icon": "mdi:cash-plus",
        "visible": True,
    },
    {
        "key": "profit_hourly",
        "name": "Hourly Profit",
        "unit": "€",
        "device_class": None,
        "icon": "mdi:clock-plus-outline",
        "visible": False,
    },
    {
        "key": "kwh_during_cost_total",
        "name": "kWh During Cost",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "icon": "mdi:transmission-tower-export",
        "visible": True,
    },
    {
        "key": "kwh_during_profit_total",
        "name": "kWh During Profit",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "icon": "mdi:transmission-tower-import",
        "visible": True,
    },
]

UTILITY_ENTITIES: list[BaseUtilitySensor] = []

class BaseUtilitySensor(SensorEntity, RestoreEntity):
    def __init__(self, name: str, unique_id: str, unit: str, device_class: str, icon: str, visible: bool, device: DeviceInfo | None = None):
        self._attr_name = name
        self._attr_unique_id = unique_id
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
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
        device_class: str = None,
        icon: str = "mdi:flash",
        visible: bool = True,
        device: DeviceInfo | None = None,
    ):
        super().__init__(name, unique_id, unit=unit, device_class=device_class, icon=icon, visible=visible, device=device)
        self.hass = hass
        self.energy_sensor = energy_sensor
        self.input_sensors = [energy_sensor]
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
        markup_consumption  = self._get_number("electricity_consumption_markup_per_kwh")
        markup_production   = self._get_number("electricity_production_markup_per_kwh")
        tax_kwh      = self._get_number("electricity_surcharge_per_kwh")
        vat_factor   = self._get_number("vat_percentage") / 100.0 + 1.0

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
                adjusted_price_cons = (price + markup_consumption + tax_kwh) * vat_factor
                price = delta * adjusted_price_cons
            # production meter
            elif self.source_type == SOURCE_TYPE_PRODUCTION:
                adjusted_price_inj = (price + markup_production) * vat_factor
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

    async def async_added_to_hass(self):
        await super().async_added_to_hass()

        for entity_id in self.input_sensors:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass,
                    entity_id,
                    self._handle_input_event,
                )
            )

    async def _handle_input_event(self, event):
        entity_id = event.data.get("entity_id")
        new_state = event.data.get("new_state")

        if new_state is None or new_state.state in ("unknown", "unavailable"):
            return

        await self.async_update()
        self.async_write_ha_state()

from homeassistant.helpers.event import async_track_time_change
from datetime import time

class DailyElectricityCostSensor(BaseUtilitySensor):
    def __init__(
        self,
        hass: HomeAssistant,
        name: str,
        unique_id: str,
        vat_entity: str,
        surcharge_entity: str,
        standing_entity: str,
        rebate_entity: str,
        device: DeviceInfo,
    ):
        super().__init__(
            name=name,
            unique_id=unique_id,
            unit="€",
            device_class=None,
            icon="mdi:calendar-currency",
            visible=True,
            device=device,
        )
        self.hass = hass
        self.input_sensors = [
            vat_entity,
            surcharge_entity,
            standing_entity,
            rebate_entity,
        ]
        self.vat_entity = vat_entity
        self.surcharge_entity = surcharge_entity
        self.standing_entity = standing_entity
        self.rebate_entity = rebate_entity

    def _get_number(self, entity_id: str) -> float:
        state = self.hass.states.get(entity_id)
        try:
            return float(state.state) if state and state.state not in ("unknown", "unavailable") else 0.0
        except (ValueError, TypeError):
            return 0.0

    def _calculate_daily_cost(self) -> float:
        vat = self._get_number(self.vat_entity)
        surcharge = self._get_number(self.surcharge_entity)
        standing = self._get_number(self.standing_entity)
        rebate = self._get_number(self.rebate_entity)

        subtotal = surcharge + standing - rebate
        total = subtotal * (1 + vat / 100)
        return round(total, 5)

    async def async_update(self):
        # Niet nodig: deze sensor telt dagelijks op via _handle_daily_addition
        pass

    async def async_added_to_hass(self):
        await super().async_added_to_hass()

        for entity_id in self.input_sensors:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass,
                    entity_id,
                    self._handle_input_event,
                )
            )

        # Plan dagelijks optellen om middernacht
        self.async_on_remove(
            async_track_time_change(
                self.hass,
                self._handle_daily_addition,
                hour=0,
                minute=0,
                second=0,
            )
        )

    async def _handle_input_event(self, event):
        new_state = event.data.get("new_state")
        if new_state is None or new_state.state in ("unknown", "unavailable"):
            return
        self.async_write_ha_state()

    async def _handle_daily_addition(self, now):
        self._attr_native_value += self._calculate_daily_cost()
        self.async_write_ha_state()

            
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
            state = hass.states.get(sensor)
            friendly_name = state.attributes.get("friendly_name") if state else sensor_entity_id
            device_info = DeviceInfo(
                identifiers={(DOMAIN, base_id)},
                name=f"{DOMAIN_ABBREVIATION}: {friendly_name}",
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

    # Daily cost sensor op basis van vaste kosten
    base_id = "daily_electricity_cost"
    unique_id = f"{DOMAIN}_{base_id}"
    device_info = DeviceInfo(
        identifiers={(DOMAIN, base_id)},
        name=f"{DOMAIN_ABBREVIATION}: Fixed Daily Electricity Cost (Total)",
        entry_type="service",
        manufacturer="DynamicEnergyCalc",
        model="daily_cost",
    )

    entities.append(
        DailyElectricityCostSensor(
            hass=hass,
            name="Daily Electricity Cost",
            unique_id=unique_id,
            vat_entity="number.dynamic_energy_calculator_vat_percentage",
            surcharge_entity="number.dynamic_energy_calculator_electricity_surcharge_per_day",
            standing_entity="number.dynamic_energy_calculator_electricity_standing_charge_per_day",
            rebate_entity="number.dynamic_energy_calculator_electricity_tax_rebate_per_day",
            device=device_info,
        )
    )


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
