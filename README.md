# Trimlight Home Assistant Integration
![Trimlight icon](assets/icon.png)

Home Assistant custom integration for Trimlight EDGE lights.

**Copy into HA config (exact steps)**
1. Locate your Home Assistant config folder (the one that contains `configuration.yaml`).
2. Create a folder `custom_components/trimlight` inside that config folder.
3. Copy everything from `TrimlightHomeAssistant/custom_components/trimlight/` into your HA config at `custom_components/trimlight/`.
4. Restart Home Assistant.
5. In Home Assistant: `Settings` -> `Devices & Services` -> `Add Integration` -> search for `Trimlight`.
6. Enter your `client_id`, `client_secret`, and `device_id`.

If you don’t know your `device_id`, use your existing Trimlight scripts in `TrimlightEdgeControl` to fetch it.

---

## What This Integration Provides

Entities created:
- `light.trimlight` (on/off + brightness)
- `select.trimlight_built_in_preset` (built-in animations)
- `select.trimlight_custom_preset` (saved custom presets)
- `select.trimlight_custom_effect_mode` (custom effect modes)
- `number.trimlight_effect_speed` (speed slider, 0–100%)
- `sensor.trimlight_current_preset` (current preset name)
- `button.trimlight_refresh_presets` (refresh presets lists)
- `sensor.trimlight_current_preset` exposes effect detail attributes (mode/speed/brightness/pixels)
- Select entities expose ID/lookup attributes for preset tracking

Presets are cached in Home Assistant storage so they persist after restarts. A human-readable cache file is also written to your HA config folder as `trimlight_presets_<entry_id>.json`.
When debug logging is enabled in the integration options, the integration also writes a structured JSONL log to `trimlight_debug_<entry_id>.jsonl` in your HA config folder.

---

## Setup Details

### Credentials
You need:
- `client_id`
- `client_secret`
- `device_id`

These come from your Trimlight EDGE account. The `client_id` is the login that you use when logging into the Trimlight app. The `client_secret` must be provided to you by the Trimlight developers. The `devide_id` can be obtained using the scripts in `TrimlightEdgeControl`.

### First Run Behavior
- On the first refresh, built-in presets are pulled from the device and cached.
- If the device does not return built-ins, the integration uses the static built‑in list.
- After that, the refresh button only updates custom presets (built-ins are static).

---

## How to Use the Features

### Sample Setup
<img width="396" height="793" alt="image" src="https://github.com/user-attachments/assets/03bf127f-2e1a-4e22-aad9-ed26a4a3ae27" />

## Cards You Can Paste

Prerequisite: Install Mushroom cards (HACS -> Frontend -> Mushroom).

### Trimlight Power Tile
```yaml
type: tile
entity: light.trimlight
vertical: false
tap_action:
  action: more-info
icon_tap_action:
  action: toggle
features_position: bottom
```

### Current Preset (Visible Only When On)
```yaml
type: conditional
conditions:
  - entity: light.trimlight
    state: "on"
card:
  type: custom:mushroom-template-card
  primary: "{{ states('sensor.trimlight_current_preset') }}"
  secondary: ""
  icon: mdi:led-strip-variant
grid_options:
  columns: 6
  rows: auto
```

### Speed Control (Visible Only When On)
```yaml
type: conditional
conditions:
  - entity: light.trimlight
    state: "on"
card:
  type: custom:mushroom-number-card
  entity: number.trimlight_effect_speed
  name: Speed Control
  icon: mdi:speedometer
  grid_options:
    columns: 12
    rows: 2
```

### Built-In Preset Selector
```yaml
type: custom:mushroom-select-card
entity: select.trimlight_built_in_preset
name: Trimlight Built In Preset
primary_info: name
secondary_info: none
grid_options:
  columns: 12
  rows: 2
```

### Custom Preset Selector
```yaml
type: custom:mushroom-select-card
entity: select.trimlight_custom_preset
name: Trimlight Custom Preset
primary_info: name
secondary_info: none
grid_options:
  columns: 12
  rows: 2
```

