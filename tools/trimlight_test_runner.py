from __future__ import annotations

import argparse
import json
import os
import shutil
import ssl
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = REPO_ROOT / "tools" / "trimlight_test_runner.local.json"

DEFAULT_ENTITY_IDS = {
    "light": "light.trimlight",
    "indicator_sensor": "sensor.trimlight_current_preset",
    "builtin_select": "select.trimlight_built_in_preset",
    "custom_select": "select.trimlight_custom_preset",
    "custom_mode_select": "select.trimlight_custom_effect_mode",
    "speed_number": "number.trimlight_effect_speed",
    "refresh_button": "button.trimlight_refresh_presets",
}

DEFAULT_PRESETS = {
    "baseline_custom": "Easter",
    "custom_alt": "Seahawks",
    "custom_off_to_on": "Red White Green",
    "builtin_primary": "Rainbow Spin",
    "builtin_secondary": "Rainbow Comet",
}

DEFAULT_SPEED_VALUES = {
    "custom_low": 25,
    "custom_high": 80,
    "builtin_low": 20,
    "builtin_high": 75,
}

DEFAULT_TIMING_S = {
    "capture_after_action": 2,
    "settle_default": 15,
    "settle_cold_start": 20,
    "after_power_off": 5,
    "after_refresh": 5,
}

DEFAULT_SCENARIOS = [
    "refresh_presets",
    "power_baseline",
    "custom_on_to_on",
    "custom_off_to_on",
    "builtin_from_custom",
    "builtin_to_builtin",
    "custom_after_builtin",
    "speed_custom",
    "speed_builtin",
]


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def dump_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)


def to_path(path_value: str | None, *, default: Path | None = None) -> Path | None:
    if not path_value:
        return default
    candidate = Path(path_value)
    if not candidate.is_absolute():
        candidate = REPO_ROOT / candidate
    return candidate


def parse_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def is_known_state(value: Any) -> bool:
    if value is None:
        return False
    text = str(value)
    return text not in {"", "unknown", "unavailable", "none"}


@dataclass(slots=True)
class RunnerConfig:
    ha_url: str
    token: str
    share_path: Path | None
    output_dir: Path
    copy_debug_log: bool
    verify_ssl: bool
    entity_ids: dict[str, str]
    presets: dict[str, str]
    speed_values: dict[str, float]
    timing_s: dict[str, float]

    @classmethod
    def from_file(cls, path: Path) -> "RunnerConfig":
        raw = load_json(path)

        ha_url = str(raw.get("ha_url", "")).strip().rstrip("/")
        if not ha_url:
            raise ValueError("Config is missing 'ha_url'.")

        token = str(raw.get("token", "")).strip()
        token_env = str(raw.get("token_env", "")).strip()
        token_file = str(raw.get("token_file", "")).strip()
        if not token and token_env:
            token = os.getenv(token_env, "").strip()
        if not token and token_file:
            resolved_token_file = to_path(token_file)
            if resolved_token_file is None or not resolved_token_file.exists():
                raise ValueError(f"Token file does not exist: {token_file}")
            token = resolved_token_file.read_text(encoding="utf-8").strip()
        if not token:
            raise ValueError(
                "No Home Assistant token found. Set 'token' in the local config, use 'token_env', or point 'token_file' at a local token file."
            )

        entity_ids = {**DEFAULT_ENTITY_IDS, **dict(raw.get("entity_ids") or {})}
        presets = {**DEFAULT_PRESETS, **dict(raw.get("presets") or {})}
        speed_values = {
            key: float(value)
            for key, value in {**DEFAULT_SPEED_VALUES, **dict(raw.get("speed_values") or {})}.items()
        }
        timing_s = {
            key: float(value)
            for key, value in {**DEFAULT_TIMING_S, **dict(raw.get("timing_s") or {})}.items()
        }

        output_dir = to_path(str(raw.get("output_dir", "debug"))) or (REPO_ROOT / "debug")
        share_path = to_path(str(raw.get("ha_share_path", "")).strip()) if raw.get("ha_share_path") else None

        return cls(
            ha_url=ha_url,
            token=token,
            share_path=share_path,
            output_dir=output_dir,
            copy_debug_log=bool(raw.get("copy_debug_log", True)),
            verify_ssl=bool(raw.get("verify_ssl", True)),
            entity_ids=entity_ids,
            presets=presets,
            speed_values=speed_values,
            timing_s=timing_s,
        )


