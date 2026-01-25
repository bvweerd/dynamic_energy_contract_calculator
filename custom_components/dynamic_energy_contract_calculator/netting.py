"""Helpers for handling Dutch netting (salderingsregeling).

The Dutch netting regulation (salderingsregeling) allows consumers to offset
their electricity consumption against their production (e.g., from solar panels).
Energy tax is only charged on the NET consumption (consumption - production).

This implementation tracks consumption with historical tax rates, so that when
the tax rate changes mid-contract, the correct rate is applied to consumption
that occurred during each period. Production is credited against consumption
in FIFO order, ensuring accurate tax calculations.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import NETTING_STORAGE_KEY_PREFIX, NETTING_STORAGE_VERSION

if TYPE_CHECKING:  # pragma: no cover
    from .entity import DynamicEnergySensor

_LOGGER = logging.getLogger(__name__)


@dataclass
class TaxContribution:
    """A record of taxable consumption with the rate at time of consumption.

    This allows accurate tax calculation when rates change mid-contract.
    Each contribution represents kWh consumed at a specific tax rate.
    """

    kwh: float
    tax_rate: float  # per_unit_government_electricity_tax at time of consumption
    vat_factor: float  # VAT multiplier (e.g., 1.21) at time of consumption

    @property
    def tax_amount(self) -> float:
        """Calculate the tax for this contribution (including VAT)."""
        return round(self.kwh * self.tax_rate * self.vat_factor, 8)

    def to_dict(self) -> dict:
        """Serialize to dictionary for storage."""
        return {
            "kwh": round(self.kwh, 8),
            "tax_rate": self.tax_rate,
            "vat_factor": self.vat_factor,
        }

    @classmethod
    def from_dict(cls, data: dict) -> TaxContribution:
        """Deserialize from dictionary."""
        return cls(
            kwh=float(data.get("kwh", 0.0)),
            tax_rate=float(data.get("tax_rate", 0.0)),
            vat_factor=float(data.get("vat_factor", 1.21)),
        )


class NettingTracker:
    """Coordinate netting adjustments across sensors.

    The tracker maintains:
    - net_consumption_kwh: The total net consumption (consumption - production)
    - tax_contributions: A FIFO queue of consumption records with historical rates

    When production occurs, it's credited against consumption in FIFO order,
    removing the corresponding tax contributions. This ensures that tax rates
    from when consumption occurred are used, even if rates change later.
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
        self._tax_contributions: list[TaxContribution] = []
        self._sensors: dict[str, DynamicEnergySensor] = {}
        self._price_settings = price_settings or {}

        if initial_state:
            self._net_consumption_kwh = float(
                initial_state.get("net_consumption_kwh", 0.0)
            )
            # Restore tax contributions from storage
            contributions_data = initial_state.get("tax_contributions", [])
            if isinstance(contributions_data, list):
                for entry in contributions_data:
                    if isinstance(entry, dict):
                        try:
                            contrib = TaxContribution.from_dict(entry)
                            if contrib.kwh > 0:
                                self._tax_contributions.append(contrib)
                        except (TypeError, ValueError):
                            continue
            _LOGGER.debug(
                "Restored netting state: net_consumption_kwh=%.4f, %d tax contributions",
                self._net_consumption_kwh,
                len(self._tax_contributions),
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
        return float(
            self._price_settings.get("per_unit_government_electricity_tax", 0.0)
        )

    @property
    def vat_factor(self) -> float:
        """Return the VAT multiplier (e.g., 1.21 for 21% VAT)."""
        vat_percentage = float(self._price_settings.get("vat_percentage", 21.0))
        return 1.0 + vat_percentage / 100.0

    @property
    def tax_balance(self) -> float:
        """Calculate the total energy tax from all contributions (including VAT).

        This sums the tax from all consumption records, each using the rate
        that was in effect when the consumption occurred. This ensures correct
        tax calculation even when rates change mid-contract.
        """
        return round(sum(c.tax_amount for c in self._tax_contributions), 8)

    @property
    def tax_balance_per_sensor(self) -> dict[str, float]:
        """Return tax balance distributed across registered consumption sensors.

        For simplicity, we assign the full balance to the first consumption sensor.
        """
        total_tax = self.tax_balance
        result: dict[str, float] = {}

        # Find consumption cost sensors
        consumption_sensors = [
            uid
            for uid, sensor in self._sensors.items()
            if hasattr(sensor, "source_type")
            and sensor.source_type == "Electricity consumption"
            and hasattr(sensor, "mode")
            and sensor.mode == "cost_total"
        ]

        if consumption_sensors:
            result[consumption_sensors[0]] = total_tax
            for uid in consumption_sensors[1:]:
                result[uid] = 0.0
        else:
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
        """Reset is a no-op for individual sensors.

        Tax balance is calculated from the contributions queue.
        """
        pass

    async def async_record_consumption(
        self,
        sensor: DynamicEnergySensor,
        delta_kwh: float,
        tax_unit_price: float,
    ) -> tuple[float, float]:
        """Record consumption and return the taxable kWh and value.

        Each consumption is recorded with the current tax rate, so that
        future rate changes don't affect historical consumption.

        Args:
            sensor: The consumption sensor recording the delta
            delta_kwh: The consumption delta in kWh
            tax_unit_price: The energy tax rate per kWh (used for return value)

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

            # Record the taxable consumption with current rates
            if taxable_kwh > 0:
                contribution = TaxContribution(
                    kwh=taxable_kwh,
                    tax_rate=self.tax_rate,
                    vat_factor=self.vat_factor,
                )
                self._tax_contributions.append(contribution)
                _LOGGER.debug(
                    "Added tax contribution: %.4f kWh @ %.4f rate, %.2f%% VAT",
                    taxable_kwh,
                    self.tax_rate,
                    (self.vat_factor - 1) * 100,
                )

            await self._async_save_state()
            return taxable_kwh, taxable_value

    async def async_record_production(
        self,
        delta_kwh: float,
        tax_unit_price: float,
    ) -> tuple[float, float, list[tuple[DynamicEnergySensor, float]]]:
        """Record production and credit against consumption in FIFO order.

        When production reduces net consumption below what was previously
        taxed, the corresponding tax contributions are removed from the queue.
        This ensures tax credits use the rate from when consumption occurred.

        Args:
            delta_kwh: The production delta in kWh
            tax_unit_price: The energy tax rate per kWh (used for return value)

        Returns:
            Tuple of (credited_kwh, credited_value, sensor_adjustments).
            sensor_adjustments is always empty in this model.
        """
        if delta_kwh <= 0 or tax_unit_price <= 0:
            return 0.0, 0.0, []

        async with self._lock:
            net_before = self._net_consumption_kwh
            net_after = net_before - delta_kwh

            # The portion that reduces positive net consumption gets tax credit
            credited_kwh = max(net_before, 0.0) - max(net_after, 0.0)

            self._net_consumption_kwh = net_after

            # Remove tax contributions in FIFO order for the credited kWh
            if credited_kwh > 0:
                remaining_credit = credited_kwh
                while remaining_credit > 0 and self._tax_contributions:
                    contrib = self._tax_contributions[0]
                    if contrib.kwh <= remaining_credit:
                        # Remove entire contribution
                        remaining_credit -= contrib.kwh
                        self._tax_contributions.pop(0)
                        _LOGGER.debug(
                            "Removed tax contribution: %.4f kWh @ %.4f rate",
                            contrib.kwh,
                            contrib.tax_rate,
                        )
                    else:
                        # Partial removal
                        contrib.kwh = round(contrib.kwh - remaining_credit, 8)
                        _LOGGER.debug(
                            "Reduced tax contribution by %.4f kWh, %.4f kWh remaining",
                            remaining_credit,
                            contrib.kwh,
                        )
                        remaining_credit = 0

            # Calculate credited value using current rate (for return value only)
            credited_value = round(credited_kwh * tax_unit_price, 8)

            await self._async_save_state()
            return credited_kwh, credited_value, []

    async def async_reset_all(self) -> None:
        """Reset the entire tracker state."""
        async with self._lock:
            self._net_consumption_kwh = 0.0
            self._tax_contributions.clear()
            await self._async_save_state()
            _LOGGER.info(
                "Netting tracker reset: net_consumption_kwh=0.0, contributions cleared"
            )

    async def async_set_net_consumption(self, value: float) -> None:
        """Set the net consumption kWh value directly.

        This also adjusts the tax contributions to match the new value,
        using the current tax rate for any positive net consumption.
        """
        async with self._lock:
            old_value = self._net_consumption_kwh
            self._net_consumption_kwh = round(value, 8)

            # Rebuild tax contributions to match new net consumption
            # Clear existing and create a single contribution for positive net
            self._tax_contributions.clear()
            if value > 0:
                contribution = TaxContribution(
                    kwh=value,
                    tax_rate=self.tax_rate,
                    vat_factor=self.vat_factor,
                )
                self._tax_contributions.append(contribution)
                _LOGGER.info(
                    "Netting set to %.4f kWh, created tax contribution @ %.4f rate",
                    value,
                    self.tax_rate,
                )
            else:
                _LOGGER.info("Netting set to %.4f kWh (no tax contribution)", value)

            await self._async_save_state()

    async def _async_save_state(self) -> None:
        """Persist the tracker state to storage."""
        data = {
            "net_consumption_kwh": round(self._net_consumption_kwh, 8),
            "tax_contributions": [c.to_dict() for c in self._tax_contributions],
        }
        await self._store.async_save(data)
