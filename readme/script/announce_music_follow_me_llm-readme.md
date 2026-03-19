# Announce Music Follow Me (TTS, LLM)

![Image](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/announce_music_follow_me_llm-header.jpeg)

Script blueprint that announces via TTS where the music was moved for a "music follow me" automation. Supports three message strategies: static default, random message pool, and LLM-generated context-aware announcements. When the LLM path is active, the conversation agent receives playback context (track name, artist, radio station) to produce relevant commentary.

## How It Works

```
START (called with target_player, source_player, tts_output_player)
  |
  v
<Dispatcher enabled?>--YES-->[agent_dispatch]
  |                              |
  NO                             v
  |                     [Set agent/voice/persona]
  v                              |
[Resolve pipeline]               |
  |<-----------------------------+
  v
[Resolve player names + playback context + time of day]
  |
  v
<LLM enabled?>---YES--->[conversation.process with context]
  |        |                |
  |        |                v
  |        |          [Sanitize LLM response]
  |        |                |
  |        NO but random    |
  |        |                |
  |        v                |
  |  [Pick from pool]       |
  |        |                |
  NO (static)               |
  |        |                |
  v        v                v
[Default message]     [tts_message set]
  |                        |
  +------------------------+
  |
  v
[TTS queue speak to target player]
  |
  v
[Whisper -- self-awareness]
  |
  v
END
```

## Features

- Three message strategies: static default, random pool, or LLM-generated
- LLM context awareness: includes currently playing track/artist or radio station
- Radio detection via `media_content_type` with string-match fallback
- Waterfall player resolution: prefers source then target based on active `media_title`
- LLM response sanitization: catches tool/function definition leakage
- Playback context toggle (can exclude track info from LLM prompt)
- Customizable LLM prompt template with `{player_name}`, `{current_time}`, `{time_of_day}` placeholders
- Optional `tts_output_player` override for announcement target
- Time-of-day awareness (late night / morning / afternoon / evening)

## Prerequisites

- Home Assistant **2024.10.0** or newer
- `pyscript.agent_dispatch` service (agent dispatcher)
- `pyscript.tts_queue_speak` service (TTS queue)
- `pyscript.agent_whisper` service (agent whisper)
- A conversation agent configured in an Assist Pipeline (for LLM mode)

## Installation

1. Copy `announce_music_follow_me_llm.yaml` to `config/blueprints/script/madalone/`
2. Create script: **Settings > Automations & Scenes > Scripts > Add > Use Blueprint**

## Configuration

<details>
<summary><strong>Section 1 -- Voice Assistant</strong></summary>

| Input | Default | Description |
|---|---|---|
| `use_dispatcher` | `true` | AI dispatcher selects persona dynamically |

</details>

<details>
<summary><strong>Section 2 -- Message Strategy</strong></summary>

| Input | Default | Description |
|---|---|---|
| `use_random_messages` | `true` | Pick a random message from pool instead of default |
| `use_llm_fun_messages` | `false` | Use conversation agent for context-aware announcements |
| `custom_random_messages` | 3 templates | Pool of announcement templates with `{player_name}` placeholder |
| `default_message` | `Moving the music to {player_name}.` | Fallback message template |

</details>

<details>
<summary><strong>Section 3 -- LLM Configuration</strong></summary>

| Input | Default | Description |
|---|---|---|
| `use_playback_context` | `true` | Include current track info in LLM prompt |
| `llm_prompt_template` | _(casual smart home assistant prompt)_ | System prompt with `{player_name}`, `{current_time}`, `{time_of_day}` |
| `llm_agent_id` | `Rick` | Voice Assistant pipeline (used when dispatcher is disabled) |

</details>

<details>
<summary><strong>Section 4 -- Infrastructure</strong></summary>

| Input | Default | Description |
|---|---|---|
| `dispatcher_enabled` | `input_boolean.ai_dispatcher_enabled` | Dispatcher toggle entity |

</details>

### Script Fields (passed at call time)

| Field | Required | Description |
|---|---|---|
| `target_player` | Yes | Media player where music is being moved to |
| `source_player` | No | Media player where music was playing before |
| `tts_output_player` | No | Override where TTS announcement plays |

## Technical Notes

- **Mode:** `queued` / `max_exceeded: silent`
- **Error handling:** `continue_on_error: true` on all external service calls
- **LLM timeout caveat:** If the LLM hangs, the script blocks until HA's default timeout (no per-action override)
- **Silent exit:** If no TTS entity is resolved, the script exits cleanly without announcement

## Changelog

- **v6 (2026-02-24):** Audit pass -- trimmed Jinja whitespace, removed redundant filters, clarified silent-exit design
- **v5 (2026-02-24):** Fixed Jinja whitespace contamination in ctx_player, time_of_day, and tts_message branches
- **v4 (2026-02-24):** Waterfall ctx_player resolution; radio detection via media_content_type
- **v3 (2026-02-18):** Bumped min_version to 2024.10.0; added defaults and collapsed sections
- **v2 (2026-02-15):** Fixed voice_profile crash on non-ElevenLabs; migrated to action: syntax
- **v1 (2026-02-14):** Initial version

## Author

**madalone**

## License

See repository for license details.
