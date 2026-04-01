"""Diagnostics support for Dynamic Energy Contract Calculator."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_SOURCES, DOMAIN, SUBENTRY_TYPE_SOURCE

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
        "subentries": [
            {
                "subentry_id": se.subentry_id,
                "subentry_type": se.subentry_type,
                "title": se.title,
                "data": async_redact_data(dict(se.data), REDACT_CONFIG),
            }
            for se in entry.subentries.values()
        ],
        "sources": sources,
    }

    runtime = getattr(entry, "runtime_data", None)
    tracker = runtime.netting_tracker if runtime is not None else None
    if tracker:
        data["netting"] = {
            "enabled": True,
            "net_consumption_kwh": tracker.net_consumption_kwh,
            "tax_balance_per_sensor": tracker.tax_balance_per_sensor,
        }
    else:
        data["netting"] = {"enabled": False}

    solar_bonus_tracker = runtime.solar_bonus_tracker if runtime is not None else None
    if solar_bonus_tracker:
        data["solar_bonus"] = {
            "enabled": True,
            "year_production_kwh": solar_bonus_tracker.year_production_kwh,
            "total_bonus_euro": solar_bonus_tracker.total_bonus_euro,
        }
    else:
        data["solar_bonus"] = {"enabled": False}

    # Add binary sensor states
    binary_sensors = {}
    for state in hass.states.async_all("binary_sensor"):
        if state and (
            "solar_bonus_active" in state.entity_id.lower()
            or "production_price_positive" in state.entity_id.lower()
        ):
            sensor_name = state.entity_id.replace("binary_sensor.", "")
            binary_sensors[sensor_name] = async_redact_data(
                state.as_dict(), REDACT_STATE
            )

    if binary_sensors:
        data["binary_sensors"] = binary_sensors

    # Build sources from sub-entries
    for subentry in entry.subentries.values():
        if subentry.subentry_type == SUBENTRY_TYPE_SOURCE:
            for source in subentry.data.get(CONF_SOURCES, []):
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
