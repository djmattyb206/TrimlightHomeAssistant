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
from .effects import find_builtin_preset, find_custom_preset_by_state, get_effect_mode

_LOGGER = logging.getLogger(__name__)
_CUSTOM_PRESET_API_RETRIES = 1
_CUSTOM_PRESET_RETRY_DELAY_SECONDS = 0.35
_CUSTOM_PRESET_POWER_ON_DELAY_SECONDS = 0.8
_CUSTOM_PRESET_COLD_START_VERIFY_DELAY_SECONDS = 12.0


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
        raw_switch_state = data.get("switch_state")
        forced_on_override = raw_switch_state is not None and int(raw_switch_state) == 0 and is_on is True
        if forced_on_override:
            last_known = self._data.last_known_builtin_preset
            if last_known and self._data.last_selected_preset == last_known:
                return last_known
        if data.get("current_effect_category") != 0:
            return None
        effect_id = data.get("current_effect_id")
        current_mode = get_effect_mode(data.get("current_effect") or {})
        builtins = self._data.builtins
        match = find_builtin_preset(builtins, effect_id, current_mode)
        if match is not None:
            return match["name"]
        last_known = self._data.last_known_builtin_preset
        if last_known:
            return last_known
        return None

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
        preview_resp = await api.preview_builtin(selected_mode, brightness=brightness, speed=speed)
        preview_code = _resp_code(preview_resp)
        preview_desc = _resp_desc(preview_resp)
        applied_via = "preview"
        view_resp = None
        view_effect_id = match.get("id")

        if preview_code not in (None, 0) and view_effect_id is not None:
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

        # Track last selected preset for sensor fallback
        data.last_selected_preset = match.get("name")
        data.last_known_preset = match.get("name")
        data.last_known_builtin_preset = match.get("name")
        # Clear custom selection context when a built-in is chosen
        data.last_selected_custom_preset = None
        data.last_selected_custom_mode = None
        # Optimistic UI update: reflect built-in selection immediately so
        # custom select clears even before coordinator refresh.
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
            view_response=view_resp,
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
        current_category = data.get("current_effect_category")
        if current_category not in (1, 2, None):
            return None
        effect_id = data.get("current_effect_id")
        current_effect = data.get("current_effect") or {}

        runtime = self._data
        presets = (data.get("custom_effects") or runtime.custom_cache)
        rows = self._option_entries(presets)
        raw_switch_state = data.get("switch_state")
        forced_on_override = raw_switch_state is not None and int(raw_switch_state) == 0 and is_on is True
        if forced_on_override:
            last_selected = runtime.last_selected_custom_preset
            if last_selected:
                return last_selected
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
        selected_name = self._base_name(match)
        selected_mode = get_effect_mode(match)
        pixels = match.get("pixels")
        pixel_count = len(pixels) if isinstance(pixels, list) else None
        _LOGGER.info(
            "Custom preset selected: cid=%s option='%s' name='%s' id=%s mode=%s pixels=%s was_off=%s apply=run_effect",
            correlation_id,
            selected_label,
            selected_name,
            effect_id,
            selected_mode,
            pixel_count,
            was_off,
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
        finally:
            self._schedule_verification_refresh(
                correlation_id=correlation_id,
                source="custom_preset_select",
                delay_s=_CUSTOM_PRESET_COLD_START_VERIFY_DELAY_SECONDS if was_off else None,
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

        current_category = data.get("current_effect_category")
        effect_id = data.get("current_effect_id")
        last_custom = runtime.last_selected_custom_preset
        last_mode = runtime.last_selected_custom_mode

        is_custom = current_category in (1, 2) or (effect_id in custom_ids) or bool(last_custom)
        if not is_custom:
            return None

        raw_switch_state = data.get("switch_state")
        forced_on_override = raw_switch_state is not None and int(raw_switch_state) == 0 and is_on is True

        mode = None if forced_on_override else get_effect_mode(data.get("current_effect") or {})
        if mode is None and effect_id in custom_ids:
            match = next((e for e in presets if e.get("id") == effect_id), None)
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
