# Voice -- Wake Guard TTS Router (Helper Script)

Routes TTS between ElevenLabs Custom (with `voice_profile` option) and standard `tts.speak`. Called by the wake-up-guard blueprint to avoid duplicating TTS routing logic across pass 1 and pass 2. The ElevenLabs Custom entity ID is configurable, so it also works with other custom TTS integrations that support `voice_profile` options.

## How It Works

```
Called from wake-up-guard blueprint
(pass 1 or pass 2 TTS step)
                |
                v
  ┌─────────────────────────────────┐
  │ Is tts_engine == ElevenLabs?    │
  └──────────┬──────────────────────┘
         YES |              NO
             v               v
  ┌──────────────────┐  ┌──────────────────┐
  │ tts.speak with   │  │ tts.speak        │
  │ options:         │  │ (standard, no    │
  │   voice_profile  │  │  extra options)  │
  └──────────────────┘  └──────────────────┘
```

## Features

- Single TTS routing point -- eliminates duplicated choose blocks in the parent blueprint
- ElevenLabs Custom support with `voice_profile` option passthrough
- Standard TTS fallback for all other engines (HA Cloud, Google, etc.)
- Configurable ElevenLabs entity ID -- works with any TTS integration that uses `voice_profile`
- Parallel mode (max 5) -- supports concurrent TTS requests

## Prerequisites

- Home Assistant with at least one TTS integration
- ElevenLabs Custom TTS integration (optional -- falls back to standard `tts.speak` for other engines)

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
- Routing is based on exact entity ID match (`tts_engine == elevenlabs_entity`), not integration detection
- The `voice_profile` option is silently ignored if the TTS engine doesn't support it, but routing avoids sending it to non-ElevenLabs engines regardless
- This is a helper script -- not intended to be called directly by users or LLMs; called internally by the wake-up-guard blueprint

## Changelog

- **v1.0** -- Initial version; extracted TTS routing from wake-up-guard blueprint

## Author

**Madalone + Assistant**

## License

See repository for license details.
