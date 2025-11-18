"""
Comprehensive tests for all known Dutch energy supplier configurations.

Tests each supplier against:
- 3 energy scenarios: more consumption than production, more production than consumption, equal
- Positive and negative spot prices for both consumption and production

This generates a test matrix to verify pricing calculations for all suppliers.
"""

import pytest
from homeassistant.core import HomeAssistant

from custom_components.dynamic_energy_contract_calculator.entity import (
    DynamicEnergySensor,
)
from custom_components.dynamic_energy_contract_calculator.const import (
    SOURCE_TYPE_CONSUMPTION,
    SOURCE_TYPE_PRODUCTION,
)


# Supplier configurations based on current documentation
SUPPLIER_CONFIGS = {
    "ANWB Energie": {
        "per_unit_supplier_electricity_markup": 0.040,
        "per_unit_supplier_electricity_production_markup": 0.040,
        "per_unit_government_electricity_tax": 0.1017,
        "vat_percentage": 21.0,
        "production_price_include_vat": True,
        "overage_compensation_enabled": True,
        "overage_compensation_rate": 0.040,
        "surplus_vat_enabled": False,
        "production_bonus_percentage": 0.0,
        "negative_price_production_bonus_percentage": 0.0,
    },
    "Tibber": {
        "per_unit_supplier_electricity_markup": 0.021,
        "per_unit_supplier_electricity_production_markup": 0.021,
        "per_unit_government_electricity_tax": 0.1017,
        "vat_percentage": 21.0,
        "production_price_include_vat": True,
        "overage_compensation_enabled": True,
        "overage_compensation_rate": 0.021,
        "surplus_vat_enabled": False,
        "production_bonus_percentage": 0.0,
        "negative_price_production_bonus_percentage": 0.0,
    },
    "Zonneplan": {
        "per_unit_supplier_electricity_markup": 0.025,
        "per_unit_supplier_electricity_production_markup": 0.0,
        "per_unit_supplier_electricity_production_surcharge": 0.02,  # €0.02 surcharge before bonus
        "per_unit_government_electricity_tax": 0.1017,
        "vat_percentage": 21.0,
        "production_price_include_vat": True,
        "overage_compensation_enabled": False,
        "overage_compensation_rate": 0.0,
        "surplus_vat_enabled": False,
        "production_bonus_percentage": 10.0,  # 10% on (price + surcharge)
        "negative_price_production_bonus_percentage": 0.0,
    },
    "Frank Energie": {
        "per_unit_supplier_electricity_markup": 0.010,
        "per_unit_supplier_electricity_production_markup": 0.0,
        "per_unit_government_electricity_tax": 0.1017,
        "vat_percentage": 21.0,
        "production_price_include_vat": True,
        "overage_compensation_enabled": False,
        "overage_compensation_rate": 0.0,
        "surplus_vat_enabled": False,
        "production_bonus_percentage": 15.0,  # 15% bonus on all production
        "negative_price_production_bonus_percentage": 0.0,
    },
    "easyEnergy": {
        "per_unit_supplier_electricity_markup": 0.0,
        "per_unit_supplier_electricity_production_markup": 0.0,
        "per_unit_government_electricity_tax": 0.1017,
        "vat_percentage": 21.0,
        "production_price_include_vat": True,
        "overage_compensation_enabled": True,
        "overage_compensation_rate": 0.0,
        "surplus_vat_enabled": False,
        "production_bonus_percentage": 0.0,
        "negative_price_production_bonus_percentage": 0.0,
    },
    "Budget Energie": {
        "per_unit_supplier_electricity_markup": 0.017,
        "per_unit_supplier_electricity_production_markup": 0.017,
        "per_unit_government_electricity_tax": 0.1017,
        "vat_percentage": 21.0,
        "production_price_include_vat": True,
        "overage_compensation_enabled": True,
        "overage_compensation_rate": 0.017,
        "surplus_vat_enabled": False,
        "production_bonus_percentage": 0.0,
        "negative_price_production_bonus_percentage": 0.0,
    },
    "Vandebron": {
        "per_unit_supplier_electricity_markup": 0.030,
        "per_unit_supplier_electricity_production_markup": 0.030,
        "per_unit_government_electricity_tax": 0.1017,
        "vat_percentage": 21.0,
        "production_price_include_vat": True,
        "overage_compensation_enabled": True,
        "overage_compensation_rate": 0.060,  # Double deduction for surplus
        "surplus_vat_enabled": False,
        "production_bonus_percentage": 0.0,
        "negative_price_production_bonus_percentage": 0.0,
    },
    "NextEnergy": {
        "per_unit_supplier_electricity_markup": 0.022,
        "per_unit_supplier_electricity_production_markup": 0.022,
        "per_unit_government_electricity_tax": 0.1017,
        "vat_percentage": 21.0,
        "production_price_include_vat": True,
        "overage_compensation_enabled": True,
        "overage_compensation_rate": 0.044,  # Double deduction for surplus
        "surplus_vat_enabled": False,
        "production_bonus_percentage": 0.0,
        "negative_price_production_bonus_percentage": 0.0,
    },
}

