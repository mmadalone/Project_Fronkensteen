![Meal Detection](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/meal_detection-header.jpeg)

# Meal Detection

Passive meal time logging from kitchen presence patterns. When the kitchen sensor is occupied for a minimum duration within configured meal windows (breakfast, lunch, dinner), updates `last_meal_time` and optionally logs to L2 memory via pyscript. False positives are acceptable -- this is logging-only, with no actions beyond timestamps and optional memory entries.

## How It Works

```
┌─────────────────────────────────────────────────────────┐
│                      TRIGGER                            │
│  ┌───────────────────────────────────────────────────┐  │
│  │ Kitchen presence sensor: off → on                 │  │
│  │ for: min_kitchen_minutes (default 15 min)         │  │
│  └──────────────────────┬────────────────────────────┘  │
└─────────────────────────┼───────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│                  CONDITION GATES                        │
│  • Current hour within a meal window?                  │
│    (breakfast / lunch / dinner)                         │
│  • Last meal was long enough ago? (dedup)              │
│  • Privacy gate passes?                                │
└────────────────────────┬────────────────────────────────┘
                         │ all pass
                         ▼
┌─────────────────────────────────────────────────────────┐
│                  ACTION SEQUENCE                        │
│  1. Update last_meal_time to now                       │
│  2. Call pyscript.meal_passive_log (if enabled)        │
└─────────────────────────────────────────────────────────┘
```

## Features

- **Passive detection** -- no user interaction required; kitchen presence duration is the only signal.
- **3 meal windows** -- configurable hour ranges for breakfast, lunch, and dinner.
- **Minimum dwell time** -- triggers only after sustained presence (default 15 minutes), reducing false positives.
- **Dedup gate** -- skips detection if the last meal was less than N hours ago (default 2 hours).
- **L2 memory logging** -- optionally calls `pyscript.meal_passive_log` for context-aware agent memory.
- **Last meal timestamp** -- updates an `input_datetime` consumed by focus_guard and other systems.
- **Privacy gate** -- tier-based suppression.

## Prerequisites

- **Home Assistant 2024.10.0+**
- **Kitchen presence sensor** -- binary sensor for kitchen occupancy (e.g., Aqara FP2 zone)
- **input_datetime** -- for last meal time tracking
- **Pyscript** with `meal_passive_log` service (optional, for L2 logging)

## Installation

1. Copy `meal_detection.yaml` to `config/blueprints/automation/madalone/`
2. Create automation: **Settings -> Automations -> Create -> Use Blueprint**

## Configuration

<details>
<summary>Section 1 -- Kitchen Sensor</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `kitchen_presence` | `""` *(required)* | Binary sensor for kitchen presence |
| `min_kitchen_minutes` | `15` | Minimum minutes in kitchen before logging (5-45) |

</details>

<details>
<summary>Section 2 -- Meal Windows</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `breakfast_start` | `7` | Breakfast window start hour |
| `breakfast_end` | `9` | Breakfast window end hour |
| `lunch_start` | `12` | Lunch window start hour |
| `lunch_end` | `14` | Lunch window end hour |
| `dinner_start` | `19` | Dinner window start hour |
| `dinner_end` | `21` | Dinner window end hour |

</details>

<details>
<summary>Section 3 -- Tracking</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `last_meal_entity` | `""` *(required)* | Input datetime for last detected meal time |
| `min_gap_hours` | `2` | Minimum hours between detected meals (dedup) |
| `use_meal_log` | `true` | Log meals to L2 via `pyscript.meal_passive_log` |

</details>

<details>
<summary>Privacy</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `privacy_gate_enabled` | `input_boolean.ai_privacy_gate_enabled` | Privacy gate master toggle |
| `privacy_gate_mode` | `input_select.ai_privacy_gate_mode` | Privacy gate behavior selector |
| `privacy_gate_person` | `miquel` | Person name for tier suppression lookups |

</details>

## Technical Notes

- **Mode:** `single` with `max_exceeded: silent` -- one detection at a time.
- **Trigger mechanism:** Uses `state` trigger with `from: "off"` / `to: "on"` and `for: N minutes`. The presence must be sustained for the full minimum duration before the trigger fires.
- **Meal window check:** Uses `now().hour` compared against the configured hour ranges. All three windows are checked with OR logic.
- **Dedup logic:** Compares current timestamp against the `last_meal_entity` state. If the helper is unknown/unavailable/empty, dedup is skipped (always passes).
- **Pyscript call:** `pyscript.meal_passive_log` is called with `continue_on_error: true` so pyscript failures don't block the timestamp update.

## Changelog

- **v1:** Initial blueprint -- replaces automation from `ai_meal_detection.yaml`.

## Author

**madalone**

## License

See repository for license details.
