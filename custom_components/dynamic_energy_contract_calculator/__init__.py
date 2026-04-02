# custom_components/dynamic_energy_contract_calculator/__init__.py
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from types import MappingProxyType

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

from .const import CONF_CONFIGS, CONF_SOURCE_TYPE, CONF_SOURCES, DOMAIN, PLATFORMS, SOURCE_TYPE_CONSUMPTION, SUBENTRY_TYPE_SOURCE
from .services import async_register_services, async_unregister_services

if TYPE_CHECKING:
    from .entity import BaseUtilitySensor
    from .netting import NettingTracker
    from .solar_bonus import SolarBonusTracker

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


@dataclass
class RuntimeData:
    """Runtime data stored per config entry."""

    entities: dict[str, BaseUtilitySensor] = field(default_factory=dict)
    netting_tracker: NettingTracker | None = None
    solar_bonus_tracker: SolarBonusTracker | None = None


type DynamicEnergyConfigEntry = ConfigEntry[RuntimeData]


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up the base integration (no YAML)."""
    hass.data.setdefault(DOMAIN, {})
    _LOGGER.info("Initialized Dynamic Energy Contract Calculator")
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate config entry to current version."""
    _LOGGER.debug("Migrating from version %s", entry.version)

    if entry.version == 1:
        # Migrate: move CONF_CONFIGS list to sub-entries
        configs: list[dict[str, Any]] = entry.data.get(CONF_CONFIGS, [])
        _LOGGER.info(
            "Migrating entry %s from v1 to v2: creating %d sub-entries",
            entry.entry_id,
            len(configs),
        )

        # Build new entry data without CONF_CONFIGS
        new_data = {k: v for k, v in entry.data.items() if k != CONF_CONFIGS}

        # Update entry to version 2 first
        hass.config_entries.async_update_entry(entry, data=new_data, version=2)

        # Create a sub-entry for each configuration block
        for config in configs:
            source_type = config.get(CONF_SOURCE_TYPE, SOURCE_TYPE_CONSUMPTION)
            hass.config_entries.async_add_subentry(
                entry,
                ConfigSubentry(
                    subentry_type=SUBENTRY_TYPE_SOURCE,
                    title=source_type,
                    data=MappingProxyType({
                        CONF_SOURCE_TYPE: source_type,
                        CONF_SOURCES: config.get(CONF_SOURCES, []),
                    }),
                    unique_id=None,
                ),
            )
            _LOGGER.debug("Created sub-entry for source type: %s", source_type)

        _LOGGER.info("Migration to v2 complete for entry %s", entry.entry_id)
        return True

    _LOGGER.error("Cannot migrate from version %s", entry.version)
    return False


async def async_setup_entry(hass: HomeAssistant, entry: DynamicEnergyConfigEntry) -> bool:
    """Set up a config entry by forwarding to sensor & binary_sensor platforms."""
    _LOGGER.info("Setting up entry %s", entry.entry_id)

    hass.data.setdefault(DOMAIN, {})

    # Register services once across all entries
    if not hass.data[DOMAIN].get("services_registered"):
        await async_register_services(hass)
        hass.data[DOMAIN]["services_registered"] = True

    # Initialize per-entry runtime data
    entry.runtime_data = RuntimeData()

    entry.async_on_unload(entry.add_update_listener(_update_listener))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _LOGGER.debug("Forwarded entry %s to platforms %s", entry.entry_id, PLATFORMS)
    return True


async def _update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update by reloading the config entry."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry and its platforms."""
    _LOGGER.info("Unloading entry %s", entry.entry_id)
    unload_ok = bool(
        await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    )
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        _LOGGER.debug("Successfully unloaded entry %s", entry.entry_id)

        # Unregister services if no other entries remain
        remaining = [
            e for e in hass.config_entries.async_entries(DOMAIN)
            if e.entry_id != entry.entry_id
        ]
        if not remaining and hass.data[DOMAIN].get("services_registered"):
            await async_unregister_services(hass)
            hass.data[DOMAIN]["services_registered"] = False
    else:
        _LOGGER.warning("Failed to unload entry %s", entry.entry_id)
    return unload_ok
