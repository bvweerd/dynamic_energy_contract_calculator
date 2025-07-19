import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dynamic_energy_calculator import (
    async_setup,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.dynamic_energy_calculator.const import DOMAIN, PLATFORMS


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
