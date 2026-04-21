import pytest
from unittest.mock import AsyncMock
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.config_entries import ConfigEntryState

from custom_components.dynamic_energy_contract_calculator.services import (
    _handle_reset_all,
    _handle_reset_sensors,
    _handle_set_netting,
    _handle_set_netting_value,
    _handle_set_value,
)
from custom_components.dynamic_energy_contract_calculator.const import (
    CONF_PRICE_SETTINGS,
    DOMAIN,
)
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


def _make_loaded_entry_with_entities(
    hass: HomeAssistant, entities: dict
) -> MockConfigEntry:
    """Create a loaded MockConfigEntry with RuntimeData entities."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, entry_id="svc-test-1")
    entry.add_to_hass(hass)
    hass.data.setdefault(DOMAIN, {})
    entry.runtime_data = RuntimeData(entities=entities)
    # Mark as loaded so service handlers process it
    object.__setattr__(entry, "state", ConfigEntryState.LOADED)
    return entry


async def test_service_registration(hass: HomeAssistant):
    from custom_components.dynamic_energy_contract_calculator.services import (
        async_register_services,
        async_unregister_services,
    )

    await async_setup(hass, {})
    await async_register_services(hass)
    assert hass.services.has_service(DOMAIN, "reset_all_meters")
    assert hass.services.has_service(DOMAIN, "reset_selected_meters")
    assert hass.services.has_service(DOMAIN, "set_meter_value")
    assert hass.services.has_service(DOMAIN, "set_netting")
    assert hass.services.has_service(DOMAIN, "set_netting_value")

    await async_unregister_services(hass)
    assert not hass.services.has_service(DOMAIN, "reset_all_meters")
    assert not hass.services.has_service(DOMAIN, "set_netting")


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


async def test_service_handlers_skip_non_loaded_or_missing_runtime(hass: HomeAssistant):
    called = {"reset": 0, "set": 0}

    class Dummy(BaseUtilitySensor):
        def __init__(self):
            super().__init__("Test", "uid", "€", None, "mdi:flash", True)
            self.hass = hass

        async def async_reset(self):
            called["reset"] += 1

        async def async_set_value(self, value):
            called["set"] += value

    dummy = Dummy()
    loaded = _make_loaded_entry_with_entities(hass, {"sensor.valid": dummy})
    unloaded = MockConfigEntry(domain=DOMAIN, data={}, entry_id="svc-test-2")
    unloaded.add_to_hass(hass)
    object.__setattr__(unloaded, "state", ConfigEntryState.SETUP_ERROR)
    missing_runtime = MockConfigEntry(domain=DOMAIN, data={}, entry_id="svc-test-3")
    missing_runtime.add_to_hass(hass)
    object.__setattr__(missing_runtime, "state", ConfigEntryState.LOADED)

    await _handle_reset_all(ServiceCall(hass, DOMAIN, "reset_all_meters", {}))
    await _handle_reset_sensors(
        ServiceCall(
            hass,
            DOMAIN,
            "reset_selected_meters",
            {"entity_ids": ["sensor.valid", "sensor.missing"]},
        )
    )
    await _handle_set_value(
        ServiceCall(
            hass,
            DOMAIN,
            "set_meter_value",
            {"entity_id": "sensor.valid", "value": 2},
        )
    )

    assert loaded.runtime_data.entities["sensor.valid"] is dummy
    assert called == {"reset": 2, "set": 2}


async def test_service_reset_all_resets_netting_tracker(hass: HomeAssistant):
    tracker = type("Tracker", (), {"async_reset_all": AsyncMock()})()
    entry = _make_loaded_entry_with_entities(hass, {})
    entry.runtime_data.netting_tracker = tracker

    await _handle_reset_all(ServiceCall(hass, DOMAIN, "reset_all_meters", {}))

    tracker.async_reset_all.assert_awaited_once()


async def test_service_set_netting_updates_loaded_entries(hass: HomeAssistant):
    entry_options = MockConfigEntry(
        domain=DOMAIN,
        data={},
        options={CONF_PRICE_SETTINGS: {"vat_percentage": 21.0}},
        entry_id="netting-options",
    )
    entry_options.add_to_hass(hass)
    object.__setattr__(entry_options, "state", ConfigEntryState.LOADED)

    entry_data = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_PRICE_SETTINGS: {"vat_percentage": 9.0}},
        options={},
        entry_id="netting-data",
    )
    entry_data.add_to_hass(hass)
    object.__setattr__(entry_data, "state", ConfigEntryState.LOADED)

    unloaded = MockConfigEntry(domain=DOMAIN, data={}, options={}, entry_id="unloaded")
    unloaded.add_to_hass(hass)
    object.__setattr__(unloaded, "state", ConfigEntryState.NOT_LOADED)

    updates = []
    reloads = []

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            hass.config_entries,
            "async_update_entry",
            lambda entry, **kwargs: updates.append((entry.entry_id, kwargs["options"])),
        )

        async def reload(entry_id):
            reloads.append(entry_id)
            return True

        mp.setattr(hass.config_entries, "async_reload", reload)

        await _handle_set_netting(
            ServiceCall(hass, DOMAIN, "set_netting", {"enabled": True})
        )

    assert updates == [
        (
            "netting-options",
            {CONF_PRICE_SETTINGS: {"vat_percentage": 21.0, "netting_enabled": True}},
        ),
        (
            "netting-data",
            {CONF_PRICE_SETTINGS: {"vat_percentage": 9.0, "netting_enabled": True}},
        ),
    ]
    assert reloads == ["netting-options", "netting-data"]


async def test_service_set_netting_value_uses_tracker_when_present(hass: HomeAssistant):
    tracker = type("Tracker", (), {"async_set_net_consumption": AsyncMock()})()
    entry = _make_loaded_entry_with_entities(hass, {})
    entry.runtime_data.netting_tracker = tracker

    missing_runtime = MockConfigEntry(domain=DOMAIN, data={}, entry_id="svc-test-4")
    missing_runtime.add_to_hass(hass)
    object.__setattr__(missing_runtime, "state", ConfigEntryState.LOADED)

    await _handle_set_netting_value(
        ServiceCall(hass, DOMAIN, "set_netting_value", {"value": 4.25})
    )

    tracker.async_set_net_consumption.assert_awaited_once_with(4.25)


async def test_service_set_value_skips_unloaded_and_missing_runtime(
    hass: HomeAssistant,
):
    loaded = MockConfigEntry(domain=DOMAIN, data={}, entry_id="svc-loaded")
    loaded.add_to_hass(hass)
    loaded.runtime_data = RuntimeData(entities={})
    object.__setattr__(loaded, "state", ConfigEntryState.LOADED)

    missing_runtime = MockConfigEntry(domain=DOMAIN, data={}, entry_id="svc-no-runtime")
    missing_runtime.add_to_hass(hass)
    object.__setattr__(missing_runtime, "state", ConfigEntryState.LOADED)

    unloaded = MockConfigEntry(domain=DOMAIN, data={}, entry_id="svc-unloaded")
    unloaded.add_to_hass(hass)
    object.__setattr__(unloaded, "state", ConfigEntryState.SETUP_ERROR)

    await _handle_set_value(
        ServiceCall(
            hass,
            DOMAIN,
            "set_meter_value",
            {"entity_id": "sensor.missing", "value": 1},
        )
    )


async def test_service_set_netting_value_skips_unloaded_entries(hass: HomeAssistant):
    unloaded = MockConfigEntry(domain=DOMAIN, data={}, entry_id="svc-netting-unloaded")
    unloaded.add_to_hass(hass)
    object.__setattr__(unloaded, "state", ConfigEntryState.SETUP_ERROR)

    await _handle_set_netting_value(
        ServiceCall(hass, DOMAIN, "set_netting_value", {"value": 1.0})
    )


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
