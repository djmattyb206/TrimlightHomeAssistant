from __future__ import annotations

from typing import Any

from homeassistant.components.light import ATTR_BRIGHTNESS, ColorMode, LightEntity
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
    async_add_entities([TrimlightLight(hass, entry.entry_id, coordinator)])


class TrimlightLight(TrimlightEntity, LightEntity):
    _attr_name = "Trimlight"
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}
    _attr_color_mode = ColorMode.BRIGHTNESS

    def __init__(self, hass: HomeAssistant, entry_id: str, coordinator) -> None:
        super().__init__(hass, entry_id, coordinator)
        self._attr_unique_id = f"{entry_id}_light"

    @property
    def is_on(self) -> bool | None:
        switch_state = (self.coordinator.data or {}).get("switch_state")
        if switch_state is None:
            return None
        return int(switch_state) != 0

    @property
    def brightness(self) -> int | None:
        data = self.coordinator.data or {}
        brightness = data.get("brightness")
        if brightness is None:
            return self._hass.data[DOMAIN][self._entry_id]["last_brightness"]
        return int(brightness)

    async def async_turn_on(self, **kwargs: Any) -> None:
        api = self._hass.data[DOMAIN][self._entry_id]["api"]
        brightness = kwargs.get(ATTR_BRIGHTNESS)

        await api.set_switch_state(1)

        # Optimistic UI update: mark on immediately
        data = self.coordinator.data or {}
        optimistic = dict(data)
        optimistic["switch_state"] = 1
        self.coordinator.async_set_updated_data(optimistic)

        if brightness is not None:
            self._hass.data[DOMAIN][self._entry_id]["last_brightness"] = int(brightness)
            await self._apply_brightness(int(brightness))

        await self.coordinator.async_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        api = self._hass.data[DOMAIN][self._entry_id]["api"]
        await api.set_switch_state(0)
        data = self.coordinator.data or {}
        optimistic = dict(data)
        optimistic["switch_state"] = 0
        self.coordinator.async_set_updated_data(optimistic)
        await self.coordinator.async_refresh()

    async def _apply_brightness(self, brightness: int) -> None:
        data = self.coordinator.data or {}
        api = self._hass.data[DOMAIN][self._entry_id]["api"]
        last_speed = self._hass.data[DOMAIN][self._entry_id]["last_speed"]

        current_effect = data.get("current_effect") or {}
        if current_effect:
            await api.preview_effect(current_effect, brightness, speed=last_speed)
            return

        effect_id = data.get("current_effect_id")
        category = data.get("current_effect_category")
        if effect_id is None or category is None:
            return

        if category == 2:
            presets = (data.get("custom_effects") or self._hass.data[DOMAIN][self._entry_id].get("custom_cache", []))
            match = next((e for e in presets if e.get("id") == effect_id), None)
            if match:
                await api.preview_effect(match, brightness, speed=last_speed)
            return

        if category == 0:
            builtins = self._hass.data[DOMAIN][self._entry_id].get("builtins", [])
            match = next((b for b in builtins if b.get("id") == effect_id or b.get("mode") == effect_id), None)
            if match:
                await api.preview_builtin(match.get("mode", match.get("id")), brightness=brightness, speed=last_speed)
