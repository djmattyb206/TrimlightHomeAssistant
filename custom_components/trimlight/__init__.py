from __future__ import annotations

import json

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_CLIENT_ID, CONF_CLIENT_SECRET
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store

from .api import TrimlightApi, TrimlightCredentials
from .const import CONF_DEVICE_ID, DOMAIN, build_builtin_presets_from_effects
from .coordinator import TrimlightCoordinator

PLATFORMS: list[str] = ["light", "select", "button"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    data = entry.data
    creds = TrimlightCredentials(
        client_id=data[CONF_CLIENT_ID],
        client_secret=data[CONF_CLIENT_SECRET],
        device_id=data[CONF_DEVICE_ID],
    )
    api = TrimlightApi(async_get_clientsession(hass), creds)
    coordinator = TrimlightCoordinator(hass, api)

    store = Store(hass, 1, f"trimlight_presets_{entry.entry_id}")
    stored = await store.async_load() or {}

    debug_path = hass.config.path(f"trimlight_presets_{entry.entry_id}.json")

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "api": api,
        "coordinator": coordinator,
        "builtins": stored.get("builtins", []),
        "custom_cache": stored.get("custom", []),
        "builtins_refreshed": bool(stored.get("builtins")),
        "last_brightness": 255,
        "store": store,
        "debug_path": debug_path,
    }

    await coordinator.async_config_entry_first_refresh()
    if not hass.data[DOMAIN][entry.entry_id]["builtins_refreshed"]:
        effects = (coordinator.data or {}).get("effects") or []
        builtins = build_builtin_presets_from_effects(effects)
        if builtins:
            hass.data[DOMAIN][entry.entry_id]["builtins"] = builtins
            hass.data[DOMAIN][entry.entry_id]["builtins_refreshed"] = True

    def _write_debug_cache(path: str, payload: dict) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

    async def _save_cache() -> None:
        entry_data = hass.data[DOMAIN][entry.entry_id]
        custom = (coordinator.data or {}).get("custom_effects") or entry_data.get("custom_cache", [])
        payload = {"builtins": entry_data.get("builtins", []), "custom": custom}
        entry_data["custom_cache"] = custom
        await entry_data["store"].async_save(payload)
        await hass.async_add_executor_job(_write_debug_cache, entry_data["debug_path"], payload)

    def _schedule_cache_write() -> None:
        hass.async_create_task(_save_cache())

    coordinator.async_add_listener(_schedule_cache_write)
    _schedule_cache_write()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
