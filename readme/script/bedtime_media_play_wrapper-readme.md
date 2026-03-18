# Bedtime Media Play Wrapper -- Music Assistant

![Bedtime Media Play Wrapper header](https://raw.githubusercontent.com/mmadalone/HA-Master-Repo/main/images/header/bedtime_media_play_wrapper-header.jpeg)

Wrapper script to play bedtime media (especially audiobooks) via Music Assistant. Always targets the passed-in MA media_player, so bedtime blueprints can pass their selected player directly. Supports optional volume, shuffle, and enqueue control with duck guard integration.

## How It Works

```
START
  |
  v
[Resolve inputs: player, media_id, media_type, enqueue, volume, shuffle]
  |
  v
<Volume provided?>
  |         |
 YES        NO
  |         |
  v         |
[Set volume on player]
  |         |
  v         |
<Duck guard active?>
  |    |    |
  YES  NO   |
  |    |    |
  v    |    |
[Sync duck snapshot]
  |    |    |
  +----+----+
       |
       v
[Play media via music_assistant.play_media]
       |
       v
<Shuffle enabled?>
  |         |
 YES        NO
  |         |
  v         |
[Enable shuffle on player]
  |         |
  +----+----+
       |
       v
END
```

## Features

- Clean wrapper for Music Assistant `play_media` action
- Supports audiobook, podcast, radio, track, album, artist, playlist media types
- Optional volume set before playback (skip by leaving empty)
- Optional shuffle toggle after playback starts
- Enqueue mode: `replace` (start fresh) or `add` (append to queue)
- Duck guard snapshot sync when volume is changed during active ducking
- Queued mode supports up to 10 concurrent calls

## Prerequisites

- Home Assistant **2024.10.0** or newer
- Music Assistant integration
- Duck guard system (optional: `input_boolean.ducking_flag`, `input_boolean.ai_duck_guard_enabled`)

## Installation

1. Copy `bedtime_media_play_wrapper.yaml` to `config/blueprints/script/madalone/`
2. Create script: **Settings > Automations & Scenes > Scripts > Add > Use Blueprint**

## Configuration

<details>
<summary><strong>Section 1 -- Playback</strong></summary>

| Input | Default | Description |
|---|---|---|
| `media_player` | _(empty)_ | Target Music Assistant media_player entity |
| `media_type` | `audiobook` | Media type: audiobook, podcast, radio, track, album, artist, playlist |
| `media_id` | _(empty)_ | Media ID: name or URI (e.g. `library://audiobook/86`) |
| `enqueue` | `replace` | Replace starts fresh; Add appends to queue |

</details>

<details>
<summary><strong>Section 2 -- Volume & Behavior</strong></summary>

| Input | Default | Description |
|---|---|---|
| `volume` | _(empty)_ | Playback volume (0.0-1.0). Leave empty to keep current |
| `shuffle` | `false` | Enable shuffle on target player after playback starts |

</details>

<details>
<summary><strong>Section 3 -- Infrastructure</strong></summary>

| Input | Default | Description |
|---|---|---|
| `ducking_flag` | `input_boolean.ducking_flag` | Boolean indicating audio ducking is active |
| `duck_guard_enabled` | `input_boolean.ai_duck_guard_enabled` | Boolean that enables the duck guard system |

</details>

## Technical Notes

- **Mode:** `queued` / `max: 10`
- **Error handling:** `continue_on_error: true` on volume set, duck snapshot sync, and shuffle set
- **Volume sentinel:** Empty list `[]` is used as the "no volume" sentinel since number selectors have no native "unset" state
- **Duck guard:** Snapshot is synced only when both `duck_guard_enabled` and `ducking_flag` are ON

## Changelog

- **v2:** Restructured header, collapsible inputs, conditional shuffle, aliases
- **v1:** Initial version -- basic MA play_media wrapper with volume control

## Author

**madalone**

## License

See repository for license details.
