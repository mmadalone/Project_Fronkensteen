# Alexa Presence-Aware Radio -- Music Assistant

![header](https://raw.githubusercontent.com/mmadalone/HA-Master-Repo/main/images/header/alexa_presence_radio-header.jpeg)

Say a single phrase to any Alexa device in your home. Home Assistant determines which room you are in using presence sensors and plays the configured radio station (or other media) on that room's Music Assistant speaker. One voice command, one Alexa routine, any Echo -- HA handles the room detection. Supports up to 10 additional zone mappings, Follow-Me interlock, and post-play verification.

## How It Works

```
┌──────────────────────────────────────┐
│  "Alexa, turn on Radio Klara"        │
│  (from ANY Echo in the house)        │
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│  input_boolean.radio_klara -> ON     │
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│  Auto-reset trigger boolean          │
│  (runs FIRST so Alexa can re-fire)   │
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│  Gates:                              │
│  ├─ Person home? (optional)          │
│  ├─ Voice assistant guard? (opt.)    │
│  ├─ Target player resolved?         │
│  └─ Target already playing? (opt.)  │
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│  Presence detection (priority order) │
│  ├─ Primary rooms (1:1 mapping)      │
│  ├─ Extra zones 1-10                 │
│  └─ Fallback player                  │
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│  Disable Follow-Me (optional)        │
│  Stop/pause other players (opt.)     │
│  Set volume (optional)               │
│  Play media on target speaker        │
│  Verify playback (3s delay)          │
│  Re-enable Follow-Me (optional)      │
└──────────────────────────────────────┘
```

## Features

- One voice command from any Alexa triggers presence-based room detection
- Priority-ordered presence sensor mapping -- first detected room wins
- Up to 10 additional zone mappings for zones sharing speakers with other rooms
- Fallback player when no presence is detected
- Minimum presence duration filter to avoid walk-through false positives
- Optional volume override before playback
- Multiple media types: radio, playlist, album, track, artist
- Configurable enqueue mode (replace, add, play next)
- Radio mode control (player settings, always on, never)
- Auto-reset of trigger boolean for next command
- Optional active playback protection (skip if speaker already playing)
- Optional stop/pause of other configured players with queue preservation
- Follow-Me interlock -- disables during room detection, re-enables after playback starts
- Post-play verification with logbook warning on failure
- Person-home gate and voice assistant guard
- Duck guard snapshot updates after volume changes

## Prerequisites

- Home Assistant 2024.10.0+
- Music Assistant integration with configured media players
- An `input_boolean` helper exposed to Alexa via HA Cloud
- An Alexa Routine that turns the boolean ON on voice command
- Presence sensors (Aqara FP2, PIR, or any binary_sensor)

## Installation

1. Copy `alexa_presence_radio.yaml` to `config/blueprints/automation/madalone/`
2. Create automation: **Settings -> Automations -> Create -> Use Blueprint**

## Configuration

<details>
<summary><strong>Section 1 -- Trigger & Room Mapping</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| Trigger entity | _(required)_ | `input_boolean` that fires this automation when Alexa turns it ON. |
| Presence sensors | `[]` | Binary sensors in priority order -- first ON sensor wins. |
| Music Assistant players | `[]` | MA players mapped 1:1 with presence sensors (same order). |
| Fallback player | _(empty)_ | Speaker to use when no room has presence. |

</details>

<details>
<summary><strong>Section 2 -- Additional Zone Mappings</strong> (up to 10 slots)</summary>

Each slot has two inputs:

| Input | Default | Description |
|-------|---------|-------------|
| Extra zone N -- Presence sensor | _(empty)_ | Binary sensor for the extra zone. Leave empty if unused. |
| Extra zone N -- Music Assistant player | _(empty)_ | Target speaker -- can reuse a primary room speaker. |

</details>

<details>
<summary><strong>Section 3 -- Media & Playback</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| Radio station or media | _(empty)_ | Name or content ID as it appears in the MA library. |
| Media type | `radio` | radio, playlist, album, track, or artist. |
| Enqueue mode | `replace` | Replace queue, add to queue, or play next. |
| Radio mode | `Use player settings` | Use player settings, Always, or Never. |

</details>

<details>
<summary><strong>Section 4 -- Volume Settings</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| Set volume before playback | `false` | Enable to override speaker volume before play. |
| Volume level | `25` % | Target volume (0-100). Only applied when volume override enabled. |

</details>

<details>
<summary><strong>Section 5 -- Behaviour & Safety</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| Auto-off trigger | `true` | Turn input_boolean OFF after playback starts. |
| Skip if already playing | `false` | Do not interrupt active playback on the target. |
| Minimum presence time | `0s` | Presence must be continuous for this duration before room counts. |
| Stop other players | `false` | Stop/pause all other configured players before playback. |
| Pause instead of stop | `false` | Preserve queues on other players (requires stop enabled). |
| Disable Follow-Me | `false` | Turn off Follow-Me toggle when radio starts. |
| Follow-Me entity | _(empty)_ | `input_boolean` controlling the Follow-Me automation. |

</details>

<details>
<summary><strong>Section 6 -- Infrastructure</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| Ducking flag entity | `input_boolean.ducking_flag` | Audio ducking active flag. |
| Duck guard enabled | `input_boolean.ai_duck_guard_enabled` | Duck guard system toggle. |

</details>

<details>
<summary><strong>Section 7 -- Advanced Options</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| Require person home | `false` | Only run when at least one selected person is home. |
| Persons | `[]` | Person entities to check. |
| Voice assistant guard | _(empty)_ | `input_boolean` that blocks during active voice pipelines. |

</details>

## Technical Notes

- **Mode:** `single` (silent on overflow)
- The auto-reset of the trigger boolean runs BEFORE any condition that could abort, ensuring Alexa can always re-trigger
- Extra zone pairs are filtered at template resolution time -- empty slots are silently skipped
- Post-play verification waits 3 seconds then checks player state; logs a warning if not playing/buffering
- Follow-Me is disabled before room detection and re-enabled after playback starts, so the radio follows the user between rooms

## Changelog

- **v6:** Post-play verification with logbook warning, explicit defaults on all optional entity inputs (AP-17, AP-44)
- **v5:** Follow-Me interlock -- disables during room detection, re-enables after playback
- **v4:** Folded trigger_entity into Stage 1, de-duplicated zone slot descriptions

## Author

**madalone**

## License

See repository for license details.
