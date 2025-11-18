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
    "per_unit_supplier_electricity_production_surcharge",
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
    "overage_compensation_enabled",
    "overage_compensation_rate",
    "surplus_vat_enabled",
    "production_bonus_percentage",
    "production_bonus_start_hour",
    "production_bonus_end_hour",
    "negative_price_production_bonus_percentage",
]

DEFAULT_PRICE_SETTINGS = {
    "per_unit_supplier_electricity_markup": 0.02,
    "per_unit_supplier_electricity_production_markup": 0.0,
    "per_unit_supplier_electricity_production_surcharge": 0.0,
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
    "overage_compensation_enabled": False,
    "overage_compensation_rate": 0.0,
    "surplus_vat_enabled": False,
    "production_bonus_percentage": 0.0,
    "production_bonus_start_hour": 0,
    "production_bonus_end_hour": 24,
    "negative_price_production_bonus_percentage": 0.0,
}

NETTING_STORAGE_VERSION = 1
NETTING_STORAGE_KEY_PREFIX = f"{DOMAIN}_netting"

OVERAGE_COMPENSATION_STORAGE_VERSION = 1
OVERAGE_COMPENSATION_STORAGE_KEY_PREFIX = f"{DOMAIN}_overage_compensation"
