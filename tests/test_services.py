import pytest
from homeassistant.core import HomeAssistant

from custom_components.dynamic_energy_contract_calculator.const import DOMAIN
from custom_components.dynamic_energy_contract_calculator import (
    async_setup,
    async_setup_entry,
    async_unload_entry,
)
from pytest_homeassistant_custom_component.common import MockConfigEntry
from custom_components.dynamic_energy_contract_calculator.entity import (
    BaseUtilitySensor,
)


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

    # Register services first
    await async_setup(hass, {})

    hass.data[DOMAIN] = {
        "entities": {"dynamic_energy_contract_calculator.test": Dummy()}
    }
    hass.states.async_set("dynamic_energy_contract_calculator.test", 1)

    await hass.services.async_call(DOMAIN, "reset_all_meters", {}, blocking=True)
    assert called["reset"]

    called["reset"] = False
    await hass.services.async_call(
        DOMAIN,
        "reset_selected_meters",
        {"entity_ids": ["dynamic_energy_contract_calculator.test"]},
        blocking=True,
    )
    assert called["reset"]

    await hass.services.async_call(
        DOMAIN,
        "set_meter_value",
        {"entity_id": "dynamic_energy_contract_calculator.test", "value": 5},
        blocking=True,
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


async def test_service_handlers_with_netting_trackers(hass: HomeAssistant):
    """Test that service handlers also reset netting trackers."""
    from unittest.mock import MagicMock, AsyncMock

    called = {
        "reset": False,
        "netting_reset": False,
    }

    class Dummy(BaseUtilitySensor):
        def __init__(self):
            super().__init__("Test", "uid", "€", None, "mdi:flash", True)
            self.hass = hass
            self.async_write_ha_state = lambda *a, **k: None

        async def async_reset(self):
            called["reset"] = True

    # Mock netting tracker
    mock_tracker = MagicMock()
    mock_tracker.async_reset_all = AsyncMock(
        side_effect=lambda: called.update(netting_reset=True)
    )

    # Register services first
    await async_setup(hass, {})

    hass.data[DOMAIN] = {
        "entities": {"dynamic_energy_contract_calculator.test": Dummy()},
        "netting": {"entry1": mock_tracker},
    }
    hass.states.async_set("dynamic_energy_contract_calculator.test", 1)

    await hass.services.async_call(DOMAIN, "reset_all_meters", {}, blocking=True)
    assert called["reset"]
    assert called["netting_reset"]

    # Reset flags
    called["reset"] = False
    called["netting_reset"] = False

    await hass.services.async_call(
        DOMAIN,
        "reset_selected_meters",
        {"entity_ids": ["dynamic_energy_contract_calculator.test"]},
        blocking=True,
    )
    assert called["reset"]
    assert called["netting_reset"]
