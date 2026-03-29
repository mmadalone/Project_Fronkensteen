# Email Follow-Me

![Email Follow-Me header](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/email-follow-me-header.jpeg)

When a new email arrives via the IMAP integration, this blueprint determines which room you're in via FP2 presence sensors, routes to the nearest voice satellite, and has a conversation agent summarize who emailed and what it's about -- completely hands-free. Includes blocked-sender filtering, keyword-based whitelist or blacklist, configurable cooldown, quiet hours, DND respect, attachment detection, UID-based deduplication, unread email reminders with LLM escalation, and sender alias mapping.

## How It Works

```
┌─────────────────────────────────────────────────────────┐
│                      TRIGGER                            │
│  ┌───────────────────────────────────────────────────┐  │
│  │ imap_content event (filtered by IMAP entry ID)   │  │
│  └──────────────────────┬────────────────────────────┘  │
└─────────────────────────┼───────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│                  CONDITION GATES                        │
│  • Master toggle ON?                                   │
│  • DND sensor not active?                              │
│  • Outside quiet hours?                                │
│  • Privacy gate passes?                                │
└────────────────────────┬────────────────────────────────┘
                         │ all pass
                         ▼
┌─────────────────────────────────────────────────────────┐
│                  ACTION SEQUENCE                        │
│  0. Save & bypass follow-me/ducking (refcount)         │
│  1. IMAP entry ID match gate                           │
│  1a. UID dedup gate (skip if recently announced)       │
│  1b. Blocked sender filter                             │
│  1c. Keyword filter (whitelist/blacklist)               │
│  1d. Email body sanitization (URLs, MIME, base64)      │
│  2. Junk subject pattern filter                        │
│  3. Cooldown enforcement (per-sender or time-only)     │
│  4. Resolve presence → satellite (parallel-array)      │
│  5. Gate: satellite found OR fallback enabled?          │
│  6. Route by announcement style:                       │
│     ├─ headline: "Email from [sender]"                 │
│     ├─ brief: sender + subject, no LLM                 │
│     └─ full_summary: LLM summarization                 │
│  7. Attachment detection → "check inbox" fallback      │
│  8. TTS delivery with volume control + ducking         │
│  9. Update timestamps + dedup helpers                  │
│ 10. Reminder loop (if enabled):                        │
│     ├─ Wait N minutes                                  │
│     ├─ Check IMAP unread count (exit if dropped)       │
│     ├─ Escalate style (headline→brief→full LLM)       │
│     └─ Repeat up to max_repeats                        │
│ 11. Restore follow-me/ducking                          │
└─────────────────────────────────────────────────────────┘
```

## Features

- **Hands-free email announcements** -- incoming emails are summarized and spoken via the nearest satellite.
- **3-tier announcement style** -- full LLM summary, brief (sender + subject), or headline (sender only).
- **3-layer email sanitization** -- strips URLs, MIME headers, base64 blobs, CSS, and tracking pixels before LLM processing; content policy block in prompts; TTS catch-all sanitization.
- **Blocked sender filter** -- comma-separated names/addresses, case-insensitive substring matching.
- **Sender alias map** -- map raw sender names to friendly display names (e.g., `boss@work.com=The Boss`).
- **Keyword filtering** -- whitelist or blacklist mode on subject + body content.
- **Junk subject patterns** -- suppress system emails by subject substring.
- **UID-based deduplication** -- prevents re-announcement of duplicate IMAP events from restarts or re-syncs.
- **Per-sender cooldown** -- optional per-sender gate so different senders always pass; same-sender repeats are throttled.
- **Presence-based routing** -- parallel-array mapping of FP2 sensors to satellites; first occupied zone wins.
- **Mobile push fallback** -- optional push notification when no satellite is in range.
- **Configurable TTS volume** -- fixed output volume with save/restore around playback.
- **Ringer mode integration** -- reduced volume on vibrate, skip entirely on silent.
- **Media player ducking** -- temporarily lower other players during TTS with shared snapshot helper for race-free parallel runs.
- **Unread email reminders** -- re-announce at configurable intervals with IMAP unread count exit detection.
- **Reminder escalation** -- headline -> brief -> full LLM with each reminder iteration (or match mode for uniform style).
- **LLM-powered reminders** -- agent re-summarizes with escalation context (reminder number, elapsed time).
- **Multi-email awareness** -- LLM receives last announced sender/subject and IMAP unread count for natural context.
- **Attachment detection** -- emails with attachments get "check your inbox" fallback or LLM summary.
- **Mark as seen** -- optionally mark emails as read on the mail server after announcing.
- **Dispatcher integration** -- dynamically selects agent/voice via the AI dispatcher when enabled.
- **Follow-me/ducking bypass** -- refcount-based bypass to prevent notification interrupts during processing.
- **Privacy gate** -- tier-based suppression with per-person overrides.

