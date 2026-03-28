![Follow-Me Refcount Watchdog](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/follow_me_refcount_watchdog-header.jpeg)

# Follow-Me Refcount Watchdog

Safety net for the follow-me bypass refcount system used by Notification Follow-Me, Email Follow-Me, Voice Handoff, Wake-Up Guard, Calendar Alarm, Phone Charge Reminder, and Email Priority Filter. When parallel automation instances die mid-flight (automation reload, HA restart, supersede exit), the bypass owner list stays populated and `notification_follow_me` stays OFF permanently. This watchdog detects the stranded state and force-resets everything.

## How It Works

```
┌─────────────────────────────────────────────────────────┐
│                      TRIGGERS                           │
│  ┌────────────────────────────────────────────────────┐ │
│  │ 1. Time pattern: every N minutes (configurable)   │ │
│  │ 2. HA startup                                     │ │
│  │ 3. automation_reloaded event                      │ │
│  └──────────────────────┬─────────────────────────────┘ │
└─────────────────────────┼───────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│                  CONDITION GATES                        │
│  • Follow-me toggle is OFF?                            │
│  • Privacy gate passes?                                │
└────────────────────────┬────────────────────────────────┘
                         │ both true
                         ▼
┌─────────────────────────────────────────────────────────┐
│                  ACTION SEQUENCE                        │
│  0. Entity settle delay (10s, startup/reload only)     │
│  1. Parse JSON owner list from helper                  │
│     • Identify stale entries (older than TTL)          │
│     • Identify fresh entries (within TTL)              │
│  2. Choose path:                                       │
│     ├─ startup/reload → full reset (clear list,        │
│     │   restore toggle)                                │
│     └─ poll → evict stale entries only                 │
│        └─ if list now empty → restore toggle           │
│  3. Persistent notification (optional)                 │
└─────────────────────────────────────────────────────────┘
```

## Features

- **Configurable poll interval** -- check every 1, 2, 3, 5, or 10 minutes (default 2).
- **TTL-based eviction** -- individual owner entries older than the TTL (default 60s) are evicted; fresh entries are preserved.
- **Startup/reload instant reset** -- clears the entire owner list and restores the toggle immediately on HA restart or automation reload.
- **Stuck-toggle recovery** -- if the owner list is already empty but the toggle is stuck OFF, restores it anyway.
- **Optional persistent notification** -- shows trigger source, evicted owner count, and owner names for audit trail.
- **Privacy gate** -- tier-based suppression with per-automation override support.

## Prerequisites

- Home Assistant
- Follow-me bypass system helpers:
  - `input_text` for bypass owner list (JSON array, e.g., `input_text.notification_follow_me_bypass_owners`)
  - `input_boolean` for follow-me toggle (e.g., `input_boolean.notification_follow_me`)

## Installation

1. Copy `follow_me_refcount_watchdog.yaml` to `config/blueprints/automation/madalone/`
2. Create automation: **Settings -> Automations -> Create -> Use Blueprint**

## Configuration

<details>
<summary>Section 1 -- Core</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `bypass_owners_helper` | `input_text.notification_follow_me_bypass_owners` | Input text holding the JSON owner list |
| `follow_me_toggle` | `input_boolean.notification_follow_me` | Input boolean for notification follow-me |

</details>

<details>
<summary>Section 2 -- Timing</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `poll_interval_minutes` | `/2` (every 2 min) | Poll frequency: `/1`, `/2`, `/3`, `/5`, or `/10` |
| `ttl_seconds` | `60` | Max age in seconds before an owner entry is evicted |

</details>

<details>
<summary>Section 3 -- Optional</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `notify_on_reset` | `true` | Send persistent notification when watchdog fires |

</details>

<details>
<summary>Section 4 -- Privacy</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `privacy_tier` | `off` | Privacy gate tier (off/t1/t2/t3) |
| `privacy_gate_enabled` | `input_boolean.ai_privacy_gate_enabled` | Privacy gate master toggle |
| `privacy_gate_mode` | `input_select.ai_privacy_gate_mode` | Privacy gate behavior selector |
| `privacy_gate_person` | `miquel` | Person name for tier suppression lookups |

</details>

## Technical Notes

- **Mode:** `single` -- only one watchdog run at a time; `max_exceeded: silent`.
- **Worst-case recovery time:** TTL + poll interval (default ~3 minutes with 60s TTL + 2 min poll).
- **Poll vs. state trigger:** v1.1.0 replaced the one-shot state trigger with `time_pattern` because the state trigger with `for:` fired exactly once per OFF transition -- if the TTL hadn't elapsed yet, the watchdog was exhausted.
- **JSON owner format:** Each entry is `{"o": "automation.entity_id", "t": unix_timestamp}`. TTL comparison uses `selectattr`/`rejectattr` Jinja filters.
- **continue_on_error:** All helper mutations use `continue_on_error: true` to prevent cascading failures.

## Changelog

- **v1.2.0:** Configurable `poll_interval_minutes` input (default 2). Reduced TTL default from 180s to 60s.
- **v1.1.0:** Replace one-shot state trigger with `time_pattern` poll.
- **v1.0.0:** Initial release -- startup/reload instant reset, TTL-based eviction, optional persistent notification.

## Author

**madalone**

## License

See repository for license details.