### Custom Effect Mode (Visible Only When Custom Preset Selected)
```yaml
type: conditional
conditions:
  - entity: select.trimlight_custom_preset
    state_not: unknown
  - entity: select.trimlight_custom_preset
    state_not: unavailable
card:
  type: custom:mushroom-select-card
  entity: select.trimlight_custom_effect_mode
  name: Trimlight Custom Effect Mode
  primary_info: name
  secondary_info: none
  grid_options:
    columns: 12
    rows: 2
```

### Power On/Off
Use the `light.trimlight` entity:
- `turn_on` sets `switchState=1`
- `turn_off` sets `switchState=0`

The UI updates immediately on toggle, then confirms via refresh.

### Brightness
Adjust brightness using the `light.trimlight` entity.
- The integration updates the active effect by previewing it with the new brightness.
- Works for both built‑in and custom presets.

### Speed (Slider)
Use `number.trimlight_effect_speed`.
- Displays 0–100% in the UI
- Converts to 0–255 for the device
- Updates the currently active effect immediately

### Select Built-in Presets
Use `select.trimlight_built_in_preset`.
- Choosing an option powers the controller on if needed, then tries to preview the built-in effect.
- If the controller rejects built-in preview, the integration falls back to applying the saved built-in effect by id using `effect/view`.
- The UI updates optimistically, then confirms via verification refresh.
- Brightness + speed changes for built-in effects are still sent as preview updates.

### Select Custom Presets
Use `select.trimlight_custom_preset`.
- Choosing an option applies the saved custom preset by id using `effect/view`.
- If the controller is off, the integration powers it on first, waits briefly, then applies the preset.
- The UI updates optimistically, then confirms via verification refresh.
- Duplicate preset names are disambiguated in the option list as `Name (id <id>)`.
- Speed + brightness changes update the active custom effect via preview.

### Custom Effect Modes
Use `select.trimlight_custom_effect_mode`.
- Choose a mode by name. The list includes all known modes (0-19).
- Applied to the currently active custom effect.
- If the controller reports a mode not in the list, use the `sensor.trimlight_current_preset` attribute `current_effect_mode` to map and name it.

### Select Entity Attributes
The select entities expose extra attributes for IDs and lookup:
- `select.trimlight_custom_preset`: `current_id`, `presets` (list of `{id,name}`), `name_to_id` (unique names only), `option_to_id` (exact option label to id map, including disambiguated duplicates).
- `select.trimlight_built_in_preset`: `current_id`, `builtins` (list of `{id,mode,name}`).
- `select.trimlight_custom_effect_mode`: `current_mode_id`, `modes` (list of `{id,name}`).

### Current Preset Sensor
`sensor.trimlight_current_preset` shows the active preset name.
- Uses the API's `currentEffect` when available.
- Falls back to the select entity state and last selected preset if needed.
- For custom presets, if the controller omits the saved effect id, the sensor resolves the active preset from the custom select state and cached preset list.
- Attributes (from API effect fields):
  - `current_effect_id`: integer ID of saved effect. `-1` means preview (not yet saved).
  - `current_effect_category`: integer. `0` = built-in effect, `1` or `2` = custom effect.
  - `current_effect_mode`: integer. Built-in mode range `0-179`; custom mode range `0-19` (documented).
  - `current_effect_speed`: integer `0-255`.
  - `current_effect_brightness`: integer `0-255`.
  - `current_effect_pixel_len`: integer `1-90` (only required for built-in effects).
  - `current_effect_reverse`: boolean (only required for built-in effects).
  - `current_effect_pixels`: list of pixels for custom effects. Each entry includes `index`, `count`, `color` (RGB int), `disable` (bool).
  - When a saved custom preset can be resolved, pixel/speed/brightness attributes prefer that saved preset definition over stale controller data.
  - If `current_effect_pixels` is empty/disabled, the integration falls back to last known custom pixels.

### Refresh Preset Lists
Press `button.trimlight_refresh_presets`.
- First press: loads built-ins from the device + refreshes custom presets.
- Later presses: refresh custom presets only.

