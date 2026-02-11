from __future__ import annotations

from typing import Any

from .api import TrimlightApi
from .data import TrimlightData
from .effects import (
    find_builtin_preset,
    find_custom_preset_by_id,
    get_effect_mode,
    infer_builtin_preview_params,
)


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
    if current_effect:
        await api.preview_effect(current_effect, brightness, speed=speed)
        return

    effect_id = (coordinator_data or {}).get("current_effect_id")
    category = (coordinator_data or {}).get("current_effect_category")
    if effect_id is None or category is None:
        return

    if category in (1, 2):
        presets = (coordinator_data.get("custom_effects") or data.custom_cache)
        match = find_custom_preset_by_id(presets, effect_id)
        if match:
            await api.preview_effect(match, brightness, speed=speed)
        return

    if category == 0:
        match = find_builtin_preset(data.builtins, effect_id, get_effect_mode(current_effect))
        if not match:
            return
        effects = coordinator_data.get("effects") or []
        pixel_len, reverse = infer_builtin_preview_params(effect_id, current_effect, effects)
        await api.preview_builtin(
            match.get("mode", match.get("id")),
            brightness=brightness,
            speed=speed,
            pixel_len=pixel_len,
            reverse=reverse,
        )
