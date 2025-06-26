from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.sensor import SensorEntity, RestoreEntity
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_change
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN, DOMAIN_ABBREVIATION, CONF_CONFIGS, CONF_SOURCE_TYPE, CONF_SOURCES, CONF_PRICE_SENSOR, CONF_PRICE_SETTINGS, SOURCE_TYPE_CONSUMPTION, SOURCE_TYPE_PRODUCTION

import logging

_LOGGER = logging.getLogger(__name__)

SENSOR_MODES_ELECTRICITY = [
    {
        "key": "kwh_total",
        "name": "Total kWh",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "icon": "mdi:counter",
        "visible": True,
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
        "key": "profit_total",
        "name": "Total Profit",
        "unit": "€",
        "device_class": None,
        "icon": "mdi:cash-plus",
        "visible": True,
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
        return round(self._attr_native_value, 8)

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
        self._attr_native_value = round(value, 8)
        self.async_write_ha_state()


class TotalCostSensor(BaseUtilitySensor):
    def __init__(self, hass: HomeAssistant, name: str, unique_id: str, device: DeviceInfo):
        super().__init__(
            name=name,
            unique_id=unique_id,
            unit="€",
            device_class=None,
            icon="mdi:scale-balance",
            visible=True,
            device=device,
        )
        self.hass = hass

    async def async_update(self):
        cost_total = 0.0
        profit_total = 0.0

        for entity in UTILITY_ENTITIES:
            if isinstance(entity, DynamicEnergySensor):
                if entity.mode == "cost_total":
                    try:
                        cost_total += float(entity.native_value or 0.0)
                    except ValueError:
                        continue
                elif entity.mode == "profit_total":
                    try:
                        profit_total += float(entity.native_value or 0.0)
                    except ValueError:
                        continue

        self._attr_native_value = round(cost_total - profit_total, 8)

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        for entity in UTILITY_ENTITIES:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass,
                    entity.entity_id,
                    self._handle_input_event,
                )
            )

    async def _handle_input_event(self, event):
        await self.async_update()
        self.async_write_ha_state()


