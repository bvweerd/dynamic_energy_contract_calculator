# custom_components/dynamic_energy_contract_calculator/services.py

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

    async def handle_reset_all(call: ServiceCall) -> None:
        """Reset **all** dynamic-energy sensors back to zero."""
        _LOGGER.info("Service reset_all_meters called")
        entities = hass.data.get(DOMAIN, {}).get("entities", {})
        for entity_id, ent in entities.items():
            if hasattr(ent, "async_reset"):
                _LOGGER.debug("  resetting %s", entity_id)
                await ent.async_reset()
        netting_map = hass.data.get(DOMAIN, {}).get("netting")
        if isinstance(netting_map, dict):
            for tracker in netting_map.values():
                await tracker.async_reset_all()

    async def handle_reset_sensors(call: ServiceCall) -> None:
        """Reset only the specified sensors back to zero."""
        to_reset = call.data["entity_ids"]
        _LOGGER.info("Service reset_selected_meters called: %s", to_reset)
        entities = hass.data.get(DOMAIN, {}).get("entities", {})
        for entity in to_reset:
            ent = entities.get(entity)
            if ent and hasattr(ent, "async_reset"):
                _LOGGER.debug("  resetting %s", entity)
                await ent.async_reset()
        netting_map = hass.data.get(DOMAIN, {}).get("netting")
        if isinstance(netting_map, dict):
            for tracker in netting_map.values():
                await tracker.async_reset_all()

    async def handle_set_value(call: ServiceCall) -> None:
        """Set a value on a single sensor."""
        entity = call.data["entity_id"]
        value = call.data["value"]
        _LOGGER.info("Service set_meter_value called: %s → %s", entity, value)
        ent = hass.data.get(DOMAIN, {}).get("entities", {}).get(entity)
        if ent and hasattr(ent, "async_set_value"):
            _LOGGER.debug("  setting %s → %s", entity, value)
            await ent.async_set_value(value)

    hass.services.async_register(
        DOMAIN, "reset_all_meters", handle_reset_all, schema=RESET_ALL_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        "reset_selected_meters",
        handle_reset_sensors,
        schema=RESET_SENSORS_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN, "set_meter_value", handle_set_value, schema=SET_VALUE_SCHEMA
    )
    _LOGGER.debug("Dynamic Energy Contract Calculator services registered.")


async def async_unregister_services(hass: HomeAssistant) -> None:
    """Remove custom services when no entries remain."""
    hass.services.async_remove(DOMAIN, "reset_all_meters")
    hass.services.async_remove(DOMAIN, "reset_selected_meters")
    hass.services.async_remove(DOMAIN, "set_meter_value")
    _LOGGER.debug("Dynamic Energy Contract Calculator services unregistered.")
