"""Helpers for handling solar bonus (zonnebonus) calculations."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, date
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    SOLAR_BONUS_BASE_MARKET_ONLY,
    SOLAR_BONUS_BASE_MARKET_PLUS_MARKUP,
    SOLAR_BONUS_LIMIT_CALENDAR_YEAR,
    SOLAR_BONUS_LIMIT_CONTRACT_YEAR,
    SOLAR_BONUS_STORAGE_KEY_PREFIX,
    SOLAR_BONUS_STORAGE_VERSION,
    SOLAR_BONUS_WINDOW_FIXED_HOURS,
    SOLAR_BONUS_WINDOW_SUNRISE_SUNSET,
)

if TYPE_CHECKING:  # pragma: no cover
    pass

_LOGGER = logging.getLogger(__name__)


class SolarBonusTracker:
    """Track solar bonus eligible production and annual limits."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        store: Store[dict[str, Any]],
        initial_state: dict[str, Any] | None,
        contract_start_date: str | None = None,
        limit_period: str = SOLAR_BONUS_LIMIT_CALENDAR_YEAR,
    ) -> None:
        self._lock = asyncio.Lock()
        self._store = store
        self._entry_id = entry_id
        self._hass = hass
        self._contract_start_date = self._parse_date(contract_start_date)
        self._limit_period = limit_period

        # Track production eligible for bonus this limit period
        self._current_contract_year_start: date | None = None
        self._year_production_kwh: float = 0.0
        self._total_bonus_euro: float = 0.0

        self._current_contract_year_start = self._get_current_period_start()

        if initial_state:
            stored_year_start = self._parse_date(
                initial_state.get("contract_year_start")
            )
            # Reset if we rolled over into a new limit period
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

    def _get_current_period_start(self) -> date | None:
        """Return the start date of the current annual-limit period.

        Contract-year periods run from the contract anniversary; every other
        configuration counts per calendar year. Falling back to the calendar
        year matters: without it a tracker with no contract start date would
        never reset and would exhaust its annual limit permanently.
        """
        if (
            self._limit_period == SOLAR_BONUS_LIMIT_CONTRACT_YEAR
            and self._contract_start_date
        ):
            return self._get_current_contract_year_start()
        return dt_util.now().date().replace(month=1, day=1)

    def _get_current_contract_year_start(self) -> date | None:
        """Get the start date of the current contract year."""
        if not self._contract_start_date:
            return None

        today = dt_util.now().date()
        current_year = today.year

        # Try this year's anniversary
        try:
            this_year_anniversary = self._contract_start_date.replace(year=current_year)
        except ValueError:
            # Handle February 29 edge case
            this_year_anniversary = self._contract_start_date.replace(
                year=current_year, day=28
            )

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
        cls,
        hass: HomeAssistant,
        entry_id: str,
        contract_start_date: str | None = None,
        limit_period: str = SOLAR_BONUS_LIMIT_CALENDAR_YEAR,
    ) -> SolarBonusTracker:
        """Create a tracker and restore persisted state."""
        storage_key = f"{SOLAR_BONUS_STORAGE_KEY_PREFIX}_{entry_id}"
        store: Store[dict[str, Any]] = Store(
            hass,
            SOLAR_BONUS_STORAGE_VERSION,
            storage_key,
            private=True,
        )
        initial = await store.async_load() or {}
        return cls(hass, entry_id, store, initial, contract_start_date, limit_period)

    @property
    def year_production_kwh(self) -> float:
        """Return production eligible for bonus this calendar year."""
        return self._year_production_kwh

    @property
    def total_bonus_euro(self) -> float:
        """Return total bonus earned this year."""
        return self._total_bonus_euro

    def is_daylight(self) -> bool:
        """Check if current time is between sunrise and sunset."""
        try:
            # Try to get sun data from Home Assistant
            sun_state = self._hass.states.get("sun.sun")
            if sun_state:
                if sun_state.state == "above_horizon":
                    return True
                if sun_state.state == "below_horizon":
                    return False
                # Unknown/unavailable sun state — fall through to hour-based fallback
                _LOGGER.debug(
                    "sun.sun has unexpected state %r, using hour-based fallback",
                    sun_state.state,
                )
        except Exception as err:
            _LOGGER.debug(
                "sun.sun state unavailable, using hour-based fallback: %s", err
            )
        now = dt_util.now()
        return bool(6 <= now.hour < 20)

    def is_in_bonus_window(
        self,
        window_mode: str = SOLAR_BONUS_WINDOW_SUNRISE_SUNSET,
        start_hour: float = 6.0,
        end_hour: float = 22.0,
    ) -> bool:
        """Check whether the current time falls inside the bonus window.

        Suppliers define this window differently: Zonneplan pays the bonus
        from sunrise to sunset, NextEnergy between fixed clock hours.
        """
        if window_mode == SOLAR_BONUS_WINDOW_FIXED_HOURS:
            hour = dt_util.now().hour
            return bool(int(start_hour) <= hour < int(end_hour))
        return self.is_daylight()

    async def async_calculate_bonus(
        self,
        delta_kwh: float,
        base_price: float,
        production_markup: float,
        bonus_percentage: float,
        annual_limit_kwh: float,
        bonus_base: str = SOLAR_BONUS_BASE_MARKET_PLUS_MARKUP,
        window_mode: str = SOLAR_BONUS_WINDOW_SUNRISE_SUNSET,
        start_hour: float = 6.0,
        end_hour: float = 22.0,
    ) -> tuple[float, float]:
        """
        Calculate solar bonus for production delta.

        Args:
            delta_kwh: Energy produced in kWh
            base_price: Base price per kWh (EPEX)
            production_markup: Fixed production compensation per kWh
            bonus_percentage: Bonus percentage (e.g., 10.0 for 10%)
            annual_limit_kwh: Annual kWh limit for bonus (e.g., 7500)
            bonus_base: Whether the percentage applies to the market price
                only, or to the market price plus the production markup
            window_mode: Sunrise-to-sunset or a fixed clock-hour window
            start_hour: First hour of a fixed window (inclusive)
            end_hour: Hour the fixed window ends (exclusive)

        Returns:
            Tuple of (bonus amount in euro, eligible kWh for this delta)
        """
        async with self._lock:
            # Reset the counter when we roll into a new limit period
            current_period_start = self._get_current_period_start()
            if current_period_start != self._current_contract_year_start:
                self._current_contract_year_start = current_period_start
                self._year_production_kwh = 0.0
                self._total_bonus_euro = 0.0

            # Check conditions for bonus eligibility
            if delta_kwh <= 0:
                return 0.0, 0.0

            # Must be inside the supplier's bonus window
            if not self.is_in_bonus_window(window_mode, start_hour, end_hour):
                return 0.0, 0.0

            # The amount the bonus percentage applies to. Suppliers that pay a
            # percentage over the bare market price ignore the production
            # markup entirely — including for the positive-price condition, so
            # feed-in charges cannot suppress an otherwise valid bonus.
            if bonus_base == SOLAR_BONUS_BASE_MARKET_ONLY:
                base_compensation = base_price
            else:
                base_compensation = base_price + production_markup
            if base_compensation <= 0:
                return 0.0, 0.0

            # Only kWh that actually earn the bonus count towards the annual
            # limit, so feed-in at night or at negative prices does not use it
            # up. Neither supplier settles this outright: Zonneplan writes "de
            # bonus geldt tot 7.500 kWh teruglevering per kalenderjaar" and
            # NextEnergy "je kunt tot 6.000 kWh profiteren van de Zonnebonus
            # per contract jaar". Both phrase the limit as a cap on bonus, not
            # on feed-in, and that is also the reading that favours the user.
            # Counting gross feed-in instead would only mean reaching the cap
            # sooner, and would apply to both suppliers alike.
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
            self._current_contract_year_start = self._get_current_period_start()
            await self._async_save_state()

    async def _async_save_state(self) -> None:
        """Persist current state to storage."""
        state = {
            "contract_year_start": (
                self._current_contract_year_start.isoformat()
                if self._current_contract_year_start
                else None
            ),
            "year_production_kwh": self._year_production_kwh,
            "total_bonus_euro": self._total_bonus_euro,
        }
        await self._store.async_save(state)

    def get_next_anniversary_date(self) -> date | None:
        """Get the next contract anniversary date."""
        if not self._contract_start_date:
            return None

        today = dt_util.now().date()
        current_year = today.year

        # Try this year's anniversary
        try:
            this_year_anniversary = self._contract_start_date.replace(year=current_year)
        except ValueError:
            # Handle February 29 edge case
            this_year_anniversary = self._contract_start_date.replace(
                year=current_year, day=28
            )

        if today >= this_year_anniversary:
            # Return next year's anniversary
            try:
                return self._contract_start_date.replace(year=current_year + 1)
            except ValueError:
                return self._contract_start_date.replace(year=current_year + 1, day=28)
        else:
            return this_year_anniversary
