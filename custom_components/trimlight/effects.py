from __future__ import annotations

from typing import Any, Iterable, Mapping

from .models import BuiltinPreset, Effect

_EFFECT_MODE_KEYS = ("effectMode", "effect_mode", "effect_mode_id", "modeId")


def get_effect_mode(effect: Mapping[str, Any] | None) -> int | None:
    if not effect:
        return None
    mode = effect.get("mode")
    if mode is not None:
        try:
            return int(mode)
        except (TypeError, ValueError):
            return None
    for key in _EFFECT_MODE_KEYS:
        if effect.get(key) is not None:
            try:
                return int(effect.get(key))
            except (TypeError, ValueError):
                return None
    return None


def normalize_effect_mode(effect: dict[str, Any]) -> None:
    mode = get_effect_mode(effect)
    if mode is not None:
        effect["mode"] = mode


def normalize_custom_effects(effects: list[Effect]) -> list[Effect]:
    # Devices may report custom effects as category 1 or 2 depending on firmware/API.
    custom_effects = [e for e in effects if e.get("category") in (1, 2)]
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


def find_custom_preset_by_name(
    presets: Iterable[Effect], name: str | None
) -> Effect | None:
    if not name:
        return None
    wanted = name.strip()
    if not wanted:
        return None

    direct = next((e for e in presets if (e.get("name") or "").strip() == wanted), None)
    if direct is not None:
        return direct

    if " (id " in wanted and wanted.endswith(")"):
        base_name = wanted.rsplit(" (id ", 1)[0].strip()
        if base_name:
            return next((e for e in presets if (e.get("name") or "").strip() == base_name), None)

    return None


def _pixel_signature(pixels: Any) -> tuple[tuple[int, int, int, bool], ...] | None:
    if not isinstance(pixels, list):
        return None

    rows: list[tuple[int, int, int, bool]] = []
    for pixel in pixels:
        if not isinstance(pixel, Mapping):
            continue
        rows.append(
            (
                int(pixel.get("index", 0) or 0),
                int(pixel.get("count", 0) or 0),
                int(pixel.get("color", 0) or 0),
                bool(pixel.get("disable", False)),
            )
        )

    return tuple(rows) if rows else None


def find_custom_preset_by_state(
    presets: Iterable[Effect],
    current_effect: Mapping[str, Any] | None,
    effect_id: int | None = None,
) -> Effect | None:
    if effect_id not in (None, -1):
        match = find_custom_preset_by_id(presets, effect_id)
        if match is not None:
            return match

    current_effect = current_effect or {}
    if not current_effect:
        return None

    current_pixels = _pixel_signature(current_effect.get("pixels"))
    current_mode = get_effect_mode(current_effect)
    current_speed = current_effect.get("speed")
    current_brightness = current_effect.get("brightness")

    candidates = list(presets)

    if current_pixels is not None:
        pixel_matches = [e for e in candidates if _pixel_signature(e.get("pixels")) == current_pixels]
        if len(pixel_matches) == 1:
            return pixel_matches[0]
        if pixel_matches:
            candidates = pixel_matches

    if current_mode is not None:
        mode_matches = [e for e in candidates if get_effect_mode(e) == current_mode]
        if len(mode_matches) == 1:
            return mode_matches[0]
        if mode_matches:
            candidates = mode_matches

    if current_speed is not None:
        speed_matches = [
            e for e in candidates if e.get("speed") is not None and int(e.get("speed")) == int(current_speed)
        ]
        if len(speed_matches) == 1:
            return speed_matches[0]
        if speed_matches:
            candidates = speed_matches

    if current_brightness is not None:
        brightness_matches = [
            e
            for e in candidates
            if e.get("brightness") is not None and int(e.get("brightness")) == int(current_brightness)
        ]
        if len(brightness_matches) == 1:
            return brightness_matches[0]
        if brightness_matches:
            candidates = brightness_matches

    return candidates[0] if len(candidates) == 1 else None


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


def find_builtin_preset_by_name(
    builtins: Iterable[BuiltinPreset], name: str | None
) -> BuiltinPreset | None:
    if not name:
        return None
    wanted = name.strip()
    if not wanted:
        return None
    for preset in builtins:
        if (preset.get("name") or "").strip() == wanted:
            return preset
    return None


def effect_has_pixels(effect: Mapping[str, Any] | None) -> bool:
    if not effect:
        return False
    pixels = effect.get("pixels")
    return isinstance(pixels, list) and len(pixels) > 0


def is_builtin_like_state(
    builtins: Iterable[BuiltinPreset],
    current_effect: Mapping[str, Any] | None,
    current_category: int | None,
    effect_id: int | None,
) -> bool:
    current_effect = current_effect or {}
    if current_category == 0:
        return True

    current_name = (current_effect.get("name") or "").strip()
    if find_builtin_preset_by_name(builtins, current_name) is not None:
        return True

    current_mode = get_effect_mode(current_effect)
    builtin_match = find_builtin_preset(builtins, effect_id, current_mode)
    if builtin_match is None:
        return False

    if current_category == 1 and not effect_has_pixels(current_effect):
        return True

    if not effect_has_pixels(current_effect) and (
        current_effect.get("pixelLen") is not None or current_effect.get("reverse") is not None
    ):
        return True

    return False


def matches_builtin_target(
    builtins: Iterable[BuiltinPreset],
    current_effect: Mapping[str, Any] | None,
    current_category: int | None,
    effect_id: int | None,
    *,
    target_name: str | None = None,
    target_id: int | None = None,
    target_mode: int | None = None,
) -> bool:
    current_effect = current_effect or {}
    current_name = (current_effect.get("name") or "").strip()
    current_mode = get_effect_mode(current_effect)

    if target_name and current_name == target_name:
        return True

    if not is_builtin_like_state(builtins, current_effect, current_category, effect_id):
        return False

    match = find_builtin_preset_by_name(builtins, current_name)
    if match is None:
        match = find_builtin_preset(builtins, effect_id, current_mode)
    if match is None:
        return False

    if target_name and (match.get("name") or "").strip() == target_name:
        return True
    if target_id is not None and match.get("id") == target_id:
        return True
    if target_mode is not None and match.get("mode") == target_mode:
        return True
    return False


def matches_custom_target(
    presets: Iterable[Effect],
    current_effect: Mapping[str, Any] | None,
    current_category: int | None,
    effect_id: int | None,
    *,
    target_name: str | None = None,
    target_id: int | None = None,
    builtins: Iterable[BuiltinPreset] | None = None,
) -> bool:
    current_effect = current_effect or {}

    if builtins is not None and is_builtin_like_state(builtins, current_effect, current_category, effect_id):
        return False

    if current_category not in (1, 2) and effect_id in (None, -1):
        return False

    if target_id is not None and effect_id == target_id:
        return True

    match = find_custom_preset_by_state(presets, current_effect, effect_id)
    if match is None:
        return False

    if target_id is not None and match.get("id") == target_id:
        return True
    if target_name and ((match.get("name") or "").strip() == target_name):
        return True
    return False


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
