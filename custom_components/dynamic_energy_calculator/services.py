# custom_components/dynamic_energy_calculator/services.py

import logging
import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# ─── service schemas ──────────────────────────────────────────────────────────

RESET_ALL_SCHEMA = vol.Schema({})

RESET_SENSORS_SCHEMA = vol.Schema(
    {vol.Required("entity_ids"): vol.All(cv.ensure_list, [cv.entity_id])}
)

SET_VALUE_SCHEMA = vol.Schema(
    {
        vol.Required("entity_id"): cv.entity_id,
        vol.Required("value"): vol.Coerce(float),
    }
)

# ─── registration ──────────────────────────────────────────────────────────────


async def async_register_services(hass: HomeAssistant) -> None:
    """Register custom services for Dynamic Energy Contract Calculator."""
    hass.services.async_register(
        DOMAIN, "reset_all_meters", _handle_reset_all, schema=RESET_ALL_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        "reset_selected_meters",
        _handle_reset_sensors,
        schema=RESET_SENSORS_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN, "set_meter_value", _handle_set_value, schema=SET_VALUE_SCHEMA
    )
    _LOGGER.debug("Dynamic Energy Contract Calculator services registered.")


# ─── service handlers ─────────────────────────────────────────────────────────


async def _handle_reset_all(call: ServiceCall) -> None:
    """Reset **all** dynamic‐energy sensors back to zero."""
    _LOGGER.info("Service reset_all_meters called")
    for entity in call.hass.states.async_entity_ids(f"{DOMAIN}."):
        ent = call.hass.data[DOMAIN]["entities"].get(entity)
        if ent and hasattr(ent, "async_reset"):
            _LOGGER.debug("  resetting %s", entity)
            await ent.async_reset()


async def _handle_reset_sensors(call: ServiceCall) -> None:
    """Reset only the specified sensors back to zero."""
    to_reset = call.data["entity_ids"]
    _LOGGER.info("Service reset_selected_meters called: %s", to_reset)
    for entity in to_reset:
        ent = call.hass.data[DOMAIN]["entities"].get(entity)
        if ent and hasattr(ent, "async_reset"):
            _LOGGER.debug("  resetting %s", entity)
            await ent.async_reset()


async def _handle_set_value(call: ServiceCall) -> None:
    """Set a value on a single sensor."""
    entity = call.data["entity_id"]
    value = call.data["value"]
    _LOGGER.info("Service set_meter_value called: %s → %s", entity, value)
    ent = call.hass.data[DOMAIN]["entities"].get(entity)
    if ent and hasattr(ent, "async_set_value"):
        _LOGGER.debug("  setting %s → %s", entity, value)
        await ent.async_set_value(value)
