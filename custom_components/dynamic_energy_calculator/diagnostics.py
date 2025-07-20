"""Diagnostics support for Dynamic Energy Contract Calculator."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_CONFIGS, CONF_SOURCES

REDACT_CONFIG = set()
REDACT_STATE = {"context"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""

    data = {
        "entry": {
            "data": async_redact_data(dict(entry.data), REDACT_CONFIG),
            "options": async_redact_data(dict(entry.options), REDACT_CONFIG),
        },
        "sources": [],
    }

    for block in entry.data.get(CONF_CONFIGS, []):
        for source in block.get(CONF_SOURCES, []):
            state = hass.states.get(source)
            state_dict = None
            if state:
                state_dict = async_redact_data(state.as_dict(), REDACT_STATE)
            data["sources"].append(
                {
                    "entity_id": source,
                    "state": state_dict,
                }
            )

    return data
