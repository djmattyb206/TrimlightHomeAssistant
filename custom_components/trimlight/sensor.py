from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .data import get_data
from .entity import TrimlightEntity
from .effects import get_effect_mode


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data = get_data(hass, entry.entry_id)
    coordinator = data.coordinator
    async_add_entities([TrimlightCurrentPresetSensor(hass, entry.entry_id, coordinator)])


class TrimlightCurrentPresetSensor(TrimlightEntity, SensorEntity):
    _attr_name = "Trimlight Current Preset"

    def __init__(self, hass: HomeAssistant, entry_id: str, coordinator) -> None:
        super().__init__(hass, entry_id, coordinator)
        self._attr_unique_id = f"{entry_id}_current_preset"

    @property
    def native_value(self) -> str:
        data = self.coordinator.data or {}
        switch_state = data.get("switch_state")
        if switch_state is None or int(switch_state) == 0:
            return "Off"

        current_effect = data.get("current_effect") or {}
        current_name = (current_effect.get("name") or "").strip()
        if current_name:
            return current_name

        effect_id = data.get("current_effect_id")
        current_category = data.get("current_effect_category")
        current_mode = get_effect_mode(current_effect)

        runtime = self._data
        presets = (data.get("custom_effects") or runtime.custom_cache)
        builtins = runtime.builtins

        # Prefer custom preset if currently active (category 1/2)
        if current_category in (1, 2):
            for e in presets:
                if e.get("id") == effect_id:
                    return (e.get("name") or "").strip() or "(no name)"
            # If preview (id = -1) or no match, fall through to UI/state fallback
            # to avoid mislabeling as a built-in.
        elif current_category == 0:
            # Built-in preset
            for b in builtins:
                if b.get("id") == effect_id or b.get("mode") == effect_id or b.get("mode") == current_mode:
                    return b.get("name")
        else:
            # Category missing: try to infer by id first (custom preferred)
            if effect_id not in (None, -1):
                for e in presets:
                    if e.get("id") == effect_id:
                        return (e.get("name") or "").strip() or "(no name)"
                for b in builtins:
                    if b.get("id") == effect_id:
                        return b.get("name")
            # If mode > 16, it's definitely built-in
            if current_mode is not None and int(current_mode) > 16:
                for b in builtins:
                    if b.get("mode") == current_mode:
                        return b.get("name")

        # Final fallback: use HA state of the select entities (if available)
        def _valid_state(value: str | None) -> bool:
            if value is None:
                return False
            return value not in {"unknown", "unavailable", "none", ""}

        custom_state = self._hass.states.get("select.trimlight_custom_preset")
        if _valid_state(custom_state.state if custom_state else None):
            return custom_state.state

        builtin_state = self._hass.states.get("select.trimlight_built_in_preset")
        if _valid_state(builtin_state.state if builtin_state else None):
            return builtin_state.state

        last_selected = runtime.last_selected_preset
        if _valid_state(last_selected):
            return last_selected

        last_known = runtime.last_known_preset
        if _valid_state(last_known):
            return last_known

        return "Unknown"

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data or {}
        current_effect = data.get("current_effect") or {}
        mode = get_effect_mode(current_effect)

        pixels = current_effect.get("pixels")
        if not pixels:
            pixels = self._data.last_known_custom_pixels
        else:
            # If controller returns an empty/disabled pixel map, fall back to last known pixels.
            has_data = any(
                (p.get("count", 0) or 0) > 0 or (p.get("color", 0) or 0) != 0 for p in pixels
            )
            if not has_data:
                pixels = self._data.last_known_custom_pixels or pixels

        return {
            "current_effect_id": data.get("current_effect_id"),
            "current_effect_category": data.get("current_effect_category"),
            "current_effect_mode": mode,
            "current_effect_speed": current_effect.get("speed"),
            "current_effect_brightness": current_effect.get("brightness"),
            "current_effect_pixel_len": current_effect.get("pixelLen"),
            "current_effect_reverse": current_effect.get("reverse"),
            "current_effect_pixels": pixels,
        }
