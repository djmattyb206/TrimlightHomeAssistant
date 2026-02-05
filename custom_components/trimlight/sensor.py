from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import TrimlightEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    async_add_entities([TrimlightCurrentPresetSensor(hass, entry.entry_id, coordinator)])


class TrimlightCurrentPresetSensor(TrimlightEntity, SensorEntity):
    _attr_name = "Trimlight Current Preset"

    def __init__(self, hass: HomeAssistant, entry_id: str, coordinator) -> None:
        super().__init__(hass, entry_id, coordinator)
        self._attr_unique_id = f"{entry_id}_current_preset"

    @property
    def native_value(self) -> str:
        data = self.coordinator.data or {}
        switch_state = data.get("switch_state")
        if switch_state is None or int(switch_state) == 0:
            return "Off"

        current_effect = data.get("current_effect") or {}
        current_name = (current_effect.get("name") or "").strip()
        if current_name:
            return current_name

        effect_id = data.get("current_effect_id")
        current_category = data.get("current_effect_category")

        # Prefer custom preset if currently active
        if current_category == 2:
            presets = (data.get("custom_effects") or self._hass.data[DOMAIN][self._entry_id].get("custom_cache", []))
            for e in presets:
                if e.get("id") == effect_id:
                    return (e.get("name") or "").strip() or "(no name)"

        # Fall back to built-in preset (category 0)
        builtins = self._hass.data[DOMAIN][self._entry_id].get("builtins", [])
        for b in builtins:
            if b.get("id") == effect_id or b.get("mode") == effect_id:
                return b.get("name")

        return "Unknown"
