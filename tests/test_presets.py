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

    # Test consumption costs (exclusive VAT - will be multiplied by 1.21)
    assert abs(preset["per_unit_supplier_electricity_markup"] - 0.01653) < 0.00001
    assert abs(preset["per_unit_government_electricity_tax"] - 0.10880) < 0.00001
    assert abs(preset["per_day_supplier_electricity_standing_charge"] - 0.17355) < 0.00001
    assert abs(preset["per_day_grid_operator_electricity_connection_fee"] - 1.07438) < 0.00001
    assert abs(preset["per_day_government_electricity_tax_rebate"] - 1.42975) < 0.00001

    # Test production revenue
    assert abs(preset["per_unit_supplier_electricity_production_markup"] - 0.01653) < 0.00001

    # Test VAT settings (prices are exclusive of VAT, integration calculates VAT)
    assert preset["vat_percentage"] == 21.0
    assert preset["production_price_include_vat"] is True

    # Test netting is enabled
    assert preset["netting_enabled"] is True

    # Test solar bonus settings
    assert preset["solar_bonus_enabled"] is True
    assert preset["solar_bonus_percentage"] == 10.0
    assert preset["solar_bonus_annual_kwh_limit"] == 7500.0

    # Test gas settings (not used for Zonneplan electricity)
    assert preset["per_unit_supplier_gas_markup"] == 0.0
    assert preset["per_unit_government_gas_tax"] == 0.0
    assert preset["per_day_grid_operator_gas_connection_fee"] == 0.0
    assert preset["per_day_supplier_gas_standing_charge"] == 0.0


def test_zonneplan_vat_calculation():
    """Test that VAT calculation yields correct inclusive prices."""
    preset = PRESET_ZONNEPLAN_2025
    vat_factor = 1.21

    # Test per-unit costs: exclusive * 1.21 should equal inclusive
    # Inkoopvergoeding: €0.02 inclusive
    assert abs((preset["per_unit_supplier_electricity_markup"] * vat_factor) - 0.02) < 0.0001

    # Energiebelasting: €0.13165 inclusive
    assert abs((preset["per_unit_government_electricity_tax"] * vat_factor) - 0.13165) < 0.0001

    # Test daily costs: (exclusive * 1.21) should match original daily inclusive
    # Vaste leveringskosten: €6.25/month = €0.21/day inclusive
    daily_standing_charge_incl = preset["per_day_supplier_electricity_standing_charge"] * vat_factor
    assert abs(daily_standing_charge_incl - (6.25 / 30.416667)) < 0.001

    # Netbeheerkosten: €39.48/month = €1.30/day inclusive
    daily_connection_fee_incl = preset["per_day_grid_operator_electricity_connection_fee"] * vat_factor
    assert abs(daily_connection_fee_incl - (39.48 / 30.416667)) < 0.001

    # Vermindering energiebelasting: €52.62/month = €1.73/day inclusive
    daily_rebate_incl = preset["per_day_government_electricity_tax_rebate"] * vat_factor
    assert abs(daily_rebate_incl - (52.62 / 30.416667)) < 0.001


def test_zonneplan_daily_costs_calculation():
    """Test that daily costs match Zonneplan monthly rates (with VAT)."""
    preset = PRESET_ZONNEPLAN_2025
    vat_factor = 1.21

    # Calculate monthly costs from daily rates (including VAT)
    # Using 30.416667 days per month (365/12)
    days_per_month = 30.416667

    # Vaste leveringskosten: €6.25 per maand (inclusive VAT)
    monthly_standing_charge = preset["per_day_supplier_electricity_standing_charge"] * days_per_month * vat_factor
    assert abs(monthly_standing_charge - 6.25) < 0.01

    # Netbeheerkosten: €39.48 per maand (inclusive VAT)
    monthly_connection_fee = preset["per_day_grid_operator_electricity_connection_fee"] * days_per_month * vat_factor
    assert abs(monthly_connection_fee - 39.48) < 0.01

    # Vermindering energiebelasting: €52.62 per maand (inclusive VAT)
    monthly_rebate = preset["per_day_government_electricity_tax_rebate"] * days_per_month * vat_factor
    assert abs(monthly_rebate - 52.62) < 0.01
