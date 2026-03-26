from __future__ import annotations

from typing import Any

from .api import TrimlightApi
from .data import TrimlightData
from .debug import async_log_event
from .effects import (
    find_builtin_preset,
    find_custom_preset_by_id,
    find_custom_preset_by_name,
    find_custom_preset_by_state,
    get_effect_mode,
    infer_builtin_preview_params,
)


def _optimistically_apply_effect_update(
    data: TrimlightData,
    coordinator_data: dict[str, Any],
    effect: dict[str, Any],
    *,
    effect_id: int | None,
    brightness: int,
    speed: int,
) -> None:
    updated = dict(coordinator_data or {})
    current = dict(updated.get("current_effect") or {})
    current.update(effect)
    current["brightness"] = int(brightness)
    current["speed"] = int(speed)
    updated["current_effect"] = current
    updated["brightness"] = int(brightness)
    updated["current_effect_category"] = current.get("category", updated.get("current_effect_category"))
    updated["current_effect_id"] = effect_id if effect_id is not None else updated.get("current_effect_id")
    data.coordinator.async_set_updated_data(updated)


async def apply_effect_update(
    api: TrimlightApi,
    data: TrimlightData,
    coordinator_data: dict[str, Any],
    *,
    brightness: int | None = None,
    speed: int | None = None,
) -> None:
    brightness = data.last_brightness if brightness is None else int(brightness)
    speed = data.last_speed if speed is None else int(speed)

    current_effect = (coordinator_data or {}).get("current_effect") or {}
    effect_id = (coordinator_data or {}).get("current_effect_id")
    category = (coordinator_data or {}).get("current_effect_category")

    if category in (1, 2):
        presets = (coordinator_data.get("custom_effects") or data.custom_cache)
        match = None
        matched_via = None
        pending = data.pending_transition
        if pending is not None and pending.target_kind == "custom" and pending.target_id is not None:
            match = find_custom_preset_by_id(presets, pending.target_id)
            if match is not None:
                matched_via = "pending_transition"
        if (
            match is None
            and data.last_selected_custom_preset
            and data.last_selected_preset == data.last_selected_custom_preset
        ):
            match = find_custom_preset_by_name(presets, data.last_selected_custom_preset)
            if match is not None:
                matched_via = "last_selected_custom_preset"
        if (
            match is None
            and data.last_known_custom_preset
            and data.last_known_preset == data.last_known_custom_preset
        ):
            match = find_custom_preset_by_name(presets, data.last_known_custom_preset)
            if match is not None:
                matched_via = "last_known_custom_preset"
        if match is None:
            match = find_custom_preset_by_id(presets, effect_id)
            if match is not None:
                matched_via = "effect_id"
        if match is None:
            match = find_custom_preset_by_state(presets, current_effect, effect_id)
            if match is not None:
                matched_via = "current_state"

        if match:
            response = await api.preview_effect(match, brightness, speed=speed)
            if response.get("code") == 0:
                effect_name = (match.get("name") or "").strip()
                if effect_name:
                    data.last_selected_preset = effect_name
                    data.last_selected_custom_preset = effect_name
                    data.last_known_preset = effect_name
                    data.last_known_custom_preset = effect_name
                mode = get_effect_mode(match)
                if mode is not None:
                    data.last_selected_custom_mode = mode
                if match.get("pixels") is not None:
                    data.last_known_custom_pixels = match.get("pixels")
                _optimistically_apply_effect_update(
                    data,
                    coordinator_data,
                    dict(match),
                    effect_id=int(match.get("id")) if match.get("id") is not None else effect_id,
                    brightness=brightness,
                    speed=speed,
                )
            await async_log_event(
                data.coordinator.hass,
                data,
                "effect_update_preview_custom",
                coordinator_data=coordinator_data,
                effect_id=effect_id,
                matched_effect_id=match.get("id"),
                matched_via=matched_via,
                requested_brightness=brightness,
                requested_speed=speed,
                response=response,
            )
            return

    if current_effect:
        response = await api.preview_effect(current_effect, brightness, speed=speed)
        if response.get("code") == 0:
            _optimistically_apply_effect_update(
                data,
                coordinator_data,
                dict(current_effect),
                effect_id=effect_id,
                brightness=brightness,
                speed=speed,
            )
        await async_log_event(
            data.coordinator.hass,
            data,
            "effect_update_preview_current",
            coordinator_data=coordinator_data,
            requested_brightness=brightness,
            requested_speed=speed,
            response=response,
        )
        return

    if effect_id is None or category is None:
        await async_log_event(
            data.coordinator.hass,
            data,
            "effect_update_skipped",
            coordinator_data=coordinator_data,
            reason="missing_effect_id_or_category",
            requested_brightness=brightness,
            requested_speed=speed,
        )
        return

    if category in (1, 2):
        presets = (coordinator_data.get("custom_effects") or data.custom_cache)
        match = find_custom_preset_by_id(presets, effect_id)
        if match:
            response = await api.preview_effect(match, brightness, speed=speed)
            await async_log_event(
                data.coordinator.hass,
                data,
                "effect_update_preview_custom",
                coordinator_data=coordinator_data,
                effect_id=effect_id,
                requested_brightness=brightness,
                requested_speed=speed,
                response=response,
            )
        else:
            await async_log_event(
                data.coordinator.hass,
                data,
                "effect_update_skipped",
                coordinator_data=coordinator_data,
                reason="custom_effect_not_found",
                effect_id=effect_id,
                requested_brightness=brightness,
                requested_speed=speed,
            )
        return

    if category == 0:
        match = find_builtin_preset(data.builtins, effect_id, get_effect_mode(current_effect))
        if not match:
            await async_log_event(
                data.coordinator.hass,
                data,
                "effect_update_skipped",
                coordinator_data=coordinator_data,
                reason="builtin_effect_not_found",
                effect_id=effect_id,
                requested_brightness=brightness,
                requested_speed=speed,
            )
            return
        effects = coordinator_data.get("effects") or []
        pixel_len, reverse = infer_builtin_preview_params(effect_id, current_effect, effects)
        response = await api.preview_builtin(
            match.get("mode", match.get("id")),
            brightness=brightness,
            speed=speed,
            pixel_len=pixel_len,
            reverse=reverse,
        )
        if response.get("code") == 0:
            builtin_effect = {
                "category": 0,
                "mode": match.get("mode", match.get("id")),
                "speed": speed,
                "brightness": brightness,
                "pixelLen": pixel_len,
                "reverse": reverse,
            }
            _optimistically_apply_effect_update(
                data,
                coordinator_data,
                builtin_effect,
                effect_id=effect_id,
                brightness=brightness,
                speed=speed,
            )
        await async_log_event(
            data.coordinator.hass,
            data,
            "effect_update_preview_builtin",
            coordinator_data=coordinator_data,
            effect_id=effect_id,
            requested_brightness=brightness,
            requested_speed=speed,
            pixel_len=pixel_len,
            reverse=reverse,
            response=response,
        )
