# Wake-Up Alarm -- LLM Context

![header](https://raw.githubusercontent.com/mmadalone/HA-Master-Repo/main/images/header/llm_alarm-header.jpeg)

Time-based alarm that fires on selected weekdays, optionally generates a wake-up message via a conversation agent with live sensor context, speaks it over TTS, and supports one snooze cycle with mobile notification controls. After the snooze/stop window expires, an optional music script launches post-alarm audio. Volume is set before the announcement and restored on every exit path. Designed as Layer 1 of a two-layer wake-up system (pair with `escalating_wakeup_guard.yaml` as Layer 2).

## How It Works

```
┌─────────────────────────────────────┐
│  Wake-up time fires                 │
│  (e.g. 07:00)                       │
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
│  Validate required TTS inputs       │
│  Agent selection (dispatcher/manual)│
│  Turn on wake-up lights (optional)  │
│  Set TTS volume                     │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  Generate wake message:             │
│  ├─ LLM path (if enabled)          │
│  │   ├─ Prompt + meta + context    │
│  │   └─ Fallback to static msg     │
│  └─ Static message (default)       │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  Send mobile notification           │
│  (Snooze + Stop buttons)            │
│  Speak wake-up message via TTS      │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  Wait for Snooze/Stop:              │
│  ├─ Stop -> restore volume, exit    │
│  ├─ Snooze -> wait N min, repeat    │
│  │   └─ Stop after snooze -> exit   │
│  │   └─ Timeout -> play music       │
│  └─ Timeout -> play music           │
└─────────────────────────────────────┘
```

## Features

- Time-based alarm with configurable weekday selection
- Optional LLM-generated wake-up message with live sensor context
- LLM context includes: calendar events, priority emails, sensor readings, wake-up time, snooze window
- Target word count sized to the snooze/stop listening window
- Static fallback message when LLM is disabled or fails
- Mobile notification with Snooze and Stop action buttons
- One snooze cycle with configurable duration (1-60 minutes)
- Post-alarm music script on all non-stop exit paths
- TTS volume set before announcement and restored on every exit path
- Wake-up lights/switches activation
- AI agent dispatcher or manual pipeline selection
- Privacy gate with per-feature override (T1/T2/T3 tiers)
- Duck guard snapshot updates after volume changes
- Self-awareness whisper after delivery
- Input validation -- aborts early if required TTS inputs are missing

## Prerequisites

- Home Assistant 2024.6.0+
- A media player for TTS output
- (Optional) Mobile app with notification action support
- (Optional) A conversation agent for LLM wake-up messages
- (Optional) Light/switch entities for wake-up lights
- pyscript services: `agent_dispatch`, `tts_queue_speak`, `agent_whisper`

## Installation

1. Copy `llm_alarm.yaml` to `config/blueprints/automation/madalone/`
2. Create automation: **Settings -> Automations -> Create -> Use Blueprint**

## Configuration

<details>
<summary><strong>Section 1 -- Schedule</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| Active weekdays | Mon-Fri | Days on which the alarm fires. |
| Wake-up time | `07:00:00` | Time the alarm fires. |
| Wake-up lights/switches | `[]` | Entities to turn on when the alarm starts. |

</details>

<details>
<summary><strong>Section 2 -- TTS & Audio</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| TTS output player | _(required)_ | Media player for the wake-up announcement. |
| TTS volume before | `0.4` | Volume level for TTS before the announcement. |
| TTS volume after | `0.4` | Volume to restore after the flow completes. |
| Static wake-up message | `good morning, time to get up.` | Fallback message when LLM is disabled or fails. |

</details>

<details>
<summary><strong>Section 3 -- LLM Wake-Up Message</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| Use LLM for wake-up | `false` | Generate the message via a conversation agent. |
| Use Dispatcher | `true` | Let the dispatcher select the persona dynamically. |
| Voice Assistant | `Rick` | Assist Pipeline when dispatcher is disabled. |
| LLM wake-up prompt | _(empty)_ | Prompt for the conversation agent. Meta data appended automatically. |
| LLM context entities | `[]` | Extra entities for sensor context (temperature, persons, etc.). |

</details>

<details>
<summary><strong>Section 4 -- Mobile Notifications</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| Notify service | _(empty)_ | `notify.mobile_app_<device>`. Leave empty to skip. |
| Mobile Snooze action ID | `GUARD_SNOOZE` | Action ID for the Snooze button. |
| Mobile Stop action ID | `GUARD_STOP` | Action ID for the Stop button. |

</details>

<details>
<summary><strong>Section 5 -- Snooze & Music</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| Snooze/Stop listening window | `40` s | Seconds to watch for Snooze/Stop actions after TTS. |
| Snooze minutes | `7` min | Wait time after Snooze before repeating. |
| Wake-up music script | _(empty)_ | Script to call when the flow completes (no stop). |

</details>

<details>
<summary><strong>Section 6 -- Infrastructure</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| Ducking flag entity | `input_boolean.ducking_flag` | Audio ducking active flag. |
| Duck guard enabled | `input_boolean.ai_duck_guard_enabled` | Duck guard system toggle. |
| Dispatcher enabled | `input_boolean.ai_dispatcher_enabled` | AI agent dispatcher toggle. |

</details>

<details>
<summary><strong>Section 7 -- Privacy</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| Privacy gate tier | `t2` | Privacy tier (off/T1/T2/T3). |
| Privacy gate enabled | `input_boolean.ai_privacy_gate_enabled` | Privacy gate toggle. |
| Privacy gate mode | `input_select.ai_privacy_gate_mode` | Mode selector. |
| Privacy gate person | `miquel` | Person name for suppression lookups. |

</details>

## Technical Notes

- **Mode:** `single` (silent on overflow)
- The notification fires BEFORE TTS intentionally -- it is a brief heads-up, not a transcript
- The notification uses a static message by design (not the LLM output)
- LLM prompt meta includes: configured wake-up time, snooze window duration, target word count (window * 2)
- LLM context automatically includes `ai_calendar_today_summary` and `ai_email_priority_count`
- Defensive LLM response traversal: any intermediate key could be None if the call errored
- `| trim` on LLM response extraction guards against whitespace-only replies
- The music script guard is duplicated across exit paths (HA choose branches cannot share sub-sequences)
- `wait.trigger.event.data` is explicitly checked with `is defined` guard on all three wait evaluations
- Duck guard snapshot updates occur after every `media_player.volume_set` call
- Volume is restored on all exit paths: Stop (first window), Stop (after snooze), music (first window), music (after snooze)

## Changelog

- **v12:** Added `| default()` guards to `v_wakeup_time` and `v_post_tts_timeout` in LLM prompt
- **v11:** Added `v_tts_volume_before` and `v_tts_volume_after` to variables block
- **v10:** Added `v_tts_engine` and `v_tts_output_player` to variables, runtime guard on unconfigured TTS, trim on sensor_context
- **v9:** Migrated conversation agent to native `conversation_agent` selector, renamed input
- **v8:** `v_tts_message` in variables, `| trim` on LLM response, `| tojson` on tts_options
- **v7:** Unicode section numbering, `event.data is defined` guard, `source_url`, trimmed changelog
- **v6:** Empty-list guards on `wakeup_entities` and `music_script`, variables parity

## Author

**madalone**

## License

See repository for license details.
