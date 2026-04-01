# Proactive Bedtime Escalation (v1.7)

![Proactive Bedtime Escalation](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/proactive_bedtime_escalation-header.jpeg)

Unified presence-based escalation blueprint with inline bedtime routine. Combines a proactive LLM nag layer with a multi-stage escalation engine that culminates in an autonomous bedtime routine -- audiobook (Music Assistant) or Kodi playback. Presence in a configured area triggers LLM-generated spoken messages, with each successive nag advancing the escalation stage, adjusting tone and assertiveness via stage-specific prompts.

## How It Works

```
┌─────────────────────┐   ┌──────────────────────┐
│ Presence ON         │   │ Nag tick (/5 min)    │
│ (binary sensors)    │   │ + Scheduled bedtime  │
└─────────┬───────────┘   └──────────┬───────────┘
          └─────────┬────────────────┘
                    ▼
┌────────────────────────────────────────┐
│ Conditions                             │
│ • Not during active bedtime            │
│ • Identity confidence >= 50            │
│ • Day-of-week + weekend mode gate      │
│ • Within active time window            │
│ • Media guard (optional)               │
│ • Minimum presence duration            │
│ • Presence still detected              │
│ • Repeat mode gate                     │
│ • Cooldown + max nags check            │
│ • Privacy gate                         │
└────────────────┬───────────────────────┘
                 │
                 ▼
┌────────────────────────────────────────┐
│ Dispatch agent (dispatcher or manual)  │
│ Build LLM prompt + stage overlay       │
│ Generate TTS via conversation.process  │
│ Deliver via dedup_announce             │
└────────────────┬───────────────────────┘
                 │
     ┌───────────┴───────────┐
     │ Escalation enabled?   │
     └───┬───────────────┬───┘
     YES │               │ NO
         ▼               ▼
┌──────────────┐  ┌──────────────────┐
│ Advance      │  │ Optional bedtime │
│ stage        │  │ yes/no question  │
│              │  └──────────────────┘
│ Final stage? │
│ ├─ YES →     │
│ │  Bedtime   │
│ │  routine   │
│ └─ NO →      │
│   Bedtime    │
│   question?  │
└──────────────┘
        │
        ▼
┌────────────────────────────────────────┐
│ INLINE BEDTIME ROUTINE                 │
│ ├─ Stop TV (CEC/IR/script)            │
│ ├─ Kill lights (except lamp)          │
│ ├─ Media playback (audiobook or Kodi) │
│ ├─ Countdown timer                    │
│ ├─ Bathroom occupancy guard           │
│ ├─ Final goodnight TTS                │
│ └─ Lamp off + cleanup                 │
└────────────────────────────────────────┘
```

## Features

- 22 configurable input sections (numbered ①-㉒), 33 prompts, zero hardcoded strings
- Multi-stage escalation engine with configurable stage count (2-8)
- Three cooldown curves: fixed, accelerating (halves each stage), or custom per-stage intervals
- Absence gap tolerance: session resumes if user returns within configured window
- Stage-specific prompt overlays with automatic gap-fill for stages without explicit prompts
- Autonomous bedtime execution at final escalation stage
- Bedtime yes/no question via Assist Satellite (configurable start stage)
- Media mode selector: audiobook (Music Assistant) or Kodi, with preset/curated modes
- Sleepy TV detection: skips content switching if bedtime content already playing
- Countdown negotiation via LLM conversation
- Bathroom occupancy guard with timeout and grace period
- Settling-in TTS and final goodnight TTS with sensor context injection
- Independent weekend overrides for both proactive and bedtime layers
- Kill switch, conflict guard (bedtime mutex), and test mode
- Test mode: compressed cooldowns, device actions skipped, only TTS + logbook
- Optional memory tool integration for bedtime history tracking
- Bed presence sensor: bypasses escalation and runs bedtime routine directly
- Agent dispatcher support with manual pipeline fallback
- Per-instance voice assistants for proactive and bedtime flows
- Privacy gate with tiered suppression

