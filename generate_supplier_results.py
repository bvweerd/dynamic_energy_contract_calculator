#!/usr/bin/env python3
"""
Generate test results table for all supplier configurations.

This script calculates expected costs and profits for all Dutch energy suppliers
against various price and energy scenarios.
"""

# Supplier configurations based on current documentation (November 2025)
SUPPLIER_CONFIGS = {
    "ANWB Energie": {
        "per_unit_supplier_electricity_markup": 0.040,
        "per_unit_supplier_electricity_production_markup": 0.040,
        "per_unit_government_electricity_tax": 0.1017,
        "per_day_supplier_electricity_standing_charge": 0.2301,  # ~€7.00/month
        "vat_percentage": 21.0,
        "production_price_include_vat": True,
        "overage_compensation_enabled": True,
        "overage_compensation_rate": 0.040,
        "surplus_vat_enabled": False,
        "production_bonus_percentage": 0.0,
        "negative_price_production_bonus_percentage": 0.0,
    },
    "Tibber": {
        "per_unit_supplier_electricity_markup": 0.0248,  # Updated Nov 2025
        "per_unit_supplier_electricity_production_markup": 0.0248,
        "per_unit_government_electricity_tax": 0.1017,
        "per_day_supplier_electricity_standing_charge": 0.1970,  # €5.99/month
        "vat_percentage": 21.0,
        "production_price_include_vat": True,
        "overage_compensation_enabled": True,
        "overage_compensation_rate": 0.0248,
        "surplus_vat_enabled": False,
        "production_bonus_percentage": 0.0,
        "negative_price_production_bonus_percentage": 0.0,
    },
    "Zonneplan": {
        "per_unit_supplier_electricity_markup": 0.0200,  # Updated Nov 2025
        "per_unit_supplier_electricity_production_markup": 0.0,
        "per_unit_supplier_electricity_production_surcharge": 0.02,  # €0.02 surcharge before bonus
        "per_unit_government_electricity_tax": 0.1017,
        "per_day_supplier_electricity_standing_charge": 0.2055,  # €6.25/month
        "vat_percentage": 21.0,
        "production_price_include_vat": True,
        "overage_compensation_enabled": False,
        "overage_compensation_rate": 0.0,
        "surplus_vat_enabled": False,
        "production_bonus_percentage": 10.0,  # 10% on (price + surcharge)
        "negative_price_production_bonus_percentage": 0.0,
    },
    "Frank Energie": {
        "per_unit_supplier_electricity_markup": 0.0182,  # Updated Nov 2025
        "per_unit_supplier_electricity_production_markup": 0.0,
        "per_unit_government_electricity_tax": 0.1017,
        "per_day_supplier_electricity_standing_charge": 0.2301,  # €7.00/month
        "vat_percentage": 21.0,
        "production_price_include_vat": True,
        "overage_compensation_enabled": False,
        "overage_compensation_rate": 0.0,
        "surplus_vat_enabled": False,
        "production_bonus_percentage": 15.0,  # 15% bonus on all production
        "negative_price_production_bonus_percentage": 0.0,
    },
    "easyEnergy": {
        "per_unit_supplier_electricity_markup": 0.0218,  # Updated Nov 2025
        "per_unit_supplier_electricity_production_markup": 0.0218,
        "per_unit_government_electricity_tax": 0.1017,
        "per_day_supplier_electricity_standing_charge": 0.2301,  # €7.00/month
        "vat_percentage": 21.0,
        "production_price_include_vat": True,
        "overage_compensation_enabled": True,
        "overage_compensation_rate": 0.0218,
        "surplus_vat_enabled": False,
        "production_bonus_percentage": 0.0,
        "negative_price_production_bonus_percentage": 0.0,
    },
    "Budget Energie": {
        "per_unit_supplier_electricity_markup": 0.017,
        "per_unit_supplier_electricity_production_markup": 0.017,
        "per_unit_government_electricity_tax": 0.1017,
        "per_day_supplier_electricity_standing_charge": 0.1973,  # ~€6.00/month
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
        "per_day_supplier_electricity_standing_charge": 0.2466,  # ~€7.50/month
        "vat_percentage": 21.0,
        "production_price_include_vat": True,
        "overage_compensation_enabled": True,
        "overage_compensation_rate": 0.060,
        "surplus_vat_enabled": False,
        "production_bonus_percentage": 0.0,
        "negative_price_production_bonus_percentage": 0.0,
    },
    "NextEnergy": {
        "per_unit_supplier_electricity_markup": 0.0219,  # Updated Nov 2025
        "per_unit_supplier_electricity_production_markup": 0.0219,
        "per_unit_government_electricity_tax": 0.1017,
        "per_day_supplier_electricity_standing_charge": 0.1970,  # €5.99/month
        "vat_percentage": 21.0,
        "production_price_include_vat": True,
        "overage_compensation_enabled": True,
        "overage_compensation_rate": 0.044,
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


def calculate_expected_consumption_cost(kwh, spot_price, config):
    """Calculate expected consumption cost based on supplier config."""
    markup = config.get("per_unit_supplier_electricity_markup", 0.0)
    tax = config.get("per_unit_government_electricity_tax", 0.0)
    vat = config.get("vat_percentage", 21.0) / 100.0 + 1.0

    unit_price = (spot_price + markup + tax) * vat
    return kwh * unit_price


def calculate_expected_production_profit(kwh, spot_price, config):
    """Calculate expected production profit based on supplier config."""
    markup = config.get("per_unit_supplier_electricity_production_markup", 0.0)
    surcharge = config.get("per_unit_supplier_electricity_production_surcharge", 0.0)
    vat = config.get("vat_percentage", 21.0) / 100.0 + 1.0
    include_vat = config.get("production_price_include_vat", True)
    production_bonus_pct = config.get("production_bonus_percentage", 0.0)
    negative_price_bonus_pct = config.get(
        "negative_price_production_bonus_percentage", 0.0
    )

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


def calculate_expected_production_cost(kwh, spot_price, config):
    """Calculate expected production cost (when price is negative)."""
    markup = config.get("per_unit_supplier_electricity_production_markup", 0.0)
    surcharge = config.get("per_unit_supplier_electricity_production_surcharge", 0.0)
    vat = config.get("vat_percentage", 21.0) / 100.0 + 1.0
    include_vat = config.get("production_price_include_vat", True)
    production_bonus_pct = config.get("production_bonus_percentage", 0.0)
    negative_price_bonus_pct = config.get(
        "negative_price_production_bonus_percentage", 0.0
    )

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


def generate_yearly_summary_table():
    """Generate a yearly summary table showing estimated costs for each supplier."""
    # Yearly assumptions
    yearly_consumption_kwh = 3500.0  # Average Dutch household consumption
    yearly_production_kwh = 3000.0  # Typical solar panel production
    avg_spot_price = 0.08  # Average spot price EUR/kWh
    days_per_year = 365
    # Assume 90% of production happens during Zonneplan bonus hours (08:00-19:00)
    zonneplan_bonus_production_ratio = 0.90

    print("## Yearly Supplier Cost Comparison\n")
    print("### Assumptions\n")
    print(f"- **Yearly consumption**: {yearly_consumption_kwh:.0f} kWh")
    print(f"- **Yearly production**: {yearly_production_kwh:.0f} kWh")
    print(f"- **Average spot price**: €{avg_spot_price:.2f}/kWh")
    print("- **Government electricity tax**: €0.1017/kWh")
    print("- **VAT**: 21%")
    print(
        f"- **Production during Zonneplan bonus hours (08-19)**: {zonneplan_bonus_production_ratio * 100:.0f}%"
    )
    print("- **Spot price assumed non-negative** (bonuses apply)")
    print("- **Fixed costs include VAT**")
    print("")

    print("### Special Conditions by Supplier\n")
    print("| Supplier | Bonus | Bonus Hours | Surcharge | Overage Rate | Notes |")
    print("|----------|-------|-------------|-----------|--------------|-------|")
    print("| ANWB Energie | - | - | - | €0.040 | Standard overage compensation |")
    print("| Tibber | - | - | - | €0.021 | Lower overage rate |")
    print("| Zonneplan | 10% | 08:00-19:00 | €0.02 | - | Bonus only during daylight |")
    print("| Frank Energie | 15% | All hours | - | - | Best bonus, all day |")
    print("| easyEnergy | - | - | - | €0.000 | No markup, no extras |")
    print("| Budget Energie | - | - | - | €0.017 | Balanced rates |")
    print("| Vandebron | - | - | - | €0.060 | High overage deduction |")
    print("| NextEnergy | - | - | - | €0.044 | High overage deduction |")
    print("")

    print("### Estimated Yearly Costs by Supplier\n")
    print(
        "| Supplier | Fixed/yr | Markup | Yearly Cons Cost | Yearly Prod Profit | Est. Yearly Cost |"
    )
    print(
        "|----------|----------|--------|------------------|--------------------|-----------------:|"
    )

    results = []
    for supplier_name, config in SUPPLIER_CONFIGS.items():
        consumption_cost = calculate_expected_consumption_cost(
            yearly_consumption_kwh, avg_spot_price, config
        )

        # Calculate fixed yearly cost (including VAT)
        daily_fixed = config.get("per_day_supplier_electricity_standing_charge", 0.0)
        vat_multiplier = 1 + config.get("vat_percentage", 21.0) / 100.0
        yearly_fixed_cost = daily_fixed * days_per_year * vat_multiplier

        # Calculate production profit with time-bound bonus consideration
        if supplier_name == "Zonneplan":
            # Split production: 90% during bonus hours, 10% outside
            bonus_production = yearly_production_kwh * zonneplan_bonus_production_ratio
            non_bonus_production = yearly_production_kwh * (
                1 - zonneplan_bonus_production_ratio
            )

            # Profit during bonus hours (with 10% bonus)
            bonus_profit = calculate_expected_production_profit(
                bonus_production, avg_spot_price, config
            )

            # Profit outside bonus hours (no bonus, just surcharge)
            config_no_bonus = config.copy()
            config_no_bonus["production_bonus_percentage"] = 0.0
            non_bonus_profit = calculate_expected_production_profit(
                non_bonus_production, avg_spot_price, config_no_bonus
            )

            production_profit = bonus_profit + non_bonus_profit
            production_cost = 0.0  # Price is positive
        else:
            production_profit = calculate_expected_production_profit(
                yearly_production_kwh, avg_spot_price, config
            )
            production_cost = calculate_expected_production_cost(
                yearly_production_kwh, avg_spot_price, config
            )

        net_cost = (
            yearly_fixed_cost + consumption_cost - production_profit + production_cost
        )

        markup = config.get("per_unit_supplier_electricity_markup", 0.0)

        results.append(
            (
                supplier_name,
                yearly_fixed_cost,
                markup,
                consumption_cost,
                production_profit,
                net_cost,
            )
        )

    # Sort by net cost (lowest first)
    results.sort(key=lambda x: x[5])

    for (
        supplier_name,
        yearly_fixed_cost,
        markup,
        consumption_cost,
        production_profit,
        net_cost,
    ) in results:
        print(
            f"| {supplier_name} | €{yearly_fixed_cost:.2f} | €{markup:.4f} | "
            f"€{consumption_cost:.2f} | €{production_profit:.2f} | €{net_cost:.2f} |"
        )

    print("\n*Table sorted by estimated yearly cost (lowest first)*\n")
    print("---\n")


def generate_summary_table():
    """Generate a summary table showing key metrics for each supplier."""
    print("## Supplier Configuration Test Results\n")
    print(
        "This table shows calculated costs and profits for each supplier configuration"
    )
    print("with 10 kWh consumption and 10 kWh production at various spot prices.\n")

    print("### Summary by Supplier and Price\n")
    print("| Supplier | Spot Price | Cons Cost | Prod Profit | Prod Cost | Net Cost |")
    print("|----------|------------|-----------|-------------|-----------|----------|")

    for supplier_name, config in SUPPLIER_CONFIGS.items():
        for price_name, spot_price in PRICE_SCENARIOS.items():
            consumption_kwh = 10.0
            production_kwh = 10.0

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

            print(
                f"| {supplier_name} | {spot_price:+.2f} | "
                f"{consumption_cost:.2f} | {production_profit:.2f} | "
                f"{production_cost:.2f} | {net_cost:.2f} |"
            )


def generate_detailed_table():
    """Generate detailed results for all scenarios."""
    print("\n### Detailed Test Matrix\n")
    print(
        "Test scenarios: 10/5 kWh (more consumption), 5/10 kWh (more production), 10/10 kWh (equal)\n"
    )

    # Group by scenario for better readability
    for scenario_name, scenario in ENERGY_SCENARIOS.items():
        consumption_kwh = scenario["consumption_kwh"]
        production_kwh = scenario["production_kwh"]

        print(
            f"\n#### Scenario: {scenario_name} ({consumption_kwh:.0f} kWh consumption, {production_kwh:.0f} kWh production)\n"
        )
        print("| Supplier | Spot | Cons Cost | Prod Profit | Prod Cost | Net Cost |")
        print("|----------|------|-----------|-------------|-----------|----------|")

        for supplier_name, config in SUPPLIER_CONFIGS.items():
            for price_name, spot_price in PRICE_SCENARIOS.items():
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

                print(
                    f"| {supplier_name} | {spot_price:+.2f} | "
                    f"{consumption_cost:.2f} | {production_profit:.2f} | "
                    f"{production_cost:.2f} | {net_cost:.2f} |"
                )


def generate_special_features_table():
    """Show how special features (bonuses) affect pricing."""
    print("\n### Special Features Comparison\n")
    print(
        "This section highlights the unique features of Zonneplan and Frank Energie.\n"
    )

    print("#### Zonneplan: (price + €0.02) * 10% Bonus\n")
    print("| Spot Price | Without Bonus | With Zonneplan | Difference |")
    print("|------------|---------------|----------------|------------|")

    for spot_price in [0.20, 0.10, 0.05, -0.05, -0.10]:
        # Without bonus (like easyEnergy)
        without = spot_price * 1.21 * 10  # 10 kWh
        # With surcharge + 10% bonus: (price + 0.02) * 1.10 * VAT
        with_bonus = (spot_price + 0.02) * 1.10 * 1.21 * 10
        diff = with_bonus - without

        print(f"| {spot_price:+.2f} | {without:.2f} | {with_bonus:.2f} | {diff:+.2f} |")

    print("\n#### Frank Energie: 15% Production Bonus\n")
    print(
        "Note: With 'Slim Terugleveren', inverter is turned off during negative prices.\n"
    )
    print("| Spot Price | Without Bonus | With 15% Bonus | Difference |")
    print("|------------|---------------|----------------|------------|")

    for spot_price in [0.20, 0.10, 0.05, -0.05, -0.10]:
        # Without bonus (like easyEnergy)
        without = spot_price * 1.21 * 10  # 10 kWh
        # With 15% bonus on all production
        with_bonus = spot_price * 1.15 * 1.21 * 10
        diff = with_bonus - without

        print(f"| {spot_price:+.2f} | {without:.2f} | {with_bonus:.2f} | {diff:+.2f} |")


if __name__ == "__main__":
    generate_yearly_summary_table()
    generate_summary_table()
    generate_detailed_table()
    generate_special_features_table()
