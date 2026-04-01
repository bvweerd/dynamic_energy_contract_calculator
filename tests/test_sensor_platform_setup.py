from unittest.mock import MagicMock

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dynamic_energy_contract_calculator.sensor import (
    async_setup_entry,
)
from custom_components.dynamic_energy_contract_calculator.const import (
    DOMAIN,
    CONF_PRICE_SENSOR,
    CONF_PRICE_SETTINGS,
    CONF_SOURCE_TYPE,
    CONF_SOURCES,
    SOURCE_TYPE_CONSUMPTION,
    SUBENTRY_TYPE_SOURCE,
)


def _make_subentry(source_type: str, sources: list[str]) -> MagicMock:
    """Return a mock sub-entry for the given source type and sensor list."""
    subentry = MagicMock()
    subentry.subentry_type = SUBENTRY_TYPE_SOURCE
    subentry.data = {CONF_SOURCE_TYPE: source_type, CONF_SOURCES: sources}
    return subentry


async def test_async_setup_entry(hass: HomeAssistant):
    from custom_components.dynamic_energy_contract_calculator import async_setup

    await async_setup(hass, {})
    assert hass.services.has_service(DOMAIN, "reset_all_meters")
    hass.states.async_set("sensor.energy", 0)
    hass.states.async_set("sensor.price", 0)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_PRICE_SENSOR: ["sensor.price"]},
        options={CONF_PRICE_SETTINGS: {}},
    )
    entry.add_to_hass(hass)
    entry._subentries = {
        "sub-1": _make_subentry(SOURCE_TYPE_CONSUMPTION, ["sensor.energy"])
    }
    added = []

    async def add_entities(entities, update=False):
        added.extend(entities)

    await async_setup_entry(hass, entry, add_entities)
    await hass.async_block_till_done()
    assert isinstance(added, list)
    assert hass.services.has_service(DOMAIN, "reset_all_meters")


async def test_setup_entry_without_price_sensor(hass: HomeAssistant):
    from custom_components.dynamic_energy_contract_calculator import async_setup

    await async_setup(hass, {})
    hass.states.async_set("sensor.energy", 0)

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={},
        options={CONF_PRICE_SETTINGS: {}},
    )
    entry.add_to_hass(hass)
    entry._subentries = {
        "sub-1": _make_subentry(SOURCE_TYPE_CONSUMPTION, ["sensor.energy"])
    }

    added: list[str] = []

    async def add_entities(entities, update=False):
        added.extend([e.unique_id for e in entities])

    await async_setup_entry(hass, entry, add_entities)
    await hass.async_block_till_done()

    energy_ids = {uid for uid in added if uid.startswith(f"{DOMAIN}_sensor_energy_")}
    assert f"{DOMAIN}_sensor_energy_cost_total" not in energy_ids
    assert f"{DOMAIN}_sensor_energy_profit_total" not in energy_ids
    assert f"{DOMAIN}_sensor_energy_kwh_during_cost_total" not in energy_ids
    assert f"{DOMAIN}_sensor_energy_kwh_during_profit_total" not in energy_ids