# Test scenarios
ENERGY_SCENARIOS = {
    "more_consumption": {"consumption_kwh": 10.0, "production_kwh": 5.0},
    "more_production": {"consumption_kwh": 5.0, "production_kwh": 10.0},
    "equal": {"consumption_kwh": 10.0, "production_kwh": 10.0},
}

# Price scenarios (spot prices in EUR/kWh)
PRICE_SCENARIOS = {
    "positive_high": 0.20,
    "positive_low": 0.05,
    "zero": 0.00,
    "negative_low": -0.05,
    "negative_high": -0.20,
}


def calculate_expected_consumption_cost(
    kwh: float, spot_price: float, config: dict
) -> float:
    """Calculate expected consumption cost based on supplier config."""
    markup = config.get("per_unit_supplier_electricity_markup", 0.0)
    tax = config.get("per_unit_government_electricity_tax", 0.0)
    vat = config.get("vat_percentage", 21.0) / 100.0 + 1.0

    unit_price = (spot_price + markup + tax) * vat
    return kwh * unit_price


def calculate_expected_production_profit(
    kwh: float, spot_price: float, config: dict
) -> float:
    """Calculate expected production profit based on supplier config."""
    markup = config.get("per_unit_supplier_electricity_production_markup", 0.0)
    surcharge = config.get("per_unit_supplier_electricity_production_surcharge", 0.0)
    vat = config.get("vat_percentage", 21.0) / 100.0 + 1.0
    include_vat = config.get("production_price_include_vat", True)
    production_bonus_pct = config.get("production_bonus_percentage", 0.0)
    negative_price_bonus_pct = config.get("negative_price_production_bonus_percentage", 0.0)

    # Calculate effective price with surcharge and bonuses
    # First add surcharge (before bonus calculation)
    base_for_bonus = spot_price + surcharge

    # Apply general production bonus
    if production_bonus_pct != 0.0:
        effective_price = base_for_bonus * (1 + production_bonus_pct / 100.0)
    else:
        effective_price = base_for_bonus

    # Apply negative price bonus when price is negative
    if spot_price < 0 and negative_price_bonus_pct != 0.0:
        effective_price = spot_price * (1 + negative_price_bonus_pct / 100.0)

    if include_vat:
        unit_price = (effective_price - markup) * vat
    else:
        unit_price = effective_price - markup

    # Profit only counted when unit_price >= 0
    if unit_price >= 0:
        return kwh * unit_price
    else:
        return 0.0


