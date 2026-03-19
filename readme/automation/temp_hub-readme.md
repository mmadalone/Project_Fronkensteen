# Temperature hub -- cooling fan per device

![header](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/temp_hub-header.jpeg)

Generic temperature-based cooling controller. Monitors one temperature sensor and turns a smart plug (fan) ON when it exceeds a high threshold and OFF again when it drops below a lower threshold. Uses hysteresis to avoid flapping. If the sensor becomes unavailable or unknown, the fan is turned OFF as a safety fallback. Create one automation instance per device (e.g. media center, Raspberry Pi, NAS).

## How It Works

```
┌──────────────────────┐
│  Temperature Sensor  │
│    state changed     │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐     ┌──────────────────────┐
│  HA restarted?       │────▶│  Also triggers sync  │
└──────────┬───────────┘     └──────────────────────┘
           │
           ▼
    ┌──────────────┐
    │  Evaluate    │
    │  temperature │
    └──────┬───────┘
           │
     ┌─────┼──────────────────┐
     ▼     ▼                  ▼
 ┌───────┐ ┌──────────┐ ┌──────────────┐
 │ Above │ │ Below    │ │ Unavailable/ │
 │ high  │ │ low      │ │ Unknown      │
 │ temp  │ │ temp     │ │              │
 └───┬───┘ └────┬─────┘ └──────┬───────┘
     │          │              │
     ▼          ▼              ▼
  Fan ON     Fan OFF      Fan OFF
                        (safety)
```

## Features

- Hysteresis-based control with separate ON/OFF thresholds to prevent flapping
- Multi-target support -- one or more fan switches per instance
- Safety fallback turns fan OFF when sensor reports unavailable or unknown
- Syncs fan state on Home Assistant restart
- One instance per device for independent monitoring

## Prerequisites

- Home Assistant 2024.10.0 or later
- A temperature sensor entity (e.g. Glances CPU temp, ESPHome sensor)
- One or more smart plug / switch entities controlling the fan(s)

## Installation

1. Copy `temp_hub.yaml` to `config/blueprints/automation/madalone/`
2. Create automation: **Settings -> Automations -> Create -> Use Blueprint**

## Configuration

### Section 1 -- Sensor & fan

| Input | Default | Description |
|---|---|---|
| Temperature sensor | _(required)_ | Temperature sensor to monitor for this device |
| Fan smart switches | _(required)_ | Smart plug(s) / switch(es) that power the external fan(s) -- supports multiple targets |

### Section 2 -- Thresholds

| Input | Default | Description |
|---|---|---|
| Turn fan ON above | 60 C | Temperature above which the fan turns ON |
| Turn fan OFF below | 50 C | Temperature below which the fan turns OFF (set lower than ON for hysteresis) |

## Technical Notes

- **Mode:** `single` / `max_exceeded: silent`
- **Triggers:** Temperature sensor state change + HA restart (ensures fan syncs on boot)
- **Hysteresis:** The gap between ON and OFF thresholds prevents rapid toggling when the temperature hovers near a single threshold
- **Safety:** If the sensor enters `unavailable` or `unknown` state, the fan is turned OFF immediately

## Changelog

- **v3:** Multi-target support -- `fan_switch` replaced by `fan_switches` (target selector, supports multiple switches)
- **v2:** Full style guide compliance -- modern syntax, aliases, collapsible sections
- **v1:** Initial version

## Author

**madalone**

## License

See repository for license details.
