"""Test supplier preset configurations."""

import pytest

from custom_components.dynamic_energy_contract_calculator.config_flow import (
    _apply_preset,
)
from custom_components.dynamic_energy_contract_calculator.const import (
    DEFAULT_PRICE_SETTINGS,
    PRESET_GREENCHOICE_GAS_2026,
    PRESET_NEXTENERGY_2026,
    PRESET_ZONNEPLAN_2026,
    SOLAR_BONUS_BASE_MARKET_ONLY,
    SOLAR_BONUS_LIMIT_CONTRACT_YEAR,
    SOLAR_BONUS_WINDOW_FIXED_HOURS,
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
    # Updated to 2026 tariffs
    assert abs(preset["per_unit_supplier_electricity_markup"] - 0.01653) < 0.00001
    assert abs(preset["per_unit_government_electricity_tax"] - 0.09157) < 0.00001
    assert (
        abs(preset["per_day_supplier_electricity_standing_charge"] - 0.14343) < 0.00001
    )
    assert (
        abs(preset["per_day_grid_operator_electricity_connection_fee"] - 0.92098)
        < 0.00001
    )
    assert abs(preset["per_day_government_electricity_tax_rebate"] - 1.17707) < 0.00001

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

    # Energiebelasting 2026: €0.1108 inclusive (0.09157 * 1.21)
    assert (
        abs((preset["per_unit_government_electricity_tax"] * vat_factor) - 0.1108)
        < 0.0001
    )

    # Test daily costs: (exclusive * 1.21) should match original daily inclusive
    # Vaste leveringskosten 2026: €5.28/month = ~€0.17/day inclusive
    daily_standing_charge_incl = (
        preset["per_day_supplier_electricity_standing_charge"] * vat_factor
    )
    assert abs(daily_standing_charge_incl - (5.28 / 30.416667)) < 0.005

    # Netbeheerkosten 2026: €33.90/month = ~€1.11/day inclusive
    daily_connection_fee_incl = (
        preset["per_day_grid_operator_electricity_connection_fee"] * vat_factor
    )
    assert abs(daily_connection_fee_incl - (33.90 / 30.416667)) < 0.005

    # Vermindering energiebelasting 2026: €43.33/month = ~€1.42/day inclusive
    daily_rebate_incl = preset["per_day_government_electricity_tax_rebate"] * vat_factor
    assert abs(daily_rebate_incl - (43.33 / 30.416667)) < 0.005


def test_zonneplan_daily_costs_calculation():
    """Test that daily costs match Zonneplan 2026 monthly rates (with VAT)."""
    preset = PRESET_ZONNEPLAN_2026
    vat_factor = 1.21

    # Calculate monthly costs from daily rates (including VAT)
    # Using 30.416667 days per month (365/12)
    days_per_month = 30.416667

    # Vaste leveringskosten 2026: €5.28 per maand (inclusive VAT)
    monthly_standing_charge = (
        preset["per_day_supplier_electricity_standing_charge"]
        * days_per_month
        * vat_factor
    )
    assert abs(monthly_standing_charge - 5.28) < 0.15

    # Netbeheerkosten 2026: €33.90 per maand (inclusive VAT)
    monthly_connection_fee = (
        preset["per_day_grid_operator_electricity_connection_fee"]
        * days_per_month
        * vat_factor
    )
    assert abs(monthly_connection_fee - 33.90) < 0.10

    # Vermindering energiebelasting 2026: €43.33 per maand (inclusive VAT)
    monthly_rebate = (
        preset["per_day_government_electricity_tax_rebate"]
        * days_per_month
        * vat_factor
    )
    assert abs(monthly_rebate - 43.33) < 0.01


def test_nextenergy_preset_exists():
    """Test that the NextEnergy preset is available."""
    assert "nextenergy_2026" in SUPPLIER_PRESETS
    assert SUPPLIER_PRESETS["nextenergy_2026"] == PRESET_NEXTENERGY_2026


def test_nextenergy_preset_zonnebonus_terms():
    """The preset carries NextEnergy's published Zonnebonus conditions."""
    preset = PRESET_NEXTENERGY_2026

    assert preset["solar_bonus_enabled"] is True
    # 50% over the bare exchange price
    assert preset["solar_bonus_percentage"] == 50.0
    assert preset["solar_bonus_base"] == SOLAR_BONUS_BASE_MARKET_ONLY
    # Fixed 06:00-22:00 window rather than sunrise to sunset
    assert preset["solar_bonus_window_mode"] == SOLAR_BONUS_WINDOW_FIXED_HOURS
    assert preset["solar_bonus_start_hour"] == 6.0
    assert preset["solar_bonus_end_hour"] == 22.0
    # 6000 kWh per contract year, not per calendar year
    assert preset["solar_bonus_annual_kwh_limit"] == 6000.0
    assert preset["solar_bonus_limit_period"] == SOLAR_BONUS_LIMIT_CONTRACT_YEAR
    # NextEnergy settles on quarter-hour prices
    assert preset["average_prices_to_hourly"] is False


def test_nextenergy_preset_carries_no_supply_tariffs():
    """NextEnergy does not publish supply tariffs, so the preset omits them.

    Absent keys are never written, so loading this preset must not reset
    tariffs the user entered from their own contract.
    """
    unpublished = {
        "per_unit_supplier_electricity_markup",
        "per_unit_government_electricity_tax",
        "per_day_grid_operator_electricity_connection_fee",
        "per_day_supplier_electricity_standing_charge",
        "per_day_government_electricity_tax_rebate",
    }
    assert unpublished.isdisjoint(PRESET_NEXTENERGY_2026)


def test_nextenergy_preset_preserves_existing_settings():
    """Loading the NextEnergy preset leaves gas and electricity tariffs alone."""
    current = dict(DEFAULT_PRICE_SETTINGS)
    current.update(
        {
            "per_unit_supplier_electricity_markup": 0.0181,
            "per_day_supplier_electricity_standing_charge": 0.1735,
            "per_unit_supplier_gas_markup": 0.4105,
            "per_day_supplier_gas_standing_charge": 0.4386,
        }
    )

    result = _apply_preset(current, PRESET_NEXTENERGY_2026)

    # Tariffs the user configured survive untouched
    assert result["per_unit_supplier_electricity_markup"] == 0.0181
    assert result["per_day_supplier_electricity_standing_charge"] == 0.1735
    assert result["per_unit_supplier_gas_markup"] == 0.4105
    assert result["per_day_supplier_gas_standing_charge"] == 0.4386

    # The bonus terms are applied
    assert result["solar_bonus_percentage"] == 50.0
    assert result["solar_bonus_base"] == SOLAR_BONUS_BASE_MARKET_ONLY
    assert result["solar_bonus_annual_kwh_limit"] == 6000.0


def test_nextenergy_and_greenchoice_presets_compose():
    """Electricity from NextEnergy and gas from Greenchoice must coexist."""
    combined = _apply_preset(dict(DEFAULT_PRICE_SETTINGS), PRESET_NEXTENERGY_2026)
    combined = _apply_preset(combined, PRESET_GREENCHOICE_GAS_2026)

    # Gas preset must not clear the NextEnergy Zonnebonus terms
    assert combined["solar_bonus_enabled"] is True
    assert combined["solar_bonus_percentage"] == 50.0
    assert combined["solar_bonus_annual_kwh_limit"] == 6000.0
    assert combined["solar_bonus_base"] == SOLAR_BONUS_BASE_MARKET_ONLY

    # And the gas tariffs are loaded
    assert combined["per_unit_supplier_gas_markup"] == pytest.approx(0.41050)
