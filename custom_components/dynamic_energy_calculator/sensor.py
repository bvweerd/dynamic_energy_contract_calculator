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
            val = float(st.state)
            _LOGGER.debug("Read %s = %s", entity_id, val)
            return val
        except ValueError:
            _LOGGER.warning("Non-numeric state for %s: %s", entity_id, st.state)
    else:
        _LOGGER.debug("State for %s unavailable/unknown: %s", entity_id, st)
    return 0.0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    _LOGGER.debug("async_setup_entry(%s)", entry.entry_id)
    configs = entry.data.get(CONF_CONFIGS, [])
    entities: list[SensorEntity] = []
    cost_entities: list[HourlyCostSensor] = []

    for block in configs:
        source_type = block[CONF_SOURCE_TYPE]
        sources = block[CONF_SOURCES]
        price_sensor = block[CONF_PRICE_SENSOR]
        _LOGGER.debug(
            "Block %s: sources=%s price=%s", source_type, sources, price_sensor
        )

        for src in sources:
            slug = src.split(".", 1)[1]
            _LOGGER.debug("Creating sensors for slug=%s", slug)

            entities.append(IntegratedEnergySensor(hass, entry, src, source_type, slug))
            entities.append(HourlyEnergySensor(hass, entry, src, source_type, slug))

            hourly_cost = HourlyCostSensor(
                hass, entry, src, source_type, price_sensor, slug
            )
            entities.append(hourly_cost)
            cost_entities.append(hourly_cost)

            # New: cumulative cost per source
            cum_cost = CumulativeCostSensor(hass, entry, slug, source_type)
            entities.append(cum_cost)

    # Global total-cost across all sources
    entities.append(TotalCostSensor(hass, entry, cost_entities))
    _LOGGER.debug("Adding entities: %s", [e.entity_id for e in entities])
    async_add_entities(entities)


class IntegratedEnergySensor(DynamicEnergyEntity, RestoreEntity, SensorEntity):
    """Cumulative kWh since first setup, persisting across restarts."""

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
        key = f"{slug}_{source_type}_total"
        name = f"{slug.replace('_',' ').title()} Total"
        device_id = slug
        device_name = slug.replace("_", " ").title()
        device_model = f"{source_type.title()} Source"
        _LOGGER.debug("Init IntegratedEnergySensor: %s", name)
        super().__init__(hass, entry, key, name, device_id, device_name, device_model)

        self.entity_id = f"sensor.{DOMAIN}_{slug}_{source_type}_total"
        self._source = source_entity_id
        self._initial: float = 0.0
        self._attr_native_value: float | None = None

    async def async_added_to_hass(self) -> None:
        _LOGGER.debug(
            "IntegratedEnergySensor %s added; restoring state", self.entity_id
        )
        last = await self.async_get_last_state()
        current = _read(self.hass, self._source)

        if last and last.state not in ("unknown", None):
            try:
                restored = float(last.state)
                self._initial = current - restored
                self._attr_native_value = restored
                _LOGGER.debug(
                    "%s restored=%s, current=%s, new initial=%s",
                    self.entity_id,
                    restored,
                    current,
                    self._initial,
                )
            except ValueError:
                self._initial = current
                _LOGGER.warning(
                    "%s failed to parse restored state, setting baseline to %s",
                    self.entity_id,
                    self._initial,
                )
        else:
            self._initial = current
            self._attr_native_value = 0.0
            _LOGGER.debug(
                "%s no restore state, initial baseline=%s",
                self.entity_id,
                self._initial,
            )

        async_track_state_change_event(self.hass, [self._source], self._recalc)
        await self._recalc(None)

    @callback
    async def _recalc(self, event: Any) -> None:
        current = _read(self.hass, self._source)
        value = round(current - self._initial, 5)
        _LOGGER.debug("%s recalc: %s", self.entity_id, value)
        self._attr_native_value = value
        self.async_write_ha_state()


