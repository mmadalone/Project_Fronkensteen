![AI Email Promotion](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/ai_email_promotion-header.jpeg)

# AI Email Priority Filter — IMAP to Voice Context

Filters incoming IMAP emails and promotes only priority messages to L2 memory. Uses known contacts and keyword matching to filter high-volume inboxes, ensuring agents only see relevant emails. Part of Task 18b of the Voice Context Architecture.

## What's Inside

- **Template sensors:** 1 (`sensor.ai_email_priority_count`)
- **Input helpers:** 11 (moved to consolidated helper files) -- 3 booleans, 1 number, 6 texts, 1 select

Note: The automation (`ai_email_priority_filter`) was migrated to a blueprint instance in `automations.yaml`.

## Entity Reference

| Entity ID | Type | Purpose |
|---|---|---|
| `sensor.ai_email_priority_count` | template sensor | Mirror of `input_number.ai_email_priority_count` for dashboard display |
| `input_boolean.ai_email_master_toggle` | input_boolean | Master toggle for email system |
| `input_boolean.ai_email_promotion_enabled` | input_boolean | Kill switch (default ON) |
| `input_boolean.ai_email_stale` | input_boolean | Set when email API data is stale |
| `input_number.ai_email_priority_count` | input_number | Unread priority email count |
| `input_text.ai_email_known_contacts` | input_text | Comma-separated trusted senders/domains |
| `input_text.ai_email_priority_keywords` | input_text | Comma-separated custom filter keywords |
| `input_text.ai_email_blocked_senders` | input_text | Comma-separated blocked senders/domains (blacklist mode) |
| `input_text.ai_email_blocked_keywords` | input_text | Comma-separated blocked keywords (blacklist mode) |
| `input_text.ai_email_last_priority` | input_text | Last priority email subject (quick reference) |
| `input_text.ai_email_urgent_keywords` | input_text | Keywords that trigger urgent TTS announcement |
| `input_select.ai_email_filter_mode` | input_select | Filter mode: whitelist, blacklist, or hybrid |
| `sensor.ai_email_promotion_status` | sensor (pyscript) | Last operation status (created by pyscript) |

## Dependencies

- **Pyscript:** `pyscript/email_promote.py` (services: `email_promote_process`, `email_clear_count`)
- **Pyscript:** `pyscript/notification_dedup.py` (Task 14 -- `dedup_announce` for urgent TTS)
- **Pyscript:** `pyscript/memory.py` (L2 memory storage)
- **Package:** `ai_test_harness.yaml` (test mode toggle)
- **Package:** `ai_identity.yaml` (identity confidence sensors for privacy gating)
- **Integration:** IMAP (entry_id: `01KJDGKRNXQVVSPH5NT7V5P87E`)

## Cross-References

- **Package:** `ai_context_hot.yaml` -- priority email count injected into the Schedule section
- **Blueprint:** `madalone/email_priority_filter.yaml` -- IMAP trigger automation (migrated from inline)

## Notes

- Privacy-first design: email data is always user-scoped (never "household"), L2 keys include `:miquel:` for per-user enforcement, suppressed entirely when identity confidence < 70%, and invisible in guest mode.
- Test mode logs filter decisions but does not write to L2 or announce via TTS.
- Deployed: 2026-03-02.
