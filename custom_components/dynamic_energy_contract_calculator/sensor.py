from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from itertools import pairwise
from typing import Any
from zoneinfo import ZoneInfo

from homeassistant.components.sensor import SensorExtraStoredData, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy, UnitOfVolume
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import (
    async_track_point_in_time,
    async_track_state_change_event,
    async_track_time_change,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

try:
    from astral import LocationInfo
    from astral.sun import sun as _astral_sun

    _ASTRAL_AVAILABLE = True
except ImportError:  # pragma: no cover
    _ASTRAL_AVAILABLE = False

from .const import (
    CONF_PRICE_SENSOR,
    CONF_PRICE_SENSOR_GAS,
    CONF_PRICE_SETTINGS,
    CONF_SOURCE_TYPE,
    CONF_SOURCES,
    CONTRACT_STORAGE_KEY_PREFIX,
    CONTRACT_STORAGE_VERSION,
    DOMAIN,
    DOMAIN_ABBREVIATION,
    SOLAR_BONUS_BASE_MARKET_ONLY,
    SOLAR_BONUS_BASE_MARKET_PLUS_MARKUP,
    SOLAR_BONUS_LIMIT_CONTRACT_YEAR,
    SOLAR_BONUS_WINDOW_FIXED_HOURS,
    SOLAR_BONUS_WINDOW_SUNRISE_SUNSET,
    SOURCE_TYPE_CONSUMPTION,
    SOURCE_TYPE_GAS,
    SOURCE_TYPE_PRODUCTION,
    SUBENTRY_TYPE_SOURCE,
)
from .contract import (
    is_anniversary,
    latest_anniversary,
    parse_contract_date,
)
from .device_compat import (
    device_subentry_ids,
    find_entry_device,
    move_device_to_subentry,
    remove_device_from_entry,
)
from .entity import BaseUtilitySensor, DynamicEnergySensor, read_price_sum
from .netting import NettingTracker
from .solar_bonus import SolarBonusTracker, async_get_solar_bonus_tracker

_LOGGER = logging.getLogger(__name__)

# Safety cap on the forecast attribute lists. They are excluded from the
# recorder (_unrecorded_attributes), so the 16 KB database limit does not
# apply. The cap must still fit the longest day: 25 hours on the day DST ends,
# at 15-minute resolution, plus the two extra entries from splitting at
# sunrise and sunset.
_MAX_NET_PRICE_STEPS = 25 * 4 + 2

# Device identifier shared by the summary sensors and the binary sensors.
SUMMARY_DEVICE_ID = "daily_electricity_cost"


def _compute_sun_times(
    latitude: float,
    longitude: float,
    timezone: str,
    date_obj: Any,
) -> tuple[datetime | None, datetime | None]:
    """Return (sunrise, sunset) for *date_obj*.

    This function performs blocking disk I/O via pytz/astral and **must** be
    called inside an executor (``hass.async_add_executor_job``).
    """
    if not _ASTRAL_AVAILABLE:
        return None, None
    try:
        location = LocationInfo(
            name="Home",
            region="",
            timezone=timezone,
            latitude=latitude,
            longitude=longitude,
        )
        s = _astral_sun(location.observer, date=date_obj, tzinfo=timezone)
        return s["sunrise"], s["sunset"]
    # ValueError: the sun never rises or sets that day (polar regions);
    # KeyError: unknown time zone (ZoneInfoNotFoundError);
    # TypeError: no coordinates configured
    except (ValueError, KeyError, TypeError) as exc:
        _LOGGER.debug("Sunrise/sunset calculation failed for %s: %s", date_obj, exc)
        return None, None


def _parse_timestamp(value: Any) -> datetime | None:
    """Parse a price entry timestamp (ISO string or datetime)."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _sort_timestamp(value: datetime) -> float:
    """Return a sort key that orders naive and aware datetimes together."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc).timestamp()
    return value.timestamp()


def _price_intervals(
    entries: list[dict[str, Any]],
) -> list[tuple[datetime, datetime, float, dict[str, Any]]] | None:
    """Return (start, end, value, entry) per entry, or None if not parseable.

    An entry without an end runs until the next entry starts; the last one
    gets the same length as the one before it, or one hour.
    """
    parsed: list[tuple[datetime, datetime | None, float, dict[str, Any]]] = []
    for entry in entries:
        start = _parse_timestamp(entry.get("start") or entry.get("time"))
        if start is None:
            return None
        try:
            value = float(entry.get("value", 0))
        except (TypeError, ValueError):
            return None
        parsed.append((start, _parse_timestamp(entry.get("end")), value, entry))
    try:
        parsed.sort(key=lambda item: _sort_timestamp(item[0]))
        intervals: list[tuple[datetime, datetime, float, dict[str, Any]]] = []
        for idx, (start, end, value, entry) in enumerate(parsed):
            if end is None:
                if idx + 1 < len(parsed):
                    end = parsed[idx + 1][0]
                elif idx > 0:
                    end = start + (start - parsed[idx - 1][0])
                else:
                    end = start + timedelta(hours=1)
            if end <= start:
                return None
            intervals.append((start, end, value, entry))
    except TypeError:
        # Naive and aware timestamps mixed within one list
        return None
    return intervals


SENSOR_MODES_ELECTRICITY: list[dict[str, Any]] = [
    {
        "key": "kwh_total",
        "translation_key": "kwh_total",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "icon": "mdi:counter",
        "visible": True,
    },
    {
        "key": "cost_total",
        "translation_key": "cost_total",
        "unit": "€",
        "device_class": None,
        "icon": "mdi:cash",
        "visible": True,
    },
    {
        "key": "profit_total",
        "translation_key": "profit_total",
        "unit": "€",
        "device_class": None,
        "icon": "mdi:cash-plus",
        "visible": True,
    },
    {
        "key": "kwh_during_cost_total",
        "translation_key": "kwh_during_cost_total",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "icon": "mdi:transmission-tower-export",
        "visible": True,
    },
    {
        "key": "kwh_during_profit_total",
        "translation_key": "kwh_during_profit_total",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": "energy",
        "icon": "mdi:transmission-tower-import",
        "visible": True,
    },
]

SENSOR_MODES_GAS: list[dict[str, Any]] = [
    {
        "key": "m3_total",
        "translation_key": "m3_total",
        "unit": UnitOfVolume.CUBIC_METERS,
        "device_class": "gas",
        "icon": "mdi:counter",
        "visible": True,
    },
    {
        "key": "cost_total",
        "translation_key": "cost_total",
        "unit": "€",
        "device_class": None,
        "icon": "mdi:cash",
        "visible": True,
    },
]

PARALLEL_UPDATES = 0


def _build_netting_attributes(
    tracker: NettingTracker | None,
) -> dict[str, float | bool]:
    if tracker is None:
        return {"netting_enabled": False}
    balances = tracker.tax_balance_per_sensor
    total_balance = round(sum(balances.values()), 8)
    return {
        "netting_enabled": True,
        "netting_net_consumption_kwh": round(tracker.net_consumption_kwh, 8),
        "netting_tax_balance_eur": total_balance,
    }


class NettingStatusMixin:
    _netting_tracker: NettingTracker | None

    def _update_netting_attributes(self) -> None:
        self._attr_extra_state_attributes = _build_netting_attributes(
            self._netting_tracker
        )


class SolarBonusStatusSensor(BaseUtilitySensor):
    """Sensor showing solar bonus statistics."""

    def __init__(
        self,
        hass: HomeAssistant,
        name: str,
        unique_id: str,
        device: DeviceInfo,
        solar_bonus_tracker: SolarBonusTracker,
    ):
        super().__init__(
            name=name,
            unique_id=unique_id,
            unit="€",
            device_class=None,
            icon="mdi:solar-power",
            visible=True,
            device=device,
            translation_key="solar_bonus_total",
        )
        self.hass = hass
        self._solar_bonus_tracker = solar_bonus_tracker

    # The value mirrors the tracker, which follows its own limit period. A
    # contract-year reset must not zero it while the tracker keeps counting.
    _resets_with_contract_year = False

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            self._solar_bonus_tracker.async_add_listener(self._handle_tracker_update)
        )

    @callback
    def _handle_tracker_update(self) -> None:
        self.async_schedule_update_ha_state(True)

    async def async_reset(self) -> None:
        """Show the tracker's value; resetting the tracker is done separately."""
        await self.async_update()
        self.async_write_ha_state()

    async def async_update(self) -> None:
        """Update sensor with current solar bonus stats."""
        self._attr_native_value = self._solar_bonus_tracker.total_bonus_euro
        self._attr_extra_state_attributes = {
            "year_production_kwh": round(
                self._solar_bonus_tracker.year_production_kwh, 2
            ),
            "total_bonus_euro": round(self._solar_bonus_tracker.total_bonus_euro, 2),
        }


