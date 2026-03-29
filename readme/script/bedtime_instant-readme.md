![Voice -- Bedtime Instant Shutdown](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/bedtime_instant-header.jpeg)

# Voice -- Bedtime Instant Shutdown

Script blueprint that executes an instant bedtime sequence as a single tool call: announce bedtime, stop TV, play audiobook, warn before lights-off, wait, turn off lights, and say goodnight. Designed to be exposed as an LLM tool function so a voice agent can trigger a full staggered shutdown with one command.

## How It Works

```
START
  |
  v
[1. Set announcement volume]
  |
  v
[2. TTS: "Bedtime!" on announcement speaker]
  |
  v
[3. Wait announcement_delay seconds]
  |
  v
<TV entity configured?>--YES-->[4. Stop TV media]
  |                                   |
  NO                                  v
  |                      <TV power script?>--YES-->[5. Run power-off script]
  |                          |                          |
  +------+------------------+                          |
         |<-------------------------------------------+
         v
[6. Set audiobook volume]
  |
  v
[7. Play audiobook via Music Assistant]
  |
  v
[8. Seek to position 2s]
  |
  v
[9. TTS: lights-off warning on audiobook speaker]
  |
  v
[10. Wait lights_off_delay minutes]
  |
  v
[11. Turn off lights/switches]
  |
  v
[12. TTS: "Goodnight!" on audiobook speaker]
  |
  v
END
```

## Features

- Full staggered bedtime shutdown in one script call
- Optional TV stop + power-off script support
- Audiobook playback via Music Assistant with seek-to-start
- Configurable lights-off delay (1-60 minutes)
- Duck guard snapshot sync for announcement and audiobook volume changes
- All TTS messages fully customizable
- Separate announcement and audiobook speakers supported

## Prerequisites

- Home Assistant **2024.10.0** or newer
- Music Assistant integration (for audiobook playback)
- TTS entity (Piper, ElevenLabs, HA Cloud, etc.)
- Duck guard system (optional: `input_boolean.ai_ducking_flag`, `input_boolean.ai_duck_guard_enabled`)

## Installation

1. Copy `bedtime_instant.yaml` to `config/blueprints/script/madalone/`
2. Create script: **Settings > Automations & Scenes > Scripts > Add > Use Blueprint**

## Configuration

<details>
<summary><strong>Section 1 -- Speakers</strong></summary>

| Input | Default | Description |
|---|---|---|
| `tts_entity` | _(required)_ | TTS engine entity for announcements |
| `announcement_player` | _(required)_ | Media player for the initial bedtime announcement |
| `announcement_volume` | `1.0` | Volume for the announcement speaker |
| `audiobook_player` | _(required)_ | Media player for audiobook and warning/goodnight messages |

</details>

<details>
<summary><strong>Section 2 -- Media</strong></summary>

| Input | Default | Description |
|---|---|---|
| `tv_entity` | _(empty)_ | Media player to stop (e.g. Kodi). Leave empty to skip |
| `tv_power_script` | _(empty)_ | Script to power off the TV. Leave empty to skip |
| `audiobook_media_id` | `library://audiobook/86` | Music Assistant media ID for the audiobook |
| `audiobook_volume` | `0.3` | Volume level for audiobook playback |

</details>

<details>
<summary><strong>Section 3 -- Timing</strong></summary>

| Input | Default | Description |
|---|---|---|
| `announcement_delay` | `5` | Seconds between announcement and TV shutdown |
| `lights_off_delay` | `7` | Minutes between audiobook start and lights off |

</details>

<details>
<summary><strong>Section 4 -- Devices to turn off</strong></summary>

| Input | Default | Description |
|---|---|---|
| `lights_off_targets` | _(required)_ | Lights and switches to turn off when timer expires |

</details>

<details>
<summary><strong>Section 5 -- Messages</strong></summary>

| Input | Default | Description |
|---|---|---|
| `announcement_message` | `That's it, I'm shutting everything down, and putting you to bed!` | Initial bedtime announcement |
| `warning_message` | `You have seven minutes til lights out.` | Warning before lights go out |
| `goodnight_message` | `Good night!` | Final message after lights off |

</details>

<details>
<summary><strong>Section 6 -- Infrastructure</strong></summary>

| Input | Default | Description |
|---|---|---|
| `ducking_flag` | `input_boolean.ai_ducking_flag` | Boolean indicating audio ducking is active |
| `duck_guard_enabled` | `input_boolean.ai_duck_guard_enabled` | Boolean that enables the duck guard system |

</details>

## Technical Notes

- **Mode:** `single` / `max_exceeded: silent`
- **Error handling:** `continue_on_error: true` on TV stop, TV power-off script, audiobook play, and seek actions
- **Duck guard:** After each `media_player.volume_set`, the script syncs the duck snapshot if guard + ducking are both active
- **Seek position:** Seeks to 2 seconds (not 0) to avoid potential edge cases with position 0

## Changelog

- **v1.0:** Initial version -- full staggered bedtime shutdown

## Author

**Madalone + Assistant**

## License

See repository for license details.
