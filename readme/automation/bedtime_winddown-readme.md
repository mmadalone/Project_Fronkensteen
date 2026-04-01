![Bedtime Wind-Down](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/bedtime_winddown-header.jpeg)

# Bedtime Wind-Down

Context-aware bedtime detection + conversational offers + multi-stage escalation. Detects 4 scenarios based on bed presence and TV state, makes personalised LLM offers via Assist Satellite, tracks escalation stages with configurable cooldown curves, and at the final stage runs the bedtime routine autonomously.

## How It Works

```
┌─────────────────────┐     ┌───────────────────────┐
│  Bed presence ON     │     │  Sleepy TV detected    │
│  (settle timer)      │     │  (PVR/title/content)   │
└────────┬────────────┘     └───────────┬───────────┘
         │                              │
         ▼                              ▼
┌─────────────────────────────────────────────────────┐
│                 Scenario Classification              │
│  sleepy_tv │ bed_tv │ bed_idle │ bed_non_sleepy     │
└──────────────────────┬──────────────────────────────┘
                       │
         ┌─────────────▼─────────────┐
         │  Guards: kill switch,      │
         │  time window, day, privacy,│
         │  cooldown, bedtime_active  │
         └─────────────┬─────────────┘
                       │
              ┌────────▼────────┐
              │  Stage Manager   │
              │  (session resume │
              │   or reset)      │
              └────────┬────────┘
                       │
            ┌──────────▼──────────┐
     NO     │   Final stage?      │  YES
   ┌────────┤                     ├────────┐
   │        └─────────────────────┘        │
   ▼                                       ▼
┌──────────────┐              ┌──────────────────────┐
│  LLM offer   │              │  Autonomous TTS       │
│  via Assist  │              │  → run routine_core   │
│  Satellite   │              │  → notify (optional)  │
└──────┬───────┘              └──────────────────────┘
       │
       ▼
  Advance stage
  + memory write
  + whisper
```

## Key Design Decisions

### Separate detection from execution
The wind-down blueprint handles **when** and **how** to offer bedtime — it doesn't execute the routine itself. That's delegated to `bedtime_routine_core.yaml`, keeping both blueprints focused and independently testable.

### Budget gate with static fallback
When the LLM budget drops below a configurable floor, offers switch to a static TTS message instead of an LLM call. Escalation and stage management continue normally — only the offer delivery changes.

### Cross-midnight time windows
The schedule supports windows that span midnight (e.g., 20:30–02:00) using proper time comparison logic that handles the wraparound.

### Absence gap tolerance
If the user leaves bed briefly (e.g., bathroom) and returns within the configured gap, the session resumes at the current stage instead of resetting. Prevents escalation restart on brief absences.

## Features

- 4 scenario detection: sleepy TV, bed+TV, bed+idle, bed+non-sleepy content
- 4 sleepy TV detection methods: media title, content ID, playing+title, PVR channel
- Multi-stage escalation (2–8 stages) with per-stage prompt overlays
- 3 cooldown curves: fixed, accelerating (halves each stage), custom per-stage
- Autonomous execution at final stage (runs routine without consent)
- Budget gate with static fallback when LLM budget is low
- Weekend overrides (same/disabled/profile with separate schedule)
- Memory integration (stores offer history, injects into LLM context)
- Privacy gate (3-tier suppression)
- Repeat offers via 5-minute time pattern tick
- Kill switch + bedtime_active mutual exclusion
- Test mode with compressed cooldowns

## Prerequisites

- Home Assistant 2024.10.0+
- `bedtime_routine_core.yaml` script blueprint (for the routine execution)
- Pyscript modules: `agent_dispatcher`, `tts_queue`, `conversation_with_timeout`, `memory`, `agent_whisper`
- Assist Satellite entity (ESP32 Voice PE or similar)
- Bed presence sensor (binary_sensor)
- 8 helper entities (see Configuration)

## Installation

1. Copy `bedtime_winddown.yaml` to `config/blueprints/automation/madalone/`
2. Create the 8 helper entities (see below)
3. Reload automations in Developer Tools → YAML
4. Create an instance via Settings → Automations → Add → Create from Blueprint

