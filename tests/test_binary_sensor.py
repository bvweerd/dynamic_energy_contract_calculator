"""Tests for binary sensor platform."""

import pytest
from unittest.mock import patch
from datetime import datetime
from homeassistant.core import HomeAssistant
from homeassistant.const import STATE_ON, STATE_OFF

from custom_components.dynamic_energy_contract_calculator.binary_sensor import (
    SolarBonusActiveBinarySensor,
    ProductionPricePositiveBinarySensor,
)
from custom_components.dynamic_energy_contract_calculator.solar_bonus import SolarBonusTracker
from homeassistant.helpers.entity import DeviceInfo


async def test_production_price_positive_sensor(hass: HomeAssistant):
    """Test the production price positive binary sensor."""
    # Set up price sensor
    hass.states.async_set("sensor.production_price", "0.10")

    price_settings = {
        "per_unit_supplier_electricity_production_markup": 0.02,
    }

    device = DeviceInfo(identifiers={("test", "test_device")})

    sensor = ProductionPricePositiveBinarySensor(
        hass=hass,
        unique_id="test_production_positive",
        device=device,
        price_sensor="sensor.production_price",
        price_settings=price_settings,
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


async def test_production_price_positive_no_price_sensor(hass: HomeAssistant):
    """Test production price positive sensor without price sensor."""
    price_settings = {
        "per_unit_supplier_electricity_production_markup": 0.02,
    }

    device = DeviceInfo(identifiers={("test", "test_device")})

    sensor = ProductionPricePositiveBinarySensor(
        hass=hass,
        unique_id="test_production_no_sensor",
        device=device,
        price_sensor=None,
        price_settings=price_settings,
    )

    await sensor.async_added_to_hass()

    # Should be OFF when no price sensor
    assert sensor.is_on is False


async def test_solar_bonus_active_sensor(hass: HomeAssistant):
    """Test the solar bonus active binary sensor."""
    # Create a solar bonus tracker
    tracker = await SolarBonusTracker.async_create(hass, "test_entry")

    # Set up price sensor
    hass.states.async_set("sensor.production_price", "0.10")

    price_settings = {
        "per_unit_supplier_electricity_production_markup": 0.02,
        "solar_bonus_annual_kwh_limit": 7500.0,
    }

    device = DeviceInfo(identifiers={("test", "test_device")})

    sensor = SolarBonusActiveBinarySensor(
        hass=hass,
        unique_id="test_solar_bonus_active",
        device=device,
        solar_bonus_tracker=tracker,
        price_sensor="sensor.production_price",
        price_settings=price_settings,
    )

    # Mock daylight to True
    with patch.object(tracker, '_is_daylight', return_value=True):
        await sensor.async_added_to_hass()

        # Should be ON (daylight, positive price, under limit)
        assert sensor.is_on is True

    # Mock daylight to False (night)
    with patch.object(tracker, '_is_daylight', return_value=False):
        await sensor._async_update_state()

        # Should be OFF (night time)
        assert sensor.is_on is False


async def test_solar_bonus_active_negative_price(hass: HomeAssistant):
    """Test solar bonus active sensor with negative price."""
    tracker = await SolarBonusTracker.async_create(hass, "test_entry_neg")

    # Set up negative price sensor
    hass.states.async_set("sensor.production_price", "-0.10")

    price_settings = {
        "per_unit_supplier_electricity_production_markup": 0.02,
        "solar_bonus_annual_kwh_limit": 7500.0,
    }

    device = DeviceInfo(identifiers={("test", "test_device")})

    sensor = SolarBonusActiveBinarySensor(
        hass=hass,
        unique_id="test_solar_bonus_neg",
        device=device,
        solar_bonus_tracker=tracker,
        price_sensor="sensor.production_price",
        price_settings=price_settings,
    )

    # Mock daylight to True
    with patch.object(tracker, '_is_daylight', return_value=True):
        await sensor.async_added_to_hass()

        # Should be OFF (price -0.10 + 0.02 = -0.08, negative)
        assert sensor.is_on is False


async def test_solar_bonus_active_at_limit(hass: HomeAssistant):
    """Test solar bonus active sensor when at annual limit."""
    tracker = await SolarBonusTracker.async_create(hass, "test_entry_limit")

    # Manually set production to limit
    tracker._year_production_kwh = 7500.0

    hass.states.async_set("sensor.production_price", "0.10")

    price_settings = {
        "per_unit_supplier_electricity_production_markup": 0.02,
        "solar_bonus_annual_kwh_limit": 7500.0,
    }

    device = DeviceInfo(identifiers={("test", "test_device")})

    sensor = SolarBonusActiveBinarySensor(
        hass=hass,
        unique_id="test_solar_bonus_limit",
        device=device,
        solar_bonus_tracker=tracker,
        price_sensor="sensor.production_price",
        price_settings=price_settings,
    )

    # Mock daylight to True
    with patch.object(tracker, '_is_daylight', return_value=True):
        await sensor.async_added_to_hass()

        # Should be OFF (at limit)
        assert sensor.is_on is False


async def test_solar_bonus_active_no_price_sensor(hass: HomeAssistant):
    """Test solar bonus active sensor without price sensor."""
    tracker = await SolarBonusTracker.async_create(hass, "test_entry_no_sensor")

    price_settings = {
        "per_unit_supplier_electricity_production_markup": 0.02,
        "solar_bonus_annual_kwh_limit": 7500.0,
    }

    device = DeviceInfo(identifiers={("test", "test_device")})

    sensor = SolarBonusActiveBinarySensor(
        hass=hass,
        unique_id="test_solar_bonus_no_sensor",
        device=device,
        solar_bonus_tracker=tracker,
        price_sensor=None,
        price_settings=price_settings,
    )

    with patch.object(tracker, '_is_daylight', return_value=True):
        await sensor.async_added_to_hass()

        # Should be OFF when no price sensor
        assert sensor.is_on is False
