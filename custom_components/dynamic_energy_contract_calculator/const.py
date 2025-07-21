"""Constants for the Dynamic Energy Contract Calculator integration."""

from typing import Any

# Domain of the integration
DOMAIN = "dynamic_energy_contract_calculator"
DOMAIN_ABBREVIATION = "DECC"

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
    "per_kwh",
    "per_day",
    "vat_percentage",
    "production_price_include_vat",
]

DEFAULT_PRICE_SETTINGS = {
    "per_kwh": {
        "government": {
            "electricity_tax": 0.1088,
            "gas_tax": 0.0,
        },
        "grid_operator": {
            "electricity_network_fee": 0.0,
            "gas_network_fee": 0.0,
        },
        "supplier": {
            "electricity_markup": 0.02,
            "electricity_production_markup": 0.0,
            "gas_markup": 0.0,
        },
    },
    "per_day": {
        "government": {
            "electricity_tax_rebate": 0.25,
        },
        "grid_operator": {
            "electricity_connection_fee": 0.25,
            "gas_connection_fee": 0.0,
        },
        "supplier": {
            "electricity_standing_charge": 0.25,
            "gas_standing_charge": 0.0,
        },
    },
    "vat_percentage": 21.0,
    "production_price_include_vat": True,
}

# Mapping of flattened config keys to nested price_setting paths
FLAT_PRICE_SETTING_PATHS = {
    "per_kwh_government_electricity_tax": [
        "per_kwh",
        "government",
        "electricity_tax",
    ],
    "per_kwh_government_gas_tax": ["per_kwh", "government", "gas_tax"],
    "per_kwh_grid_operator_electricity_network_fee": [
        "per_kwh",
        "grid_operator",
        "electricity_network_fee",
    ],
    "per_kwh_grid_operator_gas_network_fee": [
        "per_kwh",
        "grid_operator",
        "gas_network_fee",
    ],
    "per_kwh_supplier_electricity_markup": [
        "per_kwh",
        "supplier",
        "electricity_markup",
    ],
    "per_kwh_supplier_electricity_production_markup": [
        "per_kwh",
        "supplier",
        "electricity_production_markup",
    ],
    "per_kwh_supplier_gas_markup": ["per_kwh", "supplier", "gas_markup"],
    "per_day_government_electricity_tax_rebate": [
        "per_day",
        "government",
        "electricity_tax_rebate",
    ],
    "per_day_grid_operator_electricity_connection_fee": [
        "per_day",
        "grid_operator",
        "electricity_connection_fee",
    ],
    "per_day_grid_operator_gas_connection_fee": [
        "per_day",
        "grid_operator",
        "gas_connection_fee",
    ],
    "per_day_supplier_electricity_standing_charge": [
        "per_day",
        "supplier",
        "electricity_standing_charge",
    ],
    "per_day_supplier_gas_standing_charge": [
        "per_day",
        "supplier",
        "gas_standing_charge",
    ],
    "vat_percentage": ["vat_percentage"],
    "production_price_include_vat": ["production_price_include_vat"],
}


def expand_flat_price_settings(data: dict) -> dict:
    """Convert a flat dict with config keys to the nested structure."""
    settings = DEFAULT_PRICE_SETTINGS.copy()
    # Deep copy of nested dicts
    settings["per_kwh"] = {
        k: v.copy() for k, v in DEFAULT_PRICE_SETTINGS["per_kwh"].items()
    }
    settings["per_day"] = {
        k: v.copy() for k, v in DEFAULT_PRICE_SETTINGS["per_day"].items()
    }

    for flat_key, path in FLAT_PRICE_SETTING_PATHS.items():
        if flat_key in data:
            current = settings
            for part in path[:-1]:
                current = current.setdefault(part, {})
            current[path[-1]] = data[flat_key]
    return settings


def flatten_price_settings(settings: dict) -> dict:
    """Flatten nested price settings for forms."""
    result = {}
    for flat_key, path in FLAT_PRICE_SETTING_PATHS.items():
        default = get_price_setting(DEFAULT_PRICE_SETTINGS, path, 0)
        result[flat_key] = get_price_setting(settings, path, default)
    return result


def get_price_setting(settings: dict, path: list[str], default: float | bool = 0.0):
    """Return a nested value from the price settings dict."""
    val: Any = settings
    for key in path:
        if not isinstance(val, dict):
            return default
        if key not in val:
            return default
        val = val[key]
    return val