## Prerequisites

- Home Assistant 2024.10.0+
- Pyscript integration with `agent_dispatch`, `tts_queue_speak`, `dedup_announce`, and `agent_whisper` services
- Presence sensors (binary_sensor, device_class: occupancy)
- Assist Satellite for bedtime questions/conversations
- Optional: Music Assistant for audiobook playback
- Optional: Kodi integration for TV bedtime content
- Escalation helpers: `input_number` (stage counter), `input_datetime` (session timestamp)

## Installation

1. Copy `proactive_bedtime_escalation.yaml` to `config/blueprints/automation/madalone/`
2. Create required helpers (stage counter, session timestamp, conflict guard)
3. Create automation: **Settings -> Automations -> Create -> Use Blueprint**

## Configuration

<details>
<summary><strong>① Presence & detection</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| `presence_sensors` | `[]` | Binary sensors indicating presence in this area |
| `min_presence_seconds` | `0` | Minimum continuous presence before speaking (0-600) |
| `block_if_media_playing` | `false` | Suppress TTS while media player is active |

</details>

<details>
<summary><strong>② TTS & speaker</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| `media_player` | *(empty)* | Speaker for proactive TTS in this area |
| `area_name` | `Living room` | Friendly area name for speech context |
| `proactive_tts_volume` | `0.0` | Volume before TTS delivery (0 = skip) |
| `bypass_ducking` | `false` | Skip volume ducking on other speakers during TTS |

</details>

<details>
<summary><strong>③ AI conversation</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| `user_names` | *(empty)* | Comma-separated names/nicknames (random pick) |
| `fallback_names` | `friend, hey there` | Fallback direct address terms |
| `llm_fallback_names` | `the user` | Fallback 3rd-person LLM reference terms |
| `conversation_agent` | `Rick` | Voice Assistant for proactive messages |
| `bedtime_conversation_agent` | `Rick - Bedtime` | Voice Assistant for bedtime routine |
| `use_dispatcher` | `true` | Use AI dispatcher for persona selection |
| `assist_satellites` | *(empty)* | Assist satellites for bedtime conversations |
| `llm_prompt` | *(playful one-liner)* | Base LLM prompt for proactive messages |
| `context_entities` | `[]` | Extra sensors/entities for LLM context |

</details>

<details>
<summary><strong>④ Schedule & timing</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| `start_time` | `08:00:00` | Active window start |
| `end_time` | `23:00:00` | Active window end (cross-midnight supported) |
| `bedtime_weekday_scheduled_time` | `22:00:00` | Weekday scheduled bedtime trigger |
| `run_days` | All days | Days the proactive layer is active |
| `cooldown_minutes` | `30` | Base interval between messages (min) |
| `repeat_while_present` | `false` | Keep nagging at cooldown intervals |
| `max_nags_per_session` | `0` | Max nags per presence session (0 = unlimited) |

</details>

<details>
<summary><strong>⑤ Weekend overrides -- proactive layer</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| `weekend_mode` | `same_as_weekdays` | Weekend behavior: same/disabled/weekend_profile |
| `weekend_days` | `sat, sun` | Days treated as weekend |
| `weekend_start_time` | `10:00:00` | Weekend active window start |
| `weekend_end_time` | `23:00:00` | Weekend active window end |
| `weekend_cooldown_minutes` | `30` | Weekend cooldown interval |
| `weekend_llm_prompt_override` | *(empty)* | Alternate weekend prompt |

</details>

<details>
<summary><strong>⑥ Bedtime question</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| `enable_bedtime_question` | `false` | Ask bedtime yes/no question |
| `bedtime_assist_satellite` | *(empty)* | Satellite for bedtime question |
| `bedtime_question_delay` | `5` | Delay between TTS and question (seconds) |
| `bedtime_llm_prompt` | *(short yes/no prompt)* | LLM prompt for bedtime question |
| `bedtime_question_fallback` | `Do you want me to help you go to bed now?` | Fallback text |
| `weekend_bedtime_mode` | `same_as_weekdays` | Weekend bedtime question behavior |
| `weekend_bedtime_llm_prompt_override` | *(empty)* | Weekend bedtime prompt |

