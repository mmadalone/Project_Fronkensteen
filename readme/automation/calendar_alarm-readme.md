![Calendar Alarm](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/calendar_alarm-header.jpeg)

# Calendar-Aware Wake-Up Alarm

Fires at the dynamically-computed wake time from the bedtime advisor (`input_datetime.ai_predicted_wake_time`). Optionally restricted to workdays only and presence-gated. The alarm turns on configured lights/switches, announces via TTS (static or LLM-generated), and can call an optional wake script for extended routines like music handoff, curtains, or coffee machines. Deliberately lean -- no snooze/stop cycle by design.

## How It Works

```
input_datetime.ai_predicted_wake_time
(updated every 30 min by predictive_schedule.py)
        |
        v
+-------------------+
| Time trigger      |
+-------------------+
        |
        v
+-------------------+     +-------------------+
| Workday gate      |---->| Presence gate     |
| (if enabled)      |     | (if configured)   |
+-------------------+     +-------------------+
                                  |
                                  v
                          +-------------------+
                          | Privacy gate      |
                          +-------------------+
                                  |
                                  v
                          +-------------------+
                          | Bypass follow-me  |
                          | (claim refcount)  |
                          +-------------------+
                                  |
                                  v
                          +-------------------+
                          | Agent selection   |
                          | (dispatcher or    |
                          |  manual pipeline) |
                          +-------------------+
                                  |
                                  v
                          +-------------------+
                          | Turn on wake      |
                          | entities          |
                          +-------------------+
                                  |
                                  v
                          +-------------------+
                          | Generate message  |
                          | (static or LLM)   |
                          +-------------------+
                                  |
                                  v
                          +-------------------+
                          | TTS announcement  |
                          | (satellite or     |
                          |  media player)    |
                          +-------------------+
                                  |
                                  v
                          +-------------------+
                          | Run wake script   |
                          | (if configured)   |
                          +-------------------+
                                  |
                                  v
                          +-------------------+
                          | Release follow-me |
                          +-------------------+
```

## Features

- Dynamic wake time from `predictive_schedule.py` bedtime advisor (I-29 integration)
- Workday-only gating via `calendar_promote.py` work day detection
- Presence gating: all configured binary sensors must have been ON for minimum duration
- Agent dispatcher integration with manual pipeline fallback
- TTS via Assist Satellite (`assist_satellite.announce`) or media player (`tts_queue_speak`)
- Static or LLM-generated wake-up messages with automatic fallback
- Configurable wake entities (lights/switches) turned on at alarm time
- Optional wake script for extended routines (music, curtains, coffee, etc.)
- Follow-me bypass via refcount claim/release pattern
- Privacy gate with tiered suppression (T1 intimate by default)
- Agent whisper context injection after delivery

## Prerequisites

- Home Assistant 2024.10.0+
- `input_datetime.ai_predicted_wake_time` (set by `predictive_schedule.py`)
- `input_boolean.ai_context_work_day_tomorrow` (set by `calendar_promote.py`)
- `pyscript/agent_dispatcher.py` (agent selection)
- `pyscript/tts_queue.py` (TTS playback)
- `pyscript/agent_whisper.py` (whisper context)
- Refcount bypass scripts (for follow-me bypass)

## Installation

1. Copy `calendar_alarm.yaml` to `config/blueprints/automation/madalone/`
2. Create automation: **Settings -> Automations -> Create -> Use Blueprint**

## Configuration

<details><summary>① Schedule</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `wake_time_entity` | `input_datetime.ai_predicted_wake_time` | Entity holding the predicted wake time |
| `workday_only` | `true` | Only fire if tomorrow is a work day |
| `workday_entity` | `input_boolean.ai_context_work_day_tomorrow` | Work day indicator boolean |

</details>

<details><summary>② Presence</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `presence_sensors` | `[]` | Binary sensors that must all be ON for min duration |
| `presence_min_minutes` | `30` | Minimum continuous presence duration (minutes) |

</details>

<details><summary>③ Wake Actions</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `wake_script` | _(empty)_ | Optional script for extended wake routines |
| `wake_entities` | `[]` | Lights/switches to turn on at alarm time |

</details>

<details><summary>④ TTS & Voice</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `satellite_entity` | _(empty)_ | Assist Satellite for TTS announcements |
| `tts_output_player` | _(empty)_ | Media player for TTS output |
| `wake_message` | `Good morning. Time to get up.` | Static wake-up message (fallback) |
| `use_llm` | `false` | Generate context-aware message via LLM |
| `llm_wake_prompt` | `Generate a brief, friendly good-morning...` | LLM prompt for wake-up message |

</details>

<details><summary>⑤ Infrastructure</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `use_dispatcher` | `true` | Use AI dispatcher for agent selection |
| `conversation_agent` | `Rick` | Pipeline used when dispatcher is disabled |
| `bypass_follow_me` | `true` | Pause follow-me during wake-up sequence |
| `dispatcher_enabled` | `input_boolean.ai_dispatcher_enabled` | Dispatcher toggle entity |
| `bypass_claim_script` | `script.refcount_bypass_claim` | Refcount bypass claim script |
| `bypass_release_script` | `script.refcount_bypass_release` | Refcount bypass release script |

</details>

<details><summary>⑥ Privacy</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `privacy_tier` | `t1` | Privacy gate tier (off/t1/t2/t3). T1 = intimate |
| `privacy_gate_enabled` | `input_boolean.ai_privacy_gate_enabled` | Privacy gate toggle |
| `privacy_gate_mode` | `input_select.ai_privacy_gate_mode` | Privacy gate mode selector |
| `privacy_gate_person` | `person.miquel` | Person entity for tier suppression lookups |

</details>

<details><summary>⑦ Music</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `wake_melody_enabled` | `false` | Play a personalized wake-up melody before the TTS alarm |
| `wake_melody_agent` | _(empty)_ | Agent persona for melody style. Empty = use dispatched agent |
| `wake_melody_volume` | `0.3` | Volume for wake-up melody playback (0.0-1.0) |
| `wake_melody_source` | `auto` | auto (cached API melody, local fallback) or fluidsynth (free, instant) |
| `wake_melody_library_id_override` | _(empty)_ | Specific library ID to play, bypassing auto-resolution |
| `wake_melody_delay_after` | `2` | Seconds to wait after melody before alarm continues |
| `wake_melody_fallback_url` | _(empty)_ | Static audio URL if library empty and compose is off |

</details>

## Technical Notes

- **Mode:** `single` (silent on exceeded) -- one alarm at a time
- **TTS priority:** Satellite announce takes precedence over media player TTS queue
- **LLM fallback:** If LLM call fails or returns empty, falls back to static `wake_message`
- **Dispatcher path:** Calls `pyscript.agent_dispatch` with `wake_word: proactive_wakeup` and `skip_continuity: true`
- **Presence check:** Uses `last_changed` for accurate duration calculation; all sensors must be continuously ON
- **No snooze/stop:** By design. Chain with `wake-up-guard.yaml` for snooze functionality
- **Error handling:** All action steps use `continue_on_error: true`; wake entities and scripts guarded by length checks

## Author

**madalone**

## License

See repository for license details.
