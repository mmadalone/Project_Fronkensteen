# Wake-Up Guard -- Mobile Snooze/Stop Handler

![header](https://raw.githubusercontent.com/mmadalone/HA-Master-Repo/main/images/header/wakeup_guard_mobile_notify-header.jpeg)

Handles Snooze and Stop actions for the Wake-Up Guard automation. Reacts to Companion app notification actions (`GUARD_SNOOZE` / `GUARD_STOP`) or the snooze/stop `input_boolean` helpers being turned ON (e.g., from a dashboard button). Turns on the matching toggle so the main wake-up blueprint takes the right branch, then immediately stops TTS and optionally music players.

## How It Works

```
┌─────────────────────────────────────┐
│ Triggers (any of 4)                 │
│  ├─ mobile_app: GUARD_SNOOZE       │
│  ├─ mobile_app: GUARD_STOP         │
│  ├─ snooze_toggle turned ON        │
│  └─ stop_toggle turned ON          │
└──────────────┬──────────────────────┘
               │
    ┌──────────▼──────────────┐
    │ Resolve target toggle   │
    │ (snooze or stop)        │
    └──────────┬──────────────┘
               │
    ┌──────────▼──────────────┐
    │ Turn ON target toggle   │
    │ (signals main blueprint)│
    └──────────┬──────────────┘
               │
    ┌──────────▼──────────────┐
    │ Stop TTS player         │
    └──────────┬──────────────┘
               │
    ┌──────────▼──────────────┐
    │ Stop music players      │
    │ (if configured)         │
    └─────────────────────────┘
```

## Features

- Dual input: mobile notification actions and dashboard toggle buttons
- Unified action path for both snooze and stop
- Immediately silences TTS and music players
- Designed to pair with the main Wake-Up Guard blueprint
- Configurable notification action IDs with custom value support

## Prerequisites

- Home Assistant 2024.10.0+
- Two `input_boolean` helpers matching the main Wake-Up Guard configuration
- Mobile Companion app (for notification action triggers)

## Installation

1. Copy `wakeup_guard_mobile_notify.yaml` to `config/blueprints/automation/madalone/`
2. Create automation: **Settings -> Automations -> Create -> Use Blueprint**

## Configuration

<details><summary><strong>① Toggles & Entities</strong></summary>

| Input | Default | Description |
|---|---|---|
| `snooze_toggle` | _(required)_ | Same `input_boolean` as "Snooze toggle" in Wake-Up Guard |
| `stop_toggle` | _(required)_ | Same `input_boolean` as "Stop toggle" in Wake-Up Guard |
| `tts_player` | _(required)_ | Media player used by TTS (same as in the main blueprint) |
| `music_players` | `[]` | Additional media players playing wake-up music (optional) |

</details>

<details><summary><strong>② Notification Action IDs</strong></summary>

| Input | Default | Description |
|---|---|---|
| `snooze_action_id` | `GUARD_SNOOZE` | Notification action ID for Snooze (must match Companion app) |
| `stop_action_id` | `GUARD_STOP` | Notification action ID for Stop (must match Companion app) |

</details>

## Technical Notes

- **Mode:** `restart` -- a new snooze/stop action immediately overrides any in-progress sequence
- **Error handling:** `continue_on_error: true` on both media stop actions
- **Queue destruction:** Music player stop is intentional in wake-up context (no need to preserve queue)

## Changelog

- **v3:** Refactored to single action path, added continue_on_error, section polish
- **v2:** Full style-guide compliance -- modern syntax, collapsible inputs, aliases
- **v1:** Initial version

## Author

**madalone**

## License

See repository for license details.
