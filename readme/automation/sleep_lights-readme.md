![Sleep Lights -- Turn Off Lights on Sleep Detection](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/sleep_lights-header.jpeg)

# Sleep Lights -- Turn Off Lights on Sleep Detection

Turns off selected lights and switches after sleep is detected. Waits a configurable delay, re-checks that sleep is still detected, then turns off the targets. Time window prevents accidental triggers outside nighttime hours. Requires the sleep detection system (`input_boolean.ai_sleep_detected`) or equivalent flag.

## How It Works

```
┌─────────────────────────────┐
│ Trigger: sleep detected     │
│ flag turns ON               │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│ Conditions:                 │
│  ✓ Within time window       │
│    (cross-midnight safe)    │
│  ✓ Privacy gate passes      │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│ Wait configured delay       │
│ (default 15 minutes)        │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│ Re-check: sleep flag still  │
│ ON? (stops if cleared)      │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│ Turn off target lights      │
│ Turn off target switches    │
└─────────────────────────────┘
```

## Features

- **Delay with re-check** -- waits before acting, then confirms sleep is still detected (false positive buffer)
- **Lights and switches** -- separate target selectors for light and switch entities, areas, or devices
- **Cross-midnight time window** -- only triggers within configurable nighttime hours
- **Privacy gate** -- tier-based suppression with per-person and per-feature overrides
- **Graceful switch handling** -- `continue_on_error: true` on switch turn-off prevents failures from blocking the sequence

## Prerequisites

- Home Assistant 2024.10.0+
- A sleep detected `input_boolean` (from the sleep detection blueprint or equivalent)
- Light and/or switch entities to control

## Installation

1. Copy `sleep_lights.yaml` to `config/blueprints/automation/madalone/`
2. Create automation: **Settings → Automations → Create → Use Blueprint**

## Configuration

### ① Sleep Detection

| Input | Default | Description |
|-------|---------|-------------|
| **Sleep detected entity** | (required) | `input_boolean` that signals sleep has been detected |

### ② Targets

| Input | Default | Description |
|-------|---------|-------------|
| **Lights to turn off** | (optional) | Light entities, areas, or devices to turn off |
| **Switches to turn off** | (optional) | Switch entities to turn off (smart plugs, accent lighting, etc.) |

### ③ Time Window

| Input | Default | Description |
|-------|---------|-------------|
| **Window start** | `22:00:00` | Earliest time sleep lights can trigger |
| **Window end** | `08:00:00` | Latest time sleep lights can trigger |

### ④ Delay & Safety

| Input | Default | Description |
|-------|---------|-------------|
| **Delay (minutes)** | `15` | Minutes to wait after sleep detection before turning lights off (1--60) |

### ⑤ Privacy

| Input | Default | Description |
|-------|---------|-------------|
| **Privacy gate tier** | `off` | Privacy tier: off, t1 (intimate), t2 (personal), t3 (ambient) |
| **Privacy gate enabled entity** | `input_boolean.ai_privacy_gate_enabled` | Boolean that enables the privacy gate system |
| **Privacy gate mode entity** | `input_select.ai_privacy_gate_mode` | Select controlling gate behavior |
| **Privacy gate person** | `miquel` | Person name for tier suppression lookups |

## Technical Notes

- `mode: single` with `max_exceeded: silent` -- no overlapping runs.
- The re-check condition after the delay uses `condition: state` on the sleep detected entity -- if the flag was cleared during the delay (false positive or manual override), the automation stops without turning off lights.
- Cross-midnight time window uses the same OR logic pattern as the sleep detection blueprint.
- `continue_on_error: true` on the switch turn-off step ensures that an unreachable switch entity does not prevent lights from being turned off.
- The privacy gate supports four tiers with per-feature override via `input_select.ai_privacy_gate_sleep_lights`.

## Changelog

- **v1:** Initial blueprint -- replaces package `ai_sleep_lights.yaml`

## Author

**madalone**

## License

See repository for license details.
