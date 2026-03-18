# Media Play at Volume (helper script)

Set volume on a media player and play a specific media item. Useful for routines like morning radio, background music, or podcast playback at a predetermined volume. Integrates with the duck guard system to keep volume snapshots accurate during active ducking.

## How It Works

```
Start
  |
  v
+---------------------+
| Set volume on       |
| media player        |
+---------------------+
  |
  v
+---------------------+     +-------------------------+
| Duck guard +        |---->| Update duck snapshot    |
| ducking flag ON?    | yes | (continue_on_error)     |
+---------------------+     +-------------------------+
  | no                              |
  +----------------------------------+
  |
  v
+---------------------+
| Play media content  |
| (content_id + type) |
+---------------------+
  |
  v
Done
```

## Features

- Sets volume before playback for consistent listening levels
- Supports five media content types: music, radio, audiobook, playlist, podcast
- Duck guard integration keeps volume snapshot in sync during active ducking
- `continue_on_error` on duck snapshot update prevents playback failures from guard issues

## Prerequisites

- Home Assistant
- A `media_player` entity
- `input_boolean.ducking_flag` (ducking status flag)
- `input_boolean.ai_duck_guard_enabled` (duck guard toggle)
- `pyscript/duck_manager.py` (for duck snapshot updates)

## Installation

1. Copy `media_play_at_volume.yaml` to `config/blueprints/script/madalone/`
2. Create script: **Settings -> Automations & Scenes -> Scripts -> Add -> Use Blueprint**

## Configuration

<details><summary>① Configuration</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `media_player` | _(required)_ | The player to set volume on and play media through |
| `volume_level` | `0.4` | Volume to set before playback (0.0 - 1.0) |
| `media_content_id` | _(required)_ | The media ID to play (e.g. library://radio/4, a URL) |
| `media_content_type` | `music` | Type of media content: music, radio, audiobook, playlist, podcast |

</details>

<details><summary>② Infrastructure</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `ducking_flag` | `input_boolean.ducking_flag` | Boolean indicating audio ducking is active |
| `duck_guard_enabled` | `input_boolean.ai_duck_guard_enabled` | Boolean that enables the duck guard system |

</details>

## Technical Notes

- **Mode:** `single` / `max_exceeded: silent`
- Duck snapshot update only fires when both the duck guard and ducking flag are ON simultaneously
- The duck snapshot call uses `continue_on_error: true` so playback proceeds even if the snapshot service is unavailable

## Changelog

- **v1.0** -- Initial release

## Author

**madalone**

## License

See repository for license details.
