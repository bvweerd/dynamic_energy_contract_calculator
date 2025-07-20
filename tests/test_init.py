import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dynamic_energy_calculator import (
    async_setup,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.dynamic_energy_calculator.const import DOMAIN, PLATFORMS
from custom_components.dynamic_energy_calculator.entity import BaseUtilitySensor
from custom_components.dynamic_energy_calculator.sensor import UTILITY_ENTITIES


async def test_async_setup(hass: HomeAssistant):
    result = await async_setup(hass, {})
    assert result
    assert DOMAIN in hass.data


async def test_async_setup_and_unload_entry(hass: HomeAssistant):
    entry = MockConfigEntry(domain=DOMAIN, data={}, entry_id="1234")
    entry.add_to_hass(hass)

    await async_setup(hass, {})

    with pytest.MonkeyPatch.context() as mp:

        async def forward(entry_to_forward, platforms):
            assert entry_to_forward is entry
            assert platforms == PLATFORMS

        mp.setattr(hass.config_entries, "async_forward_entry_setups", forward)
        assert await async_setup_entry(hass, entry)

    assert hass.data[DOMAIN][entry.entry_id] == {}

    with pytest.MonkeyPatch.context() as mp:

        async def unload(entry_to_unload, platforms):
            assert entry_to_unload is entry
            assert platforms == PLATFORMS
            return True

        mp.setattr(hass.config_entries, "async_unload_platforms", unload)
        result = await async_unload_entry(hass, entry)

    assert result
    assert entry.entry_id not in hass.data[DOMAIN]


async def test_async_setup_entry_registers_services_when_missing(hass: HomeAssistant):
    entry = MockConfigEntry(domain=DOMAIN, data={}, entry_id="1")
    entry.add_to_hass(hass)

    hass.data[DOMAIN] = {}

    with pytest.MonkeyPatch.context() as mp:

        async def register_services(hass_arg):
            return None

        async def forward(entry_to_forward, platforms):
            return True

        mp.setattr(
            "custom_components.dynamic_energy_calculator.services.async_register_services",
            register_services,
        )
        mp.setattr(hass.config_entries, "async_forward_entry_setups", forward)
        assert await async_setup_entry(hass, entry)

    assert hass.data[DOMAIN]["services_registered"]


async def test_async_unload_entry_failure_keeps_data(hass: HomeAssistant):
    entry = MockConfigEntry(domain=DOMAIN, data={}, entry_id="1")
    entry.add_to_hass(hass)

    hass.data[DOMAIN] = {entry.entry_id: {}, "services_registered": True}

    with pytest.MonkeyPatch.context() as mp:

        async def unload(entry_to_unload, platforms):
            return False

        mp.setattr(hass.config_entries, "async_unload_platforms", unload)
        result = await async_unload_entry(hass, entry)

    assert not result
    assert entry.entry_id in hass.data[DOMAIN]
    assert hass.data[DOMAIN]["services_registered"]


async def test_async_unload_removes_utility_entities(hass: HomeAssistant):
    entry = MockConfigEntry(domain=DOMAIN, data={}, entry_id="1")
    entry.add_to_hass(hass)

    dummy = BaseUtilitySensor("Test", "uid", "€", None, "mdi:flash", True)
    dummy.hass = hass

    hass.data[DOMAIN] = {
        entry.entry_id: {},
        "services_registered": True,
        "entities": {"dynamic_energy_calculator.test": dummy},
    }
    UTILITY_ENTITIES.append(dummy)

    with pytest.MonkeyPatch.context() as mp:
        async def unload(entry_to_unload, platforms):
            return True

        mp.setattr(hass.config_entries, "async_unload_platforms", unload)
        result = await async_unload_entry(hass, entry)

    assert result
    assert dummy not in UTILITY_ENTITIES
    assert "entities" not in hass.data[DOMAIN]
