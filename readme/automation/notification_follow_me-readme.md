# Notification Follow-Me (v3.20.0)

![header](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/notification-follow-me-header.jpeg)

When a messaging notification arrives on your phone (WhatsApp, Signal, SMS, or any selected app), this blueprint determines which room you are in via FP2 presence sensors, routes to the nearest voice satellite, and has a conversation agent summarize the message -- completely hands-free. Uses the Android Companion App's `last_notification` sensor as the data source. Includes blocked-sender filtering, cooldown, quiet hours, DND respect, media message detection, unread message reminders, agent randomization, contact history, ringer-aware volume control, and multi-player ducking.

## How It Works

```
┌──────────────────────────┐
│  Notification sensor     │
│  state changed           │
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│  GATES:                  │
│  - Master toggle ON      │
│  - Not blocked sender    │
│  - Not self/outgoing     │
│  - Not junk pattern      │
│  - Not emoji reaction    │
│  - Cooldown elapsed      │
│  - DND inactive          │
│  - Quiet hours inactive  │
│  - Privacy gate passed   │
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│  Resolve presence →      │
│  target satellite        │
│  (or fallback mode)      │
└────────────┬─────────────┘
             │
       ┌─────┴──────┐
       ▼            ▼
  ┌─────────┐  ┌──────────┐
  │ Satellite│  │ Fallback │
  │ found   │  │ (push or │
  │         │  │  silent)  │
  └────┬────┘  └──────────┘
       │
       ▼
┌──────────────────────────┐
│  Media msg? → short TTS  │
│  or drop or LLM summary  │
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│  Build LLM prompt:       │
│  - Notification data     │
│  - Sender alias          │
│  - Direct address detect │
│  - Contact history       │
│  - Thread context        │
│  - Guardrails            │
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│  conversation.process →  │
│  TTS announcement        │
│  (with ducking +         │
│   volume control)        │
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│  Reminder loop           │
│  (if enabled)            │
│  - Re-announce unread    │
│  - Escalating urgency    │
│  - Exit on phone use /   │
│    dismiss / gates fail  │
└──────────────────────────┘
```

## Features

- Presence-based routing via parallel-array sensor-to-satellite mapping
- LLM-powered notification summarization with configurable prompt
- Direct-address detection -- agent reacts personally when named in the message
- Agent randomizer support -- optional script overrides agent + TTS at runtime
- Sender alias map for friendly display names (e.g. "Mare" -> "Mum")
- User pet name awareness for the LLM
- Blocked contacts filtering (comma-separated, case-insensitive)
- Self/outgoing message filtering
- Junk notification pattern suppression
- Emoji reaction drop filter
- Media message handling (drop / short TTS / LLM summary)
- Per-sender cooldown with `input_datetime` + `input_text` helpers
- Burst message handling (thread_aware / debounce / catch_up modes)
- DND sensor gate + time-based quiet hours window
- Ringer mode volume control (normal / vibrate / silent)
- TTS output volume with satellite volume snapshot for parallel safety
- Multi-player ducking with refcount for parallel runs
- Duck guard integration
- Expressive text interpretation (laughter, emoji, elongation)
- ElevenLabs v3 audio tag density control
- Unread message reminders with escalating urgency
- Notification ledger for bundled multi-sender reminders
- Long-tail reminder phase with configurable interval
- Reminder ceiling (max total reminder time)
- Presence re-trigger modes (continue / re-escalate / single burst)
- Phone interactive sensor for reminder exit detection
- App-aware R3c gate (evicts only the app the user is viewing)
- Last removed notification sensor for dismissal detection
- Reminder loop watchdog with dead-man switch
- Loop ownership guard via context ID (prevents zombie parallel loops)
- Per-contact message history via L2 memory (pyscript integration)
- LLM guardrails (sender name rules, perspective, emoji suppression, outgoing guard)
- Thread format context rules
- Privacy gate with tiered suppression
- Bypass follow-me and ducking via refcount scripts
- Dispatcher / pipeline-based agent selection
- Fallback to mobile push or silent when no presence detected
- Extra context entities for richer LLM prompts

