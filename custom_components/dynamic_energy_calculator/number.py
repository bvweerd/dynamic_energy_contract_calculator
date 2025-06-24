from homeassistant.components.number import NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.entity import EntityCategory

from .const import DOMAIN

NUMBER_SETTINGS = [
    {
        "key": "electricity_consumption_markup_per_kwh",
        "name": "Electricity Consumption Markup Per kWh",
        "min": 0.0,
        "max": 1.0,
        "step": 0.00001,
        "unit": "€",
        "mode": "box",
        "default": 0.0,
    },
    {
        "key": "electricity_production_markup_per_kwh",
        "name": "Electricity Production Markup Per kWh",
        "min": 0.0,
        "max": 1.0,
        "step": 0.00001,
        "unit": "€",
        "mode": "box",
        "default": 0.0,
    },
    {
        "key": "electricity_surcharge_per_kwh",
        "name": "Electricity Surcharge Per kWh",
        "min": 0.0,
        "max": 1.0,
        "step": 0.00001,
        "unit": "€",
        "mode": "box",
        "default": 0.0,
    },
    {
        "key": "vat_percentage",
        "name": "VAT Percentage",
        "min": 0.0,
        "max": 30.0,
        "step": 0.1,
        "unit": "%",
        "mode": "box",
        "default": 21.0,
    },
    {
        "key": "electricity_surcharge_per_day",
        "name": "Electricity Surcharge Per Day",
        "min": 0.0,
        "max": 10.0,
        "step": 0.00001,
        "unit": "€",
        "mode": "box",
        "default": 0.0,
    },
    {
        "key": "electricity_standing_charge_per_day",
        "name": "Electricity Standing Charge Per Day",
        "min": 0.0,
        "max": 10.0,
        "step": 0.00001,
        "unit": "€",
        "mode": "box",
        "default": 0.0,
    },
    {
        "key": "electricity_tax_rebate_per_day",
        "name": "Electricity Tax Rebate Per Day",
        "min": 0.0,
        "max": 10.0,
        "step": 0.00001,
        "unit": "€",
        "mode": "box",
        "default": 0.0,
    },
]

from homeassistant.helpers.entity import DeviceInfo

class DynamicNumber(NumberEntity, RestoreEntity):
    def __init__(self, setting: dict):
        device_info = DeviceInfo(
            identifiers={(DOMAIN, "config")},
            name="Dynamic Energy Configuration",
            entry_type="service",
            manufacturer="DynamicEnergyCalc",
            model="configuration",
        )
        self._attr_name = setting["name"]
        self._attr_unique_id = f"{DOMAIN}_{setting['key']}"
        self._attr_native_unit_of_measurement = setting["unit"]
        self._attr_mode = setting["mode"]
        self._attr_min_value = setting["min"]
        self._attr_max_value = setting["max"]
        self._attr_step = setting["step"]
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_native_value = setting["default"]
        self._attr_device_info = device_info
        self._key = setting["key"]

    async def async_added_to_hass(self):
        last_state = await self.async_get_last_state()
        if last_state and last_state.state not in ("unknown", "unavailable"):
            try:
                self._attr_native_value = float(last_state.state)
            except ValueError:
                pass

    @property
    def native_value(self) -> float:
        return round(self._attr_native_value, 5)

    async def async_set_native_value(self, value: float) -> None:
        self._attr_native_value = value
        self.async_write_ha_state()

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback
) -> None:
    entities = [DynamicNumber(setting) for setting in NUMBER_SETTINGS]
    async_add_entities(entities, True)
