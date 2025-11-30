"""Test supplier preset configurations."""
from custom_components.dynamic_energy_contract_calculator.const import (
    PRESET_ZONNEPLAN_2025,
    SUPPLIER_PRESETS,
)


def test_zonneplan_preset_exists():
    """Test that Zonneplan preset is available."""
    assert "zonneplan_2025" in SUPPLIER_PRESETS
    assert SUPPLIER_PRESETS["zonneplan_2025"] == PRESET_ZONNEPLAN_2025


def test_zonneplan_preset_structure():
    """Test that Zonneplan preset has correct structure and values."""
    preset = PRESET_ZONNEPLAN_2025

    # Test consumption costs
    assert preset["per_unit_supplier_electricity_markup"] == 0.02
    assert preset["per_unit_government_electricity_tax"] == 0.13165
    assert preset["per_day_supplier_electricity_standing_charge"] == 0.21
    assert preset["per_day_grid_operator_electricity_connection_fee"] == 1.30
    assert preset["per_day_government_electricity_tax_rebate"] == 1.73

    # Test production revenue
    assert preset["per_unit_supplier_electricity_production_markup"] == 0.02

    # Test VAT settings (prices are inclusive of VAT)
    assert preset["vat_percentage"] == 0.0
    assert preset["production_price_include_vat"] is False

    # Test netting is enabled
    assert preset["netting_enabled"] is True

    # Test gas settings (not used for Zonneplan electricity)
    assert preset["per_unit_supplier_gas_markup"] == 0.0
    assert preset["per_unit_government_gas_tax"] == 0.0
    assert preset["per_day_grid_operator_gas_connection_fee"] == 0.0
    assert preset["per_day_supplier_gas_standing_charge"] == 0.0


def test_zonneplan_daily_costs_calculation():
    """Test that daily costs match Zonneplan monthly rates."""
    preset = PRESET_ZONNEPLAN_2025

    # Calculate monthly costs from daily rates
    # Using 30.416667 days per month (365/12)
    days_per_month = 30.416667

    # Vaste leveringskosten: €6.25 per maand
    monthly_standing_charge = preset["per_day_supplier_electricity_standing_charge"] * days_per_month
    assert abs(monthly_standing_charge - 6.25) < 0.5  # Allow some rounding tolerance

    # Netbeheerkosten: €39.48 per maand
    monthly_connection_fee = preset["per_day_grid_operator_electricity_connection_fee"] * days_per_month
    assert abs(monthly_connection_fee - 39.48) < 0.5

    # Vermindering energiebelasting: €52.62 per maand
    monthly_rebate = preset["per_day_government_electricity_tax_rebate"] * days_per_month
    assert abs(monthly_rebate - 52.62) < 0.5
