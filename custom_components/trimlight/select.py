from __future__ import annotations

import asyncio
from collections import Counter
import logging
import time
import uuid
from typing import Awaitable, Callable

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CUSTOM_EFFECT_MODES, FORCED_ON_GRACE_SECONDS
from .data import get_data
from .debug import async_log_event
from .entity import TrimlightEntity
from .effects import (
    find_builtin_preset,
    find_builtin_preset_by_name,
    find_custom_preset_by_state,
    get_effect_mode,
    infer_builtin_preview_params,
    is_builtin_like_state,
    matches_builtin_target,
    matches_custom_target,
)

_LOGGER = logging.getLogger(__name__)
_CUSTOM_PRESET_API_RETRIES = 1
_CUSTOM_PRESET_RETRY_DELAY_SECONDS = 0.35
_CUSTOM_PRESET_POWER_ON_DELAY_SECONDS = 0.8
_BUILTIN_PRESET_REAPPLY_DELAY_SECONDS = 5.5
_BUILTIN_PRESET_SECOND_REAPPLY_DELAY_SECONDS = 5.5
_BUILTIN_PRESET_REAPPLY_VERIFY_DELAY_SECONDS = 5.0
_CUSTOM_PRESET_VERIFY_DELAY_SECONDS = 12.0
_CUSTOM_PRESET_REAPPLY_DELAY_SECONDS = _CUSTOM_PRESET_VERIFY_DELAY_SECONDS + 0.5
_CUSTOM_PRESET_FROM_BUILTIN_VERIFY_DELAY_SECONDS = 5.0
_CUSTOM_PRESET_FROM_BUILTIN_REAPPLY_DELAY_SECONDS = (
    _CUSTOM_PRESET_FROM_BUILTIN_VERIFY_DELAY_SECONDS + 0.5
)
_CUSTOM_PRESET_REAPPLY_VERIFY_DELAY_SECONDS = 5.0
_PENDING_TRANSITION_EXPIRY_SECONDS = 30.0


def _resp_code(resp: dict | None) -> int | None:
    if not isinstance(resp, dict):
        return None
    code = resp.get("code")
    return int(code) if code is not None else None


def _resp_desc(resp: dict | None) -> str | None:
    if not isinstance(resp, dict):
        return None
    desc = resp.get("desc")
    return str(desc) if desc is not None else None


async def _call_with_retry(
    *,
    action: str,
    correlation_id: str,
    request: Callable[[], Awaitable[dict]],
    retries: int = _CUSTOM_PRESET_API_RETRIES,
    retry_delay_s: float = _CUSTOM_PRESET_RETRY_DELAY_SECONDS,
) -> tuple[bool, dict | None]:
    attempts = retries + 1
    for attempt in range(1, attempts + 1):
        try:
            resp = await request()
        except Exception as exc:  # noqa: BLE001
            if attempt < attempts:
                _LOGGER.warning(
                    "%s failed: cid=%s error=%s attempt=%s/%s retrying",
                    action,
                    correlation_id,
                    exc,
                    attempt,
                    attempts,
                )
                await asyncio.sleep(retry_delay_s)
                continue
            _LOGGER.warning(
                "%s failed: cid=%s error=%s attempt=%s/%s",
                action,
                correlation_id,
                exc,
                attempt,
                attempts,
            )
            return False, None

        code = _resp_code(resp)
        desc = _resp_desc(resp)
        if code not in (None, 0):
            if attempt < attempts:
                _LOGGER.warning(
                    "%s non-success response: cid=%s code=%s desc=%s attempt=%s/%s retrying",
                    action,
                    correlation_id,
                    code,
                    desc,
                    attempt,
                    attempts,
                )
                await asyncio.sleep(retry_delay_s)
                continue
            _LOGGER.warning(
                "%s non-success response: cid=%s code=%s desc=%s attempt=%s/%s",
                action,
                correlation_id,
                code,
                desc,
                attempt,
                attempts,
            )
            return False, resp

        _LOGGER.info(
            "%s response: cid=%s code=%s desc=%s attempt=%s/%s",
            action,
            correlation_id,
            code,
            desc,
            attempt,
            attempts,
        )
        return True, resp

    return False, None


def _infer_transition_source_kind(
    *,
    builtins: list[dict],
    presets: list[dict],
    current_effect: dict,
    current_category: int | None,
    effect_id: int | None,
) -> str | None:
    if is_builtin_like_state(builtins, current_effect, current_category, effect_id):
        return "builtin"
    if current_category in (1, 2):
        return "custom"
    inferred_custom = find_custom_preset_by_state(presets, current_effect, effect_id)
    if inferred_custom is not None:
        return "custom"
    return None


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data = get_data(hass, entry.entry_id)
    coordinator = data.coordinator
    async_add_entities(
        [
            TrimlightBuiltInSelect(hass, entry.entry_id, coordinator),
            TrimlightCustomSelect(hass, entry.entry_id, coordinator),
            TrimlightCustomModeSelect(hass, entry.entry_id, coordinator),
        ]
    )


