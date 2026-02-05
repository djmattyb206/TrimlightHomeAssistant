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
- Choosing an option runs the saved custom preset by id.
- Speed + brightness changes update the active custom effect via preview.

### Custom Effect Modes
Use `select.trimlight_custom_effect_mode`.
- Choose a mode (0–16) by name (camel case).
- Applied to the currently active custom effect.

### Current Preset Sensor
`sensor.trimlight_current_preset` shows the active preset name.
- Uses the API’s `currentEffect` when available.
- Falls back to the last selected preset if needed.

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

- If you don’t see custom presets, press the refresh button and check the debug cache file in your HA config folder.
- If built-in presets are empty on first load, the integration will fall back to the static built‑in list.
- API credentials are required for every call; a bad key or secret will cause setup failures.
- If the current preset shows `Unknown`, select a preset once so it can be cached.

---

## API Documentation

The Trimlight EDGE API PDF is included here:
`docs/Trimlight_Edge_API_Documentation 8192022.pdf`

---

## License

MIT License. See `TrimlightHomeAssistant/LICENSE`.
