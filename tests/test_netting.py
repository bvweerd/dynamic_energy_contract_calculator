from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from homeassistant.core import HomeAssistant

from custom_components.dynamic_energy_contract_calculator.netting import (
    NettingTracker,
    TaxContribution,
)


def _make_sensor(unique_id: str, source_type: str, mode: str) -> SimpleNamespace:
    return SimpleNamespace(unique_id=unique_id, source_type=source_type, mode=mode)


async def test_tax_contribution_from_dict_defaults() -> None:
    contribution = TaxContribution.from_dict({})

    assert contribution.kwh == 0.0
    assert contribution.tax_rate == 0.0
    assert contribution.vat_factor == pytest.approx(1.21)


async def test_netting_tracker_restores_valid_contributions_only(
    hass: HomeAssistant,
) -> None:
    store = AsyncMock()
    tracker = NettingTracker(
        hass,
        "entry-1",
        store,
        {
            "net_consumption_kwh": 4.5,
            "tax_contributions": [
                {"kwh": 2.0, "tax_rate": 0.1, "vat_factor": 1.21},
                {"kwh": 0.0, "tax_rate": 0.2, "vat_factor": 1.21},
                {"kwh": "bad", "tax_rate": 0.2, "vat_factor": 1.21},
                "invalid",
            ],
        },
        {"per_unit_government_electricity_tax": 0.1, "vat_percentage": 21.0},
    )

    assert tracker.net_consumption_kwh == pytest.approx(4.5)
    assert len(tracker._tax_contributions) == 1
    assert tracker.tax_balance == pytest.approx(2.0 * 0.1 * 1.21)


async def test_netting_tracker_tax_properties_and_distribution(
    hass: HomeAssistant,
) -> None:
    tracker = NettingTracker(
        hass,
        "entry-2",
        AsyncMock(),
        None,
        {"per_unit_government_electricity_tax": 0.12, "vat_percentage": 9.0},
    )
    tracker._tax_contributions = [
        TaxContribution(kwh=2.0, tax_rate=0.12, vat_factor=1.09),
        TaxContribution(kwh=1.0, tax_rate=0.08, vat_factor=1.21),
    ]

    assert tracker.tax_rate == pytest.approx(0.12)
    assert tracker.vat_factor == pytest.approx(1.09)
    assert tracker.tax_balance == pytest.approx(0.3584)
    assert tracker.tax_balance_per_sensor == {}

    sensor_one = _make_sensor("cost-1", "Electricity consumption", "cost_total")
    sensor_two = _make_sensor("cost-2", "Electricity consumption", "cost_total")
    other = _make_sensor("profit-1", "Electricity production", "profit_total")

    await tracker.async_register_sensor(sensor_one)
    await tracker.async_register_sensor(sensor_two)
    await tracker.async_register_sensor(other)

    assert tracker.tax_balance_per_sensor == {
        "cost-1": pytest.approx(0.3584),
        "cost-2": 0.0,
    }

    await tracker.async_unregister_sensor(sensor_one)
    assert tracker.tax_balance_per_sensor == {"cost-2": pytest.approx(0.3584)}

    await tracker.async_unregister_sensor(_make_sensor("missing", "Other", "other"))
    assert tracker.tax_balance_per_sensor == {"cost-2": pytest.approx(0.3584)}


async def test_netting_tracker_distribution_without_consumption_sensors(
    hass: HomeAssistant,
) -> None:
    tracker = NettingTracker(hass, "entry-else", AsyncMock(), None, None)
    tracker._tax_contributions = [
        TaxContribution(kwh=1.0, tax_rate=0.1, vat_factor=1.21)
    ]
    await tracker.async_register_sensor(
        _make_sensor("profit", "Electricity production", "profit_total")
    )

    assert tracker.tax_balance_per_sensor == {"profit": 0.0}
    assert (
        await tracker.async_reset_sensor(
            _make_sensor("profit", "Electricity production", "profit_total")
        )
        is None
    )