def calculate_expected_production_cost(
    kwh: float, spot_price: float, config: dict
) -> float:
    """Calculate expected production cost (when price is negative)."""
    markup = config.get("per_unit_supplier_electricity_production_markup", 0.0)
    surcharge = config.get("per_unit_supplier_electricity_production_surcharge", 0.0)
    vat = config.get("vat_percentage", 21.0) / 100.0 + 1.0
    include_vat = config.get("production_price_include_vat", True)
    production_bonus_pct = config.get("production_bonus_percentage", 0.0)
    negative_price_bonus_pct = config.get("negative_price_production_bonus_percentage", 0.0)

    # Calculate effective price with surcharge and bonuses
    # First add surcharge (before bonus calculation)
    base_for_bonus = spot_price + surcharge

    # Apply general production bonus
    if production_bonus_pct != 0.0:
        effective_price = base_for_bonus * (1 + production_bonus_pct / 100.0)
    else:
        effective_price = base_for_bonus

    # Apply negative price bonus when price is negative
    if spot_price < 0 and negative_price_bonus_pct != 0.0:
        effective_price = spot_price * (1 + negative_price_bonus_pct / 100.0)

    if include_vat:
        unit_price = (effective_price - markup) * vat
    else:
        unit_price = effective_price - markup

    # Cost only counted when unit_price < 0
    if unit_price < 0:
        return kwh * abs(unit_price)
    else:
        return 0.0


class TestSupplierConfigurations:
    """Test all supplier configurations against various scenarios."""

    @pytest.mark.parametrize("supplier_name,config", list(SUPPLIER_CONFIGS.items()))
    @pytest.mark.parametrize("scenario_name,scenario", list(ENERGY_SCENARIOS.items()))
    @pytest.mark.parametrize("price_name,spot_price", list(PRICE_SCENARIOS.items()))
    async def test_supplier_scenario(
        self,
        hass: HomeAssistant,
        supplier_name: str,
        config: dict,
        scenario_name: str,
        scenario: dict,
        price_name: str,
        spot_price: float,
    ):
        """Test a supplier configuration against a specific scenario and price."""
        consumption_kwh = scenario["consumption_kwh"]
        production_kwh = scenario["production_kwh"]

        # Create consumption sensor
        consumption_cost_sensor = DynamicEnergySensor(
            hass,
            f"{supplier_name} Consumption Cost",
            f"consumption_cost_{supplier_name}_{scenario_name}_{price_name}",
            "sensor.consumption_energy",
            SOURCE_TYPE_CONSUMPTION,
            config,
            price_sensor="sensor.price",
            mode="cost_total",
        )

        # Create production profit sensor
        production_profit_sensor = DynamicEnergySensor(
            hass,
            f"{supplier_name} Production Profit",
            f"production_profit_{supplier_name}_{scenario_name}_{price_name}",
            "sensor.production_energy",
            SOURCE_TYPE_PRODUCTION,
            config,
            price_sensor="sensor.price",
            mode="profit_total",
        )

        # Create production cost sensor (for negative prices)
        production_cost_sensor = DynamicEnergySensor(
            hass,
            f"{supplier_name} Production Cost",
            f"production_cost_{supplier_name}_{scenario_name}_{price_name}",
            "sensor.production_energy",
            SOURCE_TYPE_PRODUCTION,
            config,
            price_sensor="sensor.price",
            mode="cost_total",
        )

        # Set up initial states
        consumption_cost_sensor._last_energy = 0
        production_profit_sensor._last_energy = 0
        production_cost_sensor._last_energy = 0

        # Set the states
        hass.states.async_set("sensor.consumption_energy", consumption_kwh)
        hass.states.async_set("sensor.production_energy", production_kwh)
        hass.states.async_set("sensor.price", spot_price)

        # Update sensors
        await consumption_cost_sensor.async_update()
        await production_profit_sensor.async_update()
        await production_cost_sensor.async_update()

        # Calculate expected values
        expected_consumption_cost = calculate_expected_consumption_cost(
            consumption_kwh, spot_price, config
        )
        expected_production_profit = calculate_expected_production_profit(
            production_kwh, spot_price, config
        )
        expected_production_cost = calculate_expected_production_cost(
            production_kwh, spot_price, config
        )

        # Verify results
        assert consumption_cost_sensor.native_value == pytest.approx(
            expected_consumption_cost, rel=1e-4
        ), f"{supplier_name} consumption cost mismatch"

        assert production_profit_sensor.native_value == pytest.approx(
            expected_production_profit, rel=1e-4
        ), f"{supplier_name} production profit mismatch"

        assert production_cost_sensor.native_value == pytest.approx(
            expected_production_cost, rel=1e-4
        ), f"{supplier_name} production cost mismatch"


