# Escalating Wake-Up Guard -- Inverted Presence

![header](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/escalating_wakeup_guard-header.jpg)

Multi-stage escalation alarm that uses inverted presence logic: instead of checking if you are in bed, it checks whether you have gotten up by monitoring non-bedroom activity sensors. No activity detected = still asleep = escalate further. Designed as Layer 2 behind `llm_alarm.yaml`. Volume and brightness interpolate smoothly from start to end values across a configurable number of stages (1-6). Lights, music, and LLM messages are all optional.

## How It Works

```
┌─────────────────────────────────────┐
│  Guard time fires                   │
│  (e.g. 07:15 -- after Layer 1)      │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  Conditions:                        │
│  ├─ Active weekday?                │
│  └─ Privacy gate?                  │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  Pre-loop activity check            │
│  └─ Already awake? -> abort         │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  Repeat loop (1 to N stages):      │
│  ├─ Interpolate volume + brightness │
│  ├─ Set TTS volume                  │
│  ├─ Turn on lights (optional)       │
│  ├─ Speak message (static or LLM)   │
│  ├─ Start music at stage N (opt.)   │
│  ├─ Flash lights on final (opt.)    │
│  ├─ Send mobile notification (opt.) │
│  ├─ Wait for activity or stop       │
│  │   └─ Activity detected -> break  │
│  │   └─ Stop toggle ON -> break     │
│  └─ Inter-stage lookback check      │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  Cleanup:                           │
│  ├─ Restore volume                  │
│  ├─ Reset stop toggle               │
│  └─ Run cleanup script (optional)   │
└─────────────────────────────────────┘
```

## Features

- Inverted presence detection -- monitors non-bedroom sensors for activity
- Configurable 1-6 escalation stages with smooth volume and brightness interpolation
- Per-tier LLM message generation (first, middle, final stages) with static fallbacks
- Placeholder tokens in prompts and messages: `{STAGE}`, `{TOTAL}`, `{STAGE_DELAY}`
- Activity lookback window -- sensors that recently turned OFF still count as activity
- Minimum active presence duration -- brief sensor blips do not cancel escalation
- Optional lights with brightness ramp and final-stage flash cycling
- Optional music playback starting at a configurable stage
- Mobile notification with STOP button (no snooze -- this IS the snooze escalation)
- Stop toggle for immediate cancellation from HA UI or other automations
- AI agent dispatcher or manual pipeline selection
- LLM context entity injection for richer wake-up messages
- Privacy gate with per-feature override (T1/T2/T3 tiers)
- Duck guard snapshot updates after volume changes
- Volume restore and toggle reset on all exit paths

## Prerequisites

- Home Assistant 2024.6.0+
- Binary sensors outside the bedroom (motion, presence, door sensors)
- A media player for TTS output
- An `input_boolean` for the stop toggle
- (Optional) Light entities for brightness escalation
- (Optional) A conversation agent for LLM-generated messages
- pyscript services: `agent_dispatch`, `tts_queue_speak`, `agent_whisper`

## Installation

1. Copy `escalating_wakeup_guard.yaml` to `config/blueprints/automation/madalone/`
2. Create automation: **Settings -> Automations -> Create -> Use Blueprint**

## Configuration

<details>
<summary><strong>Section 1 -- Schedule</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| Active weekdays | Mon-Fri | Days on which the guard fires. |
| Guard time | `07:15:00` | When escalation begins. Set 5-10 min after primary alarm. |

</details>

<details>
<summary><strong>Section 2 -- Activity Sensors</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| Activity sensors | `[]` | Non-bedroom binary sensors. ANY recent activity = awake. |
| Activity lookback | `5` min | How recently a sensor must have been ON to count. |
| Minimum active presence | `0` min | How long a sensor must stay ON to count as genuine activity. |

</details>

<details>
<summary><strong>Section 3 -- TTS & Output</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| TTS output player | _(required)_ | Media player for TTS and volume control. |

</details>

<details>
<summary><strong>Section 4 -- Escalation</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| Number of stages | `4` | Escalation stages (1-6). |
| Delay between stages | `10` min | Wait time between stages (activity monitored). |
| Start volume | `0.30` | TTS volume for first stage. |
| End volume | `1.0` | TTS volume for final stage. |
| Lights | `[]` | Lights to ramp up during escalation. |
| Start brightness | `50` | Brightness for first stage (0-255). |
| End brightness | `255` | Brightness for final stage (0-255). |
| Flash on final stage | `true` | Rapidly flash lights on/off during final stage. |
| Flash count | `10` | Number of on/off flash cycles. |
| Music script | _(empty)_ | Script to start music playback. |
| Start music at stage | `3` | Stage number at which music begins (0 = never). |

</details>

