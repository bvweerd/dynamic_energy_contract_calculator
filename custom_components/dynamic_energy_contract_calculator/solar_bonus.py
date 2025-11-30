"""Helpers for handling solar bonus (zonnebonus) calculations."""

from __future__ import annotations

import asyncio
from datetime import datetime, date
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
        contract_start_date: str | None = None,
    ) -> None:
        self._lock = asyncio.Lock()
        self._store = store
        self._entry_id = entry_id
        self._hass = hass
        self._contract_start_date = self._parse_date(contract_start_date)

        # Track production eligible for bonus this contract year
        self._current_contract_year_start: date | None = None
        self._year_production_kwh: float = 0.0
        self._total_bonus_euro: float = 0.0

        # Calculate current contract year start
        if self._contract_start_date:
            self._current_contract_year_start = self._get_current_contract_year_start()

        if initial_state:
            stored_year_start = self._parse_date(initial_state.get("contract_year_start"))
            # Reset if new contract year
            if stored_year_start == self._current_contract_year_start:
                self._year_production_kwh = float(
                    initial_state.get("year_production_kwh", 0.0)
                )
                self._total_bonus_euro = float(
                    initial_state.get("total_bonus_euro", 0.0)
                )

    def _parse_date(self, date_str: str | None) -> date | None:
        """Parse date string to date object."""
        if not date_str:
            return None
        try:
            return datetime.fromisoformat(date_str).date()
        except (ValueError, AttributeError):
            return None

    def _get_current_contract_year_start(self) -> date | None:
        """Get the start date of the current contract year."""
        if not self._contract_start_date:
            return None

        today = datetime.now().date()
        current_year = today.year

        # Try this year's anniversary
        try:
            this_year_anniversary = self._contract_start_date.replace(year=current_year)
        except ValueError:
            # Handle February 29 edge case
            this_year_anniversary = self._contract_start_date.replace(year=current_year, day=28)

        if today >= this_year_anniversary:
            return this_year_anniversary
        else:
            # We're before this year's anniversary, so use last year's
            try:
                return self._contract_start_date.replace(year=current_year - 1)
            except ValueError:
                return self._contract_start_date.replace(year=current_year - 1, day=28)

    @classmethod
    async def async_create(
        cls, hass: HomeAssistant, entry_id: str, contract_start_date: str | None = None
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
        return cls(hass, entry_id, store, initial, contract_start_date)

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
            # Check if new contract year - reset if needed
            if self._contract_start_date:
                current_contract_year_start = self._get_current_contract_year_start()
                if current_contract_year_start != self._current_contract_year_start:
                    self._current_contract_year_start = current_contract_year_start
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
            if self._contract_start_date:
                self._current_contract_year_start = self._get_current_contract_year_start()
            await self._async_save_state()

    async def _async_save_state(self) -> None:
        """Persist current state to storage."""
        state = {
            "contract_year_start": self._current_contract_year_start.isoformat() if self._current_contract_year_start else None,
            "year_production_kwh": self._year_production_kwh,
            "total_bonus_euro": self._total_bonus_euro,
        }
        await self._store.async_save(state)

    def get_next_anniversary_date(self) -> date | None:
        """Get the next contract anniversary date."""
        if not self._contract_start_date:
            return None

        today = datetime.now().date()
        current_year = today.year

        # Try this year's anniversary
        try:
            this_year_anniversary = self._contract_start_date.replace(year=current_year)
        except ValueError:
            # Handle February 29 edge case
            this_year_anniversary = self._contract_start_date.replace(year=current_year, day=28)

        if today >= this_year_anniversary:
            # Return next year's anniversary
            try:
                return self._contract_start_date.replace(year=current_year + 1)
            except ValueError:
                return self._contract_start_date.replace(year=current_year + 1, day=28)
        else:
            return this_year_anniversary