## Prerequisites

- **Home Assistant 2024.10.0+**
- **IMAP integration** configured with an email account
- **Presence sensors** -- binary sensors for room presence (e.g., Aqara FP2 zones)
- **Voice satellites** -- media_player entities capable of TTS
- **Conversation agent** -- any agent supporting `conversation.process`
- **TTS integration** -- any `tts.*` entity
- **input_boolean** -- master on/off toggle
- **input_datetime** -- cooldown timestamp tracker

## Installation

1. Copy `email_follow_me.yaml` to `config/blueprints/automation/madalone/`
2. Create automation: **Settings -> Automations -> Create -> Use Blueprint**

## Configuration

<details>
<summary>Section 1 -- Core Setup</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `imap_entry_id` | `""` | IMAP integration config entry ID |
| `email_account_label` | `"Email"` | Friendly label for the account (used in TTS) |
| `enable_toggle` | `""` *(required)* | Master enable/disable toggle |
| `notification_master_gate` | `input_boolean.ai_notifications_master_enabled` | Global notification gate -- suppresses all notification automations when OFF |
| `conversation_agent` | `Rick` | Assist Pipeline name (overridden by dispatcher) |
| `email_prompt` | *(see blueprint)* | LLM summarization instructions |
| `context_entities` | `[]` | Extra sensors/entities for LLM context |
| `mark_as_seen` | `false` | Mark email as read on server after announcing |

</details>

<details>
<summary>Section 2 -- Presence Routing</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `presence_sensors` | `[]` | Binary sensors for room presence (priority order) |
| `target_satellites` | `[]` | Paired media players (same order as sensors) |
| `fallback_mode` | `silent` | No-presence fallback: `mobile_push` or `silent` |
| `mobile_notify_service` | `""` | Notify service for mobile push fallback |

</details>

<details>
<summary>Section 3 -- Email Filtering</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `blocked_senders` | `""` | Comma-separated blocked sender names/addresses |
| `sender_aliases` | `""` | Comma-separated Key=Value alias map |
| `keyword_list` | `""` | Comma-separated keywords for filtering |
| `keyword_mode` | `blacklist` | Keyword filter mode: `whitelist` or `blacklist` |
| `junk_patterns` | `""` | Comma-separated junk subject substrings |
| `cooldown_seconds` | `120` | Minimum seconds between announcements |
| `last_announced_helper` | `""` *(required)* | Input datetime for cooldown tracking |
| `last_announced_sender_helper` | `""` | Optional input text for per-sender cooldown |
| `char_cap` | `1000` | Max email body characters sent to LLM |
| `attachment_behavior` | `llm_summary` | Attachment handling: `llm_summary`, `short_tts`, or `drop` |
| `announcement_style` | `full_summary` | Verbosity: `full_summary`, `brief`, or `headline` |

</details>

<details>
<summary>Section 4 -- Quiet Hours and DND</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `dnd_sensor` | `""` | Phone DND sensor entity |
| `enable_quiet_hours` | `false` | Enable time-based quiet hours window |
| `quiet_start` | `23:00:00` | Quiet hours start time |
| `quiet_end` | `07:00:00` | Quiet hours end time |

</details>

<details>
<summary>Section 5 -- TTS Configuration</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `tts_announce` | `false` | Use announce mode for TTS |
| `tts_output_volume` | `0.0` | Fixed TTS volume (0 = disabled) |

</details>

<details>
<summary>Section 6 -- Ringer Mode Volume Control</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `ringer_mode_sensor` | `""` | Phone ringer mode sensor (normal/vibrate/silent) |
| `quiet_volume` | `0.15` | Volume level when phone is in vibrate mode |
| `tts_restore_delay` | `3` s | Post-playback grace period before volume restore |