<details>
<summary><strong>Section 5 -- Messages</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| First stage message | `Good morning. Time to get up.` | Static first wake-up message. |
| Use LLM for first stage | `false` | Generate first-stage message via conversation agent. |
| LLM prompt -- first stage | _(default)_ | Prompt for first stage. Supports `{STAGE}`, `{TOTAL}`, `{STAGE_DELAY}`. |
| Middle stage message | `You are still in bed...` | Static message for middle stages. Supports placeholders. |
| Use LLM for middle stages | `false` | Generate middle messages via conversation agent. |
| LLM prompt -- middle stages | _(default)_ | Prompt for middle stages. Supports placeholders. |
| Final stage message | `Last warning...` | Static last-resort message. Supports placeholders. |
| Use LLM for final stage | `false` | Generate final message via conversation agent. |
| LLM prompt -- final stage | _(default)_ | Prompt for final stage. Supports placeholders. |

</details>

<details>
<summary><strong>Section 6 -- Voice Assistant & LLM</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| Use Dispatcher | `true` | Let the dispatcher select the persona dynamically. |
| Voice Assistant | `Rick` | Assist Pipeline when dispatcher is disabled. |
| Context entities | `[]` | Sensor entities for richer LLM context (weather, temp, etc.). |

</details>

<details>
<summary><strong>Section 7 -- Mobile Notifications</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| Notification service | _(empty)_ | `notify.mobile_app_<device>`. Leave empty to skip. |
| Mobile stop action ID | `ESCALATION_STOP` | Action identifier for the STOP button. |

</details>

<details>
<summary><strong>Section 8 -- Cleanup & Restore</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| Restore volume | `0.4` | Volume to restore after escalation ends. |
| Cleanup script | _(empty)_ | Script to run after escalation (stop music, reset lights). |
| Stop toggle | _(required)_ | `input_boolean` for immediate cancellation. Reset to OFF on exit. |

</details>

<details>
<summary><strong>Section 9 -- Infrastructure</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| Ducking flag entity | `input_boolean.ai_ducking_flag` | Audio ducking active flag. |
| Duck guard enabled | `input_boolean.ai_duck_guard_enabled` | Duck guard system toggle. |
| Dispatcher enabled | `input_boolean.ai_dispatcher_enabled` | AI agent dispatcher toggle. |

</details>

<details>
<summary><strong>Section 10 -- Privacy</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| Privacy gate tier | `t1` | Privacy tier (off/T1/T2/T3). |
| Privacy gate enabled | `input_boolean.ai_privacy_gate_enabled` | Privacy gate toggle. |
| Privacy gate mode | `input_select.ai_privacy_gate_mode` | Mode selector. |
| Privacy gate person | `person.miquel` | Person entity for suppression lookups. |

</details>

<details>
<summary><strong>Section 11 -- User Preferences</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| Enable user preferences | `true` | Inject user preferences into wake-up escalation prompts. |
| Use preference wake time | `false` | Override static guard time with user's preference wake time helpers. |
| Weekday wake time entity | `input_datetime.ai_context_wake_time_weekday_miquel` | Input datetime for weekday wake time. |
| Weekend wake time entity | `input_datetime.ai_context_wake_time_weekend_miquel` | Input datetime for weekend wake time. |
| Alt weekday wake time entity | `input_datetime.ai_context_wake_time_alt_weekday_miquel` | Input datetime for alternate weekday wake time. |
| Alt wake days | `""` | Comma-separated day abbreviations using the alt wake time. |

</details>

## Technical Notes

- **Mode:** `restart` (stored traces: 15)
- Volume and brightness are interpolated linearly: `start + (end - start) * (stage - 1) / (total - 1)`
- Placeholder tokens `{STAGE}`, `{TOTAL}`, `{STAGE_DELAY}` use non-Jinja syntax to avoid premature evaluation at variable-resolution time
- The minimum active presence filter applies to the pre-loop check, inter-stage lookback, and the `wait_for_trigger` gate
- Music starts once at the configured stage and keeps playing through subsequent stages
- All light, music, notification, and volume calls use `continue_on_error: true`
- The stop toggle is checked during each inter-stage wait and immediately breaks the loop

## Changelog

- **v10:** Minimum active presence duration -- prevents brief sensor blips from cancelling escalation
- **v9:** Fixed Jinja placeholder bug -- replaced `{{ stage }}` with `{STAGE}` tokens
- **v8:** Plural top-level keys, collapsed sections, DRY comments
- **v7:** Wired up llm_context_entities (was declared but unused)
- **v6:** Native condition:time for weekday check, removed decorative banners, continue_on_error on flash
- **v5:** Missing inner aliases, removed decorative input banners, default guard on weekday condition
- **v4:** continue_on_error on non-critical calls, aliases on flash delays

## Author

**madalone**

## License

See repository for license details.
