# Voice -- Play Bedtime Audiobook (Music Assistant)

![Header](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/voice_play_bedtime_audiobook.jpeg)

LLM tool wrapper that plays an audiobook (or other media type) via Music Assistant on a designated player at a configurable volume. Designed as a voice-agent tool script -- the LLM passes title, player, and optional volume at runtime via fields. Instantiate once per use-case (e.g. one for audiobooks, one for podcasts) with different defaults, then register each instance as an LLM tool.

## How It Works

```
LLM calls script with title, player, volume
            |
            v
  ┌─────────────────────────┐
  │ Resolve inputs & fields │
  │ (field overrides win)   │
  └───────────┬─────────────┘
              |
              v
  ┌─────────────────────────┐
  │ Set playback volume     │
  │ on target player        │
  └───────────┬─────────────┘
              |
              v
  ┌─────────────────────────────────┐
  │ Duck guard active?              │
  │  YES → update duck snapshot     │
  │  NO  → skip                     │
  └───────────┬─────────────────────┘
              |
              v
  ┌─────────────────────────┐
  │ Play media via          │
  │ music_assistant.play    │
  │ (title, type, enqueue)  │
  └─────────────────────────┘
```

## Features

- Voice-agent tool script -- LLM passes `title`, `player`, and optional `volume` at runtime
- Configurable media type: audiobook, podcast, track, album, artist, playlist, or radio
- Enqueue mode: replace (clear queue) or add (append)
- Field-level volume override with blueprint default fallback
- Duck guard integration -- updates volume snapshot when ducking is active
- `continue_on_error` on volume step for resilience

## Prerequisites

- Home Assistant **2024.10.0** or later
- **Music Assistant** integration installed and configured
- At least one Music Assistant media player entity
- Duck guard system (optional -- `input_boolean.ducking_flag` and `input_boolean.ai_duck_guard_enabled`)

## Installation

1. Copy `voice_play_bedtime_audiobook.yaml` to `config/blueprints/script/madalone/`
2. Create script: **Settings -> Automations & Scenes -> Scripts -> Add -> Use Blueprint**

## Configuration

<details>
<summary><strong>① Playback Defaults</strong></summary>

| Input | Default | Description |
|---|---|---|
| `default_volume` | `0.35` | Fallback volume when the caller doesn't specify one (0.0--1.0) |
| `media_type` | `audiobook` | Media type sent to Music Assistant (audiobook, podcast, track, album, artist, playlist, radio) |
| `enqueue` | `replace` | Queue behavior: `replace` clears queue and starts fresh; `add` appends |

</details>

<details>
<summary><strong>② Infrastructure</strong></summary>

| Input | Default | Description |
|---|---|---|
| `ducking_flag` | `input_boolean.ducking_flag` | Boolean indicating audio ducking is active |
| `duck_guard_enabled` | `input_boolean.ai_duck_guard_enabled` | Boolean that enables the duck guard system |

</details>

### Runtime Fields (passed by LLM)

| Field | Required | Description |
|---|---|---|
| `title` | Yes | Media title (or URI) to search for and play |
| `player` | Yes | Media player entity to play on |
| `volume` | No | Playback volume (0.0--1.0); uses blueprint default if omitted |

## Technical Notes

- **Mode:** `single` -- only one playback request at a time
- **Version:** 1.1.0
- Volume set uses `continue_on_error: true` so playback proceeds even if the volume call fails
- Duck snapshot update is conditional -- only fires when both `duck_guard_enabled` and `ducking_flag` are ON
- Field overrides use Jinja defaults: `volume | default(_default_volume) | float(_default_volume)`

## Changelog

- **v1.1.0** -- Duck guard integration, field-based volume override, style guide compliance

## Author

**madalone**

## License

See repository for license details.
