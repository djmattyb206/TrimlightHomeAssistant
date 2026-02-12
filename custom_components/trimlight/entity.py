from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, VERIFY_REFRESH_DELAY_SECONDS
from .coordinator import TrimlightCoordinator
from .data import TrimlightData, get_data

_LOGGER = logging.getLogger(__name__)


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

    def _schedule_verification_refresh(
        self,
        *,
        correlation_id: str | None = None,
        source: str | None = None,
    ) -> None:
        data = self._data
        handle = data.verify_refresh_handle
        if handle:
            handle.cancel()
            if correlation_id:
                _LOGGER.info(
                    "Verification refresh rescheduled: cid=%s source=%s delay_s=%s",
                    correlation_id,
                    source,
                    VERIFY_REFRESH_DELAY_SECONDS,
                )

        if correlation_id:
            _LOGGER.info(
                "Verification refresh scheduled: cid=%s source=%s delay_s=%s",
                correlation_id,
                source,
                VERIFY_REFRESH_DELAY_SECONDS,
            )

        async def _do_refresh() -> None:
            if correlation_id:
                _LOGGER.info("Verification refresh firing: cid=%s source=%s", correlation_id, source)
            try:
                await self.coordinator.async_refresh()
                if correlation_id:
                    _LOGGER.info(
                        "Verification refresh completed: cid=%s source=%s",
                        correlation_id,
                        source,
                    )
            except Exception as exc:  # noqa: BLE001
                if correlation_id:
                    _LOGGER.warning(
                        "Verification refresh failed: cid=%s source=%s error=%s",
                        correlation_id,
                        source,
                        exc,
                    )
                else:
                    _LOGGER.warning("Verification refresh failed: %s", exc)

        def _refresh() -> None:
            self._hass.async_create_task(_do_refresh())

        data.verify_refresh_handle = self._hass.loop.call_later(
            VERIFY_REFRESH_DELAY_SECONDS, _refresh
        )