## Prerequisites

- Home Assistant 2024.10.0 or later
- Android Companion App with `last_notification` sensor (Notification Listener permission + Allow List)
- FP2 presence sensors (one per monitored zone)
- Voice satellites / media players (one per zone, matching sensor order)
- An LLM conversation agent (or AI dispatcher)
- An `input_boolean` for the master enable toggle
- An `input_datetime` for cooldown tracking
- (Optional) Additional helpers for reminders, ducking, volume snapshots, contact history

## Installation

1. Copy `notification_follow_me.yaml` to `config/blueprints/automation/madalone/`
2. Create automation: **Settings -> Automations -> Create -> Use Blueprint**

## Configuration

### Section 1 -- Core setup

| Input | Default | Description |
|---|---|---|
| Notification sensor | _(required)_ | Android Companion App `last_notification` sensor |
| Master enable toggle | _(required)_ | `input_boolean` to enable/disable the automation |
| Notification master gate | `input_boolean.ai_notifications_master_enabled` | Global notification gate -- suppresses all notification automations when OFF |
| Voice Assistant | "Rick" | Assist Pipeline for notification summary (overridden by dispatcher) |
| LLM summarization prompt | _(long default)_ | Instructions for how the AI summarizes notifications |
| Direct-address prompt override | _(long default)_ | Prompt used when sender addresses the agent by name |
| Include group chat context | false | Include group/direct message status in LLM prompt |
| Extra context sensors | _(empty)_ | Additional entities whose states are passed to the LLM |
| User pet names | _(empty)_ | Comma-separated pet names the LLM recognizes as referring to the user |

### Section 2 -- Presence routing

| Input | Default | Description |
|---|---|---|
| Presence sensors | _(empty)_ | Binary sensors in priority order (first occupied wins) |
| Target satellites | _(empty)_ | Media players paired with sensors (same order) |
| No-presence fallback | silent | What to do when no sensor is active (mobile_push or silent) |
| Mobile notify service | _(empty)_ | Notify service for mobile push fallback |

### Section 3 -- Notification filtering

| Input | Default | Description |
|---|---|---|
| Blocked contacts | _(empty)_ | Comma-separated sender names to suppress |
| Your name(s) | _(empty)_ | Names identifying outgoing messages to filter |
| Sender alias map | _(empty)_ | Key=Value pairs mapping raw names to friendly names |
| Cooldown (seconds) | 60 | Minimum seconds between announcements |
| Last announced helper | _(empty)_ | `input_datetime` for cooldown tracking |
| Message character cap | 500 | Max characters sent to the LLM |
| Junk patterns | _(empty)_ | Substrings that identify system notifications to suppress |
| Last announced sender helper | _(empty)_ | `input_text` for per-sender cooldown |
| Last processed post_time helper | _(empty)_ | `input_text` for dedup of attribute-only re-fires |
| Burst handling mode | thread_aware | How to handle rapid bursts (thread_aware / debounce / catch_up) |
| Debounce window | 15 s | Settle time for debounce mode |
| Burst batch tail window | 15 s | Tail wait for catch_up mode |
| Media message behavior | short_tts | How to handle media messages (drop / short_tts / llm_summary) |
| Drop emoji reactions | true | Silently drop reaction notifications |

### Section 4 -- Quiet hours & DND

| Input | Default | Description |
|---|---|---|
| DND sensor | _(empty)_ | Phone DND sensor -- suppresses when not "off" |
| Enable quiet hours | false | Enable time-based quiet window |
| Quiet hours start | 23:00 | Start of quiet period |
| Quiet hours end | 07:00 | End of quiet period |

### Section 5 -- TTS configuration

