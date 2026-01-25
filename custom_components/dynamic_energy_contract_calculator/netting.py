"""Helpers for handling Dutch netting (salderingsregeling).

The Dutch netting regulation (salderingsregeling) allows consumers to offset
their electricity consumption against their production (e.g., from solar panels).
Energy tax is only charged on the NET consumption (consumption - production).

The tax rate (energiebelasting) is a FIXED rate per kWh, not variable per hour.
Therefore, the tax balance is calculated dynamically as:
    tax_balance = max(net_consumption_kwh, 0) * per_unit_government_electricity_tax
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import NETTING_STORAGE_KEY_PREFIX, NETTING_STORAGE_VERSION

if TYPE_CHECKING:  # pragma: no cover
    from .entity import DynamicEnergySensor

_LOGGER = logging.getLogger(__name__)


class NettingTracker:
    """Coordinate netting adjustments across sensors.

    The tracker maintains the net consumption (consumption - production) in kWh.
    The tax balance is calculated dynamically based on the current tax rate,
    as per Dutch netting regulations where energy tax is a fixed rate.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        store: Store,
        initial_state: dict | None,
        price_settings: dict | None = None,
    ) -> None:
        self._hass = hass
        self._lock = asyncio.Lock()
        self._store = store
        self._entry_id = entry_id
        self._net_consumption_kwh: float = 0.0
        self._sensors: dict[str, DynamicEnergySensor] = {}
        self._price_settings = price_settings or {}

        if initial_state:
            self._net_consumption_kwh = float(
                initial_state.get("net_consumption_kwh", 0.0)
            )
            _LOGGER.debug(
                "Restored netting state: net_consumption_kwh=%.4f",
                self._net_consumption_kwh,
            )

    @classmethod
    async def async_create(
        cls,
        hass: HomeAssistant,
        entry_id: str,
        price_settings: dict | None = None,
    ) -> NettingTracker:
        """Create a tracker and restore persisted state."""
        storage_key = f"{NETTING_STORAGE_KEY_PREFIX}_{entry_id}"
        store = Store(
            hass,
            NETTING_STORAGE_VERSION,
            storage_key,
            private=True,
        )
        initial = await store.async_load() or {}
        return cls(hass, entry_id, store, initial, price_settings)

    def update_price_settings(self, price_settings: dict) -> None:
        """Update the price settings (e.g., after config reload)."""
        self._price_settings = price_settings

    @property
    def net_consumption_kwh(self) -> float:
        """Return the current net electricity consumption (kWh)."""
        return self._net_consumption_kwh

    @property
    def tax_rate(self) -> float:
        """Return the current energy tax rate per kWh (excluding VAT)."""
        return float(self._price_settings.get("per_unit_government_electricity_tax", 0.0))

    @property
    def vat_factor(self) -> float:
        """Return the VAT multiplier (e.g., 1.21 for 21% VAT)."""
        vat_percentage = float(self._price_settings.get("vat_percentage", 21.0))
        return 1.0 + vat_percentage / 100.0

    @property
    def tax_balance(self) -> float:
        """Calculate the total energy tax based on net consumption (including VAT).

        As per Dutch netting regulations, energy tax is only charged on
        positive net consumption (consumption > production).
        The returned value includes VAT.
        """
        taxable_kwh = max(self._net_consumption_kwh, 0.0)
        return round(taxable_kwh * self.tax_rate * self.vat_factor, 8)

    @property
    def tax_balance_per_sensor(self) -> dict[str, float]:
        """Return tax balance distributed across registered consumption sensors.

        Since tax is calculated on total net consumption, we distribute it
        proportionally across all registered consumption sensors.
        For simplicity, we assign the full balance to the first consumption sensor.
        """
        total_tax = self.tax_balance
        result: dict[str, float] = {}

        # Find consumption sensors and assign tax balance
        consumption_sensors = [
            uid for uid, sensor in self._sensors.items()
            if hasattr(sensor, 'source_type') and sensor.source_type == "Electricity consumption"
            and hasattr(sensor, 'mode') and sensor.mode == "cost_total"
        ]

        if consumption_sensors:
            # Assign full tax balance to first consumption cost sensor
            result[consumption_sensors[0]] = total_tax
            for uid in consumption_sensors[1:]:
                result[uid] = 0.0
        else:
            # Fallback: assign to all registered sensors proportionally
            for uid in self._sensors:
                result[uid] = 0.0

        return result

    async def async_register_sensor(self, sensor: DynamicEnergySensor) -> None:
        """Register a cost sensor that participates in netting."""
        async with self._lock:
            uid = sensor.unique_id
            self._sensors[uid] = sensor

    async def async_unregister_sensor(self, sensor: DynamicEnergySensor) -> None:
        """Remove a cost sensor from the tracker."""
        async with self._lock:
            uid = sensor.unique_id
            self._sensors.pop(uid, None)

    async def async_reset_sensor(self, sensor: DynamicEnergySensor) -> None:
        """Reset is a no-op for individual sensors in the new model.

        Tax balance is calculated dynamically from net_consumption_kwh.
        """
        pass  # No action needed - tax is calculated dynamically

    async def async_record_consumption(
        self,
        sensor: DynamicEnergySensor,
        delta_kwh: float,
        tax_unit_price: float,
    ) -> tuple[float, float]:
        """Record consumption and return the taxable kWh and value.

        Args:
            sensor: The consumption sensor recording the delta
            delta_kwh: The consumption delta in kWh
            tax_unit_price: The energy tax rate per kWh (fixed, not hourly)

        Returns:
            Tuple of (taxable_kwh, taxable_value) - the portion that is taxable
            after applying netting rules.
        """
        if delta_kwh <= 0 or tax_unit_price <= 0:
            return 0.0, 0.0

        async with self._lock:
            net_before = self._net_consumption_kwh
            net_after = net_before + delta_kwh

            # Only the portion that brings net consumption above 0 is taxable
            taxable_kwh = max(net_after, 0.0) - max(net_before, 0.0)
            taxable_value = round(taxable_kwh * tax_unit_price, 8)

            self._net_consumption_kwh = net_after
            await self._async_save_state()

            return taxable_kwh, taxable_value

    async def async_record_production(
        self,
        delta_kwh: float,
        tax_unit_price: float,
    ) -> tuple[float, float, list[tuple[DynamicEnergySensor, float]]]:
        """Record production and return credited kWh/value plus adjustments.

        Args:
            delta_kwh: The production delta in kWh
            tax_unit_price: The energy tax rate per kWh (fixed, not hourly)

        Returns:
            Tuple of (credited_kwh, credited_value, sensor_adjustments).
            In the new model, sensor_adjustments is always empty because
            tax balance is calculated dynamically.
        """
        if delta_kwh <= 0 or tax_unit_price <= 0:
            return 0.0, 0.0, []

        async with self._lock:
            net_before = self._net_consumption_kwh
            net_after = net_before - delta_kwh

            # The portion that reduces positive net consumption gets tax credit
            credited_kwh = max(net_before, 0.0) - max(net_after, 0.0)
            credited_value = round(credited_kwh * tax_unit_price, 8)

            self._net_consumption_kwh = net_after
            await self._async_save_state()

            # No sensor adjustments needed - tax is calculated dynamically
            return credited_kwh, credited_value, []

    async def async_reset_all(self) -> None:
        """Reset the entire tracker state."""
        async with self._lock:
            self._net_consumption_kwh = 0.0
            await self._async_save_state()
            _LOGGER.info("Netting tracker reset: net_consumption_kwh=0.0")

    async def async_set_net_consumption(self, value: float) -> None:
        """Set the net consumption kWh value directly."""
        async with self._lock:
            self._net_consumption_kwh = round(value, 8)
            await self._async_save_state()
            _LOGGER.info("Netting net_consumption_kwh set to %.4f", value)

    async def _async_save_state(self) -> None:
        """Persist the tracker state to storage."""
        data = {
            "net_consumption_kwh": round(self._net_consumption_kwh, 8),
        }
        await self._store.async_save(data)
