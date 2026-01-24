"""Test supplier preset configurations."""

from custom_components.dynamic_energy_contract_calculator.config_flow import (
    ELECTRICITY_CORE_FIELDS,
    ELECTRICITY_FIELDS,
    GAS_CORE_FIELDS,
    GAS_FIELDS,
    GENERAL_FIELDS,
)
from custom_components.dynamic_energy_contract_calculator.const import (
    PRESET_GREENCHOICE_GAS_2026,
    PRESET_ZONNEPLAN_2026,
    SUPPLIER_PRESETS,
)


def test_zonneplan_preset_exists():
    """Test that Zonneplan preset is available."""
    assert "zonneplan_2026" in SUPPLIER_PRESETS
    assert SUPPLIER_PRESETS["zonneplan_2026"] == PRESET_ZONNEPLAN_2026


def test_zonneplan_preset_structure():
    """Test that Zonneplan preset has correct structure and values."""
    preset = PRESET_ZONNEPLAN_2026

    # Test consumption costs (exclusive VAT - will be multiplied by 1.21)
    assert abs(preset["per_unit_supplier_electricity_markup"] - 0.01653) < 0.00001
    assert abs(preset["per_unit_government_electricity_tax"] - 0.10880) < 0.00001
    assert (
        abs(preset["per_day_supplier_electricity_standing_charge"] - 0.17355) < 0.00001
    )
    assert (
        abs(preset["per_day_grid_operator_electricity_connection_fee"] - 1.07438)
        < 0.00001
    )
    assert abs(preset["per_day_government_electricity_tax_rebate"] - 1.42975) < 0.00001

    # Test production revenue (no VAT on production compensation)
    assert (
        abs(preset["per_unit_supplier_electricity_production_markup"] - 0.02) < 0.00001
    )

    # Test VAT settings (prices are exclusive of VAT, integration calculates VAT)
    assert preset["vat_percentage"] == 21.0
    assert preset["production_price_include_vat"] is False

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
    preset = PRESET_ZONNEPLAN_2026
    vat_factor = 1.21

    # Test per-unit costs: exclusive * 1.21 should equal inclusive
    # Inkoopvergoeding: €0.02 inclusive
    assert (
        abs((preset["per_unit_supplier_electricity_markup"] * vat_factor) - 0.02)
        < 0.0001
    )

    # Energiebelasting: €0.13165 inclusive
    assert (
        abs((preset["per_unit_government_electricity_tax"] * vat_factor) - 0.13165)
        < 0.0001
    )

    # Test daily costs: (exclusive * 1.21) should match original daily inclusive
    # Vaste leveringskosten: €6.25/month = €0.21/day inclusive
    daily_standing_charge_incl = (
        preset["per_day_supplier_electricity_standing_charge"] * vat_factor
    )
    assert abs(daily_standing_charge_incl - (6.25 / 30.416667)) < 0.005

    # Netbeheerkosten: €39.48/month = €1.30/day inclusive
    daily_connection_fee_incl = (
        preset["per_day_grid_operator_electricity_connection_fee"] * vat_factor
    )
    assert abs(daily_connection_fee_incl - (39.48 / 30.416667)) < 0.005

    # Vermindering energiebelasting: €52.62/month = €1.73/day inclusive
    daily_rebate_incl = preset["per_day_government_electricity_tax_rebate"] * vat_factor
    assert abs(daily_rebate_incl - (52.62 / 30.416667)) < 0.005


def test_zonneplan_daily_costs_calculation():
    """Test that daily costs match Zonneplan monthly rates (with VAT)."""
    preset = PRESET_ZONNEPLAN_2026
    vat_factor = 1.21

    # Calculate monthly costs from daily rates (including VAT)
    # Using 30.416667 days per month (365/12)
    days_per_month = 30.416667

    # Vaste leveringskosten: €6.25 per maand (inclusive VAT)
    monthly_standing_charge = (
        preset["per_day_supplier_electricity_standing_charge"]
        * days_per_month
        * vat_factor
    )
    assert abs(monthly_standing_charge - 6.25) < 0.15

    # Netbeheerkosten: €39.48 per maand (inclusive VAT)
    monthly_connection_fee = (
        preset["per_day_grid_operator_electricity_connection_fee"]
        * days_per_month
        * vat_factor
    )
    assert abs(monthly_connection_fee - 39.48) < 0.10

    # Vermindering energiebelasting: €52.62 per maand (inclusive VAT)
    monthly_rebate = (
        preset["per_day_government_electricity_tax_rebate"]
        * days_per_month
        * vat_factor
    )
    assert abs(monthly_rebate - 52.62) < 0.01


