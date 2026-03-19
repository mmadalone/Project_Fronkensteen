# Goodnight LLM Negotiator (agent personas + stage modes + fallbacks)

![Header](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/goodnight_negotiator_llm_driven-header.jpeg)

LLM-driven goodnight routine with resilient satellite handling. Uses conversation agents for all prompts and responses, with per-stage mode control (ask/just_do/skip) and per-stage fallback policies for voice failures. Persona comes from Home Assistant conversation agents via Assist Pipelines, with optional custom opening/closing prompts. Music will NOT start unless explicitly confirmed when Stage 3 mode is set to ask.

## How It Works

```
START
  |
  v
[Agent selection: dispatcher or manual pipeline]
  |
  v
[Speech guard delay]
  |
  v
[Set satellite volume (optional)]
  |
  v
<Say opening line?>--YES-->[LLM generates greeting]
  |                            |
  NO                           v
  |                       [Announce via satellite]
  |                            |
  +----------+-----------------+
             |
             v
========= STAGE 1: TV / IR =========
<mode != skip + scripts exist?>
  |         |
 YES        NO (skip)
  |         |
  v         |
<just_do?>--YES-->[Run IR scripts]
  |                    |
  NO (ask)             |
  |                    |
  v                    |
[LLM asks yes/no via satellite]
  |                    |
  v                    |
[Classify: yes/no/unclear]
  |    |    |          |
 YES  NO  UNCLEAR      |
  |    |    |          |
  v    |  [Fallback]   |
[Run]  |    |          |
  +----+----+----------+
       |
       v
========= STAGE 2: DEVICES =========
[Same ask/just_do/skip pattern]
[Turn off device targets]
       |
       v
========= STAGE 3: MUSIC ===========
<mode != skip?>
  |         |
 YES        NO
  |         |
  v         |
<Already playing?>
  |         |
  v         |
[Handle: ask/keep/stop]
  |         |
<just_do?>--YES-->[Play media_id directly]
  |                    |
  NO (ask)             |
  |                    |
  v                    |
[LLM asks via satellite]
  |                    |
  v                    |
[Classify + fallback]  |
  |                    |
  v                    |
[Set volume + play]    |
  +----------+---------+
             |
             v
<Say closing line?>--YES-->[LLM generates farewell]
  |                            |
  +----------+-----------------+
             |
             v
END
```

## Features

- Full LLM-driven conversational flow via conversation agents
- Per-stage mode: ask (voice confirmation), just_do (execute silently), skip (do nothing)
- Per-stage fallback on voice failure: ask (retry), do_it_anyway, skip, safe_default (Stage 3)
- AI dispatcher integration for dynamic persona selection
- Custom opening and closing prompts (or defaults)
- Multi-language yes/no classification (English, Dutch, Spanish, Catalan)
- Reprompt-once option for unclear voice responses
- Music Assistant integration with media_id/URI playback
- "Already playing" detection (ask/keep/stop)
- Volume control with duck guard snapshot sync
- Speech guard delay to avoid SatelliteBusy collisions
- Configurable TTS output volume on satellite
- Stable conversation_id for cross-stage LLM context retention
- Fallback play workaround: if MA queues but stays paused, issues `media_play`

## Prerequisites

- Home Assistant **2024.10.0** or newer
- Assist Satellite (Voice PE) entity
- Music Assistant integration (for Stage 3)
- `pyscript.agent_dispatch` service (agent dispatcher)
- `pyscript.agent_whisper` service (agent whisper)
- Duck guard system (optional)

## Installation

1. Copy `goodnight_negotiator_llm_driven.yaml` to `config/blueprints/script/madalone/`
2. Create script: **Settings > Automations & Scenes > Scripts > Add > Use Blueprint**

## Configuration

<details>
<summary><strong>Section 1 -- Persona & Prompts</strong></summary>

