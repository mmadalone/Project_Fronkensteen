![Voice -- Wake Guard TTS Router (Helper Script)](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/voice_wake_guard_tts_router-header.jpeg)

# Voice -- Wake Guard TTS Router (Helper Script)

Routes TTS via the centralized `pyscript.tts_queue_speak` service in announce mode. Called by the wake-up-guard blueprint to avoid duplicating TTS logic across pass 1 and pass 2. The ElevenLabs Custom entity ID is configurable for voice_profile passthrough.

## How It Works

```
Called from wake-up-guard blueprint
(pass 1 or pass 2 TTS step)
                |
                v
  ┌─────────────────────────────────┐
  │ pyscript.tts_queue_speak        │
  │   voice: tts_engine             │
  │   voice_id: tts_voice_profile   │
  │   target_mode: explicit         │
  │   announce: true                │
  │   priority: 1                   │
  │   metadata: {source: wake_guard}│
  └─────────────────────────────────┘
```

## Features

- Single TTS routing point -- eliminates duplicated TTS logic in the parent blueprint
- Routes through `pyscript.tts_queue_speak` in announce mode with priority 1
- Passes `voice_id` (ElevenLabs voice profile) through to the TTS queue
- Configurable ElevenLabs entity ID for voice_profile support
- Parallel mode (max 5) -- supports concurrent TTS requests
- `continue_on_error: true` for resilience

## Prerequisites

- Home Assistant with at least one TTS integration
- Pyscript integration with `tts_queue_speak` service deployed
- ElevenLabs Custom TTS integration (optional -- for voice_profile passthrough)

## Installation

1. Copy `voice_wake_guard_tts_router.yaml` to `config/blueprints/script/madalone/`
2. Create script: **Settings -> Automations & Scenes -> Scripts -> Add -> Use Blueprint**

## Configuration

<details>
<summary><strong>① Configuration</strong></summary>

| Input | Default | Description |
|---|---|---|
| `elevenlabs_entity` | `tts.elevenlabs_custom_tts` | The TTS entity that triggers the voice_profile code path. Change if your custom TTS has a different entity ID. |

</details>

### Runtime Fields (passed by caller)

| Field | Required | Default | Description |
|---|---|---|---|
| `tts_engine` | Yes | -- | TTS entity ID (e.g. `tts.google_en` or `tts.elevenlabs_custom_tts`) |
| `tts_output_player` | Yes | -- | Speaker entity where TTS audio plays |
| `message` | Yes | -- | The wake-up message to speak |
| `tts_voice_profile` | No | `""` | ElevenLabs voice profile; only used when `tts_engine` matches the ElevenLabs entity |

## Technical Notes

- **Mode:** `parallel`, max `5` -- supports concurrent calls from escalating wake-up sequences
- **Version:** 1.0
- Uses `pyscript.tts_queue_speak` with `announce: true` and `target_mode: explicit` -- all TTS goes through the centralized queue
- The `voice_id` field passes the ElevenLabs voice profile through to the TTS queue; empty string when not using ElevenLabs
- Includes `metadata: {source: wake_guard}` for queue tracing
- This is a helper script -- not intended to be called directly by users or LLMs; called internally by the wake-up-guard blueprint

## Changelog

- **v1.0** -- Initial version; extracted TTS routing from wake-up-guard blueprint

## Author

**Madalone + Assistant**

## License

See repository for license details.
