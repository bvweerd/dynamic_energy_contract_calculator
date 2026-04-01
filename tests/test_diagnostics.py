from unittest.mock import MagicMock

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dynamic_energy_contract_calculator import RuntimeData
from custom_components.dynamic_energy_contract_calculator.const import (
    CONF_SOURCE_TYPE,
    CONF_SOURCES,
    DOMAIN,
    SOURCE_TYPE_CONSUMPTION,
    SUBENTRY_TYPE_SOURCE,
)


def _make_subentry(source_type: str, sources: list[str]) -> MagicMock:
    """Return a mock sub-entry for the given source type and sensor list."""
    subentry = MagicMock()
    subentry.subentry_type = SUBENTRY_TYPE_SOURCE
    subentry.data = {CONF_SOURCE_TYPE: source_type, CONF_SOURCES: sources}
    subentry.subentry_id = "test-sub-1"
    subentry.title = source_type
    return subentry


async def test_diagnostics_redaction_and_structure(hass: HomeAssistant):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={},
        options={},
    )
    entry.add_to_hass(hass)
    entry._subentries = {
        "test-sub-1": _make_subentry(SOURCE_TYPE_CONSUMPTION, ["sensor.energy"])
    }
    entry.runtime_data = RuntimeData()
    hass.states.async_set("sensor.energy", 1, {"attr": "val"})

    calls = []

    def _redact(data, to_redact):
        calls.append((data, to_redact))
        return data

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "custom_components.dynamic_energy_contract_calculator.diagnostics.async_redact_data",
            _redact,
        )
        from custom_components.dynamic_energy_contract_calculator import diagnostics

        result = await diagnostics.async_get_config_entry_diagnostics(hass, entry)

    # Two fixed redact calls (entry data/options) + one per source state
    assert len(calls) >= 2
    assert result["entry"]["data"] == dict(entry.data)
    assert result["entry"]["options"] == dict(entry.options)
    assert result["sources"][0]["entity_id"] == "sensor.energy"
    assert result["sources"][0]["state"]["state"] == "1"
    assert result["sources"][0]["state"]["attributes"] == {"attr": "val"}
    assert result["netting"] == {"enabled": False}
    assert result["solar_bonus"] == {"enabled": False}


async def test_diagnostics_with_netting_tracker(hass: HomeAssistant):
    """Test diagnostics when netting tracker is active."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={})
    entry.add_to_hass(hass)
    entry._subentries = {}

    netting_tracker = MagicMock()
    netting_tracker.net_consumption_kwh = 10.5
    netting_tracker.tax_balance_per_sensor = {"sensor.energy": 1.5}

    entry.runtime_data = RuntimeData(netting_tracker=netting_tracker)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "custom_components.dynamic_energy_contract_calculator.diagnostics.async_redact_data",
            lambda data, keys: data,
        )
        from custom_components.dynamic_energy_contract_calculator import diagnostics

        result = await diagnostics.async_get_config_entry_diagnostics(hass, entry)

    assert result["netting"]["enabled"] is True
    assert result["netting"]["net_consumption_kwh"] == 10.5


async def test_diagnostics_with_solar_bonus_tracker(hass: HomeAssistant):
    """Test diagnostics when solar bonus tracker is active."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={})
    entry.add_to_hass(hass)
    entry._subentries = {}

    solar_tracker = MagicMock()
    solar_tracker.year_production_kwh = 250.0
    solar_tracker.total_bonus_euro = 12.5

    entry.runtime_data = RuntimeData(solar_bonus_tracker=solar_tracker)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "custom_components.dynamic_energy_contract_calculator.diagnostics.async_redact_data",
            lambda data, keys: data,
        )
        from custom_components.dynamic_energy_contract_calculator import diagnostics

        result = await diagnostics.async_get_config_entry_diagnostics(hass, entry)

    assert result["solar_bonus"]["enabled"] is True
    assert result["solar_bonus"]["year_production_kwh"] == 250.0
    assert result["solar_bonus"]["total_bonus_euro"] == 12.5