class HourlyEnergySensor(DynamicEnergyEntity, SensorEntity):
    """kWh per hour (resets hourly)."""

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
        key = f"{slug}_{source_type}_hourly"
        name = f"{slug.replace('_',' ').title()} Hourly"
        device_id = slug
        device_name = slug.replace("_", " ").title()
        device_model = f"{source_type.title()} Source"
        _LOGGER.debug("Init HourlyEnergySensor: %s", name)
        super().__init__(hass, entry, key, name, device_id, device_name, device_model)

        self.entity_id = f"sensor.{DOMAIN}_{slug}_{source_type}_hourly"
        self._source = source_entity_id
        self._base = _read(self.hass, self._source)
        self._attr_native_value: float | None = None

    async def async_added_to_hass(self) -> None:
        _LOGGER.debug("%s added; base=%s", self.entity_id, self._base)
        async_track_state_change_event(self.hass, [self._source], self._update)
        async_track_time_change(self.hass, self._reset, minute=0, second=0)
        await self._update(None)

    @callback
    async def _update(self, event: Any) -> None:
        current = _read(self.hass, self._source)
        value = round(current - self._base, 5)
        _LOGGER.debug("%s update: %s", self.entity_id, value)
        self._attr_native_value = value
        self.async_write_ha_state()

    @callback
    async def _reset(self, now: datetime) -> None:
        self._base = _read(self.hass, self._source)
        _LOGGER.debug("%s reset at %s; new base=%s", self.entity_id, now, self._base)
        self._attr_native_value = 0.0
        self.async_write_ha_state()


class HourlyCostSensor(DynamicEnergyEntity, SensorEntity):
    """€ cost per hour, reacting to energy, price & input changes."""

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
        key = f"{slug}_{source_type}_cost_hourly"
        name = f"{slug.replace('_',' ').title()} Cost Hourly"
        device_id = slug
        device_name = slug.replace("_", " ").title()
        device_model = f"{source_type.title()} Source"
        _LOGGER.debug("Init HourlyCostSensor: %s", name)
        super().__init__(hass, entry, key, name, device_id, device_name, device_model)

        self.entity_id = f"sensor.{DOMAIN}_{slug}_{source_type}_cost_hourly"
        self._energy_entity = f"sensor.{DOMAIN}_{slug}_{source_type}_hourly"
        self._price = price_entity_id
        base = f"number.{DOMAIN}_general_"
        self._num_cons = base + "electricity_consumption_markup_per_kwh"
        self._num_prod = base + "electricity_production_markup_per_kwh"
        self._num_taxkwh = base + "electricity_tax_per_kwh"
        self._num_taxpct = base + "tax_percentage"
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
        _LOGGER.debug("%s subscribing to %s", self.entity_id, deps)
        async_track_state_change_event(self.hass, deps, self._on_event)
        await self._compute()

    @callback
    async def _on_event(self, event: Any) -> None:
        ent = event.data.get("entity_id")
        old = event.data.get("old_state")
        new = event.data.get("new_state")
        _LOGGER.debug(
            "%s triggered by %s: %r -> %r",
            self.entity_id,
            ent,
            old and old.state,
            new and new.state,
        )
        await self._compute()

    async def _compute(self) -> None:
        """Compute cost differently for consumption vs production."""
        e = _read(self.hass, self._energy_entity)
        p = _read(self.hass, self._price)
        cm = _read(self.hass, self._num_cons)
        pm = _read(self.hass, self._num_prod)
        tp = _read(self.hass, self._num_taxpct)

        _LOGGER.debug(
            "%s inputs: e=%s p=%s cm=%s pm=%s tp=%s", self.entity_id, e, p, cm, pm, tp
        )

        if self._type == "consumption":
            rate = p + cm
            factor = 1 + tp / 100
            cost = e * rate * factor
        else:
            rate = p
            factor = 1 + tp / 100
            cost = -(e * rate + e * pm * factor)

        new_cost = round(cost, 5)
        _LOGGER.info("%s computed new_cost=%s", self.entity_id, new_cost)
        self._attr_native_value = new_cost
        self.async_write_ha_state()


