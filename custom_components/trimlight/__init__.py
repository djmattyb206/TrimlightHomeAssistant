from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_CLIENT_ID, CONF_CLIENT_SECRET
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import TrimlightApi, TrimlightCredentials
from .const import (
    CONF_COMMIT_CUSTOM_PRESET,
    CONF_DEVICE_ID,
    DEFAULT_COMMIT_CUSTOM_PRESET,
    DOMAIN,
    build_builtin_presets_from_effects,
    build_builtin_presets_static,
)
from .coordinator import TrimlightCoordinator
from .data import TrimlightData
from .storage import get_debug_cache_path, load_preset_cache, setup_preset_cache_listener

PLATFORMS: list[str] = ["light", "select", "button", "sensor", "number"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    data = entry.data
    creds = TrimlightCredentials(
        client_id=data[CONF_CLIENT_ID],
        client_secret=data[CONF_CLIENT_SECRET],
        device_id=data[CONF_DEVICE_ID],
    )
    api = TrimlightApi(async_get_clientsession(hass), creds)
    coordinator = TrimlightCoordinator(hass, api)

    store, builtins, custom_cache = await load_preset_cache(hass, entry.entry_id)
    runtime = TrimlightData(
        api=api,
        coordinator=coordinator,
        store=store,
        debug_path=get_debug_cache_path(hass, entry.entry_id),
        builtins=builtins,
        custom_cache=custom_cache,
        builtins_refreshed=bool(builtins),
        commit_custom_preset=entry.options.get(
            CONF_COMMIT_CUSTOM_PRESET, DEFAULT_COMMIT_CUSTOM_PRESET
        ),
    )

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = runtime

    await coordinator.async_config_entry_first_refresh()
    if not runtime.builtins_refreshed:
        effects = (coordinator.data or {}).get("effects") or []
        builtins = build_builtin_presets_from_effects(effects)
        if not builtins:
            builtins = build_builtin_presets_static()
        if builtins:
            runtime.builtins = builtins
            runtime.builtins_refreshed = True

    setup_preset_cache_listener(hass, runtime, coordinator)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_entry_updated))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def _async_entry_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