class TestZonneplanSpecific:
    """Specific tests for Zonneplan's 10% production bonus with €0.02 surcharge."""

    async def test_zonneplan_production_bonus_positive_price(self, hass: HomeAssistant):
        """Test Zonneplan's formula: (price + €0.02) * 1.10 at positive price."""
        config = SUPPLIER_CONFIGS["Zonneplan"]
        spot_price = 0.10  # EUR/kWh
        kwh = 1.0

        sensor = DynamicEnergySensor(
            hass,
            "Zonneplan Production",
            "zonneplan_prod_bonus",
            "sensor.production_energy",
            SOURCE_TYPE_PRODUCTION,
            config,
            price_sensor="sensor.price",
            mode="profit_total",
        )
        sensor._last_energy = 0

        hass.states.async_set("sensor.production_energy", kwh)
        hass.states.async_set("sensor.price", spot_price)

        await sensor.async_update()

        # Expected: (0.10 + 0.02) * 1.10 (10% bonus) * 1.21 (VAT) = 0.15972
        expected = (spot_price + 0.02) * 1.10 * 1.21
        assert sensor.native_value == pytest.approx(expected, rel=1e-4)

    async def test_zonneplan_production_bonus_negative_price(self, hass: HomeAssistant):
        """Test Zonneplan's formula at negative price (with surcharge still applied)."""
        config = SUPPLIER_CONFIGS["Zonneplan"]
        spot_price = -0.10  # EUR/kWh
        kwh = 1.0

        sensor = DynamicEnergySensor(
            hass,
            "Zonneplan Production Neg",
            "zonneplan_prod_bonus_neg",
            "sensor.production_energy",
            SOURCE_TYPE_PRODUCTION,
            config,
            price_sensor="sensor.price",
            mode="cost_total",
        )
        sensor._last_energy = 0

        hass.states.async_set("sensor.production_energy", kwh)
        hass.states.async_set("sensor.price", spot_price)

        await sensor.async_update()

        # Expected: (-0.10 + 0.02) * 1.10 * 1.21 = -0.1065 -> cost = 0.1065
        # Note: In practice, Zonneplan bonus doesn't apply during negative prices
        expected = abs((spot_price + 0.02) * 1.10 * 1.21)
        assert sensor.native_value == pytest.approx(expected, rel=1e-4)


class TestFrankEnergieSpecific:
    """Specific tests for Frank Energie's 15% production bonus."""

    async def test_frank_energie_production_bonus_positive_price(self, hass: HomeAssistant):
        """Test Frank Energie's 15% bonus at positive price."""
        config = SUPPLIER_CONFIGS["Frank Energie"]
        spot_price = 0.10  # EUR/kWh
        kwh = 1.0

        sensor = DynamicEnergySensor(
            hass,
            "Frank Energie Production",
            "frank_prod_bonus",
            "sensor.production_energy",
            SOURCE_TYPE_PRODUCTION,
            config,
            price_sensor="sensor.price",
            mode="profit_total",
        )
        sensor._last_energy = 0

        hass.states.async_set("sensor.production_energy", kwh)
        hass.states.async_set("sensor.price", spot_price)

        await sensor.async_update()

        # Expected: 0.10 * 1.15 (15% bonus) * 1.21 (VAT) = 0.13915
        expected = spot_price * 1.15 * 1.21
        assert sensor.native_value == pytest.approx(expected, rel=1e-4)

    async def test_frank_energie_bonus_also_at_negative_price(self, hass: HomeAssistant):
        """Test Frank Energie's 15% bonus also applies at negative price (cost scenario)."""
        config = SUPPLIER_CONFIGS["Frank Energie"]
        spot_price = -0.10  # EUR/kWh
        kwh = 1.0

        sensor = DynamicEnergySensor(
            hass,
            "Frank Energie Production Neg",
            "frank_prod_bonus_neg",
            "sensor.production_energy",
            SOURCE_TYPE_PRODUCTION,
            config,
            price_sensor="sensor.price",
            mode="cost_total",
        )
        sensor._last_energy = 0

        hass.states.async_set("sensor.production_energy", kwh)
        hass.states.async_set("sensor.price", spot_price)

        await sensor.async_update()

        # Expected: -0.10 * 1.15 (15% bonus) * 1.21 (VAT) = -0.13915 -> cost = 0.13915
        # Note: In practice, Slim Terugleveren would prevent production at negative prices
        expected = abs(spot_price * 1.15 * 1.21)
        assert sensor.native_value == pytest.approx(expected, rel=1e-4)