</details>

<details>
<summary><strong>⑦ Escalation settings</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| `enable_escalation` | `false` | Enable multi-stage escalation engine |
| `escalation_stage_count` | `4` | Total stages before autonomous bedtime |
| `escalation_stage_helper` | *(empty)* | input_number for current stage |
| `escalation_session_helper` | *(empty)* | input_datetime for session start |
| `cooldown_curve` | `fixed` | fixed / accelerating / custom |
| `custom_stage_intervals` | `30,20,15,10` | Per-stage intervals (custom curve) |
| `absence_gap_minutes` | `15` | Session resume tolerance (minutes) |
| `no_response_behavior` | `advance` | "No" answer: reset or advance |
| `bedtime_question_start_stage` | `2` | Stage to begin asking bedtime question |
| `stage_1-6_prompt_overlay` | *(tone-specific)* | Per-stage prompt overlays |
| `autonomous_execution_prompt` | *(firm announcement)* | TTS for autonomous bedtime execution |

</details>

<details>
<summary><strong>⑧ Kill switch & guards</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| `kill_switch_entity` | *(empty)* | Master kill switch (input_boolean) |
| `conflict_guard_entity` | *(empty)* | Bedtime active mutex (input_boolean) |

</details>

<details>
<summary><strong>⑨ Test mode & notifications</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| `enable_test_mode` | `false` | Compress cooldowns, skip device actions |
| `test_mode_cooldown_seconds` | `60` | Compressed cooldown in test mode |
| `notify_on_autonomous` | `false` | Notify when bedtime fires autonomously |
| `notify_entity` | *(empty)* | Notification service entity |
| `notify_message` | *(template with stage/area)* | Notification message |
| `autonomous_media_mode` | `conversation_with_preset_fallback` | Media mode for autonomous execution |
| `autonomous_conversation_timeout` | `30` | Conversation timeout for autonomous fallback |

</details>

<details>
<summary><strong>⑩ Devices</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| `bedtime_media_target` | `audiobook` | audiobook / kodi / none |
| `tv_entity` | *(empty)* | TV media player for CEC/software off |
| `tv_off_script` | *(empty)* | Complex TV shutdown script |
| `tv_ir_remote` | *(empty)* | Broadlink/IR remote entity |
| `tv_ir_command` | `Power` | IR power-off command |
| `tv_ir_device` | *(empty)* | IR device name |
| `lights_off_target` | *(empty)* | Lights/switches to turn off |
| `living_room_lamp` | *(empty)* | Lamp that stays on during countdown |
| `reset_switches` | *(empty)* | Speaker reset switches |
| `reset_switch_delay` | `0:00:02` | Reset switch cycle delay |
| `media_players_stop` | *(empty)* | Additional media players to pause/stop |
| `bathroom_sensor` | *(empty)* | Bathroom occupancy sensor |
| `bathroom_max_timeout` | `0:15:00` | Max wait for bathroom to clear |
| `bathroom_grace_period` | `0:01:30` | Grace period after bathroom clears |
| `countdown_helper` | *(empty)* | input_number for negotiated countdown |
| `post_tts_delay` | `3` | Post-TTS buffer (seconds) |
| `tv_sleep_timer_minutes` | `30` | Kodi mode TV sleep timer |

</details>

<details>
<summary><strong>⑪ Audiobook (Music Assistant)</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| `audiobook_player` | *(empty)* | Music Assistant player |
| `audiobook_mode` | `both` | curated / freeform / both / preset |
| `curated_audiobooks` | `The Hitchhiker's Guide...` | Comma-separated audiobook list |
| `audiobook_preset_uri` | *(empty)* | Preset audiobook URI |
| `audiobook_media_type` | `auto` | auto / audiobook / album / playlist / track |
| `audiobook_volume` | `0.25` | Audiobook playback volume |
| `bedtime_prompt` | *(countdown announcement)* | Bedtime announcement prompt |
| `goodnight_prompt` | *(warm goodnight)* | Goodnight prompt (conversational modes) |
| `default_countdown_minutes` | `4` | Default countdown before lamp off |
| `enable_countdown_negotiation` | `true` | Allow LLM to negotiate extra time |
| `enable_audiobook_offer` | `true` | Let LLM offer bedtime audiobook |

