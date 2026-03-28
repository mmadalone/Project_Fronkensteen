![Sleep Detection -- Presence-Based Sleep Lifecycle](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/sleep_detection-header.jpeg)

# Sleep Detection -- Presence-Based Sleep Lifecycle

Detects sleep from sustained presence in a bed zone. Manages the full lifecycle: sleep start (flag + timestamp), sleep end (clear + event + optional log), and false positive override. Includes configurable time window with cross-midnight support and cat mitigation (multi-zone check when a specific person is away).

## How It Works

```
┌─────────────────────────────────┐
│ Triggers (3):                   │
│  A. Presence ON for N minutes   │
│     → sleep_start               │
│  B. Presence OFF               │
│     → sleep_end                 │
│  C. False positive flag ON      │
│     → false_positive            │
└──────────────┬──────────────────┘
               │
               ▼
┌─────────────────────────────────┐
│ Condition: Privacy gate         │
└──────────────┬──────────────────┘
               │
               ▼
       ┌───────┴───────┐
       ▼               ▼
┌────────────┐  ┌─────────────┐
│ SLEEP START│  │ SLEEP END   │
│            │  │             │
│ ✓ Not      │  │ ✓ Flag was  │
│   already  │  │   ON        │
│   detected │  │             │
│ ✓ In time  │  │ • Clear flag│
│   window   │  │ • Record    │
│ ✓ Cat check│  │   end time  │
│   passes   │  │ • Fire event│
│            │  │   (optional)│
│ • Set flag │  │ • Log to L2 │
│ • Record   │  │   (optional)│
│   start    │  │             │
└────────────┘  └─────────────┘
       ┌───────────────┘
       ▼
┌─────────────────┐
│ FALSE POSITIVE   │
│ • Clear flag     │
│ • Wait 2s        │
│ • Auto-reset     │
│   override flag  │
└─────────────────┘
```

## Features

- **Three-trigger lifecycle** -- sleep start (sustained presence), sleep end (presence cleared), false positive override
- **Configurable duration** -- minimum presence time before sleep is detected (15--180 minutes)
- **Cross-midnight time window** -- only detect sleep within configurable hours (e.g., 23:00--08:00)
- **Cat mitigation** -- when a specific person is away, checks additional zones to filter out pet-triggered false positives
- **False positive override** -- user can flag a detection as false; auto-resets after clearing state
- **Sleep event** -- optional `ai_sleep_ended` event with start/end timestamps for downstream consumers
- **L2 logging** -- optional pyscript call to record the sleep session
- **Privacy gate** -- tier-based suppression with per-person and per-feature overrides

## Prerequisites

- Home Assistant 2024.10.0+
- A bed/sleep zone **binary sensor** (e.g., FP2 presence sensor)
- Four helper entities: sleep detected flag, sleep start datetime, sleep end datetime, false positive flag
- Optional: `pyscript.sleep_detect_log` service for L2 logging
- Optional: additional binary sensors for cat mitigation zones

## Installation

1. Copy `sleep_detection.yaml` to `config/blueprints/automation/madalone/`
2. Create automation: **Settings → Automations → Create → Use Blueprint**

## Configuration

### ① Presence Sensor

| Input | Default | Description |
|-------|---------|-------------|
| **Presence sensor** | (required) | Binary sensor for the bed/sleep zone |
| **Minimum duration (minutes)** | `60` | How long presence must be sustained before sleep is detected (15--180) |

### ② State Helpers

| Input | Default | Description |
|-------|---------|-------------|
| **Sleep detected flag** | (required) | `input_boolean` set ON when sleep detected, OFF on wake |
| **Sleep start datetime** | (required) | `input_datetime` recording when sleep was detected |
| **Sleep end datetime** | (required) | `input_datetime` recording when sleep ended |
| **False positive flag** | (required) | `input_boolean` toggled by user to mark false positive; auto-resets |

### ③ Time Window

| Input | Default | Description |
|-------|---------|-------------|
| **Window start** | `23:00:00` | Earliest time sleep detection can trigger |
| **Window end** | `08:00:00` | Latest time sleep detection can trigger (cross-midnight supported) |

### ④ Cat Mitigation

| Input | Default | Description |
|-------|---------|-------------|
| **Enable cat mitigation** | `false` | Activate multi-zone checking when person is away |
| **Person entity to check** | (empty) | When this person is NOT home, cat mitigation activates |
| **Monitoring zones** | `[]` | Additional presence sensors; if 2+ active alongside bed sensor while person is away, detection is blocked |

### ⑤ Logging

| Input | Default | Description |
|-------|---------|-------------|
| **Log sleep to L2** | `true` | Call `pyscript.sleep_detect_log` on sleep end |
| **Fire sleep_ended event** | `true` | Fire `ai_sleep_ended` event with start/end timestamps |

### Privacy

| Input | Default | Description |
|-------|---------|-------------|
| **Privacy gate enabled entity** | `input_boolean.ai_privacy_gate_enabled` | Boolean that enables the privacy gate system |
| **Privacy gate mode entity** | `input_select.ai_privacy_gate_mode` | Select controlling gate behavior (auto/force_suppress/force_allow) |
| **Privacy gate person** | `miquel` | Person name for tier suppression lookups |

## Technical Notes

- `mode: restart` with `max_exceeded: silent` -- a new trigger replaces a running instance.
- The `sleep_start` trigger uses `for: minutes:` to require sustained presence before firing.
- Cross-midnight time window uses OR logic: `now >= start OR now <= end` when start > end.
- Cat mitigation counts active zones using `select('is_state', 'on')` -- threshold is 2+ active zones.
- The false positive branch waits 2 seconds before auto-resetting the override flag, giving the state change time to propagate.
- `continue_on_error: true` on the pyscript L2 logging call -- logging failure does not block the sleep end sequence.
- The `ai_sleep_ended` event includes ISO-formatted timestamps for start and end.

## Changelog

- **v1:** Initial blueprint -- replaces 3 automations from `ai_sleep_detection.yaml`

## Author

**madalone**

## License

See repository for license details.
