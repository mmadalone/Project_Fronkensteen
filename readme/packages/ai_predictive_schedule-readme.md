# AI Predictive Schedule

Fuses data from L1 (presence patterns), L2 (routine fingerprints), and L3 (Google Calendar) to compute bedtime timing recommendations and general event scheduling. Fires advisory events when the target routine start time approaches, enabling proactive bedtime nudges without creepy behavior tracking disclosure. Part of Task 17 of the Voice Context Architecture.

## What's Inside

| Type | Count |
|------|-------|
| Template sensors | 1 |
| Input helpers (external) | 4 |

## Entity Reference

| Entity ID | Type | Purpose |
|-----------|------|---------|
| `sensor.ai_schedule_confidence` | Template sensor | Confidence level (high/medium/low/none) based on which data sources contributed |
| `sensor.ai_predictive_schedule_status` | Pyscript sensor | Last operation result (set by pyscript via `state.set()`); attrs include `bedtime_recommendation` and `schedule_sources_raw` |
| `input_number.ai_target_sleep_hours` | Input Number | Target sleep duration (default: 7h) |
| `input_number.ai_morning_prep_buffer` | Input Number | Wake-to-ready buffer in minutes (default: 45m) |
| `input_text.ai_test_calendar_event` | Input Text | Mock calendar data for test mode |
| `input_datetime.ai_predicted_routine_start` | Input Datetime | Predicted routine start time |

## Dependencies

- **Pyscript:** `pyscript/predictive_schedule.py` — bedtime advisor and optimal timing services
- **Pyscript:** `pyscript/routine_fingerprint.py` (Task 16) — routine fingerprints and completion events
- **Pyscript:** `pyscript/presence_patterns.py` (Task 15) — frequency tables
- **Pyscript:** `pyscript/memory.py` — L2 memory layer
- **Package:** `ai_context_hot.yaml` — default wake times
- **Package:** `ai_routine_tracker.yaml` — routine stage and bedtime prediction flag
- **Package:** `ai_test_harness.yaml` — test mode toggle
- **Integration:** `calendar.miquel_angel_cano_gmail_com` (Google Calendar)
- **Helper files:** `helpers_input_number.yaml`, `helpers_input_text.yaml`, `helpers_input_datetime.yaml`

## Cross-References

- **calendar_alarm.yaml** blueprint — triggers from `ai_predicted_wake_time` (exposed by pyscript)
- **ai_context_hot.yaml** — reads `input_boolean.ai_context_work_day_tomorrow` set by calendar promotion
- **proactive_briefing.py** — may reference schedule data for briefing content
- **Pyscript events:** `ai_bedtime_advisory` (<=15 min to target), `ai_bedtime_overdue` (past target)

## Notes

- **Creep Factor Gate:** Recommendations must be about schedule and sleep timing, never about tracked behavior. "Start winding down in 45 minutes" is acceptable; "I tracked your bathroom routine at 11:23 PM" is not.
- Confidence tiers: high = calendar + fingerprint, medium = fingerprint only, low = presence/calendar only, none = no data.
- Includes a commented-out dashboard card definition for manual deployment.
