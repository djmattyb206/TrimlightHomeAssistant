from __future__ import annotations

import asyncio
import logging
import time
import uuid

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CUSTOM_EFFECT_MODES, FORCED_ON_GRACE_SECONDS
from .data import get_data
from .entity import TrimlightEntity
from .effects import get_effect_mode

_LOGGER = logging.getLogger(__name__)
_CUSTOM_PRESET_REAPPLY_DELAY_SECONDS = 0.8


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
        switch_state = data.get("switch_state")
        if switch_state is None or int(switch_state) == 0:
            return None
        if data.get("current_effect_category") != 0:
            return None
        effect_id = data.get("current_effect_id")
        if effect_id is None:
            return None
        builtins = self._data.builtins
        for row in builtins:
            if row.get("id") == effect_id or row.get("mode") == effect_id:
                return row["name"]
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
        # Ensure the lights are on when a preset is selected.
        try:
            await api.set_switch_state(1)
        except Exception:
            pass
        # Keep UI on for a short grace window while the controller catches up.
        data.forced_on_until = time.monotonic() + FORCED_ON_GRACE_SECONDS
        brightness = data.last_brightness
        speed = data.last_speed
        selected_mode = int(match.get("mode", match.get("id")))
        await api.preview_builtin(selected_mode, brightness=brightness, speed=speed)

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
        self._schedule_verification_refresh()


