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
| `sleepytv_pvr_sensor` | sensor | — | PVR channel sensor |
| `min_presence_seconds` | number (0–600) | 0 | Extra debounce |
| `block_if_media_playing` | boolean | false | Suppress during playback |

### ② Schedule & Timing

| Input | Type | Default | Description |
|---|---|---|---|
| `enable_toggle` | input_boolean | ai_winddown_enabled | Kill switch |
| `time_window_start` | time | 20:30 | Window start |
| `time_window_end` | time | 02:00 | Window end (cross-midnight OK) |
| `run_days` | multi-select | all | Active days |
| `cooldown_minutes` | number (1–240) | 30 | Base cooldown between offers |
| `repeat_while_present` | boolean | true | Keep offering while in bed |
| `max_offers_per_session` | number | 0 (unlimited) | Cap per session |
| `bedtime_active_entity` | input_boolean | ai_bedtime_active | Routine mutex |
| `winddown_active_flag` | input_boolean | ai_winddown_active | In-progress flag |

### ④ Escalation Settings

| Input | Type | Default | Description |
|---|---|---|---|
| `enable_escalation` | boolean | true | Multi-stage escalation |
| `escalation_stage_count` | number (2–8) | 4 | Number of stages |
| `cooldown_curve` | select | accelerating | fixed / accelerating / custom |
| `custom_stage_intervals` | text | 30,20,15,10 | Per-stage minutes |
| `absence_gap_minutes` | number (0–120) | 15 | Resume window |
| `no_response_behavior` | select | advance | advance / reset on decline |
| `stage_1..6_prompt_overlay` | text | (see defaults) | Per-stage LLM tone |
| `autonomous_execution_prompt` | text | (dramatic) | Final stage TTS |

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
