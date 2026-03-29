![Bedtime Routine Core](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/bedtime_routine_core-header.jpeg)

# Bedtime Routine – Core Sequence

Complete bedtime shutdown sequence as a reusable script blueprint. Handles TV shutdown (3-method stack), lights off, media playback (Music Assistant audiobook or Kodi), countdown timer, bathroom guard with timeout, settling-in and goodnight TTS via LLM, and memory integration.

## How It Works

```
┌─────────────────────────────────────────┐
│  1. Set bedtime_active ON               │
│  2. Resolve agent (dispatcher/manual)   │
│  3. Speaker reset (power-cycle)         │
└──────────────┬──────────────────────────┘
               │
┌──────────────▼──────────────────────────┐
│  4. TV shutdown stack                    │
│     CEC/software → custom script → IR   │
│  5. Lights off (except holdback lamp)   │
│  6. Stop extra media players            │
└──────────────┬──────────────────────────┘
               │
┌──────────────▼──────────────────────────┐
│  7. Media playback                       │
│     ┌─ audiobook (Music Assistant)       │
│     ├─ kodi (PVR/content)               │
│     └─ none (skip)                       │
│  8. Settling-in TTS (if enabled)        │
└──────────────┬──────────────────────────┘
               │
┌──────────────▼──────────────────────────┐
│  9. Countdown timer                      │
│     (field override > helper > default) │
│ 10. Bathroom guard                       │
│     AP-20: check if already clear       │
│     AP-04: wait with timeout            │
│     + grace period                       │
│ 11. Holdback lamp off                   │
└──────────────┬──────────────────────────┘
               │
┌──────────────▼──────────────────────────┐
│ 12. Goodnight TTS (LLM + sensors)       │
│ 13. Memory write (bedtime.actual)       │
│ 14. Agent whisper (log completion)      │
│ 15. Cleanup: bedtime_active OFF         │
└─────────────────────────────────────────┘
```

## Key Design Decisions

### 3-method TV shutdown stack
Tries CEC/software first, then a custom power-off script, then IR remote — each with `continue_on_error: true`. Only configured methods execute. Handles TVs that don't respond consistently to one method.

### Preset-only media for v1.0
Starts with preset URIs for audiobook and Kodi. Conversational selection (curated/freeform) is deferred to a future version to keep v1.0 simple and reliable.

### Countdown with 3-tier override
Runtime field override > helper entity value > blueprint default. Allows the calling automation to pass a countdown, or the user to change it via the dashboard helper, with a sensible fallback.

### Bathroom guard with AP-20 + AP-04
Checks if the bathroom is already clear before starting the wait (AP-20 idempotent). Wait has a max timeout + `continue_on_timeout: true` (AP-04). Grace period after clear lets the user settle back in bed.

## Features

- TV shutdown: CEC/software, custom script, IR remote (3-method stack)
- Lights off with holdback lamp (turns off after bathroom guard)
- Music Assistant audiobook playback (preset URI)
- Kodi playback (PVR channel, directory, video)
- Settling-in TTS: contextual LLM message after media starts
- Goodnight TTS: LLM message with sensor context injection
- Countdown timer with 3-tier override
- Bathroom guard with timeout + grace period
- Speaker power-cycle before TTS
- Memory integration (bedtime.actual timestamp)
- Agent whisper logging
- Test mode (TTS + logbook only, skip device actions)
- Runtime fields: countdown_override, skip_bathroom_guard, skip_media

## Prerequisites

- Home Assistant 2024.10.0+
- Pyscript modules: `agent_dispatcher`, `tts_queue`, `conversation_with_timeout`, `memory`, `agent_whisper`
- Music Assistant (if using audiobook mode)
- Kodi (if using Kodi mode)

## Installation

1. Copy `bedtime_routine_core.yaml` to `config/blueprints/script/madalone/`
2. Reload scripts in Developer Tools → YAML
3. Create instance via Settings → Automations & Scenes → Scripts → Add → Create from Blueprint
4. Or add to `scripts.yaml` directly (see example below)

### scripts.yaml example

```yaml
bedtime_routine_core:
  use_blueprint:
    path: madalone/bedtime_routine_core.yaml
    input:
      tv_entity: media_player.madteevee
      tv_ir_remote: remote.remote_control
      tv_ir_command: Power
      tv_ir_device: TV
      lights_off_target:
        entity_id:
          - light.workshop_main
      living_room_lamp: switch.living_room_none
      bathroom_sensor: binary_sensor.fp2_presence_sensor_bathroom
      conversation_agent: Rick - Bedtime
      use_dispatcher: true
      tts_speaker: media_player.home_assistant_voice_workshop_media_player_esp
      media_target: kodi
      kodi_entity: media_player.madteevee
  alias: Bedtime Routine Core
  description: Complete bedtime shutdown sequence
```

