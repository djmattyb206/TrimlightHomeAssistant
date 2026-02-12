from .presets import BUILTIN_ANIMATIONS

DOMAIN = "trimlight"

DEFAULT_POLL_INTERVAL_SECONDS = 600
FORCED_ON_GRACE_SECONDS = 20
VERIFY_REFRESH_DELAY_SECONDS = 5

CONF_DEVICE_ID = "device_id"
CONF_COMMIT_CUSTOM_PRESET = "commit_custom_preset"
DEFAULT_COMMIT_CUSTOM_PRESET = True


def build_builtin_presets_from_effects(effects: list[dict]) -> list[dict]:
    builtins = []
    for e in effects:
        if e.get("category") != 0:
            continue
        name = (e.get("name") or "").strip()
        if not name:
            mode = e.get("mode")
            name = BUILTIN_ANIMATIONS.get(mode, f"Mode {mode}")
        builtins.append({"id": e.get("id", e.get("mode")), "name": name, "mode": e.get("mode")})
    builtins.sort(key=lambda r: (r.get("mode", 0), r.get("name", "")))
    return builtins


def build_builtin_presets_static() -> list[dict]:
    return [{"id": mode, "name": name, "mode": mode} for mode, name in sorted(BUILTIN_ANIMATIONS.items())]


CUSTOM_EFFECT_MODES = {
    0: "Static",
    1: "Chase Forward",
    2: "Chase Backward",
    3: "Chase Middle To Out",
    4: "Chase Out To Middle",
    5: "Stars",
    6: "Breath",
    7: "Comet Forward",
    8: "Comet Backward",
    9: "Comet Middle To Out",
    10: "Comet Out To Middle",
    11: "Wave Forward",
    12: "Wave Backward",
    13: "Wave Middle To Out",
    14: "Wave Out To Middle/Inside Out",
    15: "Strobe",
    16: "Solid Fade",
    17: "Full Strobe",
    18: "Twinkle",
    19: "Firework"
}