## Configuration

### ① Triggers & Detection

| Input | Type | Default | Description |
|---|---|---|---|
| `bed_presence_sensor` | binary_sensor | — | Bed occupancy sensor |
| `bed_settle_minutes` | number (1–30) | 3 | Settle time before trigger |
| `tv_media_player` | media_player | — | TV entity for sleepy detection |
| `sleepytv_detection_method` | select | pvr_channel_matches | Detection algorithm |
| `sleepytv_match_string` | text | — | Match string (case-insensitive) |
| `sleepytv_pvr_sensor` | sensor | sensor.madteevee_pvr_channel | PVR channel sensor |
| `min_presence_seconds` | number (0–600) | 0 | Extra debounce |
| `block_if_media_playing` | boolean | false | Suppress during playback |

### ② Schedule & Timing

| Input | Type | Default | Description |
|---|---|---|---|
| `enable_toggle` | input_boolean | ai_winddown_enabled | Kill switch |
| `notification_master_gate` | input_boolean | ai_notifications_master_enabled | Global notification gate |
| `time_window_start` | time | 20:30 | Window start |
| `time_window_end` | time | 02:00 | Window end (cross-midnight OK) |
| `run_days` | multi-select | all | Active days |
| `cooldown_minutes` | number (1–240) | 30 | Base cooldown between offers |
| `repeat_while_present` | boolean | true | Keep offering while in bed |
| `max_offers_per_session` | number | 0 (unlimited) | Cap per session |
| `bedtime_active_entity` | input_boolean | ai_bedtime_active | Routine mutex |
| `winddown_active_flag` | input_boolean | ai_winddown_active | In-progress flag |

### ③ AI Conversation

| Input | Type | Default | Description |
|---|---|---|---|
| `conversation_agent` | text | Rick - Bedtime | Pipeline name or agent entity |
| `use_dispatcher` | boolean | true | Use dispatcher for persona selection |
| `assist_satellites` | entity | _(empty)_ | Satellite entity for start_conversation offers |
| `user_names` | text | Miquel | User name(s) for LLM personalisation (comma-separated) |
| `llm_prompt` | text | _(default)_ | Base offer prompt for bedtime offers |
| `context_entities` | entity | `[]` | Entity states appended to LLM prompt |
| `budget_floor` | number (0–100) | 60 | Below this budget %, use static fallback |
| `fallback_offer_text` | text | _(default)_ | Static fallback when LLM budget is below floor |

### ④ Escalation Settings

| Input | Type | Default | Description |
|---|---|---|---|
| `enable_escalation` | boolean | true | Multi-stage escalation |
| `escalation_stage_count` | number (2–8) | 4 | Number of stages |
| `escalation_stage_helper` | input_number | ai_winddown_stage | Stage counter helper |
| `escalation_session_helper` | input_datetime | ai_winddown_session_start | Session start timestamp |
| `cooldown_curve` | select | accelerating | fixed / accelerating / custom |
| `custom_stage_intervals` | text | 30,20,15,10 | Per-stage minutes |
| `absence_gap_minutes` | number (0–120) | 15 | Resume window |
| `no_response_behavior` | select | advance | advance / reset on decline |
| `offer_start_stage` | number (1–8) | 1 | Don't offer until this stage is reached |
| `stage_1..6_prompt_overlay` | text | (see defaults) | Per-stage LLM tone |
| `autonomous_execution_prompt` | text | (dramatic) | Final stage TTS |

### ⑤ Offer Flow

| Input | Type | Default | Description |
|---|---|---|---|
| `offer_timeout_seconds` | number (10–120) | 30 | How long to wait for a response on the satellite |
| `offer_prompt_sleepy_tv` | text | _(default)_ | Scenario prompt for sleepy TV |
| `offer_prompt_bed_tv` | text | _(default)_ | Scenario prompt for bed + TV playing |
| `offer_prompt_bed_idle` | text | _(default)_ | Scenario prompt for bed + idle |
| `offer_prompt_bed_non_sleepy` | text | _(default)_ | Scenario prompt for bed + non-sleepy content |

