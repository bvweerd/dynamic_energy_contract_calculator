"""Helpers for handling solar bonus (zonnebonus) calculations."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Mapping
from datetime import date
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    SOLAR_BONUS_BASE_MARKET_ONLY,
    SOLAR_BONUS_BASE_MARKET_PLUS_MARKUP,
    SOLAR_BONUS_LIMIT_CALENDAR_YEAR,
    SOLAR_BONUS_LIMIT_CONTRACT_YEAR,
    SOLAR_BONUS_STORAGE_KEY_PREFIX,
    SOLAR_BONUS_STORAGE_VERSION,
    SOLAR_BONUS_WINDOW_FIXED_HOURS,
    SOLAR_BONUS_WINDOW_SUNRISE_SUNSET,
    STORAGE_SAVE_DELAY_SECONDS,
)
from .contract import latest_anniversary, next_anniversary, parse_contract_date

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
        self._contract_start_date = parse_contract_date(contract_start_date)
        self._limit_period = limit_period
        self._listeners: list[Callable[[], None]] = []

        # Track production eligible for bonus this limit period
        self._current_contract_year_start: date | None = None
        self._year_production_kwh: float = 0.0
        self._total_bonus_euro: float = 0.0

        self._current_contract_year_start = self._get_current_period_start()

        if initial_state:
            stored_year_start = parse_contract_date(
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
        return latest_anniversary(self._contract_start_date, dt_util.now().date())

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
    def limit_period(self) -> str:
        """Return the period over which the annual kWh limit is counted."""
        return self._limit_period

    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Call *listener* whenever the tracked totals change.

        Returns a callable that removes the listener again.
        """
        self._listeners.append(listener)

        @callback
        def _remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return _remove

    @callback
    def _notify_listeners(self) -> None:
        for listener in list(self._listeners):
            listener()

    def limit_reached(self, annual_limit_kwh: float) -> bool:
        """Return whether no bonus can be earned for the rest of this period."""
        return self._year_production_kwh >= annual_limit_kwh

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
                await self._async_save_state()
                self._notify_listeners()

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
            self._notify_listeners()

            return bonus_amount, eligible_kwh

    async def async_reset_year(self) -> None:
        """Reset the yearly counter (for testing or manual reset)."""
        async with self._lock:
            self._year_production_kwh = 0.0
            self._total_bonus_euro = 0.0
            self._current_contract_year_start = self._get_current_period_start()
            await self._async_save_state()
        self._notify_listeners()

    def _data_to_save(self) -> dict[str, Any]:
        return {
            "contract_year_start": (
                self._current_contract_year_start.isoformat()
                if self._current_contract_year_start
                else None
            ),
            "year_production_kwh": self._year_production_kwh,
            "total_bonus_euro": self._total_bonus_euro,
        }

    async def _async_save_state(self) -> None:
        """Schedule a write of the current state to storage."""
        self._store.async_delay_save(self._data_to_save, STORAGE_SAVE_DELAY_SECONDS)

    async def async_flush(self) -> None:
        """Write the current state to storage now (e.g. before unload)."""
        await self._store.async_save(self._data_to_save())

    def get_next_anniversary_date(self) -> date | None:
        """Get the next contract anniversary date."""
        if not self._contract_start_date:
            return None
        return next_anniversary(self._contract_start_date, dt_util.now().date())


async def async_get_solar_bonus_tracker(
    hass: HomeAssistant, entry_id: str, price_settings: Mapping[str, Any]
) -> SolarBonusTracker:
    """Return the entry's shared tracker, creating and loading it once.

    The sensor and binary_sensor platforms are set up concurrently and both
    need the same tracker. Loading the store awaits, so a plain get-or-create
    would let both platforms build their own tracker; the in-flight creation
    task is shared instead.
    """
    domain_data = hass.data.setdefault(DOMAIN, {})
    trackers: dict[str, SolarBonusTracker] = domain_data.setdefault("solar_bonus", {})
    if (tracker := trackers.get(entry_id)) is not None:
        return tracker

    loading: dict[str, asyncio.Task[SolarBonusTracker]] = domain_data.setdefault(
        "solar_bonus_loading", {}
    )
    task = loading.get(entry_id)
    if task is None:
        task = hass.async_create_task(
            SolarBonusTracker.async_create(
                hass,
                entry_id,
                price_settings.get("contract_start_date", ""),
                price_settings.get(
                    "solar_bonus_limit_period", SOLAR_BONUS_LIMIT_CALENDAR_YEAR
                ),
            ),
            eager_start=True,
        )
        loading[entry_id] = task
    try:
        tracker = await task
    finally:
        loading.pop(entry_id, None)
        if not loading:
            domain_data.pop("solar_bonus_loading", None)
    return trackers.setdefault(entry_id, tracker)
