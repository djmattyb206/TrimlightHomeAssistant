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
            speed = self._hass.data[DOMAIN][self._entry_id]["last_speed"]
        return round((float(speed) / 255.0) * 100.0, 1)

    async def async_set_native_value(self, value: float) -> None:
        speed = int(round((float(value) / 100.0) * 255.0))
        data = self._hass.data[DOMAIN][self._entry_id]
        api = data["api"]
        data["last_speed"] = speed

        coord = self.coordinator.data or {}
        current_effect = coord.get("current_effect") or {}
        if current_effect:
            brightness = data["last_brightness"]
            await api.preview_effect(current_effect, brightness, speed=speed)
        else:
            effect_id = coord.get("current_effect_id")
            category = coord.get("current_effect_category")
            brightness = data["last_brightness"]
            if category in (1, 2):
                presets = (coord.get("custom_effects") or data.get("custom_cache", []))
                match = next((e for e in presets if e.get("id") == effect_id), None)
                if match:
                    await api.preview_effect(match, brightness, speed=speed)
            elif category == 0:
                builtins = data.get("builtins", [])
                match = next((b for b in builtins if b.get("id") == effect_id or b.get("mode") == effect_id), None)
                if match:
                    pixel_len = None
                    reverse = None
                    if current_effect and current_effect.get("category") == 0:
                        pixel_len = current_effect.get("pixelLen")
                        reverse = current_effect.get("reverse")

                    if pixel_len is None or reverse is None:
                        effects = (coord.get("effects") or [])
                        for e in effects:
                            if e.get("category") == 0 and (
                                e.get("id") == effect_id
                                or e.get("mode") == effect_id
                                or e.get("mode") == current_effect.get("mode")
                            ):
                                if pixel_len is None:
                                    pixel_len = e.get("pixelLen")
                                if reverse is None:
                                    reverse = e.get("reverse")

                    pixel_len = 30 if pixel_len is None else int(pixel_len)
                    reverse = False if reverse is None else bool(reverse)

                    await api.preview_builtin(
                        match.get("mode", match.get("id")),
                        brightness=brightness,
                        speed=speed,
                        pixel_len=pixel_len,
                        reverse=reverse,
                    )

        self._schedule_verification_refresh()
