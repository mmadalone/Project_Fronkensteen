# Predictive Scheduling Engine

Fuses calendar events (L3), routine fingerprint durations (L2), and real-time state (L1) to produce bedtime advisories and general timing recommendations. Runs a 30-minute cron loop from 20:00-02:00, fires `ai_bedtime_advisory` and `ai_bedtime_overdue` events, and feeds back predicted-vs-actual timing to improve accuracy over time. Part of Task 17 of the Voice Context Architecture.

## Services

| Service | Parameters | Returns | Description |
|---------|-----------|---------|-------------|
| `pyscript.schedule_bedtime_advisor` | `target_sleep_hours` (float, default 0.0), `prep_buffer_minutes` (int, default 0) | `{status, first_event_tomorrow, is_work_tomorrow, required_wake_time, target_sleep_time, routine_duration_min, target_routine_start, minutes_until_routine, recommendation, confidence, sources, current_zone, relaxed_mode, elapsed_ms}` | Flagship prediction: combines calendar (L3), routine fingerprint duration (L2), and current state (L1) to recommend when to start winding down. |
| `pyscript.schedule_optimal_timing` | `event_description` (str), `event_time` (str, required), `prep_minutes` (int, default 30), `travel_minutes` (int, default 0) | `{status, event, event_time, leave_by, start_prep, reminder_time, prep_minutes, travel_minutes}` | General-purpose: given a target event, work backwards using prep and travel time to suggest when to start preparing. |

Both services use `supports_response="only"`.

## Triggers

| Trigger | Function | Condition |
|---------|----------|-----------|
| `@event_trigger("ai_routine_completed")` | `_on_routine_completed` | Feedback loop: compare predicted vs actual routine timing. Only tracks bed-ending fingerprints. |
| `@time_trigger("cron(0,30 20-23 * * *)", "cron(0,30 0-1 * * *)", "cron(0 2 * * *)")` | `_bedtime_check` | Every 30 min from 20:00-02:00: run bedtime advisor, fire advisory/overdue events. |
| `@time_trigger("startup")` | `_startup` | Initialize status sensor. Runs initial advisory after 240s delay for fingerprints to populate. |

## Key Functions

- `_compute_bedtime_plan(...)` -- Compute bedtime timing plan on a 48-hour minute number line. `@pyscript_compile`.
- `_extract_earliest_timed_event(events_raw)` -- Find earliest timed event from calendar list (skips all-day). `@pyscript_compile`.
- `_compute_optimal_plan(...)` -- Compute prep/leave/reminder times for a given event. `@pyscript_compile`.
- `_build_recommendation(minutes_until, sleep_hours)` -- Build human-readable recommendation (creep factor safe). `@pyscript_compile`.
- `_fetch_calendar_tomorrow()` -- Fetch events from Google Calendar with 1-hour cache. Stores earliest event in L2 as fallback.
- `_get_first_event_tomorrow()` -- Fallback chain: Calendar API -> L2 cached data -> None.
- `_get_bedtime_routine_duration()` -- Average duration of bed-ending routines from L2 fingerprints.
- `_get_default_wake_time(for_tomorrow)` -- Per-day overrides -> per-user weekday/weekend defaults -> hard defaults.
- `_update_helpers(result, test_mode)` -- Write recommendation text and sources JSON to status sensor attributes, predicted routine start and wake time to input_datetime helpers.

## State Dependencies

- `input_number.ai_target_sleep_hours` -- Target hours of sleep (default 7.0)
- `input_number.ai_morning_prep_buffer` -- Minutes from wake to leaving house (default 45)
- `input_number.ai_bedtime_relaxed_extension_minutes` -- Extra minutes when no timed event tomorrow (default 90)
- `input_datetime.ai_context_wake_time_weekday_{user}` / `_weekend_{user}` -- Per-user default wake times
- `input_text.ai_schedule_day_overrides` -- JSON per-day-of-week wake time overrides
- `sensor.ai_predictive_schedule_status` attr `bedtime_recommendation` -- Output: recommendation text
- `input_datetime.ai_predicted_routine_start` -- Output: predicted routine start time
- `input_datetime.ai_predicted_wake_time` -- Output: predicted wake time (used by calendar_alarm blueprint)
- `sensor.ai_predictive_schedule_status` attr `schedule_sources_raw` -- Output: confidence sources JSON
- `input_text.ai_routine_stage` -- Current routine stage from routine_fingerprint.py
- `input_boolean.ai_bedtime_predicted` -- Whether bedtime routine is predicted/active
- `input_boolean.ai_context_work_day_tomorrow` -- Work day status from calendar_promote
- `input_boolean.ai_test_mode` -- Test mode toggle
- `input_text.ai_test_calendar_event` -- Mock calendar event for testing
- FP2 binary sensors (8 zones) -- Current zone detection

## Package Pairing

Pairs with `packages/ai_predictive_schedule.yaml` (helpers for sleep hours, prep buffer, recommendation text, routine start, sources). Also reads from `packages/ai_context_hot.yaml` (wake times), `packages/ai_routine_tracker.yaml` (routine stage, bedtime predicted).

## Called By

- **Blueprints**: `calendar_alarm.yaml` consumes `ai_predicted_wake_time`; `bedtime_instant.yaml` and bedtime routines consume bedtime advisory events
- **Other pyscript**: `proactive_briefing.py` reads schedule section data
- **Automations**: Bedtime advisory events (`ai_bedtime_advisory`, `ai_bedtime_overdue`) trigger downstream blueprints
- **Depends on**: `pyscript/routine_fingerprint.py` (L2 fingerprints), `pyscript/presence_patterns.py` (frequency tables), `pyscript/memory.py` (L2)

## Notes

- **Creep factor gate**: Recommendations talk about schedule and sleep, NEVER about tracked behavior ("start winding down" not "I tracked your routine").
- **Calendar cache**: 1-hour TTL to avoid hammering the Google Calendar API. Cache invalidated on date change.
- **Fallback chain**: Calendar API -> L2 cached calendar -> default wake time helper.
- **Feedback loop**: `ai_routine_completed` events compare predicted vs actual timing. Classified as reinforced (within 15 min), neutral, or weakened (>30 min off) and stored in L2 for 90 days.
- **Relaxed mode**: When no timed events exist tomorrow, adds a configurable extension (default 90 min) to the routine start time.
- **48-hour number line**: All time math uses a 48-hour minute line where post-midnight hours (0-5) are treated as "still tonight" (+1440 minutes).
