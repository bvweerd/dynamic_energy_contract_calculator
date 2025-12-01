"""Diagnostics support for Dynamic Energy Contract Calculator."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_CONFIGS, CONF_SOURCES, DOMAIN

REDACT_CONFIG: set[str] = set()
REDACT_STATE = {"context"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""

    sources: list[dict[str, Any]] = []
    data: dict[str, Any] = {
        "entry": {
            "data": async_redact_data(dict(entry.data), REDACT_CONFIG),
            "options": async_redact_data(dict(entry.options), REDACT_CONFIG),
        },
        "sources": sources,
    }

    tracker = hass.data.get(DOMAIN, {}).get("netting", {}).get(entry.entry_id)
    if tracker:
        data["netting"] = {
            "enabled": True,
            "net_consumption_kwh": tracker.net_consumption_kwh,
            "tax_balance_per_sensor": tracker.tax_balance_per_sensor,
        }
    else:
        data["netting"] = {"enabled": False}

    # Add solar bonus tracker info if available
    solar_bonus_tracker = hass.data.get(DOMAIN, {}).get("solar_bonus", {}).get(entry.entry_id)
    if solar_bonus_tracker:
        data["solar_bonus"] = {
            "enabled": True,
            "year_production_kwh": solar_bonus_tracker.year_production_kwh,
            "total_bonus_euro": solar_bonus_tracker.total_bonus_euro,
        }
    else:
        data["solar_bonus"] = {"enabled": False}

    # Add binary sensor states by searching for them
    binary_sensors = {}

    # Search through all binary_sensor entities that might belong to this integration
    for state in hass.states.async_all("binary_sensor"):
        if state and (
            "solar_bonus_active" in state.entity_id.lower() or
            "production_price_positive" in state.entity_id.lower()
        ):
            # Try to match by checking the unique_id or attributes
            sensor_name = state.entity_id.replace("binary_sensor.", "")
            binary_sensors[sensor_name] = async_redact_data(
                state.as_dict(), REDACT_STATE
            )

    if binary_sensors:
        data["binary_sensors"] = binary_sensors

    for block in entry.data.get(CONF_CONFIGS, []):
        for source in block.get(CONF_SOURCES, []):
            state = hass.states.get(source)
            state_dict = None
            if state:
                state_dict = async_redact_data(state.as_dict(), REDACT_STATE)
            sources.append(
                {
                    "entity_id": source,
                    "state": state_dict,
                }
            )

    return data