class TotalCostSensor(NettingStatusMixin, BaseUtilitySensor):
    def __init__(
        self,
        hass: HomeAssistant,
        name: str,
        unique_id: str,
        device: DeviceInfo,
        source_sensors: list[DynamicEnergySensor],
        netting_tracker: NettingTracker | None = None,
    ):
        super().__init__(
            name=None,
            unique_id=unique_id,
            unit="€",
            device_class=None,
            icon="mdi:scale-balance",
            visible=True,
            device=device,
            translation_key="net_total_cost",
        )
        self.hass = hass
        self._source_sensors = source_sensors
        self._netting_tracker = netting_tracker
        self._update_netting_attributes()

    async def async_update(self) -> None:
        cost_total = 0.0
        profit_total = 0.0

        for entity in self._source_sensors:
            if entity.mode == "cost_total":
                try:
                    cost_total += float(entity.native_value or 0.0)
                except ValueError:
                    continue
            elif entity.mode == "profit_total":
                try:
                    profit_total += float(entity.native_value or 0.0)
                except ValueError:
                    continue
        _LOGGER.debug("Aggregated cost=%s profit=%s", cost_total, profit_total)
        self._attr_native_value = round(cost_total - profit_total, 8)
        self._update_netting_attributes()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        for entity in self._source_sensors:
            if entity.entity_id:
                self.async_on_remove(
                    async_track_state_change_event(
                        self.hass,
                        entity.entity_id,
                        self._handle_input_event,
                    )
                )
        if self.platform is not None:
            await self.async_update()
            self.async_write_ha_state()

    async def _handle_input_event(self, event: Event[EventStateChangedData]) -> None:
        _LOGGER.debug(
            "%s changed, updating %s", event.data.get("entity_id"), self.entity_id
        )
        await self.async_update()
        self.async_write_ha_state()


@dataclass
class DailyCostExtraStoredData(SensorExtraStoredData):
    """Restore data that also keeps the date the daily cost was last added."""

    last_charged_date: str | None

    def as_dict(self) -> dict[str, Any]:
        data = super().as_dict()
        data["last_charged_date"] = self.last_charged_date
        return data