class HomeAssistantClient:
    def __init__(self, base_url: str, token: str, *, verify_ssl: bool = True) -> None:
        self._base_url = base_url.rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        self._ssl_context = None if verify_ssl else ssl._create_unverified_context()

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        url = f"{self._base_url}{path}"
        body = None
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")

        request = Request(url, data=body, headers=self._headers, method=method)
        try:
            with urlopen(request, timeout=30, context=self._ssl_context) as response:
                raw = response.read()
        except HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"{method} {path} failed with HTTP {exc.code}: {raw}") from exc
        except URLError as exc:
            raise RuntimeError(f"{method} {path} failed: {exc}") from exc

        if not raw:
            return None
        return json.loads(raw.decode("utf-8"))

    def get_state(self, entity_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/states/{quote(entity_id, safe='')}")

    def call_service(self, domain: str, service: str, service_data: dict[str, Any]) -> Any:
        return self._request("POST", f"/api/services/{domain}/{service}", service_data)


class TrimlightTestRunner:
    def __init__(self, config: RunnerConfig) -> None:
        self.config = config
        self.client = HomeAssistantClient(
            config.ha_url,
            config.token,
            verify_ssl=config.verify_ssl,
        )
        self.run_started_at = now_iso()
        self.report: dict[str, Any] = {
            "started_at": self.run_started_at,
            "ha_url": config.ha_url,
            "share_path": str(config.share_path) if config.share_path else None,
            "scenarios": [],
            "copied_debug_log": None,
        }

    def sleep(self, seconds: float) -> None:
        if seconds > 0:
            time.sleep(seconds)

    def capture_snapshot(self) -> dict[str, Any]:
        entities: dict[str, Any] = {}
        for key, entity_id in self.config.entity_ids.items():
            state = self.client.get_state(entity_id)
            entities[key] = {
                "entity_id": entity_id,
                "state": state.get("state"),
                "attributes": state.get("attributes", {}),
                "last_changed": state.get("last_changed"),
                "last_updated": state.get("last_updated"),
            }
        return {"captured_at": now_iso(), "entities": entities}

    def state_value(self, snapshot: dict[str, Any], key: str) -> Any:
        return snapshot["entities"][key]["state"]

    def attr_value(self, snapshot: dict[str, Any], key: str, attr_name: str) -> Any:
        return snapshot["entities"][key]["attributes"].get(attr_name)

    def available_options(self, snapshot: dict[str, Any], key: str) -> list[str]:
        options = snapshot["entities"][key]["attributes"].get("options")
        return options if isinstance(options, list) else []

    def run_service_step(
        self,
        *,
        name: str,
        domain: str,
        service: str,
        service_data: dict[str, Any],
        settle_s: float,
        settle_condition: Callable[[dict[str, Any]], bool] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        before = self.capture_snapshot()
        started_at = now_iso()
        response = self.client.call_service(domain, service, service_data)

        capture_after = self.config.timing_s["capture_after_action"]
        self.sleep(capture_after)
        after_action = self.capture_snapshot()

        remaining = max(float(settle_s) - capture_after, 0.0)
        settled = after_action
        condition_met = settle_condition(after_action) if settle_condition else None
        deadline = time.monotonic() + remaining

        if settle_condition is None:
            self.sleep(remaining)
            settled = self.capture_snapshot()
        else:
            while time.monotonic() < deadline:
                sleep_for = min(1.0, max(deadline - time.monotonic(), 0.0))
                if sleep_for <= 0:
                    break
                self.sleep(sleep_for)
                settled = self.capture_snapshot()
                condition_met = bool(condition_met) or settle_condition(settled)

        step = {
            "name": name,
            "started_at": started_at,
            "service": f"{domain}.{service}",
            "service_data": service_data,
            "service_response": response,
            "snapshots": {
                "before": before,
                "after_action": after_action,
                "settled": settled,
            },
            "checks": [],
            "passed": True,
            "settle_condition_met": condition_met,
        }
        return step, settled

    def add_checks(self, step: dict[str, Any], checks: list[dict[str, Any]]) -> None:
        step["checks"] = checks
        step["passed"] = all(check["passed"] for check in checks)

    def build_check(self, *, name: str, passed: bool, expected: Any, actual: Any) -> dict[str, Any]:
        return {
            "name": name,
            "passed": bool(passed),
            "expected": expected,
            "actual": actual,
        }

    def check_state_eq(self, snapshot: dict[str, Any], key: str, expected: str, label: str) -> dict[str, Any]:
        actual = self.state_value(snapshot, key)
        return self.build_check(name=label, passed=actual == expected, expected=expected, actual=actual)

    def is_state_eq(self, snapshot: dict[str, Any], key: str, expected: str) -> bool:
        return self.state_value(snapshot, key) == expected

    def is_state_known(self, snapshot: dict[str, Any], key: str) -> bool:
        return is_known_state(self.state_value(snapshot, key))

    def check_state_known(self, snapshot: dict[str, Any], key: str, label: str) -> dict[str, Any]:
        actual = self.state_value(snapshot, key)
        return self.build_check(
            name=label,
            passed=is_known_state(actual),
            expected="known state",
            actual=actual,
        )

    def check_options_present(self, snapshot: dict[str, Any], key: str, label: str) -> dict[str, Any]:
        options = self.available_options(snapshot, key)
        return self.build_check(
            name=label,
            passed=len(options) > 0,
            expected="one or more options",
            actual=f"{len(options)} options",
        )

    def check_pixels_present(self, snapshot: dict[str, Any], label: str) -> dict[str, Any]:
        pixels = self.attr_value(snapshot, "indicator_sensor", "current_effect_pixels")
        passed = isinstance(pixels, list) and len(pixels) > 0
        return self.build_check(
            name=label,
            passed=passed,
            expected="non-empty current_effect_pixels",
            actual=f"{len(pixels)} pixel rows" if isinstance(pixels, list) else pixels,
        )

    def check_numeric_close(
        self,
        snapshot: dict[str, Any],
        key: str,
        expected: float,
        label: str,
        tolerance: float = 0.51,
    ) -> dict[str, Any]:
        actual_value = parse_float(self.state_value(snapshot, key))
        passed = actual_value is not None and abs(actual_value - expected) <= tolerance
        return self.build_check(name=label, passed=passed, expected=expected, actual=actual_value)

    def require_option(self, snapshot: dict[str, Any], key: str, option: str) -> None:
        options = self.available_options(snapshot, key)
        if option not in options:
            raise RuntimeError(
                f"Option '{option}' was not found for {key}. Available options: {options[:15]}"
            )

    def press_refresh(self) -> dict[str, Any]:
        step, settled = self.run_service_step(
            name="Refresh preset lists",
            domain="button",
            service="press",
            service_data={"entity_id": self.config.entity_ids["refresh_button"]},
            settle_s=self.config.timing_s["after_refresh"],
        )
        checks = [
            self.check_options_present(settled, "builtin_select", "Built-in preset list is populated"),
            self.check_options_present(settled, "custom_select", "Custom preset list is populated"),
        ]
        self.add_checks(step, checks)
        return step

    def select_custom(self, option: str, *, settle_s: float) -> dict[str, Any]:
        before = self.capture_snapshot()
        self.require_option(before, "custom_select", option)
        step, settled = self.run_service_step(
            name=f"Select custom preset: {option}",
            domain="select",
            service="select_option",
            service_data={
                "entity_id": self.config.entity_ids["custom_select"],
                "option": option,
            },
            settle_s=settle_s,
            settle_condition=lambda snapshot: (
                self.is_state_eq(snapshot, "light", "on")
                and self.is_state_eq(snapshot, "indicator_sensor", option)
                and self.is_state_eq(snapshot, "custom_select", option)
                and self.is_state_known(snapshot, "custom_mode_select")
            ),
        )
        checks = [
            self.check_state_eq(settled, "light", "on", "Light is on"),
            self.check_state_eq(settled, "indicator_sensor", option, "Indicator sensor matches custom preset"),
            self.check_state_eq(settled, "custom_select", option, "Custom preset select matches"),
            self.check_state_known(settled, "custom_mode_select", "Custom effect mode select is available"),
            self.check_pixels_present(settled, "Indicator sensor has pixel details"),
        ]
        self.add_checks(step, checks)
        return step

    def select_builtin(self, option: str, *, settle_s: float) -> dict[str, Any]:
        before = self.capture_snapshot()
        self.require_option(before, "builtin_select", option)
        step, settled = self.run_service_step(
            name=f"Select built-in preset: {option}",
            domain="select",
            service="select_option",
            service_data={
                "entity_id": self.config.entity_ids["builtin_select"],
                "option": option,
            },
            settle_s=settle_s,
            settle_condition=lambda snapshot: (
                self.is_state_eq(snapshot, "light", "on")
                and self.is_state_eq(snapshot, "indicator_sensor", option)
                and self.is_state_eq(snapshot, "builtin_select", option)
            ),
        )
        checks = [
            self.check_state_eq(settled, "light", "on", "Light is on"),
            self.check_state_eq(settled, "indicator_sensor", option, "Indicator sensor matches built-in preset"),
            self.check_state_eq(settled, "builtin_select", option, "Built-in preset select matches"),
        ]
        self.add_checks(step, checks)
        return step

    def turn_off(self) -> dict[str, Any]:
        step, settled = self.run_service_step(
            name="Turn Trimlight off",
            domain="light",
            service="turn_off",
            service_data={"entity_id": self.config.entity_ids["light"]},
            settle_s=self.config.timing_s["after_power_off"],
            settle_condition=lambda snapshot: (
                self.is_state_eq(snapshot, "light", "off")
                and self.is_state_eq(snapshot, "indicator_sensor", "Off")
            ),
        )
        checks = [
            self.check_state_eq(settled, "light", "off", "Light entity is off"),
            self.check_state_eq(settled, "indicator_sensor", "Off", "Indicator sensor shows Off"),
        ]
        self.add_checks(step, checks)
        return step

    def turn_on_expect_custom(self, expected_preset: str) -> dict[str, Any]:
        step, settled = self.run_service_step(
            name="Turn Trimlight on",
            domain="light",
            service="turn_on",
            service_data={"entity_id": self.config.entity_ids["light"]},
            settle_s=self.config.timing_s["settle_cold_start"],
            settle_condition=lambda snapshot: (
                self.is_state_eq(snapshot, "light", "on")
                and self.is_state_eq(snapshot, "indicator_sensor", expected_preset)
                and self.is_state_eq(snapshot, "custom_select", expected_preset)
                and self.is_state_known(snapshot, "custom_mode_select")
            ),
        )
        checks = [
            self.check_state_eq(settled, "light", "on", "Light entity is on"),
            self.check_state_eq(
                settled, "indicator_sensor", expected_preset, "Indicator sensor restored the active custom preset"
            ),
            self.check_state_eq(settled, "custom_select", expected_preset, "Custom preset select restored"),
            self.check_state_known(settled, "custom_mode_select", "Custom effect mode select restored"),
            self.check_pixels_present(settled, "Indicator sensor has pixel details"),
        ]
        self.add_checks(step, checks)
        return step

    def set_speed(self, value: float, *, expected_preset: str, preset_kind: str) -> dict[str, Any]:
        expected_select_key = "custom_select" if preset_kind == "custom" else "builtin_select"
        step, settled = self.run_service_step(
            name=f"Set speed to {value}",
            domain="number",
            service="set_value",
            service_data={
                "entity_id": self.config.entity_ids["speed_number"],
                "value": value,
            },
            settle_s=self.config.timing_s["settle_default"],
            settle_condition=lambda snapshot: (
                self.is_state_eq(snapshot, "light", "on")
                and self.check_numeric_close(snapshot, "speed_number", value, "speed", tolerance=0.51)["passed"]
                and self.is_state_eq(snapshot, "indicator_sensor", expected_preset)
                and self.is_state_eq(snapshot, expected_select_key, expected_preset)
            ),
        )
        checks = [
            self.check_state_eq(settled, "light", "on", "Light is on"),
            self.check_numeric_close(settled, "speed_number", value, "Speed number matches requested value"),
            self.check_state_eq(
                settled,
                "indicator_sensor",
                expected_preset,
                f"Indicator sensor stayed on the {preset_kind} preset",
            ),
        ]
        if preset_kind == "custom":
            checks.append(self.check_state_eq(settled, "custom_select", expected_preset, "Custom preset select stayed matched"))
        else:
            checks.append(
                self.check_state_eq(settled, "builtin_select", expected_preset, "Built-in preset select stayed matched")
            )
        self.add_checks(step, checks)
        return step

    def run_scenario(self, name: str) -> dict[str, Any]:
        handler = getattr(self, f"scenario_{name}", None)
        if handler is None:
            raise RuntimeError(f"Unknown scenario '{name}'.")

        scenario: dict[str, Any] = {
            "name": name,
            "started_at": now_iso(),
            "steps": [],
            "passed": True,
            "error": None,
        }
        try:
            handler(scenario)
        except Exception as exc:  # noqa: BLE001
            scenario["passed"] = False
            scenario["error"] = str(exc)
        scenario["finished_at"] = now_iso()
        scenario["passed"] = scenario["passed"] and all(step["passed"] for step in scenario["steps"])
        self.report["scenarios"].append(scenario)
        return scenario

    def scenario_refresh_presets(self, scenario: dict[str, Any]) -> None:
        scenario["steps"].append(self.press_refresh())

    def scenario_power_baseline(self, scenario: dict[str, Any]) -> None:
        baseline = self.config.presets["baseline_custom"]
        scenario["steps"].append(self.select_custom(baseline, settle_s=self.config.timing_s["settle_default"]))
        scenario["steps"].append(self.turn_off())
        scenario["steps"].append(self.turn_on_expect_custom(baseline))

    def scenario_custom_on_to_on(self, scenario: dict[str, Any]) -> None:
        baseline = self.config.presets["baseline_custom"]
        alternate = self.config.presets["custom_alt"]
        scenario["steps"].append(self.select_custom(baseline, settle_s=self.config.timing_s["settle_default"]))
        scenario["steps"].append(self.select_custom(alternate, settle_s=self.config.timing_s["settle_default"]))
        scenario["steps"].append(self.select_custom(baseline, settle_s=self.config.timing_s["settle_default"]))

    def scenario_custom_off_to_on(self, scenario: dict[str, Any]) -> None:
        option = self.config.presets["custom_off_to_on"]
        scenario["steps"].append(self.turn_off())
        scenario["steps"].append(self.select_custom(option, settle_s=self.config.timing_s["settle_cold_start"]))

    def scenario_builtin_from_custom(self, scenario: dict[str, Any]) -> None:
        baseline = self.config.presets["baseline_custom"]
        builtin = self.config.presets["builtin_primary"]
        scenario["steps"].append(self.select_custom(baseline, settle_s=self.config.timing_s["settle_default"]))
        scenario["steps"].append(self.select_builtin(builtin, settle_s=self.config.timing_s["settle_default"]))

    def scenario_builtin_to_builtin(self, scenario: dict[str, Any]) -> None:
        primary = self.config.presets["builtin_primary"]
        secondary = self.config.presets["builtin_secondary"]
        scenario["steps"].append(self.select_builtin(primary, settle_s=self.config.timing_s["settle_default"]))
        scenario["steps"].append(self.select_builtin(secondary, settle_s=self.config.timing_s["settle_default"]))

    def scenario_custom_after_builtin(self, scenario: dict[str, Any]) -> None:
        builtin = self.config.presets["builtin_primary"]
        baseline = self.config.presets["baseline_custom"]
        scenario["steps"].append(self.select_builtin(builtin, settle_s=self.config.timing_s["settle_default"]))
        scenario["steps"].append(self.select_custom(baseline, settle_s=self.config.timing_s["settle_default"]))

    def scenario_speed_custom(self, scenario: dict[str, Any]) -> None:
        baseline = self.config.presets["baseline_custom"]
        scenario["steps"].append(self.select_custom(baseline, settle_s=self.config.timing_s["settle_default"]))
        scenario["steps"].append(
            self.set_speed(
                self.config.speed_values["custom_low"],
                expected_preset=baseline,
                preset_kind="custom",
            )
        )
        scenario["steps"].append(
            self.set_speed(
                self.config.speed_values["custom_high"],
                expected_preset=baseline,
                preset_kind="custom",
            )
        )

    def scenario_speed_builtin(self, scenario: dict[str, Any]) -> None:
        builtin = self.config.presets["builtin_primary"]
        scenario["steps"].append(self.select_builtin(builtin, settle_s=self.config.timing_s["settle_default"]))
        scenario["steps"].append(
            self.set_speed(
                self.config.speed_values["builtin_low"],
                expected_preset=builtin,
                preset_kind="built-in",
            )
        )
        scenario["steps"].append(
            self.set_speed(
                self.config.speed_values["builtin_high"],
                expected_preset=builtin,
                preset_kind="built-in",
            )
        )

    def copy_latest_debug_log(self) -> str | None:
        if not self.config.copy_debug_log or self.config.share_path is None:
            return None

        share_path = self.config.share_path
        if not share_path.exists():
            return None

        candidates = sorted(
            share_path.rglob("trimlight_debug_*.jsonl"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if not candidates:
            return None

        latest = candidates[0]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        destination = self.config.output_dir / f"{timestamp}_{latest.name}"
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(latest, destination)
        return str(destination)

    def write_report(self) -> Path:
        self.report["finished_at"] = now_iso()
        self.report["copied_debug_log"] = self.copy_latest_debug_log()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = self.config.output_dir / f"trimlight_test_run_{timestamp}.json"
        dump_json(report_path, self.report)
        return report_path


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run automated Home Assistant Trimlight state-based tests.")
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help="Path to the local JSON config file. Default: tools/trimlight_test_runner.local.json",
    )
    parser.add_argument(
        "--scenario",
        action="append",
        help="Run only the named scenario. Repeat to run more than one. Defaults to the standard scenario set.",
    )
    parser.add_argument(
        "--list-scenarios",
        action="store_true",
        help="Print the available scenarios and exit.",
    )
    return parser


def print_summary(report: dict[str, Any], report_path: Path) -> None:
    print()
    print(f"Report written to: {report_path}")
    copied_debug_log = report.get("copied_debug_log")
    if copied_debug_log:
        print(f"Copied debug log: {copied_debug_log}")
    print()
    for scenario in report["scenarios"]:
        status = "PASS" if scenario["passed"] else "FAIL"
        print(f"[{status}] {scenario['name']}")
        if scenario.get("error"):
            print(f"  Error: {scenario['error']}")
        for step in scenario["steps"]:
            step_status = "PASS" if step["passed"] else "FAIL"
            print(f"  [{step_status}] {step['name']}")
            for check in step["checks"]:
                if not check["passed"]:
                    print(
                        f"    - {check['name']}: expected {check['expected']!r}, got {check['actual']!r}"
                    )


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()

    available = list(DEFAULT_SCENARIOS)
    if args.list_scenarios:
        for scenario in available:
            print(scenario)
        return 0

    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = REPO_ROOT / config_path
    if not config_path.exists():
        print(f"Config file not found: {config_path}", file=sys.stderr)
        print("Copy tools/trimlight_test_runner.example.json to tools/trimlight_test_runner.local.json and fill it in.", file=sys.stderr)
        return 2

    try:
        config = RunnerConfig.from_file(config_path)
    except Exception as exc:  # noqa: BLE001
        print(f"Failed to load config: {exc}", file=sys.stderr)
        return 2

    scenarios = args.scenario or available
    invalid = [name for name in scenarios if name not in available]
    if invalid:
        print(f"Unknown scenario(s): {invalid}", file=sys.stderr)
        print(f"Available scenarios: {available}", file=sys.stderr)
        return 2

    runner = TrimlightTestRunner(config)
    for scenario_name in scenarios:
        runner.run_scenario(scenario_name)

    report_path = runner.write_report()
    print_summary(runner.report, report_path)
    return 0 if all(s["passed"] for s in runner.report["scenarios"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
