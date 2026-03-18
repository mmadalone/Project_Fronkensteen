# Wake-up Music -- Music Assistant (Simple)

![Wake-up music MA header](https://raw.githubusercontent.com/mmadalone/HA-Master-Repo/main/images/header/wakeup_music_ma-header.jpeg)

Simple helper script: set volume, clear queue, and play one item on a Music Assistant player. Supports configurable enqueue mode and radio mode for continuous playback. No post-playback logic -- handle that with a separate automation if needed. Includes duck guard integration to keep volume snapshots accurate during active ducking.

## How It Works

```
Called from wake-up automation
            |
            v
  ┌──────────────────────────────────┐
  │ 1) Set volume BEFORE playback    │
  │    (continue_on_error: true)     │
  └───────────┬──────────────────────┘
              |
              v
  ┌──────────────────────────────────┐
  │ 2) Duck guard active?            │
  │    YES → update duck snapshot    │
  │    NO  → skip                    │
  └───────────┬──────────────────────┘
              |
              v
  ┌──────────────────────────────────┐
  │ 3) Clear queue — fresh start     │
  │    (continue_on_error: true)     │
  └───────────┬──────────────────────┘
              |
              v
  ┌──────────────────────────────────┐
  │ 4) Play media via Music Asst.   │
  │    ┌──────────────────────┐      │
  │    │ Radio mode = Always  │──→ radio_mode: true   │
  │    │ Radio mode = Never   │──→ radio_mode: false  │
  │    │ Use player settings  │──→ (no radio_mode)    │
  │    └──────────────────────┘      │
  └──────────────────────────────────┘
```

## Features

- Set volume before playback with automatic duck snapshot sync
- Clear queue for a fresh wake-up start
- Configurable media type: music, track, album, artist, playlist, radio
- Enqueue mode: replace, play, next, or add
- Three-way radio mode: Always (force continuous), Never (force off), or Use player settings
- Duck guard integration -- keeps ducking volume snapshots accurate
- Music Assistant entity filter on player selector -- only shows MA players

## Prerequisites

- Home Assistant **2024.10.0** or later
- **Music Assistant** integration installed and configured
- At least one Music Assistant media player entity
- Duck guard system (optional -- `input_boolean.ducking_flag` and `input_boolean.ai_duck_guard_enabled`)

## Installation

1. Copy `wakeup_music_ma.yaml` to `config/blueprints/script/madalone/`
2. Create script: **Settings -> Automations & Scenes -> Scripts -> Add -> Use Blueprint**

## Configuration

<details>
<summary><strong>① Player & Media</strong></summary>

| Input | Default | Description |
|---|---|---|
| `player` | _(none)_ | Music Assistant speaker to play on (MA players only) |
| `media_id` | _(none)_ | Media identifier: URI, library name, or any string MA can resolve |
| `media_type` | `music` | Type of media (music, track, album, artist, playlist, radio) |

</details>

<details>
<summary><strong>② Playback Settings</strong></summary>

| Input | Default | Description |
|---|---|---|
| `volume_before` | `0.6` | Volume level before playback (0.0--1.0) |
| `enqueue_mode` | `replace` | Queue behavior: replace (clear + play), play (play now, keep queue), next (insert after current), add (append) |
| `radio_mode` | `Use player settings` | Continuous playback: Always (force on), Never (force off), or Use player settings |

</details>

<details>
<summary><strong>③ Infrastructure</strong></summary>

| Input | Default | Description |
|---|---|---|
| `ducking_flag` | `input_boolean.ducking_flag` | Boolean indicating audio ducking is active |
| `duck_guard_enabled` | `input_boolean.ai_duck_guard_enabled` | Boolean that enables the duck guard system |

</details>

## Technical Notes

- **Mode:** `single`
- **Version:** 2.2
- Volume set and queue clear both use `continue_on_error: true` -- playback proceeds even if these fail
- Radio mode uses a `choose` block with three branches; the default (Use player settings) omits the `radio_mode` parameter entirely, letting the MA player's own setting apply
- Duck snapshot update is conditional: only fires when both `duck_guard_enabled` and `ducking_flag` are ON
- Player selector is filtered to `integration: music_assistant` -- do not use the underlying platform entity (Alexa, ESPHome, Sonos, etc.)

## Changelog

- **v2.2** -- Duck guard: `volume_set` now calls `duck_manager_update_snapshot` so ducking snapshots stay accurate
- **v2.1** -- QA audit remediation: collapsible section defaults + collapsed flags, `continue_on_error` on volume set, template default guards
- **v2** -- Full rebuild: `music_assistant.play_media`, modern syntax, collapsible sections, radio_mode/enqueue inputs, MA entity filter
- **v1** -- Initial version (used generic `media_player.play_media`)

## Author

**madalone**

## License

See repository for license details.
