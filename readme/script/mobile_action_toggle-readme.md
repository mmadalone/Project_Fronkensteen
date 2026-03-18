# Mobile Action Toggle (helper script)

Fires a `mobile_app_notification_action` event and turns on an `input_boolean`. Used to bridge dashboard buttons with mobile notification action handlers (e.g. alarm snooze/stop from a dashboard). Create one instance per action you want to expose on a dashboard.

## How It Works

```
Start
  |
  v
+-------------------------------+
| Fire mobile_app_notification  |
| _action event                 |
| (action + source)             |
+-------------------------------+
  |
  v
+-------------------------------+
| Turn ON input_boolean         |
| (toggle_entity)               |
+-------------------------------+
  |
  v
Done
```

## Features

- Fires the same `mobile_app_notification_action` event that tapping a notification action would
- Configurable event source identifier (default: `dashboard`)
- Turns on an associated input_boolean for automations that listen on state changes
- One blueprint instance per action keeps configuration clean and reusable

## Prerequisites

- Home Assistant
- An `input_boolean` entity for each action toggle
- An automation that listens for `mobile_app_notification_action` events or the toggle state

## Installation

1. Copy `mobile_action_toggle.yaml` to `config/blueprints/script/madalone/`
2. Create script: **Settings -> Automations & Scenes -> Scripts -> Add -> Use Blueprint**

## Configuration

<details><summary>① Configuration</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `event_action` | _(required)_ | The action string to fire (e.g. GUARD_SNOOZE, GUARD_STOP) |
| `event_source` | `dashboard` | Source identifier for the event |
| `toggle_entity` | _(required)_ | The input_boolean to turn on |

</details>

## Technical Notes

- **Mode:** `single` / `max_exceeded: silent`
- The event fires first, then the toggle turns on -- order matters if automations listen on both
- Designed for pairing with wake-up guard and similar notification-action-driven automations

## Changelog

- **v1.0** -- Initial release

## Author

**madalone**

## License

See repository for license details.
