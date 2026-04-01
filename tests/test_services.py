import pytest
from homeassistant.core import HomeAssistant, ServiceCall

from custom_components.dynamic_energy_contract_calculator.services import (
    _handle_reset_all,
    _handle_reset_sensors,
    _handle_set_value,
)
from custom_components.dynamic_energy_contract_calculator.const import DOMAIN
from custom_components.dynamic_energy_contract_calculator import (
    RuntimeData,
    async_setup,
    async_setup_entry,
    async_unload_entry,
)
from pytest_homeassistant_custom_component.common import MockConfigEntry
from custom_components.dynamic_energy_contract_calculator.entity import (
    BaseUtilitySensor,
)


def _make_loaded_entry_with_entities(hass: HomeAssistant, entities: dict) -> MockConfigEntry:
    """Create a loaded MockConfigEntry with RuntimeData entities."""
    from homeassistant.config_entries import ConfigEntryState

    entry = MockConfigEntry(domain=DOMAIN, data={}, entry_id="svc-test-1")
    entry.add_to_hass(hass)
    hass.data.setdefault(DOMAIN, {})
    entry.runtime_data = RuntimeData(entities=entities)
    # Mark as loaded so service handlers process it
    entry._state = ConfigEntryState.LOADED
    return entry


async def test_service_registration(hass: HomeAssistant):
    await async_setup(hass, {})
    assert hass.services.has_service(DOMAIN, "reset_all_meters")
    assert hass.services.has_service(DOMAIN, "reset_selected_meters")
    assert hass.services.has_service(DOMAIN, "set_meter_value")


async def test_service_handlers(hass: HomeAssistant):
    called = {
        "reset": False,
        "set": False,
    }

    class Dummy(BaseUtilitySensor):
        def __init__(self):
            super().__init__("Test", "uid", "€", None, "mdi:flash", True)
            self.hass = hass
            self.async_write_ha_state = lambda *a, **k: None

        async def async_reset(self):
            called["reset"] = True

        async def async_set_value(self, value):
            called["set"] = value

    entity_id = "dynamic_energy_contract_calculator.test"
    dummy = Dummy()
    _make_loaded_entry_with_entities(hass, {entity_id: dummy})
    hass.states.async_set(entity_id, 1)

    await _handle_reset_all(ServiceCall(hass, DOMAIN, "reset_all_meters", {}))
    assert called["reset"]

    called["reset"] = False
    await _handle_reset_sensors(
        ServiceCall(
            hass,
            DOMAIN,
            "reset_selected_meters",
            {"entity_ids": [entity_id]},
        )
    )
    assert called["reset"]

    await _handle_set_value(
        ServiceCall(
            hass,
            DOMAIN,
            "set_meter_value",
            {"entity_id": entity_id, "value": 5},
        )
    )
    assert called["set"] == 5


async def test_services_removed_after_unload(hass: HomeAssistant):
    entry = MockConfigEntry(domain=DOMAIN, data={}, entry_id="1")
    entry.add_to_hass(hass)
    await async_setup(hass, {})

    with pytest.MonkeyPatch.context() as mp:

        async def forward(entry_to_forward, platforms):
            return True

        mp.setattr(hass.config_entries, "async_forward_entry_setups", forward)
        await async_setup_entry(hass, entry)

    assert hass.services.has_service(DOMAIN, "reset_all_meters")

    with pytest.MonkeyPatch.context() as mp:

        async def unload(entry_to_unload, platforms):
            return True

        mp.setattr(hass.config_entries, "async_unload_platforms", unload)
        assert await async_unload_entry(hass, entry)

    assert not hass.services.has_service(DOMAIN, "reset_all_meters")
