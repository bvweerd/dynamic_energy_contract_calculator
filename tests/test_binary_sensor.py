"""Tests for binary sensor platform."""

import pytest
from unittest.mock import patch
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo

from custom_components.dynamic_energy_contract_calculator.binary_sensor import (
    async_setup_entry,
    DeliveryPricePositiveBinarySensor,
    SolarBonusActiveBinarySensor,
    ProductionPricePositiveBinarySensor,
)
from custom_components.dynamic_energy_contract_calculator.solar_bonus import (
    SolarBonusTracker,
)
from custom_components.dynamic_energy_contract_calculator.const import (
    CONF_PRICE_SENSOR,
    CONF_PRICE_SETTINGS,
    DOMAIN,
    DOMAIN_ABBREVIATION,
    SOURCE_TYPE_CONSUMPTION,
    SOURCE_TYPE_PRODUCTION,
    SUBENTRY_TYPE_SOURCE,
)
from pytest_homeassistant_custom_component.common import MockConfigEntry


@pytest.fixture
def device_info():
    """Create device info for tests."""
    return DeviceInfo(
        identifiers={(DOMAIN, "daily_electricity_cost")},
        name=f"{DOMAIN_ABBREVIATION}: Summary Sensors",
        entry_type=DeviceEntryType.SERVICE,
        manufacturer="DynamicEnergyCalc",
        model="summary",
    )


async def test_production_price_positive_sensor(hass: HomeAssistant, device_info):
    """Test the production price positive binary sensor."""
    # Set up price sensor
    hass.states.async_set("sensor.production_price", "0.10")

    price_settings = {
        "per_unit_supplier_electricity_production_markup": 0.02,
    }

    sensor = ProductionPricePositiveBinarySensor(
        hass=hass,
        unique_id="test_production_positive",
        entry_id="test_entry",
        price_sensor="sensor.production_price",
        price_settings=price_settings,
        device_info=device_info,
    )

    # Add sensor to hass
    await sensor.async_added_to_hass()

    # Should be ON (positive: 0.10 + 0.02 = 0.12)
    assert sensor.is_on is True

    # Change price to negative
    hass.states.async_set("sensor.production_price", "-0.05")
    await hass.async_block_till_done()

    # Should be OFF (negative: -0.05 + 0.02 = -0.03)
    assert sensor.is_on is False

    # Change to small negative that becomes positive with markup
    hass.states.async_set("sensor.production_price", "-0.01")
    await hass.async_block_till_done()

    # Should be ON (positive: -0.01 + 0.02 = 0.01)
    assert sensor.is_on is True


async def test_production_price_positive_no_price_sensor(
    hass: HomeAssistant, device_info
):
    """Test production price positive sensor without price sensor."""
    price_settings = {
        "per_unit_supplier_electricity_production_markup": 0.02,
    }

    sensor = ProductionPricePositiveBinarySensor(
        hass=hass,
        unique_id="test_production_no_sensor",
        entry_id="test_entry",
        price_sensor=None,
        price_settings=price_settings,
        device_info=device_info,
    )

    await sensor.async_added_to_hass()

    # Should be OFF when no price sensor
    assert sensor.is_on is False


async def test_production_price_positive_invalid_price_state(
    hass: HomeAssistant, device_info
):
    hass.states.async_set("sensor.production_price", "not-a-number")
    sensor = ProductionPricePositiveBinarySensor(
        hass=hass,
        unique_id="invalid-price",
        entry_id="test_entry",
        price_sensor="sensor.production_price",
        price_settings={"per_unit_supplier_electricity_production_markup": 0.5},
        device_info=device_info,
    )

    await sensor.async_added_to_hass()

    assert sensor.is_on is False


async def test_production_price_positive_entity_write_and_handler(
    hass: HomeAssistant, device_info
):
    hass.states.async_set("sensor.production_price", "bad")
    sensor = ProductionPricePositiveBinarySensor(
        hass=hass,
        unique_id="production-write",
        entry_id="test_entry",
        price_sensor="sensor.production_price",
        price_settings={"per_unit_supplier_electricity_production_markup": 0.0},
        device_info=device_info,
    )
    sensor.entity_id = "binary_sensor.production_write"
    writes = []
    sensor.async_write_ha_state = lambda: writes.append("write")

    await sensor._async_update_state()
    await sensor._handle_price_change(type("Event", (), {"data": {}})())

    assert writes == ["write", "write"]


