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
from .overage_compensation import OverageCompensationTracker

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


def _build_overage_compensation_attributes(
    tracker: OverageCompensationTracker | None,
) -> dict[str, float | bool]:
    if tracker is None:
        return {"overage_compensation_enabled": False}
    return {
        "overage_compensation_enabled": True,
        "overage_compensation_net_consumption_kwh": round(
            tracker.net_consumption_kwh, 8
        ),
        "overage_compensation_total_consumption_kwh": round(
            tracker.total_consumption_kwh, 8
        ),
        "overage_compensation_total_production_kwh": round(
            tracker.total_production_kwh, 8
        ),
        "overage_compensation_pending_kwh": round(tracker.pending_compensation_kwh, 8),
    }


class NettingStatusMixin:
    _netting_tracker: NettingTracker | None

    def _update_netting_attributes(self) -> None:
        self._attr_extra_state_attributes = _build_netting_attributes(
            self._netting_tracker
        )


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


class DailyGasCostSensor(NettingStatusMixin, BaseUtilitySensor):
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
            translation_key="daily_gas_cost_total",
        )
        self.hass = hass
        self.price_settings = price_settings
        self._netting_tracker = netting_tracker
        self._update_netting_attributes()

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
            "Adding daily gas cost %s at %s to %s",
            addition,
            now,
            self.entity_id,
        )
        self._attr_native_value += addition
        self._update_netting_attributes()
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
                if self.price_settings.get("production_price_include_vat", True):
                    price = (base_price - markup_production) * vat_factor
                else:
                    price = base_price - markup_production
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

    def _convert_raw_prices(self, raw_prices):
        """Convert raw price entries by applying price settings.

        The input may be a list accumulated from multiple price sensors.
        Each entry is copied before modification to avoid mutating the
        original structure.
        """

        if not isinstance(raw_prices, list):
            return None

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
            entry_conv["value"] = calculated
            if "price" in entry_conv:
                entry_conv["price"] = calculated
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
        self._attr_extra_state_attributes = {
            "net_prices_today": self._net_today,
            "net_prices_tomorrow": self._net_tomorrow,
        }

        price = self._calculate_price(total_price)
        if price is None:
            return
        self._attr_native_value = price

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        for sensor in self.price_sensors:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass,
                    sensor,
                    self._handle_price_change,
                )
            )

    async def _handle_price_change(self, event):
        new_state = event.data.get("new_state")
        if new_state is None or new_state.state in ("unknown", "unavailable"):
            self._attr_available = False
            _LOGGER.warning(
                "Price sensor %s is unavailable", event.data.get("entity_id")
            )
            return
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

    overage_compensation_enabled = bool(
        price_settings.get("overage_compensation_enabled")
    )
    overage_compensation_tracker: OverageCompensationTracker | None = None
    if overage_compensation_enabled:
        overage_map = hass.data[DOMAIN].setdefault("overage_compensation", {})
        tracker = overage_map.get(entry.entry_id)
        if tracker is None:
            tracker = await OverageCompensationTracker.async_create(
                hass, entry.entry_id
            )
            overage_map[entry.entry_id] = tracker
        overage_compensation_tracker = tracker

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
                overage_tracker_arg = (
                    overage_compensation_tracker
                    if overage_compensation_tracker
                    and source_type in (SOURCE_TYPE_CONSUMPTION, SOURCE_TYPE_PRODUCTION)
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
                        overage_compensation_tracker=overage_tracker_arg,
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
        netting_tracker=netting_tracker,
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
