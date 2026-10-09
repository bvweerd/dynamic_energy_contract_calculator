import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntryType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dynamic_energy_contract_calculator import (
    RuntimeData,
    async_migrate_entry,
    async_remove_entry,
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


def _subentries_for(device: dr.DeviceEntry, entry_id: str) -> set[str | None]:
    """Return the device's subentries under entry_id, on any HA release.

    Home Assistant 2026.10 gives a device a single config entry and subentry and
    deprecates config_entries_subentries; older releases only have the latter.
    """
    if hasattr(device, "config_entry_id"):
        if device.config_entry_id != entry_id:
            return set()
        return {device.config_subentry_id}
    return device.config_entries_subentries.get(entry_id, set())


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


async def test_migrate_entry_v1_to_v2_migrates_registries(hass: HomeAssistant) -> None:
    """Migration moves existing entity/device registry entries to their sub-entry."""
    sensor_id = "sensor.elec"
    base_id = sensor_id.replace(".", "_")
    old_data = {
        CONF_CONFIGS: [
            {CONF_SOURCE_TYPE: SOURCE_TYPE_CONSUMPTION, CONF_SOURCES: [sensor_id]},
        ],
        CONF_PRICE_SETTINGS: {},
    }
    entry = MockConfigEntry(domain=DOMAIN, data=old_data, version=1, entry_id="migreg")
    entry.add_to_hass(hass)

    # Pre-populate device registry with old entry (no subentry)
    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, base_id)},
        entry_type=DeviceEntryType.SERVICE,
    )
    # Verify device starts under main entry (no subentry)
    assert None in _subentries_for(device, entry.entry_id)

    # Pre-populate entity registry with old entity (no subentry)
    ent_reg = er.async_get(hass)
    entity_entry = ent_reg.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{DOMAIN}_{base_id}_cost_total",
        config_entry=entry,
        device_id=device.id,
    )
    assert entity_entry.config_subentry_id is None

    result = await async_migrate_entry(hass, entry)
    assert result is True

    subentries = list(entry.subentries.values())
    assert len(subentries) == 1
    expected_subentry_id = subentries[0].subentry_id

    # Entity registry entry must now point to the sub-entry
    updated_entity = ent_reg.async_get(entity_entry.entity_id)
    assert updated_entity is not None
    assert updated_entity.config_subentry_id == expected_subentry_id

    # Device registry must have sub-entry association and no main-entry (None) association
    updated_device = dev_reg.async_get(device.id)
    assert updated_device is not None
    subentries_for_entry = _subentries_for(updated_device, entry.entry_id)
    assert expected_subentry_id in subentries_for_entry
    assert None not in subentries_for_entry


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


async def test_async_remove_entry_deletes_store_data(hass: HomeAssistant) -> None:
    """Deleting a config entry removes persistent Store files for netting and solar bonus."""
    from unittest.mock import patch

    entry = MockConfigEntry(domain=DOMAIN, data={}, entry_id="remove-me")
    entry.add_to_hass(hass)

    removed_keys: list[str] = []

    class FakeStore:
        def __init__(self, hass, version, key, **kwargs):
            self._key = key

        async def async_remove(self):
            removed_keys.append(self._key)

    with patch(
        "custom_components.dynamic_energy_contract_calculator.Store",
        FakeStore,
    ):
        await async_remove_entry(hass, entry)

    assert any("netting" in k for k in removed_keys)
    assert any("solar_bonus" in k for k in removed_keys)
    assert all("remove-me" in k for k in removed_keys)
