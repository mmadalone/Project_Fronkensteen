# Goodnight Routine -- Bedtime Negotiator (Music Assistant)

![Image](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/goodnight_routine_music_assistant-header.jpeg)

Interactive voice-driven goodnight routine with multi-stage negotiation. Uses `assist_satellite.ask_question` for conversational YES/NO flow on a Voice PE satellite. Three stages: device shutdown, IR device control, and music/bedtime story -- each with fully editable messages that can optionally source text from `input_text` helpers for AI-refreshed content. Four music modes: single preset, multi-preset choice, dynamic input_text URI, or free-text voice search via Music Assistant.

## How It Works

```
START
  |
  v
[Agent selection: dispatcher or manual pipeline]
  |
  v
[Set TTS volume (optional)]
  |
  v
<Pre-announcement enabled?>
  |         |
 YES        NO
  |         |
  v         |
[Resolve text: helper > manual]
  |         |
  v         |
[Speak via satellite or TTS]
  |         |
  +----+----+
       |
       v
===== STAGE 1: DEVICES =====
<Enabled?>--NO-->[skip]
  |                |
 YES               |
  |                |
  v                |
[Ask question (helper or manual text)]
  |                |
  v                |
<YES?>             |
  |    |           |
 YES   NO          |
  |    |           |
  v    v           |
[Turn off] [Speak NO confirm]
[Speak YES]   |    |
  |           |    |
  +-----------+----+
       |
       v
===== STAGE 2: IR DEVICES =====
[Same ask pattern with helper/manual text]
[Run IR off scripts on YES]
       |
       v
===== STAGE 3: MUSIC / BEDTIME STORY =====
<Enabled?>--NO-->[skip]
  |                |
 YES               |
  |                |
  v                |
[Ask intro question]
  |                |
  v                |
<YES?>             |
  |    |           |
 YES   NO          |
  |    |           |
  v    v           |
[Speak  [Speak NO  |
 YES     confirm]  |
 confirm]    |     |
  |          |     |
  v          |     |
<Music mode?>|     |
  |  |  |  | |     |
  v  v  v  v |     |
[preset_single: play media_id]
[preset_multi: ask which of 3 presets]
[from_input_text: read URI from helper]
[free_text_name: ask + search MA]
  |              |     |
  +---------+----+-----+
            |
            v
<Post-announcement enabled?>
  |         |
 YES        NO
  |         |
  v         v
[Speak post-announcement]
  |         |
  +----+----+
       |
       v
END
```

## Features

- Three independently toggleable stages: Devices, IR Devices, Music/Bedtime Story
- Every question, YES confirm, and NO confirm message is editable
- Optional `input_text` helper sourcing for all messages (for AI-refreshed content)
- Pre- and post-announcement messages (helper or manual)
- Four music modes: preset_single, preset_multi (up to 3 labeled presets), from_input_text, free_text_name
- Music Assistant voice search in free_text_name mode
- AI dispatcher integration for dynamic persona selection
- Satellite or TTS speaker for pre/post announcements (configurable)
- Volume control with duck guard integration
- Uses `assist_satellite.ask_question` for natural conversational flow

## Prerequisites

- Home Assistant **2024.10.0** or newer
- Assist Satellite (Voice PE) entity
- Music Assistant integration (for Stage 3)
- `pyscript.agent_dispatch` service (agent dispatcher)
- Duck guard system (optional)

## Installation

1. Copy `goodnight_routine_music_assistant.yaml` to `config/blueprints/script/madalone/`
2. Create script: **Settings > Automations & Scenes > Scripts > Add > Use Blueprint**

## Configuration

<details>
<summary><strong>Section 1 -- Core Settings</strong></summary>

| Input | Default | Description |
|---|---|---|
| `use_dispatcher` | `true` | AI dispatcher selects persona dynamically |
| `conversation_agent` | `Rick - Bedtime` | Assist Pipeline (when dispatcher disabled) |
| `music_assist_satellite` | _(empty)_ | Assist Satellite for all questions |
| `tts_media_player` | _(empty)_ | Speaker for pre/post TTS announcements |
| `use_satellite_for_pre_post` | `true` | Use satellite for pre/post TTS (duck-friendly) |
| `tts_output_volume` | `0.0` | TTS volume (0 = use current) |
| `off_targets` | `{}` | Devices to turn off in Stage 1 |
| `ir_off_scripts` | `[]` | IR off scripts for Stage 2 |

</details>

<details>
<summary><strong>Section 2 -- Pre-Announcement</strong></summary>

| Input | Default | Description |
|---|---|---|
| `pre_tts_use_helper` | `false` | Source text from input_text helper |
| `pre_tts_helper` | _(empty)_ | input_text entity for AI-generated text |
| `pre_tts_use_manual` | `true` | Use manual text field |
| `pre_tts_message` | _(empty)_ | Manual pre-announcement message |

</details>