async def test_netting_tracker_records_consumption_and_saves(
    hass: HomeAssistant,
) -> None:
    store = AsyncMock()
    tracker = NettingTracker(
        hass,
        "entry-3",
        store,
        {"net_consumption_kwh": -1.0},
        {"per_unit_government_electricity_tax": 0.11, "vat_percentage": 21.0},
    )

    taxable_kwh, taxable_value = await tracker.async_record_consumption(
        _make_sensor("cost", "Electricity consumption", "cost_total"),
        3.0,
        0.1331,
    )

    assert taxable_kwh == pytest.approx(2.0)
    assert taxable_value == pytest.approx(0.2662)
    assert tracker.net_consumption_kwh == pytest.approx(2.0)
    assert tracker.tax_balance == pytest.approx(2.0 * 0.11 * 1.21)
    store.async_save.assert_awaited_once_with(
        {
            "net_consumption_kwh": 2.0,
            "tax_contributions": [{"kwh": 2.0, "tax_rate": 0.11, "vat_factor": 1.21}],
        }
    )


async def test_netting_tracker_consumption_short_circuits_invalid_input(
    hass: HomeAssistant,
) -> None:
    store = AsyncMock()
    tracker = NettingTracker(hass, "entry-4", store, None, None)

    assert await tracker.async_record_consumption(None, 0.0, 0.1) == (0.0, 0.0)
    assert await tracker.async_record_consumption(None, 1.0, 0.0) == (0.0, 0.0)
    store.async_save.assert_not_awaited()


async def test_netting_tracker_records_production_fifo_credit(
    hass: HomeAssistant,
) -> None:
    store = AsyncMock()
    tracker = NettingTracker(
        hass,
        "entry-5",
        store,
        None,
        {"per_unit_government_electricity_tax": 0.11, "vat_percentage": 21.0},
    )
    tracker._net_consumption_kwh = 5.0
    tracker._tax_contributions = [
        TaxContribution(kwh=2.0, tax_rate=0.09, vat_factor=1.21),
        TaxContribution(kwh=3.0, tax_rate=0.11, vat_factor=1.21),
    ]

    credited_kwh, credited_value, adjustments = await tracker.async_record_production(
        4.0, 0.1331
    )

    assert credited_kwh == pytest.approx(4.0)
    assert credited_value == pytest.approx(0.5324)
    assert adjustments == []
    assert tracker.net_consumption_kwh == pytest.approx(1.0)
    assert len(tracker._tax_contributions) == 1
    assert tracker._tax_contributions[0].kwh == pytest.approx(1.0)
    store.async_save.assert_awaited_once()


async def test_netting_tracker_production_short_circuits_invalid_input(
    hass: HomeAssistant,
) -> None:
    store = AsyncMock()
    tracker = NettingTracker(hass, "entry-6", store, None, None)

    assert await tracker.async_record_production(0.0, 0.2) == (0.0, 0.0, [])
    assert await tracker.async_record_production(1.0, 0.0) == (0.0, 0.0, [])
    store.async_save.assert_not_awaited()


async def test_netting_tracker_set_net_consumption_and_reset_all(
    hass: HomeAssistant,
) -> None:
    store = AsyncMock()
    tracker = NettingTracker(
        hass,
        "entry-7",
        store,
        None,
        {"per_unit_government_electricity_tax": 0.15, "vat_percentage": 21.0},
    )

    await tracker.async_set_net_consumption(3.5)
    assert tracker.net_consumption_kwh == pytest.approx(3.5)
    assert tracker._tax_contributions[0].kwh == pytest.approx(3.5)

    await tracker.async_set_net_consumption(-2.0)
    assert tracker.net_consumption_kwh == pytest.approx(-2.0)
    assert tracker._tax_contributions == []

    await tracker.async_reset_all()
    assert tracker.net_consumption_kwh == 0.0
    assert tracker._tax_contributions == []
    assert store.async_save.await_count == 3
