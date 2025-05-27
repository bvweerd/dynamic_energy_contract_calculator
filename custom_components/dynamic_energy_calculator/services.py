# custom_components/dynamic_energy_calculator/services.py

import logging
import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

#─── service schemas ──────────────────────────────────────────────────────────

RESET_ALL_SCHEMA = vol.Schema({})

RESET_SENSORS_SCHEMA = vol.Schema({
    vol.Required("entity_ids"): vol.All(cv.ensure_list, [cv.entity_id])
})

SET_VALUES_SCHEMA = vol.Schema({
    vol.Required("values"): {cv.entity_id: vol.Coerce(float)}
})

#─── registration ──────────────────────────────────────────────────────────────

async def async_register_services(hass: HomeAssistant) -> None:
    """Register custom services for Dynamic Energy Calculator."""
    hass.services.async_register(
        DOMAIN, "reset_all", _handle_reset_all, schema=RESET_ALL_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "reset_sensors", _handle_reset_sensors, schema=RESET_SENSORS_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "set_values", _handle_set_values, schema=SET_VALUES_SCHEMA
    )
    _LOGGER.debug("Dynamic Energy Calculator services registered.")


#─── service handlers ─────────────────────────────────────────────────────────

async def _handle_reset_all(call: ServiceCall) -> None:
    """Reset **all** dynamic‐energy sensors back to zero."""
    _LOGGER.info("Service reset_all called")
    for entity in call.hass.states.async_entity_ids(f"{DOMAIN}."):
        ent = call.hass.data[DOMAIN]["entities"].get(entity)
        if ent and hasattr(ent, "async_reset"):
            _LOGGER.debug("  resetting %s", entity)
            await ent.async_reset()


async def _handle_reset_sensors(call: ServiceCall) -> None:
    """Reset only the specified sensors back to zero."""
    to_reset = call.data["entity_ids"]
    _LOGGER.info("Service reset_sensors called: %s", to_reset)
    for entity in to_reset:
        ent = call.hass.data[DOMAIN]["entities"].get(entity)
        if ent and hasattr(ent, "async_reset"):
            _LOGGER.debug("  resetting %s", entity)
            await ent.async_reset()


async def _handle_set_values(call: ServiceCall) -> None:
    """Set arbitrary values on one or more sensors."""
    vals = call.data["values"]
    _LOGGER.info("Service set_values called: %s", vals)
    for entity, value in vals.items():
        ent = call.hass.data[DOMAIN]["entities"].get(entity)
        if ent and hasattr(ent, "async_set_value"):
            _LOGGER.debug("  setting %s → %s", entity, value)
            await ent.async_set_value(value)
