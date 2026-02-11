from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import build_builtin_presets_from_effects, build_builtin_presets_static
from .data import get_data
from .entity import TrimlightEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data = get_data(hass, entry.entry_id)
    coordinator = data.coordinator
    async_add_entities([TrimlightRefreshButton(hass, entry.entry_id, coordinator)])


class TrimlightRefreshButton(TrimlightEntity, ButtonEntity):
    _attr_name = "Trimlight Refresh Presets"

    def __init__(self, hass: HomeAssistant, entry_id: str, coordinator) -> None:
        super().__init__(hass, entry_id, coordinator)
        self._attr_unique_id = f"{entry_id}_refresh_presets"

    async def async_press(self) -> None:
        data = self._data

        if not data.builtins_refreshed:
            effects = (data.coordinator.data or {}).get("effects") or []
            builtins = build_builtin_presets_from_effects(effects)
            if not builtins:
                builtins = build_builtin_presets_static()
            if builtins:
                data.builtins = builtins
                data.builtins_refreshed = True

        await data.coordinator.async_refresh()
