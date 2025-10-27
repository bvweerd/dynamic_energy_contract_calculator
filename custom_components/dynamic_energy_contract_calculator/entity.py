from __future__ import annotations

from datetime import datetime, timedelta

from typing import TYPE_CHECKING, cast

from homeassistant.components.sensor import (
    SensorEntity,
    RestoreEntity,
    SensorStateClass,
    SensorDeviceClass,
)
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.event import async_track_state_change_event

from .const import (
    SOURCE_TYPE_CONSUMPTION,
    SOURCE_TYPE_GAS,
    SOURCE_TYPE_PRODUCTION,
)
from .repair import async_report_issue, async_clear_issue

if TYPE_CHECKING:  # pragma: no cover - runtime import would create a cycle
    from .netting import NettingTracker

import logging

_LOGGER = logging.getLogger(__name__)

# Seconds to wait before creating an unavailable issue
UNAVAILABLE_GRACE_SECONDS = 60


class BaseUtilitySensor(SensorEntity, RestoreEntity):
    def __init__(
        self,
        name: str | None,
        unique_id: str,
        unit: str,
        device_class: SensorDeviceClass | str | None,
        icon: str,
        visible: bool,
        device: DeviceInfo | None = None,
        translation_key: str | None = None,
    ):
        if name is not None:
            self._attr_name = name
        self._attr_translation_key = translation_key
        self._attr_has_entity_name = translation_key is not None
        self._attr_unique_id = unique_id
        self._attr_native_unit_of_measurement = unit
        if device_class is not None and not isinstance(device_class, SensorDeviceClass):
            device_class = SensorDeviceClass(device_class)
        self._attr_device_class = device_class
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_native_value = 0.0
        self._attr_available = True
        self._attr_icon = icon
        self._attr_entity_registry_enabled_default = visible
        self._attr_device_info = device

    @property
    def native_value(self) -> float:
        return float(round(float(cast(float, self._attr_native_value or 0.0)), 8))

    async def async_added_to_hass(self):
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state not in (
            "unknown",
            "unavailable",
        ):
            try:
                self._attr_native_value = float(last_state.state)
            except ValueError:
                self._attr_native_value = 0.0

    def reset(self):
        self._attr_native_value = 0.0
        self.async_write_ha_state()

    def set_value(self, value: float):
        self._attr_native_value = round(value, 8)
        self.async_write_ha_state()

    async def async_reset(self) -> None:
        """Async wrapper for reset."""
        self.reset()

    async def async_set_value(self, value: float) -> None:
        """Async wrapper for set_value."""
        self.set_value(value)


