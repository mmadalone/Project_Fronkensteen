![Email Priority Filter](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/email_priority_filter-header.jpeg)

# Email Priority Filter

Listens for IMAP content events from a specific email account and passes sender + subject to `pyscript.email_promote_process` for priority filtering and L2 memory promotion. Gated by a kill switch. Designed to work alongside Email Follow-Me -- this blueprint handles backend priority classification while Email Follow-Me handles TTS announcements.

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
│  • Notification master gate ON?                        │
│  • Kill switch ON?                                     │
└────────────────────────┬────────────────────────────────┘
                         │ all pass
                         ▼
┌─────────────────────────────────────────────────────────┐
│                  ACTION SEQUENCE                        │
│  0. Save & bypass follow-me/ducking (refcount)         │
│  1. Call pyscript.email_promote_process                 │
│     (sender + subject + suppress_tts flag)             │
│  2. Restore follow-me/ducking                          │
└─────────────────────────────────────────────────────────┘
```

## Features

- **IMAP-to-pyscript pipeline** -- bridges HA's IMAP integration to the pyscript email priority engine.
- **L2 memory promotion** -- urgent/important emails are promoted to L2 memory for agent context.
- **TTS suppression option** -- suppress urgent TTS announcements when Email Follow-Me instances already handle them (avoids duplicate speech).
- **Follow-me bypass** -- refcount-based bypass prevents notification follow-me from interrupting during processing.
- **Notification master gate** -- respects the global notification gate toggle.
- **Privacy gate** -- tier-based suppression (default: T2 Personal).

## Prerequisites

- **Home Assistant 2024.10.0+**
- **IMAP integration** configured
- **Pyscript** with `email_promote_process` service
- **input_boolean** -- kill switch for enable/disable

## Installation

1. Copy `email_priority_filter.yaml` to `config/blueprints/automation/madalone/`
2. Create automation: **Settings -> Automations -> Create -> Use Blueprint**

## Configuration

<details>
<summary>Section 1 -- IMAP Source</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `imap_entry_id` | `""` | Config entry ID of the IMAP integration |

</details>

<details>
<summary>Section 2 -- Controls</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `kill_switch` | `""` *(required)* | Input boolean to enable/disable the filter |
| `notification_master_gate` | `input_boolean.ai_notifications_master_enabled` | Global notification gate -- when OFF, all notification automations are suppressed |
| `suppress_urgent_tts` | `false` | Skip TTS for urgent emails (use when Email Follow-Me handles announcements) |

</details>

<details>
<summary>Section 3 -- Bypass</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `bypass_follow_me` | `true` | Bypass notification follow-me during processing |
| `bypass_claim_script` | `script.refcount_bypass_claim` | Refcount claim script |
| `bypass_release_script` | `script.refcount_bypass_release` | Refcount release script |

</details>

<details>
<summary>Section 4 -- Privacy</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `privacy_tier` | `t2` | Privacy gate tier (off/t1/t2/t3) |

</details>

## Technical Notes

- **Mode:** `queued` with `max: 5` -- multiple emails can queue for sequential processing.
- **Pyscript call:** `pyscript.email_promote_process` receives `sender`, `subject`, and `suppress_tts` flag. The pyscript service handles all priority classification logic.
- **Refcount bypass pattern:** Uses the same claim/release script pattern (I-45b) as other blueprints for race-free follow-me/ducking management.
- **Dual use with Email Follow-Me:** Set `suppress_urgent_tts: true` when an Email Follow-Me instance covers the same IMAP account to avoid duplicate TTS announcements.

## Changelog

- **v1:** Initial blueprint -- replaces automation from `ai_email_promotion.yaml`.

## Author

**madalone**

## License

See repository for license details.
