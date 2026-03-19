# UPS -- Notify on power events (NUT status sensor)

![header](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/ups_notify-header.jpeg)

Sends notifications when your UPS switches to battery power, when utility power returns, and when the UPS battery is critically low. Uses the NUT integration status sensor (e.g. `sensor.madups_status`) to detect power transitions (OL/OB/CHRG) and a battery percentage sensor for low-charge warnings.

## How It Works

```
┌─────────────────────┐    ┌───────────────────────┐
│ UPS status changed  │    │ Battery dropped below  │
│ (OL/OB transitions) │    │ low-battery threshold  │
└─────────┬───────────┘    └───────────┬────────────┘
          │                            │
          ▼                            ▼
   ┌──────────────┐            ┌──────────────┐
   │ Resolve vars │            │ On battery?  │
   │ status/batt  │            │ (OB check)   │
   └──────┬───────┘            └──────┬───────┘
          │                           │ yes
    ┌─────┼─────────┐                 ▼
    ▼     ▼         ▼         ┌──────────────┐
┌──────┐┌────────┐           │  Notify:     │
│ OB   ││ Was OB │           │  Battery low │
│ now  ││ now OL │           └──────────────┘
└──┬───┘└───┬────┘
   ▼        ▼
Notify:  Notify:
Power    Power
outage   restored
```

## Features

- Detects power outage (UPS switches to battery -- status contains "OB")
- Detects power restored (UPS returns to mains from battery)
- Low battery warning when charge drops below configurable threshold while on battery
- Includes current battery percentage in all notifications
- Uses any Home Assistant notify service (mobile app, Telegram, etc.)

## Prerequisites

- Home Assistant 2024.10.0 or later
- NUT integration configured with UPS status and battery sensors
- A Home Assistant notification service (e.g. `notify.mobile_app_your_device`)

## Installation

1. Copy `ups_notify.yaml` to `config/blueprints/automation/madalone/`
2. Create automation: **Settings -> Automations -> Create -> Use Blueprint**

## Configuration

### Section 1 -- UPS sensors

| Input | Default | Description |
|---|---|---|
| UPS status sensor | _(required)_ | NUT sensor reporting UPS status (OL, OB, OB DISCHRG, OL CHRG, etc.) |
| UPS battery percentage | _(required)_ | NUT sensor reporting battery charge in percent |

### Section 2 -- Thresholds & notifications

| Input | Default | Description |
|---|---|---|
| Low battery warning threshold | 30% | Battery level below which a low-battery warning is sent (while on battery) |
| Notification service | _(required)_ | Notify service name (e.g. `notify.mobile_app_your_device`) -- free-text field |

## Technical Notes

- **Mode:** `restart` / `max_exceeded: silent` -- ensures rapid status transitions are handled cleanly
- **Template safety:** `trigger.from_state` is guarded with `is defined` and `is not none` checks
- **Low battery gate:** The low-battery notification only fires when the UPS is actually on battery (OB), not during normal charging
- **continue_on_error:** All notify actions use `continue_on_error: true` to prevent notification failures from crashing the automation

## Changelog

- **v2:** Full style guide compliance -- modern syntax, template safety, aliases
- **v1:** Initial version

## Author

**madalone**

## License

See repository for license details.
