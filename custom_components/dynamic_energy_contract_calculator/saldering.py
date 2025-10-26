"""Helpers for handling Dutch net metering (salderingsregeling)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import List, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from .entity import DynamicEnergySensor


@dataclass
class _Adjustment:
    sensor_id: str
    value: float


class SalderingTracker:
    """Coordinate saldering (net metering) adjustments across sensors."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._net_consumption_kwh: float = 0.0
        self._queue: List[_Adjustment] = []
        self._balances: dict[str, float] = {}
        self._sensors: dict[str, DynamicEnergySensor] = {}

    @property
    def net_consumption_kwh(self) -> float:
        """Return the current net electricity consumption (kWh)."""
        return self._net_consumption_kwh

    @property
    def tax_balance_per_sensor(self) -> dict[str, float]:
        """Return a snapshot of outstanding tax already charged per sensor."""
        return dict(self._balances)

    async def async_register_sensor(self, sensor: DynamicEnergySensor) -> None:
        """Register a cost sensor that participates in saldering."""
        async with self._lock:
            uid = sensor.unique_id
            self._sensors[uid] = sensor
            self._balances.setdefault(uid, 0.0)

    async def async_unregister_sensor(self, sensor: DynamicEnergySensor) -> None:
        """Remove a cost sensor from the tracker."""
        async with self._lock:
            uid = sensor.unique_id
            self._sensors.pop(uid, None)
            self._balances.pop(uid, None)
            self._queue = [
                adj for adj in self._queue if adj.sensor_id != uid
            ]

    async def async_reset_sensor(self, sensor: DynamicEnergySensor) -> None:
        """Clear outstanding tax balance for a sensor."""
        async with self._lock:
            uid = sensor.unique_id
            self._balances[uid] = 0.0
            self._queue = [
                adj for adj in self._queue if adj.sensor_id != uid
            ]

    async def async_record_consumption(
        self,
        sensor: DynamicEnergySensor,
        delta_kwh: float,
        tax_unit_price: float,
    ) -> Tuple[float, float]:
        """Record consumption and return the taxable kWh and value."""
        if delta_kwh <= 0 or tax_unit_price <= 0:
            return 0.0, 0.0

        async with self._lock:
            net_before = self._net_consumption_kwh
            net_after = net_before + delta_kwh
            taxable_kwh = max(net_after, 0.0) - max(net_before, 0.0)
            taxable_value = round(taxable_kwh * tax_unit_price, 8)

            self._net_consumption_kwh = net_after
            if taxable_value > 0:
                uid = sensor.unique_id
                self._balances[uid] = self._balances.get(uid, 0.0) + taxable_value
                self._queue.append(_Adjustment(sensor_id=uid, value=taxable_value))

            return taxable_kwh, taxable_value

    async def async_record_production(
        self,
        delta_kwh: float,
        tax_unit_price: float,
    ) -> Tuple[float, float, List[Tuple[DynamicEnergySensor, float]]]:
        """Record production and return credited kWh/value plus adjustments."""
        if delta_kwh <= 0 or tax_unit_price <= 0:
            return 0.0, 0.0, []

        async with self._lock:
            net_before = self._net_consumption_kwh
            net_after = net_before - delta_kwh
            credited_kwh = max(net_before, 0.0) - max(net_after, 0.0)
            credited_value = round(credited_kwh * tax_unit_price, 8)

            self._net_consumption_kwh = net_after
            if credited_value <= 0:
                return credited_kwh, 0.0, []

            remaining = credited_value
            adjustments: List[_Adjustment] = []

            while remaining > 0 and self._queue:
                entry = self._queue[0]
                take = min(entry.value, remaining)
                adjustments.append(_Adjustment(sensor_id=entry.sensor_id, value=take))
                entry.value = round(entry.value - take, 8)
                remaining = round(remaining - take, 8)
                self._balances[entry.sensor_id] = max(
                    round(self._balances.get(entry.sensor_id, 0.0) - take, 8), 0.0
                )
                if entry.value <= 0:
                    self._queue.pop(0)
                else:
                    self._queue[0] = entry

            sensor_adjustments: List[Tuple[DynamicEnergySensor, float]] = []
            for adj in adjustments:
                sensor = self._sensors.get(adj.sensor_id)
                if sensor is not None and adj.value > 0:
                    sensor_adjustments.append((sensor, adj.value))

            return credited_kwh, credited_value, sensor_adjustments

    async def async_reset_all(self) -> None:
        """Reset the entire tracker state."""
        async with self._lock:
            self._net_consumption_kwh = 0.0
            self._queue.clear()
            for key in list(self._balances):
                self._balances[key] = 0.0
