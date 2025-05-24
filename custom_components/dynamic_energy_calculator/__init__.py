"""
Initialization for the Dynamic Energy Calculator integration.
"""

from __future__ import annotations

from typing import Any
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN

PLATFORMS: list[str] = ["sensor", "number"]

async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the integration from configuration (not used)."""
    # No YAML configuration needed
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up integration from a config entry."""
    # Store entry data
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = entry.data

    # Forward setup to sensor and number platforms
    for platform in PLATFORMS:
        hass.async_create_task(
            hass.config_entries.async_forward_entry_setup(entry, platform)  # type: ignore
        )

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)  # type: ignore
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