class DynamicEnergySensor(BaseUtilitySensor):
    def __init__(
        self,
        hass: HomeAssistant,
        name: str,
        unique_id: str,
        energy_sensor: str,
        source_type: str,
        price_settings: dict[str, float],
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
        self.price_settings = price_settings
        self._last_energy = None
        self._last_updated = datetime.now()

    async def async_update(self):
        markup_consumption  = self.price_settings.get("electricity_consumption_markup_per_kwh", 0.0)
        markup_production   = self.price_settings.get("electricity_production_markup_per_kwh", 0.0)
        tax_kwh             = self.price_settings.get("electricity_surcharge_per_kwh", 0.0)
        vat_factor          = self.price_settings.get("vat_percentage", 21.0) / 100.0 + 1.0

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

        if self.mode == "kwh_total":
            self._attr_native_value += delta
        elif self.price_sensor:
            price_state = self.hass.states.get(self.price_sensor)
            if price_state is None or price_state.state in ("unknown", "unavailable"):
                return
            try:
                price = float(price_state.state)
            except ValueError:
                return

            if self.source_type == SOURCE_TYPE_CONSUMPTION:
                price = (price + markup_consumption + tax_kwh) * vat_factor
            elif self.source_type == SOURCE_TYPE_PRODUCTION:
                price = (price + markup_production) * vat_factor
            else:
                _LOGGER.error("Unknown source_type: %s", self.source_type)
                return

            value = delta * price
            _LOGGER.debug("Delta: %5f, Price: %5f, Value: %5f", delta, price, value)

            if self.mode == "cost_total" and value >= 0:
                self._attr_native_value += value
            elif self.mode == "profit_total" and value < 0:
                self._attr_native_value += abs(value)
            elif self.mode == "kwh_during_cost_total" and value >= 0:
                self._attr_native_value += delta
            elif self.mode == "kwh_during_profit_total" and value < 0:
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
        new_state = event.data.get("new_state")
        if new_state is None or new_state.state in ("unknown", "unavailable"):
            return
        await self.async_update()
        self.async_write_ha_state()


class DailyElectricityCostSensor(BaseUtilitySensor):
    def __init__(
        self,
        hass: HomeAssistant,
        name: str,
        unique_id: str,
        price_settings: dict[str, float],
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
        self.price_settings = price_settings

    def _calculate_daily_cost(self) -> float:
        vat = self.price_settings.get("vat_percentage", 21.0)
        surcharge = self.price_settings.get("electricity_surcharge_per_day", 0.0)
        standing = self.price_settings.get("electricity_standing_charge_per_day", 0.0)
        rebate = self.price_settings.get("electricity_tax_rebate_per_day", 0.0)

        subtotal = surcharge + standing - rebate
        total = subtotal * (1 + vat / 100)
        return round(total, 8)

    async def async_update(self):
        pass

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(
            async_track_time_change(
                self.hass,
                self._handle_daily_addition,
                hour=0,
                minute=0,
                second=0,
            )
        )

    async def _handle_daily_addition(self, now):
        self._attr_native_value += self._calculate_daily_cost()
        self.async_write_ha_state()

class TotalEnergyCostSensor(BaseUtilitySensor):
    def __init__(self, hass: HomeAssistant, name: str, unique_id: str, net_cost_entity_id: str, fixed_cost_entity_id: str, device: DeviceInfo):
        super().__init__(
            name=name,
            unique_id=unique_id,
            unit="€",
            device_class=None,
            icon="mdi:currency-eur",
            visible=True,
            device=device,
        )
        self.hass = hass
        self.net_cost_entity_id = net_cost_entity_id
        self.fixed_cost_entity_id = fixed_cost_entity_id

    async def async_update(self):
        net_cost = 0.0
        fixed_cost = 0.0

        net_state = self.hass.states.get(self.net_cost_entity_id)
        if net_state and net_state.state not in ("unknown", "unavailable"):
            try:
                net_cost = float(net_state.state)
            except ValueError:
                pass

        fixed_state = self.hass.states.get(self.fixed_cost_entity_id)
        if fixed_state and fixed_state.state not in ("unknown", "unavailable"):
            try:
                fixed_cost = float(fixed_state.state)
            except ValueError:
                pass

        self._attr_native_value = round(net_cost + fixed_cost, 8)

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        for entity_id in [self.net_cost_entity_id, self.fixed_cost_entity_id]:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass,
                    entity_id,
                    self._handle_input_event,
                )
            )

    async def _handle_input_event(self, event):
        await self.async_update()
        self.async_write_ha_state()

class CurrentElectricityPriceSensor(BaseUtilitySensor):
    def __init__(
        self,
        hass: HomeAssistant,
        name: str,
        unique_id: str,
        price_sensor: str,
        source_type: str,
        price_settings: dict[str, float],
        icon: str,
        device: DeviceInfo,
    ):
        super().__init__(
            name=name,
            unique_id=unique_id,
            unit="€/kWh",
            device_class=None,
            icon=icon,
            visible=True,
            device=device,
        )
        self.hass = hass
        self.price_sensor = price_sensor
        self.source_type = source_type
        self.price_settings = price_settings

    async def async_update(self):
        state = self.hass.states.get(self.price_sensor)
        if state is None or state.state in ("unknown", "unavailable"):
            return
        try:
            base_price = float(state.state)
        except ValueError:
            return

        markup_consumption = self.price_settings.get("electricity_consumption_markup_per_kwh", 0.0)
        markup_production  = self.price_settings.get("electricity_production_markup_per_kwh", 0.0)
        tax_kwh            = self.price_settings.get("electricity_surcharge_per_kwh", 0.0)
        vat_factor         = self.price_settings.get("vat_percentage", 21.0) / 100.0 + 1.0

        if self.source_type == SOURCE_TYPE_CONSUMPTION:
            price = (base_price + markup_consumption + tax_kwh) * vat_factor
        elif self.source_type == SOURCE_TYPE_PRODUCTION:
            price = (base_price + markup_production) * vat_factor
        else:
            return

        self._attr_native_value = round(price, 8)

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(
            async_track_state_change_event(
                self.hass,
                self.price_sensor,
                self._handle_price_change,
            )
        )

    async def _handle_price_change(self, event):
        await self.async_update()
        self.async_write_ha_state()
        
