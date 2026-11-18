"""Device registry helpers that work across Home Assistant releases.

Home Assistant 2026.10 made a device belong to exactly one config entry and
subentry (``config_entry_id``/``config_subentry_id``). It deprecated the
multi-entry ``config_entries_subentries`` view and the ``add_``/``remove_``
update parameters, which raise in tests and stop working in 2027.8. Older
releases only have the multi-entry API, so both are supported here.
"""

from __future__ import annotations

import logging

from homeassistant.helpers import device_registry as dr

_LOGGER = logging.getLogger(__name__)


def _single_owner(device: dr.DeviceEntry) -> bool:
    """Return whether the registry uses the single config entry device model."""
    return hasattr(device, "config_entry_id")


def find_entry_device(
    dev_reg: dr.DeviceRegistry, identifier: tuple[str, str], entry_id: str
) -> dr.DeviceEntry | None:
    """Return the entry's device with *identifier*, if any.

    async_get_device is deprecated because identifiers are no longer unique
    across config entries; the per-entry lookup exists from HA 2026.10.
    """
    get_by_identifier = getattr(dev_reg, "async_get_device_by_identifier", None)
    if get_by_identifier is not None:
        device: dr.DeviceEntry | None = get_by_identifier(identifier, entry_id)
        return device
    return dev_reg.async_get_device(identifiers={identifier})


def device_subentry_ids(device: dr.DeviceEntry, entry_id: str) -> set[str | None]:
    """Return the entry's subentries the device is linked to (None: main entry)."""
    if _single_owner(device):
        if device.config_entry_id != entry_id:
            return set()
        return {device.config_subentry_id}
    return set(device.config_entries_subentries.get(entry_id, set()))


def device_in_main_entry(device: dr.DeviceEntry, entry_id: str) -> bool:
    """Return whether the device is linked to the entry outside any subentry."""
    return None in device_subentry_ids(device, entry_id)


def move_device_to_subentry(
    dev_reg: dr.DeviceRegistry,
    device: dr.DeviceEntry,
    entry_id: str,
    subentry_id: str,
) -> None:
    """Move a device to *subentry_id*, from the main entry or another subentry."""
    _LOGGER.debug("Moving device %s to subentry %s", device.id, subentry_id)
    if _single_owner(device):
        dev_reg.async_update_device(device.id, new_config_subentry_id=subentry_id)
        return
    old_subentry_ids = device_subentry_ids(device, entry_id) - {subentry_id}
    # The multi-entry model links the new subentry first and then drops the
    # old links, so the device is never left without an owner.
    dev_reg.async_update_device(
        device.id,
        add_config_entry_id=entry_id,
        add_config_subentry_id=subentry_id,
    )
    for old_subentry_id in old_subentry_ids:
        dev_reg.async_update_device(
            device.id,
            remove_config_entry_id=entry_id,
            remove_config_subentry_id=old_subentry_id,
        )


def remove_device_from_entry(
    dev_reg: dr.DeviceRegistry, device: dr.DeviceEntry, entry_id: str
) -> None:
    """Remove the device, or only its link to the entry if others share it."""
    if _single_owner(device) or device.config_entries <= {entry_id}:
        _LOGGER.debug("Removing device %s", device.id)
        dev_reg.async_remove_device(device.id)
        return
    _LOGGER.debug("Unlinking device %s from entry %s", device.id, entry_id)
    dev_reg.async_update_device(device.id, remove_config_entry_id=entry_id)
