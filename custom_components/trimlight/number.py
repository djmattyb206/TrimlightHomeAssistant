from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .controller import apply_effect_update
from .data import get_data
from .entity import TrimlightEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data = get_data(hass, entry.entry_id)
    coordinator = data.coordinator
    async_add_entities([TrimlightSpeedNumber(hass, entry.entry_id, coordinator)])


class TrimlightSpeedNumber(TrimlightEntity, NumberEntity):
    _attr_name = "Trimlight Effect Speed"
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "%"
    _attr_mode = NumberMode.SLIDER

    def __init__(self, hass: HomeAssistant, entry_id: str, coordinator) -> None:
        super().__init__(hass, entry_id, coordinator)
        self._attr_unique_id = f"{entry_id}_effect_speed"

    @property
    def native_value(self) -> float | None:
        data = self.coordinator.data or {}
        speed = (data.get("current_effect") or {}).get("speed")
        if speed is None:
            speed = self._data.last_speed
        return round((float(speed) / 255.0) * 100.0, 1)

    async def async_set_native_value(self, value: float) -> None:
        speed = int(round((float(value) / 100.0) * 255.0))
        data = self._data
        api = data.api
        data.last_speed = speed

        await apply_effect_update(api, data, self.coordinator.data or {}, speed=speed)

        self._schedule_verification_refresh()
