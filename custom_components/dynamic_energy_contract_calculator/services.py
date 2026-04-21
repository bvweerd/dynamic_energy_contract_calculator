# custom_components/dynamic_energy_contract_calculator/services.py
from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .const import CONF_PRICE_SETTINGS, DOMAIN

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

SET_NETTING_SCHEMA = vol.Schema(
    {
        vol.Required("enabled"): bool,
    }
)

SET_NETTING_VALUE_SCHEMA = vol.Schema(
    {
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
    hass.services.async_register(
        DOMAIN, "set_netting", _handle_set_netting, schema=SET_NETTING_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        "set_netting_value",
        _handle_set_netting_value,
        schema=SET_NETTING_VALUE_SCHEMA,
    )
    _LOGGER.debug("Dynamic Energy Contract Calculator services registered.")


async def async_unregister_services(hass: HomeAssistant) -> None:
    """Remove custom services when no entries remain."""
    hass.services.async_remove(DOMAIN, "reset_all_meters")
    hass.services.async_remove(DOMAIN, "reset_selected_meters")
    hass.services.async_remove(DOMAIN, "set_meter_value")
    hass.services.async_remove(DOMAIN, "set_netting")
    hass.services.async_remove(DOMAIN, "set_netting_value")
    _LOGGER.debug("Dynamic Energy Contract Calculator services unregistered.")


# ─── service handlers ─────────────────────────────────────────────────────────


async def _handle_reset_all(call: ServiceCall) -> None:
    """Reset **all** dynamic-energy sensors back to zero."""
    _LOGGER.info("Service reset_all_meters called")
    for entry in call.hass.config_entries.async_entries(DOMAIN):
        if entry.state != ConfigEntryState.LOADED:
            continue
        runtime = getattr(entry, "runtime_data", None)
        if runtime is None:
            continue
        for entity_id, ent in runtime.entities.items():
            if hasattr(ent, "async_reset"):
                _LOGGER.debug("  resetting %s", entity_id)
                await ent.async_reset()
        if runtime.netting_tracker is not None:
            await runtime.netting_tracker.async_reset_all()


async def _handle_reset_sensors(call: ServiceCall) -> None:
    """Reset only the specified sensors back to zero."""
    to_reset: list[str] = call.data["entity_ids"]
    _LOGGER.info("Service reset_selected_meters called: %s", to_reset)
    for entry in call.hass.config_entries.async_entries(DOMAIN):
        if entry.state != ConfigEntryState.LOADED:
            continue
        runtime = getattr(entry, "runtime_data", None)
        if runtime is None:
            continue
        for entity_id in to_reset:
            ent = runtime.entities.get(entity_id)
            if ent and hasattr(ent, "async_reset"):
                _LOGGER.debug("  resetting %s", entity_id)
                await ent.async_reset()


async def _handle_set_value(call: ServiceCall) -> None:
    """Set a value on a single sensor."""
    entity_id: str = call.data["entity_id"]
    value: float = call.data["value"]
    _LOGGER.info("Service set_meter_value called: %s → %s", entity_id, value)
    for entry in call.hass.config_entries.async_entries(DOMAIN):
        if entry.state != ConfigEntryState.LOADED:
            continue
        runtime = getattr(entry, "runtime_data", None)
        if runtime is None:
            continue
        ent = runtime.entities.get(entity_id)
        if ent and hasattr(ent, "async_set_value"):
            _LOGGER.debug("  setting %s → %s", entity_id, value)
            await ent.async_set_value(value)
            return


async def _handle_set_netting(call: ServiceCall) -> None:
    """Enable or disable netting via config entry options."""
    enabled: bool = call.data["enabled"]
    _LOGGER.info("Service set_netting called: enabled=%s", enabled)

    entries = call.hass.config_entries.async_entries(DOMAIN)
    for entry in entries:
        if entry.state != ConfigEntryState.LOADED:
            continue

        current_options = dict(entry.options) if entry.options else dict(entry.data)
        price_settings = dict(current_options.get(CONF_PRICE_SETTINGS, {}))
        price_settings["netting_enabled"] = enabled
        current_options[CONF_PRICE_SETTINGS] = price_settings

        call.hass.config_entries.async_update_entry(entry, options=current_options)
        _LOGGER.info("Netting set to %s for entry %s", enabled, entry.entry_id)

        await call.hass.config_entries.async_reload(entry.entry_id)


async def _handle_set_netting_value(call: ServiceCall) -> None:
    """Set the netting net_consumption_kwh value directly."""
    value: float = call.data["value"]
    _LOGGER.info("Service set_netting_value called: value=%s", value)

    for entry in call.hass.config_entries.async_entries(DOMAIN):
        if entry.state != ConfigEntryState.LOADED:
            continue
        runtime = getattr(entry, "runtime_data", None)
        if runtime is None:
            continue
        tracker = runtime.netting_tracker
        if tracker is not None:
            await tracker.async_set_net_consumption(value)
            _LOGGER.info(
                "Netting net_consumption_kwh set to %s for entry %s",
                value,
                entry.entry_id,
            )
