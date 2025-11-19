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


def generate_supplier_overview_table():
    """Generate a consolidated overview table of all supplier configurations."""
    print("## Supplier Configuration Overview\n")
    print("| Supplier | Markup | Fixed/month | Bonus | Bonus Hours | Overage Rate |")
    print("|----------|--------|-------------|-------|-------------|--------------|")

    for supplier_name, config in SUPPLIER_CONFIGS.items():
        markup = config.get("per_unit_supplier_electricity_markup", 0.0)
        daily_fixed = config.get("per_day_supplier_electricity_standing_charge", 0.0)
        monthly_fixed = daily_fixed * 30.44 * 1.21  # Including VAT
        bonus_pct = config.get("production_bonus_percentage", 0.0)
        surcharge = config.get(
            "per_unit_supplier_electricity_production_surcharge", 0.0
        )
        overage_rate = config.get("overage_compensation_rate", 0.0)
        overage_enabled = config.get("overage_compensation_enabled", False)

        # Format bonus info
        if bonus_pct > 0:
            if supplier_name == "Zonneplan":
                bonus_str = f"{bonus_pct:.0f}% (+€{surcharge:.2f})"
            else:
                bonus_str = f"{bonus_pct:.0f}%"
        else:
            bonus_str = "-"

        # Format bonus hours
        if supplier_name == "Zonneplan":
            hours_str = "08:00-19:00"
        elif supplier_name == "Frank Energie":
            hours_str = "All hours"
        else:
            hours_str = "-"

        # Format overage rate
        if overage_enabled and overage_rate > 0:
            overage_str = f"€{overage_rate:.3f}"
        else:
            overage_str = "-"

        print(
            f"| {supplier_name} | €{markup:.4f} | €{monthly_fixed:.2f} | "
            f"{bonus_str} | {hours_str} | {overage_str} |"
        )

    print("")


def generate_yearly_cost_comparison_table():
    """Generate a yearly cost comparison table showing estimated costs for each supplier."""
    # Yearly assumptions
    yearly_consumption_kwh = 3500.0  # Average Dutch household consumption
    yearly_production_kwh = 3000.0  # Typical solar panel production
    avg_spot_price = 0.08  # Average spot price EUR/kWh
    days_per_year = 365
    # Assume 90% of production happens during Zonneplan bonus hours (08:00-19:00)
    zonneplan_bonus_production_ratio = 0.90

    print("## Yearly Cost Comparison\n")
    print("### Assumptions\n")
    print(f"- **Yearly consumption**: {yearly_consumption_kwh:.0f} kWh")
    print(f"- **Yearly production**: {yearly_production_kwh:.0f} kWh")
    print(f"- **Average spot price**: €{avg_spot_price:.2f}/kWh")
    print("- **Government electricity tax**: €0.1017/kWh")
    print("- **VAT**: 21%")
    print(
        f"- **Production during bonus hours (08-19)**: {zonneplan_bonus_production_ratio * 100:.0f}%"
    )
    print("- **Spot price assumed non-negative** (bonuses apply)")
    print("")

    print("| Supplier | Fixed/yr | Cons Cost | Prod Profit | Est. Yearly Cost |")
    print("|----------|----------|-----------|-------------|------------------:|")

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

        results.append(
            (
                supplier_name,
                yearly_fixed_cost,
                consumption_cost,
                production_profit,
                net_cost,
            )
        )

    # Sort by net cost (lowest first)
    results.sort(key=lambda x: x[4])

    for (
        supplier_name,
        yearly_fixed_cost,
        consumption_cost,
        production_profit,
        net_cost,
    ) in results:
        print(
            f"| {supplier_name} | €{yearly_fixed_cost:.2f} | "
            f"€{consumption_cost:.2f} | €{production_profit:.2f} | €{net_cost:.2f} |"
        )

    print("\n*Table sorted by estimated yearly cost (lowest first)*\n")


if __name__ == "__main__":
    generate_supplier_overview_table()
    generate_yearly_cost_comparison_table()
