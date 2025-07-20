import pytest
from homeassistant.core import HomeAssistant, ServiceCall

from custom_components.dynamic_energy_calculator.services import (
    _handle_reset_all,
    _handle_reset_sensors,
    _handle_set_value,
)
from custom_components.dynamic_energy_calculator.const import DOMAIN
from custom_components.dynamic_energy_calculator import (
    async_setup,
    async_setup_entry,
    async_unload_entry,
)
from pytest_homeassistant_custom_component.common import MockConfigEntry
from custom_components.dynamic_energy_calculator.sensor import BaseUtilitySensor


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

        def reset(self):
            called["reset"] = True

        def set_value(self, value):
            called["set"] = value

    hass.data[DOMAIN] = {"entities": {"dynamic_energy_calculator.test": Dummy()}}
    hass.states.async_set("dynamic_energy_calculator.test", 1)

    def ids(prefix=None):
        if prefix == f"{DOMAIN}.":
            return ["dynamic_energy_calculator.test"]
        return []

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        hass.states.__class__, "async_entity_ids", lambda self, prefix=None: ids(prefix)
    )

    await _handle_reset_all(ServiceCall(hass, DOMAIN, "reset_all_meters", {}))
    assert called["reset"]

    called["reset"] = False
    await _handle_reset_sensors(
        ServiceCall(
            hass,
            DOMAIN,
            "reset_selected_meters",
            {"entity_ids": ["dynamic_energy_calculator.test"]},
        )
    )
    assert called["reset"]

    await _handle_set_value(
        ServiceCall(
            hass,
            DOMAIN,
            "set_meter_value",
            {"entity_id": "dynamic_energy_calculator.test", "value": 5},
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