async def test_solar_bonus_active_sensor(hass: HomeAssistant, device_info):
    """Test the solar bonus active binary sensor."""
    # Create a solar bonus tracker
    tracker = await SolarBonusTracker.async_create(hass, "test_entry")

    # Set up price sensor
    hass.states.async_set("sensor.production_price", "0.10")

    price_settings = {
        "per_unit_supplier_electricity_production_markup": 0.02,
        "solar_bonus_annual_kwh_limit": 7500.0,
    }

    sensor = SolarBonusActiveBinarySensor(
        hass=hass,
        unique_id="test_solar_bonus_active",
        entry_id="test_entry",
        solar_bonus_tracker=tracker,
        price_sensor="sensor.production_price",
        price_settings=price_settings,
        device_info=device_info,
    )

    # Mock daylight to True
    with patch.object(tracker, "is_daylight", return_value=True):
        await sensor.async_added_to_hass()

        # Should be ON (daylight, positive price, under limit)
        assert sensor.is_on is True

    # Mock daylight to False (night)
    with patch.object(tracker, "is_daylight", return_value=False):
        await sensor._async_update_state()

        # Should be OFF (night time)
        assert sensor.is_on is False


async def test_solar_bonus_active_negative_price(hass: HomeAssistant, device_info):
    """Test solar bonus active sensor with negative price."""
    tracker = await SolarBonusTracker.async_create(hass, "test_entry_neg")

    # Set up negative price sensor
    hass.states.async_set("sensor.production_price", "-0.10")

    price_settings = {
        "per_unit_supplier_electricity_production_markup": 0.02,
        "solar_bonus_annual_kwh_limit": 7500.0,
    }

    sensor = SolarBonusActiveBinarySensor(
        hass=hass,
        unique_id="test_solar_bonus_neg",
        entry_id="test_entry_neg",
        solar_bonus_tracker=tracker,
        price_sensor="sensor.production_price",
        price_settings=price_settings,
        device_info=device_info,
    )

    # Mock daylight to True
    with patch.object(tracker, "is_daylight", return_value=True):
        await sensor.async_added_to_hass()

        # Should be OFF (price -0.10 + 0.02 = -0.08, negative)
        assert sensor.is_on is False


async def test_solar_bonus_active_at_limit(hass: HomeAssistant, device_info):
    """Test solar bonus active sensor when at annual limit."""
    tracker = await SolarBonusTracker.async_create(hass, "test_entry_limit")

    # Manually set production to limit
    tracker._year_production_kwh = 7500.0

    hass.states.async_set("sensor.production_price", "0.10")

    price_settings = {
        "per_unit_supplier_electricity_production_markup": 0.02,
        "solar_bonus_annual_kwh_limit": 7500.0,
    }

    sensor = SolarBonusActiveBinarySensor(
        hass=hass,
        unique_id="test_solar_bonus_limit",
        entry_id="test_entry_limit",
        solar_bonus_tracker=tracker,
        price_sensor="sensor.production_price",
        price_settings=price_settings,
        device_info=device_info,
    )

    # Mock daylight to True
    with patch.object(tracker, "is_daylight", return_value=True):
        await sensor.async_added_to_hass()

        # Should be OFF (at limit)
        assert sensor.is_on is False


async def test_solar_bonus_active_no_price_sensor(hass: HomeAssistant, device_info):
    """Test solar bonus active sensor without price sensor."""
    tracker = await SolarBonusTracker.async_create(hass, "test_entry_no_sensor")

    price_settings = {
        "per_unit_supplier_electricity_production_markup": 0.02,
        "solar_bonus_annual_kwh_limit": 7500.0,
    }

    sensor = SolarBonusActiveBinarySensor(
        hass=hass,
        unique_id="test_solar_bonus_no_sensor",
        entry_id="test_entry_no_sensor",
        solar_bonus_tracker=tracker,
        price_sensor=None,
        price_settings=price_settings,
        device_info=device_info,
    )

    with patch.object(tracker, "is_daylight", return_value=True):
        await sensor.async_added_to_hass()

        # Should be OFF when no price sensor
        assert sensor.is_on is False


