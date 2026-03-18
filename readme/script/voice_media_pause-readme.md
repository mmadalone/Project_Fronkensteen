# Voice -- Pause Active Media (tool script)

![Voice -- Pause Active Media](https://raw.githubusercontent.com/mmadalone/HA-Master-Repo/main/images/header/voice_media_pause.jpeg)

Pauses the currently active media player. This script is a thin wrapper around the "Voice -- Active Media Controls" automation blueprint -- it passes the `pause_active` command via `automation.trigger`, keeping all player priority logic centralized in the automation. Expose this script as a tool for your LLM conversation agent so users can say "pause" and the right player stops.

## How It Works

```
Start
  |
  v
+-----------------------------+
| Resolve automation state    |
| (available + enabled?)      |
+-----------------------------+
  |
  +----------+-----------+
  |                      |
  v                      v
 OK                  Missing/Disabled
  |                      |
  |                      v
  |               +------------------+
  |               | Notifications    |
  |               | enabled?         |
  |               +------------------+
  |                 | yes        | no
  |                 v            |
  |          +------------+     |
  |          | Persistent |     |
  |          | notification|    |
  |          +------------+     |
  |                 |           |
  |                 +-----+----+
  |                       |
  |                       v
  |                    STOP
  |
  v
+-----------------------------+
| automation.trigger          |
| command = "pause_active"    |
| skip_condition = true       |
+-----------------------------+
  |
  v
Done (automation finds +
      pauses active player)
```

## Features

- Single-purpose LLM tool script -- exposes "pause active media" as a callable action
- Delegates all player priority logic to the Voice Active Media Controls automation
- Availability gate with optional persistent notification on misconfiguration
- Editable phrase lists for LLM agent prompt documentation (pause intent + exclude phrases)
- Phrase lists stored in HA for easy syncing with agent descriptions

## Prerequisites

- Home Assistant
- An automation created from the "Voice -- Active Media Controls (Kodi / MA / SpotifyPlus / Alexa / etc.)" blueprint
- The automation must be enabled

## Installation

1. Copy `voice_media_pause.yaml` to `config/blueprints/script/madalone/`
2. Create script: **Settings -> Automations & Scenes -> Scripts -> Add -> Use Blueprint**
3. Expose the script to your LLM agent (Settings -> Entities -> toggle Assist)

## Configuration

<details><summary>① Core configuration</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `active_media_automation` | _(required)_ | The Voice Active Media Controls automation entity |
| `enable_notifications` | `true` | Create persistent notification if automation is missing/disabled |

</details>

<details><summary>② Phrase configuration</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `pause_phrases` | `[pause, pause it, pause the TV, stop the music, stop that sound, hold on a second]` | Example phrases that should trigger a media pause (for LLM prompt) |
| `pause_exclude_phrases` | `[don't pause keep going, I said don't pause it]` | Example phrases where "pause" appears but should NOT trigger this tool |

</details>

## Technical Notes

- **Mode:** `single` / `max_exceeded: silent`
- The phrase lists are not parsed by the script -- they exist purely as documentation for your LLM agent prompt
- The script calls `automation.trigger` with `skip_condition: true` and `variables: { command: "pause_active" }` to invoke the automation unconditionally
- If the automation entity is unavailable, unknown, or disabled (state `off`), the script stops early

## Changelog

- **v2.0** -- Full style-guide compliance (collapsible sections, action syntax, aliases)
- **v1.0** -- Initial release

## Author

**madalone**

## License

See repository for license details.
