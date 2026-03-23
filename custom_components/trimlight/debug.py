from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any, Mapping

from homeassistant.core import HomeAssistant

from .effects import get_effect_mode

if TYPE_CHECKING:
    from .data import TrimlightData

_LOGGER = logging.getLogger(__name__)


def get_debug_log_path(hass: HomeAssistant, entry_id: str) -> str:
    return hass.config.path(f"trimlight_debug_{entry_id}.jsonl")


def snapshot_coordinator_state(coordinator_data: Mapping[str, Any] | None) -> dict[str, Any]:
    data = coordinator_data or {}
    current_effect = dict(data.get("current_effect") or {})
    return {
        "switch_state": data.get("switch_state"),
        "current_effect_id": data.get("current_effect_id"),
        "current_effect_category": data.get("current_effect_category"),
        "current_effect_name": current_effect.get("name"),
        "current_effect_mode": get_effect_mode(current_effect),
        "current_effect_speed": current_effect.get("speed"),
        "current_effect_brightness": current_effect.get("brightness"),
        "current_effect_pixel_len": current_effect.get("pixelLen"),
        "current_effect_reverse": current_effect.get("reverse"),
        "current_effect_pixels": current_effect.get("pixels"),
    }


def snapshot_runtime_state(data: TrimlightData) -> dict[str, Any]:
    return {
        "last_brightness": data.last_brightness,
        "last_speed": data.last_speed,
        "last_selected_preset": data.last_selected_preset,
        "last_selected_custom_preset": data.last_selected_custom_preset,
        "last_selected_custom_mode": data.last_selected_custom_mode,
        "last_known_preset": data.last_known_preset,
        "last_known_builtin_preset": data.last_known_builtin_preset,
        "last_known_custom_preset": data.last_known_custom_preset,
    }


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return repr(value)


def _append_jsonl(path: str, payload: dict[str, Any]) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False))
        f.write("\n")


async def async_log_event(
    hass: HomeAssistant,
    data: TrimlightData,
    event: str,
    *,
    correlation_id: str | None = None,
    coordinator_data: Mapping[str, Any] | None = None,
    **details: Any,
) -> None:
    if not data.debug_logging:
        return

    payload: dict[str, Any] = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "event": event,
        "device_id": data.api._creds.device_id,
        "state": snapshot_coordinator_state(
            coordinator_data if coordinator_data is not None else (data.coordinator.data or {})
        ),
        "runtime": snapshot_runtime_state(data),
    }
    if correlation_id:
        payload["correlation_id"] = correlation_id
    if details:
        payload["details"] = _json_safe(details)

    try:
        async with data.debug_log_lock:
            await hass.async_add_executor_job(_append_jsonl, data.debug_log_path, _json_safe(payload))
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("Failed to write Trimlight debug log: %s", exc)