| Input | Default | Description |
|---|---|---|
| Use announce mode | false | Send `announce: true` with TTS calls |
| TTS output volume | 0.0 | Fixed volume before TTS (0 = use current) |
| Satellite volume snapshot helper | _(empty)_ | `input_text` for parallel-safe volume snapshots |
| Expressive sensitivity | moderate | How aggressively LLM interprets informal text |
| Expressive patterns | _(cultural defaults)_ | Pattern=meaning cheat sheet for the LLM |
| Audio tag density | moderate | ElevenLabs v3 audio tag frequency |

### Section 6 -- Ringer mode volume control

| Input | Default | Description |
|---|---|---|
| Ringer mode sensor | _(empty)_ | Phone ringer mode sensor (normal/vibrate/silent) |
| Quiet volume | 0.15 | Volume when phone is in vibrate mode |
| Volume restore delay | 8 s | Seconds to wait before restoring original volume |

### Section 7 -- Duck guard

| Input | Default | Description |
|---|---|---|
| Ducking flag | _(empty)_ | `input_boolean` signaling active duck cycle |
| Duck guard enabled | `input_boolean.ai_duck_guard_enabled` | Boolean enabling duck guard system |

### Section 8 -- Unread message reminders

| Input | Default | Description |
|---|---|---|
| Enable reminders | false | Re-announce unread messages at intervals |
| Reminder interval | 5 min | Minutes between fast-cadence reminders |
| Max reminder repeats | 3 | Max fast-cadence reminders before switching to long-tail |
| Reminder LLM prompt | _(long default)_ | Prompt for escalating reminder tone |
| Reminder read mode | paraphrase | How agent delivers content (paraphrase / verbatim / progressive) |
| Phone interactive sensor | _(empty)_ | Binary sensor for phone screen activity |
| Phone interactive threshold | 2 min | Sustained phone use before reminders stop |
| Last used app sensor | _(empty)_ | Enables app-aware R3c gate |
| Notification app packages | "com.whatsapp,org.thoughtcrime.securesms" | Package names for app-aware eviction |
| Last removed notification sensor | _(empty)_ | Notification dismissal detection |
| Long-tail interval | 15 min | Slow-phase reminder interval (0 = disable) |
| Reminder ceiling | 240 min | Max total reminder time |
| Presence re-trigger mode | single_burst | Behavior on room change during reminders |
| Notification ledger | _(empty)_ | `input_text` for unread notification index |
| Reminder loop flag | _(empty)_ | `input_boolean` tracking active loop |
| Reminder loop watchdog | _(empty)_ | `input_datetime` dead-man switch |
| Reminder loop owner | _(empty)_ | `input_text` for context ID ownership |
| Bundled reminder prompt | _(long default)_ | Prompt for multi-sender reminder bundles |

### Section 9 -- Agent selection

| Input | Default | Description |
|---|---|---|
| Use Dispatcher | true | AI dispatcher selects persona dynamically |
| Fallback persona name | _(empty)_ | Human-readable name when dispatcher returns no name |
| Bypass Follow-Me | false | Pause follow-me during processing |
| Refcount claim script | `script.refcount_bypass_claim` | Bypass claim script |
| Refcount release script | `script.refcount_bypass_release` | Bypass release script |

### Section 10 -- Privacy

| Input | Default | Description |
|---|---|---|
| Privacy gate tier | t2 | Privacy tier for suppression (off / t1 / t2 / t3) |
| Privacy gate enabled | `input_boolean.ai_privacy_gate_enabled` | Privacy gate system toggle |
| Privacy gate mode | `input_select.ai_privacy_gate_mode` | Privacy gate behavior selector |
| Privacy gate person | `person.miquel` | Person entity for tier suppression lookups |

### Section 11 -- Contact history

| Input | Default | Description |
|---|---|---|
| Enable contact history | false | Fetch/log per-sender message history from L2 memory |
| Context window | 24h | How far back to look for previous messages |
| Storage mode | both | What to persist (both / summary_only / text_only) |