class CumulativeCostSensor(DynamicEnergyEntity, RestoreEntity, SensorEntity):
    """Cumulative per-source cost (never resets)."""

    _attr_native_unit_of_measurement = "€"
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        slug: str,
        source_type: str,
    ) -> None:
        key = f"{slug}_{source_type}_cost_cumulative"
        name = f"{slug.replace('_',' ').title()} Cost Cumulative"
        device_id = slug
        device_name = slug.replace("_", " ").title()
        device_model = f"{source_type.title()} Source"
        _LOGGER.debug("Init CumulativeCostSensor: %s", name)
        super().__init__(hass, entry, key, name, device_id, device_name, device_model)

        self.entity_id = f"sensor.{DOMAIN}_{slug}_{source_type}_cost_cumulative"
        self._hourly_entity = f"sensor.{DOMAIN}_{slug}_{source_type}_cost_hourly"
        self._cumulative: float = 0.0
        self._prev: float = 0.0

    async def async_added_to_hass(self) -> None:
        _LOGGER.debug("%s added; restoring state", self.entity_id)
        last = await self.async_get_last_state()
        if last and last.state not in ("unknown", None):
            try:
                self._cumulative = float(last.state)
            except ValueError:
                self._cumulative = 0.0
        _LOGGER.debug("%s restored cumulative=%s", self.entity_id, self._cumulative)

        # initialize prev to current hourly cost
        self._prev = _read(self.hass, self._hourly_entity)
        _LOGGER.debug("%s initial prev hourly=%s", self.entity_id, self._prev)

        async_track_state_change_event(
            self.hass, [self._hourly_entity], self._hourly_changed
        )
        # write initial
        self._attr_native_value = round(self._cumulative, 5)
        self.async_write_ha_state()

    @callback
    async def _hourly_changed(self, event: Any) -> None:
        new = _read(self.hass, self._hourly_entity)
        prev = self._prev
        delta = new - prev if new >= prev else new
        self._prev = new
        self._cumulative += delta
        _LOGGER.debug(
            "%s hourly delta=%s cumulative=%s", self.entity_id, delta, self._cumulative
        )
        self._attr_native_value = round(self._cumulative, 5)
        self.async_write_ha_state()


class TotalCostSensor(DynamicEnergyEntity, RestoreEntity, SensorEntity):
    """Cumulative total-cost sensor (persists across restart)."""

    _attr_native_unit_of_measurement = "€"
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        cost_entities: list[HourlyCostSensor],
    ) -> None:
        key = "total_cost_cumulative"
        name = "Total Cost Cumulative"
        device_id = "general"
        device_name = "Dynamic Energy Calculator General"
        device_model = "General"
        _LOGGER.debug("Init TotalCostSensor: %s", name)
        super().__init__(hass, entry, key, name, device_id, device_name, device_model)

        self.entity_id = f"sensor.{DOMAIN}_total_cost_cumulative"
        self._cost_entities = cost_entities

    async def async_added_to_hass(self) -> None:
        _LOGGER.debug("%s added; restoring state", self.entity_id)
        last = await self.async_get_last_state()
        if last and last.state not in ("unknown", None):
            try:
                self._attr_native_value = float(last.state)
            except ValueError:
                self._attr_native_value = 0.0
        _LOGGER.debug("%s restored state=%s", self.entity_id, self._attr_native_value)

        ids = [ent.entity_id for ent in self._cost_entities]
        _LOGGER.debug("%s subscribing to %s", self.entity_id, ids)
        async_track_state_change_event(self.hass, ids, self._recalc)
        await self._recalc(None)

    @callback
    async def _recalc(self, event: Any) -> None:
        total = sum(_read(self.hass, e.entity_id) for e in self._cost_entities)
        _LOGGER.info("%s new total=%s", self.entity_id, total)
        self._attr_native_value = round(total, 5)
        self.async_write_ha_state()
