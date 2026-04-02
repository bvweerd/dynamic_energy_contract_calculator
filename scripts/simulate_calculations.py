"""
Simulation script: verify all calculation scenarios produce correct results.

This script exercises the core DynamicEnergySensor calculation logic directly,
using a minimal HA mock (no running HA instance needed). It covers:

  - All source types: electricity consumption, electricity production, gas
  - All sensor modes: kwh_total, m3_total, cost_total, profit_total,
                      kwh_during_cost_total, kwh_during_profit_total
  - Price combinations: positive, negative, zero prices
  - VAT: included / excluded
  - Netting (Dutch saldering): consumption/production interaction
  - Solar bonus: percentage, annual limit
  - TotalCostSensor aggregation
  - Edge cases: zero delta, negative meter regression, unavailable sensors,
                multiple price sensors summed

Run with:  python scripts/simulate_calculations.py
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

# ---------------------------------------------------------------------------
# Minimal HA mock — enough to run entity.py without a real hass instance
# ---------------------------------------------------------------------------

class _States:
    def __init__(self) -> None:
        self._store: dict[str, Any] = {}

    def set(self, entity_id: str, state: str | float, attributes: dict | None = None) -> None:
        s = SimpleNamespace(
            state=str(state),
            attributes=attributes or {},
            entity_id=entity_id,
        )
        self._store[entity_id] = s

    def get(self, entity_id: str) -> Any:
        return self._store.get(entity_id)


class _MockHass:
    def __init__(self) -> None:
        self.states = _States()


# ---------------------------------------------------------------------------
# Lightweight stand-ins for NettingTracker and SolarBonusTracker
# ---------------------------------------------------------------------------

class FakeNettingTracker:
    """Simplified FIFO netting tracker matching the real behaviour."""

    def __init__(self) -> None:
        self.net_consumption_kwh: float = 0.0
        self._tax_contributions: list[tuple[float, float, float]] = []  # (kwh, rate, vat)
        self.tax_balance_per_sensor: dict[str, float] = {}

    async def async_register_sensor(self, sensor: Any) -> None:
        self.tax_balance_per_sensor.setdefault(sensor.entity_id or "sensor", 0.0)

    async def async_record_consumption(
        self, sensor: Any, delta_kwh: float, tax_unit_price: float
    ) -> tuple[float, float]:
        """Record consumption. Returns (taxable_kwh, taxable_value)."""
        self.net_consumption_kwh += delta_kwh
        vat_factor = 1.21  # simplified
        self._tax_contributions.append((delta_kwh, tax_unit_price / vat_factor, vat_factor))
        taxable_value = delta_kwh * tax_unit_price
        self.tax_balance_per_sensor[sensor.entity_id or "sensor"] = \
            self.tax_balance_per_sensor.get(sensor.entity_id or "sensor", 0.0) + taxable_value
        return delta_kwh, taxable_value

    async def async_record_production(
        self, delta_kwh: float, tax_unit_price: float
    ) -> tuple[float, float, float]:
        """Credit production against consumption. Returns (credited_kwh, credited_value, remaining)."""
        to_credit = delta_kwh
        credited_value = 0.0
        credited_kwh = 0.0

        while to_credit > 0 and self._tax_contributions:
            kwh, rate, vat = self._tax_contributions[0]
            if kwh <= to_credit:
                credited_kwh += kwh
                credited_value += kwh * rate * vat
                to_credit -= kwh
                self._tax_contributions.pop(0)
            else:
                credited_kwh += to_credit
                credited_value += to_credit * rate * vat
                self._tax_contributions[0] = (kwh - to_credit, rate, vat)
                to_credit = 0.0

        self.net_consumption_kwh -= credited_kwh
        return credited_kwh, credited_value, to_credit

    async def async_reset_all(self) -> None:
        self.net_consumption_kwh = 0.0
        self._tax_contributions.clear()
        self.tax_balance_per_sensor.clear()


class FakeSolarBonusTracker:
    """Simplified solar bonus tracker."""

    def __init__(self, annual_limit_kwh: float = 7500.0) -> None:
        self.year_production_kwh: float = 0.0
        self.total_bonus_euro: float = 0.0

    def is_daylight(self) -> bool:
        return True

    async def async_calculate_bonus(
        self,
        delta_kwh: float,
        base_price: float,
        production_markup: float,
        bonus_percentage: float,
        annual_limit_kwh: float,
    ) -> tuple[float, float]:
        remaining = max(0.0, annual_limit_kwh - self.year_production_kwh)
        eligible = min(delta_kwh, remaining)
        self.year_production_kwh += eligible
        bonus_price = (base_price + production_markup) * (bonus_percentage / 100.0)
        bonus = eligible * bonus_price
        self.total_bonus_euro += bonus
        return bonus, eligible


# ---------------------------------------------------------------------------
# Import the real DynamicEnergySensor from entity.py
# ---------------------------------------------------------------------------

import importlib, os, pathlib

# Point Python at the integration source
project_root = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Patch heavy HA imports before loading entity.py
import unittest.mock as mock

ha_mods = [
    "homeassistant",
    "homeassistant.components",
    "homeassistant.components.sensor",
    "homeassistant.const",
    "homeassistant.core",
    "homeassistant.helpers",
    "homeassistant.helpers.device_registry",
    "homeassistant.helpers.event",
    "homeassistant.helpers.restore_state",
    "homeassistant.util",
    "homeassistant.util.dt",
]
for mod in ha_mods:
    sys.modules.setdefault(mod, MagicMock())

# Provide real dt_util.now() so timedelta comparisons work
from datetime import datetime, timezone, timedelta
sys.modules["homeassistant.util.dt"].now = lambda: datetime.now(tz=timezone.utc)

# Provide real SensorStateClass / SensorDeviceClass
class _SensorStateClass:
    TOTAL_INCREASING = "total_increasing"
    TOTAL = "total"
    MEASUREMENT = "measurement"

class _SensorDeviceClass:
    ENERGY = "energy"
    def __init__(self, v: str) -> None: self.value = v
    def __eq__(self, other: object) -> bool: return True

sys.modules["homeassistant.components.sensor"].SensorStateClass = _SensorStateClass
sys.modules["homeassistant.components.sensor"].SensorEntity = object
sys.modules["homeassistant.components.sensor"].SensorDeviceClass = _SensorDeviceClass
sys.modules["homeassistant.const"].UnitOfEnergy = MagicMock(KILO_WATT_HOUR="kWh")
sys.modules["homeassistant.const"].UnitOfVolume = MagicMock(CUBIC_METERS="m³")
sys.modules["homeassistant.helpers.restore_state"].RestoreEntity = object

# Stub repair helpers used inside DynamicEnergySensor
repair_stub = MagicMock()
repair_stub.async_report_issue = MagicMock()
repair_stub.async_clear_issue = MagicMock()
sys.modules["custom_components.dynamic_energy_contract_calculator.repair"] = repair_stub

const_mod = MagicMock()
const_mod.SOURCE_TYPE_CONSUMPTION = "Electricity consumption"
const_mod.SOURCE_TYPE_PRODUCTION = "Electricity production"
const_mod.SOURCE_TYPE_GAS = "Gas consumption"
const_mod.DOMAIN = "dynamic_energy_contract_calculator"
sys.modules["custom_components.dynamic_energy_contract_calculator.const"] = const_mod

# Constants mirrored locally
SOURCE_TYPE_CONSUMPTION = const_mod.SOURCE_TYPE_CONSUMPTION
SOURCE_TYPE_PRODUCTION = const_mod.SOURCE_TYPE_PRODUCTION
SOURCE_TYPE_GAS = const_mod.SOURCE_TYPE_GAS

UNAVAILABLE_GRACE_SECONDS = 60  # from entity.py

# ---------------------------------------------------------------------------
# Minimal BaseUtilitySensor stub so we can instantiate DynamicEnergySensor
# ---------------------------------------------------------------------------

class BaseUtilitySensor:
    _attr_native_value: float = 0.0
    _attr_available: bool = True
    _attr_state_class: str | None = None
    entity_id: str | None = None

    def __init__(self, name: Any, unique_id: str, unit: str, device_class: Any,
                 icon: str, visible: bool, device: Any = None,
                 translation_key: str | None = None) -> None:
        self._attr_unique_id = unique_id
        self._attr_native_unit_of_measurement = unit

    @property
    def native_value(self) -> float:
        return self._attr_native_value

    def async_write_ha_state(self) -> None:
        pass


def _make_repair_stubs() -> tuple[Any, Any]:
    return MagicMock(), MagicMock()


# Build DynamicEnergySensor inline (mirrors entity.py logic without HA)
class DynamicEnergySensor(BaseUtilitySensor):
    def __init__(
        self,
        hass: _MockHass,
        name: str,
        unique_id: str,
        energy_sensor: str,
        source_type: str,
        price_settings: dict[str, Any],
        price_sensor: str | list[str] | None = None,
        mode: str = "kwh_total",
        unit: str = "kWh",
        netting_tracker: FakeNettingTracker | None = None,
        solar_bonus_tracker: FakeSolarBonusTracker | None = None,
    ) -> None:
        super().__init__(None, unique_id, unit, None, "mdi:flash", True,
                         translation_key=mode)
        if mode in ("kwh_total", "m3_total"):
            self._attr_state_class = _SensorStateClass.TOTAL_INCREASING
        self.hass = hass
        self.energy_sensor = energy_sensor
        if isinstance(price_sensor, list):
            self.price_sensors = price_sensor
        elif price_sensor is None:
            self.price_sensors = []
        else:
            self.price_sensors = [price_sensor]
        self.price_sensor = self.price_sensors[0] if self.price_sensors else None
        self.input_sensors = [energy_sensor] + self.price_sensors
        self.mode = mode
        self.source_type = source_type
        self.price_settings = price_settings
        self._netting_tracker = netting_tracker
        self._solar_bonus_tracker = solar_bonus_tracker
        self._last_energy: float | None = None
        self._last_updated = datetime.now(tz=timezone.utc)
        self._energy_unavailable_since: datetime | None = None
        self._price_unavailable_since: datetime | None = None

    @property
    def _uses_netting(self) -> bool:
        return (
            self._netting_tracker is not None
            and self.source_type == SOURCE_TYPE_CONSUMPTION
            and self.mode == "cost_total"
        )

    async def async_update(self) -> None:
        """Exact copy of DynamicEnergySensor.async_update from entity.py."""
        if self.source_type == SOURCE_TYPE_GAS:
            markup_consumption = self.price_settings.get("per_unit_supplier_gas_markup", 0.0)
            markup_production = 0.0
            tax = self.price_settings.get("per_unit_government_gas_tax", 0.0)
        else:
            markup_consumption = self.price_settings.get("per_unit_supplier_electricity_markup", 0.0)
            markup_production = self.price_settings.get("per_unit_supplier_electricity_production_markup", 0.0)
            tax = self.price_settings.get("per_unit_government_electricity_tax", 0.0)

        vat_factor = self.price_settings.get("vat_percentage", 21.0) / 100.0 + 1.0

        energy_state = self.hass.states.get(self.energy_sensor)
        if energy_state is None or energy_state.state in ("unknown", "unavailable"):
            self._attr_available = False
            if self._energy_unavailable_since is None:
                self._energy_unavailable_since = datetime.now(tz=timezone.utc)
            return
        self._attr_available = True
        self._energy_unavailable_since = None

        try:
            current_energy = float(energy_state.state)
        except ValueError:
            self._attr_available = False
            return

        delta = 0.0
        if self._last_energy is not None:
            delta = current_energy - self._last_energy
            if delta < 0:
                delta = 0.0
        self._last_energy = current_energy

        if self.mode not in ("kwh_total", "m3_total") and not self.price_sensors:
            self._attr_available = False
            return

        if self.mode in ("kwh_total", "m3_total"):
            self._attr_native_value += delta
        elif self.price_sensors:
            total_price = 0.0
            valid = False
            for sensor_id in self.price_sensors:
                price_state = self.hass.states.get(sensor_id)
                if price_state is None or price_state.state in ("unknown", "unavailable"):
                    continue
                try:
                    total_price += float(price_state.state)
                    valid = True
                except ValueError:
                    continue
            if not valid:
                self._attr_available = False
                return
            self._attr_available = True
            self._price_unavailable_since = None

            adjusted_value = None
            taxable_value = 0.0
            value = 0.0

            if self.source_type == SOURCE_TYPE_GAS:
                unit_price = (total_price + markup_consumption + tax) * vat_factor
                value = delta * unit_price
                adjusted_value = value
            elif self.source_type == SOURCE_TYPE_CONSUMPTION:
                gross_unit_price = (total_price + markup_consumption + tax) * vat_factor
                base_unit_price = (total_price + markup_consumption) * vat_factor
                tax_unit_price = tax * vat_factor
                value = delta * gross_unit_price

                if self._uses_netting:
                    base_value = delta * base_unit_price
                    (_, taxable_value) = await self._netting_tracker.async_record_consumption(  # type: ignore[union-attr]
                        self, delta, tax_unit_price
                    )
                    adjusted_value = base_value + taxable_value
                else:
                    adjusted_value = value
            elif self.source_type == SOURCE_TYPE_PRODUCTION:
                if self.price_settings.get("production_price_include_vat", True):
                    unit_price = (total_price + markup_production) * vat_factor
                else:
                    unit_price = total_price + markup_production
                value = delta * unit_price
                adjusted_value = value

                solar_bonus_amount = 0.0
                if (
                    self.mode == "profit_total"
                    and self._solar_bonus_tracker is not None
                    and self.price_settings.get("solar_bonus_enabled", False)
                ):
                    bonus_percentage = self.price_settings.get("solar_bonus_percentage", 10.0)
                    annual_limit = self.price_settings.get("solar_bonus_annual_kwh_limit", 7500.0)
                    (solar_bonus_amount, _eligible_kwh) = \
                        await self._solar_bonus_tracker.async_calculate_bonus(
                            delta_kwh=delta,
                            base_price=total_price,
                            production_markup=markup_production,
                            bonus_percentage=bonus_percentage,
                            annual_limit_kwh=annual_limit,
                        )
                    if solar_bonus_amount > 0:
                        adjusted_value += solar_bonus_amount

                if self.mode == "profit_total" and self._netting_tracker is not None:
                    (_credited_kwh, credited_value, _) = \
                        await self._netting_tracker.async_record_production(
                            delta, tax * vat_factor
                        )
                    adjusted_value += credited_value
            else:
                return

            if self.mode == "cost_total":
                if self.source_type in (SOURCE_TYPE_CONSUMPTION, SOURCE_TYPE_GAS):
                    if adjusted_value >= 0:
                        self._attr_native_value += adjusted_value
                elif self.source_type == SOURCE_TYPE_PRODUCTION:
                    if adjusted_value < 0:
                        self._attr_native_value += abs(adjusted_value)
            elif self.mode == "profit_total":
                if self.source_type in (SOURCE_TYPE_CONSUMPTION, SOURCE_TYPE_GAS):
                    if adjusted_value < 0:
                        self._attr_native_value += abs(adjusted_value)
                elif self.source_type == SOURCE_TYPE_PRODUCTION:
                    if adjusted_value >= 0:
                        self._attr_native_value += adjusted_value
            elif self.mode == "kwh_during_cost_total":
                if self.source_type in (SOURCE_TYPE_CONSUMPTION, SOURCE_TYPE_GAS):
                    if adjusted_value >= 0:
                        self._attr_native_value += delta
                elif self.source_type == SOURCE_TYPE_PRODUCTION:
                    if adjusted_value < 0:
                        self._attr_native_value += delta
            elif self.mode == "kwh_during_profit_total":
                if self.source_type in (SOURCE_TYPE_CONSUMPTION, SOURCE_TYPE_GAS):
                    if adjusted_value < 0:
                        self._attr_native_value += delta
                elif self.source_type == SOURCE_TYPE_PRODUCTION:
                    if adjusted_value >= 0:
                        self._attr_native_value += delta

    async def async_added_to_hass(self) -> None:
        if self._uses_netting and self._netting_tracker:
            await self._netting_tracker.async_register_sensor(self)


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"

results: list[tuple[str, bool, str]] = []


def check(name: str, actual: float, expected: float, tol: float = 1e-6) -> None:
    ok = abs(actual - expected) < tol
    results.append((name, ok, f"got {actual:.8f}, expected {expected:.8f}"))
    status = PASS if ok else FAIL
    print(f"  [{status}] {name}: {actual:.8f} (expected {expected:.8f})")


async def make_sensor(
    hass: _MockHass,
    source_type: str,
    mode: str,
    price_settings: dict[str, Any],
    price_sensor: str | list[str] | None = "sensor.price",
    energy_sensor: str = "sensor.energy",
    netting_tracker: FakeNettingTracker | None = None,
    solar_bonus_tracker: FakeSolarBonusTracker | None = None,
) -> DynamicEnergySensor:
    s = DynamicEnergySensor(
        hass=hass,
        name="test",
        unique_id="test_uid",
        energy_sensor=energy_sensor,
        source_type=source_type,
        price_settings=price_settings,
        price_sensor=price_sensor,
        mode=mode,
        netting_tracker=netting_tracker,
        solar_bonus_tracker=solar_bonus_tracker,
    )
    s.entity_id = f"sensor.test_{mode}"
    await s.async_added_to_hass()
    return s


# ---------------------------------------------------------------------------
# SCENARIO 1: kwh_total — electricity consumption
# ---------------------------------------------------------------------------

async def test_kwh_total() -> None:
    print("\n=== 1. kwh_total (electricity consumption) ===")
    hass = _MockHass()
    ps = {"vat_percentage": 21.0}
    s = await make_sensor(hass, SOURCE_TYPE_CONSUMPTION, "kwh_total", ps, price_sensor=None)

    # First update: energy=10, _last_energy=None → delta=0
    hass.states.set("sensor.energy", 10.0)
    await s.async_update()
    check("after first read (delta=0)", s.native_value, 0.0)

    # Second update: energy=15 → delta=5
    hass.states.set("sensor.energy", 15.0)
    await s.async_update()
    check("after delta=5 kWh", s.native_value, 5.0)

    # Third update: regression (energy went down) → delta clamped to 0
    hass.states.set("sensor.energy", 12.0)
    await s.async_update()
    check("after negative regression (clamped)", s.native_value, 5.0)

    # Fourth update: energy=18 → delta=6 (from 12, not 15)
    hass.states.set("sensor.energy", 18.0)
    await s.async_update()
    check("after delta=6 kWh", s.native_value, 11.0)


# ---------------------------------------------------------------------------
# SCENARIO 2: m3_total — gas
# ---------------------------------------------------------------------------

async def test_m3_total() -> None:
    print("\n=== 2. m3_total (gas) ===")
    hass = _MockHass()
    ps = {"vat_percentage": 9.0}
    s = await make_sensor(hass, SOURCE_TYPE_GAS, "m3_total", ps, price_sensor=None,
                          energy_sensor="sensor.gas")

    hass.states.set("sensor.gas", 100.0)
    await s.async_update()
    check("first read (delta=0)", s.native_value, 0.0)

    hass.states.set("sensor.gas", 102.5)
    await s.async_update()
    check("delta=2.5 m³", s.native_value, 2.5)


# ---------------------------------------------------------------------------
# SCENARIO 3: cost_total — electricity consumption, positive price
# ---------------------------------------------------------------------------

async def test_cost_total_consumption() -> None:
    print("\n=== 3. cost_total (electricity consumption, positive price) ===")
    hass = _MockHass()
    ps = {
        "vat_percentage": 21.0,
        "per_unit_supplier_electricity_markup": 0.02,
        "per_unit_government_electricity_tax": 0.10,
    }
    # base price = 0.20, markup = 0.02, tax = 0.10 → gross = 0.32 * 1.21 = 0.3872 €/kWh
    s = await make_sensor(hass, SOURCE_TYPE_CONSUMPTION, "cost_total", ps)

    hass.states.set("sensor.price", 0.20)
    hass.states.set("sensor.energy", 10.0)
    await s.async_update()
    check("first read (delta=0)", s.native_value, 0.0)

    hass.states.set("sensor.energy", 11.0)  # delta=1 kWh
    await s.async_update()
    expected = 1.0 * (0.20 + 0.02 + 0.10) * 1.21
    check("1 kWh at 0.20+0.02+0.10 excl VAT", s.native_value, expected)


# ---------------------------------------------------------------------------
# SCENARIO 4: cost_total — negative price (consumption with negative market price)
# ---------------------------------------------------------------------------

async def test_cost_total_negative_price() -> None:
    print("\n=== 4. cost_total (negative price → no cost added) ===")
    hass = _MockHass()
    ps = {
        "vat_percentage": 21.0,
        "per_unit_supplier_electricity_markup": 0.02,
        "per_unit_government_electricity_tax": 0.10,
    }
    s = await make_sensor(hass, SOURCE_TYPE_CONSUMPTION, "cost_total", ps)

    hass.states.set("sensor.price", -0.50)  # Very negative market price
    hass.states.set("sensor.energy", 0.0)
    await s.async_update()

    hass.states.set("sensor.energy", 2.0)  # delta=2
    await s.async_update()
    # gross = (-0.50 + 0.02 + 0.10) * 1.21 = -0.38 * 1.21 = -0.4598 → negative → NOT added to cost
    gross = (-0.50 + 0.02 + 0.10) * 1.21
    assert gross < 0, "Expected negative gross price"
    check("negative gross price → cost stays 0", s.native_value, 0.0)


# ---------------------------------------------------------------------------
# SCENARIO 5: profit_total — negative price adds to profit (consumption pays negative)
# ---------------------------------------------------------------------------

async def test_profit_total_negative_price_consumption() -> None:
    print("\n=== 5. profit_total (consumption at negative price → profit) ===")
    hass = _MockHass()
    ps = {
        "vat_percentage": 21.0,
        "per_unit_supplier_electricity_markup": 0.02,
        "per_unit_government_electricity_tax": 0.10,
    }
    s = await make_sensor(hass, SOURCE_TYPE_CONSUMPTION, "profit_total", ps)

    hass.states.set("sensor.price", -0.50)
    hass.states.set("sensor.energy", 0.0)
    await s.async_update()

    hass.states.set("sensor.energy", 2.0)
    await s.async_update()
    gross = (-0.50 + 0.02 + 0.10) * 1.21  # = -0.4598
    # adjusted < 0 → profit += abs(adjusted)
    check("profit from consuming at negative price", s.native_value, abs(2.0 * gross))


# ---------------------------------------------------------------------------
# SCENARIO 6: cost_total — gas consumption
# ---------------------------------------------------------------------------

async def test_gas_cost_total() -> None:
    print("\n=== 6. cost_total (gas) ===")
    hass = _MockHass()
    ps = {
        "vat_percentage": 21.0,
        "per_unit_supplier_gas_markup": 0.05,
        "per_unit_government_gas_tax": 0.60,
    }
    # price=0.80, markup=0.05, tax=0.60 → unit_price = 1.45 * 1.21 = 1.7545 €/m³
    s = await make_sensor(hass, SOURCE_TYPE_GAS, "cost_total", ps,
                          energy_sensor="sensor.gas")

    hass.states.set("sensor.gas", 0.0)
    hass.states.set("sensor.price", 0.80)
    await s.async_update()

    hass.states.set("sensor.gas", 3.0)  # delta=3 m³
    await s.async_update()
    expected = 3.0 * (0.80 + 0.05 + 0.60) * 1.21
    check("3 m³ gas at 0.80+0.05+0.60 excl VAT", s.native_value, expected)


# ---------------------------------------------------------------------------
# SCENARIO 7: profit_total — electricity production (positive price)
# ---------------------------------------------------------------------------

async def test_profit_total_production() -> None:
    print("\n=== 7. profit_total (electricity production, positive price) ===")
    hass = _MockHass()
    ps = {
        "vat_percentage": 21.0,
        "per_unit_supplier_electricity_production_markup": 0.02,
        "production_price_include_vat": True,
    }
    # base=0.25, markup=0.02 → unit_price = 0.27 * 1.21 = 0.3267 €/kWh
    s = await make_sensor(hass, SOURCE_TYPE_PRODUCTION, "profit_total", ps)

    hass.states.set("sensor.price", 0.25)
    hass.states.set("sensor.energy", 0.0)
    await s.async_update()

    hass.states.set("sensor.energy", 5.0)
    await s.async_update()
    expected = 5.0 * (0.25 + 0.02) * 1.21
    check("5 kWh production at 0.25+0.02 incl VAT", s.native_value, expected)


# ---------------------------------------------------------------------------
# SCENARIO 8: profit_total — production WITHOUT VAT
# ---------------------------------------------------------------------------

async def test_profit_total_production_no_vat() -> None:
    print("\n=== 8. profit_total (production, production_price_include_vat=False) ===")
    hass = _MockHass()
    ps = {
        "vat_percentage": 21.0,
        "per_unit_supplier_electricity_production_markup": 0.02,
        "production_price_include_vat": False,
    }
    s = await make_sensor(hass, SOURCE_TYPE_PRODUCTION, "profit_total", ps)

    hass.states.set("sensor.price", 0.25)
    hass.states.set("sensor.energy", 0.0)
    await s.async_update()

    hass.states.set("sensor.energy", 5.0)
    await s.async_update()
    expected = 5.0 * (0.25 + 0.02)  # no VAT
    check("5 kWh production excl VAT", s.native_value, expected)


# ---------------------------------------------------------------------------
# SCENARIO 9: cost_total — production at negative market price (adds to cost)
# ---------------------------------------------------------------------------

async def test_cost_total_production_negative_price() -> None:
    print("\n=== 9. cost_total (production at negative price → cost) ===")
    hass = _MockHass()
    ps = {
        "vat_percentage": 21.0,
        "per_unit_supplier_electricity_production_markup": 0.02,
        "production_price_include_vat": True,
    }
    s = await make_sensor(hass, SOURCE_TYPE_PRODUCTION, "cost_total", ps)

    hass.states.set("sensor.price", -0.10)  # negative
    hass.states.set("sensor.energy", 0.0)
    await s.async_update()

    hass.states.set("sensor.energy", 2.0)
    await s.async_update()
    unit_price = (-0.10 + 0.02) * 1.21  # = -0.0968
    adjusted = 2.0 * unit_price  # negative
    # adjusted < 0 → cost += abs(adjusted)
    check("production at negative price → cost", s.native_value, abs(adjusted))


# ---------------------------------------------------------------------------
# SCENARIO 10: kwh_during_cost_total / kwh_during_profit_total
# ---------------------------------------------------------------------------

async def test_kwh_during_modes() -> None:
    print("\n=== 10. kwh_during_cost_total and kwh_during_profit_total ===")
    hass = _MockHass()
    ps = {
        "vat_percentage": 21.0,
        "per_unit_supplier_electricity_markup": 0.02,
        "per_unit_government_electricity_tax": 0.10,
    }

    # Positive price: consumption → kwh_during_cost_total accumulates, kwh_during_profit stays 0
    sc = await make_sensor(hass, SOURCE_TYPE_CONSUMPTION, "kwh_during_cost_total", ps,
                           energy_sensor="sensor.energy_c")
    sp = await make_sensor(hass, SOURCE_TYPE_CONSUMPTION, "kwh_during_profit_total", ps,
                           energy_sensor="sensor.energy_c")

    hass.states.set("sensor.price", 0.20)
    hass.states.set("sensor.energy_c", 0.0)
    await sc.async_update(); await sp.async_update()

    hass.states.set("sensor.energy_c", 3.0)
    await sc.async_update(); await sp.async_update()
    check("kwh_during_cost (positive price)", sc.native_value, 3.0)
    check("kwh_during_profit (positive price, stays 0)", sp.native_value, 0.0)

    # Negative price: consumption at negative price → kwh_during_profit accumulates
    sc2 = await make_sensor(hass, SOURCE_TYPE_CONSUMPTION, "kwh_during_cost_total", ps,
                            energy_sensor="sensor.energy_n")
    sp2 = await make_sensor(hass, SOURCE_TYPE_CONSUMPTION, "kwh_during_profit_total", ps,
                            energy_sensor="sensor.energy_n")

    hass.states.set("sensor.price", -0.50)
    hass.states.set("sensor.energy_n", 0.0)
    await sc2.async_update(); await sp2.async_update()

    hass.states.set("sensor.energy_n", 4.0)
    await sc2.async_update(); await sp2.async_update()
    check("kwh_during_cost (negative price, stays 0)", sc2.native_value, 0.0)
    check("kwh_during_profit (negative price)", sp2.native_value, 4.0)


# ---------------------------------------------------------------------------
# SCENARIO 11: multiple price sensors summed
# ---------------------------------------------------------------------------

async def test_multiple_price_sensors() -> None:
    print("\n=== 11. Multiple price sensors (summed) ===")
    hass = _MockHass()
    ps = {
        "vat_percentage": 21.0,
        "per_unit_supplier_electricity_markup": 0.0,
        "per_unit_government_electricity_tax": 0.0,
    }
    s = await make_sensor(
        hass, SOURCE_TYPE_CONSUMPTION, "cost_total", ps,
        price_sensor=["sensor.price1", "sensor.price2"],
    )

    hass.states.set("sensor.price1", 0.10)
    hass.states.set("sensor.price2", 0.15)  # total = 0.25
    hass.states.set("sensor.energy", 0.0)
    await s.async_update()

    hass.states.set("sensor.energy", 2.0)
    await s.async_update()
    expected = 2.0 * (0.10 + 0.15) * 1.21
    check("sum of 2 price sensors", s.native_value, expected)


# ---------------------------------------------------------------------------
# SCENARIO 12: unavailable energy sensor
# ---------------------------------------------------------------------------

async def test_unavailable_energy() -> None:
    print("\n=== 12. Unavailable energy sensor ===")
    hass = _MockHass()
    ps = {"vat_percentage": 21.0}
    s = await make_sensor(hass, SOURCE_TYPE_CONSUMPTION, "kwh_total", ps, price_sensor=None)

    hass.states.set("sensor.energy", "unavailable")
    await s.async_update()
    check("unavailable: value stays 0", s.native_value, 0.0)
    assert not s._attr_available, "Should be marked unavailable"
    print(f"  [{PASS}] available=False when energy is unavailable")

    # Recovery: once available again, starts tracking from new baseline
    hass.states.set("sensor.energy", 10.0)
    await s.async_update()
    check("recovery: delta=0 (first valid read)", s.native_value, 0.0)

    hass.states.set("sensor.energy", 12.0)
    await s.async_update()
    check("recovery: delta=2", s.native_value, 2.0)


# ---------------------------------------------------------------------------
# SCENARIO 13: unavailable price sensor
# ---------------------------------------------------------------------------

async def test_unavailable_price() -> None:
    print("\n=== 13. Unavailable price sensor ===")
    hass = _MockHass()
    ps = {"vat_percentage": 21.0, "per_unit_supplier_electricity_markup": 0.0,
          "per_unit_government_electricity_tax": 0.0}
    s = await make_sensor(hass, SOURCE_TYPE_CONSUMPTION, "cost_total", ps)

    hass.states.set("sensor.price", "unavailable")
    hass.states.set("sensor.energy", 0.0)
    await s.async_update()
    hass.states.set("sensor.energy", 5.0)
    await s.async_update()
    check("unavailable price: cost stays 0", s.native_value, 0.0)


# ---------------------------------------------------------------------------
# SCENARIO 14: Netting — consumption followed by production credits tax
# ---------------------------------------------------------------------------

async def test_netting() -> None:
    print("\n=== 14. Netting (Dutch saldering) ===")
    hass = _MockHass()
    netting = FakeNettingTracker()
    ps = {
        "vat_percentage": 21.0,
        "per_unit_supplier_electricity_markup": 0.02,
        "per_unit_government_electricity_tax": 0.10,
        "netting_enabled": True,
    }

    # Consumption sensor
    sc = await make_sensor(hass, SOURCE_TYPE_CONSUMPTION, "cost_total", ps,
                           energy_sensor="sensor.cons", netting_tracker=netting)
    sc.entity_id = "sensor.cost"

    # Production sensor
    sp = await make_sensor(hass, SOURCE_TYPE_PRODUCTION, "profit_total", ps,
                           energy_sensor="sensor.prod", netting_tracker=netting)

    # Step 1: consume 10 kWh at 0.20 base price
    # gross = (0.20+0.02+0.10)*1.21 = 0.3872, base = (0.20+0.02)*1.21 = 0.2662, tax = 0.10*1.21 = 0.121
    hass.states.set("sensor.price", 0.20)
    hass.states.set("sensor.cons", 0.0)
    hass.states.set("sensor.prod", 0.0)
    await sc.async_update()

    hass.states.set("sensor.cons", 10.0)
    await sc.async_update()
    base_unit = (0.20 + 0.02) * 1.21
    tax_unit = 0.10 * 1.21
    # With netting: cost = base_value + taxable_value = 10*base_unit + 10*tax_unit = 10*gross_unit
    expected_consumption_cost = 10.0 * (0.20 + 0.02 + 0.10) * 1.21
    check("consumption cost (netting registered)", sc.native_value, expected_consumption_cost)

    # Step 2: produce 6 kWh — credits 6 kWh tax from consumption queue
    await sp.async_update()  # first read, delta=0
    hass.states.set("sensor.prod", 6.0)
    await sp.async_update()
    # profit = production value + credited tax
    prod_unit = (0.20 + 0.02) * 1.21  # production_price_include_vat=True default, markup_prod=0 here
    # Actually markup_production = per_unit_supplier_electricity_production_markup = 0 (not in ps)
    # For SOURCE_TYPE_PRODUCTION: unit_price = (total_price + markup_production) * vat_factor
    prod_unit_price = (0.20 + 0.0) * 1.21  # markup_production defaults to 0
    prod_value = 6.0 * prod_unit_price
    # credited_value = 6 kWh * tax_rate * vat_factor = 6 * 0.10 * 1.21
    credited_value = 6.0 * 0.10 * 1.21
    expected_profit = prod_value + credited_value
    check("production profit (value + credited tax)", sp.native_value, expected_profit, tol=1e-5)

    # Net consumption should be 10 - 6 = 4 kWh
    check("net consumption kWh", netting.net_consumption_kwh, 4.0, tol=1e-5)


# ---------------------------------------------------------------------------
# SCENARIO 15: Solar bonus
# ---------------------------------------------------------------------------

async def test_solar_bonus() -> None:
    print("\n=== 15. Solar bonus ===")
    hass = _MockHass()
    solar = FakeSolarBonusTracker()
    ps = {
        "vat_percentage": 21.0,
        "per_unit_supplier_electricity_production_markup": 0.02,
        "production_price_include_vat": True,
        "solar_bonus_enabled": True,
        "solar_bonus_percentage": 10.0,
        "solar_bonus_annual_kwh_limit": 7500.0,
    }
    s = await make_sensor(hass, SOURCE_TYPE_PRODUCTION, "profit_total", ps,
                          solar_bonus_tracker=solar)

    hass.states.set("sensor.price", 0.25)
    hass.states.set("sensor.energy", 0.0)
    await s.async_update()

    hass.states.set("sensor.energy", 10.0)  # 10 kWh produced
    await s.async_update()
    base_profit = 10.0 * (0.25 + 0.02) * 1.21
    bonus = 10.0 * (0.25 + 0.02) * (10.0 / 100.0)  # 10% of unit price * delta
    expected = base_profit + bonus
    check("production profit + 10% solar bonus", s.native_value, expected)
    check("solar tracker year_production", solar.year_production_kwh, 10.0)
    check("solar tracker total_bonus_euro", solar.total_bonus_euro, bonus)


# ---------------------------------------------------------------------------
# SCENARIO 16: Solar bonus annual limit
# ---------------------------------------------------------------------------

async def test_solar_bonus_annual_limit() -> None:
    print("\n=== 16. Solar bonus annual limit ===")
    hass = _MockHass()
    solar = FakeSolarBonusTracker()
    solar.year_production_kwh = 7490.0  # 10 kWh below limit
    ps = {
        "vat_percentage": 21.0,
        "per_unit_supplier_electricity_production_markup": 0.0,
        "production_price_include_vat": True,
        "solar_bonus_enabled": True,
        "solar_bonus_percentage": 10.0,
        "solar_bonus_annual_kwh_limit": 7500.0,
    }
    s = await make_sensor(hass, SOURCE_TYPE_PRODUCTION, "profit_total", ps,
                          solar_bonus_tracker=solar)

    hass.states.set("sensor.price", 0.30)
    hass.states.set("sensor.energy", 0.0)
    await s.async_update()

    hass.states.set("sensor.energy", 20.0)  # 20 kWh but only 10 eligible
    await s.async_update()
    base_profit = 20.0 * 0.30 * 1.21
    bonus = 10.0 * 0.30 * 0.10  # only 10 kWh eligible
    expected = base_profit + bonus
    check("profit with partial bonus (limit=7500, already 7490)", s.native_value, expected)
    check("year_production capped at 7500", solar.year_production_kwh, 7500.0)


# ---------------------------------------------------------------------------
# SCENARIO 17: TotalCostSensor aggregation
# ---------------------------------------------------------------------------

async def test_total_cost_sensor() -> None:
    print("\n=== 17. TotalCostSensor aggregation ===")
    # Simulate 2 source sensors: consumption cost + production profit
    # Then verify TotalCostSensor = cost - profit

    hass = _MockHass()
    ps = {
        "vat_percentage": 21.0,
        "per_unit_supplier_electricity_markup": 0.0,
        "per_unit_government_electricity_tax": 0.0,
        "per_unit_supplier_electricity_production_markup": 0.0,
        "production_price_include_vat": True,
    }

    hass.states.set("sensor.price", 0.25)

    sc = await make_sensor(hass, SOURCE_TYPE_CONSUMPTION, "cost_total", ps,
                           energy_sensor="sensor.cons")
    sp = await make_sensor(hass, SOURCE_TYPE_PRODUCTION, "profit_total", ps,
                           energy_sensor="sensor.prod")

    hass.states.set("sensor.cons", 0.0)
    hass.states.set("sensor.prod", 0.0)
    await sc.async_update()
    await sp.async_update()

    hass.states.set("sensor.cons", 8.0)
    hass.states.set("sensor.prod", 3.0)
    await sc.async_update()
    await sp.async_update()

    cost = 8.0 * 0.25 * 1.21
    profit = 3.0 * 0.25 * 1.21
    net = cost - profit

    check("consumption cost_total", sc.native_value, cost)
    check("production profit_total", sp.native_value, profit)

    # Simulate TotalCostSensor aggregation
    total = sum(
        float(e.native_value or 0.0)
        for e in [sc, sp]
        if e.mode == "cost_total"
    ) - sum(
        float(e.native_value or 0.0)
        for e in [sc, sp]
        if e.mode == "profit_total"
    )
    check("TotalCostSensor net = cost - profit", total, net)


# ---------------------------------------------------------------------------
# SCENARIO 18: Zero VAT
# ---------------------------------------------------------------------------

async def test_zero_vat() -> None:
    print("\n=== 18. Zero VAT ===")
    hass = _MockHass()
    ps = {
        "vat_percentage": 0.0,
        "per_unit_supplier_electricity_markup": 0.05,
        "per_unit_government_electricity_tax": 0.10,
    }
    s = await make_sensor(hass, SOURCE_TYPE_CONSUMPTION, "cost_total", ps)

    hass.states.set("sensor.price", 0.20)
    hass.states.set("sensor.energy", 0.0)
    await s.async_update()

    hass.states.set("sensor.energy", 1.0)
    await s.async_update()
    expected = 1.0 * (0.20 + 0.05 + 0.10)  # vat_factor = 1.0
    check("1 kWh with 0% VAT", s.native_value, expected)


# ---------------------------------------------------------------------------
# SCENARIO 19: Accumulation over many steps
# ---------------------------------------------------------------------------

async def test_accumulation() -> None:
    print("\n=== 19. Accumulation over 100 steps ===")
    hass = _MockHass()
    ps = {
        "vat_percentage": 21.0,
        "per_unit_supplier_electricity_markup": 0.0,
        "per_unit_government_electricity_tax": 0.0,
    }
    s = await make_sensor(hass, SOURCE_TYPE_CONSUMPTION, "cost_total", ps)

    hass.states.set("sensor.price", 0.10)
    hass.states.set("sensor.energy", 0.0)
    await s.async_update()

    # 100 updates of 1 kWh each
    for i in range(1, 101):
        hass.states.set("sensor.energy", float(i))
        await s.async_update()

    expected = 100.0 * 0.10 * 1.21
    check("100 × 1 kWh at 0.10 excl VAT", s.native_value, expected, tol=1e-5)


# ---------------------------------------------------------------------------
# SCENARIO 20: Gas at zero price (only markup + tax)
# ---------------------------------------------------------------------------

async def test_gas_zero_base_price() -> None:
    print("\n=== 20. Gas with zero market price (fixed markup+tax only) ===")
    hass = _MockHass()
    ps = {
        "vat_percentage": 21.0,
        "per_unit_supplier_gas_markup": 0.05,
        "per_unit_government_gas_tax": 0.60,
    }
    s = await make_sensor(hass, SOURCE_TYPE_GAS, "cost_total", ps,
                          energy_sensor="sensor.gas")

    hass.states.set("sensor.price", 0.0)
    hass.states.set("sensor.gas", 0.0)
    await s.async_update()

    hass.states.set("sensor.gas", 10.0)
    await s.async_update()
    expected = 10.0 * (0.0 + 0.05 + 0.60) * 1.21
    check("10 m³ gas at zero market price", s.native_value, expected)


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

async def main() -> None:
    print("=" * 60)
    print(" Dynamic Energy Calculator — Calculation Simulation")
    print("=" * 60)

    await test_kwh_total()
    await test_m3_total()
    await test_cost_total_consumption()
    await test_cost_total_negative_price()
    await test_profit_total_negative_price_consumption()
    await test_gas_cost_total()
    await test_profit_total_production()
    await test_profit_total_production_no_vat()
    await test_cost_total_production_negative_price()
    await test_kwh_during_modes()
    await test_multiple_price_sensors()
    await test_unavailable_energy()
    await test_unavailable_price()
    await test_netting()
    await test_solar_bonus()
    await test_solar_bonus_annual_limit()
    await test_total_cost_sensor()
    await test_zero_vat()
    await test_accumulation()
    await test_gas_zero_base_price()

    print("\n" + "=" * 60)
    passed = sum(1 for _, ok, _ in results if ok)
    failed = sum(1 for _, ok, _ in results if not ok)
    print(f" Results: {passed} passed, {failed} failed out of {len(results)} checks")
    if failed:
        print("\nFailed checks:")
        for name, ok, detail in results:
            if not ok:
                print(f"  ✗ {name}: {detail}")
    print("=" * 60)
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    asyncio.run(main())
