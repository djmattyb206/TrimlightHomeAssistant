from __future__ import annotations

from typing import Any, Iterable, Mapping

from .models import BuiltinPreset, Effect

_EFFECT_MODE_KEYS = ("effectMode", "effect_mode", "effect_mode_id", "modeId")


def get_effect_mode(effect: Mapping[str, Any] | None) -> int | None:
    if not effect:
        return None
    mode = effect.get("mode")
    if mode is not None:
        return int(mode)
    for key in _EFFECT_MODE_KEYS:
        if effect.get(key) is not None:
            return int(effect.get(key))
    return None


def normalize_effect_mode(effect: dict[str, Any]) -> None:
    mode = get_effect_mode(effect)
    if mode is not None:
        effect["mode"] = mode


def normalize_custom_effects(effects: list[Effect]) -> list[Effect]:
    custom_effects = [e for e in effects if e.get("category") == 2]
    for effect in custom_effects:
        normalize_effect_mode(effect)
    custom_effects.sort(key=lambda e: e.get("id", 9999))
    return custom_effects


def find_custom_preset_by_id(
    presets: Iterable[Effect], effect_id: int | None
) -> Effect | None:
    if effect_id is None:
        return None
    return next((e for e in presets if e.get("id") == effect_id), None)


def find_builtin_preset(
    builtins: Iterable[BuiltinPreset], effect_id: int | None, effect_mode: int | None = None
) -> BuiltinPreset | None:
    if effect_id is None and effect_mode is None:
        return None
    for preset in builtins:
        if effect_id is not None and (preset.get("id") == effect_id or preset.get("mode") == effect_id):
            return preset
        if effect_mode is not None and preset.get("mode") == effect_mode:
            return preset
    return None


def infer_builtin_preview_params(
    effect_id: int,
    current_effect: Mapping[str, Any] | None,
    effects: Iterable[Mapping[str, Any]],
) -> tuple[int, bool]:
    pixel_len = None
    reverse = None

    if current_effect and current_effect.get("category") == 0:
        pixel_len = current_effect.get("pixelLen")
        reverse = current_effect.get("reverse")

    if pixel_len is None or reverse is None:
        current_mode = get_effect_mode(current_effect) if current_effect else None
        for effect in effects:
            if effect.get("category") != 0:
                continue
            if (
                effect.get("id") == effect_id
                or effect.get("mode") == effect_id
                or (current_mode is not None and effect.get("mode") == current_mode)
            ):
                if pixel_len is None:
                    pixel_len = effect.get("pixelLen")
                if reverse is None:
                    reverse = effect.get("reverse")

    pixel_len = 30 if pixel_len is None else int(pixel_len)
    reverse = False if reverse is None else bool(reverse)
    return pixel_len, reverse
