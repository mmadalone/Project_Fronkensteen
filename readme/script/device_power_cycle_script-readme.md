![Device Power Cycle (manual script)](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/device_power_cycle_script-header.jpeg)

# Device Power Cycle (manual script)

Script blueprint for on-demand power cycling of a switch entity. Turns off the target switch, waits a configurable duration, then turns it back on. Ideal for rebooting speakers, routers, or smart-plug-controlled devices. For scheduled automatic power cycling, use the `device_power_cycle` automation blueprint instead.

## How It Works

```
START
  |
  v
[Turn OFF target switch]
  |
  v
[Wait delay_seconds]
  |
  v
[Turn ON target switch]
  |
  v
END
```

## Features

- Simple off-wait-on power cycle for any switch entity
- Configurable off duration (5-300 seconds, default 60)
- Single mode prevents overlapping power cycles
- Clean companion to the scheduled `device_power_cycle` automation blueprint

## Prerequisites

- Home Assistant **2024.10.0** or newer
- A switch entity controlling the device to power cycle

## Installation

1. Copy `device_power_cycle_script.yaml` to `config/blueprints/script/madalone/`
2. Create script: **Settings > Automations & Scenes > Scripts > Add > Use Blueprint**

## Configuration

<details>
<summary><strong>Section 1 -- Configuration</strong></summary>

| Input | Default | Description |
|---|---|---|
| `target_switch` | _(required)_ | The switch entity to power cycle |
| `delay_seconds` | `60` | How long to keep the device off before turning it back on (5-300 seconds) |

</details>

## Technical Notes

- **Mode:** `single` / `max_exceeded: silent`
- **Error handling:** No `continue_on_error` -- if the switch fails to turn off, the script stops (desired behavior for power cycling)
- **Delay resolution:** Uses `int(60)` fallback to ensure delay is always valid

## Changelog

- **v1.0:** Initial version -- basic off-wait-on power cycle

## Author

**Madalone + Assistant**

## License

See repository for license details.