</details>

<details>
<summary><strong>⑫ Kodi playback</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| `kodi_entity` | *(empty)* | Kodi media player entity |
| `kodi_volume_target` | `0.15` | Kodi bedtime volume |
| `bedtime_media_mode` | `curated` | curated (voice conversation) / preset |
| `kodi_curated_content` | *(empty)* | Name=ContentID pairs (one per line) |
| `kodi_preset_content` | *(empty)* | Preset content path/URI |
| `kodi_media_content_type` | `DIRECTORY` | DIRECTORY / video / CHANNEL / music |
| `kodi_tts_player` | *(empty)* | TTS audio player (separate from TV) |
| `bedtime_media_post_play_delay` | `3` | Post-play delay before state read |
| `media_conversation_settle_delay` | `30` | Wait after conversation for Kodi to start |

</details>

<details>
<summary><strong>⑬ Sleepy TV detection</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| `sleepytv_detection_method` | `media_title_contains` | Detection method |
| `sleepytv_match_string` | *(empty)* | Match string (empty = disabled) |
| `sleepytv_pvr_sensor` | `sensor.madteevee_pvr_channel` | PVR channel sensor |

</details>

<details>
<summary><strong>⑭ Settling-in TTS</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| `enable_settling_tts` | `false` | Enable post-media settling-in TTS |
| `settling_prompt_audiobook` | *(warm observation)* | Prompt for audiobook settling |
| `settling_sensors_audiobook` | `[]` | Sensor entities for audiobook context |
| `settling_prompt_kodi` | *(warm observation)* | Prompt for Kodi settling |
| `settling_sensors_kodi` | `[]` | Sensor entities for Kodi context |

</details>

<details>
<summary><strong>⑮ Final goodnight TTS</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| `enable_goodnight_tts` | `false` | Enable final goodnight after bathroom guard |
| `goodnight_context_prompt_audiobook` | *(warm goodnight)* | Audiobook goodnight prompt |
| `goodnight_sensors_audiobook` | `[]` | Sensors for audiobook goodnight context |
| `goodnight_context_prompt_kodi` | *(warm goodnight)* | Kodi goodnight prompt |
| `goodnight_sensors_kodi` | `[]` | Sensors for Kodi goodnight context |

</details>

<details>
<summary><strong>⑯ Weekend overrides -- bedtime layer</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| `bedtime_weekend_mode` | `same_as_weekdays` | Weekend bedtime behavior |
| `bedtime_weekend_scheduled_time` | `01:00:00` | Weekend bedtime trigger time |

</details>

<details>
<summary><strong>⑰ Memory & history</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| `enable_memory_tool` | `false` | Enable bedtime history tracking |
| `memory_tool_entity` | `script.voice_memory_tool` | Memory tool script |
| `memory_store_key` | `bedtime.actual` | Key for storing bedtime timestamps |
| `memory_history_search_tags` | `bedtime sleep routine` | Tags for history search |
| `memory_history_inject_prompt` | *(history context prompt)* | Prompt for history injection |
| `memory_scope` | `user` | Memory scope: user / household |
| `memory_expiration_days` | `90` | Days before memory entries expire (0 = forever) |

</details>

<details>
<summary><strong>⑱ Bed presence sensor</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| `bed_presence_sensor` | *(empty)* | Binary sensor confirming user is in bed; bypasses escalation |
| `bed_presence_minutes` | `5` | Minutes bed sensor must be ON before triggering bedtime (1-60) |
| `bed_confirm_countdown_minutes` | `0` | Lamp countdown minutes after bed trigger (0 = skip countdown) |
| `bed_confirm_settling_tts` | `true` | Speak a settling-in announcement instead of full bedtime TTS |
| `bed_confirm_prompt` | *(settling prompt)* | LLM prompt for settling-in announcement when bed sensor triggers |

