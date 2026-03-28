![Privacy Gate -- Hysteresis Controller](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/privacy_gate_hysteresis-header.jpeg)

# Privacy Gate -- Hysteresis Controller

Watches an identity confidence sensor and toggles a gate boolean when the score crosses configurable suppress/re-enable thresholds. The hysteresis gap between the two thresholds prevents flapping -- the gate turns ON (suppressed) when confidence rises above the suppress threshold, and only turns OFF (re-enabled) when confidence drops below the lower re-enable threshold.

Create one instance per person per tier (6 total for a 2-person household with 3 tiers).

## How It Works

```
┌──────────────────────┐  ┌────────────────────┐  ┌──────────────────┐
│ Confidence sensor    │  │ Suppress threshold │  │ Re-enable        │
│ changed              │  │ helper changed     │  │ threshold changed│
└──────────┬───────────┘  └─────────┬──────────┘  └────────┬─────────┘
           └────────────┬───────────┘───────────────────────┘
                        │
           ┌────────────┴────────────┐
           │ Kill switch changed     │
           └────────────┬────────────┘
                        │
                        ▼
           ┌─────────────────────────┐
           │ Kill switch OFF?        │
           │ ├─ YES → gate OFF,     │
           │ │        stop           │
           │ └─ NO → evaluate       │
           └─────────────┬───────────┘
                         │
                         ▼
           ┌─────────────────────────┐
           │ Hysteresis evaluation   │
           │                         │
           │ confidence >= suppress  │
           │  AND not suppressed     │
           │  → gate ON (suppress)   │
           │                         │
           │ confidence < re-enable  │
           │  AND suppressed         │
           │  → gate OFF (allow)     │
           │                         │
           │ else → no change        │
           └─────────────────────────┘
```

## Features

- Hysteresis-based gate control preventing rapid state flapping
- Threshold values read from input_number helpers (adjustable at runtime)
- Global kill switch: OFF = force gate open (features allowed)
- Reacts to changes in confidence sensor, both threshold helpers, and kill switch
- Designed for multi-instance deployment: 3 tiers x 2 persons = 6 instances
- Zero-delay response to confidence changes

## Prerequisites

- Home Assistant 2024.10.0+
- Identity confidence sensors (e.g. `sensor.identity_confidence_jessica`)
- Per-tier suppress/re-enable threshold helpers (`input_number`)
- Per-tier gate booleans (`input_boolean`)
- Kill switch: `input_boolean.ai_privacy_gate_enabled`

## Installation

1. Copy `privacy_gate_hysteresis.yaml` to `config/blueprints/automation/madalone/`
2. Create 6 automation instances: **Settings -> Automations -> Create -> Use Blueprint**
   - Miquel T1/T2/T3: watch Jessica's confidence, control Miquel's gate booleans
   - Jessica T1/T2/T3: watch Miquel's confidence, control Jessica's gate booleans

## Configuration

<details>
<summary><strong>① Core Settings</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| `confidence_sensor` | *(required)* | The OTHER person's identity confidence sensor |
| `suppress_threshold` | *(required)* | input_number helper for suppress-at threshold (pts) |
| `reenable_threshold` | *(required)* | input_number helper for re-enable-at threshold (pts) |
| `gate_boolean` | *(required)* | input_boolean this instance controls (ON = suppressed) |

</details>

<details>
<summary><strong>② Safety</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| `kill_switch` | `input_boolean.ai_privacy_gate_enabled` | Master toggle. When OFF, gate is forced OFF |

</details>

## Technical Notes

- **Mode:** `restart` -- ensures rapid threshold changes are evaluated immediately
- Kill switch OFF forces the gate boolean OFF and stops execution
- Suppress threshold must be higher than re-enable threshold for proper hysteresis behavior
- Default integer fallback: suppress = 30, re-enable = 20 (used if helpers are unavailable)
- The gate boolean being ON means features are suppressed; OFF means features are allowed

## Changelog

- **v1.0:** Initial release -- hysteresis controller for privacy gate system (deployed 2026-03-10)

## Author

**madalone**

## License

See repository for license details.
