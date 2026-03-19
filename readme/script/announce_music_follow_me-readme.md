# Announce Music Follow Me -- TTS (v2.0)

![Announce Music Follow Me](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/announce-music-follow-me-header.jpeg)

Script blueprint that announces via TTS where the music was moved for the "Music Assistant -- Follow Me" automation. A simpler alternative to the LLM variant -- supports static default messages and random message pools with fun Rick/Quark-style personality. Works with any TTS engine and includes optional volume control.

## How It Works

```
START (called with target_player)
  |
  v
<Dispatcher enabled?>--YES-->[agent_dispatch]
  |                              |
  NO                             v
  |                     [Set voice/persona]
  v                              |
[Resolve pipeline]               |
  |<-----------------------------+
  v
<Random mode?>
  |       |
 YES      NO
  |       |
  v       v
[Pick from       [Use default
 custom pool      message]
 or fallback]     |
  |               |
  +-------+-------+
          |
          v
[Replace {player_name} / {target_player}]
          |
          v
[TTS queue speak to target player]
          |
          v
[Post-interaction whisper]
          |
          v
END
```

## Features

- Random fun message pool with Rick/Quark-style defaults
- Editable message list with `{player_name}` and `{target_player}` placeholders
- Optional TTS output volume control (0.0-1.0)
- Built-in fallback message pool if custom list is cleared
- AI dispatcher integration for dynamic persona selection
- TTS delivery via pyscript TTS queue (priority 4)

## Prerequisites

- Home Assistant **2024.6.0** or newer
- `pyscript.agent_dispatch` service (agent dispatcher)
- `pyscript.tts_queue_speak` service (TTS queue)
- `pyscript.agent_whisper` service (agent whisper)

## Installation

1. Copy `announce_music_follow_me.yaml` to `config/blueprints/script/madalone/`
2. Create script: **Settings > Automations & Scenes > Scripts > Add > Use Blueprint**

## Configuration

<details>
<summary><strong>Dispatcher & Voice Assistant</strong></summary>

| Input | Default | Description |
|---|---|---|
| `use_dispatcher` | `true` | AI dispatcher selects persona dynamically |
| `conversation_agent` | `Rick` | Assist Pipeline used when dispatcher is disabled |
| `tts_output_volume` | `0.0` | Volume level (0.0-1.0); 0 = use current volume |

</details>

<details>
<summary><strong>Message Settings</strong></summary>

| Input | Default | Description |
|---|---|---|
| `use_random_messages` | `true` | Pick a random message from the list |
| `custom_random_messages` | 5 Rick/Quark messages | YAML list of message templates |
| `default_message` | `Moving the music to {player_name}.` | Static fallback message |

</details>

<details>
<summary><strong>Infrastructure</strong></summary>

| Input | Default | Description |
|---|---|---|
| `dispatcher_enabled` | `input_boolean.ai_dispatcher_enabled` | Dispatcher toggle entity |

</details>

### Script Fields (passed at call time)

| Field | Required | Description |
|---|---|---|
| `target_player` | Yes | Media player where music was moved |

## Technical Notes

- **Mode:** `queued` / `max_exceeded: silent`
- **Error handling:** `continue_on_error: true` on all external service calls
- **Fallback messages:** If `custom_random_messages` is cleared, a built-in 5-message pool is used
- **Volume:** Passed to TTS queue; only applied when > 0

## Changelog

- **v2.0:** Full style-guide compliance: collapsible sections, `action:` syntax, aliases, `continue_on_error`, template safety, DRY fallback, header image
- **v1.0:** Initial release

## Author

**madalone**

## License

See repository for license details.
