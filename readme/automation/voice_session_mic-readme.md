![Voice Session -- Post-Pipeline Mic Control](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/voice_session_mic-header.jpeg)

# Voice Session -- Post-Pipeline Mic Control (v1.0)

Triggered when `ai_voice_session_pending` is set with a JSON payload. Waits for pipeline TTS to finish, plays media (e.g., music compositions), then opens the mic for user feedback via a continuous conversation loop. One global instance -- routes to the correct satellite via `ai_last_satellite`.

## How It Works

```
┌────────────────────────────────────┐
│  TRIGGER                            │
│  input_text.ai_voice_session_       │
│  pending changes to non-empty       │
│  (JSON payload)                     │
└──────────────┬─────────────────────┘
               │
               ▼
┌────────────────────────────────────┐
│  1. Parse JSON request             │
│  • type (music_feedback, etc.)     │
│  • file, player, agent, volume     │
│  • continuous, continuous_timeout   │
│  Clear pending flag                │
└──────────────┬─────────────────────┘
               │
               ▼
┌────────────────────────────────────┐
│  2. Build extra system prompt      │
│  + feedback question               │
│  (auto-populated for music_        │
│  feedback, or from request)        │
└──────────────┬─────────────────────┘
               │
               ▼
┌────────────────────────────────────┐
│  3. Wait for pipeline TTS          │
│  (pyscript.voice_session_          │
│  wait_audio)                       │
└──────────────┬─────────────────────┘
               │
               ▼
┌────────────────────────────────────┐
│  4. Build media URL                │
│  (composition → /local/ path)      │
└──────────────┬─────────────────────┘
               │
               ▼
┌────────────────────────────────────┐
│  5. Echo guard delay               │
└──────────────┬─────────────────────┘
               │
        ┌──────┴──────┐
        │             │
        ▼             ▼
 ┌────────────┐ ┌────────────┐
 │ Continuous  │ │ Single     │
 │ conversation│ │ mic open   │
 │ loop        │ │            │
 │ (voice_     │ │ (voice_    │
 │ session_    │ │ session_   │
 │ continuous) │ │ open_mic)  │
 └────────────┘ └────────────┘
```

## Features

- JSON-driven session requests via `input_text.ai_voice_session_pending`
- Automatic music feedback flow: builds ESP with composition context, sets feedback question, includes promote/delete/revise instructions
- Continuous conversation loop with configurable timeout and no-speech limit
- Single mic open mode for one-shot feedback
- Waits for pipeline TTS to finish before opening mic (prevents echo)
- Composition media playback via satellite before feedback loop
- Echo guard delay between audio playback and mic open
- Routes to last-active satellite automatically (no per-satellite instances needed)

## Prerequisites

- Home Assistant 2024.10.0+
- Pyscript modules: `voice_session` (`voice_session_wait_audio`, `voice_session_continuous`, `voice_session_open_mic`)
- `input_text.ai_voice_session_pending` (trigger flag, JSON payload)
- `input_text.ai_last_satellite` (satellite routing)
- `input_boolean.ai_ducking_flag` (ducking state)
- `input_boolean.ai_duck_guard_enabled` (duck guard)

## Installation

1. Copy `voice_session_mic.yaml` to `config/blueprints/automation/madalone/`
2. Create automation: **Settings -> Automations -> Create -> Use Blueprint**
3. One global instance is sufficient

## Configuration

<details><summary>① Configuration</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `silence_media` | `http://homeassistant.local:8123/local/silence.wav` | Audio file URL for silent mic open |
| `echo_guard_seconds` | `0.5` | Wait seconds after audio before opening mic |
| `feedback_question` | _(empty)_ | Text spoken before opening mic on first turn. Empty = auto-populated for music_feedback sessions |
| `default_continuous_timeout` | `120` | Default timeout in seconds for continuous loop if not specified in request |

</details>

<details><summary>② Infrastructure</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `ducking_flag` | `input_boolean.ai_ducking_flag` | Ducking flag entity |
| `duck_guard_enabled` | `input_boolean.ai_duck_guard_enabled` | Duck guard enabled entity |
| `session_pending_entity` | `input_text.ai_voice_session_pending` | The input_text that triggers a voice session when set |
| `last_satellite_entity` | `input_text.ai_last_satellite` | Helper that stores the last-active satellite entity_id |

</details>

### JSON Payload Format

The trigger entity expects a JSON string with these fields:

| Field | Default | Description |
|-------|---------|-------------|
| `type` | `music_feedback` | Session type |
| `file` | _(empty)_ | Media file path (e.g., composition file) |
| `player` | _(empty)_ | Target media player |
| `agent` | _(empty)_ | Agent identifier |
| `volume` | `0.5` | Playback volume |
| `continuous` | `true` | Enable continuous conversation loop |
| `continuous_timeout` | _(from input)_ | Timeout for continuous loop |
| `extra_system_prompt` | _(empty)_ | Custom ESP for non-music sessions |

## Technical Notes

- **Mode:** `queued` / `max: 3` -- supports multiple queued session requests
- **Trigger:** State change on `input_text.ai_voice_session_pending` to non-empty value (minimum 2 characters)
- **Music feedback ESP:** Auto-generated with composition context, including instructions for `compose_music` (revise), `music_library` with `action: "promote"` (keep), or `action: "delete"` (discard)
- **Media URL construction:** Converts `/config/www/` paths to `/local/` URLs using the HA base URL derived from the silence media input
- **Satellite routing:** Reads `input_text.ai_last_satellite` at trigger time -- no per-satellite instances needed
- **Flag clearing:** Pending flag is cleared immediately after parsing to prevent re-triggers
- **All pyscript actions** use `continue_on_error: true`

## Author

**madalone**

## License

See [LICENSE](../../LICENSE) in the repository root.
