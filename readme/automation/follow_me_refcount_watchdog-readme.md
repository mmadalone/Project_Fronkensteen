![Follow-Me Refcount Watchdog](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/follow_me_refcount_watchdog-header.jpeg)

# Follow-Me Refcount Watchdog

Safety net for the follow-me bypass refcount system used by Notification Follow-Me, Email Follow-Me, Voice Handoff, Wake-Up Guard, Calendar Alarm, Phone Charge Reminder, and Email Priority Filter. When parallel automation instances die mid-flight (automation reload, HA restart, `mode: restart` kill), the bypass counter stays incremented and `notification_follow_me` stays OFF permanently. This watchdog detects the stranded state and force-resets.

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
│  1. Snapshot counter + debug log before reset          │
│  2. Choose path:                                       │
│     ├─ startup/reload → full reset (reset counter,     │
│     │   restore toggle, clear debug log)               │
│     └─ poll → check counter > 0 AND last_changed       │
│        older than TTL → reset if stale                 │
│  3. Persistent notification (optional)                 │
└─────────────────────────────────────────────────────────┘
```

## Features

- **Configurable poll interval** -- check every 1, 2, 3, 5, or 10 minutes (default 2).
- **Counter-based stale detection** -- uses `last_changed` age on the counter entity instead of per-entry timestamps. Zero JSON, zero `from_json`, zero `selectattr`.
- **Startup/reload instant reset** -- resets the counter and restores the toggle immediately on HA restart or automation reload.
- **Debug log cleanup** -- clears the debug log helper on every reset.
- **Optional persistent notification** -- shows trigger source, counter snapshot, and debug log for audit trail.
- **Privacy gate** -- tier-based suppression with per-automation override support.

## Prerequisites

- Home Assistant
- Follow-me bypass system helpers:
  - `counter` for bypass refcount (e.g., `counter.ai_notification_follow_me_bypass_refcount`)
  - `input_boolean` for follow-me toggle (e.g., `input_boolean.ai_notification_follow_me`)
  - `input_text` for debug log (e.g., `input_text.ai_notification_follow_me_bypass_log`)

## Installation

1. Copy `follow_me_refcount_watchdog.yaml` to `config/blueprints/automation/madalone/`
2. Create automation: **Settings -> Automations -> Create -> Use Blueprint**

## Configuration

<details>
<summary>Section 1 -- Core</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `refcount_entity` | `counter.ai_notification_follow_me_bypass_refcount` | Counter entity tracking active bypass claims |
| `follow_me_toggle` | `input_boolean.ai_notification_follow_me` | Input boolean for notification follow-me |
| `debug_log_entity` | `input_text.ai_notification_follow_me_bypass_log` | Input text for owner debug logging (cleared on reset) |

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
| `privacy_gate_person` | `person.miquel` | Person entity for tier suppression lookups |

</details>

## Technical Notes

- **Mode:** `single` -- only one watchdog run at a time; `max_exceeded: silent`.
- **Worst-case recovery time:** TTL + poll interval (default ~3 minutes with 60s TTL + 2 min poll).
- **Counter-based design (v2.0.0):** Replaced JSON owner list with HA `counter` helper. Stale detection uses `last_changed` age on the counter entity. Zero JSON, zero `from_json`, zero `selectattr` -- eliminates BRP-WATCHDOG-001 class entirely.
- **Condition gate:** Follow-me toggle must be OFF (confirms the stranded state) plus privacy gate.
- **continue_on_error:** All helper mutations use `continue_on_error: true` to prevent cascading failures.

## Changelog

- **v2.0.0:** Replaced JSON owner list with HA `counter` helper. Stale detection uses `last_changed` age. Zero JSON, zero `from_json`, zero `selectattr`. Eliminates BRP-WATCHDOG-001 class entirely.
- **v1.3.0:** Inline stale/fresh owner filtering (BRP-WATCHDOG-001).
- **v1.2.0:** Configurable `poll_interval_minutes`, reduced TTL.
- **v1.1.0:** Replace one-shot state trigger with `time_pattern` poll.
- **v1.0.0:** Initial release.

## Author

**madalone**

## License

See repository for license details.