class TrimlightBuiltInSelect(TrimlightEntity, SelectEntity):
    _attr_name = "Trimlight Built-in Preset"

    def __init__(self, hass: HomeAssistant, entry_id: str, coordinator) -> None:
        super().__init__(hass, entry_id, coordinator)
        self._attr_unique_id = f"{entry_id}_builtin_select"

    @staticmethod
    def _safe_int(value: object, default: int | None = None) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @property
    def options(self) -> list[str]:
        builtins = self._data.builtins
        return [row["name"] for row in builtins]

    @property
    def current_option(self) -> str | None:
        data = self.coordinator.data or {}
        is_on = self._is_effectively_on()
        if is_on is not True:
            return None
        current_effect = data.get("current_effect") or {}
        builtins = self._data.builtins
        current_category = data.get("current_effect_category")
        effect_id = self._safe_int(data.get("current_effect_id"))
        pending = self._active_pending_transition()
        if pending is not None:
            if pending.target_kind == "builtin":
                if matches_builtin_target(
                    builtins,
                    current_effect,
                    current_category,
                    effect_id,
                    target_name=pending.target_name,
                    target_id=pending.target_id,
                    target_mode=pending.target_mode,
                ):
                    self._clear_pending_transition()
                else:
                    return pending.target_name
            elif pending.target_kind == "custom":
                if matches_custom_target(
                    self._data.custom_cache,
                    current_effect,
                    current_category,
                    effect_id,
                    target_name=pending.target_name,
                    target_id=pending.target_id,
                    builtins=builtins,
                ):
                    self._clear_pending_transition()
                else:
                    return None
        name_match = find_builtin_preset_by_name(builtins, (current_effect.get("name") or "").strip())
        if name_match is not None:
            return name_match["name"]
        raw_switch_state = data.get("switch_state")
        forced_on_override = raw_switch_state is not None and int(raw_switch_state) == 0 and is_on is True
        if forced_on_override:
            last_known = self._data.last_known_builtin_preset
            if last_known and self._data.last_known_preset == last_known:
                return last_known
            return None
        current_mode = get_effect_mode(current_effect)
        builtin_like = is_builtin_like_state(builtins, current_effect, current_category, effect_id)
        if current_category != 0 and not builtin_like:
            return None
        match = find_builtin_preset(builtins, effect_id, current_mode)
        if match is not None:
            return match["name"]
        last_known = self._data.last_known_builtin_preset
        if last_known:
            return last_known
        return None

    def _optimistic_builtin_selection(
        self,
        *,
        match: dict,
        selected_mode: int,
        brightness: int,
        speed: int,
    ) -> dict:
        data = self._data
        data.last_selected_preset = match.get("name")
        data.last_known_preset = match.get("name")
        data.last_known_builtin_preset = match.get("name")
        data.last_selected_custom_preset = None
        data.last_selected_custom_mode = None

        current_effect = {
            "id": match.get("id", selected_mode),
            "name": match.get("name"),
            "category": 0,
            "mode": selected_mode,
            "brightness": brightness,
            "speed": speed,
        }
        updated = dict(self.coordinator.data or {})
        updated.update(
            {
                "switch_state": 1,
                "current_effect": current_effect,
                "current_effect_id": current_effect.get("id"),
                "current_effect_category": 0,
                "brightness": brightness,
            }
        )
        self.coordinator.async_set_updated_data(updated)
        return updated

    def _schedule_builtin_reapply_if_needed(
        self,
        *,
        correlation_id: str,
        option: str,
        match: dict,
        selected_mode: int,
        brightness: int,
        speed: int,
        apply_via: str,
        pixel_len: int,
        reverse: bool,
        attempt: int = 1,
        delay_s: float = _BUILTIN_PRESET_REAPPLY_DELAY_SECONDS,
    ) -> None:
        data = self._data
        handle = data.builtin_reapply_handle
        if handle:
            handle.cancel()

        view_effect_id = match.get("id")
        if view_effect_id is None:
            return
        view_effect_id = int(view_effect_id)

        async def _reapply_if_needed() -> None:
            runtime = self._data
            try:
                if runtime.last_known_builtin_preset != option:
                    return

                current = self.coordinator.data or {}
                current_effect = current.get("current_effect") or {}
                current_category = current.get("current_effect_category")
                current_effect_id = self._safe_int(current.get("current_effect_id"))
                current_mode = get_effect_mode(current_effect)
                current_name = (current_effect.get("name") or "").strip()
                current_match = find_builtin_preset_by_name(runtime.builtins, current_name)
                if current_match is None and is_builtin_like_state(
                    runtime.builtins, current_effect, current_category, current_effect_id
                ):
                    current_match = find_builtin_preset(runtime.builtins, current_effect_id, current_mode)
                is_target_builtin = current_match is not None and (
                    current_match.get("name") == option
                    or current_match.get("id") in (view_effect_id, selected_mode)
                    or current_match.get("mode") == selected_mode
                )
                if is_target_builtin:
                    return

                await async_log_event(
                    self._hass,
                    runtime,
                    "builtin_preset_reapply_requested",
                    correlation_id=correlation_id,
                    coordinator_data=current,
                    option=option,
                    effect_id=view_effect_id,
                    current_effect_id=current_effect_id,
                    current_mode=current_mode,
                    current_category=current_category,
                    attempt=attempt,
                )
                if apply_via == "preview_category_1":
                    reapply_ok, reapply_resp = await _call_with_retry(
                        action=f"Builtin preset delayed preview category=1 mode={selected_mode}",
                        correlation_id=correlation_id,
                        request=lambda: runtime.api.preview_builtin(
                            selected_mode,
                            category=1,
                            brightness=brightness,
                            speed=speed,
                            pixel_len=pixel_len,
                            reverse=reverse,
                        ),
                        retries=0,
                    )
                else:
                    reapply_ok, reapply_resp = await _call_with_retry(
                        action=f"Builtin preset delayed run_effect id={view_effect_id}",
                        correlation_id=correlation_id,
                        request=lambda: runtime.api.run_effect(view_effect_id),
                        retries=0,
                    )
                await async_log_event(
                    self._hass,
                    runtime,
                    "builtin_preset_reapply_result",
                    correlation_id=correlation_id,
                    coordinator_data=self.coordinator.data or {},
                    success=reapply_ok,
                    response=reapply_resp,
                    effect_id=view_effect_id,
                    applied_via=apply_via,
                    attempt=attempt,
                )
                if reapply_ok:
                    self._optimistic_builtin_selection(
                        match=match,
                        selected_mode=selected_mode,
                        brightness=brightness,
                        speed=speed,
                    )
                    self._schedule_verification_refresh(
                        correlation_id=correlation_id,
                        source="builtin_preset_reapply",
                        delay_s=_BUILTIN_PRESET_REAPPLY_VERIFY_DELAY_SECONDS,
                    )
                    if attempt == 1:
                        self._schedule_builtin_reapply_if_needed(
                            correlation_id=correlation_id,
                            option=option,
                            match=match,
                            selected_mode=selected_mode,
                            brightness=brightness,
                            speed=speed,
                            apply_via=apply_via,
                            pixel_len=pixel_len,
                            reverse=reverse,
                            attempt=2,
                            delay_s=_BUILTIN_PRESET_SECOND_REAPPLY_DELAY_SECONDS,
                        )
            except Exception as exc:  # noqa: BLE001
                _LOGGER.warning(
                    "Builtin preset delayed reapply failed: cid=%s option=%s error=%s",
                    correlation_id,
                    option,
                    exc,
                )

        def _start_reapply() -> None:
            self._hass.async_create_task(_reapply_if_needed())

        data.builtin_reapply_handle = self._hass.loop.call_later(delay_s, _start_reapply)

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data or {}
        effect_id = data.get("current_effect_id")
        builtins = self._data.builtins
        return {
            "current_id": effect_id,
            "builtins": [{"id": b.get("id"), "mode": b.get("mode"), "name": b.get("name")} for b in builtins],
        }

    async def async_select_option(self, option: str) -> None:
        data = self._data
        builtins = data.builtins
        match = next((row for row in builtins if row["name"] == option), None)
        if not match:
            return

        api = data.api
        correlation_id = uuid.uuid4().hex[:8]
        current = self.coordinator.data or {}
        current_effect = current.get("current_effect") or {}
        current_category = current.get("current_effect_category")
        current_effect_id = self._safe_int(current.get("current_effect_id"))
        current_presets = current.get("custom_effects") or data.custom_cache
        source_kind = _infer_transition_source_kind(
            builtins=data.builtins,
            presets=current_presets,
            current_effect=current_effect,
            current_category=current_category,
            effect_id=current_effect_id,
        )
        # Ensure the lights are on when a preset is selected.
        switch_resp = None
        try:
            switch_resp = await api.set_switch_state(1)
        except Exception:
            pass
        # Keep UI on for a short grace window while the controller catches up.
        data.forced_on_until = time.monotonic() + FORCED_ON_GRACE_SECONDS
        brightness = data.last_brightness
        speed = data.last_speed
        selected_mode = int(match.get("mode", match.get("id")))
        current_effect = current.get("current_effect") or {}
        effects = current.get("effects") or []
        pixel_len, reverse = infer_builtin_preview_params(
            int(match.get("id", selected_mode)), current_effect, effects
        )
        self._set_pending_transition(
            target_kind="builtin",
            target_name=option,
            target_id=self._safe_int(match.get("id")),
            target_mode=selected_mode,
            source_kind=source_kind,
            correlation_id=correlation_id,
            expires_in_s=_PENDING_TRANSITION_EXPIRY_SECONDS,
        )
        preview_resp = await api.preview_builtin(
            selected_mode,
            category=0,
            brightness=brightness,
            speed=speed,
            pixel_len=pixel_len,
            reverse=reverse,
        )
        preview_code = _resp_code(preview_resp)
        preview_desc = _resp_desc(preview_resp)
        applied_via = "preview"
        alt_preview_resp = None
        view_resp = None
        view_effect_id = match.get("id")

        if preview_code not in (None, 0):
            alt_preview_resp = await api.preview_builtin(
                selected_mode,
                category=1,
                brightness=brightness,
                speed=speed,
                pixel_len=pixel_len,
                reverse=reverse,
            )
            if _resp_code(alt_preview_resp) in (None, 0):
                applied_via = "preview_category_1"

        if applied_via == "preview" and preview_code not in (None, 0) and view_effect_id is not None:
            _LOGGER.warning(
                "Builtin preset preview rejected: cid=%s option=%s mode=%s code=%s desc=%s; falling back to effect/view id=%s",
                correlation_id,
                option,
                selected_mode,
                preview_code,
                preview_desc,
                view_effect_id,
            )
            view_success, view_resp = await _call_with_retry(
                action="Builtin preset view",
                correlation_id=correlation_id,
                request=lambda: api.run_effect(int(view_effect_id)),
            )
            if view_success:
                applied_via = "view"

        updated = self._optimistic_builtin_selection(
            match=match,
            selected_mode=selected_mode,
            brightness=brightness,
            speed=speed,
        )
        await async_log_event(
            self._hass,
            data,
            "builtin_preset_select",
            correlation_id=correlation_id,
            coordinator_data=updated,
            option=option,
            preset=match,
            applied_via=applied_via,
            switch_response=switch_resp,
            preview_response=preview_resp,
            alt_preview_response=alt_preview_resp,
            view_response=view_resp,
            pixel_len=pixel_len,
            reverse=reverse,
        )
        if applied_via in {"view", "preview_category_1"} and view_effect_id is not None:
            self._schedule_builtin_reapply_if_needed(
                correlation_id=correlation_id,
                option=option,
                match=match,
                selected_mode=selected_mode,
                brightness=brightness,
                speed=speed,
                apply_via=applied_via,
                pixel_len=pixel_len,
                reverse=reverse,
            )
        self._schedule_verification_refresh(
            correlation_id=correlation_id,
            source="builtin_preset_select",
        )


