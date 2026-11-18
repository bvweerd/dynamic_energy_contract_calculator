"""Tests for the device registry helpers on the pre-2026.10 multi-entry model."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from custom_components.dynamic_energy_contract_calculator.device_compat import (
    device_in_main_entry,
    device_subentry_ids,
    find_entry_device,
    move_device_to_subentry,
    remove_device_from_entry,
)


def _legacy_device(subentries: dict) -> SimpleNamespace:
    """A device without config_entry_id, as before HA 2026.10."""
    return SimpleNamespace(
        id="dev-1",
        config_entries=set(subentries),
        config_entries_subentries=subentries,
    )


async def test_legacy_subentry_lookup() -> None:
    device = _legacy_device({"entry": {None, "sub-a"}})
    assert device_subentry_ids(device, "entry") == {None, "sub-a"}
    assert device_subentry_ids(device, "other") == set()
    assert device_in_main_entry(device, "entry")


async def test_legacy_move_links_new_subentry_before_dropping_old() -> None:
    dev_reg = MagicMock()
    device = _legacy_device({"entry": {None, "sub-a"}})

    move_device_to_subentry(dev_reg, device, "entry", "sub-b")

    calls = dev_reg.async_update_device.call_args_list
    assert calls[0].kwargs == {
        "add_config_entry_id": "entry",
        "add_config_subentry_id": "sub-b",
    }
    removed = {call.kwargs["remove_config_subentry_id"] for call in calls[1:]}
    assert removed == {None, "sub-a"}


async def test_legacy_remove_keeps_device_shared_with_other_entries() -> None:
    dev_reg = MagicMock()
    shared = _legacy_device({"entry": {"sub-a"}, "other": {None}})
    remove_device_from_entry(dev_reg, shared, "entry")
    dev_reg.async_update_device.assert_called_once_with(
        "dev-1", remove_config_entry_id="entry"
    )
    dev_reg.async_remove_device.assert_not_called()

    own = _legacy_device({"entry": {"sub-a"}})
    remove_device_from_entry(dev_reg, own, "entry")
    dev_reg.async_remove_device.assert_called_once_with("dev-1")


async def test_find_entry_device_without_per_entry_lookup() -> None:
    dev_reg = SimpleNamespace(async_get_device=MagicMock(return_value="device"))
    assert find_entry_device(dev_reg, ("domain", "id"), "entry") == "device"
    dev_reg.async_get_device.assert_called_once_with(identifiers={("domain", "id")})