---

## Automations and Schedules

To turn on the system and set a custom preset:
1. Call `light.turn_on` for `light.trimlight`.
2. Call `select.select_option` for `select.trimlight_custom_preset`.

Example automation snippet:
```yaml
action:
  - service: light.turn_on
    target:
      entity_id: light.trimlight
  - service: select.select_option
    target:
      entity_id: select.trimlight_custom_preset
    data:
      option: "Seahawks"
```

---

## Notes and Troubleshooting

- Verification refresh happens 5 seconds after each command (`VERIFY_REFRESH_DELAY_SECONDS`).
- Custom preset selection from off uses a longer delayed verification refresh so the controller has time to finish powering on and applying the preset.
- If you don’t see custom presets, press the refresh button and check the debug cache file in your HA config folder.
- Custom effects may be reported by the device as category 1 or 2; the integration accepts both.
- If built-in presets are empty on first load, the integration will fall back to the static built‑in list.
- API credentials are required for every call; a bad key or secret will cause setup failures.
- If the current preset shows `Unknown`, select a preset once so it can be cached.
- Polling interval is 10 minutes (`DEFAULT_POLL_INTERVAL_SECONDS`).
- UI uses a 20-second on grace window after actions to avoid flicker (`FORCED_ON_GRACE_SECONDS`).
- Options:
  - `Commit custom presets` is still present in the options flow for compatibility, but saved custom preset selection now applies by id directly.
  - `Enable debug logging` writes `trimlight_debug_<entry_id>.jsonl` in the HA config folder with structured action, refresh, and state snapshots.

---

## Automated Test Runner

This repo includes a Windows-friendly test runner for state-based Trimlight checks:
- `tools/trimlight_test_runner.py`
- `tools/run_trimlight_tests.ps1`
- `tools/trimlight_test_runner.example.json`

Recommended setup:
1. Copy `tools/trimlight_test_runner.example.json` to `tools/trimlight_test_runner.local.json`.
2. Create a local token file such as `tools/ha_trimlight.token` and paste your Home Assistant long-lived token into it.
3. Edit the local file with your Home Assistant URL, mapped HA share path, token file path, and your preset names.
4. Run the suite from PowerShell:
   - `.\tools\run_trimlight_tests.ps1`
5. Reports are written to the local `debug/` folder.
   - The runner also copies the latest `trimlight_debug_*.jsonl` from your mapped HA share into `debug/` when available.

Useful commands:
- List scenarios:
  - `python .\tools\trimlight_test_runner.py --list-scenarios`
- Run one scenario:
  - `.\tools\run_trimlight_tests.ps1 -Scenario custom_off_to_on`
- Run multiple scenarios:
  - `.\tools\run_trimlight_tests.ps1 -Scenario power_baseline,builtin_from_custom`

What it verifies well:
- Home Assistant service calls
- Entity state transitions for power, preset selection, speed changes, and sensor/select sync
- Captured integration debug logs copied from your HA share

What it does not verify by itself:
- The actual visual look of the lights
- Whether a built-in animation "looks right" beyond the states reported back through Home Assistant

The local runner config file is ignored by Git, so you can keep your personal URL/share settings out of GitHub.
Token files matching `tools/*.token` are also ignored by Git.

---

## API Documentation

The Trimlight EDGE API PDF is included here:
[Trimlight Edge API Documentation (PDF)](https://github.com/djmattyb206/TrimlightHomeAssistant/blob/main/docs/Trimlight_Edge_API_Documentation%208192022.pdf)

---

## Developer Notes

- Runtime state is stored in `custom_components/trimlight/data.py` as `TrimlightData`.
- Effect normalization and lookups live in `custom_components/trimlight/effects.py`, and preview updates in `custom_components/trimlight/controller.py`.
- Built-in animation names live in `custom_components/trimlight/presets.py`.
- Preset cache persistence and debug file writes live in `custom_components/trimlight/storage.py`.

---

## License

MIT License. See `TrimlightHomeAssistant/LICENSE`.
