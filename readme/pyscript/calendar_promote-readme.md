# Calendar Promotion Engine — Google Calendar to L2/L1

Task 18a of the Voice Context Architecture. Promotes Google Calendar events from L3 (API) to L2 (memory) and L1 (input_text helpers) for fast agent access. Fetches a 48-hour window (today + tomorrow), detects work days from event keywords, and updates hot-context helpers. Includes a 5-minute promote cache to debounce rapid triggers.

## Services

| Service | Parameters | Returns | Description |
|---------|-----------|---------|-------------|
| `pyscript.calendar_promote_now` | `force` (bool, default false) | `{status, op, today_events, tomorrow_events, today_summary, tomorrow_summary, l2_today, l2_tomorrow, api_failed, stale, test_mode, elapsed_ms}` | On-demand calendar promotion. Fetches today + tomorrow events from Google Calendar (plus holidays and birthdays), formats for agent consumption, writes to L2 memory and updates L1 input_text helpers. `supports_response="only"` |

## Triggers

| Trigger | Function | Condition |
|---------|----------|-----------|
| `@time_trigger("startup")` | `calendar_promote_startup` | Initializes status sensor, runs initial promotion with `force=True` |
| `@time_trigger("cron(5 0 * * *)")` | `calendar_promote_midnight` | Midnight sync: clears cache, refreshes today + tomorrow data |
| `@state_trigger("calendar.miquel_angel_cano_gmail_com", ...)` | `calendar_state_changed` | Re-promotes when calendar entity state or next-event message changes. Cache debounces rapid-fire triggers. |

## Key Functions

- `_format_event_compact()` — Formats a single event: timed ("10:00 Dentist"), all-day ("All day: Holiday"), or multi-day ("All day: Conference Day 2/3")
- `_format_events_compact()` — Pipe-delimited formatting for L2 storage
- `_format_events_for_helper()` — Same as compact but truncated to 255 chars for input_text helpers
- `_extract_events_for_date()` — Filters events that overlap with a specific date (handles timed and all-day edge cases)
- `_filter_ended_events()` — Removes timed events whose end time has passed (prevents cross-midnight events from appearing in morning briefing)
- `_detect_work_day()` — Checks event summaries against work-related keywords to auto-set `ai_context_work_day` / `ai_context_work_day_tomorrow`
- `_parse_mock_events()` — Parses mock calendar input from test harness for integration testing

## State Dependencies

- `input_boolean.ai_calendar_promotion_enabled` — Kill switch
- `input_boolean.ai_calendar_stale` — Stale flag set on API failure
- `input_text.ai_calendar_today_summary` / `ai_calendar_tomorrow_summary` — L1 helpers for hot context
- `input_text.ai_calendar_last_sync` — Last sync timestamp
- `input_boolean.ai_context_work_day` / `ai_context_work_day_tomorrow` — Auto-detected work day flags
- `input_boolean.ai_work_day_manual_override` — When ON, skips auto work-day detection
- `input_text.ai_work_calendar_keywords` — CSV keywords for work day detection
- `input_boolean.ai_test_mode` / `input_text.ai_test_calendar_event` — Test mode toggle and mock event input

## Package Pairing

Pairs with `packages/ai_calendar_promotion.yaml` which defines all calendar-related helpers, the stale flag, sync timestamp, and the `sensor.ai_calendar_promotion_status` result entity.

## Called By

- **Midnight sync automation** — triggered by the built-in `@time_trigger("cron(5 0 * * *)")`
- **Calendar state change** — triggered by the `@state_trigger` on the Google Calendar entity
- **proactive_briefing.py** — reads L1 helpers for calendar sections in morning/afternoon/evening briefings
- **predictive_schedule.py** — reads the tomorrow work-day flag for wake time prediction
- **calendar_alarm.yaml** — uses the predicted work-day state for alarm decisions

## Notes

- Three calendar sources: main Google Calendar, Spanish holidays, and Google Contacts birthdays. All fetched in a single 48h window.
- API failure handling: on failure, the stale flag is set, existing L2 data is preserved (not cleared), and after 3 consecutive failures a persistent notification is created.
- The promote cache (5-minute TTL) prevents redundant API calls when multiple state changes fire in quick succession.
- Multi-day event support: correctly renders "Day 2/3" labels and handles the exclusive end-date convention for all-day events.
- Cross-midnight fix (I-26): timed events that ended before the current time are filtered from today's list to prevent stale events from appearing in morning briefings.
