"""Time-dependent network tariff (tijdsafhankelijke nettarief) calculator.

Dutch grid operators will implement time-of-use network tariffs starting in 2029.
Tariffs differ by season (winter/summer) and time-of-day (peak/off-peak), where
peak applies to weekdays within configured hours.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

_LOGGER = logging.getLogger(__name__)

BAND_WINTER_PEAK = "winter_peak"
BAND_WINTER_OFFPEAK = "winter_offpeak"
BAND_SUMMER_PEAK = "summer_peak"
BAND_SUMMER_OFFPEAK = "summer_offpeak"


@dataclass
class NetworkTariffResult:
    """Applicable network tariff band and rate for a point in time."""

    band: str
    tariff_per_kwh: float  # excl. VAT


class NetworkTariffCalculator:
    """Determines the applicable network tariff band for a given datetime.

    Based on the Dutch 2029 tijdsafhankelijke nettarief system:
    - Two seasons: winter (configurable months) and summer (remaining months)
    - Two time periods: peak (weekdays within configured hours) and off-peak
    - Four resulting bands: winter_peak, winter_offpeak, summer_peak, summer_offpeak

    All returned tariff values are exclusive of VAT; callers apply VAT separately.
    """

    def __init__(self, price_settings: dict[str, Any]) -> None:
        self._settings = price_settings

    @property
    def enabled(self) -> bool:
        """Return True if time-dependent network tariffs are enabled."""
        return bool(self._settings.get("network_tariff_enabled", False))

    def update_price_settings(self, price_settings: dict[str, Any]) -> None:
        """Update the price settings reference after a config reload."""
        self._settings = price_settings

    def _is_winter(self, month: int) -> bool:
        start = int(self._settings.get("network_tariff_winter_start_month", 11))
        end = int(self._settings.get("network_tariff_winter_end_month", 3))
        if start <= end:
            return start <= month <= end
        # Wraps the year boundary (e.g. Nov–Mar: months 11, 12, 1, 2, 3)
        return month >= start or month <= end

    def _is_peak(self, hour: int, weekday: int) -> bool:
        """Return True for weekdays within configured peak hours."""
        if weekday >= 5:  # Saturday = 5, Sunday = 6
            return False
        start = int(self._settings.get("network_tariff_peak_start_hour", 7))
        end = int(self._settings.get("network_tariff_peak_end_hour", 23))
        return start <= hour < end

    def get_tariff_for_datetime(self, dt: datetime) -> NetworkTariffResult:
        """Return the applicable tariff band and rate (excl. VAT) for a local datetime."""
        if not self.enabled:
            return NetworkTariffResult(band="disabled", tariff_per_kwh=0.0)

        is_winter = self._is_winter(dt.month)
        is_peak = self._is_peak(dt.hour, dt.weekday())

        if is_winter and is_peak:
            band = BAND_WINTER_PEAK
            rate = float(self._settings.get("network_tariff_winter_peak_per_kwh", 0.0))
        elif is_winter:
            band = BAND_WINTER_OFFPEAK
            rate = float(
                self._settings.get("network_tariff_winter_offpeak_per_kwh", 0.0)
            )
        elif is_peak:
            band = BAND_SUMMER_PEAK
            rate = float(self._settings.get("network_tariff_summer_peak_per_kwh", 0.0))
        else:
            band = BAND_SUMMER_OFFPEAK
            rate = float(
                self._settings.get("network_tariff_summer_offpeak_per_kwh", 0.0)
            )

        _LOGGER.debug(
            "Network tariff: band=%s, rate=%.5f €/kWh (month=%d, hour=%d, weekday=%d)",
            band,
            rate,
            dt.month,
            dt.hour,
            dt.weekday(),
        )
        return NetworkTariffResult(band=band, tariff_per_kwh=rate)
