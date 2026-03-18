# Goodnight Negotiator (Hybrid) v8.8.0

![Image](https://raw.githubusercontent.com/mmadalone/HA-Master-Repo/main/images/header/goodnight_negotiator_hybrid-header.jpeg)

Hybrid bedtime script with multi-stage voice negotiation. Combines LLM-generated conversational prompts with structured yes/no confirmation flow via `assist_satellite.ask_question`. Three independently configurable stages: TV/IR devices, lights/devices, and Music Assistant bedtime audio. Stage 3 features Music Assistant search with LLM-driven category classification, late-night bias, and fallback category offers.

## How It Works

```
START
  |
  v
[Agent selection: dispatcher or manual pipeline]
  |
  v
[Debounce check + lock acquisition (if helpers enabled)]
  |
  v
<Opening line mode?>
  |       |       |
 disabled fixed   llm_generated
  |       |       |
  |       v       v
  |  [Speak    [LLM generates
  |   fixed     greeting]
  |   text]        |
  +---+---+--------+
      |
      v
<Stage 1: TV/IR enabled + mode != skip?>
  |         |
 YES        NO
  |         |
  v         |
<mode = ask + not express?>
  |    |    |
 YES  just_do
  |    |    |
  v    v    |
[LLM asks  [Run IR   |
 yes/no]    scripts]  |
  |              |    |
  v              |    |
[Classify answer]|    |
  |              |    |
 YES/NO/UNCLEAR  |    |
  |    |    |    |    |
  v    |    v    |    |
[Run]  |  [Fallback]  |
  |    |    |    |    |
  +----+----+---+----+
       |
       v
<Stage 2: Devices enabled + mode != skip?>
  |         |
 YES        NO
  |         |
  v         |
[Same ask/just_do/skip pattern as Stage 1]
[Turn off device targets]
  |         |
  +----+----+
       |
       v
<Stage 3: Music enabled + mode != skip?>
  |         |
 YES        NO
  |         |
  v         |
<Already playing?>
  |         |
  v         |
[Handle: ask/keep/stop_and_ask/ask_to_replace]
  |         |
  v         |
[LLM asks what to play]
  |         |
  v         |
[Search Music Assistant by category]
  |         |
  v         |
<Results found?>--NO-->[Offer fallback category?]
  |                         |
 YES                        v
  |                    [Speak "nothing found"]
  v                         |
[Announce selection]        |
  |                         |
  v                         |
[Play via MA / delegate script]
  |                         |
  +----------+--------------+
             |
             v
<Closing line mode?>
  |       |       |
 disabled fixed   llm_generated
  |       |       |
  +---+---+-------+
      |
      v
[Release lock (if helpers enabled)]
      |
      v
END
```

## Features

- Three independent stages: TV/IR, Devices, Music -- each with ask/just_do/skip modes
- Express mode skips all confirmations and executes directly
- LLM-generated conversational prompts for questions, confirmations, and unclear responses
- Custom phrase overrides for all LLM-generated messages
- Multi-language yes/no classification (English, Dutch, Spanish, Catalan, or multi)
- Configurable unclear-answer retries before fallback
- Music Assistant search with category filtering (music, audiobook, podcast, radio, auto)
- Late-night category bias (avoids blasting music at 2am)
- Media context awareness (can mention what's currently playing)
- Optional delegate playback script for custom media handling
- Queue behavior control (clear_then_replace or replace)
- "Already playing" detection with ask/keep/stop_and_ask/ask_to_replace options
- Fallback category offer when target category has no results
- Helper-backed memory: last run epoch, debounce, lock, last opening/question/reply
- Opening and closing lines: disabled, fixed_text, or llm_generated
- Run debounce to prevent double-triggers
- Debug logging for Stage 3 media selection

## Prerequisites

- Home Assistant (no explicit min_version set)
- Assist Satellite (Voice PE) entity
- Music Assistant integration (for Stage 3)
- `pyscript.agent_dispatch` service (agent dispatcher)
- A conversation agent configured in an Assist Pipeline

## Installation

1. Copy `goodnight_negotiator_hybrid.yaml` to `config/blueprints/script/madalone/`
2. Create script: **Settings > Automations & Scenes > Scripts > Add > Use Blueprint**

## Configuration

<details>
<summary><strong>Section 1 -- Core Routing</strong></summary>

| Input | Default | Description |
|---|---|---|
| `user_name` | `friend` | How the assistant addresses you |
| `area_name` | `workshop` | Area name for spoken context |
| `conversation_agent` | `Rick - Bedtime` | Assist Pipeline (overridden when dispatcher is enabled) |
| `use_dispatcher` | `true` | AI dispatcher selects persona dynamically |
| `satellite_entity` | _(required)_ | Voice satellite for questions and spoken lines |

</details>

<details>
<summary><strong>Section 2 -- Express Mode & Timing</strong></summary>

| Input | Default | Description |
|---|---|---|
| `express_mode` | `false` | Skip all confirmations and execute directly |
| `inter_stage_delay` | `1` | Seconds between stages (0-600) |
| `qa_unclear_retries` | `1` | Re-ask count on unclear yes/no answers (0-10) |
| `run_debounce_seconds` | `20` | Ignore new trigger if script ran within this window (0-300) |

</details>

<details>
<summary><strong>Section 3 -- Custom Phrases</strong></summary>

| Input | Default | Description |
|---|---|---|
| `phrase_confirmation` | _(empty = LLM)_ | Spoken after completing an action |
| `phrase_cancelled` | _(empty = LLM)_ | Spoken when user aborts |
| `phrase_unclear_do_anyway` | _(empty = LLM)_ | Spoken on unclear response with do_it_anyway fallback |
| `phrase_unclear_skip` | _(empty = LLM)_ | Spoken on unclear response with skip fallback |
| `phrase_not_found` | _(empty = LLM)_ | Spoken when search returns no results |
| `phrase_ma_error` | _(empty = LLM)_ | Spoken when Music Assistant fails |
| `phrase_playing` | _(empty = LLM)_ | Spoken before playing (use `{name}` placeholder) |
| `phrase_category_empty` | _(empty = LLM)_ | Spoken when category is empty but others have results |

</details>

<details>
<summary><strong>Section 4 -- Context Inputs</strong></summary>

| Input | Default | Description |
|---|---|---|
| `media_context_entities` | `[]` | Media players for LLM context (what's currently playing) |
| `time_aware` | `true` | Mention time only when it's "late" |
| `late_after_hour` | `23` | Hour threshold for "late" detection (0-23) |
| `late_night_category_bias` | `audiobook` | Preferred category when it's late and category is auto |

</details>

<details>
<summary><strong>Section 5 -- Opening & Closing Lines</strong></summary>

| Input | Default | Description |
|---|---|---|
| `opening_line_mode` | `llm_generated` | disabled / fixed_text / llm_generated |
| `opening_line_fixed` | _(empty)_ | Fixed text for opening (when mode = fixed_text) |
| `opening_line_prompt` | _(empty)_ | LLM prompt for opening (empty = built-in default) |
| `closing_line_mode` | `llm_generated` | disabled / fixed_text / llm_generated |
| `closing_line_fixed` | _(empty)_ | Fixed text for closing |
| `closing_line_prompt` | _(empty)_ | LLM prompt for closing |

</details>

<details>
<summary><strong>Section 6 -- Stage 1: TV / IR Devices</strong></summary>

| Input | Default | Description |
|---|---|---|
| `stage1_enabled` | `true` | Enable Stage 1 |
| `stage1_mode` | `ask` | ask / do_it_anyway / skip |
| `stage1_friendly_name` | `the tv` | Spoken name for Stage 1 actions |
| `stage1_scripts` | `[]` | Scripts to run when Stage 1 is approved |
| `stage1_fallback_on_voice_fail` | `do_it_anyway` | do_it_anyway / skip |
| `stage1_confirm_completion` | `true` | Announce "done" after Stage 1 |

</details>

<details>
<summary><strong>Section 7 -- Stage 2: Lights & Devices</strong></summary>

| Input | Default | Description |
|---|---|---|
| `stage2_enabled` | `true` | Enable Stage 2 |
| `stage2_mode` | `ask` | ask / do_it_anyway / skip |
| `stage2_friendly_name` | `the lights and devices` | Spoken name for Stage 2 actions |
| `stage2_targets` | `{}` | Target entities to turn off |
| `stage2_fallback_on_voice_fail` | `do_it_anyway` | do_it_anyway / skip |
| `stage2_confirm_completion` | `true` | Announce "done" after Stage 2 |

</details>

<details>
<summary><strong>Section 8 -- Stage 3: Bedtime Audio</strong></summary>

| Input | Default | Description |
|---|---|---|
| `stage3_enabled` | `true` | Enable Stage 3 |
| `stage3_mode` | `ask` | ask / just_do / skip |
| `stage3_category` | `audiobook` | Search scope: music / audiobook / podcast / radio / auto |
| `stage3_music_assistant_config_entry_id` | _(empty)_ | MA config_entry_id (required for search) |
| `stage3_music_assistant_player` | _(empty)_ | MA media_player entity |
| `stage3_delegate_script_entity_id` | _(empty)_ | Optional delegate playback script |
| `stage3_volume` | `30` | Bedtime audio volume (0-100; 0 = don't change) |
| `stage3_queue_behavior` | `clear_then_replace` | clear_then_replace / replace |
| `stage3_if_something_playing` | `ask_to_replace` | keep / stop_and_ask / ask_to_replace |
| `stage3_ask_prompt_style` | `music_or_story` | Wording style: music_or_story / music_only / story_only / custom |
| `stage3_custom_main_question` | _(empty)_ | Custom question (when style = custom) |
| `stage3_fallback_on_voice_fail` | `skip` | skip / safe_default |
| `stage3_safe_default_category` | `audiobook` | Fallback category for safe_default |
| `stage3_search_limit` | `8` | Results per type bucket (1-25) |
| `stage3_announce_selection` | `true` | Announce what was found before playing |
| `stage3_offer_fallback_category` | `true` | Offer alternative category when target is empty |
| `stage3_debug_log` | `false` | Log selection details to trace |

</details>

<details>
<summary><strong>Section 9 -- Helper-Backed Memory</strong></summary>

| Input | Default | Description |
|---|---|---|
| `helpers_enabled` | `false` | Enable helper-backed state tracking |
| `helper_last_run_epoch` | _(empty)_ | input_number for last run timestamp |
| `helper_run_debounce_seconds` | _(empty)_ | input_number for debounce override |
| `helper_lock_boolean` | _(empty)_ | input_boolean lock (prevents concurrent runs) |
| `helper_last_opening_line` | _(empty)_ | input_text for last opening line |
| `helper_last_question` | _(empty)_ | input_text for last asked question (trace) |
| `helper_last_reply` | _(empty)_ | input_text for last spoken reply (trace) |

</details>

<details>
<summary><strong>Section 10 -- Feedback Options</strong></summary>

| Input | Default | Description |
|---|---|---|
| `announce_unclear_responses` | `true` | Announce when voice response doesn't match yes/no/abort |

</details>

<details>
<summary><strong>Section 11 -- Infrastructure</strong></summary>

| Input | Default | Description |
|---|---|---|
| `dispatcher_enabled` | `input_boolean.ai_dispatcher_enabled` | Dispatcher toggle entity |

</details>

## Technical Notes

- **Mode:** `single` / `max_exceeded: silent`
- **Yes/No classification:** Regex-based with multi-language support (en/nl/es/ca/multi)
- **Express mode:** Treats `ask` stages as `just_do` -- individual `skip` stages are still skipped
- **Stage 3 search:** Uses LLM to generate a strict JSON payload (media_id/media_type) then calls `music_assistant.play_media` directly
- **Lock pattern:** If `helper_lock_boolean` is provided, script refuses to start while lock is ON, sets ON during run, OFF at end
- **Debounce:** Compares current timestamp against `helper_last_run_epoch` to prevent rapid re-triggers

## Changelog

- **v8.8.0:** Audit remediation -- fixed 14 mislabeled Stage 1 aliases, added missing defaults on Stage 3 inputs, corrected indentation, trimmed historical changelog
- Earlier versions: see repository history

## Author

**madalone**

## License

See repository for license details.
