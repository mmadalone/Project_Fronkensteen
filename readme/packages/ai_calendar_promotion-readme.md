![AI Calendar Promotion](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/ai_calendar_promotion-header.jpeg)

# AI Calendar Promotion — Google Calendar to Voice Context

Promotes Google Calendar events from L3 (API) to L2 (memory) for fast agent access. Provides near-real-time sync via midnight cron and state-change triggers, plus L1 quick-access summaries for today and tomorrow. Part of Task 18a of the Voice Context Architecture.

## What's Inside

- **Input helpers:** 4 (moved to consolidated helper files) -- 2 booleans, 2 texts
- **Dashboard card:** Commented YAML for Lovelace integration

Note: The automation (`ai_calendar_pre_event_reminder`) was migrated to a blueprint instance in `automations.yaml`.

## Entity Reference

| Entity ID | Type | Purpose |
|---|---|---|
| `input_boolean.ai_calendar_promotion_enabled` | input_boolean | Kill switch (default ON) |
| `input_boolean.ai_calendar_stale` | input_boolean | Set when calendar API fails |
| `input_text.ai_calendar_last_sync` | input_text | ISO timestamp of last successful sync |
| `input_text.ai_calendar_today_summary` | input_text | Today's events (L1 quick access) |
| `input_text.ai_calendar_tomorrow_summary` | input_text | Tomorrow's events (L1 quick access) |
| `sensor.ai_calendar_promotion_status` | sensor (pyscript) | Last operation status (created by pyscript) |

## Dependencies

- **Pyscript:** `pyscript/calendar_promote.py` (service: `calendar_promote_now`)
- **Pyscript:** `pyscript/notification_dedup.py` (Task 14 -- `dedup_announce` for pre-event reminders)
- **Package:** `ai_test_harness.yaml` (test mode toggle)
- **Package:** `ai_predictive_schedule.yaml` (`ai_test_calendar_event` helper for test mode mock data)
- **Integration:** `calendar.miquel_angel_cano_gmail_com` (Google Calendar)

## Cross-References

- **Package:** `ai_context_hot.yaml` -- today/tomorrow summaries injected into the Schedule section of the Environment component
- **Blueprint:** `madalone/calendar_pre_event_reminder.yaml` -- 15-min TTS reminder (migrated from inline automation)

## Notes

- Test mode uses mock data from `input_text.ai_test_calendar_event` instead of querying the real calendar API. Pre-event reminder automation does not fire in test mode.
- The `ai_calendar_reminder_minutes` input_number was removed -- the blueprint uses its own offset input.
- Deployed: 2026-03-02.