class _DailyCostSensor(BaseUtilitySensor):
    """Fixed costs that are added once per day, at midnight.

    The midnight addition is driven by the platform (see
    _async_setup_midnight_handler) so that a contract-year reset on the same
    midnight always runs first. Midnights missed while Home Assistant was not
    running are added when the sensor is restored.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._last_charged_date: date | None = None

    def _calculate_daily_cost(self) -> float:  # pragma: no cover - abstract
        raise NotImplementedError

    @property
    def extra_restore_state_data(self) -> DailyCostExtraStoredData:
        return DailyCostExtraStoredData(
            self.native_value,
            self.native_unit_of_measurement,
            self._last_charged_date.isoformat() if self._last_charged_date else None,
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        today = dt_util.now().date()
        last_charged: date | None = None
        last_extra_data = await self.async_get_last_extra_data()
        if last_extra_data is not None:
            last_charged = parse_contract_date(
                last_extra_data.as_dict().get("last_charged_date")
            )
        # After a missed contract-year reset only the days of the new
        # contract year are still owed.
        if self._reset_on_restore is not None and (
            last_charged is None or last_charged < self._reset_on_restore
        ):
            last_charged = self._reset_on_restore - timedelta(days=1)
        if last_charged is None or last_charged > today:
            # First run (or a clock that went backwards): start counting from
            # today without charging for it, as before.
            self._last_charged_date = today
            return
        missed_days = (today - last_charged).days
        if missed_days > 0:
            _LOGGER.info(
                "Adding %d missed day(s) of fixed costs to %s",
                missed_days,
                self.entity_id,
            )
            self._attr_native_value += missed_days * self._calculate_daily_cost()
        self._last_charged_date = today

    async def _handle_daily_addition(self, now: datetime) -> None:
        if self._last_charged_date == now.date():
            return
        addition = self._calculate_daily_cost()
        _LOGGER.debug(
            "Adding daily cost %s at %s to %s",
            addition,
            now,
            self.entity_id,
        )
        self._attr_native_value += addition
        self._last_charged_date = now.date()
        self.async_write_ha_state()


class DailyElectricityCostSensor(NettingStatusMixin, _DailyCostSensor):
    def __init__(
        self,
        hass: HomeAssistant,
        name: str,
        unique_id: str,
        price_settings: dict[str, float],
        device: DeviceInfo,
        netting_tracker: NettingTracker | None = None,
    ):
        super().__init__(
            name=None,
            unique_id=unique_id,
            unit="€",
            device_class=None,
            icon="mdi:currency-eur",
            visible=True,
            device=device,
            translation_key="daily_electricity_cost_total",
        )
        self.hass = hass
        self.price_settings = price_settings
        self._netting_tracker = netting_tracker
        self._update_netting_attributes()

    def _calculate_daily_cost(self) -> float:
        vat = self.price_settings.get("vat_percentage", 21.0)
        surcharge = self.price_settings.get(
            "per_day_grid_operator_electricity_connection_fee", 0.0
        )
        standing = self.price_settings.get(
            "per_day_supplier_electricity_standing_charge", 0.0
        )
        rebate = self.price_settings.get(
            "per_day_government_electricity_tax_rebate", 0.0
        )

        subtotal = surcharge + standing - rebate
        total = subtotal * (1 + vat / 100)
        _LOGGER.debug(
            "Daily electricity cost calc: surcharge=%s standing=%s rebate=%s vat=%s -> %s",
            surcharge,
            standing,
            rebate,
            vat,
            total,
        )
        return round(total, 8)

    async def async_update(self) -> None:
        self._update_netting_attributes()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._update_netting_attributes()

    async def _handle_daily_addition(self, now: datetime) -> None:
        self._update_netting_attributes()
        await super()._handle_daily_addition(now)


class DailyGasCostSensor(_DailyCostSensor):
    def __init__(
        self,
        hass: HomeAssistant,
        name: str,
        unique_id: str,
        price_settings: dict[str, float],
        device: DeviceInfo,
    ):
        super().__init__(
            name=None,
            unique_id=unique_id,
            unit="€",
            device_class=None,
            icon="mdi:currency-eur",
            visible=True,
            device=device,
            translation_key="daily_gas_cost_total",
        )
        self.hass = hass
        self.price_settings = price_settings

    def _calculate_daily_cost(self) -> float:
        vat = self.price_settings.get("vat_percentage", 21.0)
        standing = self.price_settings.get("per_day_supplier_gas_standing_charge", 0.0)
        surcharge = self.price_settings.get(
            "per_day_grid_operator_gas_connection_fee", 0.0
        )

        subtotal = standing + surcharge
        total = subtotal * (1 + vat / 100)
        _LOGGER.debug(
            "Daily gas cost calc: standing=%s surcharge=%s vat=%s -> %s",
            standing,
            surcharge,
            vat,
            total,
        )
        return round(total, 8)

    async def async_update(self) -> None:
        pass


class TotalEnergyCostSensor(NettingStatusMixin, BaseUtilitySensor):
    def __init__(
        self,
        hass: HomeAssistant,
        name: str,
        unique_id: str,
        net_cost_unique_id: str,
        fixed_cost_unique_ids: list[str],
        device: DeviceInfo,
        netting_tracker: NettingTracker | None = None,
    ):
        super().__init__(
            name=None,
            unique_id=unique_id,
            unit="€",
            device_class=None,
            icon="mdi:currency-eur",
            visible=True,
            device=device,
            translation_key="total_energy_cost",
        )
        self.hass = hass
        self.net_cost_unique_id = net_cost_unique_id
        self.fixed_cost_unique_ids = fixed_cost_unique_ids
        self.net_cost_entity_id: str | None = None
        self.fixed_cost_entity_ids: list[str] = []
        self._netting_tracker = netting_tracker
        self._update_netting_attributes()

    async def async_update(self) -> None:
        net_cost = 0.0
        fixed_cost = 0.0

        if self.net_cost_entity_id:
            net_state = self.hass.states.get(self.net_cost_entity_id)
        else:
            net_state = None
        if net_state and net_state.state not in ("unknown", "unavailable"):
            try:
                net_cost = float(net_state.state)
            except ValueError:
                pass

        for fid in self.fixed_cost_entity_ids:
            fixed_state = self.hass.states.get(fid)
            if fixed_state and fixed_state.state not in ("unknown", "unavailable"):
                try:
                    fixed_cost += float(fixed_state.state)
                except ValueError:
                    continue
        total = net_cost + fixed_cost
        _LOGGER.debug(
            "Total energy cost calc: net=%s fixed=%s -> %s",
            net_cost,
            fixed_cost,
            total,
        )
        self._attr_native_value = round(total, 8)
        self._update_netting_attributes()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        ent_reg = er.async_get(self.hass)
        self.net_cost_entity_id = ent_reg.async_get_entity_id(
            "sensor", DOMAIN, self.net_cost_unique_id
        )
        for uid in self.fixed_cost_unique_ids:
            eid = ent_reg.async_get_entity_id("sensor", DOMAIN, uid)
            if eid:
                self.fixed_cost_entity_ids.append(eid)

        for entity_id in [self.net_cost_entity_id, *self.fixed_cost_entity_ids]:
            if entity_id:
                self.async_on_remove(
                    async_track_state_change_event(
                        self.hass,
                        entity_id,
                        self._handle_input_event,
                    )
                )
        if self.platform is not None:
            await self.async_update()
            self.async_write_ha_state()

    async def _handle_input_event(self, event: Event[EventStateChangedData]) -> None:
        _LOGGER.debug(
            "Recalculating total energy cost due to %s", event.data.get("entity_id")
        )
        await self.async_update()
        self.async_write_ha_state()


class CurrentElectricityPriceSensor(BaseUtilitySensor):
    _unrecorded_attributes = frozenset(
        {
            "net_today",
            "net_tomorrow",
            "net_prices_today",
            "net_prices_tomorrow",
            "raw_today",
            "raw_tomorrow",
            "today",
            "tomorrow",
        }
    )

    def __init__(
        self,
        hass: HomeAssistant,
        name: str,
        unique_id: str,
        price_sensor: str | list[str],
        source_type: str,
        price_settings: dict[str, float],
        icon: str,
        device: DeviceInfo,
        solar_bonus_tracker: SolarBonusTracker | None = None,
    ):
        unit = "€/m³" if source_type == SOURCE_TYPE_GAS else "€/kWh"
        super().__init__(
            name=None,
            unique_id=unique_id,
            unit=unit,
            device_class=None,
            icon=icon,
            visible=True,
            device=device,
            translation_key=name.lower().replace(" ", "_"),
        )

        self._attr_state_class = SensorStateClass.MEASUREMENT
        self.hass = hass
        if isinstance(price_sensor, list):
            self.price_sensors = price_sensor
        else:
            self.price_sensors = [price_sensor]
        self.price_sensor = self.price_sensors[0] if self.price_sensors else None
        self.source_type = source_type
        self.price_settings = price_settings
        self._net_today: list[dict[str, Any]] | None = None
        self._net_tomorrow: list[dict[str, Any]] | None = None
        self._attr_extra_state_attributes = {
            "net_prices_today": None,
            "net_prices_tomorrow": None,
        }
        self._price_change_unsub: Callable[[], None] | None = None
        # Cache populated by _async_prefetch_sun_times before sync helpers are
        # called – avoids blocking disk I/O (pytz) on the event loop.
        self._sun_times_cache: dict[date, tuple[datetime | None, datetime | None]] = {}
        self._solar_bonus_tracker = solar_bonus_tracker
        self._bonus_limit_reached = self._solar_bonus_limit_reached()

    # A price is not a meter: resets (service or contract year) leave it alone.
    _resets_with_contract_year = False

    async def async_reset(self) -> None:
        """Prices are not accumulated, so there is nothing to reset."""

    def _solar_bonus_applies(self, price_settings_enabled: bool) -> bool:
        return price_settings_enabled and not self._bonus_limit_reached

    def _solar_bonus_limit_reached(self) -> bool:
        """Return whether the tracker has used up this period's bonus kWh."""
        if self._solar_bonus_tracker is None:
            return False
        return self._solar_bonus_tracker.limit_reached(
            self.price_settings.get("solar_bonus_annual_kwh_limit", 7500.0)
        )

    def _solar_bonus_base_amount(self, base_price: float) -> float:
        """Return the amount the bonus percentage applies to.

        Mirrors SolarBonusTracker.async_calculate_bonus, which is what the
        profit sensor actually books: the market price, optionally plus the
        production markup, always without VAT.
        """
        if (
            self.price_settings.get(
                "solar_bonus_base", SOLAR_BONUS_BASE_MARKET_PLUS_MARKUP
            )
            == SOLAR_BONUS_BASE_MARKET_ONLY
        ):
            return base_price
        return base_price + self.price_settings.get(
            "per_unit_supplier_electricity_production_markup", 0.0
        )

    def _calculate_price(self, base_price: float) -> float | None:
        if self.source_type == SOURCE_TYPE_GAS:
            markup_consumption = self.price_settings.get(
                "per_unit_supplier_gas_markup", 0.0
            )
            tax = self.price_settings.get("per_unit_government_gas_tax", 0.0)
            price = (base_price + markup_consumption + tax) * (
                self.price_settings.get("vat_percentage", 21.0) / 100.0 + 1.0
            )
        else:
            markup_consumption = self.price_settings.get(
                "per_unit_supplier_electricity_markup", 0.0
            )
            markup_production = self.price_settings.get(
                "per_unit_supplier_electricity_production_markup", 0.0
            )
            tax = self.price_settings.get("per_unit_government_electricity_tax", 0.0)
            vat_factor = self.price_settings.get("vat_percentage", 21.0) / 100.0 + 1.0

            if self.source_type == SOURCE_TYPE_CONSUMPTION:
                price = (base_price + markup_consumption + tax) * vat_factor
            elif self.source_type == SOURCE_TYPE_PRODUCTION:
                # For production: markup is the return compensation (added, not subtracted)
                if self.price_settings.get("production_price_include_vat", True):
                    price = (base_price + markup_production) * vat_factor
                else:
                    price = base_price + markup_production
            else:
                return None
        return round(price, 8)

    def _price_with_solar_bonus(self, base_price: float) -> float | None:
        """Return the price for right now, including any solar bonus due.

        _calculate_price carries no bonus term. The paths that set the state
        straight from it would otherwise report a price that the forecast in
        net_prices_today contradicts, because _convert_raw_prices does add the
        bonus. Both must apply the same rule.
        """
        price = self._calculate_price(base_price)
        if price is None:
            return None
        if self.source_type != SOURCE_TYPE_PRODUCTION or not self._solar_bonus_applies(
            bool(self.price_settings.get("solar_bonus_enabled", False))
        ):
            return price

        bonus_base_amount = self._solar_bonus_base_amount(base_price)
        if bonus_base_amount > 0 and self._is_in_bonus_window_at(dt_util.now()):
            percentage = self.price_settings.get("solar_bonus_percentage", 10.0)
            price = round(price + bonus_base_amount * (percentage / 100.0), 8)
        return price

    def _normalize_price_entries(self, entries: Any) -> list[dict[str, Any]] | None:
        """Return list of entries with numeric value field."""
        if not isinstance(entries, list):
            return None

        normalized: list[dict[str, Any]] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            entry_copy = entry.copy()
            value_key = None
            if "value" in entry_copy:
                value_key = "value"
            elif "price" in entry_copy:
                value_key = "price"
            if value_key is None:
                continue
            try:
                numeric_value = float(entry_copy[value_key])
            except (ValueError, TypeError):
                continue
            entry_copy["value"] = numeric_value
            if "price" in entry_copy:
                entry_copy["price"] = numeric_value
            normalized.append(entry_copy)
        return normalized if normalized else None

    def _extract_price_entries(
        self, state: Any, attribute_candidates: tuple[str, ...]
    ) -> list[dict[str, Any]] | None:
        """Extract normalized price entries from the provided state."""
        if state is None:
            return None
        for attr_name in attribute_candidates:
            raw_entries = state.attributes.get(attr_name)
            normalized = self._normalize_price_entries(raw_entries)
            if normalized:
                return normalized
        return None

    def _merge_price_lists(
        self,
        existing: list[dict[str, Any]] | None,
        additions: list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]] | None:
        """Merge price entries by index, summing values."""
        if not additions:
            return existing
        if existing is None:
            return [entry.copy() for entry in additions]

        for idx, entry in enumerate(additions):
            try:
                add_val = float(entry.get("value", 0))
            except (ValueError, TypeError):
                continue
            if idx < len(existing):
                try:
                    base_val = float(existing[idx].get("value", 0))
                except (ValueError, TypeError):
                    base_val = 0.0
                new_val = base_val + add_val
                existing[idx]["value"] = new_val
                if "price" in existing[idx] or "price" in entry:
                    existing[idx]["price"] = new_val
            else:
                entry_copy = entry.copy()
                entry_copy["value"] = add_val
                if "price" in entry_copy:
                    entry_copy["price"] = add_val
                existing.append(entry_copy)
        return existing

    def _sum_price_lists(
        self, lists: list[list[dict[str, Any]]]
    ) -> list[dict[str, Any]] | None:
        """Sum price lists from several sensors by time, not by list position.

        Sources may use different resolutions (quarter-hours and hours) or
        start at different times. The result has one entry per span in which
        every source has a price, valued at the sum of those prices. When a
        list cannot be parsed into time spans, fall back to the index merge.
        """
        if not lists:
            return None
        if len(lists) == 1:
            return [entry.copy() for entry in lists[0]]

        parsed = [_price_intervals(entries) for entries in lists]
        if any(intervals is None for intervals in parsed):
            merged: list[dict[str, Any]] | None = None
            for entries in lists:
                merged = self._merge_price_lists(merged, entries)
            return merged

        all_intervals = [intervals for intervals in parsed if intervals is not None]
        try:
            boundaries = sorted(
                {
                    point
                    for intervals in all_intervals
                    for start, end, _value, _entry in intervals
                    for point in (start, end)
                },
                key=_sort_timestamp,
            )
        except TypeError:  # pragma: no cover - mixed naive/aware across sources
            return None

        result: list[dict[str, Any]] = []
        for seg_start, seg_end in pairwise(boundaries):
            total = 0.0
            template: dict[str, Any] | None = None
            covered = True
            for intervals in all_intervals:
                covering = next(
                    (
                        interval
                        for interval in intervals
                        if interval[0] <= seg_start and seg_end <= interval[1]
                    ),
                    None,
                )
                if covering is None:
                    covered = False
                    break
                total += covering[2]
                if template is None:
                    template = covering[3]
            if not covered or template is None:
                continue
            entry = template.copy()
            if "start" in entry or "time" not in entry:
                entry["start"] = seg_start.isoformat()
            if "time" in entry:
                entry["time"] = seg_start.isoformat()
            entry["end"] = seg_end.isoformat()
            entry["value"] = total
            if "price" in entry:
                entry["price"] = total
            result.append(entry)
        return result or None

    def _is_in_bonus_window_at(self, timestamp: Any) -> bool:
        """Check whether a forecast timestamp falls inside the bonus window.

        Mirrors SolarBonusTracker.is_in_bonus_window for forecast entries,
        which are evaluated at their own timestamp rather than at "now".
        """
        window_mode = self.price_settings.get(
            "solar_bonus_window_mode", SOLAR_BONUS_WINDOW_SUNRISE_SUNSET
        )
        if window_mode != SOLAR_BONUS_WINDOW_FIXED_HOURS:
            return self._is_daylight_at(timestamp)

        dt = _parse_timestamp(timestamp)
        if dt is None:
            _LOGGER.warning("Failed to parse timestamp %s", timestamp)
            return False

        # A fixed window is defined in local clock hours, so compare in the
        # configured timezone rather than whatever the price feed supplied.
        if dt.tzinfo is not None:
            try:
                dt = dt.astimezone(ZoneInfo(str(self.hass.config.time_zone)))
            except KeyError as e:  # pragma: no cover - invalid tz config
                _LOGGER.debug("Could not convert %s to local time: %s", timestamp, e)

        start_hour = int(self.price_settings.get("solar_bonus_start_hour", 6.0))
        end_hour = int(self.price_settings.get("solar_bonus_end_hour", 22.0))
        return bool(start_hour <= dt.hour < end_hour)

    def _is_daylight_at(self, timestamp: Any) -> bool:
        """Check if a given timestamp is during daylight hours.

        Uses Home Assistant's sun integration via astral to calculate
        exact sunrise/sunset times for the timestamp.
        Falls back to conservative hour-based estimate if calculation unavailable.
        """
        dt = _parse_timestamp(timestamp)
        if dt is None:
            # Can't parse timestamp, assume not daylight
            _LOGGER.warning("Failed to parse timestamp %s", timestamp)
            return False

        if not _ASTRAL_AVAILABLE:
            return 7 <= dt.hour < 19

        # Determine the local date for the timestamp.
        try:
            timezone = str(self.hass.config.time_zone)
            if dt.tzinfo is None:
                check_date = dt.date()
                dt = dt.replace(tzinfo=ZoneInfo(timezone))
            else:
                local_dt = dt.astimezone(ZoneInfo(timezone))
                check_date = local_dt.date()

            sunrise, sunset = self._get_sunrise_sunset_times(check_date)
            if sunrise is None or sunset is None:
                return 7 <= dt.hour < 19

            return bool(sunrise <= dt < sunset)
        # KeyError: unknown time zone; TypeError: a naive and an aware
        # datetime compared (e.g. a sun time computed without a time zone)
        except (KeyError, TypeError) as e:
            _LOGGER.debug("Using hour-based daylight check (astral failed: %s)", e)
            return 7 <= dt.hour < 19

    def _average_to_hourly(self, raw_prices: Any) -> Any:
        """Average quarter-hour or sub-hourly price entries to hourly averages.

        Groups entries by hour and calculates the average price for each hour.
        Returns a new list with one entry per hour.
        """
        if not isinstance(raw_prices, list) or not raw_prices:
            return raw_prices

        # Group entries by hour
        hourly_groups: defaultdict[
            tuple[int, int, int, int, timedelta | None],
            list[tuple[datetime, float, dict[str, Any]]],
        ] = defaultdict(list)

        for entry in raw_prices:
            if not isinstance(entry, dict):
                continue

            # Get timestamp
            timestamp = entry.get("start") or entry.get("time")
            if not timestamp:
                continue

            # Get price value
            value_key = None
            if "value" in entry:
                value_key = "value"
            elif "price" in entry:
                value_key = "price"
            if value_key is None:
                continue

            try:
                price_value = float(entry[value_key])
                # Parse timestamp and round to hour
                if isinstance(timestamp, str):
                    dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                else:
                    dt = timestamp

                # The UTC offset is part of the key: on the day DST ends the
                # clock shows the same hour twice, and those are two hours.
                hour_key = (dt.year, dt.month, dt.day, dt.hour, dt.utcoffset())
                hourly_groups[hour_key].append((dt, price_value, entry))
            except (ValueError, TypeError, AttributeError):
                continue

        # Calculate averages and create hourly entries
        averaged = []
        groups = sorted(
            hourly_groups.values(), key=lambda group: _sort_timestamp(group[0][0])
        )
        for entries in groups:
            if not entries:  # pragma: no cover
                continue

            # Calculate average price
            avg_price = sum(price for _, price, _ in entries) / len(entries)

            # Use the first entry as template and update with averaged price
            first_dt, _, first_entry = entries[0]
            template_entry = first_entry.copy()

            # The first entry carries the hour's own date, hour and UTC offset
            hour_start = first_dt.replace(minute=0, second=0, microsecond=0)

            # End time is one hour later
            hour_end = hour_start + timedelta(hours=1)

            if template_entry.get("start"):
                template_entry["start"] = hour_start.isoformat()
            if template_entry.get("time"):
                template_entry["time"] = hour_start.isoformat()
            if template_entry.get("end"):
                template_entry["end"] = hour_end.isoformat()

            # Update price value
            if "value" in template_entry:
                template_entry["value"] = avg_price
            if "price" in template_entry:
                template_entry["price"] = avg_price

            averaged.append(template_entry)

        return averaged if averaged else raw_prices

    def _get_sunrise_sunset_times(
        self, date_obj: Any
    ) -> tuple[datetime | None, datetime | None]:
        """Return (sunrise, sunset) for *date_obj* from the pre-populated cache.

        Call ``_async_prefetch_sun_times`` before this method to avoid blocking
        disk I/O on the event loop.  If the date is missing from the cache
        (e.g. called before prefetch) we fall back to the blocking computation
        with a debug log so the regression is visible.
        """
        if not _ASTRAL_AVAILABLE or not isinstance(date_obj, date):
            return None, None

        if date_obj in self._sun_times_cache:
            return self._sun_times_cache[date_obj]

        # Fallback – should not happen during normal operation because
        # async_update calls _async_prefetch_sun_times first.
        _LOGGER.debug(
            "Sun-times cache miss for %s – computing synchronously (may block loop)",
            date_obj,
        )
        return _compute_sun_times(
            self.hass.config.latitude,
            self.hass.config.longitude,
            str(self.hass.config.time_zone),
            date_obj,
        )

    async def _async_prefetch_sun_times(self, dates: set[date]) -> None:
        """Populate the sun-times cache for *dates* via an executor.

        This ensures that subsequent synchronous calls to
        ``_get_sunrise_sunset_times`` (from ``_convert_raw_prices``,
        ``_is_daylight_at``, ``_schedule_sunrise_sunset_updates``, …) do not
        perform blocking disk I/O on the event loop.
        """
        if not _ASTRAL_AVAILABLE:
            return

        latitude = self.hass.config.latitude
        longitude = self.hass.config.longitude
        timezone = str(self.hass.config.time_zone)

        for d in dates:
            if d not in self._sun_times_cache:
                self._sun_times_cache[d] = await self.hass.async_add_executor_job(
                    _compute_sun_times, latitude, longitude, timezone, d
                )

    def _split_entry_at_sunrise_sunset(
        self, entry: dict[str, Any], sunrise: datetime | None, sunset: datetime | None
    ) -> list[dict[str, Any]]:
        """Split a price entry at sunrise/sunset if they occur within the entry's timespan.

        Returns a list of entries (1-3 items):
        - If no sunrise/sunset in timespan: returns [original entry]
        - If sunrise in timespan: returns [before_sunrise, after_sunrise]
        - If sunset in timespan: returns [before_sunset, after_sunset]
        - If both in timespan: returns [before_sunrise, day, after_sunset]
        """
        timestamp_start = entry.get("start") or entry.get("time")
        timestamp_end = entry.get("end")

        if not timestamp_start or not timestamp_end:
            return [entry]

        start_dt = _parse_timestamp(timestamp_start)
        end_dt = _parse_timestamp(timestamp_end)
        if start_dt is None or end_dt is None:
            _LOGGER.debug("Failed to parse timestamps in price entry: %s", entry)
            return [entry]

        # Check if sunrise or sunset occur within this period
        sunrise_in_period = sunrise and start_dt <= sunrise < end_dt
        sunset_in_period = sunset and start_dt < sunset <= end_dt

        if not sunrise_in_period and not sunset_in_period:
            return [entry]

        # Build list of split points
        split_points = [start_dt]
        if sunrise_in_period:
            assert sunrise is not None
            split_points.append(sunrise)
        if sunset_in_period:
            assert sunset is not None
            split_points.append(sunset)
        split_points.append(end_dt)

        # Create entries for each segment
        result = []
        for i in range(len(split_points) - 1):
            seg_start = split_points[i]
            seg_end = split_points[i + 1]

            # Copy entry
            seg_entry = entry.copy()
            seg_entry["start"] = seg_start.isoformat()
            seg_entry["end"] = seg_end.isoformat()
            if "time" in seg_entry:
                seg_entry["time"] = seg_start.isoformat()

            result.append(seg_entry)

        return result

    def _convert_raw_prices(self, raw_prices: Any) -> list[dict[str, Any]] | None:
        """Convert raw price entries by applying price settings.

        The input may be a list accumulated from multiple price sensors.
        Each entry is copied before modification to avoid mutating the
        original structure.

        For production with solar bonus enabled, entries that span sunrise or
        sunset will be split into separate entries at those exact times.
        """

        if not isinstance(raw_prices, list):
            return None

        # Check if averaging to hourly is enabled
        average_to_hourly = self.price_settings.get("average_prices_to_hourly", True)

        # Average to hourly if enabled
        if average_to_hourly:
            raw_prices = self._average_to_hourly(raw_prices)

        # Check if solar bonus is enabled for production
        solar_bonus_enabled = self.source_type == SOURCE_TYPE_PRODUCTION and bool(
            self.price_settings.get("solar_bonus_enabled", False)
        )
        # Once the period's bonus kWh are used up the tracker pays nothing,
        # so the forecast must not promise a bonus either.
        bonus_applies = self._solar_bonus_applies(solar_bonus_enabled)
        solar_bonus_percentage = self.price_settings.get("solar_bonus_percentage", 10.0)
        solar_bonus_window_mode = self.price_settings.get(
            "solar_bonus_window_mode", SOLAR_BONUS_WINDOW_SUNRISE_SUNSET
        )

        # If solar bonus is enabled AND averaging to hourly is enabled,
        # we need to split entries at sunrise/sunset. A fixed-hour window
        # always falls on whole hours, so those entries need no splitting.
        if (
            solar_bonus_enabled
            and average_to_hourly
            and raw_prices
            and solar_bonus_window_mode != SOLAR_BONUS_WINDOW_FIXED_HOURS
        ):
            # Get all unique dates from entries
            # The averaging step returns its input unchanged when nothing in
            # it could be averaged, so non-dict entries can still be here.
            raw_prices = [entry for entry in raw_prices if isinstance(entry, dict)]
            dates_to_check = set()
            for entry in raw_prices:
                dt = _parse_timestamp(entry.get("start") or entry.get("time"))
                if dt is not None:
                    dates_to_check.add(dt.date())

            # Get sunrise/sunset for all dates
            sun_times = {}
            for date_obj in dates_to_check:
                sunrise, sunset = self._get_sunrise_sunset_times(date_obj)
                sun_times[date_obj] = (sunrise, sunset)

            # Split entries at sunrise/sunset
            split_prices = []
            for entry in raw_prices:
                dt = _parse_timestamp(entry.get("start") or entry.get("time"))
                if dt is None:
                    split_prices.append(entry)
                    continue
                sunrise, sunset = sun_times.get(dt.date(), (None, None))
                try:
                    split_prices.extend(
                        self._split_entry_at_sunrise_sunset(entry, sunrise, sunset)
                    )
                except TypeError as e:
                    # A naive entry compared with an aware sun time
                    _LOGGER.debug("Skipping entry split: %s", e)
                    split_prices.append(entry)

            raw_prices = split_prices

        converted = []
        for entry in raw_prices:
            if not isinstance(entry, dict):
                continue
            value_key = None
            if "value" in entry:
                value_key = "value"
            elif "price" in entry:
                value_key = "price"
            if value_key is None:
                continue
            try:
                base = float(entry[value_key])
            except (ValueError, TypeError):
                continue

            entry_conv = entry.copy()
            calculated = self._calculate_price(base)

            # Apply solar bonus if conditions are met
            solar_bonus_applied = False
            if bonus_applies and calculated is not None:
                # The bonus is paid over the bare market price for some
                # suppliers and over the full compensation for others, so the
                # positive-price condition follows the same amount.
                bonus_base_amount = self._solar_bonus_base_amount(base)

                timestamp = entry_conv.get("start") or entry_conv.get("time")
                in_window = (
                    self._is_in_bonus_window_at(timestamp) if timestamp else False
                )
                if bonus_base_amount > 0 and in_window:
                    calculated += bonus_base_amount * (solar_bonus_percentage / 100.0)
                    solar_bonus_applied = True

            entry_conv["value"] = calculated
            if "price" in entry_conv:
                entry_conv["price"] = calculated
            # Add marker if solar bonus was applied to this entry
            if solar_bonus_enabled:
                entry_conv["solar_bonus_applied"] = solar_bonus_applied
            converted.append(entry_conv)

        return converted

    def _collect_raw_prices(
        self,
    ) -> tuple[list[dict[str, Any]] | None, list[dict[str, Any]] | None]:
        """Return the summed raw price lists for today and tomorrow.

        A sensor without any price list (e.g. a fixed surcharge) adds its
        current value to every entry. A sensor with lists that lacks the list
        for a day makes that day unknown, since a partial sum would be wrong.
        """
        lists: dict[str, list[list[dict[str, Any]]]] = {"today": [], "tomorrow": []}
        known = {"today": True, "tomorrow": True}
        constant = 0.0
        for sensor in self.price_sensors:
            state = self.hass.states.get(sensor)
            if state is None:  # pragma: no cover - checked by read_price_sum
                continue
            per_day = {
                "today": self._extract_price_entries(
                    state, ("raw_today", "prices_today")
                ),
                "tomorrow": self._extract_price_entries(
                    state, ("raw_tomorrow", "prices_tomorrow")
                ),
            }
            if per_day["today"] is None and per_day["tomorrow"] is None:
                constant += float(state.state)
                continue
            for day, entries in per_day.items():
                if entries is None:
                    known[day] = False
                else:
                    lists[day].append(entries)

        result: dict[str, list[dict[str, Any]] | None] = {}
        for day in ("today", "tomorrow"):
            summed = self._sum_price_lists(lists[day]) if known[day] else None
            if summed and constant:
                for entry in summed:
                    entry["value"] = float(entry["value"]) + constant
                    if "price" in entry:
                        entry["price"] = entry["value"]
            result[day] = summed
        return result["today"], result["tomorrow"]

    def _set_price_from_sensors(self) -> None:
        """Set the state straight from the summed price sensors."""
        total_price, _problems = read_price_sum(self.hass, self.price_sensors)
        if total_price is None:
            self._attr_available = False
            return
        self._attr_available = True
        price = self._price_with_solar_bonus(total_price)
        if price is not None:
            self._attr_native_value = price

    async def async_update(self) -> None:
        self._bonus_limit_reached = self._solar_bonus_limit_reached()
        total_price_or_none, problems = read_price_sum(self.hass, self.price_sensors)
        if total_price_or_none is None:
            for sensor, problem in problems.items():
                _LOGGER.warning("Price sensor %s is %s", sensor, problem)
            self._attr_available = False
            return
        self._attr_available = True
        total_price = total_price_or_none
        raw_today, raw_tomorrow = self._collect_raw_prices()

        # Pre-populate the sun-times cache in an executor so that subsequent
        # synchronous helpers (_convert_raw_prices, _is_daylight_at,
        # _schedule_sunrise_sunset_updates) never block the event loop via pytz.
        today = dt_util.now().date()
        tomorrow = today + timedelta(days=1)
        dates_needed: set[date] = {today, tomorrow}
        for price_list in (raw_today, raw_tomorrow):
            if isinstance(price_list, list):
                for entry in price_list:
                    ts = entry.get("start") or entry.get("time")
                    if isinstance(ts, str):
                        try:
                            dates_needed.add(
                                datetime.fromisoformat(ts.replace("Z", "+00:00")).date()
                            )
                        except ValueError:
                            pass
        await self._async_prefetch_sun_times(dates_needed)

        self._net_today = self._convert_raw_prices(raw_today)
        self._net_tomorrow = self._convert_raw_prices(raw_tomorrow)

        # Build attributes dictionary; cap lists to stay below the 16 KB HA limit.
        cap = _MAX_NET_PRICE_STEPS
        attributes: dict[str, Any] = {
            "net_prices_today": self._net_today[:cap]
            if self._net_today
            else self._net_today,
            "net_prices_tomorrow": self._net_tomorrow[:cap]
            if self._net_tomorrow
            else self._net_tomorrow,
        }

        # Add sunrise/sunset info for production sensors with solar bonus
        if self.source_type == SOURCE_TYPE_PRODUCTION and self.price_settings.get(
            "solar_bonus_enabled", False
        ):
            sunrise_today, sunset_today = self._get_sunrise_sunset_times(today)
            sunrise_tomorrow, sunset_tomorrow = self._get_sunrise_sunset_times(tomorrow)

            if sunrise_today:
                attributes["sunrise_today"] = sunrise_today.isoformat()
            if sunset_today:
                attributes["sunset_today"] = sunset_today.isoformat()
            if sunrise_tomorrow:
                attributes["sunrise_tomorrow"] = sunrise_tomorrow.isoformat()
            if sunset_tomorrow:
                attributes["sunset_tomorrow"] = sunset_tomorrow.isoformat()

        self._attr_extra_state_attributes = attributes

        # Check if we need scheduling
        average_to_hourly = self.price_settings.get("average_prices_to_hourly", True)
        solar_bonus_enabled = (
            self.source_type == SOURCE_TYPE_PRODUCTION
            and self.price_settings.get("solar_bonus_enabled", False)
        )

        if average_to_hourly:
            # With averaging: use scheduled updates based on net_prices (includes splits at sunrise/sunset)
            self._update_current_price()
            self._schedule_next_price_change()
        else:
            # Without averaging: calculate price directly from current base price
            price = self._price_with_solar_bonus(total_price)
            if price is not None:
                self._attr_native_value = price

            # But still schedule window updates if solar bonus is enabled
            if solar_bonus_enabled:
                self._schedule_bonus_window_updates()

    @staticmethod
    def _price_at(entries: list[dict[str, Any]] | None, now: datetime) -> Any:
        """Return the value of the entry whose span contains *now*, if any."""
        for entry in entries or []:
            start_dt = _parse_timestamp(entry.get("start") or entry.get("time"))
            end_dt = _parse_timestamp(entry.get("end"))
            if start_dt is None or end_dt is None:
                continue
            try:
                if start_dt <= now < end_dt:
                    return entry.get("value")
            except TypeError:
                _LOGGER.debug("Skipping price entry without time zone: %s", entry)
        return None

    def _update_current_price(self) -> None:
        """Update the current price based on the current time and net_prices."""
        now = dt_util.now()

        # Find current price from net_prices_today or net_prices_tomorrow
        current_price = None
        for entries in (self._net_today, self._net_tomorrow):
            current_price = self._price_at(entries, now)
            if current_price is not None:
                break

        if current_price is not None:
            self._attr_native_value = current_price
        else:
            # Fallback: calculate from current base price
            self._set_price_from_sensors()

    def _schedule_next_price_change(self) -> None:
        """Schedule the next price change based on net_prices."""
        # Cancel existing schedule
        if self._price_change_unsub:
            self._price_change_unsub()
            self._price_change_unsub = None

        now = dt_util.now()
        next_change: datetime | None = None

        # Find next price change time
        all_prices: list[dict[str, Any]] = []
        if self._net_today:
            all_prices.extend(self._net_today)
        if self._net_tomorrow:
            all_prices.extend(self._net_tomorrow)

        for entry in all_prices:
            start_dt = _parse_timestamp(entry.get("start") or entry.get("time"))
            if start_dt is None:
                continue
            try:
                is_next = start_dt > now and (
                    next_change is None or start_dt < next_change
                )
            except TypeError:
                _LOGGER.debug("Skipping price entry without time zone: %s", entry)
                continue
            if is_next:
                next_change = start_dt

        if next_change:
            _LOGGER.debug(
                "Scheduling next price change for %s at %s", self.entity_id, next_change
            )

            async def handle_next_change(now: datetime) -> None:
                """Handle the next scheduled price change."""
                self._update_current_price()
                self.async_write_ha_state()
                self._schedule_next_price_change()

            self._price_change_unsub = async_track_point_in_time(
                self.hass, handle_next_change, next_change
            )

    def _schedule_bonus_window_updates(self) -> None:
        """Schedule updates at the edges of the solar bonus window.

        Used when average_prices_to_hourly is False but solar_bonus is
        enabled. Without per-entry prices to drive the schedule, the sensor
        has to wake itself when the bonus starts or stops applying — at
        sunrise and sunset, or at the fixed window hours.
        """
        # Cancel existing schedule
        if self._price_change_unsub:
            self._price_change_unsub()
            self._price_change_unsub = None

        now = dt_util.now()
        today = now.date()
        tomorrow = today + timedelta(days=1)

        candidates: list[datetime] = []
        if (
            self.price_settings.get(
                "solar_bonus_window_mode", SOLAR_BONUS_WINDOW_SUNRISE_SUNSET
            )
            == SOLAR_BONUS_WINDOW_FIXED_HOURS
        ):
            # Boundaries are local clock hours; combining with the current
            # tzinfo keeps them right across a DST change.
            start_hour = int(self.price_settings.get("solar_bonus_start_hour", 6.0))
            end_hour = int(self.price_settings.get("solar_bonus_end_hour", 22.0))
            candidates = [
                datetime.combine(day, time(hour=hour % 24), tzinfo=now.tzinfo)
                for day in (today, tomorrow)
                for hour in (start_hour, end_hour)
            ]
        else:
            for day in (today, tomorrow):
                sunrise, sunset = self._get_sunrise_sunset_times(day)
                candidates.extend(event for event in (sunrise, sunset) if event)

        upcoming = [event for event in candidates if event > now]
        next_event = min(upcoming) if upcoming else None

        if next_event:
            _LOGGER.debug(
                "Scheduling bonus window update for %s at %s",
                self.entity_id,
                next_event,
            )

            async def handle_window_event(now: datetime) -> None:
                """Handle a window edge - recalculate price and reschedule."""
                self._set_price_from_sensors()
                self.async_write_ha_state()
                self._schedule_bonus_window_updates()

            self._price_change_unsub = async_track_point_in_time(
                self.hass, handle_window_event, next_event
            )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # Track price sensor changes to update net_prices
        for sensor in self.price_sensors:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass,
                    sensor,
                    self._handle_price_change,
                )
            )
        if self._solar_bonus_tracker is not None and self.source_type == (
            SOURCE_TYPE_PRODUCTION
        ):
            self.async_on_remove(
                self._solar_bonus_tracker.async_add_listener(
                    self._handle_solar_bonus_update
                )
            )

    @callback
    def _handle_solar_bonus_update(self) -> None:
        """Rebuild the prices when the bonus limit is reached or resets."""
        if self._solar_bonus_limit_reached() != self._bonus_limit_reached:
            self.async_schedule_update_ha_state(True)

    async def async_will_remove_from_hass(self) -> None:
        """Clean up when removing entity."""
        if self._price_change_unsub:
            self._price_change_unsub()
            self._price_change_unsub = None
        await super().async_will_remove_from_hass()

    async def _handle_price_change(self, event: Event[EventStateChangedData]) -> None:
        """Handle price sensor state change - rebuild net_prices and reschedule."""
        # async_update decides availability from all price sensors together,
        # and the state is written either way so an outage is visible.
        await self.async_update()
        self.async_write_ha_state()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    from . import DynamicEnergyConfigEntry

    typed_entry: DynamicEnergyConfigEntry = entry
    price_settings = entry.options.get(
        CONF_PRICE_SETTINGS, entry.data.get(CONF_PRICE_SETTINGS, {})
    )
    price_sensor = entry.options.get(
        CONF_PRICE_SENSOR, entry.data.get(CONF_PRICE_SENSOR)
    )
    price_sensor_gas = entry.options.get(
        CONF_PRICE_SENSOR_GAS, entry.data.get(CONF_PRICE_SENSOR_GAS)
    )
    if isinstance(price_sensor, str):
        price_sensor = [price_sensor]
    if isinstance(price_sensor_gas, str):
        price_sensor_gas = [price_sensor_gas]
    entities: list[BaseUtilitySensor] = []

    netting_enabled = bool(price_settings.get("netting_enabled"))
    netting_tracker: NettingTracker | None = None
    if netting_enabled:
        netting_map = hass.data.setdefault(DOMAIN, {}).setdefault("netting", {})
        tracker = netting_map.get(entry.entry_id)
        if tracker is None:
            tracker = await NettingTracker.async_create(
                hass, entry.entry_id, price_settings
            )
            netting_map[entry.entry_id] = tracker
        else:
            tracker.update_price_settings(price_settings)
        netting_tracker = tracker

    solar_bonus_tracker: SolarBonusTracker | None = None
    if price_settings.get("solar_bonus_enabled"):
        solar_bonus_tracker = await async_get_solar_bonus_tracker(
            hass, entry.entry_id, price_settings
        )

    contract_year = _ContractYearReset(
        hass, entry.entry_id, price_settings, netting_tracker, solar_bonus_tracker
    )
    missed_reset = await contract_year.async_catch_up()

    # Per-entry list of DynamicEnergySensors (for TotalCostSensor aggregation)
    source_sensors: list[DynamicEnergySensor] = []
    current_unique_ids: set[str] = set()
    current_base_ids: set[str] = set()
    dev_reg = dr.async_get(hass)

    # Register source entities grouped per sub-entry so HA associates them correctly
    for subentry in entry.subentries.values():
        if subentry.subentry_type != SUBENTRY_TYPE_SOURCE:
            continue

        block = dict(subentry.data)
        source_type = block[CONF_SOURCE_TYPE]
        sources = block[CONF_SOURCES]
        subentry_entities: list[BaseUtilitySensor] = []

        mode_defs: list[dict[str, Any]]
        if source_type == SOURCE_TYPE_GAS:
            selected_price_sensor = price_sensor_gas
            mode_defs = SENSOR_MODES_GAS
        else:
            selected_price_sensor = price_sensor
            mode_defs = SENSOR_MODES_ELECTRICITY

        for sensor in sources:
            base_id = sensor.replace(".", "_")
            current_base_ids.add(base_id)
            state = hass.states.get(sensor)
            friendly_name = state.attributes.get("friendly_name") if state else sensor
            device_info = DeviceInfo(
                identifiers={(DOMAIN, base_id)},
                name=f"{DOMAIN_ABBREVIATION}: {friendly_name}",
                entry_type=DeviceEntryType.SERVICE,
                manufacturer="DynamicEnergyCalc",
                model=source_type,
            )

            for mode_def in mode_defs:
                mode = mode_def["key"]
                if not selected_price_sensor and mode not in ("kwh_total", "m3_total"):
                    continue
                uid = f"{DOMAIN}_{base_id}_{mode}"
                current_unique_ids.add(uid)
                tracker_arg = (
                    netting_tracker
                    if netting_tracker
                    and source_type in (SOURCE_TYPE_CONSUMPTION, SOURCE_TYPE_PRODUCTION)
                    else None
                )
                solar_tracker_arg = (
                    solar_bonus_tracker
                    if solar_bonus_tracker and source_type == SOURCE_TYPE_PRODUCTION
                    else None
                )
                sensor_entity = DynamicEnergySensor(
                    hass=hass,
                    name=mode_def.get("translation_key", mode),
                    unique_id=uid,
                    energy_sensor=sensor,
                    price_sensor=selected_price_sensor,
                    price_settings=price_settings,
                    mode=mode,
                    source_type=source_type,
                    unit=mode_def["unit"],
                    icon=mode_def["icon"],
                    visible=mode_def["visible"],
                    device=device_info,
                    netting_tracker=tracker_arg,
                    solar_bonus_tracker=solar_tracker_arg,
                )
                subentry_entities.append(sensor_entity)
                source_sensors.append(sensor_entity)

        # Give each source device the subentry it is configured in now. This
        # covers devices from pre-subentry installs (owned by the main entry)
        # and sources moved to another subentry by a reconfigure. It must
        # happen before async_add_entities so the device already has the
        # right subentry when HA processes the entities.
        for sensor in sources:
            base_id = sensor.replace(".", "_")
            existing = find_entry_device(dev_reg, (DOMAIN, base_id), entry.entry_id)
            if existing is None:
                continue
            owners = device_subentry_ids(existing, entry.entry_id)
            if owners and owners != {subentry.subentry_id}:
                move_device_to_subentry(
                    dev_reg, existing, entry.entry_id, subentry.subentry_id
                )

        _mark_missed_reset(subentry_entities, missed_reset)
        async_add_entities(
            subentry_entities, True, config_subentry_id=subentry.subentry_id
        )
        entities.extend(subentry_entities)

    _async_remove_stale_sources(
        hass, entry.entry_id, current_unique_ids, current_base_ids
    )

    unique_id = f"{DOMAIN}_{SUMMARY_DEVICE_ID}"
    device_info = DeviceInfo(
        identifiers={(DOMAIN, SUMMARY_DEVICE_ID)},
        name=f"{DOMAIN_ABBREVIATION}: Summary Sensors",
        entry_type=DeviceEntryType.SERVICE,
        manufacturer="DynamicEnergyCalc",
        model="summary",
    )

    daily_electricity = DailyElectricityCostSensor(
        hass=hass,
        name="Electricity Contract Fixed Costs (Total)",
        unique_id=unique_id,
        price_settings=price_settings,
        device=device_info,
        netting_tracker=netting_tracker,
    )

    daily_gas = DailyGasCostSensor(
        hass=hass,
        name="Gas Contract Fixed Costs (Total)",
        unique_id=f"{DOMAIN}_daily_gas_cost",
        price_settings=price_settings,
        device=device_info,
    )

    net_cost = TotalCostSensor(
        hass=hass,
        name="Net Energy Cost (Total)",
        unique_id=f"{DOMAIN}_net_total_cost",
        device=device_info,
        source_sensors=source_sensors,
        netting_tracker=netting_tracker,
    )

    energy_cost = TotalEnergyCostSensor(
        hass=hass,
        name="Energy Contract Cost (Total)",
        unique_id=f"{DOMAIN}_total_energy_cost",
        net_cost_unique_id=net_cost.unique_id or "",
        fixed_cost_unique_ids=[
            daily_electricity.unique_id or "",
            daily_gas.unique_id or "",
        ],
        device=device_info,
        netting_tracker=netting_tracker,
    )

    summary_entities: list[BaseUtilitySensor] = [
        daily_electricity,
        daily_gas,
        net_cost,
        energy_cost,
    ]

    # Add solar bonus sensor if enabled
    if solar_bonus_tracker is not None:
        summary_entities.append(
            SolarBonusStatusSensor(
                hass=hass,
                name="Solar Bonus (Total)",
                unique_id=f"{DOMAIN}_solar_bonus_total",
                device=device_info,
                solar_bonus_tracker=solar_bonus_tracker,
            )
        )

    if price_sensor:
        summary_entities.append(
            CurrentElectricityPriceSensor(
                hass=hass,
                name="Current Consumption Price",
                unique_id=f"{DOMAIN}_current_consumption_price",
                price_sensor=price_sensor,
                source_type=SOURCE_TYPE_CONSUMPTION,
                price_settings=price_settings,
                # MDI names these from the tower's point of view, which reads
                # backwards here: -export is tagged power-from-grid and
                # -import power-to-grid / return-to-grid. SENSOR_MODES_ELECTRICITY
                # above already follows that.
                icon="mdi:transmission-tower-export",
                device=device_info,
            )
        )
        summary_entities.append(
            CurrentElectricityPriceSensor(
                hass=hass,
                name="Current Production Price",
                unique_id=f"{DOMAIN}_current_production_price",
                price_sensor=price_sensor,
                source_type=SOURCE_TYPE_PRODUCTION,
                price_settings=price_settings,
                icon="mdi:transmission-tower-import",
                device=device_info,
                solar_bonus_tracker=solar_bonus_tracker,
            )
        )

    if price_sensor_gas:
        summary_entities.append(
            CurrentElectricityPriceSensor(
                hass=hass,
                name="Current Gas Consumption Price",
                unique_id=f"{DOMAIN}_current_gas_consumption_price",
                price_sensor=price_sensor_gas,
                source_type=SOURCE_TYPE_GAS,
                price_settings=price_settings,
                icon="mdi:gas-burner",
                device=device_info,
            )
        )

    # Summary sensors belong to the main config entry (no sub-entry)
    _mark_missed_reset(summary_entities, missed_reset)
    async_add_entities(summary_entities, True)
    entities.extend(summary_entities)

    # Store entities and trackers in per-entry runtime_data
    typed_entry.runtime_data.entities = {ent.entity_id: ent for ent in entities}
    typed_entry.runtime_data.netting_tracker = netting_tracker
    typed_entry.runtime_data.solar_bonus_tracker = solar_bonus_tracker

    daily_sensors: list[_DailyCostSensor] = [daily_electricity, daily_gas]

    async def handle_midnight(now: datetime) -> None:
        """Run the contract-year reset first, then add the new day's fixed costs.

        Both happen at 00:00. A single handler fixes their order, so the fixed
        costs of the first day of a contract year are not wiped by its reset.
        """
        await contract_year.async_handle_midnight(now.date(), entities)
        for daily_sensor in daily_sensors:
            await daily_sensor._handle_daily_addition(now)

    # Run at midnight every day; unsubscribe when entry is unloaded
    entry.async_on_unload(
        async_track_time_change(hass, handle_midnight, hour=0, minute=0, second=0)
    )