async def test_solar_bonus_active_handles_unavailable_and_entity_write(
    hass: HomeAssistant, device_info
):
    tracker = await SolarBonusTracker.async_create(hass, "test_entry_write")
    hass.states.async_set("sensor.production_price", "unavailable")
    sensor = SolarBonusActiveBinarySensor(
        hass=hass,
        unique_id="test_solar_bonus_write",
        entry_id="test_entry_write",
        solar_bonus_tracker=tracker,
        price_sensor="sensor.production_price",
        price_settings={"solar_bonus_annual_kwh_limit": 7500.0},
        device_info=device_info,
    )
    sensor.entity_id = "binary_sensor.test_solar_bonus_write"

    calls = []
    sensor.async_write_ha_state = lambda: calls.append("write")

    with patch.object(tracker, "is_daylight", return_value=True):
        await sensor._async_update_state()

    assert sensor.is_on is False
    assert calls == ["write"]


async def test_solar_bonus_active_handler_and_invalid_price_state(
    hass: HomeAssistant, device_info
):
    tracker = await SolarBonusTracker.async_create(hass, "test_entry_invalid")
    hass.states.async_set("sensor.production_price", "bad")
    sensor = SolarBonusActiveBinarySensor(
        hass=hass,
        unique_id="test_solar_bonus_invalid",
        entry_id="test_entry_invalid",
        solar_bonus_tracker=tracker,
        price_sensor="sensor.production_price",
        price_settings={"solar_bonus_annual_kwh_limit": 7500.0},
        device_info=device_info,
    )
    sensor.entity_id = "binary_sensor.test_solar_bonus_invalid"
    writes = []
    sensor.async_write_ha_state = lambda: writes.append("write")

    with patch.object(tracker, "is_daylight", return_value=True):
        await sensor._handle_price_change(type("Event", (), {"data": {}})())

    assert sensor.is_on is False
    assert writes == ["write"]


async def test_binary_sensor_setup_entry_creates_expected_entities(hass: HomeAssistant):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_PRICE_SENSOR: ["sensor.production_price"],
            CONF_PRICE_SETTINGS: {
                "solar_bonus_enabled": True,
                "contract_start_date": "2025-01-01",
            },
        },
        entry_id="binary-setup",
        subentries_data=[
            {
                "subentry_type": SUBENTRY_TYPE_SOURCE,
                "data": {
                    "source_type": SOURCE_TYPE_PRODUCTION,
                    "sources": ["sensor.solar"],
                },
                "title": SOURCE_TYPE_PRODUCTION,
                "unique_id": None,
            },
            {
                "subentry_type": SUBENTRY_TYPE_SOURCE,
                "data": {
                    "source_type": SOURCE_TYPE_CONSUMPTION,
                    "sources": ["sensor.energy"],
                },
                "title": SOURCE_TYPE_CONSUMPTION,
                "unique_id": None,
            },
        ],
    )
    entry.add_to_hass(hass)
    hass.data.setdefault(DOMAIN, {})

    added_entities = []

    def add_entities(entities):
        added_entities.extend(entities)

    await async_setup_entry(hass, entry, add_entities)

    assert len(added_entities) == 3
    assert {entity.translation_key for entity in added_entities} == {
        "solar_bonus_active",
        "production_price_positive",
        "delivery_price_positive",
    }
    assert "binary-setup" in hass.data[DOMAIN]["solar_bonus"]


async def test_binary_sensor_setup_entry_reuses_existing_tracker(hass: HomeAssistant):
    existing_tracker = object()
    hass.data.setdefault(DOMAIN, {})["solar_bonus"] = {
        "binary-existing": existing_tracker
    }
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_PRICE_SENSOR: ["sensor.production_price"],
            CONF_PRICE_SETTINGS: {"solar_bonus_enabled": True},
        },
        entry_id="binary-existing",
        subentries_data=[
            {
                "subentry_type": SUBENTRY_TYPE_SOURCE,
                "data": {
                    "source_type": SOURCE_TYPE_PRODUCTION,
                    "sources": ["sensor.solar"],
                },
                "title": SOURCE_TYPE_PRODUCTION,
                "unique_id": None,
            }
        ],
    )
    entry.add_to_hass(hass)

    added_entities = []

    def add_entities(entities):
        added_entities.extend(entities)

    with patch(
        "custom_components.dynamic_energy_contract_calculator.binary_sensor.SolarBonusTracker.async_create"
    ) as create_tracker:
        await async_setup_entry(hass, entry, add_entities)

    create_tracker.assert_not_called()
    assert added_entities[0]._solar_bonus_tracker is existing_tracker


