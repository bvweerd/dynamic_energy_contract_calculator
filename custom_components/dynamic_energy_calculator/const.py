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
SOURCE_TYPE_CONSUMPTION = "Electricity consumption"
SOURCE_TYPE_PRODUCTION = "Electricity production"

# allowed values for source_type
SOURCE_TYPES = [
    "Electricity consumption",
    "Electricity production",
]

CONF_CONFIGS = "configurations"
