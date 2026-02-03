from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import TrimlightCoordinator


class TrimlightEntity(CoordinatorEntity[TrimlightCoordinator]):
    def __init__(self, hass: HomeAssistant, entry_id: str, coordinator: TrimlightCoordinator) -> None:
        super().__init__(coordinator)
        self._hass = hass
        self._entry_id = entry_id

    @property
    def device_info(self) -> dict:
        data = self.coordinator.data or {}
        payload = data.get("payload") or {}
        device_id = payload.get("deviceId")
        if not device_id:
            device_id = self._hass.data[DOMAIN][self._entry_id]["api"]._creds.device_id

        return {
            "identifiers": {(DOMAIN, device_id)},
            "name": "Trimlight",
            "manufacturer": "Trimlight",
            "model": "EDGE",
        }
