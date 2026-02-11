from __future__ import annotations

import json
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .coordinator import TrimlightCoordinator
from .data import TrimlightData

STORAGE_VERSION = 1


def get_debug_cache_path(hass: HomeAssistant, entry_id: str) -> str:
    return hass.config.path(f"trimlight_presets_{entry_id}.json")


async def load_preset_cache(
    hass: HomeAssistant, entry_id: str
) -> tuple[Store, list[dict[str, Any]], list[dict[str, Any]]]:
    store = Store(hass, STORAGE_VERSION, f"trimlight_presets_{entry_id}")
    stored = await store.async_load() or {}
    builtins = stored.get("builtins", []) or []
    custom = stored.get("custom", []) or []
    return store, builtins, custom


def _write_debug_cache(path: str, payload: dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


async def save_preset_cache(
    hass: HomeAssistant, data: TrimlightData, coordinator_data: dict[str, Any]
) -> None:
    custom = (coordinator_data.get("custom_effects") or data.custom_cache)
    payload = {"builtins": data.builtins, "custom": custom}
    data.custom_cache = custom
    await data.store.async_save(payload)
    await hass.async_add_executor_job(_write_debug_cache, data.debug_path, payload)


def setup_preset_cache_listener(
    hass: HomeAssistant, data: TrimlightData, coordinator: TrimlightCoordinator
) -> None:
    async def _save_cache() -> None:
        await save_preset_cache(hass, data, coordinator.data or {})

    def _schedule_cache_write() -> None:
        hass.async_create_task(_save_cache())

    coordinator.async_add_listener(_schedule_cache_write)
    _schedule_cache_write()
