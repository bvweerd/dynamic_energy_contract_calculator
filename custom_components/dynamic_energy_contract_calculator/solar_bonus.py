"""Helpers for handling solar bonus (zonnebonus) calculations."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.sun import get_astral_event_date
from astral import LocationInfo

from .const import SOLAR_BONUS_STORAGE_KEY_PREFIX, SOLAR_BONUS_STORAGE_VERSION

if TYPE_CHECKING:  # pragma: no cover
    from .entity import DynamicEnergySensor


class SolarBonusTracker:
    """Track solar bonus eligible production and annual limits."""

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
        self._hass = hass

        # Track production eligible for bonus this year
        self._current_year: int = datetime.now().year
        self._year_production_kwh: float = 0.0
        self._total_bonus_euro: float = 0.0

        if initial_state:
            stored_year = initial_state.get("year", self._current_year)
            # Reset if new year
            if stored_year == self._current_year:
                self._year_production_kwh = float(
                    initial_state.get("year_production_kwh", 0.0)
                )
                self._total_bonus_euro = float(
                    initial_state.get("total_bonus_euro", 0.0)
                )

    @classmethod
    async def async_create(
        cls, hass: HomeAssistant, entry_id: str
    ) -> SolarBonusTracker:
        """Create a tracker and restore persisted state."""
        storage_key = f"{SOLAR_BONUS_STORAGE_KEY_PREFIX}_{entry_id}"
        store = Store(
            hass,
            SOLAR_BONUS_STORAGE_VERSION,
            storage_key,
            private=True,
        )
        initial = await store.async_load() or {}
        return cls(hass, entry_id, store, initial)

    @property
    def year_production_kwh(self) -> float:
        """Return production eligible for bonus this calendar year."""
        return self._year_production_kwh

    @property
    def total_bonus_euro(self) -> float:
        """Return total bonus earned this year."""
        return self._total_bonus_euro

    def _is_daylight(self) -> bool:
        """Check if current time is between sunrise and sunset."""
        try:
            # Try to get sun data from Home Assistant
            sun_state = self._hass.states.get("sun.sun")
            if sun_state and sun_state.state == "above_horizon":
                return True
            return False
        except Exception:
            # Fallback: assume daylight between 6 AM and 8 PM
            now = datetime.now()
            return 6 <= now.hour < 20

    async def async_calculate_bonus(
        self,
        delta_kwh: float,
        base_price: float,
        production_markup: float,
        bonus_percentage: float,
        annual_limit_kwh: float,
    ) -> tuple[float, float]:
        """
        Calculate solar bonus for production delta.

        Args:
            delta_kwh: Energy produced in kWh
            base_price: Base price per kWh (EPEX)
            production_markup: Fixed production compensation per kWh
            bonus_percentage: Bonus percentage (e.g., 10.0 for 10%)
            annual_limit_kwh: Annual kWh limit for bonus (e.g., 7500)

        Returns:
            Tuple of (bonus amount in euro, eligible kWh for this delta)
        """
        async with self._lock:
            # Check if new year - reset if needed
            current_year = datetime.now().year
            if current_year != self._current_year:
                self._current_year = current_year
                self._year_production_kwh = 0.0
                self._total_bonus_euro = 0.0

            # Check conditions for bonus eligibility
            if delta_kwh <= 0:
                return 0.0, 0.0

            # Must be during daylight hours
            if not self._is_daylight():
                return 0.0, 0.0

            # Base compensation must be positive
            base_compensation = base_price + production_markup
            if base_compensation <= 0:
                return 0.0, 0.0

            # Calculate how much production is still eligible for bonus
            remaining_eligible_kwh = annual_limit_kwh - self._year_production_kwh
            if remaining_eligible_kwh <= 0:
                return 0.0, 0.0

            # Apply the limit
            eligible_kwh = min(delta_kwh, remaining_eligible_kwh)

            # Calculate bonus: percentage of (base_price + markup) for eligible kWh
            bonus_amount = eligible_kwh * base_compensation * (bonus_percentage / 100.0)

            # Update tracking
            self._year_production_kwh += eligible_kwh
            self._total_bonus_euro += bonus_amount

            await self._async_save_state()

            return bonus_amount, eligible_kwh

    async def async_reset_year(self) -> None:
        """Reset the yearly counter (for testing or manual reset)."""
        async with self._lock:
            self._year_production_kwh = 0.0
            self._total_bonus_euro = 0.0
            self._current_year = datetime.now().year
            await self._async_save_state()

    async def _async_save_state(self) -> None:
        """Persist current state to storage."""
        state = {
            "year": self._current_year,
            "year_production_kwh": self._year_production_kwh,
            "total_bonus_euro": self._total_bonus_euro,
        }
        await self._store.async_save(state)