class DynamicEnergySensor(BaseUtilitySensor):
    def __init__(
        self,
        hass: HomeAssistant,
        name: str,
        unique_id: str,
        energy_sensor: str,
        source_type: str,
        price_settings: dict[str, float],
        price_sensor: str | list[str] | None = None,
        mode: str = "kwh_total",
        unit: str = UnitOfEnergy.KILO_WATT_HOUR,
        device_class: SensorDeviceClass | str | None = None,
        icon: str = "mdi:flash",
        visible: bool = True,
        device: DeviceInfo | None = None,
        netting_tracker: "NettingTracker | None" = None,
    ):
        super().__init__(
            None,
            unique_id,
            unit=unit,
            device_class=device_class,
            icon=icon,
            visible=visible,
            device=device,
            translation_key=mode,
        )
        if mode in ("kwh_total", "m3_total"):
            self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        self.hass = hass
        self.energy_sensor = energy_sensor
        if isinstance(price_sensor, list):
            self.price_sensors = price_sensor
        elif price_sensor is None:
            self.price_sensors = []
        else:
            self.price_sensors = [price_sensor]
        self.price_sensor = self.price_sensors[0] if self.price_sensors else None
        self.input_sensors = [energy_sensor] + self.price_sensors
        self.mode = mode
        self.source_type = source_type
        self.price_settings = price_settings
        self._netting_tracker = netting_tracker
        self._last_energy = None
        self._last_updated = datetime.now()
        self._energy_unavailable_since: datetime | None = None
        self._price_unavailable_since: datetime | None = None

    @property
    def _uses_netting(self) -> bool:
        return (
            self._netting_tracker is not None
            and self.source_type == SOURCE_TYPE_CONSUMPTION
            and self.mode == "cost_total"
        )

    async def async_update(self):
        _LOGGER.debug(
            "Updating %s (mode=%s) using %s",
            self.entity_id,
            self.mode,
            self.energy_sensor,
        )
        if self.source_type == SOURCE_TYPE_GAS:
            markup_consumption = self.price_settings.get(
                "per_unit_supplier_gas_markup", 0.0
            )
            markup_production = 0.0
            tax = self.price_settings.get("per_unit_government_gas_tax", 0.0)
        else:
            markup_consumption = self.price_settings.get(
                "per_unit_supplier_electricity_markup", 0.0
            )
            markup_production = self.price_settings.get(
                "per_unit_supplier_electricity_production_markup", 0.0
            )
            tax = self.price_settings.get("per_unit_government_electricity_tax", 0.0)

        vat_factor = self.price_settings.get("vat_percentage", 21.0) / 100.0 + 1.0

        energy_state = self.hass.states.get(self.energy_sensor)
        if energy_state is None or energy_state.state in ("unknown", "unavailable"):
            self._attr_available = False
            if self._energy_unavailable_since is None:
                self._energy_unavailable_since = datetime.now()
            if datetime.now() - self._energy_unavailable_since >= timedelta(
                seconds=UNAVAILABLE_GRACE_SECONDS
            ):
                _LOGGER.warning("Energy source %s is unavailable", self.energy_sensor)
                async_report_issue(
                    self.hass,
                    f"energy_unavailable_{self.energy_sensor}",
                    "energy_source_unavailable",
                    {"sensor": self.energy_sensor},
                )
            return
        self._attr_available = True
        if self._energy_unavailable_since is not None:
            async_clear_issue(self.hass, f"energy_unavailable_{self.energy_sensor}")
            async_clear_issue(self.hass, f"energy_invalid_{self.energy_sensor}")
            self._energy_unavailable_since = None

        try:
            current_energy = float(energy_state.state)
        except ValueError:
            self._attr_available = False
            if self._energy_unavailable_since is None:
                self._energy_unavailable_since = datetime.now()
            if datetime.now() - self._energy_unavailable_since >= timedelta(
                seconds=UNAVAILABLE_GRACE_SECONDS
            ):
                _LOGGER.warning(
                    "Energy source %s has invalid state", self.energy_sensor
                )
                async_report_issue(
                    self.hass,
                    f"energy_invalid_{self.energy_sensor}",
                    "energy_source_unavailable",
                    {"sensor": self.energy_sensor},
                )
            return

        delta = 0.0
        if self._last_energy is not None:
            delta = current_energy - self._last_energy
            if delta < 0:
                delta = 0.0

        _LOGGER.debug(
            "Current energy=%s, Last energy=%s, Delta=%s",
            current_energy,
            self._last_energy,
            delta,
        )

        self._last_energy = current_energy

        if self.mode not in ("kwh_total", "m3_total") and not self.price_sensors:
            _LOGGER.debug(
                "Skipping update for %s due to missing price sensor", self.entity_id
            )
            self._attr_available = False
            return

        if self.mode in ("kwh_total", "m3_total"):
            self._attr_native_value += delta
        elif self.price_sensors:
            total_price = 0.0
            valid = False
            for sensor_id in self.price_sensors:
                price_state = self.hass.states.get(sensor_id)
                if price_state is None or price_state.state in (
                    "unknown",
                    "unavailable",
                ):
                    _LOGGER.warning("Price sensor %s is unavailable", sensor_id)
                    continue
                try:
                    total_price += float(price_state.state)
                    valid = True
                except ValueError:
                    _LOGGER.warning("Price sensor %s has invalid state", sensor_id)
                    continue
            if not valid:
                self._attr_available = False
                if self._price_unavailable_since is None:
                    self._price_unavailable_since = datetime.now()
                if (
                    datetime.now() - self._price_unavailable_since
                    >= timedelta(seconds=UNAVAILABLE_GRACE_SECONDS)
                    and self.price_sensor
                ):
                    async_report_issue(
                        self.hass,
                        f"price_unavailable_{self.price_sensor}",
                        "price_sensor_unavailable",
                        {"sensor": self.price_sensor},
                    )
                return
            self._attr_available = True
            if self._price_unavailable_since is not None and self.price_sensor:
                async_clear_issue(self.hass, f"price_unavailable_{self.price_sensor}")
                async_clear_issue(self.hass, f"price_invalid_{self.price_sensor}")
                self._price_unavailable_since = None

            adjusted_value = None
            taxable_value = 0.0

            if self.source_type == SOURCE_TYPE_GAS:
                unit_price = (
                    total_price + markup_consumption + tax
                ) * vat_factor
                value = delta * unit_price
                adjusted_value = value
            elif self.source_type == SOURCE_TYPE_CONSUMPTION:
                gross_unit_price = (
                    total_price + markup_consumption + tax
                ) * vat_factor
                base_unit_price = (total_price + markup_consumption) * vat_factor
                tax_unit_price = tax * vat_factor
                value = delta * gross_unit_price

                if self._uses_netting:
                    base_value = delta * base_unit_price
                    _, taxable_value = await self._netting_tracker.async_record_consumption(  # type: ignore[union-attr]
                        self, delta, tax_unit_price
                    )
                    adjusted_value = base_value + taxable_value
                else:
                    adjusted_value = value
            elif self.source_type == SOURCE_TYPE_PRODUCTION:
                if self.price_settings.get("production_price_include_vat", True):
                    unit_price = (total_price - markup_production) * vat_factor
                else:
                    unit_price = total_price - markup_production
                value = delta * unit_price
                adjusted_value = value

                if (
                    self.mode == "profit_total"
                    and self._netting_tracker is not None
                ):
                    _, tax_credit_value, adjustments = await self._netting_tracker.async_record_production(  # type: ignore[union-attr]
                        delta, tax * vat_factor
                    )
                    if tax_credit_value > 0:
                        for target_sensor, deduction in adjustments:
                            await target_sensor.async_apply_tax_adjustment(deduction)
            else:
                _LOGGER.error("Unknown source_type: %s", self.source_type)
                return
            if adjusted_value is None:
                adjusted_value = value

            if self.source_type == SOURCE_TYPE_CONSUMPTION:
                unit_price_for_log = (
                    total_price + markup_consumption + tax
                ) * vat_factor
            elif self.source_type == SOURCE_TYPE_GAS:
                unit_price_for_log = unit_price
            else:
                unit_price_for_log = unit_price

            _LOGGER.debug(
                "Calculated price for %s: base=%s markup_c=%s markup_p=%s tax=%s vat=%s -> %s",
                self.entity_id,
                total_price,
                markup_consumption,
                markup_production,
                tax,
                vat_factor,
                unit_price_for_log,
            )
            _LOGGER.debug(
                "Delta: %5f, Unit price: %5f, Raw value: %5f, Adjusted value: %5f",
                delta,
                unit_price_for_log,
                value,
                adjusted_value,
            )

            if self.mode == "cost_total":
                if self.source_type in (SOURCE_TYPE_CONSUMPTION, SOURCE_TYPE_GAS):
                    if value >= 0:
                        self._attr_native_value += adjusted_value
                elif self.source_type == SOURCE_TYPE_PRODUCTION:
                    if value < 0:
                        self._attr_native_value += abs(value)
            elif self.mode == "profit_total":
                if self.source_type in (SOURCE_TYPE_CONSUMPTION, SOURCE_TYPE_GAS):
                    if value < 0:
                        self._attr_native_value += abs(value)
                elif self.source_type == SOURCE_TYPE_PRODUCTION:
                    if value >= 0:
                        self._attr_native_value += value
            elif self.mode == "kwh_during_cost_total":
                if self.source_type in (SOURCE_TYPE_CONSUMPTION, SOURCE_TYPE_GAS):
                    if value >= 0:
                        self._attr_native_value += delta
                elif self.source_type == SOURCE_TYPE_PRODUCTION:
                    if value < 0:
                        self._attr_native_value += delta
            elif self.mode == "kwh_during_profit_total":
                if self.source_type in (SOURCE_TYPE_CONSUMPTION, SOURCE_TYPE_GAS):
                    if value < 0:
                        self._attr_native_value += delta
                elif self.source_type == SOURCE_TYPE_PRODUCTION:
                    if value >= 0:
                        self._attr_native_value += delta

    async def async_added_to_hass(self):
        await super().async_added_to_hass()

        if self._uses_netting:
            await self._netting_tracker.async_register_sensor(self)  # type: ignore[union-attr]

        for entity_id in self.input_sensors:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass,
                    entity_id,
                    self._handle_input_event,
                )
            )

    async def _handle_input_event(self, event):
        new_state = event.data.get("new_state")
        if new_state is None or new_state.state in ("unknown", "unavailable"):
            self._attr_available = False
        else:
            _LOGGER.debug(
                "State change detected for %s: %s",
                self.energy_sensor,
                new_state.state,
            )
        await self.async_update()
        self.async_write_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        if self._uses_netting:
            await self._netting_tracker.async_unregister_sensor(self)  # type: ignore[union-attr]
        await super().async_will_remove_from_hass()

    async def async_reset(self) -> None:
        if self._uses_netting:
            await self._netting_tracker.async_reset_all()  # type: ignore[union-attr]
        await super().async_reset()

    async def async_set_value(self, value: float) -> None:
        if self._uses_netting:
            await self._netting_tracker.async_reset_all()  # type: ignore[union-attr]
        await super().async_set_value(value)

    async def async_apply_tax_adjustment(self, deduction: float) -> None:
        """Reduce previously booked tax from this sensor."""
        if deduction <= 0:
            return
        self._attr_native_value = round(self._attr_native_value - deduction, 8)
        if self._attr_native_value < 0:
            self._attr_native_value = 0.0
        self.async_write_ha_state()


__all__ = ["BaseUtilitySensor", "DynamicEnergySensor"]