async def test_delivery_price_positive_sensor(hass: HomeAssistant, device_info):
    """Test the delivery price positive binary sensor."""
    hass.states.async_set("sensor.electricity_price", "0.10")

    price_settings = {
        "per_unit_supplier_electricity_markup": 0.02,
        "per_unit_government_electricity_tax": 0.11,
    }

    sensor = DeliveryPricePositiveBinarySensor(
        hass=hass,
        unique_id="test_delivery_positive",
        entry_id="test_entry",
        price_sensor="sensor.electricity_price",
        price_settings=price_settings,
        device_info=device_info,
    )

    await sensor.async_added_to_hass()

    # Should be ON (positive: 0.10 + 0.02 + 0.11 = 0.23)
    assert sensor.is_on is True

    # Change price to negative but still positive with markup+tax
    hass.states.async_set("sensor.electricity_price", "-0.10")
    await hass.async_block_till_done()

    # Should be ON (positive: -0.10 + 0.02 + 0.11 = 0.03)
    assert sensor.is_on is True

    # Change price to very negative
    hass.states.async_set("sensor.electricity_price", "-0.20")
    await hass.async_block_till_done()

    # Should be OFF (negative: -0.20 + 0.02 + 0.11 = -0.07)
    assert sensor.is_on is False


async def test_delivery_price_positive_no_price_sensor(
    hass: HomeAssistant, device_info
):
    """Test delivery price positive sensor without price sensor."""
    sensor = DeliveryPricePositiveBinarySensor(
        hass=hass,
        unique_id="test_delivery_no_sensor",
        entry_id="test_entry",
        price_sensor=None,
        price_settings={},
        device_info=device_info,
    )

    await sensor.async_added_to_hass()

    assert sensor.is_on is False


async def test_delivery_price_positive_invalid_state(hass: HomeAssistant, device_info):
    hass.states.async_set("sensor.electricity_price", "not-a-number")
    sensor = DeliveryPricePositiveBinarySensor(
        hass=hass,
        unique_id="test_delivery_invalid",
        entry_id="test_entry",
        price_sensor="sensor.electricity_price",
        price_settings={"per_unit_supplier_electricity_markup": 0.02},
        device_info=device_info,
    )

    await sensor.async_added_to_hass()

    assert sensor.is_on is False


async def test_delivery_price_positive_entity_write_and_handler(
    hass: HomeAssistant, device_info
):
    hass.states.async_set("sensor.electricity_price", "bad")
    sensor = DeliveryPricePositiveBinarySensor(
        hass=hass,
        unique_id="delivery-write",
        entry_id="test_entry",
        price_sensor="sensor.electricity_price",
        price_settings={},
        device_info=device_info,
    )
    sensor.entity_id = "binary_sensor.delivery_write"
    writes = []
    sensor.async_write_ha_state = lambda: writes.append("write")

    await sensor._async_update_state()
    await sensor._handle_price_change(type("Event", (), {"data": {}})())

    assert writes == ["write", "write"]


async def test_binary_sensor_setup_entry_without_matching_configuration(
    hass: HomeAssistant,
):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_PRICE_SETTINGS: {"solar_bonus_enabled": True}},
        entry_id="binary-empty",
        subentries_data=[
            {
                "subentry_type": SUBENTRY_TYPE_SOURCE,
                "data": {
                    "source_type": SOURCE_TYPE_CONSUMPTION,
                    "sources": ["sensor.energy"],
                },
                "title": SOURCE_TYPE_CONSUMPTION,
                "unique_id": None,
            }
        ],
    )
    entry.add_to_hass(hass)
    hass.data.setdefault(DOMAIN, {})
    added_entities = []

    await async_setup_entry(
        hass, entry, lambda entities: added_entities.extend(entities)
    )

    assert added_entities == []
