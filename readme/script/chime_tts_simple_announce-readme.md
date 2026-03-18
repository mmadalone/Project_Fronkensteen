# Chime TTS -- Simple Announce (Quark edition)

![Header](https://raw.githubusercontent.com/mmadalone/HA-Master-Repo/main/images/header/chime_tts_simple_announce-header.jpeg)

Generic Chime TTS script blueprint that plays a chime followed by a TTS announcement on selected media players via the `chime_tts.say` service. Create one script instance per voice persona, then call it from any automation or blueprint as a reusable building block.

## How It Works

```
START
  |
  v
[chime_tts.say]
  |-- chime_path: soft / doorbell / custom MP3
  |-- message: plain text or Jinja template
  |-- tts_speed: playback speed %
  |-- volume_level: announcement volume
  |-- target: media player(s)
  |
  v
END
```

## Features

- Plays a chime sound before the TTS message
- Supports built-in chime presets (soft, doorbell) or custom MP3 paths
- Adjustable TTS playback speed (50%-150%)
- Volume override (-1 = keep current volume)
- Multi-player targeting (multiple media players at once)
- Jinja template support for dynamic message content
- Queued mode for sequential announcement delivery

## Prerequisites

- Home Assistant **2024.10.0** or newer
- [Chime TTS](https://github.com/nimroddolev/chime_tts) custom integration installed

## Installation

1. Copy `chime_tts_simple_announce.yaml` to `config/blueprints/script/madalone/`
2. Create script: **Settings > Automations & Scenes > Scripts > Add > Use Blueprint**

## Configuration

<details>
<summary><strong>Section 1 -- Media Players</strong></summary>

| Input | Default | Description |
|---|---|---|
| `target_players` | _(empty)_ | Media players for chime + TTS output (supports multiple) |

</details>

<details>
<summary><strong>Section 2 -- Message & TTS Settings</strong></summary>

| Input | Default | Description |
|---|---|---|
| `message_template` | `Portal opened. Music jumped to the workshop.` | Plain text or Jinja template for the spoken message |
| `tts_speed` | `100` | TTS playback speed in percent (50-150) |

</details>

<details>
<summary><strong>Section 3 -- Chime & Volume</strong></summary>

| Input | Default | Description |
|---|---|---|
| `chime_path` | `soft` | Built-in chime name or full path to an MP3 file |
| `volume_level` | `-1` | Announcement volume (0.0-1.0); -1 = keep current volume |

</details>

## Technical Notes

- **Mode:** `queued`
- **Error handling:** `continue_on_error: true` on the `chime_tts.say` action
- **Caching:** Disabled (`cache: false`) to ensure fresh TTS renders
- **Design pattern:** One script instance per persona -- call from automations by entity ID

## Changelog

- **v2.0:** Current version -- collapsible sections, Jinja template support, speed control

## Author

**madalone**

## License

See repository for license details.
