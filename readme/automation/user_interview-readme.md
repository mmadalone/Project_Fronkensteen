![AI User Interview](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/user_interview-header.jpeg)

# AI User Interview

Manages the LLM-driven user preference interview. Activates interview mode (hot context injection), runs a continuous conversation loop so the agent keeps asking questions, and auto-deactivates after timeout. The actual interview is conducted by the LLM agent using hot context guidance and the `save_user_preference` tool function.

## How It Works

```
┌─────────────────────────────┐
│ Triggers:                   │
│  A. Interview toggle → ON   │
│  B. Interview toggle → OFF  │
│  C. HA start (auto-import)  │
└──────────────┬──────────────┘
               │
     ┌────┴─────┬──────────┐
     ▼          ▼          ▼
┌────────┐ ┌─────────┐ ┌──────────┐
│ START  │ │ STOP    │ │ HA START │
└───┬────┘ │•Deactiv.│ │•Auto-    │
    │      │ contin. │ │ import   │
    │      │•Restore │ │ interview│
    │      │ toggles │ │ files    │
    │      │•Exit    │ │•Exit     │
    │      └─────────┘ └──────────┘
         ▼
┌─────────────────────────────┐
│ 0. Suppress notification    │
│    toggles (optional)       │
│ 0b. Pre-seed progress from  │
│     existing L1/L2 data     │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│ 1a. Speak opening question  │
│     via TTS queue            │
│ 1b-1c. Wait for playback   │
│ 1d. Echo guard (2s)        │
│ 1e. Open mic silently      │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│ 2. Activate continuous      │
│    conversation flag        │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│ 4. Continuous loop:         │
│    while(deadline not       │
│    reached, no-speech < 3,  │
│    toggle ON, continuous ON)│
│                             │
│    A0. Wait satellite active│
│    A. Wait satellite idle   │
│    B. No-speech detection   │
│    C. Exit check            │
│    D-E. Echo guard + wait   │
│    G. Build progress context│
│    H. Reopen mic with       │
│       extra_system_prompt   │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│ 5. Deactivate continuous    │
│ 6. Auto-turn off interview  │
│    mode if still on         │
└─────────────────────────────┘
```

## Features

- **Continuous conversation loop** -- keeps the mic cycling (same pattern as `voice_handoff.yaml`) so the agent asks multiple questions without wake word
- **Auto-timeout** -- automatically deactivates after a configurable number of minutes
- **No-speech detection** -- exits after 3 consecutive short sessions (< 12 seconds), indicating the user walked away
- **Progress tracking** -- reads `input_text.ai_interview_progress` and injects "already asked" context into `extra_system_prompt` to avoid repeating questions
- **Pre-seed from existing data** -- calls `pyscript.user_interview_preseed` to load known preferences before starting
- **Toggle suppression** -- temporarily disables notification/follow-me toggles during the interview, restores on exit
- **TTS opening question** -- speaks the first question via TTS queue in the correct agent voice
- **Echo guard** -- delays mic open after TTS to prevent the agent from hearing its own speech
- **Auto-import on startup** -- on HA start, scans `/config/interview/` for `interview_*.yaml` files and imports any matching a configured person (toggleable via `auto_import_on_startup`)

## Prerequisites

- Home Assistant 2024.10.0 or later
- An `assist_satellite` entity
- A `media_player` entity for the satellite's speaker
- A TTS entity for the agent's voice
- `input_boolean.ai_interview_mode` (or custom toggle)
- `input_boolean.ai_continuous_conversation_active`
- `input_text.ai_interview_progress` for progress tracking
- `pyscript.user_interview_preseed`, `pyscript.user_interview_auto_import`, and `pyscript.tts_queue_speak` services
- A silence media file accessible via URL

## Installation

1. Copy `user_interview.yaml` to `config/blueprints/automation/madalone/`
2. Create automation: **Settings → Automations → Create → Use Blueprint**

## Configuration

### ① Core

| Input | Default | Description |
|-------|---------|-------------|
| **Enable** | `true` | Kill switch for this automation instance |
| **Interview mode toggle** | `input_boolean.ai_interview_mode` | Input boolean that activates/deactivates interview mode |
| **Satellite** | (required) | The `assist_satellite` entity to run the interview on |
| **Speaker** | (required) | The `media_player` entity for the satellite speaker |
| **Interview target user** | `""` | Person entity for the interview target; empty = auto-detect from occupancy |
| **Use AI dispatcher for voice** | `true` | Resolve TTS voice via dispatcher; when off, uses TTS voice entity directly |

