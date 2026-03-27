from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import cast

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .api import TrimlightApi
from .const import DOMAIN
from .coordinator import TrimlightCoordinator
from .models import BuiltinPreset, Effect, Pixel


@dataclass(slots=True)
class PendingTransition:
    target_kind: str
    target_name: str
    target_id: int | None
    target_mode: int | None
    source_kind: str | None
    attempt: int
    started_monotonic: float
    expires_monotonic: float
    correlation_id: str
    confirmed_monotonic: float | None = None


@dataclass(slots=True)
class TrimlightData:
    api: TrimlightApi
    coordinator: TrimlightCoordinator
    store: Store
    debug_path: str
    debug_log_path: str
    builtins: list[BuiltinPreset]
    custom_cache: list[Effect]
    builtins_refreshed: bool
    commit_custom_preset: bool
    debug_logging: bool
    last_brightness: int = 255
    last_speed: int = 100
    last_selected_preset: str | None = None
    last_selected_custom_preset: str | None = None
    last_selected_custom_mode: int | None = None
    last_known_preset: str | None = None
    last_known_builtin_preset: str | None = None
    last_known_custom_preset: str | None = None
    last_known_custom_pixels: list[Pixel] | None = None
    forced_on_until: float | None = None
    forced_off_until: float | None = None
    verify_refresh_handle: asyncio.TimerHandle | None = None
    builtin_reapply_handle: asyncio.TimerHandle | None = None
    custom_reapply_handle: asyncio.TimerHandle | None = None
    speed_reapply_handle: asyncio.TimerHandle | None = None
    pending_transition: PendingTransition | None = None
    pending_speed: int | None = None
    pending_speed_until: float | None = None
    debug_log_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


def get_data(hass: HomeAssistant, entry_id: str) -> TrimlightData:
    return cast(TrimlightData, hass.data[DOMAIN][entry_id])
