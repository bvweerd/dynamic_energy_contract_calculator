"""
Constants for the Dynamic Energy Calculator integration.
"""

# Domain of the integration
DOMAIN = "dynamic_energy_calculator"
DOMAIN_ABBREVIATION = "DEC"

PLATFORMS = ["sensor", "number"]

# Configuration keys
CONF_SOURCE_TYPE = "source_type"
CONF_SOURCES = "sources"
CONF_PRICE_SENSOR = "price_sensor"

# Possible source types
SOURCE_TYPE_CONSUMPTION = "consumption"
SOURCE_TYPE_PRODUCTION = "production"

# allowed values for source_type
SOURCE_TYPES = [
    "consumption",
    "production",
]

CONF_CONFIGS = "configurations"