def _mark_missed_reset(
    entities: list[BaseUtilitySensor], missed_reset: date | None
) -> None:
    """Make the entities restore as zero when a contract-year reset was missed."""
    if missed_reset is None:
        return
    for entity in entities:
        if entity._resets_with_contract_year:
            entity._reset_on_restore = missed_reset


class _ContractYearReset:
    """Reset meters and trackers on each contract anniversary.

    The date of the last reset is stored so an anniversary that passed while
    Home Assistant was not running is still applied at the next start.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        price_settings: dict[str, Any],
        netting_tracker: NettingTracker | None,
        solar_bonus_tracker: SolarBonusTracker | None,
    ) -> None:
        self._start: date | None = None
        if price_settings.get("reset_on_contract_anniversary"):
            self._start = parse_contract_date(
                price_settings.get("contract_start_date", "")
            )
        self._netting_tracker = netting_tracker
        self._solar_bonus_tracker = solar_bonus_tracker
        self._store: Store[dict[str, Any]] = Store(
            hass,
            CONTRACT_STORAGE_VERSION,
            f"{CONTRACT_STORAGE_KEY_PREFIX}_{entry_id}",
            private=True,
        )

    async def _async_reset_trackers(self) -> None:
        if self._netting_tracker is not None:
            await self._netting_tracker.async_reset_all()
        # The solar bonus limit follows its own period. A calendar-year limit
        # must not restart on the contract anniversary, and a contract-year
        # limit already rolls over by itself; resetting it here keeps it in
        # step with the meters.
        if (
            self._solar_bonus_tracker is not None
            and self._solar_bonus_tracker.limit_period
            == SOLAR_BONUS_LIMIT_CONTRACT_YEAR
        ):
            await self._solar_bonus_tracker.async_reset_year()

    async def async_catch_up(self) -> date | None:
        """Apply a reset missed while not running; return its anniversary.

        Entities are not restored yet at this point, so the caller marks them
        to restore as zero instead.
        """
        if self._start is None:
            return None
        anniversary = latest_anniversary(self._start, dt_util.now().date())
        stored = await self._store.async_load() or {}
        last_reset = parse_contract_date(stored.get("last_reset"))
        missed = last_reset is not None and last_reset < anniversary
        if missed:
            _LOGGER.info(
                "Contract anniversary %s passed while not running, resetting meters",
                anniversary,
            )
            await self._async_reset_trackers()
        if last_reset is None or missed:
            # Without a stored date (first run, or an upgrade) there is no
            # way to tell whether a reset was missed, so assume it was not.
            await self._store.async_save({"last_reset": anniversary.isoformat()})
        return anniversary if missed else None

    async def async_handle_midnight(
        self, today: date, entities: list[BaseUtilitySensor]
    ) -> None:
        if self._start is None or not is_anniversary(self._start, today):
            return
        _LOGGER.info("Contract anniversary reached, resetting all meters")
        await self._async_reset_trackers()
        for entity in entities:
            if entity._resets_with_contract_year:
                await entity.async_reset()
        await self._store.async_save({"last_reset": today.isoformat()})


@callback
def _async_remove_stale_sources(
    hass: HomeAssistant,
    entry_id: str,
    current_unique_ids: set[str],
    current_base_ids: set[str],
) -> None:
    """Remove source entities and devices that are no longer configured.

    Reconfiguring a subentry can drop a source sensor, or drop the price
    sensor so that only the kWh modes remain. Their old entities would
    otherwise stay in the registry as unavailable forever.
    """
    ent_reg = er.async_get(hass)
    for entity_entry in er.async_entries_for_config_entry(ent_reg, entry_id):
        if (
            entity_entry.domain == "sensor"
            and entity_entry.config_subentry_id is not None
            and entity_entry.unique_id not in current_unique_ids
        ):
            _LOGGER.info("Removing stale entity %s", entity_entry.entity_id)
            ent_reg.async_remove(entity_entry.entity_id)

    dev_reg = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(dev_reg, entry_id):
        identifiers = {
            identifier for domain, identifier in device.identifiers if domain == DOMAIN
        }
        if not identifiers or identifiers & (current_base_ids | {SUMMARY_DEVICE_ID}):
            continue
        _LOGGER.info("Removing stale device %s", device.name)
        remove_device_from_entry(dev_reg, device, entry_id)
