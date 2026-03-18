# AI Notification Deduplication — Spam Prevention

Kill switch, TTL configuration, and daily statistics for the notification deduplication engine (Task 14 / DC-9). Prevents duplicate TTS announcements and notifications from firing within a configurable time window.

## What's Inside

- **Template sensors:** 1 (`sensor.ai_dedup_blocked_today`)
- **Input helpers:** 3 (moved to consolidated helper files) -- 1 boolean, 2 numbers

## Entity Reference

| Entity ID | Type | Purpose |
|---|---|---|
| `sensor.ai_dedup_blocked_today` | template sensor | Mirror of `input_number.ai_dedup_blocked_count` for dashboard display |
| `input_boolean.ai_dedup_enabled` | input_boolean | Kill switch (set to ON after deploy) |
| `input_number.ai_dedup_default_ttl` | input_number | Default TTL in minutes (recommended: 240 = 4 hours) |
| `input_number.ai_dedup_blocked_count` | input_number | Daily blocked notification counter (auto-managed) |
| `sensor.ai_dedup_status` | sensor (pyscript) | Dedup engine status (created by pyscript) |

## Dependencies

- **Pyscript:** `pyscript/notification_dedup.py` (services: `dedup_check`, `dedup_register`, `dedup_announce`, `dedup_daily_housekeeping`)

## Cross-References

- **Pyscript:** `pyscript/calendar_promote.py` -- uses `dedup_announce` for pre-event reminders
- **Pyscript:** `pyscript/email_promote.py` -- uses `dedup_announce` for urgent email TTS
- **Pyscript:** `pyscript/focus_guard.py` -- uses `dedup_check` and `dedup_register` for nudge deduplication
- **Multiple blueprints** call dedup services to prevent notification spam

## Notes

- Midnight counter reset is handled by `notification_dedup.py` via the `dedup_daily_housekeeping` service, not by a package automation.
- The `ai_test_mode` helper is intentionally NOT defined here -- it lives in `ai_test_harness.yaml`.
- After first deploy, set: `ai_dedup_enabled` = ON, `ai_dedup_default_ttl` = 240, `ai_dedup_blocked_count` = 0.
- Deployed as part of Task 14 / DC-9.