### Section 12 -- LLM guardrails

| Input | Default | Description |
|---|---|---|
| Agent self-awareness prompt | _(default)_ | How agent handles "the AI" references |
| Sender name + perspective rules | _(default)_ | Listener perspective enforcement |
| Speaker context (direct-address) | _(default)_ | Reminds agent it speaks through a speaker |
| Emoji & laughter suppression | _(default)_ | Prevents literal emoji/laughter reproduction |
| Contact history intro | _(default)_ | Introduces contact history block to LLM |
| Thread context intro | _(default)_ | Introduces conversation thread block |
| Thread format rules | _(default)_ | Explains "You:" prefix in threads |
| Outgoing message guard | _(default)_ | Detects and skips outgoing action notifications |

### Section 13 -- Music (pre-TTS stinger)

| Input | Default | Description |
|---|---|---|
| Enable pre-TTS stinger | false | Play a chime/stinger before TTS; swaps delivery to `tts_queue_speak` |
| Stinger agent override | _(empty)_ | Agent persona for library/compose lookups (empty = dispatched persona) |
| Stinger library ID override | _(empty)_ | Explicit music library ID; skips auto-resolve and compose |
| Compose if not in library | true | Compose locally via FluidSynth when library lookup fails |
| Stinger fallback media URL | _(empty)_ | Fallback chime file URL when both library and compose fail |

### Section 14 -- Infrastructure

| Input | Default | Description |
|---|---|---|
| Dispatcher enabled entity | `input_boolean.ai_dispatcher_enabled` | Boolean that enables the AI agent dispatcher |

### Section 15 -- User Preferences

| Input | Default | Description |
|---|---|---|
| Enable notification threshold | false | Gate TTS against user's notification threshold preference (`input_text.ai_context_user_notify_threshold_{user}`) |
| `bypass_ducking` | `false` | Skip volume ducking on other speakers during TTS |
| Notification priority level | 3 | TTS queue priority (0=emergency … 4=ambient); used for queue ordering and threshold gating |

## Technical Notes

- **Mode:** `parallel` / `max: 10`
- **Trigger:** State change on the notification sensor
- **Parallel arrays:** Presence sensors and target satellites must be in matching order
- **Cooldown:** Per-sender when `last_announced_sender_helper` is configured; time-only otherwise
- **Reminder loop:** Unified loop with ownership guard via context ID -- prevents zombie loops from `mode: parallel` race conditions
- **Watchdog:** Dead-man switch on `input_datetime`; if stale beyond 2x the reminder interval, a new run can reclaim ownership
- **Ledger format:** CSV string in `input_text` (max 255 chars): `sender|epoch|app` per entry
- **Duck refcount:** Only the last run to finish restores volumes -- prevents premature unduck during burst messages
- **R3c gate:** App-aware variant evicts only the app the user is viewing, not all reminders
- **Thread context:** LLM sees recent messages from the phone notification stack for conversational context

## Changelog

- **v3.20.0:** Eliminate duplicate announcements under `mode: parallel` -- trigger `to:` filter, context_id claim-check, post-debounce TOCTOU race guard, cooldown timestamp written before TTS
- **v3.19.0:** Fix repeated announcements -- post_time dedup gate; HA startup trigger clears stale reminder state; all tts.speak calls migrated to tts_queue_speak
- **v3.18.0:** Watchdog loop recovery fix -- context ID ownership guard prevents zombie loops; second heartbeat after TTS keeps watchdog fresh
- **v3.17.0:** Agent randomizer support -- optional script overrides agent + TTS; "called by name trumps random" detection; alias-aware matching
- **v3.16.0:** App-aware R3c gate -- evicts only the app being viewed; new `last_used_app_sensor` and `notification_app_packages` inputs

## Author

**madalone**

## License

See repository for license details.
