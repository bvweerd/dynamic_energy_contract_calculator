"""Tests for netting module."""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from custom_components.dynamic_energy_contract_calculator.netting import (
    NettingTracker,
    _Adjustment,
)


class TestNettingTracker:
    """Tests for NettingTracker."""

    async def test_init_without_initial_state(self, hass: HomeAssistant):
        """Test initialization without initial state."""
        store = MagicMock(spec=Store)
        tracker = NettingTracker(hass, "entry1", store, None)

        assert tracker._net_consumption_kwh == 0.0
        assert tracker._queue == []
        assert tracker._balances == {}

    async def test_init_with_initial_state(self, hass: HomeAssistant):
        """Test initialization with initial state."""
        store = MagicMock(spec=Store)
        initial_state = {
            "net_consumption_kwh": 5.0,
            "queue": [
                {"sensor_id": "sensor1", "value": 1.5},
            ],
            "balances": {"sensor1": 1.5},
        }
        tracker = NettingTracker(hass, "entry1", store, initial_state)

        assert tracker._net_consumption_kwh == 5.0
        assert len(tracker._queue) == 1
        assert tracker._queue[0].sensor_id == "sensor1"
        assert tracker._queue[0].value == 1.5
        assert tracker._balances["sensor1"] == 1.5

    async def test_init_with_invalid_queue_entries(self, hass: HomeAssistant):
        """Test initialization filters invalid queue entries."""
        store = MagicMock(spec=Store)
        initial_state = {
            "net_consumption_kwh": 0.0,
            "queue": [
                {"sensor_id": "sensor1", "value": 1.5},  # valid
                {"sensor_id": "sensor2"},  # missing value
                {"value": 1.0},  # missing sensor_id
                {"sensor_id": "sensor3", "value": 0},  # zero value
                "not_a_dict",  # not a dict
                {"sensor_id": "sensor4", "value": "invalid"},  # invalid type
            ],
            "balances": {},
        }
        tracker = NettingTracker(hass, "entry1", store, initial_state)

        # Only the first valid entry should be restored
        assert len(tracker._queue) == 1

    async def test_init_with_invalid_balances(self, hass: HomeAssistant):
        """Test initialization with invalid balance values."""
        store = MagicMock(spec=Store)
        initial_state = {
            "net_consumption_kwh": 0.0,
            "queue": [],
            "balances": {
                "sensor1": 1.5,
                "sensor2": "invalid",  # invalid type
                "sensor3": 2.0,
            },
        }
        tracker = NettingTracker(hass, "entry1", store, initial_state)

        assert "sensor1" in tracker._balances
        assert "sensor2" not in tracker._balances
        assert "sensor3" in tracker._balances

    async def test_init_balances_not_dict(self, hass: HomeAssistant):
        """Test initialization with balances that's not a dict."""
        store = MagicMock(spec=Store)
        initial_state = {
            "net_consumption_kwh": 0.0,
            "queue": [],
            "balances": "not_a_dict",
        }
        tracker = NettingTracker(hass, "entry1", store, initial_state)

        assert tracker._balances == {}

    async def test_init_queue_not_list(self, hass: HomeAssistant):
        """Test initialization with queue that's not a list."""
        store = MagicMock(spec=Store)
        initial_state = {
            "net_consumption_kwh": 0.0,
            "queue": "not_a_list",
            "balances": {},
        }
        tracker = NettingTracker(hass, "entry1", store, initial_state)

        assert tracker._queue == []

    async def test_async_create(self, hass: HomeAssistant):
        """Test async_create class method."""
        with patch.object(Store, "async_load", new_callable=AsyncMock) as mock_load:
            mock_load.return_value = {"net_consumption_kwh": 3.0}

            tracker = await NettingTracker.async_create(hass, "entry1")

            assert tracker._net_consumption_kwh == 3.0

    async def test_async_create_no_saved_state(self, hass: HomeAssistant):
        """Test async_create with no saved state."""
        with patch.object(Store, "async_load", new_callable=AsyncMock) as mock_load:
            mock_load.return_value = None

            tracker = await NettingTracker.async_create(hass, "entry1")

            assert tracker._net_consumption_kwh == 0.0

    async def test_properties(self, hass: HomeAssistant):
        """Test tracker properties."""
        store = MagicMock(spec=Store)
        tracker = NettingTracker(hass, "entry1", store, {
            "net_consumption_kwh": 5.0,
            "queue": [],
            "balances": {"sensor1": 1.5, "sensor2": 2.5},
        })

        assert tracker.net_consumption_kwh == 5.0
        assert tracker.tax_balance_per_sensor == {"sensor1": 1.5, "sensor2": 2.5}

    async def test_async_register_sensor(self, hass: HomeAssistant):
        """Test registering a sensor."""
        store = MagicMock(spec=Store)
        store.async_save = AsyncMock()
        tracker = NettingTracker(hass, "entry1", store, None)

        sensor = MagicMock()
        sensor.unique_id = "sensor_uid"

        await tracker.async_register_sensor(sensor)

        assert "sensor_uid" in tracker._sensors
        assert tracker._balances["sensor_uid"] == 0.0

    async def test_async_register_sensor_existing_balance(self, hass: HomeAssistant):
        """Test registering a sensor with existing balance."""
        store = MagicMock(spec=Store)
        store.async_save = AsyncMock()
        tracker = NettingTracker(hass, "entry1", store, {
            "balances": {"sensor_uid": 5.0},
        })

        sensor = MagicMock()
        sensor.unique_id = "sensor_uid"

        await tracker.async_register_sensor(sensor)

        # Should keep existing balance
        assert tracker._balances["sensor_uid"] == 5.0

    async def test_async_unregister_sensor(self, hass: HomeAssistant):
        """Test unregistering a sensor."""
        store = MagicMock(spec=Store)
        store.async_save = AsyncMock()
        tracker = NettingTracker(hass, "entry1", store, None)

        sensor = MagicMock()
        sensor.unique_id = "sensor_uid"

        # Register first
        await tracker.async_register_sensor(sensor)
        tracker._queue.append(_Adjustment(sensor_id="sensor_uid", value=1.0))

        # Unregister
        await tracker.async_unregister_sensor(sensor)

        assert "sensor_uid" not in tracker._sensors
        assert "sensor_uid" not in tracker._balances
        assert len(tracker._queue) == 0

    async def test_async_reset_sensor(self, hass: HomeAssistant):
        """Test resetting a sensor's balance."""
        store = MagicMock(spec=Store)
        store.async_save = AsyncMock()
        tracker = NettingTracker(hass, "entry1", store, {
            "balances": {"sensor_uid": 5.0},
            "queue": [
                {"sensor_id": "sensor_uid", "value": 2.0},
                {"sensor_id": "other", "value": 1.0},
            ],
        })

        sensor = MagicMock()
        sensor.unique_id = "sensor_uid"

        await tracker.async_reset_sensor(sensor)

        assert tracker._balances["sensor_uid"] == 0.0
        assert len(tracker._queue) == 1
        assert tracker._queue[0].sensor_id == "other"

    async def test_async_record_consumption_zero_or_negative(self, hass: HomeAssistant):
        """Test recording consumption with zero or negative values."""
        store = MagicMock(spec=Store)
        tracker = NettingTracker(hass, "entry1", store, None)

        sensor = MagicMock()

        result = await tracker.async_record_consumption(sensor, 0, 0.10)
        assert result == (0.0, 0.0)

        result = await tracker.async_record_consumption(sensor, -1.0, 0.10)
        assert result == (0.0, 0.0)

        result = await tracker.async_record_consumption(sensor, 5.0, 0)
        assert result == (0.0, 0.0)

    async def test_async_record_consumption_basic(self, hass: HomeAssistant):
        """Test recording basic consumption (net >= 0)."""
        store = MagicMock(spec=Store)
        store.async_save = AsyncMock()
        tracker = NettingTracker(hass, "entry1", store, None)

        sensor = MagicMock()
        sensor.unique_id = "sensor_uid"

        result = await tracker.async_record_consumption(sensor, 5.0, 0.10)

        assert result == (5.0, 0.5)  # taxable_kwh, taxable_value
        assert tracker._net_consumption_kwh == 5.0
        assert tracker._balances["sensor_uid"] == 0.5
        assert len(tracker._queue) == 1

    async def test_async_record_consumption_from_negative(self, hass: HomeAssistant):
        """Test recording consumption when net is negative."""
        store = MagicMock(spec=Store)
        store.async_save = AsyncMock()
        tracker = NettingTracker(hass, "entry1", store, {
            "net_consumption_kwh": -3.0,
        })

        sensor = MagicMock()
        sensor.unique_id = "sensor_uid"

        # Consume 5 kWh with net at -3, brings to +2
        # Taxable is max(2, 0) - max(-3, 0) = 2 - 0 = 2
        result = await tracker.async_record_consumption(sensor, 5.0, 0.10)

        assert result[0] == 2.0  # taxable_kwh
        assert result[1] == 0.2  # taxable_value
        assert tracker._net_consumption_kwh == 2.0

    async def test_async_record_production_zero_or_negative(self, hass: HomeAssistant):
        """Test recording production with zero or negative values."""
        store = MagicMock(spec=Store)
        tracker = NettingTracker(hass, "entry1", store, None)

        result = await tracker.async_record_production(0, 0.10)
        assert result == (0.0, 0.0, [])

        result = await tracker.async_record_production(-1.0, 0.10)
        assert result == (0.0, 0.0, [])

        result = await tracker.async_record_production(5.0, 0)
        assert result == (0.0, 0.0, [])

    async def test_async_record_production_no_queue(self, hass: HomeAssistant):
        """Test recording production with no queue to credit."""
        store = MagicMock(spec=Store)
        store.async_save = AsyncMock()
        tracker = NettingTracker(hass, "entry1", store, {
            "net_consumption_kwh": 5.0,
        })

        # Produce 3 kWh, brings net to 2
        result = await tracker.async_record_production(3.0, 0.10)

        assert result[0] == 3.0  # credited_kwh
        assert result[1] == 0.3  # credited_value = 3.0 * 0.10
        assert result[2] == []  # no adjustments (no queue to deduct from)
        assert tracker._net_consumption_kwh == 2.0

    async def test_async_record_production_with_queue(self, hass: HomeAssistant):
        """Test recording production with queue to credit."""
        store = MagicMock(spec=Store)
        store.async_save = AsyncMock()

        sensor = MagicMock()
        sensor.unique_id = "sensor_uid"

        tracker = NettingTracker(hass, "entry1", store, {
            "net_consumption_kwh": 5.0,
            "queue": [
                {"sensor_id": "sensor_uid", "value": 0.3},
            ],
            "balances": {"sensor_uid": 0.3},
        })
        tracker._sensors["sensor_uid"] = sensor

        # Produce 3 kWh, brings net to 2
        # credited_value = 3.0 * 0.10 = 0.3
        result = await tracker.async_record_production(3.0, 0.10)

        assert result[0] == 3.0  # credited_kwh
        assert result[1] == 0.3  # credited_value
        assert len(result[2]) == 1  # one adjustment
        assert result[2][0][0] == sensor
        assert result[2][0][1] == 0.3
        assert tracker._balances["sensor_uid"] == 0.0
        assert len(tracker._queue) == 0

    async def test_async_record_production_partial_queue(self, hass: HomeAssistant):
        """Test recording production that partially uses queue."""
        store = MagicMock(spec=Store)
        store.async_save = AsyncMock()

        sensor = MagicMock()
        sensor.unique_id = "sensor_uid"

        tracker = NettingTracker(hass, "entry1", store, {
            "net_consumption_kwh": 5.0,
            "queue": [
                {"sensor_id": "sensor_uid", "value": 1.0},
            ],
            "balances": {"sensor_uid": 1.0},
        })
        tracker._sensors["sensor_uid"] = sensor

        # Produce 3 kWh, brings net to 2
        # credited_value = 3.0 * 0.10 = 0.3
        # Only 0.3 from queue
        result = await tracker.async_record_production(3.0, 0.10)

        assert result[1] == 0.3  # credited_value
        assert len(result[2]) == 1
        assert result[2][0][1] == 0.3
        assert tracker._balances["sensor_uid"] == 0.7
        assert len(tracker._queue) == 1
        assert tracker._queue[0].value == 0.7

    async def test_async_record_production_multiple_queue_entries(self, hass: HomeAssistant):
        """Test production that spans multiple queue entries."""
        store = MagicMock(spec=Store)
        store.async_save = AsyncMock()

        sensor1 = MagicMock()
        sensor1.unique_id = "sensor1"
        sensor2 = MagicMock()
        sensor2.unique_id = "sensor2"

        tracker = NettingTracker(hass, "entry1", store, {
            "net_consumption_kwh": 10.0,
            "queue": [
                {"sensor_id": "sensor1", "value": 0.2},
                {"sensor_id": "sensor2", "value": 0.5},
            ],
            "balances": {"sensor1": 0.2, "sensor2": 0.5},
        })
        tracker._sensors["sensor1"] = sensor1
        tracker._sensors["sensor2"] = sensor2

        # Produce 5 kWh, brings net to 5
        # credited_value = 5.0 * 0.10 = 0.5
        result = await tracker.async_record_production(5.0, 0.10)

        assert result[1] == 0.5
        assert len(result[2]) == 2
        assert result[2][0][0] == sensor1
        assert result[2][0][1] == 0.2
        assert result[2][1][0] == sensor2
        assert result[2][1][1] == 0.3

    async def test_async_record_production_from_overage(self, hass: HomeAssistant):
        """Test production when already in overage (net <= 0)."""
        store = MagicMock(spec=Store)
        store.async_save = AsyncMock()

        tracker = NettingTracker(hass, "entry1", store, {
            "net_consumption_kwh": -2.0,  # already in overage
        })

        # Produce 3 kWh, stays in overage
        result = await tracker.async_record_production(3.0, 0.10)

        # credited_kwh = max(-2, 0) - max(-5, 0) = 0
        assert result[0] == 0.0
        assert result[1] == 0.0
        assert result[2] == []
        assert tracker._net_consumption_kwh == -5.0

    async def test_async_record_production_sensor_not_found(self, hass: HomeAssistant):
        """Test production with queue entry for unregistered sensor."""
        store = MagicMock(spec=Store)
        store.async_save = AsyncMock()

        tracker = NettingTracker(hass, "entry1", store, {
            "net_consumption_kwh": 5.0,
            "queue": [
                {"sensor_id": "unknown", "value": 0.3},
            ],
            "balances": {"unknown": 0.3},
        })

        result = await tracker.async_record_production(3.0, 0.10)

        # Should credit but not return adjustment for unknown sensor
        assert result[1] == 0.3
        assert result[2] == []  # no adjustments returned

    async def test_async_reset_all(self, hass: HomeAssistant):
        """Test resetting all tracker state."""
        store = MagicMock(spec=Store)
        store.async_save = AsyncMock()

        tracker = NettingTracker(hass, "entry1", store, {
            "net_consumption_kwh": 5.0,
            "queue": [
                {"sensor_id": "s1", "value": 1.0},
            ],
            "balances": {"s1": 1.0, "s2": 2.0},
        })

        await tracker.async_reset_all()

        assert tracker._net_consumption_kwh == 0.0
        assert len(tracker._queue) == 0
        assert tracker._balances["s1"] == 0.0
        assert tracker._balances["s2"] == 0.0

    async def test_async_save_state(self, hass: HomeAssistant):
        """Test that state is saved correctly."""
        store = MagicMock(spec=Store)
        store.async_save = AsyncMock()

        tracker = NettingTracker(hass, "entry1", store, None)
        tracker._net_consumption_kwh = 5.0
        tracker._queue = [_Adjustment(sensor_id="s1", value=1.0)]
        tracker._balances = {"s1": 1.0}

        await tracker._async_save_state()

        store.async_save.assert_called_once()
        saved_data = store.async_save.call_args[0][0]
        assert saved_data["net_consumption_kwh"] == 5.0
        assert len(saved_data["queue"]) == 1
        assert saved_data["balances"] == {"s1": 1.0}
