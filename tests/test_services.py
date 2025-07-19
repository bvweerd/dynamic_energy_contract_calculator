import pytest
from homeassistant.core import HomeAssistant, ServiceCall

from custom_components.dynamic_energy_calculator.services import (
    async_register_services,
    _handle_reset_all,
    _handle_reset_sensors,
    _handle_set_value,
)
from custom_components.dynamic_energy_calculator.const import DOMAIN


async def test_service_registration(hass: HomeAssistant):
    await async_register_services(hass)
    assert hass.services.has_service(DOMAIN, "reset_all_meters")
    assert hass.services.has_service(DOMAIN, "reset_selected_meters")
    assert hass.services.has_service(DOMAIN, "set_meter_value")


async def test_service_handlers(hass: HomeAssistant):
    called = {
        "reset": False,
        "set": False,
    }

    class Dummy:
        async def async_reset(self):
            called["reset"] = True

        async def async_set_value(self, value):
            called["set"] = value

    hass.data[DOMAIN] = {"entities": {"dynamic_energy_calculator.test": Dummy()}}
    hass.states.async_set("dynamic_energy_calculator.test", 1)

    def ids(prefix=None):
        if prefix == f"{DOMAIN}.":
            return ["dynamic_energy_calculator.test"]
        return []

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(hass.states.__class__, "async_entity_ids", lambda self, prefix=None: ids(prefix))

    await _handle_reset_all(ServiceCall(hass, DOMAIN, "reset_all_meters", {}))
    assert called["reset"]

    called["reset"] = False
    await _handle_reset_sensors(
        ServiceCall(hass, DOMAIN, "reset_selected_meters", {"entity_ids": ["dynamic_energy_calculator.test"]})
    )
    assert called["reset"]

    await _handle_set_value(
        ServiceCall(hass, DOMAIN, "set_meter_value", {"entity_id": "dynamic_energy_calculator.test", "value": 5})
    )
    assert called["set"] == 5
