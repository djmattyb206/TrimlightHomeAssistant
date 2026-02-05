from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import TrimlightEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    async_add_entities([TrimlightSpeedNumber(hass, entry.entry_id, coordinator)])


class TrimlightSpeedNumber(TrimlightEntity, NumberEntity):
    _attr_name = "Trimlight Effect Speed"
    _attr_native_min_value = 0
    _attr_native_max_value = 255
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "speed"
    _attr_mode = NumberMode.SLIDER

    def __init__(self, hass: HomeAssistant, entry_id: str, coordinator) -> None:
        super().__init__(hass, entry_id, coordinator)
        self._attr_unique_id = f"{entry_id}_effect_speed"

    @property
    def native_value(self) -> float | None:
        data = self.coordinator.data or {}
        speed = (data.get("current_effect") or {}).get("speed")
        if speed is None:
            return float(self._hass.data[DOMAIN][self._entry_id]["last_speed"])
        return float(speed)

    async def async_set_native_value(self, value: float) -> None:
        speed = int(value)
        data = self._hass.data[DOMAIN][self._entry_id]
        api = data["api"]
        data["last_speed"] = speed

        current_effect = (self.coordinator.data or {}).get("current_effect") or {}
        if current_effect:
            brightness = data["last_brightness"]
            await api.preview_effect(current_effect, brightness, speed=speed)

        await self.coordinator.async_refresh()
