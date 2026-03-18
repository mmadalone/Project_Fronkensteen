# Alexa Presence-Aware Radio Stop -- Music Assistant

![header](https://raw.githubusercontent.com/mmadalone/HA-Master-Repo/main/images/header/alexa_presence_radio_stop-header.jpeg)

Say "stop the music" (or any phrase you configure) to any Alexa device in your home. Home Assistant stops all configured Music Assistant players, or -- with presence-aware mode enabled -- only the player in the room where you currently have presence. Companion blueprint to the Alexa Presence-Aware Radio blueprint for a complete voice-controlled radio system.

## How It Works

```
┌──────────────────────────────────────────┐
│  "Alexa, turn on Stop Radio"             │
│  (from ANY Echo in the house)            │
└──────────────────┬───────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────┐
│  input_boolean.stop_radio -> ON          │
└──────────────────┬───────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────┐
│  Auto-reset trigger boolean              │
│  (runs FIRST -- next command always      │
│   works even if stop fails)              │
└──────────────────┬───────────────────────┘
                   │
          ┌────────┴────────┐
          ▼                 ▼
┌──────────────────┐ ┌──────────────────────┐
│  Stop All mode:  │ │  Presence mode:      │
│  Stop EVERY      │ │  Check sensors ->    │
│  configured      │ │  Stop only current   │
│  MA player       │ │  room's player       │
└────────┬─────────┘ └──────────┬───────────┘
         └──────────┬───────────┘
                    ▼
┌──────────────────────────────────────────┐
│  Optional: Reset radio trigger booleans  │
└──────────────────────────────────────────┘
```

## Features

- One voice command from any Alexa stops Music Assistant playback
- Two modes: stop all configured players, or presence-aware (only current room)
- Pause instead of stop option to preserve queues for later resume
- Auto-reset of trigger boolean for next command
- Optional reset of companion radio dispatch booleans
- Presence-aware stop uses 1:1 sensor-to-player mapping
- Falls back to stopping all players if no presence detected in presence mode

## Prerequisites

- Home Assistant 2024.10.0+
- Music Assistant integration with configured media players
- An `input_boolean` helper exposed to Alexa via HA Cloud
- An Alexa Routine that turns the boolean ON on voice command
- (Optional) Presence sensors for room-aware stop mode

## Installation

1. Copy `alexa_presence_radio_stop.yaml` to `config/blueprints/automation/madalone/`
2. Create automation: **Settings -> Automations -> Create -> Use Blueprint**

## Configuration

<details>
<summary><strong>Section 1 -- Trigger</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| Trigger entity | _(required)_ | `input_boolean` that fires this automation when Alexa turns it ON. |

</details>

<details>
<summary><strong>Section 2 -- Player Selection</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| Music Assistant players | `[]` | All MA players that can be stopped by this automation. |

</details>

<details>
<summary><strong>Section 3 -- Stop Mode</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| Presence-aware stop | `false` | Only stop the player in the room where presence is detected. |
| Presence sensors | `[]` | Binary sensors mapped 1:1 with the players list (same order). |

</details>

<details>
<summary><strong>Section 4 -- Behaviour</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| Auto-off trigger | `true` | Reset the input_boolean after stopping. |
| Pause instead of stop | `false` | Preserve queues for later resume. |
| Turn off radio booleans | `false` | Also reset companion radio dispatch trigger booleans. |
| Radio trigger booleans | `[]` | `input_boolean` entities used by radio dispatch automations. |

</details>

## Technical Notes

- **Mode:** `restart` (silent on overflow)
- The auto-reset runs first so the next command works even if the stop action fails
- In presence-aware mode, if no presence is detected, falls back to stopping all configured players
- All stop/pause actions use `continue_on_error: true` for resilience
- A `debug_summary` trace variable captures mode, target count, pause flag, and reset flag for troubleshooting

## Changelog

- **v6:** Empty-list guard on stop/pause action (AP-16), folded-string fix on condition template, `default: []` on auto-reset choose, debug_summary trace variable
- **v5:** Empty player_list guard in stop_targets template (AP-16), folded-string fixes, explicit `default: []`
- **v4:** Template hardening -- `| int(-1)` guard, trigger `id:`, all inputs in variables, `continue_on_error`
- **v3:** Template safety (`| default()`), section naming/dividers, explicit `conditions: []`

## Author

**madalone**

## License

See repository for license details.