class TestNetCostCalculations:
    """Test net cost calculations (consumption - production profit)."""

    @pytest.mark.parametrize("supplier_name,config", list(SUPPLIER_CONFIGS.items()))
    async def test_net_cost_positive_price(
        self, hass: HomeAssistant, supplier_name: str, config: dict
    ):
        """Test net cost with positive spot price."""
        spot_price = 0.15
        consumption_kwh = 10.0
        production_kwh = 5.0

        # Create sensors
        consumption_sensor = DynamicEnergySensor(
            hass,
            f"{supplier_name} Consumption",
            f"net_consumption_{supplier_name}",
            "sensor.consumption_energy",
            SOURCE_TYPE_CONSUMPTION,
            config,
            price_sensor="sensor.price",
            mode="cost_total",
        )
        production_sensor = DynamicEnergySensor(
            hass,
            f"{supplier_name} Production",
            f"net_production_{supplier_name}",
            "sensor.production_energy",
            SOURCE_TYPE_PRODUCTION,
            config,
            price_sensor="sensor.price",
            mode="profit_total",
        )

        consumption_sensor._last_energy = 0
        production_sensor._last_energy = 0

        hass.states.async_set("sensor.consumption_energy", consumption_kwh)
        hass.states.async_set("sensor.production_energy", production_kwh)
        hass.states.async_set("sensor.price", spot_price)

        await consumption_sensor.async_update()
        await production_sensor.async_update()

        # Calculate net cost
        net_cost = consumption_sensor.native_value - production_sensor.native_value

        # For all suppliers, net cost should be positive when consuming more than producing
        assert net_cost > 0, f"{supplier_name} net cost should be positive"


# Helper function to generate test results table
def generate_test_results_table():
    """Generate a markdown table of test results for all suppliers."""
    results = []

    for supplier_name, config in SUPPLIER_CONFIGS.items():
        for scenario_name, scenario in ENERGY_SCENARIOS.items():
            for price_name, spot_price in PRICE_SCENARIOS.items():
                consumption_kwh = scenario["consumption_kwh"]
                production_kwh = scenario["production_kwh"]

                consumption_cost = calculate_expected_consumption_cost(
                    consumption_kwh, spot_price, config
                )
                production_profit = calculate_expected_production_profit(
                    production_kwh, spot_price, config
                )
                production_cost = calculate_expected_production_cost(
                    production_kwh, spot_price, config
                )
                net_cost = consumption_cost - production_profit + production_cost

                results.append({
                    "supplier": supplier_name,
                    "scenario": scenario_name,
                    "price": price_name,
                    "spot_price": spot_price,
                    "consumption_kwh": consumption_kwh,
                    "production_kwh": production_kwh,
                    "consumption_cost": round(consumption_cost, 4),
                    "production_profit": round(production_profit, 4),
                    "production_cost": round(production_cost, 4),
                    "net_cost": round(net_cost, 4),
                })

    return results


if __name__ == "__main__":
    # Generate and print test results table when run directly
    results = generate_test_results_table()

    print("| Supplier | Scenario | Price | Spot | Cons kWh | Prod kWh | Cons Cost | Prod Profit | Prod Cost | Net Cost |")
    print("|----------|----------|-------|------|----------|----------|-----------|-------------|-----------|----------|")

    for r in results:
        print(f"| {r['supplier']} | {r['scenario']} | {r['price']} | {r['spot_price']:.2f} | "
              f"{r['consumption_kwh']:.1f} | {r['production_kwh']:.1f} | "
              f"{r['consumption_cost']:.4f} | {r['production_profit']:.4f} | "
              f"{r['production_cost']:.4f} | {r['net_cost']:.4f} |")