</details>

<details>
<summary><strong>⑲ Ducking infrastructure</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| `ducking_flag` | `input_boolean.ai_ducking_flag` | Boolean indicating audio ducking is active |
| `duck_guard_enabled` | `input_boolean.ai_duck_guard_enabled` | Boolean that enables the duck guard system |
| `dispatcher_enabled` | `input_boolean.ai_dispatcher_enabled` | Boolean that enables the AI agent dispatcher |

</details>

<details>
<summary><strong>⑳ Privacy</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| `privacy_tier` | `t2` | Privacy gate tier (off/t1/t2/t3) |
| `privacy_gate_enabled` | `input_boolean.ai_privacy_gate_enabled` | Privacy gate system toggle |
| `privacy_gate_mode` | `input_select.ai_privacy_gate_mode` | Privacy gate behavior |
| `privacy_gate_person` | `person.miquel` | Person entity for tier suppression |

</details>

<details>
<summary><strong>㉑ User Preferences</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| `enable_user_preferences` | `true` | Inject user preferences and sleep budget into bedtime prompts |

</details>

<details>
<summary><strong>㉒ Prompts</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| `safety_prefix` | *(safety prefix)* | Prepended to every LLM call to prevent tool invocations |
| `memory_search_instruction` | *(search prompt)* | Prompt for memory tool bedtime history search |
| `bedtime_question_system_prompt` | *(system prompt)* | System prompt for satellite bedtime question conversation |
| `audiobook_offer_start_message` | *(offer prompt)* | Opening message for audiobook satellite conversation |
| `audiobook_offer_system_prompt` | *(system prompt)* | System prompt for audiobook satellite conversation |
| `kodi_media_start_message` | *(offer prompt)* | Opening message for Kodi media satellite conversation |
| `kodi_media_prompt` | *(selection prompt)* | Instruction prompt for curated Kodi media conversation |
| `memory_store_instruction` | *(store prompt)* | Prompt for storing bedtime memory entry via memory tool |
| `goodnight_default_prompt` | *(warm goodnight)* | Fallback goodnight prompt when goodnight_prompt is empty |

</details>

## Technical Notes

- **Mode:** `single` / `max_exceeded: silent`
- Stored traces: 15 (extended for debugging escalation flows)
- Cross-midnight time window supported via timestamp comparison
- Escalation stage persists across automation runs via input_number helper
- Absence gap tolerance uses input_datetime session helper for cross-run state
- Hybrid prompt gap-fill auto-generates behavioural directives for stages without explicit overlays (4-band curve)
- Conflict guard mutex prevents overlap with standalone bedtime blueprints
- Shared bedtime routine (E-02 refactor): autonomous and scheduled paths share a single action sequence
- Stale mutex safety net clears stuck bedtime_active flags from crashed routines

## Changelog

- **v1.7:** Bed presence sensor (⑱) -- binary sensor confirms user is in bed, bypasses escalation
- **v1.6:** Shared bedtime routine refactor (E-02) -- deduplicated action sequences
- **v1.5:** Bed presence sensor, stale mutex safety net, removed freeform/both Kodi modes
- **v1.4:** Hybrid escalation prompt gap-fill for stages without explicit overlays
- **v1.3:** Fix max_nags "0 = unlimited" contract, default branch for testability, fix LLM prompt assembly
- **v1.2:** Fix string-vs-boolean truthiness bug, fix forward-reference error
- **v1.1:** Audit fixes -- explicit mode/max_exceeded, fix compound boolean, add weekday bedtime time input
- **v1.0:** Initial unified release -- merges proactive_llm_sensors v7.6, bedtime_routine v4.2.1, and bedtime_routine_plus

## Author

**madalone**

## License

See repository for license details.
