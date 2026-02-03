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

        if brightness is not None:
            self._hass.data[DOMAIN][self._entry_id]["last_brightness"] = int(brightness)
            current_effect = (self.coordinator.data or {}).get("current_effect") or {}
            if current_effect:
                await api.preview_effect(current_effect, int(brightness))

        await self.coordinator.async_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        api = self._hass.data[DOMAIN][self._entry_id]["api"]
        await api.set_switch_state(0)
        await self.coordinator.async_refresh()
