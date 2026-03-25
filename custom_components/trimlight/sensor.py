from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .data import get_data
from .entity import TrimlightEntity
from .effects import (
    find_builtin_preset,
    find_builtin_preset_by_name,
    find_custom_preset_by_state,
    get_effect_mode,
    is_builtin_like_state,
    matches_builtin_target,
    matches_custom_target,
)


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

    @staticmethod
    def _safe_int(value: object, default: int | None = None) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @property
    def native_value(self) -> str:
        data = self.coordinator.data or {}
        is_on = self._is_effectively_on()
        if is_on is not True:
            return "Off"

        current_effect = data.get("current_effect") or {}
        effect_id = self._safe_int(data.get("current_effect_id"))
        current_category = data.get("current_effect_category")
        current_mode = get_effect_mode(current_effect)

        runtime = self._data
        presets = (data.get("custom_effects") or runtime.custom_cache)
        builtins = runtime.builtins
        pending = self._active_pending_transition()

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

        if pending is not None:
            if pending.target_kind == "custom":
                if matches_custom_target(
                    presets,
                    current_effect,
                    current_category,
                    effect_id,
                    target_name=pending.target_name,
                    target_id=pending.target_id,
                    builtins=builtins,
                ):
                    if self._keep_pending_transition_visible_after_match(pending):
                        return pending.target_name
                else:
                    return pending.target_name
            elif pending.target_kind == "builtin":
                if matches_builtin_target(
                    builtins,
                    current_effect,
                    current_category,
                    effect_id,
                    target_name=pending.target_name,
                    target_id=pending.target_id,
                    target_mode=pending.target_mode,
                ):
                    if self._keep_pending_transition_visible_after_match(pending):
                        return pending.target_name
                else:
                    return pending.target_name

        current_name = (current_effect.get("name") or "").strip()
        if current_name:
            return current_name

        if forced_on_override:
            if _valid_state(custom_state.state if custom_state else None):
                return custom_state.state
            if _valid_state(builtin_state.state if builtin_state else None):
                return builtin_state.state
            if _valid_state(runtime.last_selected_preset):
                return runtime.last_selected_preset
            if _valid_state(runtime.last_known_preset):
                return runtime.last_known_preset

        builtin_name_match = find_builtin_preset_by_name(builtins, current_name)
        builtin_like = is_builtin_like_state(builtins, current_effect, current_category, effect_id)

        # Prefer custom preset only when the controller state still looks custom.
        if current_category in (1, 2) and not builtin_like:
            match = find_custom_preset_by_state(presets, current_effect, effect_id)
            if match is not None:
                return (match.get("name") or "").strip() or "(no name)"
            # If preview (id = -1) or no match, fall through to UI/state fallback
            # to avoid mislabeling as a built-in.
        elif current_category == 0 or builtin_like:
            # Built-in preset
            match = builtin_name_match or find_builtin_preset(builtins, effect_id, current_mode)
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
        effect_id = self._safe_int(data.get("current_effect_id"))
        current_category = data.get("current_effect_category")
        runtime = self._data
        presets = (data.get("custom_effects") or runtime.custom_cache)
        custom_state = self._hass.states.get("select.trimlight_custom_preset")
        builtins = runtime.builtins
        pending = self._active_pending_transition()

        def _valid_state(value: str | None) -> bool:
            if value is None:
                return False
            return value not in {"unknown", "unavailable", "none", ""}

        def _find_custom_effect_by_target(target_id: int | None, target_name: str | None) -> dict | None:
            if target_id is not None:
                match = next((e for e in presets if self._safe_int(e.get("id")) == target_id), None)
                if match is not None:
                    return match
            if target_name:
                return next((e for e in presets if (e.get("name") or "").strip() == target_name), None)
            return None

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

        if pending is not None:
            if pending.target_kind == "custom":
                if matches_custom_target(
                    presets,
                    current_effect,
                    current_category,
                    effect_id,
                    target_name=pending.target_name,
                    target_id=pending.target_id,
                    builtins=builtins,
                ):
                    if self._keep_pending_transition_visible_after_match(pending):
                        pending_effect = _find_custom_effect_by_target(pending.target_id, pending.target_name)
                        if pending_effect is not None:
                            resolved_custom_effect = pending_effect
                            resolved_effect_id = self._safe_int(pending_effect.get("id"))
                            current_category = 2
                            mode = get_effect_mode(pending_effect)
                else:
                    pending_effect = _find_custom_effect_by_target(pending.target_id, pending.target_name)
                    if pending_effect is not None:
                        resolved_custom_effect = pending_effect
                        resolved_effect_id = self._safe_int(pending_effect.get("id"))
                        current_category = 2
                        mode = get_effect_mode(pending_effect)
            elif pending.target_kind == "builtin":
                if matches_builtin_target(
                    builtins,
                    current_effect,
                    current_category,
                    effect_id,
                    target_name=pending.target_name,
                    target_id=pending.target_id,
                    target_mode=pending.target_mode,
                ):
                    self._keep_pending_transition_visible_after_match(pending)

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
