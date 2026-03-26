from __future__ import annotations

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

    @property
    def native_value(self) -> float | None:
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
        self._cancel_pending_followups()
        await apply_effect_update(api, data, self.coordinator.data or {}, speed=speed)
        await async_log_event(
            self._hass,
            data,
            "effect_speed_set",
            coordinator_data=self.coordinator.data or {},
            requested_percent=float(value),
            device_speed=speed,
        )

        self._schedule_verification_refresh()
