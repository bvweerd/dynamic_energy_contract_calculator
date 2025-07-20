from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from custom_components.dynamic_energy_calculator.sensor import async_setup_entry
from custom_components.dynamic_energy_calculator.const import (
    DOMAIN,
    CONF_CONFIGS,
    CONF_SOURCE_TYPE,
    CONF_SOURCES,
    CONF_PRICE_SENSOR,
    CONF_PRICE_SETTINGS,
    SOURCE_TYPE_CONSUMPTION,
)


async def test_async_setup_entry(hass: HomeAssistant):
    from custom_components.dynamic_energy_calculator import async_setup

    await async_setup(hass, {})
    assert hass.services.has_service(DOMAIN, "reset_all_meters")
    hass.states.async_set("sensor.energy", 0)
    hass.states.async_set("sensor.price", 0)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_CONFIGS: [
                {
                    CONF_SOURCE_TYPE: SOURCE_TYPE_CONSUMPTION,
                    CONF_SOURCES: ["sensor.energy"],
                }
            ],
            CONF_PRICE_SENSOR: "sensor.price",
        },
        options={CONF_PRICE_SETTINGS: {}},
    )
    entry.add_to_hass(hass)
    added = []

    async def add_entities(entities, update=False):
        added.extend(entities)

    await async_setup_entry(hass, entry, add_entities)
    await hass.async_block_till_done()
    assert isinstance(added, list)
    assert hass.services.has_service(DOMAIN, "reset_all_meters")
