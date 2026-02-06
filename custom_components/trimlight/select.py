from __future__ import annotations

import time

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CUSTOM_EFFECT_MODES, DOMAIN, FORCED_ON_GRACE_SECONDS
from .entity import TrimlightEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    async_add_entities(
        [
            TrimlightBuiltInSelect(hass, entry.entry_id, coordinator),
            TrimlightCustomSelect(hass, entry.entry_id, coordinator),
            TrimlightCustomModeSelect(hass, entry.entry_id, coordinator),
        ]
    )


def _get_effect_mode(effect: dict | None) -> int | None:
    if not effect:
        return None
    mode = effect.get("mode")
    if mode is not None:
        return int(mode)
    for key in ("effectMode", "effect_mode", "effect_mode_id", "modeId"):
        if effect.get(key) is not None:
            return int(effect.get(key))
    return None


class TrimlightBuiltInSelect(TrimlightEntity, SelectEntity):
    _attr_name = "Trimlight Built-in Preset"

    def __init__(self, hass: HomeAssistant, entry_id: str, coordinator) -> None:
        super().__init__(hass, entry_id, coordinator)
        self._attr_unique_id = f"{entry_id}_builtin_select"

    @property
    def options(self) -> list[str]:
        builtins = self._hass.data[DOMAIN][self._entry_id]["builtins"]
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
        builtins = self._hass.data[DOMAIN][self._entry_id]["builtins"]
        for row in builtins:
            if row.get("id") == effect_id or row.get("mode") == effect_id:
                return row["name"]
        last_known = self._hass.data[DOMAIN][self._entry_id].get("last_known_builtin_preset")
        if last_known:
            return last_known
        return None

    async def async_select_option(self, option: str) -> None:
        builtins = self._hass.data[DOMAIN][self._entry_id]["builtins"]
        match = next((row for row in builtins if row["name"] == option), None)
        if not match:
            return

        api = self._hass.data[DOMAIN][self._entry_id]["api"]
        # Ensure the lights are on when a preset is selected.
        try:
            await api.set_switch_state(1)
        except Exception:
            pass
        # Keep UI on for a short grace window while the controller catches up.
        self._hass.data[DOMAIN][self._entry_id]["forced_on_until"] = (
            time.monotonic() + FORCED_ON_GRACE_SECONDS
        )
        brightness = self._hass.data[DOMAIN][self._entry_id]["last_brightness"]
        speed = self._hass.data[DOMAIN][self._entry_id]["last_speed"]
        await api.preview_builtin(match.get("mode", match.get("id")), brightness=brightness, speed=speed)

        # Track last selected preset for sensor fallback
        self._hass.data[DOMAIN][self._entry_id]["last_selected_preset"] = match.get("name")
        self._hass.data[DOMAIN][self._entry_id]["last_known_preset"] = match.get("name")
        self._hass.data[DOMAIN][self._entry_id]["last_known_builtin_preset"] = match.get("name")
        # Clear custom selection context when a built-in is chosen
        self._hass.data[DOMAIN][self._entry_id]["last_selected_custom_preset"] = None
        self._hass.data[DOMAIN][self._entry_id]["last_selected_custom_mode"] = None
        # Optimistic UI update for on/off state
        updated = dict(self.coordinator.data or {})
        updated["switch_state"] = 1
        self.coordinator.async_set_updated_data(updated)
        self._schedule_verification_refresh()