async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback
) -> None:
    configs = entry.data.get(CONF_CONFIGS, [])
    price_settings = entry.options.get(CONF_PRICE_SETTINGS, entry.data.get(CONF_PRICE_SETTINGS, {}))
    entities: list[BaseUtilitySensor] = []

    for block in configs:
        source_type = block[CONF_SOURCE_TYPE]
        sources = block[CONF_SOURCES]
        price_sensor = entry.data.get(CONF_PRICE_SENSOR)

        for sensor in sources:
            base_id = sensor.replace(".", "_")
            state = hass.states.get(sensor)
            friendly_name = state.attributes.get("friendly_name") if state else sensor
            device_info = DeviceInfo(
                identifiers={(DOMAIN, base_id)},
                name=f"{DOMAIN_ABBREVIATION}: {friendly_name}",
                entry_type="service",
                manufacturer="DynamicEnergyCalc",
                model=source_type,
            )

            for mode_def in SENSOR_MODES_ELECTRICITY:
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
                        price_settings=price_settings,
                        mode=mode,
                        source_type=source_type,
                        unit=mode_def["unit"],
                        icon=mode_def["icon"],
                        visible=mode_def["visible"],
                        device=device_info,
                    )
                )

    UTILITY_ENTITIES.extend(entities)

    base_id = "daily_electricity_cost"
    unique_id = f"{DOMAIN}_{base_id}"
    device_info = DeviceInfo(
        identifiers={(DOMAIN, base_id)},
        name=f"{DOMAIN_ABBREVIATION}: Summary Sensors",
        entry_type="service",
        manufacturer="DynamicEnergyCalc",
        model="summary",
    )

    entities.append(
        DailyElectricityCostSensor(
            hass=hass,
            name="Electricity Contract Fixed Costs (Total)",
            unique_id=unique_id,
            price_settings=price_settings,
            device=device_info,
        )
    )

    entities.append(
        TotalCostSensor(
            hass=hass,
            name="Net Energy Cost (Total)",
            unique_id=f"{DOMAIN}_net_total_cost",
            device=device_info,
        )
    )

    entities.append(
        TotalEnergyCostSensor(
            hass=hass,
            name="Energy Contract Cost (Total)",
            unique_id=f"{DOMAIN}_total_energy_cost",
            net_cost_entity_id="sensor.net_energy_cost_total",
            fixed_cost_entity_id="sensor.electricity_contract_fixed_costs_total",
            device=device_info,
        )
    )

    price_sensor = entry.data.get(CONF_PRICE_SENSOR)
    if price_sensor:
        entities.append(
            CurrentElectricityPriceSensor(
                hass=hass,
                name="Current Consumption Price",
                unique_id=f"{DOMAIN}_current_consumption_price",
                price_sensor=price_sensor,
                source_type=SOURCE_TYPE_CONSUMPTION,
                price_settings=price_settings,
                icon="mdi:transmission-tower-import",
                device=device_info,
            )
        )
        entities.append(
            CurrentElectricityPriceSensor(
                hass=hass,
                name="Current Production Price",
                unique_id=f"{DOMAIN}_current_production_price",
                price_sensor=price_sensor,
                source_type=SOURCE_TYPE_PRODUCTION,
                price_settings=price_settings,
                icon="mdi:transmission-tower-export",
                device=device_info,
            )
        )
        
    async_add_entities(entities, True)

    async def handle_reset_all(call: ServiceCall):
        for ent in entities:
            ent.reset()

    async def handle_reset_selected(call: ServiceCall):
        ids = call.data.get("entity_ids", [])
        for ent in entities:
            if ent.entity_id in ids:
                ent.reset()

    async def handle_set_value(call: ServiceCall):
        entity_id = call.data.get("entity_id")
        value = call.data.get("value", 0.0)
        for ent in entities:
            if ent.entity_id == entity_id:
                ent.set_value(value)

    hass.services.async_register(DOMAIN, "reset_all_meters", handle_reset_all)
    hass.services.async_register(DOMAIN, "reset_selected_meters", handle_reset_selected)
    hass.services.async_register(DOMAIN, "set_meter_value", handle_set_value)

    hass.data[DOMAIN]["entities"] = entities
