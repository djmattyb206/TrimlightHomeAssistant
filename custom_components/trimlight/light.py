from __future__ import annotations

import time
from typing import Any

from homeassistant.components.light import ATTR_BRIGHTNESS, ColorMode, LightEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import FORCED_ON_GRACE_SECONDS
from .controller import apply_effect_update
from .data import get_data
from .entity import TrimlightEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data = get_data(hass, entry.entry_id)
    coordinator = data.coordinator
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
        if int(switch_state) != 0:
            # Clear any grace window once the device reports on.
            data = self._data
            data.forced_on_until = None
            forced_off_until = data.forced_off_until
            if forced_off_until is not None and time.monotonic() < forced_off_until:
                return False
            return True
        # Device reports off: clear forced-off grace window
        data = self._data
        data.forced_off_until = None
        forced_on_until = data.forced_on_until
        if forced_on_until is not None and time.monotonic() < forced_on_until:
            return True
        return False

    @property
    def brightness(self) -> int | None:
        data = self.coordinator.data or {}
        brightness = data.get("brightness")
        if brightness is None:
            return self._data.last_brightness
        return int(brightness)

    async def async_turn_on(self, **kwargs: Any) -> None:
        data = self._data
        api = data.api
        brightness = kwargs.get(ATTR_BRIGHTNESS)

        await api.set_switch_state(1)

        # Optimistic UI update: mark on immediately
        coord_data = self.coordinator.data or {}
        optimistic = dict(coord_data)
        optimistic["switch_state"] = 1
        self.coordinator.async_set_updated_data(optimistic)
        # Grace window to keep UI on while controller catches up
        data.forced_on_until = time.monotonic() + FORCED_ON_GRACE_SECONDS
        data.forced_off_until = None

        if brightness is not None:
            data.last_brightness = int(brightness)
            await apply_effect_update(
                api, data, self.coordinator.data or {}, brightness=int(brightness)
            )

        self._schedule_verification_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        data = self._data
        api = data.api
        await api.set_switch_state(0)
        coord_data = self.coordinator.data or {}
        optimistic = dict(coord_data)
        optimistic["switch_state"] = 0
        optimistic["current_effect"] = {}
        optimistic["current_effect_id"] = None
        optimistic["current_effect_category"] = None
        self.coordinator.async_set_updated_data(optimistic)
        # Grace window to keep UI off while controller catches up
        data.forced_off_until = time.monotonic() + FORCED_ON_GRACE_SECONDS
        data.forced_on_until = None
        # Clear last-selected preset context when lights turn off
        data.last_selected_preset = None
        data.last_selected_custom_preset = None
        data.last_selected_custom_mode = None
        self._schedule_verification_refresh()
