# Wake-up guard -- Snooze/Stop with TTS & mobile

![header](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/wake-up-guard-header.jpg)

Time-based wake-up automation with bed/workshop presence conditions, TTS announcements (static or LLM-generated), one snooze, mobile push with Snooze/Stop buttons, optional Assist Satellite TTS interrupt, and a music handoff script. Fires at a configured time on selected weekdays, verifies the user is actually in bed, and runs a snooze/stop flow before handing off to wake-up music.

## How It Works

```
┌──────────────────────────┐
│  Wake-up time fires      │
│  on selected weekdays    │
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│  CONDITIONS:             │
│  - Today in active days  │
│  - Bed presence ≥ N min  │
│  - Workshop empty ≥ N min│
│  - Privacy gate passed   │
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│  Turn on switches/lights │
│  (optional)              │
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│  Prepare wake-up message │
│  (static or LLM via      │
│   dispatcher/pipeline)   │
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│  Mobile push with        │
│  Snooze/Stop buttons     │
│  (optional)              │
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│  Set TTS volume →        │
│  Play TTS announcement   │
│  → Wait for Snooze/Stop  │
│    or timeout            │
└────────────┬─────────────┘
             │
      ┌──────┼──────┐
      ▼      ▼      ▼
  ┌──────┐┌──────┐┌────────┐
  │SNOOZE││ STOP ││TIMEOUT │
  │      ││      ││        │
  │Lights││Clean ││Run     │
  │off   ││up +  ││music   │
  │Wait  ││volume││script  │
  │N min ││rest. ││+ clean │
  │Repeat││      ││up      │
  │TTS   ││      ││        │
  │(once)││      ││        │
  └──────┘└──────┘└────────┘
```

## Features

- Time-based trigger with per-weekday scheduling
- Bed presence verification with configurable minimum duration
- Workshop/living room emptiness verification (confirms user is not already up)
- Static or LLM-generated wake-up messages with dispatcher support
- Mobile push notifications with Snooze/Stop action buttons
- One snooze allowed -- second snooze treated as Stop
- Configurable snooze duration
- Wake-up music handoff via configurable script
- Switches and lights turned on at wake-up, off during snooze, back on after
- Pre/post TTS volume control with duck guard integration
- Optional Assist Satellite for TTS interrupt and confirmations
- Notification follow-me bypass during wake-up sequence (via refcount scripts)
- Privacy gate with tiered suppression
- Configurable post-TTS snooze/stop window

## Prerequisites

- Home Assistant 2024.10.0 or later
- Bed presence binary sensors (e.g. mmWave bed zone)
- A media player for TTS output
- `input_boolean` helpers for snooze and stop toggles
- (Optional) Workshop/living room presence sensors
- (Optional) A notification service for mobile push
- (Optional) An Assist Satellite entity
- (Optional) TTS speak and stop cleanup helper scripts
- (Optional) A wake-up music script

## Installation

1. Copy `wake-up-guard.yaml` to `config/blueprints/automation/madalone/`
2. Create automation: **Settings -> Automations -> Create -> Use Blueprint**

## Configuration

### Section 1 -- Schedule & presence

| Input | Default | Description |
|---|---|---|
| Active weekdays | Mon--Fri | Days on which the wake-up fires |
| Wake-up time | 07:00 | Time at which the wake-up triggers |
| Bed presence sensors | _(empty)_ | Binary sensors ON when in bed -- ALL must be on for min duration |
| Minutes in bed before wake-up | 30 | Minimum continuous bed presence before wake-up |
| Workshop presence sensors | _(empty)_ | Sensors for areas you would be in if already awake |
| Minutes workshop must be empty | 15 | Minimum continuous emptiness before wake-up |

### Section 2 -- Lights & switches

| Input | Default | Description |
|---|---|---|
| Switches to turn on | _(empty)_ | Smart plugs/lamps to turn ON at wake-up, OFF during snooze |
| Lights to turn on | _(empty)_ | Lights to turn ON at wake-up, OFF during snooze |

### Section 3 -- TTS & voice output

| Input | Default | Description |
|---|---|---|
| Media player for TTS | _(required)_ | Speaker for TTS announcements |
| Volume before TTS | 0.4 | Volume set before the announcement |
| Volume after flow completes | 0.4 | Volume restored after the full wake-up flow |
| Delay before restoring volume on Stop | 1 s | Prevents volume restore while TTS is still draining |

### Section 4 -- Wake-up message

| Input | Default | Description |
|---|---|---|
| Static wake-up message | "good morning miquel, time to get up." | Fallback message when LLM is disabled or fails |
| Generate message with LLM | false | Use conversation agent for dynamic messages |
| Use Dispatcher | true | AI dispatcher selects persona dynamically |
| Voice Assistant | "Rick" | Assist Pipeline when dispatcher is disabled |
| LLM prompt | _(long default)_ | Prompt for generating the wake-up rant |

