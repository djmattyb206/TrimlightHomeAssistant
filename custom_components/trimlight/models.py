from __future__ import annotations

from dataclasses import dataclass
from typing import TypedDict


class Pixel(TypedDict, total=False):
    index: int
    count: int
    color: int
    disable: bool


class Effect(TypedDict, total=False):
    id: int
    name: str
    category: int
    mode: int
    speed: int
    brightness: int
    pixelLen: int
    reverse: bool
    pixels: list[Pixel]
    effectMode: int
    effect_mode: int
    effect_mode_id: int
    modeId: int


class BuiltinPreset(TypedDict):
    id: int
    mode: int
    name: str


class CustomPreset(TypedDict, total=False):
    id: int
    name: str
    category: int
    mode: int
    speed: int
    brightness: int
    pixels: list[Pixel]


class DevicePayload(TypedDict, total=False):
    deviceId: str
    switchState: int
    currentEffect: Effect
    effects: list[Effect]


class DeviceDetailResponse(TypedDict, total=False):
    payload: DevicePayload


@dataclass(slots=True)
class Preset:
    id: int
    name: str
    mode: int | None = None
    category: int | None = None
