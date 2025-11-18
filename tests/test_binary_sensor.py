"""Tests for binary_sensor platform."""
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from homeassistant.core import HomeAssistant, Event, State
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.device_registry import DeviceEntryType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dynamic_energy_contract_calculator.binary_sensor import (
    ReturnCostsBinarySensor,
    async_setup_entry,
)
from custom_components.dynamic_energy_contract_calculator.const import (
    DOMAIN,
    DOMAIN_ABBREVIATION,
    CONF_PRICE_SENSOR,
    CONF_PRICE_SETTINGS,
)


@pytest.fixture
def device_info():
    """Return a sample device info."""
    return DeviceInfo(
        identifiers={(DOMAIN, "test_device")},
        name=f"{DOMAIN_ABBREVIATION}: Test Device",
        entry_type=DeviceEntryType.SERVICE,
        manufacturer="DynamicEnergyCalc",
        model="test",
    )


@pytest.fixture
def price_settings():
    """Return sample price settings."""
    return {
        "per_unit_supplier_electricity_production_markup": 0.05,
        "vat_percentage": 21.0,
        "production_price_include_vat": True,
    }


class TestReturnCostsBinarySensor:
    """Tests for ReturnCostsBinarySensor."""

    async def test_init_with_string_price_sensor(self, hass: HomeAssistant, device_info, price_settings):
        """Test initialization with a single price sensor string."""
        sensor = ReturnCostsBinarySensor(
            hass=hass,
            unique_id="test_unique_id",
            price_sensor="sensor.price",
            price_settings=price_settings,
            device=device_info,
        )

        assert sensor._attr_unique_id == "test_unique_id"
        assert sensor.price_sensors == ["sensor.price"]
        assert sensor._attr_is_on is False
        assert sensor._attr_available is True
        assert sensor._current_price is None

    async def test_init_with_list_price_sensors(self, hass: HomeAssistant, device_info, price_settings):
        """Test initialization with multiple price sensors."""
        sensors = ["sensor.price1", "sensor.price2"]
        sensor = ReturnCostsBinarySensor(
            hass=hass,
            unique_id="test_unique_id",
            price_sensor=sensors,
            price_settings=price_settings,
            device=device_info,
        )

        assert sensor.price_sensors == sensors

    async def test_extra_state_attributes(self, hass: HomeAssistant, device_info, price_settings):
        """Test extra state attributes."""
        sensor = ReturnCostsBinarySensor(
            hass=hass,
            unique_id="test",
            price_sensor="sensor.price",
            price_settings=price_settings,
            device=device_info,
        )
        sensor._current_price = -0.05

        attrs = sensor.extra_state_attributes
        assert attrs["current_production_price"] == -0.05

    async def test_calculate_production_price_with_vat(self, hass: HomeAssistant, device_info):
        """Test production price calculation with VAT."""
        settings = {
            "per_unit_supplier_electricity_production_markup": 0.05,
            "vat_percentage": 21.0,
            "production_price_include_vat": True,
        }
        sensor = ReturnCostsBinarySensor(
            hass=hass,
            unique_id="test",
            price_sensor="sensor.price",
            price_settings=settings,
            device=device_info,
        )

        # Base price 0.10, markup 0.05, VAT 21%
        # (0.10 - 0.05) * 1.21 = 0.0605
        price = sensor._calculate_production_price(0.10)
        assert abs(price - 0.0605) < 0.0001

    async def test_calculate_production_price_without_vat(self, hass: HomeAssistant, device_info):
        """Test production price calculation without VAT."""
        settings = {
            "per_unit_supplier_electricity_production_markup": 0.05,
            "vat_percentage": 21.0,
            "production_price_include_vat": False,
        }
        sensor = ReturnCostsBinarySensor(
            hass=hass,
            unique_id="test",
            price_sensor="sensor.price",
            price_settings=settings,
            device=device_info,
        )

        # Base price 0.10, markup 0.05, no VAT
        # 0.10 - 0.05 = 0.05
        price = sensor._calculate_production_price(0.10)
        assert abs(price - 0.05) < 0.0001

    async def test_async_update_with_valid_sensor(self, hass: HomeAssistant, device_info, price_settings):
        """Test async_update with a valid price sensor."""
        hass.states.async_set("sensor.price", "0.10")

        sensor = ReturnCostsBinarySensor(
            hass=hass,
            unique_id="test",
            price_sensor="sensor.price",
            price_settings=price_settings,
            device=device_info,
        )

        await sensor.async_update()

        assert sensor._attr_available is True
        assert sensor._current_price is not None
        # Price is positive, so return does not cost money
        assert sensor._attr_is_on is False

    async def test_async_update_with_negative_price(self, hass: HomeAssistant, device_info, price_settings):
        """Test async_update with a negative price (return costs money)."""
        hass.states.async_set("sensor.price", "-0.10")

        sensor = ReturnCostsBinarySensor(
            hass=hass,
            unique_id="test",
            price_sensor="sensor.price",
            price_settings=price_settings,
            device=device_info,
        )

        await sensor.async_update()

        assert sensor._attr_available is True
        # Price is negative after calculation, so return costs money
        assert sensor._attr_is_on is True

    async def test_async_update_with_unavailable_sensor(self, hass: HomeAssistant, device_info, price_settings):
        """Test async_update with an unavailable sensor."""
        hass.states.async_set("sensor.price", "unavailable")

        sensor = ReturnCostsBinarySensor(
            hass=hass,
            unique_id="test",
            price_sensor="sensor.price",
            price_settings=price_settings,
            device=device_info,
        )

        await sensor.async_update()

        assert sensor._attr_available is False

    async def test_async_update_with_unknown_sensor(self, hass: HomeAssistant, device_info, price_settings):
        """Test async_update with an unknown sensor."""
        hass.states.async_set("sensor.price", "unknown")

        sensor = ReturnCostsBinarySensor(
            hass=hass,
            unique_id="test",
            price_sensor="sensor.price",
            price_settings=price_settings,
            device=device_info,
        )

        await sensor.async_update()

        assert sensor._attr_available is False

    async def test_async_update_with_missing_sensor(self, hass: HomeAssistant, device_info, price_settings):
        """Test async_update with a missing sensor."""
        sensor = ReturnCostsBinarySensor(
            hass=hass,
            unique_id="test",
            price_sensor="sensor.nonexistent",
            price_settings=price_settings,
            device=device_info,
        )

        await sensor.async_update()

        assert sensor._attr_available is False

    async def test_async_update_with_invalid_value(self, hass: HomeAssistant, device_info, price_settings):
        """Test async_update with an invalid sensor value."""
        hass.states.async_set("sensor.price", "not_a_number")

        sensor = ReturnCostsBinarySensor(
            hass=hass,
            unique_id="test",
            price_sensor="sensor.price",
            price_settings=price_settings,
            device=device_info,
        )

        await sensor.async_update()

        assert sensor._attr_available is False

    async def test_async_update_with_multiple_sensors(self, hass: HomeAssistant, device_info, price_settings):
        """Test async_update with multiple price sensors."""
        hass.states.async_set("sensor.price1", "0.05")
        hass.states.async_set("sensor.price2", "0.03")

        sensor = ReturnCostsBinarySensor(
            hass=hass,
            unique_id="test",
            price_sensor=["sensor.price1", "sensor.price2"],
            price_settings=price_settings,
            device=device_info,
        )

        await sensor.async_update()

        assert sensor._attr_available is True

    async def test_async_update_with_partial_valid_sensors(self, hass: HomeAssistant, device_info, price_settings):
        """Test async_update with some valid and some invalid sensors."""
        hass.states.async_set("sensor.price1", "0.10")
        hass.states.async_set("sensor.price2", "unavailable")

        sensor = ReturnCostsBinarySensor(
            hass=hass,
            unique_id="test",
            price_sensor=["sensor.price1", "sensor.price2"],
            price_settings=price_settings,
            device=device_info,
        )

        await sensor.async_update()

        # Should still be available if at least one sensor is valid
        assert sensor._attr_available is True

    async def test_async_added_to_hass_restores_state(self, hass: HomeAssistant, device_info, price_settings):
        """Test that state is restored when added to hass."""
        sensor = ReturnCostsBinarySensor(
            hass=hass,
            unique_id="test",
            price_sensor="sensor.price",
            price_settings=price_settings,
            device=device_info,
        )

        # Create a mock last state
        last_state = MagicMock()
        last_state.state = "on"
        last_state.attributes = {"current_production_price": -0.05}

        with patch.object(sensor, "async_get_last_state", return_value=last_state):
            await sensor.async_added_to_hass()

        assert sensor._attr_is_on is True
        assert sensor._current_price == -0.05

    async def test_async_added_to_hass_no_previous_state(self, hass: HomeAssistant, device_info, price_settings):
        """Test added to hass with no previous state."""
        sensor = ReturnCostsBinarySensor(
            hass=hass,
            unique_id="test",
            price_sensor="sensor.price",
            price_settings=price_settings,
            device=device_info,
        )

        with patch.object(sensor, "async_get_last_state", return_value=None):
            await sensor.async_added_to_hass()

        # State should remain at defaults
        assert sensor._attr_is_on is False

    async def test_handle_price_change_with_valid_state(self, hass: HomeAssistant, device_info, price_settings):
        """Test handling price sensor state changes."""
        hass.states.async_set("sensor.price", "0.10")

        sensor = ReturnCostsBinarySensor(
            hass=hass,
            unique_id="test",
            price_sensor="sensor.price",
            price_settings=price_settings,
            device=device_info,
        )

        new_state = State("sensor.price", "0.05")
        event = Event("state_changed", {
            "entity_id": "sensor.price",
            "new_state": new_state,
        })

        with patch.object(sensor, "async_write_ha_state"):
            await sensor._handle_price_change(event)

        assert sensor._attr_available is True

    async def test_handle_price_change_with_unavailable_state(self, hass: HomeAssistant, device_info, price_settings):
        """Test handling price sensor becoming unavailable."""
        sensor = ReturnCostsBinarySensor(
            hass=hass,
            unique_id="test",
            price_sensor="sensor.price",
            price_settings=price_settings,
            device=device_info,
        )

        new_state = State("sensor.price", "unavailable")
        event = Event("state_changed", {
            "entity_id": "sensor.price",
            "new_state": new_state,
        })

        await sensor._handle_price_change(event)

        assert sensor._attr_available is False

    async def test_handle_price_change_with_none_state(self, hass: HomeAssistant, device_info, price_settings):
        """Test handling price sensor with None new_state."""
        sensor = ReturnCostsBinarySensor(
            hass=hass,
            unique_id="test",
            price_sensor="sensor.price",
            price_settings=price_settings,
            device=device_info,
        )

        event = Event("state_changed", {
            "entity_id": "sensor.price",
            "new_state": None,
        })

        await sensor._handle_price_change(event)

        assert sensor._attr_available is False


