![AI Auto-Off -- Zone Vacancy](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/zone_vacancy-header.jpeg)

# AI Auto-Off -- Zone Vacancy

Turns off lights and/or media when a presence sensor (e.g., Aqara FP2) reports "off" for a configurable delay. If the sensor goes back to "on" during the delay, the trigger is automatically cancelled. Each zone gets its own automation instance created through the HA UI. This is the inverse of the Zone Presence blueprint, which turns things on.

## How It Works

```
┌─────────────────────────────────────┐
│ Trigger                             │
│  Presence sensor: on → off          │
│  (held for vacancy_delay)           │
└──────────────┬──────────────────────┘
               │
    ┌──────────▼──────────────────┐
    │ Conditions                  │
    │  ├─ Master switch ON        │
    │  ├─ Allowed day of week     │
    │  ├─ Weekend mode check      │
    │  └─ Within time window      │
    └──────────┬──────────────────┘
               │
    ┌──────────▼──────────────────┐
    │ Lights (if enabled)         │
    │  ├─ Area lights OFF, or     │
    │  ├─ Specific lights OFF     │
    │  └─ + switches from list    │
    └──────────┬──────────────────┘
               │
    ┌──────────▼──────────────────┐
    │ Media (if enabled)          │
    │  ├─ Area players STOP, or   │
    │  └─ Specific players STOP   │
    └──────────┬──────────────────┘
               │
    ┌──────────▼──────────────────┐
    │ Exit script (if set)        │
    └─────────────────────────────┘
```

## Features

- Per-zone automation via blueprint instances
- Configurable vacancy delay (duration selector) prevents premature shutoffs
- Lights: area-based or specific entity targeting (or both -- switches always from specific list)
- Media: area-based or specific player targeting
- Optional exit script for custom actions (e.g., thermostat to away mode)
- Schedule gating: active time window with cross-midnight support
- Day-of-week selection
- Weekend overrides: same as weekdays, disabled, or separate weekend profile with its own time window
- Master switch for global enable/disable
- Replaces the 900-line `pyscript/auto_off_engine.py` dynamic zone engine

## Prerequisites

- Home Assistant 2024.10.0 or later
- A `binary_sensor` for zone presence detection (e.g., Aqara FP2)
- `input_boolean.ai_auto_off_enabled` (default master switch, can be changed)

## Installation

1. Copy `zone_vacancy.yaml` to `config/blueprints/automation/madalone/`
2. Create automation: **Settings -> Automations -> Create -> Use Blueprint**

## Configuration

| Input | Default | Description |
|---|---|---|
| `presence_sensor` | _(required)_ | Binary sensor for zone occupancy |
| `vacancy_delay` | `0h 15m 0s` | Duration to wait after sensor reports "off" before turning things off |
| `master_switch` | `input_boolean.ai_auto_off_enabled` | Global on/off toggle |
| `lights_enabled` | `true` | Turn off lights when zone is vacant |
| `use_area_lights` | `true` | Use area-based light control (vs. specific entities) |
| `target_area` | _(required)_ | HA area for area-based targeting |
| `specific_lights` | `[]` | Specific light/switch entities (used when area lights disabled; switches always used) |
| `media_enabled` | `true` | Stop media players when zone is vacant |
| `use_area_players` | `true` | Use area-based media control (vs. specific entities) |
| `specific_players` | `[]` | Specific media player entities |
| `exit_script` | `[]` | Optional script to run after lights/media |

<details><summary><strong>Schedule & Timing</strong></summary>

| Input | Default | Description |
|---|---|---|
| `start_time` | `00:00:00` | Start of daily active window |
| `end_time` | `23:59:59` | End of daily active window (cross-midnight supported) |
| `run_days` | all 7 days | Days of the week the automation may run |

</details>

<details><summary><strong>Weekend Overrides</strong></summary>

| Input | Default | Description |
|---|---|---|
| `weekend_mode` | `same_as_weekdays` | Weekend behavior: same / disabled / use_weekend_profile |
| `weekend_days` | `sat, sun` | Which days count as weekend |
| `weekend_start_time` | `00:00:00` | Weekend-specific active window start |
| `weekend_end_time` | `23:59:59` | Weekend-specific active window end |

</details>

## Technical Notes

- **Mode:** `restart`, `max_exceeded: silent`
- **Cross-midnight logic:** Time window and day-of-week calculations handle cross-midnight schedules correctly by shifting the effective day key backward when `now()` is in the post-midnight portion of a window
- **Switch handling:** When `use_area_lights` is enabled, `light.turn_off` targets the area. Any `switch.*` entities in `specific_lights` are turned off separately, since `light.turn_off` does not affect switches.
- **Trigger cancellation:** HA natively cancels the `for:` trigger if the sensor returns to "on" before the delay expires

## Author

**madalone**

## License

See repository for license details.
