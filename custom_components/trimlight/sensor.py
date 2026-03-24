from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .data import get_data
from .entity import TrimlightEntity
from .effects import find_builtin_preset, find_custom_preset_by_state, get_effect_mode


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
        is_on = self._is_effectively_on()
        if is_on is not True:
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

        def _valid_state(value: str | None) -> bool:
            if value is None:
                return False
            return value not in {"unknown", "unavailable", "none", ""}

        custom_state = self._hass.states.get("select.trimlight_custom_preset")
        builtin_state = self._hass.states.get("select.trimlight_built_in_preset")
        raw_switch_state = data.get("switch_state")
        forced_on_override = (
            raw_switch_state is not None and int(raw_switch_state) == 0 and is_on is True
        )

        if forced_on_override:
            if _valid_state(custom_state.state if custom_state else None):
                return custom_state.state
            if _valid_state(builtin_state.state if builtin_state else None):
                return builtin_state.state
            if _valid_state(runtime.last_selected_preset):
                return runtime.last_selected_preset
            if _valid_state(runtime.last_known_preset):
                return runtime.last_known_preset

        # Prefer custom preset if currently active (category 1/2)
        if current_category in (1, 2):
            match = find_custom_preset_by_state(presets, current_effect, effect_id)
            if match is not None:
                return (match.get("name") or "").strip() or "(no name)"
            # If preview (id = -1) or no match, fall through to UI/state fallback
            # to avoid mislabeling as a built-in.
        elif current_category == 0:
            # Built-in preset
            match = find_builtin_preset(builtins, effect_id, current_mode)
            if match is not None:
                return match.get("name")
        else:
            # Category missing: try to infer by id first (custom preferred)
            custom_match = find_custom_preset_by_state(presets, current_effect, effect_id)
            if custom_match is not None:
                return (custom_match.get("name") or "").strip() or "(no name)"
            builtin_match = find_builtin_preset(builtins, effect_id, current_mode)
            if builtin_match is not None:
                return builtin_match.get("name")
            # If mode > 16, it's definitely built-in
            if current_mode is not None and int(current_mode) > 16:
                builtin_match = find_builtin_preset(builtins, effect_id, current_mode)
                if builtin_match is not None:
                    return builtin_match.get("name")

        # Final fallback: use HA state of the select entities (if available)
        if _valid_state(custom_state.state if custom_state else None):
            return custom_state.state

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
        effect_id = data.get("current_effect_id")
        current_category = data.get("current_effect_category")
        runtime = self._data
        presets = (data.get("custom_effects") or runtime.custom_cache)
        custom_state = self._hass.states.get("select.trimlight_custom_preset")

        def _valid_state(value: str | None) -> bool:
            if value is None:
                return False
            return value not in {"unknown", "unavailable", "none", ""}

        raw_switch_state = data.get("switch_state")
        forced_on_override = (
            raw_switch_state is not None and int(raw_switch_state) == 0 and self._is_effectively_on() is True
        )
        resolved_effect_id = effect_id
        resolved_custom_effect = None
        selected_label = None
        if custom_state and _valid_state(custom_state.state):
            selected_label = custom_state.state
        elif _valid_state(runtime.last_selected_custom_preset):
            selected_label = runtime.last_selected_custom_preset
        elif _valid_state(runtime.last_known_custom_preset):
            selected_label = runtime.last_known_custom_preset

        if current_category in (1, 2) and not forced_on_override:
            resolved_custom_effect = find_custom_preset_by_state(presets, current_effect, effect_id)
            if resolved_custom_effect is not None and resolved_custom_effect.get("id") is not None:
                resolved_effect_id = int(resolved_custom_effect.get("id"))

        should_restore_custom = (
            selected_label is not None
            and (
                current_category in (1, 2)
                or (
                    forced_on_override
                    and _valid_state(runtime.last_known_custom_preset)
                    and runtime.last_known_preset == runtime.last_known_custom_preset
                )
            )
        )
        if resolved_custom_effect is None and should_restore_custom:
            option_to_id = (
                custom_state.attributes.get("option_to_id", {}) if custom_state else {}
            )
            name_to_id = (
                custom_state.attributes.get("name_to_id", {}) if custom_state else {}
            )
            matched_id = option_to_id.get(selected_label)
            if matched_id is None:
                matched_id = name_to_id.get(selected_label)
            if matched_id is not None:
                matched_id = int(matched_id)
                resolved_custom_effect = next(
                    (e for e in presets if e.get("id") == matched_id),
                    None,
                )
                if resolved_custom_effect is not None:
                    resolved_effect_id = matched_id
                    current_category = 2

        if resolved_custom_effect is not None:
            mode = get_effect_mode(resolved_custom_effect)

        pixels = None
        if resolved_custom_effect is not None and resolved_custom_effect.get("pixels"):
            pixels = resolved_custom_effect.get("pixels")

        if not pixels:
            pixels = current_effect.get("pixels")
        if not pixels:
            pixels = runtime.last_known_custom_pixels
        else:
            # If controller returns an empty/disabled pixel map, fall back to last known pixels.
            has_data = any(
                (p.get("count", 0) or 0) > 0 or (p.get("color", 0) or 0) != 0 for p in pixels
            )
            if not has_data:
                pixels = runtime.last_known_custom_pixels or pixels

        return {
            "current_effect_id": resolved_effect_id,
            "current_effect_category": current_category,
            "current_effect_mode": mode,
            "current_effect_speed": (
                resolved_custom_effect.get("speed")
                if resolved_custom_effect is not None
                else current_effect.get("speed")
            ),
            "current_effect_brightness": (
                resolved_custom_effect.get("brightness")
                if resolved_custom_effect is not None
                else current_effect.get("brightness")
            ),
            "current_effect_pixel_len": current_effect.get("pixelLen"),
            "current_effect_reverse": current_effect.get("reverse"),
            "current_effect_pixels": pixels,
        }
