"""Device registry helpers that work across Home Assistant releases.

Home Assistant 2026.10 made a device belong to exactly one config entry and
subentry (``config_entry_id``/``config_subentry_id``). It deprecated the
multi-entry ``config_entries_subentries`` view and the ``add_``/``remove_``
update parameters, which raise in tests and stop working in 2027.8. Older
releases only have the multi-entry API, so both are supported here.
"""

from __future__ import annotations

from homeassistant.helpers import device_registry as dr


def _single_owner(device: dr.DeviceEntry) -> bool:
    """Return whether the registry uses the single config entry device model."""
    return hasattr(device, "config_entry_id")


def device_in_main_entry(device: dr.DeviceEntry, entry_id: str) -> bool:
    """Return whether the device is linked to the entry outside any subentry."""
    if _single_owner(device):
        return device.config_entry_id == entry_id and device.config_subentry_id is None
    return None in device.config_entries_subentries.get(entry_id, set())


def move_device_to_subentry(
    dev_reg: dr.DeviceRegistry,
    device: dr.DeviceEntry,
    entry_id: str,
    subentry_id: str,
) -> None:
    """Move a device from the main config entry to one of its subentries."""
    if _single_owner(device):
        dev_reg.async_update_device(device.id, new_config_subentry_id=subentry_id)
        return
    # The multi-entry model links the subentry first and then drops the
    # main-entry link, so the device is never left without an owner.
    dev_reg.async_update_device(
        device.id,
        add_config_entry_id=entry_id,
        add_config_subentry_id=subentry_id,
    )
    dev_reg.async_update_device(
        device.id,
        remove_config_entry_id=entry_id,
        remove_config_subentry_id=None,
    )
