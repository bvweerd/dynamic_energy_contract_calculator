"""Helpers for handling overage compensation (teruglevering vergoeding tot break-even)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import (
    OVERAGE_COMPENSATION_STORAGE_KEY_PREFIX,
    OVERAGE_COMPENSATION_STORAGE_VERSION,
)

if TYPE_CHECKING:  # pragma: no cover
    from .entity import DynamicEnergySensor


@dataclass
class _PendingCompensation:
    """Track production that needs retroactive compensation when consumption catches up."""

    sensor_id: str
    kwh: float
    unit_price_diff: float  # normal_price - overage_price per kWh


class OverageCompensationTracker:
    """Track net consumption for overage compensation calculations."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        store: Store,
        initial_state: dict | None,
    ) -> None:
        self._lock = asyncio.Lock()
        self._store = store
        self._entry_id = entry_id
        self._net_consumption_kwh: float = 0.0
        self._total_consumption_kwh: float = 0.0
        self._total_production_kwh: float = 0.0
        self._pending_queue: list[_PendingCompensation] = []
        self._sensors: dict[str, DynamicEnergySensor] = {}

        if initial_state:
            self._net_consumption_kwh = float(
                initial_state.get("net_consumption_kwh", 0.0)
            )
            self._total_consumption_kwh = float(
                initial_state.get("total_consumption_kwh", 0.0)
            )
            self._total_production_kwh = float(
                initial_state.get("total_production_kwh", 0.0)
            )
            # Restore pending compensation queue
            queue_data = initial_state.get("pending_queue", [])
            if isinstance(queue_data, list):
                for entry in queue_data:
                    if not isinstance(entry, dict):
                        continue
                    sid = entry.get("sensor_id")
                    kwh = entry.get("kwh")
                    price_diff = entry.get("unit_price_diff")
                    try:
                        pending = _PendingCompensation(
                            sensor_id=str(sid),
                            kwh=float(kwh),
                            unit_price_diff=float(price_diff),
                        )
                    except (TypeError, ValueError):
                        continue
                    if pending.kwh > 0:
                        self._pending_queue.append(pending)

    @classmethod
    async def async_create(
        cls, hass: HomeAssistant, entry_id: str
    ) -> OverageCompensationTracker:
        """Create a tracker and restore persisted state."""
        storage_key = f"{OVERAGE_COMPENSATION_STORAGE_KEY_PREFIX}_{entry_id}"
        store = Store(
            hass,
            OVERAGE_COMPENSATION_STORAGE_VERSION,
            storage_key,
            private=True,
        )
        initial = await store.async_load() or {}
        return cls(hass, entry_id, store, initial)

    @property
    def net_consumption_kwh(self) -> float:
        """Return the current net electricity consumption (kWh)."""
        return self._net_consumption_kwh

    @property
    def total_consumption_kwh(self) -> float:
        """Return the total electricity consumption (kWh)."""
        return self._total_consumption_kwh

    @property
    def total_production_kwh(self) -> float:
        """Return the total electricity production (kWh)."""
        return self._total_production_kwh

    @property
    def pending_compensation_kwh(self) -> float:
        """Return total kWh awaiting retroactive compensation."""
        return sum(p.kwh for p in self._pending_queue)

    async def async_register_sensor(self, sensor: DynamicEnergySensor) -> None:
        """Register a production sensor that participates in overage compensation."""
        async with self._lock:
            uid = sensor.unique_id
            self._sensors[uid] = sensor

    async def async_unregister_sensor(self, sensor: DynamicEnergySensor) -> None:
        """Remove a sensor from the tracker."""
        async with self._lock:
            uid = sensor.unique_id
            self._sensors.pop(uid, None)
            self._pending_queue = [
                p for p in self._pending_queue if p.sensor_id != uid
            ]
            await self._async_save_state()

    async def async_record_consumption(
        self,
        delta_kwh: float,
    ) -> list[tuple[DynamicEnergySensor, float]]:
        """
        Record consumption and return any retroactive compensation adjustments.

        When consumption brings net back above 0, we compensate earlier
        overage production at the difference between normal and overage rate.

        Returns:
            List of (sensor, compensation_value) tuples for retroactive adjustments.
        """
        if delta_kwh <= 0:
            return []

        async with self._lock:
            net_before = self._net_consumption_kwh
            net_after = net_before + delta_kwh

            self._net_consumption_kwh = net_after
            self._total_consumption_kwh += delta_kwh

            # Check if consumption brings us back from overage (net < 0 -> net >= 0)
            # and we have pending compensations to pay out
            adjustments: list[tuple[DynamicEnergySensor, float]] = []

            if net_before < 0 and self._pending_queue:
                # How much of the overage are we "filling back up"?
                # This is the amount that goes from negative towards 0
                recovered_kwh = min(delta_kwh, -net_before)

                remaining_kwh = recovered_kwh
                while remaining_kwh > 0 and self._pending_queue:
                    entry = self._pending_queue[0]
                    take_kwh = min(entry.kwh, remaining_kwh)
                    compensation = round(take_kwh * entry.unit_price_diff, 8)

                    sensor = self._sensors.get(entry.sensor_id)
                    if sensor is not None and compensation > 0:
                        adjustments.append((sensor, compensation))

                    entry.kwh = round(entry.kwh - take_kwh, 8)
                    remaining_kwh = round(remaining_kwh - take_kwh, 8)

                    if entry.kwh <= 0:
                        self._pending_queue.pop(0)

            await self._async_save_state()
            return adjustments

    async def async_record_production(
        self,
        sensor: DynamicEnergySensor,
        delta_kwh: float,
        normal_unit_price: float,
        overage_unit_price: float,
    ) -> tuple[float, float, float, float]:
        """
        Record production and return compensation details.

        Returns:
            tuple: (
                compensated_kwh,      # kWh compensated at normal rate
                compensated_value,    # value at normal rate
                overage_kwh,          # kWh at overage rate
                overage_value         # value at overage rate
            )
        """
        if delta_kwh <= 0:
            return 0.0, 0.0, 0.0, 0.0

        async with self._lock:
            net_before = self._net_consumption_kwh
            net_after = net_before - delta_kwh

            # Calculate how much production brings us to break-even (net = 0)
            # and how much is overage (production beyond break-even)
            if net_before > 0:
                # We have net consumption, so some/all production is compensated normally
                compensated_kwh = min(delta_kwh, net_before)
                overage_kwh = max(0.0, delta_kwh - net_before)
            else:
                # We're already in overage, all production is overage
                compensated_kwh = 0.0
                overage_kwh = delta_kwh

            compensated_value = round(compensated_kwh * normal_unit_price, 8)
            overage_value = round(overage_kwh * overage_unit_price, 8)

            # If there's overage production, track it for potential future compensation
            # when consumption catches up
            if overage_kwh > 0:
                price_diff = normal_unit_price - overage_unit_price
                if price_diff > 0:
                    self._pending_queue.append(
                        _PendingCompensation(
                            sensor_id=sensor.unique_id,
                            kwh=overage_kwh,
                            unit_price_diff=price_diff,
                        )
                    )

            self._net_consumption_kwh = net_after
            self._total_production_kwh += delta_kwh

            await self._async_save_state()
            return compensated_kwh, compensated_value, overage_kwh, overage_value

    async def async_reset_all(self) -> None:
        """Reset the entire tracker state."""
        async with self._lock:
            self._net_consumption_kwh = 0.0
            self._total_consumption_kwh = 0.0
            self._total_production_kwh = 0.0
            self._pending_queue.clear()
            await self._async_save_state()

    async def _async_save_state(self) -> None:
        """Persist the tracker state to storage."""
        data = {
            "net_consumption_kwh": round(self._net_consumption_kwh, 8),
            "total_consumption_kwh": round(self._total_consumption_kwh, 8),
            "total_production_kwh": round(self._total_production_kwh, 8),
            "pending_queue": [
                {
                    "sensor_id": p.sensor_id,
                    "kwh": round(p.kwh, 8),
                    "unit_price_diff": round(p.unit_price_diff, 8),
                }
                for p in self._pending_queue
                if p.kwh > 0
            ],
        }
        await self._store.async_save(data)