class TrimlightCustomSelect(TrimlightEntity, SelectEntity):
    _attr_name = "Trimlight Custom Preset"

    def __init__(self, hass: HomeAssistant, entry_id: str, coordinator) -> None:
        super().__init__(hass, entry_id, coordinator)
        self._attr_unique_id = f"{entry_id}_custom_select"

    @property
    def options(self) -> list[str]:
        data = self._data
        presets = (self.coordinator.data or {}).get("custom_effects") or data.custom_cache
        names = [(e.get("name") or "").strip() or "(no name)" for e in presets]

        def _sort_key(name: str) -> tuple[int, str]:
            if name == "(no name)":
                return (1, "")
            return (0, name.lower())

        return sorted(names, key=_sort_key)

    @property
    def current_option(self) -> str | None:
        data = self.coordinator.data or {}
        switch_state = data.get("switch_state")
        if switch_state is None or int(switch_state) == 0:
            return None
        current_category = data.get("current_effect_category")
        if current_category not in (1, 2, None):
            return None
        effect_id = data.get("current_effect_id")

        runtime = self._data
        presets = (data.get("custom_effects") or runtime.custom_cache)
        if effect_id is not None:
            for e in presets:
                if e.get("id") == effect_id:
                    return (e.get("name") or "").strip() or "(no name)"

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
        presets_list = [{"id": e.get("id"), "name": (e.get("name") or "").strip() or "(no name)"} for e in presets]
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

        return {
            "current_id": data.get("current_effect_id"),
            "presets": presets_list,
            "name_to_id": name_to_id,
        }

    async def async_select_option(self, option: str) -> None:
        data = self._data
        coord = self.coordinator.data or {}
        presets = coord.get("custom_effects") or data.custom_cache
        match = None
        for e in presets:
            name = (e.get("name") or "").strip() or "(no name)"
            if name == option:
                match = e
                break

        if not match:
            return

        effect_id = match.get("id")
        if effect_id is None:
            _LOGGER.warning("Custom preset '%s' is missing id and cannot be applied", option)
            return

        correlation_id = uuid.uuid4().hex[:8]
        api = data.api
        was_off = int(coord.get("switch_state", 0) or 0) == 0
        selected_name = (match.get("name") or "").strip() or "(no name)"
        selected_mode = get_effect_mode(match)
        pixels = match.get("pixels")
        pixel_count = len(pixels) if isinstance(pixels, list) else None
        _LOGGER.info(
            "Custom preset selected: cid=%s name='%s' id=%s mode=%s pixels=%s was_off=%s commit=%s",
            correlation_id,
            selected_name,
            effect_id,
            selected_mode,
            pixel_count,
            was_off,
            data.commit_custom_preset,
        )

        # Ensure the lights are on when a preset is selected.
        try:
            switch_resp = await api.set_switch_state(1)
            _LOGGER.info(
                "Custom preset switch-on response: cid=%s code=%s desc=%s",
                correlation_id,
                _resp_code(switch_resp),
                _resp_desc(switch_resp),
            )
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("Custom preset switch-on failed: cid=%s error=%s", correlation_id, exc)
        # Keep UI on for a short grace window while the controller catches up.
        data.forced_on_until = time.monotonic() + FORCED_ON_GRACE_SECONDS

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

        # Preview immediately to reduce perceived latency.
        effect = dict(match)
        mode = get_effect_mode(effect)
        if mode is not None:
            effect["mode"] = mode
        if effect.get("category") is None:
            effect["category"] = 2

        can_preview = mode is not None and effect.get("pixels") is not None
        preview_ok = False
        if can_preview:
            try:
                preview_resp = await api.preview_effect(effect, int(brightness), speed=int(speed))
                preview_ok = True
                _LOGGER.info(
                    "Custom preset preview response: cid=%s code=%s desc=%s",
                    correlation_id,
                    _resp_code(preview_resp),
                    _resp_desc(preview_resp),
                )
            except Exception as exc:  # noqa: BLE001
                _LOGGER.warning("Custom preset preview failed: cid=%s error=%s", correlation_id, exc)
        else:
            _LOGGER.info(
                "Custom preset preview skipped: cid=%s reason=missing_mode_or_pixels mode=%s pixels=%s commit=%s",
                correlation_id,
                mode,
                pixel_count,
                data.commit_custom_preset,
            )

        commit_delay_s = _CUSTOM_PRESET_REAPPLY_DELAY_SECONDS if was_off else 0.0
        should_run_effect = data.commit_custom_preset or not preview_ok

        if should_run_effect:
            if not preview_ok:
                # If preview is unavailable, force apply with saved effect id.
                if commit_delay_s > 0:
                    await asyncio.sleep(commit_delay_s)
                run_resp = await api.run_effect(int(effect_id))
                _LOGGER.info(
                    "Custom preset run_effect fallback response: cid=%s code=%s desc=%s id=%s",
                    correlation_id,
                    _resp_code(run_resp),
                    _resp_desc(run_resp),
                    effect_id,
                )
            else:
                async def _run_effect(delay_s: float) -> None:
                    if delay_s > 0:
                        await asyncio.sleep(delay_s)
                    try:
                        run_resp = await api.run_effect(int(effect_id))
                        _LOGGER.info(
                            "Custom preset run_effect response: cid=%s code=%s desc=%s id=%s",
                            correlation_id,
                            _resp_code(run_resp),
                            _resp_desc(run_resp),
                            effect_id,
                        )
                    except Exception as exc:  # noqa: BLE001
                        _LOGGER.warning(
                            "Custom preset run_effect failed: cid=%s error=%s",
                            correlation_id,
                            exc,
                        )

                self._hass.async_create_task(_run_effect(commit_delay_s))
        elif was_off and preview_ok:
            # In preview-only mode, reassert once after power-on to avoid stale-state restore.
            async def _reassert_preview() -> None:
                await asyncio.sleep(_CUSTOM_PRESET_REAPPLY_DELAY_SECONDS)
                try:
                    reassert_resp = await api.preview_effect(effect, int(brightness), speed=int(speed))
                    _LOGGER.info(
                        "Custom preset delayed preview response: cid=%s code=%s desc=%s",
                        correlation_id,
                        _resp_code(reassert_resp),
                        _resp_desc(reassert_resp),
                    )
                except Exception as exc:  # noqa: BLE001
                    _LOGGER.warning(
                        "Custom preset delayed preview failed: cid=%s error=%s",
                        correlation_id,
                        exc,
                    )

            self._hass.async_create_task(_reassert_preview())

        # Optimistic UI update: reflect the selected preset immediately
        data.last_selected_preset = selected_name
        data.last_selected_custom_preset = selected_name
        data.last_known_preset = selected_name
        data.last_known_custom_preset = selected_name
        if match.get("pixels") is not None:
            data.last_known_custom_pixels = match.get("pixels")
        mode = get_effect_mode(match)
        if mode is not None:
            data.last_selected_custom_mode = mode
        current_effect = {
            "id": effect_id,
            "name": (match.get("name") or "").strip() or "(no name)",
            "category": 2,
            "mode": get_effect_mode(match),
            "brightness": data.last_brightness,
            "speed": data.last_speed,
            "pixels": match.get("pixels"),
        }

        existing = self.coordinator.data or {}
        updated = dict(existing)
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
        self._schedule_verification_refresh(
            correlation_id=correlation_id,
            source="custom_preset_select",
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
        switch_state = data.get("switch_state")
        if switch_state is None or int(switch_state) == 0:
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

        mode = get_effect_mode(data.get("current_effect") or {})
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
        await api.preview_effect(effect, brightness, speed=speed)

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
        self._schedule_verification_refresh()
