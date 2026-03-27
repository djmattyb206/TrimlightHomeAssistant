from __future__ import annotations

import asyncio
import time

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .controller import apply_effect_update
from .data import get_data
from .debug import async_log_event
from .entity import TrimlightEntity
from .effects import (
    find_builtin_preset,
    find_builtin_preset_by_name,
    find_custom_preset_by_id,
    find_custom_preset_by_name,
    find_custom_preset_by_state,
    get_effect_mode,
    is_builtin_like_state,
)

_CUSTOM_SPEED_SECOND_APPLY_DELAY_SECONDS = 0.9
_CUSTOM_SPEED_REAPPLY_DELAY_SECONDS = 4.5
_CUSTOM_SPEED_REAPPLY_VERIFY_DELAY_SECONDS = 4.0
_PENDING_SPEED_HOLD_SECONDS = 12.0
_SPEED_UPDATE_PENDING_EXPIRY_SECONDS = 15.0


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data = get_data(hass, entry.entry_id)
    coordinator = data.coordinator
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

    @staticmethod
    def _safe_int(value: object, default: int | None = None) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _prime_pending_transition_for_speed_update(self) -> None:
        runtime = self._data
        pending = self._active_pending_transition()
        if pending is not None:
            self._set_pending_transition(
                target_kind=pending.target_kind,
                target_name=pending.target_name,
                target_id=pending.target_id,
                target_mode=pending.target_mode,
                source_kind=pending.source_kind,
                correlation_id=pending.correlation_id,
                expires_in_s=_SPEED_UPDATE_PENDING_EXPIRY_SECONDS,
                attempt=pending.attempt,
            )
            return

        data = self.coordinator.data or {}
        current_effect = data.get("current_effect") or {}
        current_category = self._safe_int(data.get("current_effect_category"))
        effect_id = self._safe_int(data.get("current_effect_id"))
        builtins = runtime.builtins
        custom_presets = data.get("custom_effects") or runtime.custom_cache

        # Built-in speed changes can trigger a stale refresh that briefly looks like
        # the last known custom preset. When we know the last active selection was a
        # built-in, keep following that target instead of pivoting into the custom
        # fallback path mid-transition.
        builtin_hint_names: list[str] = []
        if runtime.last_selected_custom_preset is None:
            if runtime.last_selected_preset:
                builtin_hint_names.append(runtime.last_selected_preset)
            if runtime.last_known_builtin_preset:
                builtin_hint_names.append(runtime.last_known_builtin_preset)

        for builtin_name in builtin_hint_names:
            builtin_match = find_builtin_preset_by_name(builtins, builtin_name)
            if builtin_match is None:
                continue
            builtin_name = (builtin_match.get("name") or "").strip()
            builtin_id = self._safe_int(builtin_match.get("id"))
            builtin_mode = self._safe_int(builtin_match.get("mode"))
            self._set_pending_transition(
                target_kind="builtin",
                target_name=builtin_name,
                target_id=builtin_id,
                target_mode=builtin_mode,
                source_kind="builtin",
                correlation_id="speed_update",
                expires_in_s=_SPEED_UPDATE_PENDING_EXPIRY_SECONDS,
            )
            return

        if not is_builtin_like_state(builtins, current_effect, current_category, effect_id):
            custom_match = None
            if effect_id is not None:
                custom_match = find_custom_preset_by_id(custom_presets, effect_id)
            if custom_match is None:
                custom_match = find_custom_preset_by_name(
                    custom_presets,
                    runtime.last_selected_custom_preset or runtime.last_known_custom_preset,
                )
            if custom_match is None:
                custom_match = find_custom_preset_by_state(custom_presets, current_effect, effect_id)
            if custom_match is not None:
                custom_name = runtime.last_selected_custom_preset or (custom_match.get("name") or "").strip()
                custom_id = self._safe_int(custom_match.get("id"))
                custom_mode = get_effect_mode(custom_match)
                self._set_pending_transition(
                    target_kind="custom",
                    target_name=custom_name,
                    target_id=custom_id,
                    target_mode=custom_mode,
                    source_kind="custom",
                    correlation_id="speed_update",
                    expires_in_s=_SPEED_UPDATE_PENDING_EXPIRY_SECONDS,
                )
                return

        builtin_match = find_builtin_preset_by_name(
            builtins, (current_effect.get("name") or "").strip()
        )
        if builtin_match is None:
            builtin_match = find_builtin_preset(builtins, effect_id, get_effect_mode(current_effect))
        if builtin_match is not None:
            builtin_name = (builtin_match.get("name") or "").strip()
            builtin_id = self._safe_int(builtin_match.get("id"))
            builtin_mode = self._safe_int(builtin_match.get("mode"))
            self._set_pending_transition(
                target_kind="builtin",
                target_name=builtin_name,
                target_id=builtin_id,
                target_mode=builtin_mode,
                source_kind="builtin",
                correlation_id="speed_update",
                expires_in_s=_SPEED_UPDATE_PENDING_EXPIRY_SECONDS,
            )

    def _set_pending_speed(self, speed: int) -> None:
        data = self._data
        data.pending_speed = int(speed)
        data.pending_speed_until = time.monotonic() + _PENDING_SPEED_HOLD_SECONDS

    def _clear_pending_speed(self) -> None:
        data = self._data
        data.pending_speed = None
        data.pending_speed_until = None

    def _active_pending_speed(self) -> int | None:
        data = self._data
        pending_speed = data.pending_speed
        pending_until = data.pending_speed_until
        if pending_speed is None or pending_until is None:
            return None
        if time.monotonic() >= pending_until:
            self._clear_pending_speed()
            return None
        return int(pending_speed)

    def _schedule_custom_speed_reapply_if_needed(
        self,
        *,
        requested_percent: float,
        device_speed: int,
        target_name: str | None,
        target_id: int | None,
        delay_s: float = _CUSTOM_SPEED_REAPPLY_DELAY_SECONDS,
    ) -> None:
        data = self._data
        handle = data.speed_reapply_handle
        if handle is not None:
            handle.cancel()

        async def _reapply_if_needed() -> None:
            runtime = self._data
            if runtime.last_speed != int(device_speed):
                return

            pending = self._active_pending_transition()
            if pending is not None and pending.target_kind != "custom":
                return
            if pending is not None:
                if target_name is not None and pending.target_name != target_name:
                    return
                if target_id is not None and pending.target_id not in (None, target_id):
                    return

            current = self.coordinator.data or {}
            current_effect = current.get("current_effect") or {}
            current_speed = self._safe_int(current_effect.get("speed"))
            if current_speed == int(device_speed):
                return

            await async_log_event(
                self._hass,
                runtime,
                "effect_speed_reapply_requested",
                coordinator_data=current,
                requested_percent=float(requested_percent),
                device_speed=int(device_speed),
                target_name=target_name,
                target_id=target_id,
                current_speed=current_speed,
            )
            await apply_effect_update(runtime.api, runtime, current, speed=int(device_speed))
            await async_log_event(
                self._hass,
                runtime,
                "effect_speed_reapply_result",
                coordinator_data=self.coordinator.data or {},
                requested_percent=float(requested_percent),
                device_speed=int(device_speed),
                target_name=target_name,
                target_id=target_id,
            )
            self._schedule_verification_refresh(
                source="effect_speed_reapply",
                delay_s=_CUSTOM_SPEED_REAPPLY_VERIFY_DELAY_SECONDS,
            )

        def _start_reapply() -> None:
            self._hass.async_create_task(_reapply_if_needed())

        data.speed_reapply_handle = self._hass.loop.call_later(delay_s, _start_reapply)

    @property
    def native_value(self) -> float | None:
        pending_speed = self._active_pending_speed()
        if pending_speed is not None and self._active_pending_transition() is not None:
            return round((float(pending_speed) / 255.0) * 100.0, 1)
        data = self.coordinator.data or {}
        speed = (data.get("current_effect") or {}).get("speed")
        if speed is None:
            speed = self._data.last_speed
        return round((float(speed) / 255.0) * 100.0, 1)

    async def async_set_native_value(self, value: float) -> None:
        speed = int(round((float(value) / 100.0) * 255.0))
        data = self._data
        api = data.api
        data.last_speed = speed

        self._prime_pending_transition_for_speed_update()
        self._set_pending_speed(speed)
        self._cancel_pending_followups()
        await apply_effect_update(api, data, self.coordinator.data or {}, speed=speed)
        pending = self._active_pending_transition()
        if pending is not None and pending.target_kind == "custom":
            await asyncio.sleep(_CUSTOM_SPEED_SECOND_APPLY_DELAY_SECONDS)
            refreshed_pending = self._active_pending_transition()
            if (
                refreshed_pending is not None
                and refreshed_pending.target_kind == "custom"
                and refreshed_pending.target_name == pending.target_name
                and refreshed_pending.target_id == pending.target_id
            ):
                await apply_effect_update(api, data, self.coordinator.data or {}, speed=speed)
                await async_log_event(
                    self._hass,
                    data,
                    "effect_speed_second_apply",
                    coordinator_data=self.coordinator.data or {},
                    requested_percent=float(value),
                    device_speed=speed,
                    target_name=refreshed_pending.target_name,
                    target_id=refreshed_pending.target_id,
                )
                self._schedule_custom_speed_reapply_if_needed(
                    requested_percent=float(value),
                    device_speed=speed,
                    target_name=refreshed_pending.target_name,
                    target_id=refreshed_pending.target_id,
                )
        await async_log_event(
            self._hass,
            data,
            "effect_speed_set",
            coordinator_data=self.coordinator.data or {},
            requested_percent=float(value),
            device_speed=speed,
        )

        self._schedule_verification_refresh()
