# Wake-Up Guard -- External Alarm Trigger

![header](https://raw.githubusercontent.com/mmadalone/HA-Master-Repo/main/images/header/wake_up_guard_external_alarm-header.jpeg)

Triggers a wake-up script based on an external alarm-time sensor, such as an Android phone's next alarm (`sensor.<phone>_next_alarm`) or an Alexa Media Player next alarm. Optionally fires some minutes before the alarm instead of exactly at the alarm time. Designed to hook into an existing wake-up script that handles the actual routine (lights, music, TTS).

## How It Works

```
┌──────────────────────────┐
│ Trigger                  │
│  time_pattern: every 1m  │
└──────────┬───────────────┘
           │
    ┌──────▼──────────────────────────┐
    │ Condition                       │
    │  Alarm sensor valid?            │
    │  Current time within 60s of     │
    │  (alarm_time - offset)?         │
    └──────┬────────────────┬─────────┘
          yes               no
           │                └──▶ skip
    ┌──────▼──────────┐
    │ Run wake-up     │
    │ script          │
    └─────────────────┘
```

## Features

- Works with any timestamp sensor (Android Companion, Alexa Media Player, etc.)
- Configurable offset: fire 0-120 minutes before the alarm
- Template-safe: handles unknown/unavailable/empty alarm states gracefully
- Delegates all wake-up behavior to an external script (separation of concerns)

## Prerequisites

- Home Assistant 2024.10.0+
- A sensor with `device_class: timestamp` that holds the next alarm time
- A wake-up script (e.g., `script.wake_up_guard_rick`)

## Installation

1. Copy `wake_up_guard_external_alarm.yaml` to `config/blueprints/automation/madalone/`
2. Create automation: **Settings -> Automations -> Create -> Use Blueprint**

## Configuration

<details><summary><strong>① Alarm Source</strong></summary>

| Input | Default | Description |
|---|---|---|
| `alarm_sensor` | _(required)_ | Sensor with device_class `timestamp` holding next alarm time |
| `offset_minutes` | `0` | Minutes before alarm to trigger (0 = exact, 10 = 10 min early) |

</details>

<details><summary><strong>② Wake-up Action</strong></summary>

| Input | Default | Description |
|---|---|---|
| `wakeup_script` | _(required)_ | Script entity that performs the actual wake-up routine |

</details>

## Technical Notes

- **Mode:** `single`, `max_exceeded: silent`
- **Polling approach:** Uses `time_pattern` every minute rather than a time trigger, since the alarm sensor value changes dynamically
- **Window logic:** Fires when the target timestamp (alarm minus offset) is between 0 and 60 seconds in the future, ensuring exactly one trigger per alarm
- **Error handling:** `continue_on_error: true` on the script call

## Changelog

- **v3 (2026-02-17):** Audit fixes -- collapsible defaults, `source_url`, `homeassistant: min_version` nesting, `continue_on_error`
- **v2 (2026-02-11):** Full style-guide compliance -- header image, collapsible sections, variables block, 2024.10+ syntax, template safety guards

## Author

**madalone**

## License

See repository for license details.
