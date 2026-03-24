from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import TrimlightApi
from .const import DEFAULT_POLL_INTERVAL_SECONDS
from .effects import normalize_custom_effects, normalize_effect_mode


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
        custom_effects = normalize_custom_effects(effects)

        current_effect = dict(payload.get("currentEffect") or {})
        normalize_effect_mode(current_effect)
        current_effect_id = current_effect.get("id")
        current_category = current_effect.get("category")
        brightness = current_effect.get("brightness")
        switch_state = payload.get("switchState")

        previous = self.data or {}
        # Some controllers briefly return an empty payload right after a
        # successful power-on. Preserve the last known on/effect state instead
        # of clobbering Home Assistant with unknown values.
        if (
            switch_state is None
            and not current_effect
            and previous.get("switch_state") == 1
        ):
            self._logger.warning(
                "Device detail returned incomplete state after power-on; preserving previous coordinator state"
            )
            preserved = dict(previous)
            preserved.update(
                {
                    "raw": data,
                    "payload": payload,
                    "effects": effects or previous.get("effects", []),
                    "custom_effects": custom_effects or previous.get("custom_effects", []),
                }
            )
            return preserved

        return {
            "raw": data,
            "payload": payload,
            "effects": effects,
            "custom_effects": custom_effects,
            "current_effect": current_effect,
            "current_effect_id": current_effect_id,
            "current_effect_category": current_category,
            "brightness": brightness,
            "switch_state": switch_state,
        }
