import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dynamic_energy_contract_calculator import (
    RuntimeData,
    async_migrate_entry,
    async_setup,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.dynamic_energy_contract_calculator.const import (
    CONF_CONFIGS,
    CONF_PRICE_SETTINGS,
    CONF_SOURCE_TYPE,
    CONF_SOURCES,
    DOMAIN,
    PLATFORMS,
    SOURCE_TYPE_CONSUMPTION,
    SOURCE_TYPE_PRODUCTION,
    SUBENTRY_TYPE_SOURCE,
)
from custom_components.dynamic_energy_contract_calculator.entity import (
    BaseUtilitySensor,
)


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
            "custom_components.dynamic_energy_contract_calculator.services.async_register_services",
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


async def test_migrate_entry_v1_to_v2_creates_subentries(hass: HomeAssistant) -> None:
    """Migration from v1 moves CONF_CONFIGS to sub-entries and bumps version."""
    old_data = {
        CONF_CONFIGS: [
            {CONF_SOURCE_TYPE: SOURCE_TYPE_CONSUMPTION, CONF_SOURCES: ["sensor.elec"]},
            {CONF_SOURCE_TYPE: SOURCE_TYPE_PRODUCTION, CONF_SOURCES: ["sensor.solar"]},
        ],
        CONF_PRICE_SETTINGS: {"vat_percentage": 21.0},
    }
    entry = MockConfigEntry(domain=DOMAIN, data=old_data, version=1, entry_id="migtest")
    entry.add_to_hass(hass)

    result = await async_migrate_entry(hass, entry)

    assert result is True
    assert entry.version == 2
    assert CONF_CONFIGS not in entry.data
    assert entry.data[CONF_PRICE_SETTINGS] == {"vat_percentage": 21.0}

    subentries = list(entry.subentries.values())
    assert len(subentries) == 2
    source_types = {se.data[CONF_SOURCE_TYPE] for se in subentries}
    assert source_types == {SOURCE_TYPE_CONSUMPTION, SOURCE_TYPE_PRODUCTION}
    for se in subentries:
        assert se.subentry_type == SUBENTRY_TYPE_SOURCE
        assert CONF_SOURCES in se.data


async def test_migrate_entry_v1_to_v2_empty_configs(hass: HomeAssistant) -> None:
    """Migration with empty CONF_CONFIGS creates no sub-entries."""
    old_data = {CONF_CONFIGS: [], CONF_PRICE_SETTINGS: {}}
    entry = MockConfigEntry(
        domain=DOMAIN, data=old_data, version=1, entry_id="migtest2"
    )
    entry.add_to_hass(hass)

    result = await async_migrate_entry(hass, entry)

    assert result is True
    assert entry.version == 2
    assert CONF_CONFIGS not in entry.data
    assert len(entry.subentries) == 0


async def test_migrate_entry_unknown_version_returns_false(hass: HomeAssistant) -> None:
    """Migration returns False for unsupported versions."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, version=99, entry_id="migtest3")
    entry.add_to_hass(hass)

    result = await async_migrate_entry(hass, entry)

    assert result is False


async def test_async_unload_clears_runtime_data(hass: HomeAssistant):
    entry = MockConfigEntry(domain=DOMAIN, data={}, entry_id="1")
    entry.add_to_hass(hass)

    dummy = BaseUtilitySensor("Test", "uid", "€", None, "mdi:flash", True)
    dummy.hass = hass

    hass.data[DOMAIN] = {"services_registered": True}

    # Set up runtime_data on the entry as async_setup_entry would do
    entry.runtime_data = RuntimeData(entities={"test_entity": dummy})

    with pytest.MonkeyPatch.context() as mp:

        async def unload(entry_to_unload, platforms):
            return True

        mp.setattr(hass.config_entries, "async_unload_platforms", unload)
        result = await async_unload_entry(hass, entry)

    assert result
    # Entry should be removed from hass.data
    assert entry.entry_id not in hass.data[DOMAIN]


async def test_async_unload_cleans_tracker_maps_and_keeps_services_for_other_entries(
    hass: HomeAssistant,
):
    entry = MockConfigEntry(domain=DOMAIN, data={}, entry_id="entry-1")
    other = MockConfigEntry(domain=DOMAIN, data={}, entry_id="entry-2")
    entry.add_to_hass(hass)
    other.add_to_hass(hass)
    hass.data[DOMAIN] = {
        "services_registered": True,
        "netting": {"entry-1": object()},
        "solar_bonus": {"entry-1": object()},
    }

    with pytest.MonkeyPatch.context() as mp:

        async def unload(entry_to_unload, platforms):
            return True

        async def unregister_services(hass_arg):
            raise AssertionError("services should stay registered")

        mp.setattr(hass.config_entries, "async_unload_platforms", unload)
        mp.setattr(
            "custom_components.dynamic_energy_contract_calculator.async_unregister_services",
            unregister_services,
        )

        result = await async_unload_entry(hass, entry)

    assert result is True
    assert "netting" not in hass.data[DOMAIN]
    assert "solar_bonus" not in hass.data[DOMAIN]
    assert hass.data[DOMAIN]["services_registered"] is True
