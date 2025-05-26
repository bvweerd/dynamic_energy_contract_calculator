# custom_components/dynamic_energy_calculator/sensor.py

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_state_change,
    async_track_time_change,
)
from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.helpers.restore_state import RestoreEntity

from .entity import DynamicEnergyEntity
from .const import (
    DOMAIN,
    CONF_CONFIGS,
    CONF_SOURCE_TYPE,
    CONF_SOURCES,
    CONF_PRICE_SENSOR,
)

_LOGGER = logging.getLogger(__name__)


def _read(hass: HomeAssistant, entity_id: str) -> float:
    """Read an entity’s state and convert to float, or return 0.0."""
    st = hass.states.get(entity_id)
    if st and st.state not in ("unknown", "unavailable", None):
        try:
            return float(st.state)
        except ValueError:
            _LOGGER.warning("Non-numeric state for %s: %s", entity_id, st.state)
    return 0.0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up all per-source energy & cost sensors plus one total-cost sensor."""
    configs = entry.data.get(CONF_CONFIGS, [])
    entities: list[SensorEntity] = []
    cost_entities: list[HourlyCostSensor] = []

    for block in configs:
        source_type = block[CONF_SOURCE_TYPE]
        sources = block[CONF_SOURCES]
        price_sensor = block[CONF_PRICE_SENSOR]

        for src in sources:
            base_slug = src.split(".", 1)[1]
            slug = f"{base_slug}_{source_type}"

            entities.append(
                IntegratedEnergySensor(hass, entry, src, source_type, slug)
            )
            entities.append(
                HourlyEnergySensor(hass, entry, src, source_type, slug)
            )
            cost = HourlyCostSensor(
                hass, entry, src, source_type, price_sensor, slug
            )
            entities.append(cost)
            cost_entities.append(cost)

    entities.append(TotalCostSensor(hass, entry, cost_entities))

    async_add_entities(entities)


class IntegratedEnergySensor(DynamicEnergyEntity, SensorEntity):
    """Cumulative kWh since setup (never resets)."""

    _attr_native_unit_of_measurement = "kWh"
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        source_entity_id: str,
        source_type: str,
        slug: str,
    ) -> None:
        entry_id = entry.entry_id
        device_id = f"{entry_id}_{slug}"
        device_name = f"{slug.replace('_', ' ').title()} Source"
        device_model = f"{source_type.title()} Source"
        key = f"{slug}_total"
        name = f"{slug.replace('_', ' ').title()} Total"

        super().__init__(hass, entry, key, name, device_id, device_name, device_model)

        self._source = source_entity_id
        self._initial: float = 0.0
        self._attr_native_value: float | None = None

    async def async_added_to_hass(self) -> None:
        self._initial = _read(self.hass, self._source)
        async_track_state_change_event(
            self.hass, [self._source], self._recalculate
        )
        await self._recalculate(None)

    @callback
    async def _recalculate(self, event: Any) -> None:
        current = _read(self.hass, self._source)
        self._attr_native_value = round(current - self._initial, 5)
        self.async_write_ha_state()


class HourlyEnergySensor(DynamicEnergyEntity, SensorEntity):
    """kWh per hour (resets at each hour)."""

    _attr_native_unit_of_measurement = "kWh"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        source_entity_id: str,
        source_type: str,
        slug: str,
    ) -> None:
        entry_id = entry.entry_id
        device_id = f"{entry_id}_{slug}"
        device_name = f"{slug.replace('_', ' ').title()} Source"
        device_model = f"{source_type.title()} Source"
        key = f"{slug}_hourly"
        name = f"{slug.replace('_', ' ').title()} Hourly"

        super().__init__(hass, entry, key, name, device_id, device_name, device_model)

        self._source = source_entity_id
        self._base: float = _read(self.hass, self._source)
        self._attr_native_value: float | None = None

    async def async_added_to_hass(self) -> None:
        async_track_state_change_event(
            self.hass, [self._source], self._update_meter
        )
        async_track_time_change(
            self.hass, self._reset_hour, minute=0, second=0
        )
        await self._update_meter(None)

    @callback
    async def _update_meter(self, event: Any) -> None:
        current = _read(self.hass, self._source)
        self._attr_native_value = round(current - self._base, 5)
        self.async_write_ha_state()

    @callback
    async def _reset_hour(self, now: datetime) -> None:
        self._base = _read(self.hass, self._source)
        self._attr_native_value = 0.0
        self.async_write_ha_state()


class HourlyCostSensor(DynamicEnergyEntity, SensorEntity):
    """€ cost accrued per hour, reacting to energy, price & input changes."""

    _attr_native_unit_of_measurement = "€"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        source_entity_id: str,
        source_type: str,
        price_entity_id: str,
        slug: str,
    ) -> None:
        entry_id = entry.entry_id
        device_id = f"{entry_id}_{slug}"
        device_name = f"{slug.replace('_', ' ').title()} Source"
        device_model = f"{source_type.title()} Source"
        key = f"{slug}_cost_hourly"
        name = f"{slug.replace('_', ' ').title()} Cost Hourly"

        super().__init__(hass, entry, key, name, device_id, device_name, device_model)

        self._energy_entity = f"sensor.{DOMAIN}_{entry_id}_{slug}_hourly"
        self._price = price_entity_id
        self._num_cons = f"number.{DOMAIN}_{entry_id}_electricity_consumption_markup_per_kwh"
        self._num_prod = f"number.{DOMAIN}_{entry_id}_electricity_production_markup_per_kwh"
        self._num_taxkwh = f"number.{DOMAIN}_{entry_id}_electricity_tax_per_kwh"
        self._num_taxpct = f"number.{DOMAIN}_{entry_id}_tax_percentage"
        self._type = source_type
        self._attr_native_value: float | None = None

    async def async_added_to_hass(self) -> None:
        deps = [
            self._energy_entity,
            self._price,
            self._num_cons,
            self._num_prod,
            self._num_taxkwh,
            self._num_taxpct,
        ]
        _LOGGER.debug("HourlyCostSensor %s subscribing to: %s", self.entity_id, deps)
        async_track_state_change(self.hass, deps, self._on_state_change)
        await self._recalculate()

    @callback
    async def _on_state_change(self, entity_id: str, old, new) -> None:
        _LOGGER.debug(
            "HourlyCostSensor %s triggered by %s: %r -> %r",
            self.entity_id,
            entity_id,
            getattr(old, "state", None),
            getattr(new, "state", None),
        )
        await self._recalculate()

    async def _recalculate(self) -> None:
        e = _read(self.hass, self._energy_entity)
        p = _read(self.hass, self._price)
        cm = _read(self.hass, self._num_cons)
        pm = _read(self.hass, self._num_prod)
        tk = _read(self.hass, self._num_taxkwh)
        tp = _read(self.hass, self._num_taxpct)

        _LOGGER.debug(
            "HourlyCostSensor %s values: energy=%s price=%s cm=%s pm=%s tk=%s tp=%s",
            self.entity_id, e, p, cm, pm, tk, tp,
        )

        if self._type == "consumption":
            rate = p + cm + tk
            factor = 1 + tp / 100
        else:
            rate = p - pm - tk
            factor = max(1 - tp / 100, 0)

        new_cost = round(e * rate * factor, 5)
        _LOGGER.debug("HourlyCostSensor %s new_cost=%s", self.entity_id, new_cost)

        self._attr_native_value = new_cost
        self.async_write_ha_state()


class TotalCostSensor(DynamicEnergyEntity, RestoreEntity, SensorEntity):
    """Cumulative total-cost sensor (never resets)."""

    _attr_native_unit_of_measurement = "€"
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        cost_entities: list[HourlyCostSensor],
    ) -> None:
        entry_id = entry.entry_id
        device_id = f"{entry_id}_general"
        device_name = "Dynamic Energy Calculator General"
        device_model = "General"
        key = "total_cost_cumulative"
        name = "Total Cost Cumulative"

        super().__init__(hass, entry, key, name, device_id, device_name, device_model)
        self._cost_entities = cost_entities

    async def async_added_to_hass(self) -> None:
        last = await self.async_get_last_state()
        if last and last.state not in ("unknown", None):
            try:
                self._attr_native_value = float(last.state)
            except ValueError:
                self._attr_native_value = 0.0

        ids = [ent.entity_id for ent in self._cost_entities]
        async_track_state_change_event(self.hass, ids, self._recalculate)
        await self._recalculate(None)

    @callback
    async def _recalculate(self, event: Any) -> None:
        total = sum(_read(self.hass, ent.entity_id) for ent in self._cost_entities)
        self._attr_native_value = round(total, 5)
        self.async_write_ha_state()
