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

---

## Setup Details

### Credentials
You need:
- `client_id`
- `client_secret`
- `device_id`

These come from your Trimlight EDGE account / device and can be obtained using the scripts in `TrimlightEdgeControl`.

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
- Choosing an option previews the built-in effect.
- Speed + brightness changes continue to apply to the active built‑in effect.

### Select Custom Presets
Use `select.trimlight_custom_preset`.
- Choosing an option previews the custom effect immediately.
- If "Commit custom presets" is enabled (default), the saved preset is applied by id in the background.
- If preview payload is incomplete (missing mode/pixels), the integration falls back to applying by saved effect id.
- Speed + brightness changes update the active custom effect via preview.

### Custom Effect Modes
Use `select.trimlight_custom_effect_mode`.
- Choose a mode by name. The list includes all known modes (0-19).
- Applied to the currently active custom effect.
- If the controller reports a mode not in the list, use the `sensor.trimlight_current_preset` attribute `current_effect_mode` to map and name it.

### Select Entity Attributes
The select entities expose extra attributes for IDs and lookup:
- `select.trimlight_custom_preset`: `current_id`, `presets` (list of `{id,name}`), `name_to_id` (unique names only).
- `select.trimlight_built_in_preset`: `current_id`, `builtins` (list of `{id,mode,name}`).
- `select.trimlight_custom_effect_mode`: `current_mode_id`, `modes` (list of `{id,name}`).

### Current Preset Sensor
`sensor.trimlight_current_preset` shows the active preset name.
- Uses the API's `currentEffect` when available.
- Falls back to the last selected preset if needed.
- Attributes (from API effect fields):
  - `current_effect_id`: integer ID of saved effect. `-1` means preview (not yet saved).
  - `current_effect_category`: integer. `0` = built-in effect, `1` = custom effect.
  - `current_effect_mode`: integer. Built-in mode range `0-179`; custom mode range `0-19` (documented).
  - `current_effect_speed`: integer `0-255`.
  - `current_effect_brightness`: integer `0-255`.
  - `current_effect_pixel_len`: integer `1-90` (only required for built-in effects).
  - `current_effect_reverse`: boolean (only required for built-in effects).
  - `current_effect_pixels`: list of pixels for custom effects. Each entry includes `index`, `count`, `color` (RGB int), `disable` (bool).
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
- If you don’t see custom presets, press the refresh button and check the debug cache file in your HA config folder.
- Custom effects may be reported by the device as category 1 or 2; the integration accepts both.
- If built-in presets are empty on first load, the integration will fall back to the static built‑in list.
- API credentials are required for every call; a bad key or secret will cause setup failures.
- If the current preset shows `Unknown`, select a preset once so it can be cached.
- Polling interval is 10 minutes (`DEFAULT_POLL_INTERVAL_SECONDS`).
- UI uses a 20-second on grace window after actions to avoid flicker (`FORCED_ON_GRACE_SECONDS`).
- Options: "Commit custom presets" (default on) controls whether selecting a custom preset also runs the saved preset id in the background. When off, preview is used first; if preview data is incomplete, id-apply fallback is used so selection still works.

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
