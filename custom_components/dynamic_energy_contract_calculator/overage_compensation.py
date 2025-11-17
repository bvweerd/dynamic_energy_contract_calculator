"""Helpers for handling overage compensation (teruglevering vergoeding tot break-even)."""

from __future__ import annotations

import asyncio

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import (
    OVERAGE_COMPENSATION_STORAGE_KEY_PREFIX,
    OVERAGE_COMPENSATION_STORAGE_VERSION,
)


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

    async def async_record_consumption(self, delta_kwh: float) -> None:
        """Record consumption."""
        if delta_kwh <= 0:
            return

        async with self._lock:
            self._net_consumption_kwh += delta_kwh
            self._total_consumption_kwh += delta_kwh
            await self._async_save_state()

    async def async_record_production(
        self,
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
            await self._async_save_state()

    async def _async_save_state(self) -> None:
        """Persist the tracker state to storage."""
        data = {
            "net_consumption_kwh": round(self._net_consumption_kwh, 8),
            "total_consumption_kwh": round(self._total_consumption_kwh, 8),
            "total_production_kwh": round(self._total_production_kwh, 8),
        }
        await self._store.async_save(data)
