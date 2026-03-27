from __future__ import annotations

import logging
import time

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, VERIFY_REFRESH_DELAY_SECONDS
from .coordinator import TrimlightCoordinator
from .data import PendingTransition, TrimlightData, get_data
from .debug import async_log_event

_LOGGER = logging.getLogger(__name__)
_PENDING_TRANSITION_STABLE_HOLD_SECONDS = 12.0


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

    def _is_effectively_on(self) -> bool | None:
        data = self.coordinator.data or {}
        switch_state = data.get("switch_state")
        runtime = self._data
        now = time.monotonic()

        forced_off_until = runtime.forced_off_until
        if forced_off_until is not None and now < forced_off_until:
            return False

        forced_on_until = runtime.forced_on_until
        if forced_on_until is not None and now < forced_on_until:
            return True

        pending_transition = self._active_pending_transition()
        pending_speed_active = self._has_active_pending_speed()
        if (
            switch_state in (None, 0)
            and (pending_transition is not None or pending_speed_active)
            and self._has_meaningful_effect_state()
        ):
            return True

        if switch_state is None:
            return None
        return int(switch_state) != 0

    def _active_pending_transition(self) -> PendingTransition | None:
        runtime = self._data
        pending = runtime.pending_transition
        if pending is None:
            return None
        if time.monotonic() >= pending.expires_monotonic:
            runtime.pending_transition = None
            return None
        return pending

    def _set_pending_transition(
        self,
        *,
        target_kind: str,
        target_name: str,
        target_id: int | None,
        target_mode: int | None,
        source_kind: str | None,
        correlation_id: str,
        expires_in_s: float,
        attempt: int = 0,
    ) -> None:
        now = time.monotonic()
        self._data.pending_transition = PendingTransition(
            target_kind=target_kind,
            target_name=target_name,
            target_id=target_id,
            target_mode=target_mode,
            source_kind=source_kind,
            attempt=attempt,
            started_monotonic=now,
            expires_monotonic=now + float(expires_in_s),
            correlation_id=correlation_id,
            confirmed_monotonic=None,
        )

    def _clear_pending_transition(self) -> None:
        self._data.pending_transition = None

    def _has_active_pending_speed(self) -> bool:
        runtime = self._data
        pending_speed = runtime.pending_speed
        pending_until = runtime.pending_speed_until
        if pending_speed is None or pending_until is None:
            return False
        if time.monotonic() >= pending_until:
            runtime.pending_speed = None
            runtime.pending_speed_until = None
            return False
        return True

    def _has_meaningful_effect_state(self) -> bool:
        data = self.coordinator.data or {}
        current_effect = data.get("current_effect") or {}
        pixels = current_effect.get("pixels")
        if isinstance(pixels, list) and len(pixels) > 0:
            return True
        if any(
            current_effect.get(key) is not None
            for key in ("id", "name", "category", "mode", "speed", "brightness", "pixelLen", "reverse")
        ):
            return True
        if any(
            data.get(key) is not None
            for key in (
                "current_effect_id",
                "current_effect_category",
                "current_effect_mode",
                "current_effect_speed",
                "current_effect_brightness",
                "current_effect_pixel_len",
                "current_effect_reverse",
            )
        ):
            return True
        pixels = data.get("current_effect_pixels")
        if isinstance(pixels, list) and len(pixels) > 0:
            return True
        return bool(self._data.last_selected_preset or self._data.last_known_preset)

    def _cancel_pending_followups(self) -> None:
        data = self._data
        for attr_name in (
            "builtin_reapply_handle",
            "custom_reapply_handle",
            "speed_reapply_handle",
            "verify_refresh_handle",
        ):
            handle = getattr(data, attr_name)
            if handle is not None:
                handle.cancel()
                setattr(data, attr_name, None)
        data.pending_speed = None
        data.pending_speed_until = None

    def _keep_pending_transition_visible_after_match(
        self,
        pending: PendingTransition,
        *,
        hold_s: float = _PENDING_TRANSITION_STABLE_HOLD_SECONDS,
    ) -> bool:
        now = time.monotonic()
        confirmed = pending.confirmed_monotonic
        if confirmed is None:
            pending.confirmed_monotonic = now
            return True
        if now - confirmed < float(hold_s):
            return True
        self._clear_pending_transition()
        return False

    def _schedule_verification_refresh(
        self,
        *,
        correlation_id: str | None = None,
        source: str | None = None,
        delay_s: float | None = None,
    ) -> None:
        data = self._data
        delay_s = VERIFY_REFRESH_DELAY_SECONDS if delay_s is None else float(delay_s)
        handle = data.verify_refresh_handle
        was_rescheduled = handle is not None
        if handle:
            handle.cancel()
            if correlation_id:
                _LOGGER.info(
                    "Verification refresh rescheduled: cid=%s source=%s delay_s=%s",
                    correlation_id,
                    source,
                    delay_s,
                )

        if correlation_id:
            _LOGGER.info(
                "Verification refresh scheduled: cid=%s source=%s delay_s=%s",
                correlation_id,
                source,
                delay_s,
            )
        self._hass.async_create_task(
            async_log_event(
                self._hass,
                data,
                "verification_refresh_scheduled",
                correlation_id=correlation_id,
                coordinator_data=self.coordinator.data or {},
                source=source,
                delay_s=delay_s,
                rescheduled=was_rescheduled,
            )
        )

        async def _do_refresh() -> None:
            if correlation_id:
                _LOGGER.info("Verification refresh firing: cid=%s source=%s", correlation_id, source)
            await async_log_event(
                self._hass,
                data,
                "verification_refresh_firing",
                correlation_id=correlation_id,
                coordinator_data=self.coordinator.data or {},
                source=source,
            )
            try:
                await self.coordinator.async_refresh()
                if correlation_id:
                    _LOGGER.info(
                        "Verification refresh completed: cid=%s source=%s",
                        correlation_id,
                        source,
                    )
                await async_log_event(
                    self._hass,
                    data,
                    "verification_refresh_completed",
                    correlation_id=correlation_id,
                    coordinator_data=self.coordinator.data or {},
                    source=source,
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
                await async_log_event(
                    self._hass,
                    data,
                    "verification_refresh_failed",
                    correlation_id=correlation_id,
                    coordinator_data=self.coordinator.data or {},
                    source=source,
                    error=str(exc),
                )

        def _refresh() -> None:
            self._hass.async_create_task(_do_refresh())

        data.verify_refresh_handle = self._hass.loop.call_later(
            delay_s, _refresh
        )
