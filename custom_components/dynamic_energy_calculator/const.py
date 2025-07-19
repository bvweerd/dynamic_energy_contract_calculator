"""
Constants for the Dynamic Energy Calculator integration.
"""

# Domain of the integration
DOMAIN = "dynamic_energy_calculator"
DOMAIN_ABBREVIATION = "DEC"

PLATFORMS = ["sensor"]

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
    "electricity_consumption_markup_per_kwh",
    "electricity_production_markup_per_kwh",
    "electricity_surcharge_per_kwh",
    "vat_percentage",
    "electricity_surcharge_per_day",
    "electricity_standing_charge_per_day",
    "electricity_tax_rebate_per_day",
    "gas_markup_per_m3",
    "gas_surcharge_per_m3",
    "gas_standing_charge_per_day",
]

DEFAULT_PRICE_SETTINGS = {
    "electricity_consumption_markup_per_kwh": 0.02,
    "electricity_production_markup_per_kwh": 0.0,
    "electricity_surcharge_per_kwh": 0.1088,
    "vat_percentage": 21.0,
    "electricity_surcharge_per_day": 0.25,
    "electricity_standing_charge_per_day": 0.25,
    "electricity_tax_rebate_per_day": 0.25,
    "gas_markup_per_m3": 0.0,
    "gas_surcharge_per_m3": 0.0,
    "gas_standing_charge_per_day": 0.0,
}
