from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import TrimlightApi
from .const import DEFAULT_POLL_INTERVAL_SECONDS


class TrimlightCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(self, hass: HomeAssistant, api: TrimlightApi) -> None:
        self._logger = logging.getLogger(__name__)
        super().__init__(
            hass,
            logger=self._logger,
            name="Trimlight",
            update_interval=timedelta(seconds=DEFAULT_POLL_INTERVAL_SECONDS),
        )
        self._api = api

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            data = await self._api.get_device_detail()
        except Exception as exc:  # noqa: BLE001
            raise UpdateFailed(str(exc)) from exc

        payload = (data.get("payload") or {}) if isinstance(data, dict) else {}
        effects = (payload.get("effects") or []) if isinstance(payload, dict) else []
        custom_effects = [e for e in effects if e.get("category") == 2]
        custom_effects.sort(key=lambda e: e.get("id", 9999))

        current_effect = payload.get("currentEffect") or {}
        current_effect_id = current_effect.get("id")
        current_category = current_effect.get("category")
        brightness = current_effect.get("brightness")

        return {
            "raw": data,
            "payload": payload,
            "effects": effects,
            "custom_effects": custom_effects,
            "current_effect": current_effect,
            "current_effect_id": current_effect_id,
            "current_effect_category": current_category,
            "brightness": brightness,
            "switch_state": payload.get("switchState"),
        }