def test_preset_type_detection():
    """Test that preset type detection uses only core pricing fields."""
    # Zonneplan has non-zero electricity core fields, zero gas core fields
    has_electricity_zonneplan = any(
        PRESET_ZONNEPLAN_2026.get(field, 0) != 0 for field in ELECTRICITY_CORE_FIELDS
    )
    has_gas_zonneplan = any(
        PRESET_ZONNEPLAN_2026.get(field, 0) != 0 for field in GAS_CORE_FIELDS
    )
    assert has_electricity_zonneplan is True
    assert has_gas_zonneplan is False

    # Greenchoice has non-zero gas core fields, zero electricity core fields
    has_electricity_greenchoice = any(
        PRESET_GREENCHOICE_GAS_2026.get(field, 0) != 0 for field in ELECTRICITY_CORE_FIELDS
    )
    has_gas_greenchoice = any(
        PRESET_GREENCHOICE_GAS_2026.get(field, 0) != 0 for field in GAS_CORE_FIELDS
    )
    assert has_electricity_greenchoice is False
    assert has_gas_greenchoice is True


def test_preset_merge_preserves_existing_values():
    """Test that loading gas preset after electricity preset preserves electricity values.

    This is the core fix for the bug where loading Greenchoice gas preset
    would overwrite Zonneplan electricity values with zeros.
    """
    # Simulate loading Zonneplan first
    settings = {}
    preset = PRESET_ZONNEPLAN_2026

    has_gas = any(preset.get(field, 0) != 0 for field in GAS_CORE_FIELDS)
    has_electricity = any(preset.get(field, 0) != 0 for field in ELECTRICITY_CORE_FIELDS)

    # Apply Zonneplan preset (electricity-only)
    for key, value in preset.items():
        if has_gas and not has_electricity:
            if key in GAS_FIELDS or key in GENERAL_FIELDS:
                settings[key] = value
        elif has_electricity and not has_gas:
            if key in ELECTRICITY_FIELDS or key in GENERAL_FIELDS:
                settings[key] = value
        else:
            settings[key] = value

    # Store original electricity values
    original_electricity_markup = settings["per_unit_supplier_electricity_markup"]
    original_electricity_tax = settings["per_unit_government_electricity_tax"]
    original_netting = settings["netting_enabled"]
    original_solar_bonus = settings["solar_bonus_enabled"]

    # Now simulate loading Greenchoice gas preset
    preset = PRESET_GREENCHOICE_GAS_2026

    has_gas = any(preset.get(field, 0) != 0 for field in GAS_CORE_FIELDS)
    has_electricity = any(preset.get(field, 0) != 0 for field in ELECTRICITY_CORE_FIELDS)

    # Apply Greenchoice preset (gas-only)
    for key, value in preset.items():
        if has_gas and not has_electricity:
            if key in GAS_FIELDS or key in GENERAL_FIELDS:
                settings[key] = value
        elif has_electricity and not has_gas:
            if key in ELECTRICITY_FIELDS or key in GENERAL_FIELDS:
                settings[key] = value
        else:
            settings[key] = value

    # Electricity values should be preserved (not overwritten with zeros)
    assert settings["per_unit_supplier_electricity_markup"] == original_electricity_markup
    assert settings["per_unit_government_electricity_tax"] == original_electricity_tax
    assert settings["netting_enabled"] == original_netting
    assert settings["solar_bonus_enabled"] == original_solar_bonus

    # Gas values should be from Greenchoice
    assert settings["per_unit_supplier_gas_markup"] == PRESET_GREENCHOICE_GAS_2026["per_unit_supplier_gas_markup"]
    assert settings["per_unit_government_gas_tax"] == PRESET_GREENCHOICE_GAS_2026["per_unit_government_gas_tax"]