### ⑥ Wind-Down Actions

| Input | Type | Default | Description |
|---|---|---|---|
| `routine_script` | entity | _(empty)_ | Bedtime routine script entity |
| `run_routine_on_accept` | boolean | true | Run routine script when user accepts |

### ⑦ Autonomous Execution

| Input | Type | Default | Description |
|---|---|---|---|
| `notify_on_autonomous` | boolean | false | Notify on autonomous execution |
| `notify_entity` | text | _(empty)_ | notify.* entity for alerts |
| `notify_message` | text | _(default)_ | Notification message |

### ⑧ Test Mode

| Input | Type | Default | Description |
|---|---|---|---|
| `enable_test_mode` | boolean | false | Compressed cooldowns, skip device actions |
| `test_mode_cooldown_seconds` | number (10–300) | 60 | Test mode cooldown |

### ⑨ Weekend Overrides

| Input | Type | Default | Description |
|---|---|---|---|
| `weekend_mode` | select | same | same / disabled / profile |
| `weekend_days` | multi-select | sat, sun | Which days count as weekend |
| `weekend_time_start` | time | 22:00 | Weekend window start |
| `weekend_time_end` | time | 03:00 | Weekend window end |
| `weekend_cooldown_minutes` | number (1–240) | 45 | Weekend cooldown |
| `weekend_llm_prompt_override` | text | _(empty)_ | Weekend LLM prompt override |

### ⑩ Memory & History

| Input | Type | Default | Description |
|---|---|---|---|
| `enable_memory` | boolean | true | Enable memory integration |
| `memory_store_key` | text | winddown.offer | Memory store key |
| `memory_scope` | select | household | household / user |
| `memory_expiration_days` | number (0–365) | 90 | Memory expiration |
| `memory_history_inject_prompt` | text | _(default)_ | Prepended to recent bedtime memory results |

### ⑪ Privacy & Infrastructure

| Input | Type | Default | Description |
|---|---|---|---|
| `privacy_tier` | select | t1 | Privacy tier (off/t1/t2/t3) |
| `privacy_gate_enabled` | input_boolean | ai_privacy_gate_enabled | Privacy gate toggle |
| `privacy_gate_mode` | input_select | ai_privacy_gate_mode | Privacy gate mode |
| `privacy_gate_person` | entity | person.miquel | Person entity for suppression lookups |
| `ducking_flag` | input_boolean | ai_ducking_flag | Ducking flag |
| `bypass_ducking` | boolean | false | Skip volume ducking on other speakers during TTS |

### Helper Entities

| Helper | Type | Purpose |
|---|---|---|
| `input_boolean.ai_winddown_enabled` | boolean | Kill switch |
| `input_boolean.ai_winddown_active` | boolean | In-progress flag |
| `input_datetime.ai_winddown_last_offer` | datetime | Cooldown tracking |
| `input_datetime.ai_winddown_session_start` | datetime | Session timestamp |
| `input_select.ai_privacy_gate_bedtime_winddown` | select | Privacy override |
| `input_select.ai_winddown_last_scenario` | select | Debug/dashboard |
| `input_number.ai_winddown_cooldown_minutes` | number | Cooldown config |
| `input_number.ai_winddown_stage` | number | Escalation stage (0–8) |

## Technical Notes

- `mode: single` / `max_exceeded: silent` — only one execution at a time
- All device/service actions use `continue_on_error: true`
- `bedtime_active` ON from routine core auto-suppresses proactive unified naggers
- 5-minute time pattern tick drives repeat offers (same pattern as escalation blueprint)
- Escalation prompt overlays auto-fill gaps with a 4-band curve (casual → frustrated → blunt → final)
- Cross-midnight day attribution: hours before 06:00 count as previous day

## Changelog

- **v1:** Initial version — 4 scenarios, multi-stage escalation, budget gate, memory integration

## Author

madalone

## License

MIT
