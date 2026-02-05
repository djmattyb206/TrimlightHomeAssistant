from __future__ import annotations

import base64
import hashlib
import hmac
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import aiohttp
import async_timeout


@dataclass(frozen=True)
class TrimlightCredentials:
    client_id: str
    client_secret: str
    device_id: str


class TrimlightApi:
    def __init__(
        self,
        session: aiohttp.ClientSession,
        creds: TrimlightCredentials,
        base_url: str = "https://trimlight.ledhue.com/trimlight",
        timeout_s: float = 10.0,
    ) -> None:
        self._session = session
        self._creds = creds
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s

    def _timestamp_ms(self) -> int:
        return int(time.time() * 1000)

    def _access_token(self, timestamp_ms: int) -> str:
        msg = f"Trimlight|{self._creds.client_id}|{timestamp_ms}".encode("utf-8")
        key = self._creds.client_secret.encode("utf-8")
        digest = hmac.new(key, msg, hashlib.sha256).digest()
        return base64.b64encode(digest).decode("ascii")

    def _headers(self) -> dict[str, str]:
        ts = self._timestamp_ms()
        return {
            "authorization": self._access_token(ts),
            "S-ClientId": self._creds.client_id,
            "S-Timestamp": str(ts),
            "Content-Type": "application/json",
        }

    def _url(self, path: str) -> str:
        return f"{self._base_url}{path}"

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = self._url(path)
        headers = self._headers()
        async with async_timeout.timeout(self._timeout_s):
            async with self._session.request(
                method,
                url,
                headers=headers,
                params=params,
                json=payload,
            ) as resp:
                resp.raise_for_status()
                return await resp.json()

    async def get_devices(self, page: int = 0) -> dict[str, Any]:
        path = "/v1/oauth/resources/devices"
        try:
            return await self._request("GET", path, params={"page": page})
        except aiohttp.ClientResponseError as exc:
            if exc.status != 405:
                raise
        except aiohttp.ContentTypeError:
            pass

        return await self._request("POST", path, payload={"page": page})

    async def get_device_detail(self) -> dict[str, Any]:
        payload = {
            "deviceId": self._creds.device_id,
            "currentDate": self._current_date_payload(),
        }
        return await self._request("POST", "/v1/oauth/resources/device/get", payload=payload)

    async def set_switch_state(self, state: int) -> dict[str, Any]:
        payload = {"deviceId": self._creds.device_id, "payload": {"switchState": int(state)}}
        return await self._request("POST", "/v1/oauth/resources/device/update", payload=payload)

    async def preview_builtin(
        self,
        mode: int,
        *,
        speed: int = 100,
        brightness: int = 200,
        pixel_len: int = 30,
        reverse: bool = False,
    ) -> dict[str, Any]:
        payload = {
            "deviceId": self._creds.device_id,
            "payload": {
                "category": 0,
                "mode": int(mode),
                "speed": int(speed),
                "brightness": int(brightness),
                "pixelLen": int(pixel_len),
                "reverse": bool(reverse),
            },
        }
        return await self._request("POST", "/v1/oauth/resources/device/effect/preview", payload=payload)

    async def preview_solid(self, rgb_hex: str, brightness: int = 255) -> dict[str, Any]:
        rgb_hex = rgb_hex.strip().lstrip("#")
        color_int = int(rgb_hex, 16)
        payload = {
            "deviceId": self._creds.device_id,
            "payload": {
                "category": 1,
                "mode": 0,
                "speed": 0,
                "brightness": int(brightness),
                "pixels": [{"index": 0, "count": 60, "color": color_int, "disable": False}],
            },
        }
        return await self._request("POST", "/v1/oauth/resources/device/effect/preview", payload=payload)

    async def preview_effect(
        self, effect: dict[str, Any], brightness: int, speed: int | None = None
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "deviceId": self._creds.device_id,
            "payload": {
                "category": effect.get("category"),
                "mode": effect.get("mode"),
                "speed": int(effect.get("speed", 0)) if speed is None else int(speed),
                "brightness": int(brightness),
            },
        }

        if "pixels" in effect:
            payload["payload"]["pixels"] = effect.get("pixels")
        if "pixelLen" in effect:
            payload["payload"]["pixelLen"] = effect.get("pixelLen")
        if "reverse" in effect:
            payload["payload"]["reverse"] = effect.get("reverse")

        return await self._request("POST", "/v1/oauth/resources/device/effect/preview", payload=payload)

    async def run_effect(self, effect_id: int) -> dict[str, Any]:
        payload = {"deviceId": self._creds.device_id, "payload": {"id": int(effect_id)}}
        return await self._request("POST", "/v1/oauth/resources/device/effect/view", payload=payload)

    @staticmethod
    def _current_date_payload() -> dict[str, int]:
        now = datetime.now()
        weekday = ((now.weekday() + 1) % 7) + 1  # Sunday=1 ... Saturday=7
        return {
            "year": now.year - 2000,
            "month": now.month,
            "day": now.day,
            "weekday": weekday,
            "hours": now.hour,
            "minutes": now.minute,
            "seconds": now.second,
        }