</details>

<details>
<summary>Section 7 -- Duck Guard</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `ducking_flag` | `""` | Input boolean for duck cycle signaling |
| `duck_guard_enabled` | `input_boolean.ai_duck_guard_enabled` | Duck guard system toggle |

</details>

<details>
<summary>Section 8 -- Unread Email Reminders</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `imap_sensor` | `""` | IMAP sensor entity (unread count) |
| `enable_reminders` | `false` | Enable reminder re-announcements |
| `reminder_interval` | `5` min | Minutes between reminders |
| `reminder_max_repeats` | `3` | Maximum reminder count |
| `reminder_style` | `escalate_to_full` | Escalation mode: `escalate_to_full` or `match_announcement` |
| `dedup_uids_helper` | `""` | Input text for UID-based dedup |
| `last_subject_helper` | `""` | Input text for last announced subject |
| `reminder_prompt` | *(see blueprint)* | LLM prompt for reminder announcements |

</details>

<details>
<summary>Section 9 -- Agent Selection</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `use_dispatcher` | `true` | Use the AI dispatcher for dynamic agent selection |
| `bypass_follow_me` | `true` | Bypass notification follow-me during processing |
| `bypass_claim_script` | `script.refcount_bypass_claim` | Refcount claim script |
| `bypass_release_script` | `script.refcount_bypass_release` | Refcount release script |

</details>

<details>
<summary>Section 10 -- Privacy</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `privacy_tier` | `t2` | Privacy gate tier (off/t1/t2/t3) |
| `privacy_gate_enabled` | `input_boolean.ai_privacy_gate_enabled` | Privacy gate master toggle |
| `privacy_gate_mode` | `input_select.ai_privacy_gate_mode` | Privacy gate behavior selector |
| `privacy_gate_person` | `person.miquel` | Person entity for tier suppression lookups |

</details>

<details>
<summary>Section 11 -- Music (Pre-TTS Stinger)</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `enable_pre_tts_stinger` | `false` | Play a chime/stinger before the TTS announcement |
| `stinger_agent` | `""` | Agent persona for library/compose lookups (empty = use dispatched persona) |
| `stinger_library_id_override` | `""` | Explicit music library ID (skips auto-resolve when set) |
| `compose_stinger_if_missing` | `true` | Compose locally via FluidSynth when library lookup fails |
| `stinger_fallback_media_url` | `""` | Fallback chime file URL when both library and compose fail |

</details>

<details>
<summary>Section 12 -- Infrastructure</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `dispatcher_enabled` | `input_boolean.ai_dispatcher_enabled` | Dispatcher enabled entity |

</details>

<details>
<summary>Section 13 -- User Preferences</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `enable_notify_threshold` | `false` | Gate TTS against user's notification threshold preference |
| `email_priority` | `3` | TTS queue priority (0=emergency, 1=alert, 2=normal, 3=low, 4=ambient) |

</details>

## Technical Notes

- **Mode:** `queued` with `max: 5` -- up to 5 emails can queue for sequential processing.
- **Stored traces:** 10 traces retained for debugging.
- **Parallel-array routing:** Presence sensors and target satellites are paired by index (sensor[0] -> satellite[0]). Lists must be the same length.
- **3-layer sanitization:** Layer 1 strips raw artifacts from the body before LLM. Layer 2 injects a content policy block into the LLM prompt. Layer 3 uses TTS-level regex as a catch-all.
- **Cooldown:** Per-sender mode allows different senders to bypass cooldown; same-sender repeats within the window are suppressed.
- **Reminder exit conditions:** IMAP unread count drops, max retries hit, or any gate condition fails (DND, quiet hours, toggle off).
- **Refcount bypass:** Uses claim/release script pattern (I-45b) to prevent notification follow-me and ducking from interfering during email processing.

## Changelog

- **v1.4.1:** 3-layer email sanitization (URL/MIME/base64 stripping, content policy prompt injection, TTS catch-all).
- **v1.4.0:** Verbosity control, UID dedup, LLM multi-email context, agent self-awareness v2, reminder escalation.
- **v1.3.0:** Agent self-awareness, playback poll race fix, LLM-powered reminders.
- **v1.2.0:** Ducking flag integration for external volume-sync race prevention.

## Author

**madalone**

## License

See repository for license details.