## Configuration

### ① Devices

| Input | Type | Default | Description |
|---|---|---|---|
| `tv_entity` | media_player | — | TV (CEC/software shutdown) |
| `tv_off_script` | script | — | Custom TV power-off script |
| `tv_ir_remote` | remote | — | IR remote entity |
| `tv_ir_command` | text | — | IR command (e.g., Power) |
| `tv_ir_device` | text | — | IR device name |
| `lights_off_target` | target | — | Lights/switches to turn off |
| `living_room_lamp` | entity | — | Holdback lamp |
| `media_players_stop` | entity[] | [] | Extra players to stop |
| `reset_switches` | entity[] | [] | Speaker reset switches |
| `reset_switch_delay` | duration | 2s | Delay between power-cycle on and off |

### ② Media Playback

| Input | Type | Default | Description |
|---|---|---|---|
| `media_target` | select | none | audiobook / kodi / none |
| `audiobook_player` | media_player | — | MA player |
| `audiobook_preset_uri` | text | — | MA media ID |
| `audiobook_volume` | number | 0.25 | Audiobook volume |
| `audiobook_media_type` | select | audiobook | MA content type (auto/audiobook/album/playlist/track) |
| `kodi_entity` | media_player | — | Kodi player |
| `kodi_preset_content` | text | — | Kodi content ID |
| `kodi_content_type` | select | CHANNEL | Content type |
| `kodi_volume` | number | 0.15 | Kodi volume |
| `skip_tv_off` | boolean | false | Keep TV on (Kodi mode) |

### ③ Countdown & Bathroom

| Input | Type | Default | Description |
|---|---|---|---|
| `default_countdown_minutes` | number (1–30) | 4 | Default countdown |
| `countdown_helper` | input_number | — | Override helper |
| `bathroom_sensor` | binary_sensor | — | Bathroom presence |
| `bathroom_max_timeout` | duration | 15 min | Max wait |
| `bathroom_grace_period` | duration | 1m 30s | Grace after clear |

### ④ TTS & Conversation

| Input | Type | Default | Description |
|---|---|---|---|
| `conversation_agent` | text | — | Pipeline name or conversation agent entity |
| `use_dispatcher` | boolean | true | Resolve agent via pyscript.agent_dispatch |
| `tts_speaker` | media_player | — | Media player for voice announcements |
| `goodnight_prompt` | text | _(brief warm goodnight)_ | LLM prompt for final goodnight message |
| `enable_settling_tts` | boolean | false | Play contextual message after media starts |
| `settling_prompt` | text | _(settling-in prompt)_ | LLM prompt for settling message |
| `settling_sensors` | entity[] | [] | Entity states injected into TTS prompts |

### ⑤ State & Control

| Input | Type | Default | Description |
|---|---|---|---|
| `bedtime_active_entity` | input_boolean | `input_boolean.ai_bedtime_active` | Signals routine is running (suppresses naggers) |
| `test_mode` | boolean | false | Skip device actions; only run TTS + logbook |
| `enable_memory` | boolean | true | Store bedtime timestamp via pyscript.memory_set |
| `post_tts_delay` | number | 3 | Pause after each TTS to let audio finish (0-15s) |

### Runtime Fields

| Field | Type | Description |
|---|---|---|
| `countdown_override` | number | Override countdown (0 = use default) |
| `skip_bathroom_guard` | boolean | Skip bathroom wait |
| `skip_media` | boolean | Skip media playback |

## Technical Notes

- `mode: single` / `max_exceeded: silent`
- All device actions use `continue_on_error: true` — sequence always runs to completion
- `bedtime_active` set ON at step 1, OFF at step 15 (AP-06 cleanup guarantee)
- Test mode: only TTS + logbook, no device actions, countdown = 10s
- Agent resolution: dispatcher → manual. Dispatcher returns agent_id + tts_engine + persona
- LLM calls via `pyscript.conversation_with_timeout` with 60s timeout
- TTS via `pyscript.tts_queue_speak` with priority 2

## Changelog

- **v1:** Initial version — preset media only, fixed countdown, full device stack

## Author

madalone

## License

MIT
