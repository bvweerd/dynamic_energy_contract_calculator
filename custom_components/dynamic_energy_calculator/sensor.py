"""
Platform for Dynamic Energy Calculator sensors, including calculations using selected price sensor and number inputs.
"""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.template import Template
from homeassistant.components.template.template_entity import TemplateSensorEntity

from .const import DOMAIN, CONF_SOURCES, CONF_SOURCE_TYPE, CONF_PRICE_SENSOR

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Dynamic Energy sensors based on config entry."""
    source_type = entry.data[CONF_SOURCE_TYPE]
    sources = entry.data[CONF_SOURCES]
    price_entity = entry.data[CONF_PRICE_SENSOR]
    entities: list[SensorEntity] = []
    entry_id = entry.entry_id

    # Create one sensor per selected source (kWh total_increasing)
    for source_entity_id in sources:
        entities.append(
            DynamicEnergySensor(
                entry_id=entry_id,
                source_entity_id=source_entity_id,
                source_type=source_type,
            )
        )
        # Template cost sensor per source
        domain, object_id = source_entity_id.split('.', 1)
        obj_name = object_id.replace('_', ' ').title()
        # Consumption: cost calculation
        if source_type == "consumption":
            state_tpl = (
                f"{{% set m = states('{source_entity_id}') | float(0) %}}"
                f"{{% set p = states('{price_entity}') | float(0) %}}"
                f"{{% set mc = states('number.{DOMAIN}_electricity_consumption_markup_per_kwh') | float(0) %}}"
                f"{{% set tp = states('number.{DOMAIN}_electricity_tax_per_kwh') | float(0) %}}"
                f"{{% set pct = states('number.{DOMAIN}_tax_percentage') | float(0) %}}"
                "{{ (m * (p + mc + tp) * (1 + pct/100)) | round(2) }}"
            )
            entities.append(
                TemplateSensor(
                    hass,
                    entry_id,
                    name=f"{obj_name} Cost",
                    unique_id=f"{entry_id}_{object_id}_cost",
                    unit="€",
                    state_template=state_tpl,
                    depends_on=[
                        source_entity_id,
                        price_entity,
                        f"number.{DOMAIN}_electricity_consumption_markup_per_kwh",
                        f"number.{DOMAIN}_electricity_tax_per_kwh",
                        f"number.{DOMAIN}_tax_percentage",
                    ],
                )
            )
        # Production: profit calculation
        else:
            state_tpl = (
                f"{{% set m = states('{source_entity_id}') | float(0) %}}"
                f"{{% set p = states('{price_entity}') | float(0) %}}"
                f"{{% set mp = states('number.{DOMAIN}_electricity_production_markup_per_kwh') | float(0) %}}"
                f"{{% set tp = states('number.{DOMAIN}_electricity_tax_per_kwh') | float(0) %}}"
                f"{{% set pct = states('number.{DOMAIN}_tax_percentage') | float(0) %}}"
                "{{ (m * (p - mp - tp) * (1 - pct/100)) | round(2) }}"
            )
            entities.append(
                TemplateSensor(
                    hass,
                    entry_id,
                    name=f"{obj_name} Profit",
                    unique_id=f"{entry_id}_{object_id}_profit",
                    unit="€",
                    state_template=state_tpl,
                    depends_on=[
                        source_entity_id,
                        price_entity,
                        f"number.{DOMAIN}_electricity_production_markup_per_kwh",
                        f"number.{DOMAIN}_electricity_tax_per_kwh",
                        f"number.{DOMAIN}_tax_percentage",
                    ],
                )
            )

    async_add_entities(entities, True)

class DynamicEnergySensor(SensorEntity):  # pylint: disable=too-many-instance-attributes
    """Sensor representing a configured energy source."""

    _attr_state_class = "total_increasing"
    _attr_native_unit_of_measurement = "kWh"

    def __init__(
        self,
        entry_id: str,
        source_entity_id: str,
        source_type: str,
    ) -> None:
        """Initialize the sensor."""
        self._entry_id = entry_id
        self._source_entity_id = source_entity_id
        self._source_type = source_type

        domain, object_id = source_entity_id.split('.', 1)
        self._attr_unique_id = f"{entry_id}_{source_type}_{object_id}"
        obj_name = object_id.replace('_', ' ').title()
        self._attr_name = f"{source_type.title()} {obj_name}"
        self._state: float | None = None

    @property
    def native_value(self) -> float | None:
        """Return the current state (kWh) of the source sensor."""
        return self._state

    @callback
    def _async_state_updated(self, event) -> None:
        new_state = event.data.get('new_state')
        if new_state and new_state.state not in (None, 'unknown', 'unavailable'):
            try:
                self._state = float(new_state.state)
            except ValueError:
                _LOGGER.warning(
                    "Received non-numeric state for %s: %s",
                    self._source_entity_id,
                    new_state.state,
                )
                self._state = None
        else:
            self._state = None
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_track_state_change_event(
                self.hass,
                [self._source_entity_id],
                self._async_state_updated,
            )
        )

class TemplateSensor(TemplateSensorEntity):
    """Generic template sensor wrapper."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        name: str,
        unique_id: str,
        unit: str,
        state_template: str,
        depends_on: list[str],
    ) -> None:
        self._template = Template(state_template, hass)
        self._attr_name = name
        self._attr_unique_id = unique_id
        self._attr_native_unit_of_measurement = unit
        self._depends = depends_on
        self._attr_native_value: float | None = None

    async def async_added_to_hass(self) -> None:
        for dep in self._depends:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass, [dep], self._update_from_template
                )
            )
        await self._update_from_template(None)

    @callback
    async def _update_from_template(self, event) -> None:
        try:
            result = self._template.async_render()
            self._attr_native_value = float(result)
        except Exception as err:
            _LOGGER.warning("Error rendering template for %s: %s", self.name, err)
            self._attr_native_value = None
        self.async_write_ha_state()
