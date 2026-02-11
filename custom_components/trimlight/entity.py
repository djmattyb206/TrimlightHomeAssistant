from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, VERIFY_REFRESH_DELAY_SECONDS
from .coordinator import TrimlightCoordinator
from .data import TrimlightData, get_data


class TrimlightEntity(CoordinatorEntity[TrimlightCoordinator]):
    def __init__(self, hass: HomeAssistant, entry_id: str, coordinator: TrimlightCoordinator) -> None:
        super().__init__(coordinator)
        self._hass = hass
        self._entry_id = entry_id

    @property
    def _data(self) -> TrimlightData:
        return get_data(self._hass, self._entry_id)

    @property
    def device_info(self) -> dict:
        data = self.coordinator.data or {}
        payload = data.get("payload") or {}
        device_id = payload.get("deviceId")
        if not device_id:
            device_id = self._data.api._creds.device_id

        return {
            "identifiers": {(DOMAIN, device_id)},
            "name": "Trimlight",
            "manufacturer": "Trimlight",
            "model": "EDGE",
        }

    def _schedule_verification_refresh(self) -> None:
        data = self._data
        handle = data.verify_refresh_handle
        if handle:
            handle.cancel()

        def _refresh() -> None:
            self._hass.async_create_task(self.coordinator.async_refresh())

        data.verify_refresh_handle = self._hass.loop.call_later(
            VERIFY_REFRESH_DELAY_SECONDS, _refresh
        )
