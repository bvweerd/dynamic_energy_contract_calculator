"""Tests for overage_compensation module."""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from custom_components.dynamic_energy_contract_calculator.overage_compensation import (
    OverageCompensationTracker,
    _PendingCompensation,
)


class TestOverageCompensationTracker:
    """Tests for OverageCompensationTracker."""

    async def test_init_without_initial_state(self, hass: HomeAssistant):
        """Test initialization without initial state."""
        store = MagicMock(spec=Store)
        tracker = OverageCompensationTracker(hass, "entry1", store, None)

        assert tracker._net_consumption_kwh == 0.0
        assert tracker._total_consumption_kwh == 0.0
        assert tracker._total_production_kwh == 0.0
        assert tracker._pending_queue == []

    async def test_init_with_initial_state(self, hass: HomeAssistant):
        """Test initialization with initial state."""
        store = MagicMock(spec=Store)
        initial_state = {
            "net_consumption_kwh": 5.0,
            "total_consumption_kwh": 10.0,
            "total_production_kwh": 5.0,
            "pending_queue": [
                {"sensor_id": "sensor1", "kwh": 2.0, "unit_price_diff": 0.05},
            ],
        }
        tracker = OverageCompensationTracker(hass, "entry1", store, initial_state)

        assert tracker._net_consumption_kwh == 5.0
        assert tracker._total_consumption_kwh == 10.0
        assert tracker._total_production_kwh == 5.0
        assert len(tracker._pending_queue) == 1
        assert tracker._pending_queue[0].sensor_id == "sensor1"
        assert tracker._pending_queue[0].kwh == 2.0
        assert tracker._pending_queue[0].unit_price_diff == 0.05

    async def test_init_with_invalid_queue_entries(self, hass: HomeAssistant):
        """Test initialization filters invalid queue entries."""
        store = MagicMock(spec=Store)
        initial_state = {
            "net_consumption_kwh": 0.0,
            "pending_queue": [
                {"sensor_id": "sensor1", "kwh": 2.0, "unit_price_diff": 0.05},  # valid
                {"sensor_id": "sensor2"},  # missing kwh and price_diff
                {"kwh": 1.0, "unit_price_diff": 0.03},  # missing sensor_id
                {"sensor_id": "sensor3", "kwh": 0, "unit_price_diff": 0.05},  # zero kwh
                "not_a_dict",  # not a dict
                {"sensor_id": "sensor4", "kwh": "invalid", "unit_price_diff": 0.05},  # invalid type
            ],
        }
        tracker = OverageCompensationTracker(hass, "entry1", store, initial_state)

        # Only the first valid entry should be restored
        assert len(tracker._pending_queue) == 1

    async def test_async_create(self, hass: HomeAssistant):
        """Test async_create class method."""
        with patch.object(Store, "async_load", new_callable=AsyncMock) as mock_load:
            mock_load.return_value = {"net_consumption_kwh": 3.0}

            tracker = await OverageCompensationTracker.async_create(hass, "entry1")

            assert tracker._net_consumption_kwh == 3.0

    async def test_async_create_no_saved_state(self, hass: HomeAssistant):
        """Test async_create with no saved state."""
        with patch.object(Store, "async_load", new_callable=AsyncMock) as mock_load:
            mock_load.return_value = None

            tracker = await OverageCompensationTracker.async_create(hass, "entry1")

            assert tracker._net_consumption_kwh == 0.0

    async def test_properties(self, hass: HomeAssistant):
        """Test tracker properties."""
        store = MagicMock(spec=Store)
        tracker = OverageCompensationTracker(hass, "entry1", store, {
            "net_consumption_kwh": 5.0,
            "total_consumption_kwh": 10.0,
            "total_production_kwh": 8.0,
            "pending_queue": [
                {"sensor_id": "s1", "kwh": 2.0, "unit_price_diff": 0.05},
                {"sensor_id": "s2", "kwh": 3.0, "unit_price_diff": 0.03},
            ],
        })

        assert tracker.net_consumption_kwh == 5.0
        assert tracker.total_consumption_kwh == 10.0
        assert tracker.total_production_kwh == 8.0
        assert tracker.pending_compensation_kwh == 5.0  # 2.0 + 3.0

    async def test_async_register_sensor(self, hass: HomeAssistant):
        """Test registering a sensor."""
        store = MagicMock(spec=Store)
        tracker = OverageCompensationTracker(hass, "entry1", store, None)

        sensor = MagicMock()
        sensor.unique_id = "sensor_uid"

        await tracker.async_register_sensor(sensor)

        assert "sensor_uid" in tracker._sensors

    async def test_async_unregister_sensor(self, hass: HomeAssistant):
        """Test unregistering a sensor."""
        store = MagicMock(spec=Store)
        store.async_save = AsyncMock()
        tracker = OverageCompensationTracker(hass, "entry1", store, None)

        sensor = MagicMock()
        sensor.unique_id = "sensor_uid"

        # Register first
        await tracker.async_register_sensor(sensor)
        tracker._pending_queue.append(
            _PendingCompensation(sensor_id="sensor_uid", kwh=1.0, unit_price_diff=0.05)
        )

        # Unregister
        await tracker.async_unregister_sensor(sensor)

        assert "sensor_uid" not in tracker._sensors
        assert len(tracker._pending_queue) == 0

    async def test_async_record_consumption_zero_or_negative(self, hass: HomeAssistant):
        """Test recording consumption with zero or negative value."""
        store = MagicMock(spec=Store)
        tracker = OverageCompensationTracker(hass, "entry1", store, None)

        result = await tracker.async_record_consumption(0)
        assert result == []

        result = await tracker.async_record_consumption(-1.0)
        assert result == []

    async def test_async_record_consumption_basic(self, hass: HomeAssistant):
        """Test recording basic consumption."""
        store = MagicMock(spec=Store)
        store.async_save = AsyncMock()
        tracker = OverageCompensationTracker(hass, "entry1", store, None)

        result = await tracker.async_record_consumption(5.0)

        assert result == []
        assert tracker._net_consumption_kwh == 5.0
        assert tracker._total_consumption_kwh == 5.0

    async def test_async_record_consumption_with_compensation(self, hass: HomeAssistant):
        """Test recording consumption that triggers compensation."""
        store = MagicMock(spec=Store)
        store.async_save = AsyncMock()

        # Create a sensor mock
        sensor = MagicMock()
        sensor.unique_id = "sensor_uid"

        # Initialize tracker in overage state (net < 0)
        tracker = OverageCompensationTracker(hass, "entry1", store, {
            "net_consumption_kwh": -3.0,
            "total_consumption_kwh": 0.0,
            "total_production_kwh": 3.0,
            "pending_queue": [
                {"sensor_id": "sensor_uid", "kwh": 2.0, "unit_price_diff": 0.10},
            ],
        })
        tracker._sensors["sensor_uid"] = sensor

        # Consume 5 kWh - brings net from -3 to +2
        # Should compensate 2 kWh from queue (min of 5 and 3)
        result = await tracker.async_record_consumption(5.0)

        assert len(result) == 1
        assert result[0][0] == sensor
        # compensation = 2.0 * 0.10 = 0.20
        assert result[0][1] == 0.2
        assert tracker._net_consumption_kwh == 2.0
        assert tracker._total_consumption_kwh == 5.0

    async def test_async_record_consumption_partial_queue(self, hass: HomeAssistant):
        """Test consumption that partially consumes the queue."""
        store = MagicMock(spec=Store)
        store.async_save = AsyncMock()

        sensor = MagicMock()
        sensor.unique_id = "sensor_uid"

        tracker = OverageCompensationTracker(hass, "entry1", store, {
            "net_consumption_kwh": -5.0,
            "pending_queue": [
                {"sensor_id": "sensor_uid", "kwh": 10.0, "unit_price_diff": 0.10},
            ],
        })
        tracker._sensors["sensor_uid"] = sensor

        # Consume 3 kWh - brings net from -5 to -2
        # Should compensate only 3 kWh from queue
        result = await tracker.async_record_consumption(3.0)

        assert len(result) == 1
        assert result[0][1] == 0.3  # 3.0 * 0.10
        assert tracker._pending_queue[0].kwh == 7.0  # 10.0 - 3.0
        assert tracker._net_consumption_kwh == -2.0

    async def test_async_record_production_zero_or_negative(self, hass: HomeAssistant):
        """Test recording production with zero or negative value."""
        store = MagicMock(spec=Store)
        tracker = OverageCompensationTracker(hass, "entry1", store, None)

        sensor = MagicMock()

        result = await tracker.async_record_production(sensor, 0, 0.15, 0.05)
        assert result == (0.0, 0.0, 0.0, 0.0)

        result = await tracker.async_record_production(sensor, -1.0, 0.15, 0.05)
        assert result == (0.0, 0.0, 0.0, 0.0)

    async def test_async_record_production_all_compensated(self, hass: HomeAssistant):
        """Test production that's fully compensated at normal rate."""
        store = MagicMock(spec=Store)
        store.async_save = AsyncMock()

        sensor = MagicMock()
        sensor.unique_id = "sensor_uid"

        # Start with positive net consumption
        tracker = OverageCompensationTracker(hass, "entry1", store, {
            "net_consumption_kwh": 10.0,
            "total_production_kwh": 0.0,
        })

        # Produce 5 kWh with net at 10 - all compensated at normal rate
        result = await tracker.async_record_production(sensor, 5.0, 0.15, 0.05)

        assert result[0] == 5.0  # compensated_kwh
        assert result[1] == 0.75  # compensated_value = 5.0 * 0.15
        assert result[2] == 0.0  # overage_kwh
        assert result[3] == 0.0  # overage_value
        assert tracker._net_consumption_kwh == 5.0
        assert tracker._total_production_kwh == 5.0
        assert len(tracker._pending_queue) == 0

    async def test_async_record_production_all_overage(self, hass: HomeAssistant):
        """Test production that's all overage."""
        store = MagicMock(spec=Store)
        store.async_save = AsyncMock()

        sensor = MagicMock()
        sensor.unique_id = "sensor_uid"

        # Start with negative net (already in overage)
        tracker = OverageCompensationTracker(hass, "entry1", store, {
            "net_consumption_kwh": -2.0,
            "total_production_kwh": 2.0,
        })

        # Produce 3 kWh - all at overage rate
        result = await tracker.async_record_production(sensor, 3.0, 0.15, 0.05)

        assert result[0] == 0.0  # compensated_kwh
        assert result[1] == 0.0  # compensated_value
        assert result[2] == 3.0  # overage_kwh
        assert result[3] == 0.15  # overage_value = 3.0 * 0.05
        assert tracker._net_consumption_kwh == -5.0
        assert len(tracker._pending_queue) == 1
        assert tracker._pending_queue[0].kwh == 3.0
        assert abs(tracker._pending_queue[0].unit_price_diff - 0.10) < 0.0001  # 0.15 - 0.05

    async def test_async_record_production_mixed(self, hass: HomeAssistant):
        """Test production that's partly compensated and partly overage."""
        store = MagicMock(spec=Store)
        store.async_save = AsyncMock()

        sensor = MagicMock()
        sensor.unique_id = "sensor_uid"

        # Start with net of 3 kWh consumption
        tracker = OverageCompensationTracker(hass, "entry1", store, {
            "net_consumption_kwh": 3.0,
        })

        # Produce 5 kWh - 3 compensated, 2 overage
        result = await tracker.async_record_production(sensor, 5.0, 0.15, 0.05)

        assert result[0] == 3.0  # compensated_kwh
        assert result[1] == 0.45  # compensated_value = 3.0 * 0.15
        assert result[2] == 2.0  # overage_kwh
        assert result[3] == 0.10  # overage_value = 2.0 * 0.05
        assert tracker._net_consumption_kwh == -2.0
        assert len(tracker._pending_queue) == 1

    async def test_async_record_production_no_price_diff(self, hass: HomeAssistant):
        """Test production with no price difference doesn't queue."""
        store = MagicMock(spec=Store)
        store.async_save = AsyncMock()

        sensor = MagicMock()
        sensor.unique_id = "sensor_uid"

        # Start with zero net
        tracker = OverageCompensationTracker(hass, "entry1", store, {
            "net_consumption_kwh": 0.0,
        })

        # Produce with same normal and overage prices
        result = await tracker.async_record_production(sensor, 5.0, 0.10, 0.10)

        assert result[2] == 5.0  # overage_kwh
        # No pending queue because price_diff is 0
        assert len(tracker._pending_queue) == 0

    async def test_async_reset_all(self, hass: HomeAssistant):
        """Test resetting all tracker state."""
        store = MagicMock(spec=Store)
        store.async_save = AsyncMock()

        tracker = OverageCompensationTracker(hass, "entry1", store, {
            "net_consumption_kwh": 5.0,
            "total_consumption_kwh": 10.0,
            "total_production_kwh": 5.0,
            "pending_queue": [
                {"sensor_id": "s1", "kwh": 2.0, "unit_price_diff": 0.05},
            ],
        })

        await tracker.async_reset_all()

        assert tracker._net_consumption_kwh == 0.0
        assert tracker._total_consumption_kwh == 0.0
        assert tracker._total_production_kwh == 0.0
        assert len(tracker._pending_queue) == 0

    async def test_async_save_state(self, hass: HomeAssistant):
        """Test that state is saved correctly."""
        store = MagicMock(spec=Store)
        store.async_save = AsyncMock()

        tracker = OverageCompensationTracker(hass, "entry1", store, None)
        tracker._net_consumption_kwh = 5.0
        tracker._total_consumption_kwh = 10.0
        tracker._total_production_kwh = 8.0
        tracker._pending_queue = [
            _PendingCompensation(sensor_id="s1", kwh=2.0, unit_price_diff=0.05),
        ]

        await tracker._async_save_state()

        store.async_save.assert_called_once()
        saved_data = store.async_save.call_args[0][0]
        assert saved_data["net_consumption_kwh"] == 5.0
        assert saved_data["total_consumption_kwh"] == 10.0
        assert saved_data["total_production_kwh"] == 8.0
        assert len(saved_data["pending_queue"]) == 1

    async def test_init_queue_not_list(self, hass: HomeAssistant):
        """Test initialization with queue that's not a list."""
        store = MagicMock(spec=Store)
        initial_state = {
            "net_consumption_kwh": 0.0,
            "pending_queue": "not_a_list",  # Invalid
        }
        tracker = OverageCompensationTracker(hass, "entry1", store, initial_state)

        assert len(tracker._pending_queue) == 0

    async def test_consumption_multiple_queue_entries(self, hass: HomeAssistant):
        """Test consumption that compensates across multiple queue entries."""
        store = MagicMock(spec=Store)
        store.async_save = AsyncMock()

        sensor1 = MagicMock()
        sensor1.unique_id = "sensor1"
        sensor2 = MagicMock()
        sensor2.unique_id = "sensor2"

        tracker = OverageCompensationTracker(hass, "entry1", store, {
            "net_consumption_kwh": -10.0,
            "pending_queue": [
                {"sensor_id": "sensor1", "kwh": 3.0, "unit_price_diff": 0.10},
                {"sensor_id": "sensor2", "kwh": 5.0, "unit_price_diff": 0.08},
            ],
        })
        tracker._sensors["sensor1"] = sensor1
        tracker._sensors["sensor2"] = sensor2

        # Consume 7 kWh - should compensate all of sensor1 (3) and part of sensor2 (4)
        result = await tracker.async_record_consumption(7.0)

        assert len(result) == 2
        assert result[0][0] == sensor1
        assert result[0][1] == 0.30  # 3.0 * 0.10
        assert result[1][0] == sensor2
        assert result[1][1] == 0.32  # 4.0 * 0.08 = 0.32
        assert len(tracker._pending_queue) == 1
        assert tracker._pending_queue[0].kwh == 1.0

    async def test_consumption_sensor_not_registered(self, hass: HomeAssistant):
        """Test consumption with unregistered sensor in queue."""
        store = MagicMock(spec=Store)
        store.async_save = AsyncMock()

        tracker = OverageCompensationTracker(hass, "entry1", store, {
            "net_consumption_kwh": -5.0,
            "pending_queue": [
                {"sensor_id": "unknown_sensor", "kwh": 3.0, "unit_price_diff": 0.10},
            ],
        })

        # Consume - should process queue but not return adjustment for unknown sensor
        result = await tracker.async_record_consumption(5.0)

        assert len(result) == 0
        assert len(tracker._pending_queue) == 0