| Input | Default | Description |
|---|---|---|
| `use_dispatcher` | `true` | AI dispatcher selects persona dynamically |
| `persona_agent_id` | `Rick - Bedtime` | Assist Pipeline (when dispatcher is disabled) |
| `bedtime_conversation_id` | `bedtime_negotiator` | Stable conversation ID for context retention |
| `current_area_name` | _(empty)_ | Area name for natural phrasing |
| `user_name` | `the user` | First name or nickname for LLM prompts |
| `pre_prompt_custom` | _(empty)_ | Custom opening prompt (empty = default) |
| `final_prompt_custom` | _(empty)_ | Custom closing prompt (empty = default) |

</details>

<details>
<summary><strong>Section 2 -- Voice Device & Behavior</strong></summary>

| Input | Default | Description |
|---|---|---|
| `assist_satellite` | _(required)_ | Voice PE satellite entity |
| `speech_guard_delay_seconds` | `1` | Delay before first TTS (0-10s) |
| `tts_output_volume` | `0.0` | Volume for satellite TTS (0 = use current) |
| `fallback_ask_delay_seconds` | `2` | Delay before retry on fallback=ask (0-20s) |
| `say_pre_line` | `true` | Speak opening line |
| `say_final_line` | `true` | Speak closing line |
| `reprompt_once_on_unclear` | `true` | Ask "yes or no?" once on classification failure |
| `yesno_language_profile` | `multi` | multi / en / nl / es / ca |

</details>

<details>
<summary><strong>Section 3 -- Stage 1: TV / IR</strong></summary>

| Input | Default | Description |
|---|---|---|
| `tv_stage_mode` | `ask` | ask / just_do / skip |
| `tv_friendly_name` | `the tv` | Spoken name for TV/IR devices |
| `ir_off_scripts` | `[]` | Scripts that turn off TV/IR devices |
| `tv_fallback_on_voice_fail` | `do_it_anyway` | ask / do_it_anyway / skip |

</details>

<details>
<summary><strong>Section 4 -- Stage 2: Devices</strong></summary>

| Input | Default | Description |
|---|---|---|
| `devices_stage_mode` | `ask` | ask / just_do / skip |
| `devices_targets` | `{}` | Entities to turn off (target selector) |
| `devices_fallback_on_voice_fail` | `do_it_anyway` | ask / do_it_anyway / skip |

</details>

<details>
<summary><strong>Section 5 -- Stage 3: Music</strong></summary>

| Input | Default | Description |
|---|---|---|
| `music_stage_mode` | `ask` | ask / just_do / skip |
| `music_player` | _(required)_ | Music Assistant player entity |
| `music_if_already_playing` | `ask` | ask / keep / stop |
| `music_volume` | `0.25` | Music volume (0-1) |
| `music_media_id` | _(empty)_ | Music Assistant media_id / URI |
| `music_media_type` | `auto` | auto / playlist / album / track / artist / radio |
| `music_fallback_on_voice_fail` | `skip` | skip / ask / safe_default |

</details>

<details>
<summary><strong>Section 6 -- Infrastructure</strong></summary>

| Input | Default | Description |
|---|---|---|
| `ducking_flag` | `input_boolean.ducking_flag` | Ducking active flag |
| `duck_guard_enabled` | `input_boolean.ai_duck_guard_enabled` | Duck guard toggle |
| `dispatcher_enabled` | `input_boolean.ai_dispatcher_enabled` | Dispatcher toggle |

</details>

## Technical Notes

- **Mode:** `single` / icon: `mdi:bed`
- **Yes/No classification:** Regex patterns with multi-language support; configurable via `yesno_language_profile`
- **Music safety:** In ask mode, music will NOT start unless the user explicitly confirms
- **MA fallback play:** If Music Assistant queues content but the player stays paused/idle, the script issues `media_player.media_play` as a workaround
- **Duck guard:** Volume changes on satellite and music player sync the duck snapshot when guard is active
- **Conversation context:** Uses a stable `conversation_id` so the LLM retains context across all stages within one run

## Changelog

- **v2.0.0:** Full Rules of Acquisition compliance pass
- Earlier versions: see repository history

## Author

**madalone**

## License

See repository for license details.