class TrimlightCustomSelect(TrimlightEntity, SelectEntity):
    _attr_name = "Trimlight Custom Preset"

    def __init__(self, hass: HomeAssistant, entry_id: str, coordinator) -> None:
        super().__init__(hass, entry_id, coordinator)
        self._attr_unique_id = f"{entry_id}_custom_select"

    @property
    def options(self) -> list[str]:
        presets = (self.coordinator.data or {}).get("custom_effects") or self._hass.data[DOMAIN][
            self._entry_id
        ].get("custom_cache", [])
        return [(e.get("name") or "").strip() or "(no name)" for e in presets]

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

        presets = (data.get("custom_effects") or self._hass.data[DOMAIN][self._entry_id].get("custom_cache", []))
        if effect_id is not None:
            for e in presets:
                if e.get("id") == effect_id:
                    return (e.get("name") or "").strip() or "(no name)"

        # If the device reports a preview (id = -1) or no match, fall back
        # to the last selected preset while the lights are on.
        last_selected = self._hass.data[DOMAIN][self._entry_id].get("last_selected_custom_preset")
        if last_selected:
            return last_selected
        last_known = self._hass.data[DOMAIN][self._entry_id].get("last_known_custom_preset")
        if last_known:
            return last_known
        return None

    async def async_select_option(self, option: str) -> None:
        presets = (self.coordinator.data or {}).get("custom_effects") or self._hass.data[DOMAIN][
            self._entry_id
        ].get("custom_cache", [])
        match = None
        for e in presets:
            name = (e.get("name") or "").strip() or "(no name)"
            if name == option:
                match = e
                break

        if not match:
            return

        api = self._hass.data[DOMAIN][self._entry_id]["api"]
        # Ensure the lights are on when a preset is selected.
        try:
            await api.set_switch_state(1)
        except Exception:
            pass
        # Keep UI on for a short grace window while the controller catches up.
        self._hass.data[DOMAIN][self._entry_id]["forced_on_until"] = (
            time.monotonic() + FORCED_ON_GRACE_SECONDS
        )
        await api.run_effect(int(match.get("id")))

        # Optimistic UI update: reflect the selected preset immediately
        data = self._hass.data[DOMAIN][self._entry_id]
        selected_name = (match.get("name") or "").strip() or "(no name)"
        data["last_selected_preset"] = selected_name
        data["last_selected_custom_preset"] = selected_name
        data["last_known_preset"] = selected_name
        data["last_known_custom_preset"] = selected_name
        mode = _get_effect_mode(match)
        if mode is not None:
            data["last_selected_custom_mode"] = mode
        brightness = match.get("brightness")
        speed = match.get("speed")
        if brightness is not None:
            data["last_brightness"] = int(brightness)
        if speed is not None:
            data["last_speed"] = int(speed)

        current_effect = {
            "id": match.get("id"),
            "name": (match.get("name") or "").strip() or "(no name)",
            "category": 2,
            "mode": _get_effect_mode(match),
            "brightness": data.get("last_brightness"),
            "speed": data.get("last_speed"),
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
        self._schedule_verification_refresh()


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
        presets = (data.get("custom_effects") or self._hass.data[DOMAIN][self._entry_id].get("custom_cache", []))
        custom_ids = {e.get("id") for e in presets}

        current_category = data.get("current_effect_category")
        effect_id = data.get("current_effect_id")
        last_custom = self._hass.data[DOMAIN][self._entry_id].get("last_selected_custom_preset")
        last_mode = self._hass.data[DOMAIN][self._entry_id].get("last_selected_custom_mode")

        is_custom = current_category in (1, 2) or (effect_id in custom_ids) or bool(last_custom)
        if not is_custom:
            return None

        mode = (data.get("current_effect") or {}).get("mode")
        if mode is None and effect_id in custom_ids:
            match = next((e for e in presets if e.get("id") == effect_id), None)
            if match:
                mode = _get_effect_mode(match)
        if mode is None and last_mode is not None:
            mode = last_mode

        if mode is None:
            return None

        self._hass.data[DOMAIN][self._entry_id]["last_selected_custom_mode"] = int(mode)
        return CUSTOM_EFFECT_MODES.get(int(mode), str(mode))

    async def async_select_option(self, option: str) -> None:
        data = self._hass.data[DOMAIN][self._entry_id]
        coord = self.coordinator.data or {}
        api = data["api"]

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
            presets = (coord.get("custom_effects") or data.get("custom_cache", []))
            match = next((e for e in presets if e.get("id") == effect_id), None)
            if match:
                effect = dict(match)
                if effect.get("mode") is None:
                    effect["mode"] = _get_effect_mode(match)

        if not effect:
            return

        effect["category"] = 2
        effect["mode"] = mode

        brightness = data.get("last_brightness", 255)
        speed = data.get("last_speed", 100)
        await api.preview_effect(effect, brightness, speed=speed)

        data["last_selected_custom_mode"] = mode

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
