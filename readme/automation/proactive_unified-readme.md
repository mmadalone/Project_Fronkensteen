# Proactive -- Unified presence engine

![Proactive Unified](https://raw.githubusercontent.com/mmadalone/HA-Master-Repo/main/images/header/proactive_llm_sensors-header.jpeg)

Consolidation of `proactive.yaml` (template), `proactive_llm.yaml` (LLM), and `proactive_llm_sensors.yaml` (LLM + sensors + weekends) into a single blueprint using the full voice infrastructure layer. Supports two message modes: **template** (reads from input_text helpers) and **llm** (generates via conversation agent). Budget gate automatically forces template mode when LLM budget drops below 60%.

## How It Works

```
┌──────────────────┐   ┌──────────────────┐
│ Presence ON      │   │ Nag tick (/5 min)│
│ (binary sensors) │   │ time_pattern     │
└────────┬─────────┘   └────────┬─────────┘
         └─────────┬────────────┘
                   ▼
┌──────────────────────────────────────┐
│ Conditions                           │
│ • Not during active bedtime          │
│ • Identity confidence >= 50          │
│ • Day-of-week + weekend mode gate    │
│ • Within active time window          │
│ • Media guard (optional)             │
│ • Minimum presence duration          │
│ • Presence still detected            │
│ • Repeat mode gate                   │
│ • Cooldown + max nags check          │
│ • Privacy gate                       │
└──────────────────┬───────────────────┘
                   │
         ┌─────────┴─────────┐
         │ Mode?             │
         └──┬──────────┬─────┘
    template│          │llm
            ▼          ▼
┌────────────────┐ ┌─────────────────────┐
│ Read from      │ │ Dispatch agent      │
│ input_text     │ │ Build LLM prompt    │
│ (morning/      │ │ conversation.process│
│  afternoon/    │ │ Extract speech      │
│  evening)      │ └──────────┬──────────┘
└────────┬───────┘            │
         └────────┬───────────┘
                  ▼
┌──────────────────────────────────────┐
│ pyscript.dedup_announce              │
│ (TTS + duplicate suppression)        │
├──────────────────────────────────────┤
│ pyscript.agent_whisper               │
│ (post-interaction context)           │
├──────────────────────────────────────┤
│ Optional: bedtime question           │
│ (Assist Satellite yes/no)            │
├──────────────────────────────────────┤
│ Optional: refresh button press       │
│ (template mode)                      │
└──────────────────────────────────────┘
```

## Features

- Two message modes: template (input_text helpers) and LLM (conversation agent)
- Budget gate: forces template mode when LLM budget < 60%
- Agent dispatcher for dynamic persona selection
- Dedup announce: duplicate suppression + TTS delivery in one call
- Agent whisper: post-interaction context for the whisper network
- Identity gate: requires confidence >= 50 for any known user
- Bedtime skip: suppressed when `bedtime_active` is on
- Configurable presence sensors with minimum duration guard
- Media-playing guard (don't speak over active playback)
- Repeat-while-present with cooldown and max nags per session
- TTS collision modes: dedup, queue, or barge-in
- Configurable TTS output volume
- Cross-midnight time window support
- Day-of-week gating with weekend mode (same/disabled/weekend profile)
- Weekend overrides: separate schedule, cooldown, and LLM prompt
- Optional bedtime yes/no question via Assist Satellite
- Weekend bedtime question overrides
- Template mode: time-of-day message helpers (morning/afternoon/evening) with optional refresh
- LLM mode: user name randomization, context entity injection, customizable prompts
- Rich sensor context in LLM prompts (media players show now-playing, Kodi shows series/episode/PVR details)
- Privacy gate with per-person tier suppression
- Stored traces: 15 for debugging

## Prerequisites

- Home Assistant 2024.10.0+
- Pyscript integration with `dedup_announce`, `agent_dispatch`, `agent_whisper` services
- Presence sensors (binary_sensor, device_class: occupancy)
- For template mode: `input_text` helpers for morning/afternoon/evening messages
- For LLM mode: Conversation agent (Assist Pipeline)
- Optional: Assist Satellite for bedtime questions

## Installation

1. Copy `proactive_unified.yaml` to `config/blueprints/automation/madalone/`
2. Create one instance per area: **Settings -> Automations -> Create -> Use Blueprint**

## Configuration

<details>
<summary><strong>① Presence & detection</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| `presence_sensors` | `[]` | Binary sensors indicating presence in this area |
| `min_presence_seconds` | `0` | Minimum continuous presence before speaking (0-600) |
| `block_if_media_playing` | `false` | Suppress TTS while media player is active |
| `media_player` | *(empty)* | Media player for media guard (NOT for TTS) |
| `area_name` | `Workshop` | Friendly area name for speech and dedup keys |

</details>

<details>
<summary><strong>② Mode</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| `proactive_mode` | `llm` | template (from helpers) or llm (conversation agent) |
| `use_dispatcher` | `true` | Use AI dispatcher for persona selection |
| `tts_output_volume` | `0.0` | Volume before TTS (0 = don't change) |
| `tts_collision_mode` | `queue` | dedup / queue / barge_in |

</details>

<details>
<summary><strong>③ Template settings</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| `message_morning_helper` | *(required)* | input_text entity for morning messages |
| `message_afternoon_helper` | *(required)* | input_text entity for afternoon messages |
| `message_evening_helper` | *(required)* | input_text entity for evening messages |
| `refresh_after_run` | `false` | Press refresh button after speaking |
| `refresh_button` | *(empty)* | input_button for message refresh |

</details>

<details>
<summary><strong>④ LLM settings</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| `user_names` | *(empty)* | Comma-separated names/nicknames (random pick) |
| `fallback_names` | `friend, hey there` | Fallback direct address terms |
| `llm_fallback_names` | `the user` | Fallback 3rd-person LLM reference terms |
| `conversation_agent` | `Rick` | Voice Assistant when dispatcher is disabled |
| `llm_prompt` | *(playful one-liner prompt)* | LLM prompt for proactive messages |
| `context_entities` | `[]` | Extra sensors/entities for LLM context |

</details>

<details>
<summary><strong>⑤ Schedule & timing</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| `start_time` | `08:00:00` | Active window start |
| `end_time` | `23:00:00` | Active window end (cross-midnight supported) |
| `run_days` | All days | Days the automation is active |
| `cooldown_minutes` | `30` | Minimum time between messages (nag interval) |
| `repeat_while_present` | `false` | Keep nagging at cooldown intervals |
| `max_nags_per_session` | `3` | Max nags while presence stays on (0 = unlimited) |

</details>

<details>
<summary><strong>⑥ Weekend overrides</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| `weekend_mode` | `same_as_weekdays` | same / disabled / use_weekend_profile |
| `weekend_days` | `sat, sun` | Days treated as weekend |
| `weekend_start_time` | `08:00:00` | Weekend active window start |
| `weekend_end_time` | `23:00:00` | Weekend active window end |
| `weekend_cooldown_minutes` | `30` | Weekend cooldown interval |
| `weekend_llm_prompt_override` | *(empty)* | Alternate weekend prompt |

</details>

<details>
<summary><strong>⑦ Bedtime question</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| `enable_bedtime_question` | `false` | Ask bedtime yes/no question after TTS |
| `bedtime_assist_satellite` | *(empty)* | Assist Satellite for bedtime question |
| `bedtime_question_delay` | `5` | Delay between TTS and question (seconds) |
| `bedtime_llm_prompt` | *(short yes/no prompt)* | LLM prompt for bedtime question |
| `bedtime_question_text` | `Do you want me to help you go to bed now?` | Fallback text |
| `bedtime_help_script` | *(empty)* | Script to run on "yes" answer |
| `weekend_bedtime_mode` | `same_as_weekdays` | same / disabled / use_weekend_bedtime_prompt |
| `weekend_bedtime_llm_prompt_override` | *(empty)* | Weekend bedtime prompt override |

</details>

<details>
<summary><strong>⑧ Privacy</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| `privacy_tier` | `t2` | Privacy gate tier (off/t1/t2/t3) |
| `privacy_gate_enabled` | `input_boolean.ai_privacy_gate_enabled` | Privacy gate system toggle |
| `privacy_gate_mode` | `input_select.ai_privacy_gate_mode` | Privacy gate behavior |
| `privacy_gate_person` | `miquel` | Person name for tier suppression |

</details>

<details>
<summary><strong>⑨ Infrastructure</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| `dispatcher_enabled` | `input_boolean.ai_dispatcher_enabled` | Dispatcher system toggle |

</details>

## Technical Notes

- **Mode:** `single` / `max_exceeded: silent`
- **Stored traces:** 15
- Cross-midnight time windows use timestamp comparison with day-shift attribution
- Weekend profile detection uses the weekday schedule for initial day-shift to avoid hijacking active cross-midnight sessions at rollover
- Budget gate checks `sensor.ai_total_daily_cost` percentage -- LLM mode is forced to template when >= 60%
- Nag tick runs every 5 minutes; effective cooldown intervals are rounded up to nearest 5-minute boundary
- `cooldown - 30` seconds tolerance prevents off-by-one misses at cooldown boundaries
- Max nags uses session duration calculation (nags x cooldown x 60) against presence start time
- Rich context for media players: now-playing titles, artists, Kodi series/episode/PVR details
- Privacy gate evaluates per-automation override via `input_select.ai_privacy_gate_proactive_unified`

## Changelog

- **v1.0:** Initial unified release -- merges proactive.yaml, proactive_llm.yaml, and proactive_llm_sensors.yaml

## Author

**madalone**

## License

See repository for license details.
