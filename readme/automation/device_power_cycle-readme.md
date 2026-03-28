![Device Power Cycle -- Scheduled Reboot via Smart Plug](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/device_power_cycle-header.jpeg)

# Device Power Cycle -- Scheduled Reboot via Smart Plug

Turns a smart plug OFF at a scheduled time, waits a configurable number of seconds, then turns it back ON. Use for speakers, routers, or any device that benefits from a daily power cycle.

## How It Works

```
Scheduled time
        |
        v
+-------------------+
| switch.turn_off   |
+-------------------+
        |
        v
+-------------------+
| Wait N seconds    |
| (configurable)    |
+-------------------+
        |
        v
+-------------------+
| switch.turn_on    |
+-------------------+
```

## Features

- Simple scheduled power cycle at a configurable time of day
- Configurable off duration (5-300 seconds)
- Works with any switch-domain entity (smart plugs, relays, etc.)
- No conditions -- fires unconditionally at the scheduled time

## Prerequisites

- Home Assistant 2024.10.0+
- A `switch` entity controlling the target device (smart plug, relay, etc.)

## Installation

1. Copy `device_power_cycle.yaml` to `config/blueprints/automation/madalone/`
2. Create automation: **Settings -> Automations -> Create -> Use Blueprint**

## Configuration

<details><summary>① Device & Schedule</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `target_switch` | _(empty)_ | Switch entity controlling the device to power cycle |
| `cycle_time` | `07:59:00` | Time of day to trigger the power cycle |

</details>

<details><summary>② Timing</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `off_duration` | `60` | Seconds to keep the switch off before turning back on |

</details>

## Technical Notes

- **Mode:** `single` (silent on exceeded) -- prevents overlapping cycles
- **No conditions:** The automation fires unconditionally at the scheduled time. Add conditions externally if needed (e.g., via automation editor)
- **Use case examples:** Daily router reboot, speaker refresh, modem power cycle
- **Default timing:** 07:59 with 60-second off duration -- device is back online by 08:00

## Changelog

- **v1:** Initial version

## Author

**madalone**

## License

See repository for license details.