class TrimlightCustomSelect(TrimlightEntity, SelectEntity):
    _attr_name = "Trimlight Custom Preset"

    def __init__(self, hass: HomeAssistant, entry_id: str, coordinator) -> None:
        super().__init__(hass, entry_id, coordinator)
        self._attr_unique_id = f"{entry_id}_custom_select"

    @staticmethod
    def _base_name(effect: dict) -> str:
        return (effect.get("name") or "").strip() or "(no name)"

    @staticmethod
    def _safe_int(value: object, default: int | None = None) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _option_entries(self, presets: list[dict]) -> list[tuple[str, dict]]:
        base_names = [self._base_name(effect) for effect in presets]
        counts = Counter(base_names)

        def _id_sort_key(effect: dict) -> int:
            effect_id = self._safe_int(effect.get("id"))
            if effect_id is None:
                return 1_000_000_000
            return effect_id

        rows: list[tuple[str, dict]] = []
        sorted_presets = sorted(
            presets,
            key=lambda effect: (
                1 if self._base_name(effect) == "(no name)" else 0,
                self._base_name(effect).lower(),
                _id_sort_key(effect),
            ),
        )
        for effect in sorted_presets:
            name = self._base_name(effect)
            label = name
            if counts[name] > 1:
                effect_id = effect.get("id")
                suffix = f"id {effect_id}" if effect_id is not None else "duplicate"
                label = f"{name} ({suffix})"
            rows.append((label, effect))
        return rows

    def _resolve_selected_effect(
        self, option: str, presets: list[dict]
    ) -> tuple[dict | None, str | None]:
        rows = self._option_entries(presets)
        for label, effect in rows:
            if label == option:
                return effect, label

        same_name = [effect for effect in presets if self._base_name(effect) == option]
        if len(same_name) == 1:
            effect = same_name[0]
            effect_id = self._safe_int(effect.get("id"))
            if effect_id is None:
                return effect, option
            selected_label = next(
                (
                    label
                    for label, row in rows
                    if self._safe_int(row.get("id")) == effect_id
                ),
                option,
            )
            return effect, selected_label

        if len(same_name) > 1:
            _LOGGER.warning(
                "Custom preset '%s' is ambiguous; use disambiguated option label with id",
                option,
            )
        return None, None

    def _optimistic_custom_selection(
        self,
        *,
        selected_label: str,
        match: dict,
        effect_id: int,
        brightness: int,
        speed: int,
    ) -> None:
        data = self._data

        data.last_selected_preset = selected_label
        data.last_selected_custom_preset = selected_label
        data.last_known_preset = selected_label
        data.last_known_custom_preset = selected_label
        if match.get("pixels") is not None:
            data.last_known_custom_pixels = match.get("pixels")

        mode = get_effect_mode(match)
        if mode is not None:
            data.last_selected_custom_mode = mode

        current_effect = {
            "id": effect_id,
            "name": self._base_name(match),
            "category": 2,
            "mode": mode,
            "brightness": int(brightness),
            "speed": int(speed),
            "pixels": match.get("pixels"),
        }
        updated = dict(self.coordinator.data or {})
        updated.update(
            {
                "current_effect": current_effect,
                "current_effect_id": current_effect.get("id"),
                "current_effect_category": 2,
                "brightness": current_effect.get("brightness"),
                "switch_state": 1,
            }
        )
        self.coordinator.async_set_updated_data(updated)

    def _schedule_custom_reapply_if_needed(
        self,
        *,
        correlation_id: str,
        selected_label: str,
        match: dict,
        effect_id: int,
        brightness: int,
        speed: int,
        delay_s: float = _CUSTOM_PRESET_REAPPLY_DELAY_SECONDS,
    ) -> None:
        data = self._data
        handle = data.custom_reapply_handle
        if handle:
            handle.cancel()

        async def _reapply_if_needed() -> None:
            runtime = self._data
            if runtime.last_selected_custom_preset != selected_label:
                return

            current = self.coordinator.data or {}
            current_effect = current.get("current_effect") or {}
            current_effect_id = self._safe_int(current.get("current_effect_id"))
            presets = (current.get("custom_effects") or runtime.custom_cache)
            inferred = find_custom_preset_by_state(presets, current_effect, current_effect_id)
            inferred_id = self._safe_int(inferred.get("id")) if inferred is not None else None

            if current_effect_id == effect_id or inferred_id == effect_id:
                return

            await async_log_event(
                self._hass,
                runtime,
                "custom_preset_reapply_requested",
                correlation_id=correlation_id,
                coordinator_data=current,
                selected_label=selected_label,
                effect_id=effect_id,
                current_effect_id=current_effect_id,
                inferred_effect_id=inferred_id,
            )
            reapply_ok, reapply_resp = await _call_with_retry(
                action=f"Custom preset delayed run_effect id={effect_id}",
                correlation_id=correlation_id,
                request=lambda: runtime.api.run_effect(effect_id),
                retries=0,
            )
            await async_log_event(
                self._hass,
                runtime,
                "custom_preset_reapply_result",
                correlation_id=correlation_id,
                coordinator_data=self.coordinator.data or {},
                success=reapply_ok,
                response=reapply_resp,
                effect_id=effect_id,
            )
            if reapply_ok:
                self._optimistic_custom_selection(
                    selected_label=selected_label,
                    match=match,
                    effect_id=effect_id,
                    brightness=brightness,
                    speed=speed,
                )
                self._schedule_verification_refresh(
                    correlation_id=correlation_id,
                    source="custom_preset_reapply",
                    delay_s=_CUSTOM_PRESET_REAPPLY_VERIFY_DELAY_SECONDS,
                )

        def _start_reapply() -> None:
            self._hass.async_create_task(_reapply_if_needed())

        data.custom_reapply_handle = self._hass.loop.call_later(delay_s, _start_reapply)

    @property
    def options(self) -> list[str]:
        data = self._data
        presets = (self.coordinator.data or {}).get("custom_effects") or data.custom_cache
        return [label for label, _ in self._option_entries(presets)]

    @property
    def current_option(self) -> str | None:
        data = self.coordinator.data or {}
        is_on = self._is_effectively_on()
        if is_on is not True:
            return None
        runtime = self._data
        presets = (data.get("custom_effects") or runtime.custom_cache)
        rows = self._option_entries(presets)
        current_effect = data.get("current_effect") or {}
        current_category = data.get("current_effect_category")
        effect_id = self._safe_int(data.get("current_effect_id"))
        pending = self._active_pending_transition()
        if pending is not None:
            if pending.target_kind == "custom":
                if matches_custom_target(
                    presets,
                    current_effect,
                    current_category,
                    effect_id,
                    target_name=pending.target_name,
                    target_id=pending.target_id,
                    builtins=runtime.builtins,
                ):
                    self._clear_pending_transition()
                else:
                    return pending.target_name
            elif pending.target_kind == "builtin":
                if matches_builtin_target(
                    runtime.builtins,
                    current_effect,
                    current_category,
                    effect_id,
                    target_name=pending.target_name,
                    target_id=pending.target_id,
                    target_mode=pending.target_mode,
                ):
                    self._clear_pending_transition()
                else:
                    return None
        raw_switch_state = data.get("switch_state")
        forced_on_override = raw_switch_state is not None and int(raw_switch_state) == 0 and is_on is True
        remembered_custom_active = (
            runtime.last_known_custom_preset is not None
            and runtime.last_known_preset == runtime.last_known_custom_preset
        )
        if forced_on_override:
            last_selected = runtime.last_selected_custom_preset
            if last_selected:
                return last_selected
            if remembered_custom_active:
                return runtime.last_known_custom_preset
            return None

        if current_category not in (1, 2, None):
            return None
        if is_builtin_like_state(runtime.builtins, current_effect, current_category, effect_id):
            return None
        if effect_id is not None:
            for label, effect in rows:
                if effect.get("id") == effect_id:
                    return label

        inferred = find_custom_preset_by_state(presets, current_effect, effect_id)
        if inferred is not None:
            inferred_id = self._safe_int(inferred.get("id"))
            if inferred_id is not None:
                for label, effect in rows:
                    if self._safe_int(effect.get("id")) == inferred_id:
                        return label

        # If the device reports a preview (id = -1) or no match, fall back
        # to the last selected preset while the lights are on.
        last_selected = runtime.last_selected_custom_preset
        if last_selected:
            return last_selected
        last_known = runtime.last_known_custom_preset
        if last_known:
            return last_known
        return None

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data or {}
        presets = (data.get("custom_effects") or self._data.custom_cache)
        rows = self._option_entries(presets)
        presets_list = [{"id": e.get("id"), "name": self._base_name(e)} for e in presets]
        name_to_id: dict[str, int] = {}
        duplicates: set[str] = set()
        for item in presets_list:
            name = item["name"]
            if name in name_to_id:
                duplicates.add(name)
            else:
                name_to_id[name] = item["id"]
        for dup in duplicates:
            name_to_id.pop(dup, None)

        option_to_id = {label: effect.get("id") for label, effect in rows}

        return {
            "current_id": data.get("current_effect_id"),
            "presets": presets_list,
            "name_to_id": name_to_id,
            "option_to_id": option_to_id,
        }

    async def async_select_option(self, option: str) -> None:
        data = self._data
        coord = self.coordinator.data or {}
        presets = coord.get("custom_effects") or data.custom_cache
        match, selected_label = self._resolve_selected_effect(option, presets)
        if not match:
            return

        effect_id = match.get("id")
        if effect_id is None:
            _LOGGER.warning("Custom preset '%s' is missing id and cannot be applied", option)
            return
        effect_id = self._safe_int(effect_id)
        if effect_id is None:
            _LOGGER.warning("Custom preset '%s' has invalid id and cannot be applied", option)
            return
        if not selected_label:
            selected_label = option

        correlation_id = uuid.uuid4().hex[:8]
        api = data.api
        was_off = int(coord.get("switch_state", 0) or 0) == 0
        current_effect = coord.get("current_effect") or {}
        current_category = coord.get("current_effect_category")
        current_effect_id = self._safe_int(coord.get("current_effect_id"))
        source_kind = _infer_transition_source_kind(
            builtins=data.builtins,
            presets=presets,
            current_effect=current_effect,
            current_category=current_category,
            effect_id=current_effect_id,
        )
        originated_from_builtin = is_builtin_like_state(
            data.builtins, current_effect, current_category, current_effect_id
        )
        selected_name = self._base_name(match)
        selected_mode = get_effect_mode(match)
        pixels = match.get("pixels")
        pixel_count = len(pixels) if isinstance(pixels, list) else None
        _LOGGER.info(
            "Custom preset selected: cid=%s option='%s' name='%s' id=%s mode=%s pixels=%s was_off=%s from_builtin=%s apply=run_effect",
            correlation_id,
            selected_label,
            selected_name,
            effect_id,
            selected_mode,
            pixel_count,
            was_off,
            originated_from_builtin,
        )

        brightness = match.get("brightness")
        if brightness is None:
            brightness = data.last_brightness
        else:
            data.last_brightness = int(brightness)

        speed = match.get("speed")
        if speed is None:
            speed = data.last_speed
        else:
            data.last_speed = int(speed)
        brightness = int(brightness)
        speed = int(speed)

        # Optimistic UI update before network I/O for snappier feedback.
        self._set_pending_transition(
            target_kind="custom",
            target_name=selected_label,
            target_id=effect_id,
            target_mode=selected_mode,
            source_kind=source_kind,
            correlation_id=correlation_id,
            expires_in_s=_PENDING_TRANSITION_EXPIRY_SECONDS,
        )
        self._optimistic_custom_selection(
            selected_label=selected_label,
            match=match,
            effect_id=effect_id,
            brightness=brightness,
            speed=speed,
        )
        await async_log_event(
            self._hass,
            data,
            "custom_preset_select_requested",
            correlation_id=correlation_id,
            coordinator_data=self.coordinator.data or {},
            option=option,
            selected_label=selected_label,
            selected_name=selected_name,
            effect_id=effect_id,
            mode=selected_mode,
            brightness=brightness,
            speed=speed,
            was_off=was_off,
            originated_from_builtin=originated_from_builtin,
            pixels=match.get("pixels"),
        )

        # Keep UI on for a short grace window while the controller catches up.
        data.forced_on_until = time.monotonic() + FORCED_ON_GRACE_SECONDS

        try:
            if was_off:
                # Only force manual mode when the controller is actually off.
                switch_ok, switch_resp = await _call_with_retry(
                    action="Custom preset switch-on",
                    correlation_id=correlation_id,
                    request=lambda: api.set_switch_state(1),
                )
                await async_log_event(
                    self._hass,
                    data,
                    "custom_preset_switch_on_result",
                    correlation_id=correlation_id,
                    coordinator_data=self.coordinator.data or {},
                    success=switch_ok,
                    response=switch_resp,
                )
                await asyncio.sleep(_CUSTOM_PRESET_POWER_ON_DELAY_SECONDS)
            run_ok, run_resp = await _call_with_retry(
                action=f"Custom preset run_effect id={effect_id}",
                correlation_id=correlation_id,
                request=lambda: api.run_effect(effect_id),
            )
            await async_log_event(
                self._hass,
                data,
                "custom_preset_run_effect_result",
                correlation_id=correlation_id,
                coordinator_data=self.coordinator.data or {},
                success=run_ok,
                response=run_resp,
                effect_id=effect_id,
            )
            if run_ok:
                self._schedule_custom_reapply_if_needed(
                    correlation_id=correlation_id,
                    selected_label=selected_label,
                    match=match,
                    effect_id=effect_id,
                    brightness=brightness,
                    speed=speed,
                    delay_s=(
                        _CUSTOM_PRESET_FROM_BUILTIN_REAPPLY_DELAY_SECONDS
                        if originated_from_builtin
                        else _CUSTOM_PRESET_REAPPLY_DELAY_SECONDS
                    ),
                )
        finally:
            self._schedule_verification_refresh(
                correlation_id=correlation_id,
                source="custom_preset_select",
                # Built-in -> custom transitions need an earlier verification so
                # a failed first apply can trigger the delayed second run_effect
                # before the UI settles. Other saved custom preset selections
                # still benefit from the longer reconciliation window.
                delay_s=(
                    _CUSTOM_PRESET_FROM_BUILTIN_VERIFY_DELAY_SECONDS
                    if originated_from_builtin
                    else _CUSTOM_PRESET_VERIFY_DELAY_SECONDS
                ),
            )


