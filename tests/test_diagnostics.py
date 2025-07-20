from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dynamic_energy_calculator.const import (
    CONF_CONFIGS,
    CONF_SOURCE_TYPE,
    CONF_SOURCES,
    DOMAIN,
    SOURCE_TYPE_CONSUMPTION,
)


async def test_diagnostics_redaction_and_structure(hass: HomeAssistant):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_CONFIGS: [
                {
                    CONF_SOURCE_TYPE: SOURCE_TYPE_CONSUMPTION,
                    CONF_SOURCES: ["sensor.energy"],
                }
            ]
        },
        options={},
    )
    entry.add_to_hass(hass)
    hass.states.async_set("sensor.energy", 1, {"attr": "val"})

    calls = []

    def _redact(data, to_redact):
        calls.append((data, to_redact))
        return data

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "custom_components.dynamic_energy_calculator.diagnostics.async_redact_data",
            _redact,
        )
        from custom_components.dynamic_energy_calculator import diagnostics

        result = await diagnostics.async_get_config_entry_diagnostics(hass, entry)

    assert len(calls) == 3
    assert result["entry"]["data"] == entry.data
    assert result["entry"]["options"] == entry.options
    assert result["sources"][0]["entity_id"] == "sensor.energy"
    assert result["sources"][0]["state"]["state"] == "1"
    assert result["sources"][0]["state"]["attributes"] == {"attr": "val"}
