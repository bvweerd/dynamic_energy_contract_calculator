"""Constants for the Dynamic Energy Contract Calculator integration."""

# Domain of the integration
DOMAIN = "dynamic_energy_contract_calculator"
DOMAIN_ABBREVIATION = "DECC"

PLATFORMS = ["sensor", "binary_sensor"]

# Configuration keys
CONF_SOURCE_TYPE = "source_type"
CONF_SOURCES = "sources"
CONF_PRICE_SENSOR = "price_sensor"
CONF_PRICE_SENSOR_GAS = "price_sensor_gas"
CONF_PRICE_SETTINGS = "price_settings"

# Possible source types
SOURCE_TYPE_CONSUMPTION = "Electricity consumption"
SOURCE_TYPE_PRODUCTION = "Electricity production"
SOURCE_TYPE_GAS = "Gas consumption"

# allowed values for source_type
SOURCE_TYPES = [
    SOURCE_TYPE_CONSUMPTION,
    SOURCE_TYPE_PRODUCTION,
    SOURCE_TYPE_GAS,
]

CONF_CONFIGS = "configurations"

PRICE_SETTINGS_KEYS = [
    "per_unit_supplier_electricity_markup",
    "per_unit_supplier_electricity_production_markup",
    "per_unit_government_electricity_tax",
    "per_unit_supplier_gas_markup",
    "per_unit_government_gas_tax",
    "per_day_grid_operator_electricity_connection_fee",
    "per_day_supplier_electricity_standing_charge",
    "per_day_government_electricity_tax_rebate",
    "per_day_grid_operator_gas_connection_fee",
    "per_day_supplier_gas_standing_charge",
    "vat_percentage",
    "production_price_include_vat",
    "netting_enabled",
    "average_prices_to_hourly",
    "solar_bonus_enabled",
    "solar_bonus_percentage",
    "solar_bonus_annual_kwh_limit",
    "contract_start_date",
    "reset_on_contract_anniversary",
]

DEFAULT_PRICE_SETTINGS = {
    "per_unit_supplier_electricity_markup": 0.02,
    "per_unit_supplier_electricity_production_markup": 0.0,
    "per_unit_government_electricity_tax": 0.1088,
    "per_unit_supplier_gas_markup": 0.0,
    "per_unit_government_gas_tax": 0.0,
    "per_day_grid_operator_electricity_connection_fee": 0.25,
    "per_day_supplier_electricity_standing_charge": 0.25,
    "per_day_government_electricity_tax_rebate": 0.25,
    "per_day_grid_operator_gas_connection_fee": 0.0,
    "per_day_supplier_gas_standing_charge": 0.0,
    "vat_percentage": 21.0,
    "production_price_include_vat": True,
    "netting_enabled": False,
    "average_prices_to_hourly": True,
    "solar_bonus_enabled": False,
    "solar_bonus_percentage": 10.0,
    "solar_bonus_annual_kwh_limit": 7500.0,
    "contract_start_date": "",
    "reset_on_contract_anniversary": False,
}

# Preset configurations for common suppliers
# Zonneplan 2026: All values are EXCLUSIVE of VAT (21%)
# The integration will add VAT on top of these values
# Contract values (inclusive VAT) converted: value_incl_vat / 1.21
PRESET_ZONNEPLAN_2026 = {
    "per_unit_supplier_electricity_markup": 0.01366,  # €0.01653 incl. VAT / 1.21
    "per_unit_supplier_electricity_production_markup": 0.02,  # €0.02 (No VAT on production)
    "per_unit_government_electricity_tax": 0.09157,  # €0.1108 incl. VAT / 1.21
    "per_unit_supplier_gas_markup": 0.0,
    "per_unit_government_gas_tax": 0.0,
    "per_day_grid_operator_electricity_connection_fee": 0.92098,  # €1.11438 incl. VAT / 1.21
    "per_day_supplier_electricity_standing_charge": 0.14343,  # €0.17355 incl. VAT / 1.21
    "per_day_government_electricity_tax_rebate": 1.17707,  # €1.42425 incl. VAT / 1.21
    "per_day_grid_operator_gas_connection_fee": 0.0,
    "per_day_supplier_gas_standing_charge": 0.0,
    "vat_percentage": 21.0,
    "production_price_include_vat": False,  # No VAT on production compensation (teruglevering)
    "netting_enabled": True,
    "average_prices_to_hourly": True,  # Zonneplan uses hourly averages
    "solar_bonus_enabled": True,
    "solar_bonus_percentage": 10.0,
    "solar_bonus_annual_kwh_limit": 7500.0,
    "contract_start_date": "",
    "reset_on_contract_anniversary": True,
}

# Greenchoice 2026: Gas only
# All values are EXCLUSIVE of VAT (21%)
# Contract: Nederlands Groen 1 jaar
PRESET_GREENCHOICE_GAS_2026 = {
    "per_unit_supplier_electricity_markup": 0.0,
    "per_unit_supplier_electricity_production_markup": 0.0,
    "per_unit_government_electricity_tax": 0.0,
    "per_day_grid_operator_electricity_connection_fee": 0.0,
    "per_day_supplier_electricity_standing_charge": 0.0,
    "per_day_government_electricity_tax_rebate": 0.0,
    "per_unit_supplier_gas_markup": 0.41050,  # €0.49671 incl. VAT / 1.21
    "per_unit_government_gas_tax": 0.60066,  # €0.7268 incl. VAT / 1.21
    "per_day_grid_operator_gas_connection_fee": 0.22249,  # €0.26921 incl. VAT / 1.21
    "per_day_supplier_gas_standing_charge": 0.43860,  # €0.53071 incl. VAT / 1.21
    "vat_percentage": 21.0,
    "production_price_include_vat": True,
    "netting_enabled": False,
    "average_prices_to_hourly": True,
    "solar_bonus_enabled": False,
    "solar_bonus_percentage": 10.0,
    "solar_bonus_annual_kwh_limit": 7500.0,
    "contract_start_date": "",
    "reset_on_contract_anniversary": False,
}

SUPPLIER_PRESETS = {
    "zonneplan_2026": PRESET_ZONNEPLAN_2026,    
    "greenchoice_gas_2026": PRESET_GREENCHOICE_GAS_2026,
}

NETTING_STORAGE_VERSION = 1
NETTING_STORAGE_KEY_PREFIX = f"{DOMAIN}_netting"

SOLAR_BONUS_STORAGE_VERSION = 1
SOLAR_BONUS_STORAGE_KEY_PREFIX = f"{DOMAIN}_solar_bonus"