class TrimlightCustomModeSelect(TrimlightEntity, SelectEntity):
    _attr_name = "Trimlight Custom Effect Mode"

    def __init__(self, hass: HomeAssistant, entry_id: str, coordinator) -> None:
        super().__init__(hass, entry_id, coordinator)
        self._attr_unique_id = f"{entry_id}_custom_mode"

    @property
    def options(self) -> list[str]:
        return [CUSTOM_EFFECT_MODES[i] for i in sorted(CUSTOM_EFFECT_MODES.keys())]

    @property
    def current_option(self) -> str | None:
        data = self.coordinator.data or {}
        is_on = self._is_effectively_on()
        if is_on is not True:
            return None
        runtime = self._data
        presets = (data.get("custom_effects") or runtime.custom_cache)
        custom_ids = {e.get("id") for e in presets}

        current_effect = data.get("current_effect") or {}
        current_category = data.get("current_effect_category")
        effect_id = self._safe_int(data.get("current_effect_id"))
        last_custom = runtime.last_selected_custom_preset
        last_mode = runtime.last_selected_custom_mode
        pending = self._active_pending_transition()
        if pending is not None:
            if pending.target_kind == "custom":
                if matches_custom_target(
                    presets,
                    current_effect,
                    current_category,
                    effect_id,
                    target_name=pending.target_name,
                    target_id=pending.target_id,
                    builtins=runtime.builtins,
                ):
                    self._clear_pending_transition()
                else:
                    if pending.target_mode is None:
                        return None
                    runtime.last_selected_custom_mode = int(pending.target_mode)
                    return CUSTOM_EFFECT_MODES.get(int(pending.target_mode), str(pending.target_mode))
            elif pending.target_kind == "builtin":
                if matches_builtin_target(
                    runtime.builtins,
                    current_effect,
                    current_category,
                    effect_id,
                    target_name=pending.target_name,
                    target_id=pending.target_id,
                    target_mode=pending.target_mode,
                ):
                    self._clear_pending_transition()
                else:
                    return None

        raw_switch_state = data.get("switch_state")
        forced_on_override = raw_switch_state is not None and int(raw_switch_state) == 0 and is_on is True
        remembered_custom_active = (
            runtime.last_known_custom_preset is not None
            and runtime.last_known_preset == runtime.last_known_custom_preset
        )

        is_custom = (
            not is_builtin_like_state(runtime.builtins, current_effect, current_category, effect_id)
            and (
                current_category in (1, 2)
                or (effect_id in custom_ids)
                or bool(last_custom)
                or (forced_on_override and remembered_custom_active)
            )
        )
        if not is_custom:
            return None

        mode = None if forced_on_override else get_effect_mode(current_effect)
        if mode is None and effect_id in custom_ids:
            match = next((e for e in presets if e.get("id") == effect_id), None)
            if match:
                mode = get_effect_mode(match)
        if mode is None and remembered_custom_active:
            match = next(
                (
                    e
                    for e in presets
                    if (e.get("name") or "").strip() == runtime.last_known_custom_preset
                ),
                None,
            )
            if match:
                mode = get_effect_mode(match)
        if mode is None and last_mode is not None:
            mode = last_mode

        if mode is None:
            return None

        runtime.last_selected_custom_mode = int(mode)
        return CUSTOM_EFFECT_MODES.get(int(mode), str(mode))

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data or {}
        current = get_effect_mode(data.get("current_effect") or {})
        if current is None:
            current = self._data.last_selected_custom_mode
        modes = [{"id": k, "name": v} for k, v in sorted(CUSTOM_EFFECT_MODES.items())]
        return {"current_mode_id": current, "modes": modes}

    async def async_select_option(self, option: str) -> None:
        data = self._data
        coord = self.coordinator.data or {}
        api = data.api

        mode = None
        for key, label in CUSTOM_EFFECT_MODES.items():
            if label == option:
                mode = int(key)
                break
        if mode is None:
            return

        current_effect = coord.get("current_effect") or {}
        effect_id = coord.get("current_effect_id")
        effect: dict = {}

        if current_effect and current_effect.get("category") in (1, 2):
            effect = dict(current_effect)
        else:
            presets = (coord.get("custom_effects") or data.custom_cache)
            match = next((e for e in presets if e.get("id") == effect_id), None)
            if match:
                effect = dict(match)
                if effect.get("mode") is None:
                    effect["mode"] = get_effect_mode(match)

        if not effect:
            return

        effect["category"] = 2
        effect["mode"] = mode

        brightness = data.last_brightness
        speed = data.last_speed
        response = await api.preview_effect(effect, brightness, speed=speed)

        data.last_selected_custom_mode = mode

        updated = dict(coord)
        current = dict(updated.get("current_effect") or {})
        current.update({"category": 2, "mode": mode})
        updated.update(
            {
                "current_effect": current,
                "current_effect_category": 2,
                "current_effect_id": effect.get("id", effect_id),
                "brightness": brightness,
            }
        )
        self.coordinator.async_set_updated_data(updated)
        await async_log_event(
            self._hass,
            data,
            "custom_mode_select",
            coordinator_data=updated,
            option=option,
            mode=mode,
            response=response,
        )
        self._schedule_verification_refresh()
