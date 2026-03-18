# Wake-up Chime

![Header](https://raw.githubusercontent.com/mmadalone/HA-Master-Repo/main/images/header/wakeup_chime-header.jpeg)

Plays a simple chime sound on a media player before the wake-up sequence starts yelling. A minimal helper script -- one action, one player, one sound file. Designed to be called from wake-up automations as a gentle audio cue before TTS or music kicks in.

## How It Works

```
Called from wake-up automation
            |
            v
  ┌─────────────────────────────┐
  │ Play chime media file       │
  │ on target media player      │
  │ (continue_on_error: true)   │
  └─────────────────────────────┘
```

## Features

- Single-action chime playback -- minimal and focused
- Configurable media URL/path and media type
- `continue_on_error: true` -- chime failure doesn't block the wake-up sequence
- Works with any media player (not limited to Music Assistant)

## Prerequisites

- Home Assistant **2024.10.0** or later
- A media player entity
- A chime sound file accessible to HA (e.g. `/local/sounds/chime.mp3` in the `www` folder)

## Installation

1. Copy `wakeup_chime.yaml` to `config/blueprints/script/madalone/`
2. Create script: **Settings -> Automations & Scenes -> Scripts -> Add -> Use Blueprint**

## Configuration

<details>
<summary><strong>① Chime Settings</strong></summary>

| Input | Default | Description |
|---|---|---|
| `player` | _(none)_ | Media player that should play the chime |
| `media_id` | `/local/sounds/chime.mp3` | Chime media URL or local path |
| `media_type` | `music` | Media content type (e.g. music, sound, audio/mp3) |

</details>

## Technical Notes

- **Mode:** `single`
- **Version:** 1.1.0
- Uses `media_player.play_media` (generic HA service, not Music Assistant-specific)
- `continue_on_error: true` ensures the calling automation proceeds even if the chime file is missing or the player is unavailable
- Place chime files in `/config/www/sounds/` to serve them at `/local/sounds/`

## Changelog

- **v1.1.0** -- Style guide compliance pass (AP-06, BP-1, VER-2)

## Author

**madalone**

## License

See repository for license details.