<details>
<summary><strong>Section 3 -- Stage 1: Devices</strong></summary>

| Input | Default | Description |
|---|---|---|
| `enable_devices_question` | `true` | Enable Stage 1 |
| `devices_question_text` | `Do you want me to switch off the selected devices?` | Manual question text |
| `devices_use_helper_question` | `false` | Source question from helper |
| `devices_question_helper` | _(empty)_ | input_text for question |
| `devices_yes_confirm_message` | `Good choice. Less power wasted...` | YES confirm text |
| `devices_use_helper_yes` | `false` | Source YES from helper |
| `devices_yes_helper` | _(empty)_ | input_text for YES confirm |
| `devices_no_confirm_message` | `Fine, leaving them on...` | NO confirm text |
| `devices_use_helper_no` | `false` | Source NO from helper |
| `devices_no_helper` | _(empty)_ | input_text for NO confirm |

</details>

<details>
<summary><strong>Section 4 -- Stage 2: IR Devices</strong></summary>

| Input | Default | Description |
|---|---|---|
| `enable_ir_question` | `true` | Enable Stage 2 |
| `ir_question_text` | `Do you want me to switch off the IR-controlled devices...?` | Manual question |
| `ir_use_helper_question` | `false` | Source question from helper |
| `ir_question_helper` | _(empty)_ | input_text for question |
| `ir_yes_confirm_message` | `Got it. Sending the IR commands...` | YES confirm |
| `ir_use_helper_yes` / `ir_yes_helper` | `false` / _(empty)_ | Helper for YES |
| `ir_no_confirm_message` | `Alright, leaving the IR devices as they are.` | NO confirm |
| `ir_use_helper_no` / `ir_no_helper` | `false` / _(empty)_ | Helper for NO |

</details>

<details>
<summary><strong>Section 5 -- Stage 3: Music / Bedtime Story</strong></summary>

| Input | Default | Description |
|---|---|---|
| `enable_music_question` | `true` | Enable Stage 3 |
| `music_intro_question_text` | `Would you like some music or maybe a bedtime story?` | Intro question |
| `music_use_helper_intro` / `music_intro_question_helper` | `false` / _(empty)_ | Helper for intro |
| `music_yes_confirm_message` | `Excellent. Let me get something playing...` | YES confirm |
| `music_no_confirm_message` | `Alright, no music or stories...` | NO confirm |
| `music_mode` | `preset_single` | preset_single / preset_multi / from_input_text / free_text_name |
| `music_player` | _(empty)_ | Music Assistant player entity |
| `music_volume` | `0.15` | Playback volume (0 = skip) |
| `music_media_type` | `auto` | auto / playlist / album / track / artist / radio |
| `music_media_id` | _(empty)_ | Media ID for preset_single mode |
| `music_media_input_text` | _(empty)_ | input_text entity for from_input_text mode |
| `music_question_text` | `What do you want me to play...?` | Secondary question for multi/free_text |
| `music_preset_1_label` / `music_preset_1_media_id` | _(empty)_ | Preset 1 (preset_multi mode) |
| `music_preset_2_label` / `music_preset_2_media_id` | _(empty)_ | Preset 2 |
| `music_preset_3_label` / `music_preset_3_media_id` | _(empty)_ | Preset 3 |

</details>

<details>
<summary><strong>Section 6 -- Post-Announcement</strong></summary>

| Input | Default | Description |
|---|---|---|
| `post_tts_use_helper` | `false` | Source text from helper |
| `post_tts_helper` | _(empty)_ | input_text for post-announcement |
| `post_tts_use_manual` | `true` | Use manual text |
| `post_tts_message` | _(empty)_ | Manual post-announcement message |

</details>

<details>
<summary><strong>Section 7 -- Infrastructure</strong></summary>

| Input | Default | Description |
|---|---|---|
| `ducking_flag` | `input_boolean.ducking_flag` | Ducking active flag |
| `duck_guard_enabled` | `input_boolean.ai_duck_guard_enabled` | Duck guard toggle |
| `dispatcher_enabled` | `input_boolean.ai_dispatcher_enabled` | Dispatcher toggle |

</details>

## Technical Notes

- **Mode:** `single` / `max_exceeded: silent`
- **Helper priority:** When both helper and manual are enabled, helper takes priority when not empty
- **Stage 2-3 coupling fix (v2.0.0):** IR NO no longer blocks music -- stages are fully independent
- **Satellite vs TTS:** Pre/post announcements can use either `assist_satellite.announce` (triggers ducking) or `tts.speak` (direct to media player)
- **Music mode branching:** All four modes share a single deduplicated playback block at the end

## Changelog

- **v2.0.0:** Full compliance rebuild -- collapsible sections, aliases on every step, continue_on_error, default guards, deduplicated music playback, fixed Stage 2-3 coupling bug, source_url + min_version + header image

## Author

**madalone**

## License

See repository for license details.
