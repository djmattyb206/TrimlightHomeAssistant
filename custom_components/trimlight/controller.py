from __future__ import annotations

import asyncio
from typing import Any

from .api import TrimlightApi
from .data import TrimlightData
from .debug import async_log_event
from .effects import (
    find_builtin_preset,
    find_builtin_preset_by_name,
    find_custom_preset_by_id,
    find_custom_preset_by_name,
    find_custom_preset_by_state,
    get_effect_mode,
    infer_builtin_preview_params,
)

_CUSTOM_EFFECT_UPDATE_SECOND_RUN_DELAY_SECONDS = 0.9


def _update_custom_preset_cache(
    data: TrimlightData,
    coordinator_data: dict[str, Any],
    effect: dict[str, Any],
) -> None:
    effect_id = effect.get("id")
    if effect_id is None:
        return

    updated_effect = dict(effect)
    replaced = False
    new_cache: list[dict[str, Any]] = []
    for row in data.custom_cache:
        if row.get("id") == effect_id:
            new_cache.append(updated_effect)
            replaced = True
        else:
            new_cache.append(row)
    if replaced:
        data.custom_cache = new_cache

    custom_effects = coordinator_data.get("custom_effects")
    if isinstance(custom_effects, list):
        updated_rows: list[dict[str, Any]] = []
        for row in custom_effects:
            if isinstance(row, dict) and row.get("id") == effect_id:
                updated_rows.append(updated_effect)
            else:
                updated_rows.append(row)
        coordinator_data["custom_effects"] = updated_rows


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
    effects = coordinator_data.get("effects") or []

    async def _apply_builtin_match(
        match: dict[str, Any],
        *,
        matched_via: str | None = None,
    ) -> None:
        builtin_effect_id = (
            int(match.get("id")) if match.get("id") is not None else effect_id
        )
        pixel_len, reverse = infer_builtin_preview_params(
            builtin_effect_id or 0, current_effect, effects
        )
        response = await api.preview_builtin(
            match.get("mode", match.get("id")),
            brightness=brightness,
            speed=speed,
            pixel_len=pixel_len,
            reverse=reverse,
        )
        if response.get("code") == 0:
            effect_name = (match.get("name") or "").strip()
            if effect_name:
                data.last_selected_preset = effect_name
                data.last_selected_custom_preset = None
                data.last_known_preset = effect_name
                data.last_known_builtin_preset = effect_name
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
                effect_id=builtin_effect_id,
                brightness=brightness,
                speed=speed,
            )
        await async_log_event(
            data.coordinator.hass,
            data,
            "effect_update_preview_builtin",
            coordinator_data=coordinator_data,
            effect_id=builtin_effect_id,
            matched_via=matched_via,
            requested_brightness=brightness,
            requested_speed=speed,
            pixel_len=pixel_len,
            reverse=reverse,
            response=response,
        )

    preferred_builtin = None
    preferred_builtin_via = None
    pending = data.pending_transition
    if pending is not None and pending.target_kind == "builtin":
        preferred_builtin = find_builtin_preset(
            data.builtins, pending.target_id, pending.target_mode
        )
        if preferred_builtin is None:
            preferred_builtin = find_builtin_preset_by_name(
                data.builtins, pending.target_name
            )
        if preferred_builtin is not None:
            preferred_builtin_via = "pending_transition"

    if preferred_builtin is None and data.last_selected_custom_preset is None:
        preferred_builtin = find_builtin_preset_by_name(
            data.builtins, data.last_selected_preset
        )
        if preferred_builtin is not None:
            preferred_builtin_via = "last_selected_preset"

    if (
        preferred_builtin is None
        and data.last_selected_custom_preset is None
        and data.last_known_preset == data.last_known_builtin_preset
    ):
        preferred_builtin = find_builtin_preset_by_name(
            data.builtins, data.last_known_builtin_preset
        )
        if preferred_builtin is not None:
            preferred_builtin_via = "last_known_builtin_preset"

    if preferred_builtin is not None and category in (1, 2):
        await _apply_builtin_match(preferred_builtin, matched_via=preferred_builtin_via)
        return

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
            updated_match = dict(match)
            updated_match["brightness"] = int(brightness)
            updated_match["speed"] = int(speed)

            response: dict[str, Any]
            run_response: dict[str, Any] | None = None
            second_run_response: dict[str, Any] | None = None
            committed = False
            effect_match_id = int(match.get("id")) if match.get("id") is not None else effect_id

            if data.commit_custom_preset and effect_match_id is not None:
                response = await api.save_effect(updated_match, brightness, speed=speed)
                if response.get("code") == 0:
                    committed = True
                    run_response = await api.run_effect(effect_match_id)
                    if run_response.get("code") != 0:
                        response = dict(response)
                        response["_run_effect_response"] = run_response
                    else:
                        should_second_run = True
                        pending = data.pending_transition
                        if (
                            pending is not None
                            and pending.target_kind == "custom"
                            and pending.target_id not in (None, effect_match_id)
                        ):
                            should_second_run = False
                        latest_selected = find_custom_preset_by_name(
                            presets, data.last_selected_custom_preset
                        )
                        latest_selected_id = (
                            int(latest_selected.get("id"))
                            if latest_selected is not None and latest_selected.get("id") is not None
                            else None
                        )
                        if latest_selected_id not in (None, effect_match_id):
                            should_second_run = False
                        if should_second_run:
                            await asyncio.sleep(_CUSTOM_EFFECT_UPDATE_SECOND_RUN_DELAY_SECONDS)
                            second_run_response = await api.run_effect(effect_match_id)
                            if second_run_response.get("code") != 0:
                                response = dict(response)
                                response["_second_run_effect_response"] = second_run_response
            else:
                response = await api.preview_effect(updated_match, brightness, speed=speed)

            if response.get("code") == 0 and (run_response is None or run_response.get("code") == 0):
                effect_name = (match.get("name") or "").strip()
                if effect_name:
                    data.last_selected_preset = effect_name
                    data.last_selected_custom_preset = effect_name
                    data.last_known_preset = effect_name
                    data.last_known_custom_preset = effect_name
                mode = get_effect_mode(match)
                if mode is not None:
                    data.last_selected_custom_mode = mode
                if updated_match.get("pixels") is not None:
                    data.last_known_custom_pixels = updated_match.get("pixels")
                if committed:
                    _update_custom_preset_cache(data, coordinator_data, updated_match)
                _optimistically_apply_effect_update(
                    data,
                    coordinator_data,
                    updated_match,
                    effect_id=effect_match_id,
                    brightness=brightness,
                    speed=speed,
                )
            event_name = "effect_update_save_custom" if committed else "effect_update_preview_custom"
            await async_log_event(
                data.coordinator.hass,
                data,
                event_name,
                coordinator_data=coordinator_data,
                effect_id=effect_id,
                matched_effect_id=match.get("id"),
                matched_via=matched_via,
                requested_brightness=brightness,
                requested_speed=speed,
                response=response,
                run_response=run_response,
                second_run_response=second_run_response,
                committed=committed,
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
        await _apply_builtin_match(match, matched_via="current_state")