### Section 5 -- Snooze/Stop controls

| Input | Default | Description |
|---|---|---|
| Snooze toggle | _(required)_ | `input_boolean` for snooze control |
| Stop toggle | _(required)_ | `input_boolean` for stop control |
| Wake-up music script | _(empty)_ | Script to start wake-up music on timeout |
| Snooze/Stop window | 40 s | Seconds to listen for button presses after TTS |
| Snooze duration | 7 min | Minutes to wait during snooze before repeating |

### Section 6 -- Optional integrations

| Input | Default | Description |
|---|---|---|
| Person display name | "miquel" | Name used in notification messages |
| Mobile notify service | _(empty)_ | Notify service for push with Snooze/Stop buttons |
| Assist Satellite entity | _(empty)_ | Optional satellite for TTS interrupt |
| TTS speak helper script | `script.wake_guard_tts_speak` | Script that routes TTS announcements |
| Stop cleanup helper script | `script.wake_guard_stop_cleanup` | Script for stop cleanup |
| Bypass Notification Follow-Me | true | Pause follow-me during wake-up sequence |
| Refcount claim script | `script.refcount_bypass_claim` | Bypass claim script |
| Refcount release script | `script.refcount_bypass_release` | Bypass release script |

### Section 7 -- Music

| Input | Default | Description |
|---|---|---|
| Enable pre-TTS stinger | `false` | Play chime before TTS via `tts_queue_speak` chime_path |
| Stinger agent override | `""` | Agent persona for library/compose lookups; empty = dispatched persona |
| Stinger library ID override | `""` | Explicit library ID; skips auto-resolve when set |
| Compose if not in library | `true` | Compose locally via FluidSynth when auto-resolve finds no match |
| Stinger fallback media URL | `""` | Fallback chime URL when library and compose both fail |

### Section 8 -- Infrastructure

| Input | Default | Description |
|---|---|---|
| Ducking flag entity | `input_boolean.ai_ducking_flag` | Boolean indicating audio ducking is active |
| Duck guard enabled entity | `input_boolean.ai_duck_guard_enabled` | Boolean enabling duck guard system |
| Dispatcher enabled entity | `input_boolean.ai_dispatcher_enabled` | Boolean enabling AI agent dispatcher |
| `bypass_ducking` | `false` | Skip volume ducking on other speakers during TTS |

### Section 9 -- Privacy

| Input | Default | Description |
|---|---|---|
| Privacy gate tier | t1 | Privacy tier for suppression (off / t1 / t2 / t3) |
| Privacy gate enabled | `input_boolean.ai_privacy_gate_enabled` | Privacy gate system toggle |
| Privacy gate mode | `input_select.ai_privacy_gate_mode` | Privacy gate behavior selector |
| Privacy gate person | `person.miquel` | Person entity for tier suppression lookups |

### Section 10 -- User Preferences

| Input | Default | Description |
|---|---|---|
| Enable user preference injection | `true` | Inject user preferences into wake-up prompts |
| Use preference wake time | `false` | Override static wake-up time with preference helpers |
| Weekday wake time entity | `input_datetime.ai_context_wake_time_weekday_miquel` | Weekday wake time helper |
| Weekend wake time entity | `input_datetime.ai_context_wake_time_weekend_miquel` | Weekend wake time helper |
| Alt weekday wake time entity | `input_datetime.ai_context_wake_time_alt_weekday_miquel` | Alt weekday wake time helper |
| Alt wake days | `""` | Comma-separated 3-letter day abbreviations for alt wake time |

## Technical Notes

- **Mode:** `single` / `max_exceeded: silent`
- **Trigger:** Four time triggers: static wake-up time (trigger ID: `wake_time`) plus three preference-based triggers (`pref_weekday`, `pref_weekend`, `pref_alt`). A gate condition selects the correct trigger based on `use_preference_wake_time` and the current day.
- **Weekday check:** Uses template condition mapping `now().weekday()` to abbreviation list -- no native HA condition exists for user-selected weekday lists
- **Bed presence:** Uses `last_changed` timestamps to verify actual continuous duration, not just current state
- **One snooze only:** Second snooze press is treated as Stop to prevent endless snooze cycling
- **Duck guard:** Volume set/restore calls are followed by `duck_manager_update_snapshot` when duck guard is enabled and ducking is active
- **Follow-me bypass:** Uses refcount-based claim/release scripts to prevent notification follow-me from interrupting the wake-up sequence
- **Mobile actions:** Notification uses `GUARD_SNOOZE` and `GUARD_STOP` action identifiers

## Changelog

- **v6:** Style guide compliance -- section keys renamed (AP-09), circled number display names, plural top-level keys, min_version bump, image reference fix
- **v5:** Added trigger ID, stripped redundant comments, template justification comment, runtime validation warning
- **v4:** Replaced hardcoded helper script calls with configurable inputs, added `person_display_name` input

## Author

**madalone**

## License

See repository for license details.
