from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorStateClass
from homeassistant.const import UnitOfEnergy, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_change,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.device_registry import DeviceEntryType

from .const import (
    DOMAIN,
    DOMAIN_ABBREVIATION,
    CONF_CONFIGS,
    CONF_SOURCE_TYPE,
    CONF_SOURCES,
    CONF_PRICE_SENSOR,
    CONF_PRICE_SENSOR_GAS,
    CONF_PRICE_SETTINGS,
    SOURCE_TYPE_CONSUMPTION,
    SOURCE_TYPE_PRODUCTION,
    SOURCE_TYPE_GAS,
)
from .entity import BaseUtilitySensor, DynamicEnergySensor
from .netting import NettingTracker
from .solar_bonus import SolarBonusTracker

import logging

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1

SENSOR_MODES_ELECTRICITY = [
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

SENSOR_MODES_GAS = [
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

UTILITY_ENTITIES: list[BaseUtilitySensor] = []


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

    async def async_update(self):
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
        self._netting_tracker = netting_tracker
        self._update_netting_attributes()

    async def async_update(self):
        cost_total = 0.0
        profit_total = 0.0

        for entity in UTILITY_ENTITIES:
            if isinstance(entity, DynamicEnergySensor):
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

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        for entity in UTILITY_ENTITIES:
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

    async def _handle_input_event(self, event):
        _LOGGER.debug(
            "%s changed, updating %s", event.data.get("entity_id"), self.entity_id
        )
        await self.async_update()
        self.async_write_ha_state()


class DailyElectricityCostSensor(NettingStatusMixin, BaseUtilitySensor):
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

    async def async_update(self):
        self._update_netting_attributes()

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self._update_netting_attributes()
        self.async_on_remove(
            async_track_time_change(
                self.hass,
                self._handle_daily_addition,
                hour=0,
                minute=0,
                second=0,
            )
        )

    async def _handle_daily_addition(self, now):
        addition = self._calculate_daily_cost()
        _LOGGER.debug(
            "Adding daily electricity cost %s at %s to %s",
            addition,
            now,
            self.entity_id,
        )
        self._attr_native_value += addition
        self._update_netting_attributes()
        self.async_write_ha_state()


class DailyGasCostSensor(BaseUtilitySensor):
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

    async def async_update(self):
        pass

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(
            async_track_time_change(
                self.hass,
                self._handle_daily_addition,
                hour=0,
                minute=0,
                second=0,
            )
        )

    async def _handle_daily_addition(self, now):
        addition = self._calculate_daily_cost()
        _LOGGER.debug(
            "Adding daily gas cost %s at %s to %s",
            addition,
            now,
            self.entity_id,
        )
        self._attr_native_value += addition
        self.async_write_ha_state()


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

    async def async_update(self):
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

    async def async_added_to_hass(self):
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

    async def _handle_input_event(self, event):
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
        self._net_today = None
        self._net_tomorrow = None
        self._attr_extra_state_attributes = {
            "net_prices_today": None,
            "net_prices_tomorrow": None,
        }
        self._price_change_unsub = None

    def _calculate_price(self, base_price: float) -> float:
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

    def _normalize_price_entries(self, entries):
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

    def _extract_price_entries(self, state, attribute_candidates):
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
            if not isinstance(entry, dict):
                continue
            try:
                add_val = float(entry.get("value"))
            except (ValueError, TypeError):
                continue
            if idx < len(existing):
                try:
                    base_val = float(existing[idx].get("value"))
                except (ValueError, TypeError):
                    base_val = 0.0
                new_val = base_val + add_val
                existing[idx]["value"] = new_val
                if "price" in existing[idx]:
                    existing[idx]["price"] = new_val
                elif "price" in entry:
                    existing[idx]["price"] = new_val
            else:
                entry_copy = entry.copy()
                entry_copy["value"] = add_val
                if "price" in entry_copy:
                    entry_copy["price"] = add_val
                existing.append(entry_copy)
        return existing

    def _is_daylight_at(self, timestamp) -> bool:
        """Check if a given timestamp is during daylight hours.

        Uses Home Assistant's sun integration via astral to calculate
        exact sunrise/sunset times for the timestamp.
        Falls back to conservative hour-based estimate if calculation unavailable.
        """
        from datetime import datetime

        # Parse timestamp first (outside try-except to use in fallback)
        try:
            if isinstance(timestamp, str):
                dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            else:
                dt = timestamp
        except Exception as e:
            # Can't parse timestamp, assume not daylight
            _LOGGER.warning("Failed to parse timestamp %s: %s", timestamp, e)
            return False

        # Try to use astral for precise calculation
        try:
            from astral import LocationInfo
            from astral.sun import sun

            # Get location from Home Assistant config
            latitude = self.hass.config.latitude
            longitude = self.hass.config.longitude
            timezone = str(self.hass.config.time_zone)

            # Validate we have location data
            if latitude is None or longitude is None:
                raise ValueError("No location configured")

            # Create location info
            location = LocationInfo(
                name="Home",
                region="",
                timezone=timezone,
                latitude=latitude,
                longitude=longitude
            )

            # Calculate sun times for the date of the timestamp
            # Use the date in the local timezone
            if dt.tzinfo is None:
                # Assume local time if no timezone
                check_date = dt.date()
            else:
                # Convert to local timezone
                import pytz
                local_tz = pytz.timezone(timezone)
                local_dt = dt.astimezone(local_tz)
                check_date = local_dt.date()

            s = sun(location.observer, date=check_date, tzinfo=timezone)
            sunrise = s["sunrise"]
            sunset = s["sunset"]

            # Compare timestamp with sunrise/sunset
            # Make sure we're comparing timezone-aware datetimes
            if dt.tzinfo is None:
                import pytz
                local_tz = pytz.timezone(timezone)
                dt = local_tz.localize(dt)

            return sunrise <= dt < sunset

        except Exception as e:
            # astral calculation failed, use hour-based fallback
            _LOGGER.debug("Using hour-based daylight check (astral failed: %s)", e)
            # Fallback: Conservative hour-based check
            # 7 AM to 7 PM covers daylight hours year-round in NL
            return 7 <= dt.hour < 19

    def _average_to_hourly(self, raw_prices):
        """Average quarter-hour or sub-hourly price entries to hourly averages.

        Groups entries by hour and calculates the average price for each hour.
        Returns a new list with one entry per hour.
        """
        if not isinstance(raw_prices, list) or not raw_prices:
            return raw_prices

        from datetime import datetime
        from collections import defaultdict

        # Group entries by hour
        hourly_groups = defaultdict(list)

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

                # Create hour key (year, month, day, hour)
                hour_key = (dt.year, dt.month, dt.day, dt.hour)
                hourly_groups[hour_key].append((price_value, entry))
            except (ValueError, TypeError, AttributeError):
                continue

        # Calculate averages and create hourly entries
        averaged = []
        for hour_key, entries in sorted(hourly_groups.items()):
            if not entries:
                continue

            # Calculate average price
            avg_price = sum(price for price, _ in entries) / len(entries)

            # Use the first entry as template and update with averaged price
            template_entry = entries[0][1].copy()

            # Get the original datetime to preserve timezone
            timestamp = template_entry.get("start") or template_entry.get("time")
            if isinstance(timestamp, str):
                original_dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            else:
                original_dt = timestamp

            # Set the timestamp to the start of the hour, preserving timezone
            year, month, day, hour = hour_key
            if original_dt.tzinfo:
                # Preserve timezone from original
                hour_start = original_dt.replace(year=year, month=month, day=day, hour=hour, minute=0, second=0, microsecond=0)
            else:
                hour_start = datetime(year, month, day, hour)

            # End time is one hour later
            from datetime import timedelta

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

    def _get_sunrise_sunset_times(self, date_obj):
        """Get sunrise and sunset times for a specific date.

        Returns tuple of (sunrise, sunset) as datetime objects, or (None, None) if unavailable.
        """
        try:
            from astral import LocationInfo
            from astral.sun import sun

            latitude = self.hass.config.latitude
            longitude = self.hass.config.longitude
            timezone = str(self.hass.config.time_zone)

            location = LocationInfo(
                name="Home",
                region="",
                timezone=timezone,
                latitude=latitude,
                longitude=longitude
            )

            s = sun(location.observer, date=date_obj, tzinfo=timezone)
            return s["sunrise"], s["sunset"]
        except Exception:
            return None, None

    def _split_entry_at_sunrise_sunset(self, entry, sunrise, sunset):
        """Split a price entry at sunrise/sunset if they occur within the entry's timespan.

        Returns a list of entries (1-3 items):
        - If no sunrise/sunset in timespan: returns [original entry]
        - If sunrise in timespan: returns [before_sunrise, after_sunrise]
        - If sunset in timespan: returns [before_sunset, after_sunset]
        - If both in timespan: returns [before_sunrise, day, after_sunset]
        """
        from datetime import datetime

        timestamp_start = entry.get("start") or entry.get("time")
        timestamp_end = entry.get("end")

        if not timestamp_start or not timestamp_end:
            return [entry]

        # Parse timestamps
        try:
            if isinstance(timestamp_start, str):
                start_dt = datetime.fromisoformat(timestamp_start.replace("Z", "+00:00"))
            else:
                start_dt = timestamp_start

            if isinstance(timestamp_end, str):
                end_dt = datetime.fromisoformat(timestamp_end.replace("Z", "+00:00"))
            else:
                end_dt = timestamp_end
        except Exception:
            return [entry]

        # Check if sunrise or sunset occur within this period
        sunrise_in_period = sunrise and start_dt <= sunrise < end_dt
        sunset_in_period = sunset and start_dt < sunset <= end_dt

        if not sunrise_in_period and not sunset_in_period:
            return [entry]

        # Build list of split points
        split_points = [start_dt]
        if sunrise_in_period:
            split_points.append(sunrise)
        if sunset_in_period:
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

    def _convert_raw_prices(self, raw_prices):
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
        solar_bonus_enabled = (
            self.source_type == SOURCE_TYPE_PRODUCTION
            and self.price_settings.get("solar_bonus_enabled", False)
        )
        solar_bonus_percentage = self.price_settings.get("solar_bonus_percentage", 10.0)

        # If solar bonus is enabled AND averaging to hourly is enabled,
        # we need to split entries at sunrise/sunset
        if solar_bonus_enabled and average_to_hourly and raw_prices:
            from datetime import datetime

            # Get all unique dates from entries
            dates_to_check = set()
            for entry in raw_prices:
                timestamp = entry.get("start") or entry.get("time")
                if timestamp:
                    try:
                        if isinstance(timestamp, str):
                            dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                        else:
                            dt = timestamp
                        dates_to_check.add(dt.date())
                    except Exception:
                        pass

            # Get sunrise/sunset for all dates
            sun_times = {}
            for date_obj in dates_to_check:
                sunrise, sunset = self._get_sunrise_sunset_times(date_obj)
                sun_times[date_obj] = (sunrise, sunset)

            # Split entries at sunrise/sunset
            split_prices = []
            for entry in raw_prices:
                timestamp = entry.get("start") or entry.get("time")
                if timestamp:
                    try:
                        if isinstance(timestamp, str):
                            dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                        else:
                            dt = timestamp
                        date_key = dt.date()
                        sunrise, sunset = sun_times.get(date_key, (None, None))

                        # Split entry if needed
                        segments = self._split_entry_at_sunrise_sunset(entry, sunrise, sunset)
                        split_prices.extend(segments)
                    except Exception:
                        split_prices.append(entry)
                else:
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
            if solar_bonus_enabled and calculated > 0:
                # Check if this hour is during daylight
                timestamp = entry_conv.get("start") or entry_conv.get("time")
                is_daylight = self._is_daylight_at(timestamp) if timestamp else False
                if is_daylight:
                    # Add solar bonus (10% extra)
                    bonus = calculated * (solar_bonus_percentage / 100.0)
                    calculated += bonus
                    solar_bonus_applied = True

            entry_conv["value"] = calculated
            if "price" in entry_conv:
                entry_conv["price"] = calculated
            # Add marker if solar bonus was applied to this entry
            if solar_bonus_enabled:
                entry_conv["solar_bonus_applied"] = solar_bonus_applied
            converted.append(entry_conv)

        return converted

    async def async_update(self):
        total_price = 0.0
        raw_today = None
        raw_tomorrow = None
        valid = False

        for sensor in self.price_sensors:
            state = self.hass.states.get(sensor)
            if state is None or state.state in ("unknown", "unavailable"):
                _LOGGER.warning("Price sensor %s is unavailable", sensor)
                continue
            try:
                total_price += float(state.state)
                valid = True
            except ValueError:
                _LOGGER.warning("Price sensor %s has invalid state", sensor)
                continue

            st_raw_today = self._extract_price_entries(
                state, ("raw_today", "prices_today")
            )
            raw_today = self._merge_price_lists(raw_today, st_raw_today)

            st_raw_tomorrow = self._extract_price_entries(
                state, ("raw_tomorrow", "prices_tomorrow")
            )
            raw_tomorrow = self._merge_price_lists(raw_tomorrow, st_raw_tomorrow)
        if not valid:
            self._attr_available = False
            return
        self._attr_available = True

        self._net_today = self._convert_raw_prices(raw_today)
        self._net_tomorrow = self._convert_raw_prices(raw_tomorrow)

        # Build attributes dictionary
        attributes = {
            "net_prices_today": self._net_today,
            "net_prices_tomorrow": self._net_tomorrow,
        }

        # Add sunrise/sunset info for production sensors with solar bonus
        if (self.source_type == SOURCE_TYPE_PRODUCTION and
            self.price_settings.get("solar_bonus_enabled", False)):
            from datetime import datetime, timedelta

            today = datetime.now().date()
            tomorrow = today + timedelta(days=1)

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
            price = self._calculate_price(total_price)
            if price is not None:
                self._attr_native_value = price

            # But still schedule sunrise/sunset updates if solar bonus is enabled
            if solar_bonus_enabled:
                self._schedule_sunrise_sunset_updates()

    def _update_current_price(self):
        """Update the current price based on the current time and net_prices."""
        from datetime import datetime
        import pytz

        # Get current time in the configured timezone
        tz = pytz.timezone(str(self.hass.config.time_zone))
        now = datetime.now(tz=tz)

        # Find current price from net_prices_today or net_prices_tomorrow
        current_price = None

        if self._net_today:
            for entry in self._net_today:
                start_str = entry.get("start") or entry.get("time")
                end_str = entry.get("end")

                if not start_str or not end_str:
                    continue

                try:
                    start_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                    end_dt = datetime.fromisoformat(end_str.replace("Z", "+00:00"))

                    if start_dt <= now < end_dt:
                        current_price = entry.get("value")
                        break
                except Exception:
                    continue

        # If not found in today, check tomorrow
        if current_price is None and self._net_tomorrow:
            for entry in self._net_tomorrow:
                start_str = entry.get("start") or entry.get("time")
                end_str = entry.get("end")

                if not start_str or not end_str:
                    continue

                try:
                    start_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                    end_dt = datetime.fromisoformat(end_str.replace("Z", "+00:00"))

                    if start_dt <= now < end_dt:
                        current_price = entry.get("value")
                        break
                except Exception:
                    continue

        if current_price is not None:
            self._attr_native_value = current_price
        else:
            # Fallback: calculate from current base price
            total_price = 0.0
            for sensor in self.price_sensors:
                state = self.hass.states.get(sensor)
                if state and state.state not in ("unknown", "unavailable"):
                    try:
                        total_price += float(state.state)
                    except ValueError:
                        pass
            price = self._calculate_price(total_price)
            if price is not None:
                self._attr_native_value = price

    def _schedule_next_price_change(self):
        """Schedule the next price change based on net_prices."""
        from datetime import datetime
        import pytz
        from homeassistant.helpers.event import async_track_point_in_time

        # Cancel existing schedule
        if self._price_change_unsub:
            self._price_change_unsub()
            self._price_change_unsub = None

        tz = pytz.timezone(str(self.hass.config.time_zone))
        now = datetime.now(tz=tz)
        next_change = None

        # Find next price change time
        all_prices = []
        if self._net_today:
            all_prices.extend(self._net_today)
        if self._net_tomorrow:
            all_prices.extend(self._net_tomorrow)

        for entry in all_prices:
            start_str = entry.get("start") or entry.get("time")
            if not start_str:
                continue

            try:
                start_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                if start_dt > now:
                    if next_change is None or start_dt < next_change:
                        next_change = start_dt
            except Exception:
                continue

        if next_change:
            _LOGGER.debug(
                "Scheduling next price change for %s at %s",
                self.entity_id,
                next_change
            )

            async def handle_next_change(now):
                """Handle the next scheduled price change."""
                self._update_current_price()
                self.async_write_ha_state()
                self._schedule_next_price_change()

            self._price_change_unsub = async_track_point_in_time(
                self.hass, handle_next_change, next_change
            )

    def _schedule_sunrise_sunset_updates(self):
        """Schedule updates at sunrise and sunset for solar bonus (without averaging).

        This is used when average_prices_to_hourly is False but solar_bonus is enabled.
        The sensor will update at sunrise/sunset to apply/remove the solar bonus.
        """
        from datetime import datetime, timedelta
        import pytz
        from homeassistant.helpers.event import async_track_point_in_time

        # Cancel existing schedule
        if self._price_change_unsub:
            self._price_change_unsub()
            self._price_change_unsub = None

        tz = pytz.timezone(str(self.hass.config.time_zone))
        now = datetime.now(tz=tz)

        # Get sunrise/sunset times for today and tomorrow
        today = now.date()
        tomorrow = today + timedelta(days=1)

        sunrise_today, sunset_today = self._get_sunrise_sunset_times(today)
        sunrise_tomorrow, sunset_tomorrow = self._get_sunrise_sunset_times(tomorrow)

        # Find the next sunrise or sunset
        next_event = None
        candidates = []

        if sunrise_today and sunrise_today > now:
            candidates.append(sunrise_today)
        if sunset_today and sunset_today > now:
            candidates.append(sunset_today)
        if sunrise_tomorrow and sunrise_tomorrow > now:
            candidates.append(sunrise_tomorrow)
        if sunset_tomorrow and sunset_tomorrow > now:
            candidates.append(sunset_tomorrow)

        if candidates:
            next_event = min(candidates)

        if next_event:
            _LOGGER.debug(
                "Scheduling sunrise/sunset update for %s at %s",
                self.entity_id,
                next_event
            )

            async def handle_sun_event(now):
                """Handle sunrise/sunset event - recalculate price and reschedule."""
                # Recalculate the price
                total_price = 0.0
                for sensor in self.price_sensors:
                    state = self.hass.states.get(sensor)
                    if state and state.state not in ("unknown", "unavailable"):
                        try:
                            total_price += float(state.state)
                        except ValueError:
                            pass

                price = self._calculate_price(total_price)
                if price is not None:
                    self._attr_native_value = price

                self.async_write_ha_state()
                self._schedule_sunrise_sunset_updates()

            self._price_change_unsub = async_track_point_in_time(
                self.hass, handle_sun_event, next_event
            )

    async def async_added_to_hass(self):
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

    async def async_will_remove_from_hass(self):
        """Clean up when removing entity."""
        if self._price_change_unsub:
            self._price_change_unsub()
            self._price_change_unsub = None
        await super().async_will_remove_from_hass()

    async def _handle_price_change(self, event):
        """Handle price sensor state change - rebuild net_prices and reschedule."""
        new_state = event.data.get("new_state")
        if new_state is None or new_state.state in ("unknown", "unavailable"):
            self._attr_available = False
            _LOGGER.warning(
                "Price sensor %s is unavailable", event.data.get("entity_id")
            )
            return
        # Rebuild net_prices and current price
        await self.async_update()
        self.async_write_ha_state()


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    configs = entry.data.get(CONF_CONFIGS, [])
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
        netting_map = hass.data[DOMAIN].setdefault("netting", {})
        tracker = netting_map.get(entry.entry_id)
        if tracker is None:
            tracker = await NettingTracker.async_create(hass, entry.entry_id)
            netting_map[entry.entry_id] = tracker
        netting_tracker = tracker

    solar_bonus_enabled = bool(price_settings.get("solar_bonus_enabled"))
    solar_bonus_tracker: SolarBonusTracker | None = None
    if solar_bonus_enabled:
        solar_bonus_map = hass.data[DOMAIN].setdefault("solar_bonus", {})
        sb_tracker = solar_bonus_map.get(entry.entry_id)
        contract_start_date = price_settings.get("contract_start_date", "")
        if sb_tracker is None:
            sb_tracker = await SolarBonusTracker.async_create(
                hass, entry.entry_id, contract_start_date
            )
            solar_bonus_map[entry.entry_id] = sb_tracker
        solar_bonus_tracker = sb_tracker

    for block in configs:
        source_type = block[CONF_SOURCE_TYPE]
        sources = block[CONF_SOURCES]

        mode_defs: list[dict[str, Any]]
        if source_type == SOURCE_TYPE_GAS:
            selected_price_sensor = price_sensor_gas
            mode_defs = SENSOR_MODES_GAS
        else:
            selected_price_sensor = price_sensor
            mode_defs = SENSOR_MODES_ELECTRICITY

        for sensor in sources:
            base_id = sensor.replace(".", "_")
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
                entities.append(
                    DynamicEnergySensor(
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
                )

    UTILITY_ENTITIES.extend(entities)

    base_id = "daily_electricity_cost"
    unique_id = f"{DOMAIN}_{base_id}"
    device_info = DeviceInfo(
        identifiers={(DOMAIN, base_id)},
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
    entities.append(daily_electricity)

    daily_gas = DailyGasCostSensor(
        hass=hass,
        name="Gas Contract Fixed Costs (Total)",
        unique_id=f"{DOMAIN}_daily_gas_cost",
        price_settings=price_settings,
        device=device_info,
    )
    entities.append(daily_gas)

    net_cost = TotalCostSensor(
        hass=hass,
        name="Net Energy Cost (Total)",
        unique_id=f"{DOMAIN}_net_total_cost",
        device=device_info,
        netting_tracker=netting_tracker,
    )
    entities.append(net_cost)

    energy_cost = TotalEnergyCostSensor(
        hass=hass,
        name="Energy Contract Cost (Total)",
        unique_id=f"{DOMAIN}_total_energy_cost",
        net_cost_unique_id=net_cost.unique_id,
        fixed_cost_unique_ids=[daily_electricity.unique_id, daily_gas.unique_id],
        device=device_info,
        netting_tracker=netting_tracker,
    )
    entities.append(energy_cost)

    # Add solar bonus sensor if enabled
    if solar_bonus_tracker is not None:
        solar_bonus_sensor = SolarBonusStatusSensor(
            hass=hass,
            name="Solar Bonus (Total)",
            unique_id=f"{DOMAIN}_solar_bonus_total",
            device=device_info,
            solar_bonus_tracker=solar_bonus_tracker,
        )
        entities.append(solar_bonus_sensor)

    if price_sensor:
        entities.append(
            CurrentElectricityPriceSensor(
                hass=hass,
                name="Current Consumption Price",
                unique_id=f"{DOMAIN}_current_consumption_price",
                price_sensor=price_sensor,
                source_type=SOURCE_TYPE_CONSUMPTION,
                price_settings=price_settings,
                icon="mdi:transmission-tower-import",
                device=device_info,
            )
        )
        entities.append(
            CurrentElectricityPriceSensor(
                hass=hass,
                name="Current Production Price",
                unique_id=f"{DOMAIN}_current_production_price",
                price_sensor=price_sensor,
                source_type=SOURCE_TYPE_PRODUCTION,
                price_settings=price_settings,
                icon="mdi:transmission-tower-export",
                device=device_info,
            )
        )

    if price_sensor_gas:
        entities.append(
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

    async_add_entities(entities, True)

    hass.data[DOMAIN]["entities"] = {ent.entity_id: ent for ent in entities}

    # Schedule contract anniversary reset if enabled
    reset_on_anniversary = bool(price_settings.get("reset_on_contract_anniversary"))
    if reset_on_anniversary and solar_bonus_tracker:

        async def check_contract_anniversary(now):
            """Check if today is the contract anniversary and reset if needed."""
            next_anniversary = solar_bonus_tracker.get_next_anniversary_date()
            if next_anniversary and now.date() == next_anniversary:
                _LOGGER.info("Contract anniversary reached, resetting all meters")
                # Reset solar bonus tracker
                await solar_bonus_tracker.async_reset_year()
                # Reset all utility entities
                for entity in UTILITY_ENTITIES:
                    await entity.async_reset()

        # Run at midnight every day
        async_track_time_change(
            hass, check_contract_anniversary, hour=0, minute=0, second=0
        )
