# Circadian Lighting (C6)

Per-room automation that continuously adjusts light color temperature and brightness based on the sun's elevation. Ported from the proven [HarvsG community formula](https://community.home-assistant.io/t/472105) (active since 2022, updated Feb 2025 for `color_temp_kelvin`). Create one instance per room.

## How It Works

```
┌──────────────────────────────────────────────────┐
│                   TRIGGERS                        │
│  • Time pattern (every N minutes)                 │
│  • Sun elevation changed (sun.sun)                │
│  • Bedtime flag changed                           │
│  • A managed light turned on                      │
└────────────────────────┬─────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────┐
│                 CONDITIONS                        │
│  • Kill switch ON?                                │
│  • Privacy gate passes?                           │
└────────────────────────┬─────────────────────────┘
                         │ pass
                         ▼
┌──────────────────────────────────────────────────┐
│          CALCULATE CIRCADIAN VALUES               │
│                                                   │
│  Bedtime ON?                                      │
│    → sleep_color_temp + sleep_brightness          │
│  Focus ON + high_brightness?                      │
│    → max_brightness + normal color                │
│  Focus ON + dim_warm?                             │
│    → 40% brightness + min color temp              │
│  Normal:                                          │
│    → Sun elevation → color temp (HarvsG curve)    │
│    → Sun elevation → brightness (linear interp)   │
└────────────────────────┬─────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────┐
│       FIRE ai_scene_learner_suppress EVENT        │
└────────────────────────┬─────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────┐
│          APPLY TO EACH MANAGED LIGHT              │
│                                                   │
│  For each light:                                  │
│  1. Check if ON + supports brightness             │
│  2. If manual override detection enabled:         │
│     - Current color_temp differs by > threshold?  │
│     - Yes → skip (user manually adjusted)         │
│  3. light.turn_on with:                           │
│     - brightness_pct                              │
│     - color_temp_kelvin (if supported)            │
│     - transition                                  │
└──────────────────────────────────────────────────┘
```

## Features

- Sun elevation to color temperature curve (2200K–5000K default) using the HarvsG community formula
- Sun elevation to brightness curve (15%–100% default) via linear interpolation
- Sleep mode: locks to warm/dim settings when bedtime flag is active
- Manual override detection: skips lights the user manually adjusted (clears on OFF->ON cycle)
- Configurable manual detection threshold (default 400K)
- Focus mode integration: normal (no change), high brightness (max brightness, normal color), or dim warm (40% brightness, warm color)
- Guest mode gate
- Per-light capability detection: only adjusts lights supporting color temperature; brightness-only lights get brightness adjustment
- Fires `ai_scene_learner_suppress` event for scene learner integration
- Standard privacy gate (off/t1/t2/t3)
- Multiple trigger sources for responsive updates

## Prerequisites

- Home Assistant 2024.10.0+
- Lights supporting `color_temp` color mode (others are silently skipped)
- `input_boolean` for per-instance kill switch
- `input_boolean.ai_bedtime_active` (sleep mode trigger)
- `sun.sun` entity (built-in)

## Installation

1. Copy `circadian_lighting.yaml` to `config/blueprints/automation/madalone/`
2. Create automation: **Settings -> Automations -> Create -> Use Blueprint**
3. Create one instance per room

## Configuration

<details><summary>① Control</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `enable_toggle` | _(required)_ | Per-instance kill switch. Turn off to pause circadian adjustments for this room |
| `target_lights` | _(required)_ | Lights to manage (multi-select). Only lights supporting color temperature will be adjusted -- others are silently skipped |
| `update_interval` | `5` | Update interval in minutes. Lower = smoother transitions but more service calls (1–30 min) |
| `transition_seconds` | `5` | Duration of the color/brightness transition in seconds (1–60 s) |

</details>

<details><summary>② Color & brightness range</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `min_color_temp_kelvin` | `2200` | Color temperature at night / below horizon. Lower = warmer/more amber (1800–4000 K) |
| `max_color_temp_kelvin` | `5000` | Color temperature at solar noon. Higher = cooler/bluer (3500–6500 K) |
| `min_brightness_pct` | `15` | Brightness when the sun is well below the horizon (1–50%) |
| `max_brightness_pct` | `100` | Brightness at solar noon (50–100%) |

</details>

<details><summary>③ Manual override detection</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `detect_manual_changes` | `true` | If enabled, lights whose current color_temp differs by more than the threshold from the circadian calculation are skipped. Prevents the automation from fighting manual adjustments |
| `manual_threshold_kelvin` | `400` | Color temperature difference (in Kelvin) that counts as a manual override. 400K catches intentional changes while allowing natural circadian drift (100–1000 K) |

</details>

<details><summary>④ Sleep mode</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `bedtime_entity` | `input_boolean.ai_bedtime_active` | Boolean that signals bedtime is active |
| `sleep_brightness_pct` | `5` | Brightness during sleep mode (1–30%) |
| `sleep_color_temp_kelvin` | `2200` | Color temperature during sleep mode. Very warm (1800–2500 K) |

</details>

<details><summary>⑤ Gates</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `focus_mode_entity` | `input_boolean.ai_focus_mode` | Boolean that signals focus mode is active |
| `focus_behavior` | `normal` | How circadian behaves during focus mode: `normal` (no change), `high_brightness` (max brightness, normal color), `dim_warm` (40% brightness, warm color) |
| `guest_mode_entity` | `input_boolean.ai_guest_mode` | Boolean that signals guests are present |
| `privacy_tier` | `off` | Privacy gate tier (off/t1/t2/t3) |
| `privacy_gate_enabled` | `input_boolean.ai_privacy_gate_enabled` | Privacy gate enabled entity |
| `privacy_gate_mode` | `input_select.ai_privacy_gate_mode` | Privacy gate mode entity |
| `privacy_gate_person` | `""` | Person entity for tier suppression lookups |

</details>

## Technical Notes

- **Mode:** `single` / `max_exceeded: silent` -- only one execution per instance at a time
- **Triggers:** 4 trigger sources -- time pattern (every N min), sun elevation change, bedtime flag change, managed light turned on. This ensures responsive updates without excessive polling
- **HarvsG formula:** Color temperature calculation uses `4791.67 - 3290.66 / (1 + 0.222 * (elev^0.81))` with sun elevation clamped to 0–90 degrees, result constrained between min/max color temp
- **Brightness formula:** Linear interpolation from -10 degrees (min brightness) to 60 degrees (max brightness)
- **Manual override:** Compares current `color_temp_kelvin` attribute against calculated circadian value. Difference exceeding the threshold (default 400K) means the user manually set the light -- it's skipped until cycled OFF->ON
- **Scene learner:** Fires `ai_scene_learner_suppress` event before applying values to prevent the scene learner from recording circadian adjustments as user preferences

## Changelog

- **v1.0.0:** Initial blueprint -- C6 Layer 1

## Author

**madalone**

## License

See [LICENSE](../../LICENSE) in the repository root.