### ② Configuration

| Input | Default | Description |
|-------|---------|-------------|
| **Auto-timeout (minutes)** | `30` | Automatically deactivate after this many minutes (5--120) |
| **Interview language** | `"English"` | Language for the interview (English, Spanish, Valencian, Dutch, Portuguese) |
| **Start message** | `"Alright, time to get to know you..."` | Opening line spoken when the interview begins |
| **TTS voice entity** | `""` | TTS entity for the agent's voice (e.g., `tts.elevenlabs_rick_text_to_speech`) |
| **Suppress during interview** | `[]` | Input booleans to turn OFF during interview; restored to ON when done |
| **Interview system prompt** | *(built-in)* | LLM guidance injected via `extra_system_prompt` on every mic reopen |
| **Progress prompt template** | *(built-in)* | Template for "already asked" context; `{done_list}` placeholder |
| **Voice mood during interview** | `true` | When OFF, disables voice mood modulation for neutral tone |
| **Interview style** | `"casual"` | Tone: casual, formal, playful, or brief |
| **Question depth** | `"standard"` | How deeply the agent probes: surface, standard, or deep |
| **Interviewer context template** | *(built-in)* | Template with `{user}` and `{language}` placeholders |
| **Empty progress prompt** | `"No preferences saved yet..."` | Message when no progress exists |

### ③ Infrastructure

| Input | Default | Description |
|-------|---------|-------------|
| **Silence media URL** | `http://homeassistant.local:8123/local/silence.wav` | URL to a short silence clip for reopening mic without speaking |
| **Use HA Cloud TTS** | `false` | Use Home Assistant Cloud TTS instead of ElevenLabs to save API credits |
| **Budget floor (%)** | `30` | Minimum budget remaining % to start/continue the interview |
| **Bypass follow-me** | `false` | Pause notification follow-me during interview |
| **Auto-import on startup** | `true` | Scan `/config/interview/` on HA start for `interview_{user}.yaml` files and import matching persons |
| **Continuous conversation entity** | `input_boolean.ai_continuous_conversation_active` | Boolean controlling the conversation loop |
| **Follow-me notification entity** | `input_boolean.ai_notification_follow_me` | Boolean controlling follow-me notifications |
| **Voice mood entity** | `input_boolean.ai_voice_mood_enabled` | Boolean controlling voice mood modulation |
| **Interview progress entity** | `input_text.ai_interview_progress` | input_text storing interview progress JSON |

### ④ Privacy

| Input | Default | Description |
|-------|---------|-------------|
| **Privacy tier** | `"off"` | Privacy gate tier (off / t1 / t2 / t3) |
| **Privacy gate person** | `""` | Person entity for privacy resolution |

### ⑤ Topics

| Input | Default | Description |
|-------|---------|-------------|
| **Interview categories** | `"identity, household, work, schedule, health, environment, media, communication, privacy"` | Comma-separated built-in categories; remove any to skip |
| **Custom topics** | `""` | Additional topics in `category_name: key1, key2` format (one per line) |

## Technical Notes

- `mode: restart` with `max_exceeded: silent` -- toggling interview mode OFF kills the running loop cleanly.
- The continuous loop uses four exit conditions: deadline reached, 3 consecutive no-speech events, toggle turned OFF, or continuous flag cleared.
- No-speech detection counts sessions shorter than 12 seconds as "no speech" -- resets to 0 on any session longer than 12 seconds.
- `extra_system_prompt` on `assist_satellite.start_conversation` injects the progress context into the agent's system prompt for each turn.
- The progress context parses `input_text.ai_interview_progress` as JSON and formats it as "ALREADY ASKED (do NOT repeat these): category.key, ..." to prevent the agent from re-asking answered questions.
- `continue_on_error: true` on TTS, toggle suppression, and mic-open steps ensures the interview continues even if individual steps fail.
- The pre-seed step calls `pyscript.user_interview_preseed` with `user: "miquel"` to populate progress from existing L1/L2 data.

## Changelog

- **v2 (2026-03-26):** Added `ha_start` trigger + `auto_import_on_startup` input for automatic interview file import on HA restart. Added budget gate, privacy gate, dispatcher toggle, user resolution, follow-me bypass, voice mood toggle, configurable prompts, tool suppression, exchange logging, interview style/depth, custom topics.
- **v1:** Initial blueprint

## Author

**madalone**

## License

See repository for license details.
