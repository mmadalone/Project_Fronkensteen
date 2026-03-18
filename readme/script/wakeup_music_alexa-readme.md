# Wake-up Music -- Alexa

![Wake-up music Alexa header](https://raw.githubusercontent.com/mmadalone/HA-Master-Repo/main/images/header/wakeup_music_alexa-header.jpeg)

Plays wake-up music on an Alexa device using `alexa_devices.send_text_command`. Sends two text commands in sequence: one to set volume, one to start a song or playlist. Simple and effective -- no Music Assistant or Spotify integration required, just the Alexa Devices integration.

## How It Works

```
Called from wake-up automation
            |
            v
  ┌─────────────────────────────────┐
  │ Send volume command to Alexa    │
  │ e.g. "set volume to 10"        │
  │ (continue_on_error: true)       │
  └───────────┬─────────────────────┘
              |
              v
  ┌─────────────────────────────────┐
  │ Send song/playlist command      │
  │ e.g. "play Mark on the bus      │
  │  by the Beastie Boys"           │
  │ (continue_on_error: true)       │
  └─────────────────────────────────┘
```

## Features

- Controls Alexa via natural language text commands -- same as voice but programmatic
- Configurable volume and song/playlist commands
- Both steps use `continue_on_error: true` for resilience
- Works with any Alexa/Echo device supported by the Alexa Devices integration

## Prerequisites

- Home Assistant **2024.10.0** or later
- **Alexa Devices** (`alexa_devices`) integration installed and configured
- At least one Alexa/Echo device registered

## Installation

1. Copy `wakeup_music_alexa.yaml` to `config/blueprints/script/madalone/`
2. Create script: **Settings -> Automations & Scenes -> Scripts -> Add -> Use Blueprint**

## Configuration

<details>
<summary><strong>① Alexa Device & Commands</strong></summary>

| Input | Default | Description |
|---|---|---|
| `alexa_device` | _(none)_ | Alexa / Echo device to control (device selector filtered to `alexa_devices` integration) |
| `volume_command` | `set volume to 10` | Text command sent to set volume before playback |
| `song_command` | `play Mark on the bus by the Beastie Boys` | Text command sent to start music |

</details>

## Technical Notes

- **Mode:** `single`
- **Version:** 2.1
- Uses `alexa_devices.send_text_command` -- sends plain-English commands to the Alexa device, the same way you'd speak to it
- Both steps have `continue_on_error: true` -- if the volume command fails, the song command still fires
- Volume is set via text command (e.g. "set volume to 10") rather than `media_player.volume_set` because Alexa Devices uses its own command interface

## Changelog

- **v2.1** -- Audit remediation: bumped `min_version` to 2024.10.0, added `version` metadata, `continue_on_error` on both steps, `default` on device input for collapsible section
- **v2** -- Modernized syntax (`action:`), added aliases, collapsible input section, header image, metadata fields, `min_version`
- **v1** -- Initial version

## Author

**madalone**

## License

See repository for license details.
