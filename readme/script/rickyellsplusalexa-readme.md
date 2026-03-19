# Rick wake-up helper -- TTS + Alexa music

![Rick wake-up helper](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/rickyellsplusalexa-header.jpeg)

A reusable script blueprint that does two things in sequence: first, it uses your TTS entity to make "Rick" (or the dispatched persona) speak a wake-up message on a chosen media player; then, after a configurable delay, it sends text commands to an Alexa device to set volume and start a song, playlist, or station. Call this script from any automation -- morning routines, pomodoro overruns, idle-too-long reminders, bedtime nudges.

## How It Works

```
Start
  |
  v
+---------------------------+
| Agent selection           |
| (dispatcher > manual)     |
+---------------------------+
  |
  v
+---------------------------+
| TTS queue speak           |
| (Rick's message on       |
|  target media player)     |
+---------------------------+
  |
  v
+---------------------------+
| Post-interaction whisper  |
| (agent self-awareness)    |
+---------------------------+
  |
  v
+---------------------------+
| Delay (configurable)      |
| before Alexa commands     |
+---------------------------+
  |
  v
+---------------------------+
| Alexa: set volume         |
| (text command)            |
+---------------------------+
  |
  v
+---------------------------+
| Alexa: play wake-up music |
| (text command)            |
+---------------------------+
  |
  v
Done
```

## Features

- AI dispatcher integration with manual pipeline fallback
- TTS delivery via `pyscript.tts_queue_speak` with optional volume control
- Customizable TTS message per instance
- Configurable delay between TTS and Alexa music start
- Alexa volume and play commands via `alexa_devices.send_text_command`
- Agent whisper for self-awareness context after delivery
- `continue_on_error` on all external calls for resilience

## Prerequisites

- Home Assistant
- A TTS entity that supports `tts.speak` (e.g. ElevenLabs)
- A `media_player` entity for TTS output
- **Alexa Devices** integration exposing `alexa_devices.send_text_command`
- `pyscript/agent_dispatcher.py` (agent dispatch)
- `pyscript/tts_queue.py` (TTS queue)
- `pyscript/agent_whisper.py` (whisper context)
- `input_boolean.ai_dispatcher_enabled` (dispatcher toggle)

## Installation

1. Copy `rickyellsplusalexa.yaml` to `config/blueprints/script/madalone/`
2. Create script: **Settings -> Automations & Scenes -> Scripts -> Add -> Use Blueprint**

## Configuration

<details><summary>Dispatcher & Voice Assistant</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `use_dispatcher` | `true` | Use AI dispatcher for dynamic persona selection |
| `conversation_agent` | `Rick` | Assist Pipeline name (used when dispatcher is disabled) |

</details>

<details><summary>TTS Settings</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `tts_output_player` | _(required)_ | Media player where Rick should speak |
| `tts_output_volume` | `0.0` | Volume level (0.0-1.0) before TTS. 0 = use current volume |
| `tts_message` | _(Rick's default rant)_ | The text Rick will shout. Customize per instance |

</details>

<details><summary>Alexa Configuration</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `alexa_delay_after_tts` | `40` | Seconds to wait after TTS before Alexa commands |
| `alexa_device` | _(required)_ | Alexa device (via alexa_devices integration) |
| `alexa_volume_command` | `set volume to 10` | Text command to set Alexa volume |
| `alexa_song_command` | `play Mark on the bus by the Beastie Boys` | Text command to start wake-up music |

</details>

<details><summary>④ Infrastructure</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `dispatcher_enabled` | `input_boolean.ai_dispatcher_enabled` | Boolean that enables the AI agent dispatcher |

</details>

## Technical Notes

- **Mode:** `single`
- The Alexa delay defaults to 40 seconds -- enough for a typical Rick rant to finish before music starts
- All external service calls use `continue_on_error: true` so the sequence completes even if one step fails
- The Alexa device selector is filtered to the `alexa_devices` integration

## Changelog

- **v2.0** -- Full style-guide compliance rewrite: collapsible sections, `action:` syntax, aliases, `continue_on_error`, device selector filter, header image, version tagging
- **v1.0** -- Initial release

## Author

**madalone**

## License

See repository for license details.
