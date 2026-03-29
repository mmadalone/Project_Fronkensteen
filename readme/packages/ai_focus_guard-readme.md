# AI Focus Guard — Anti-ADHD Nudge System

Provides anti-ADHD nudges: time checks, meal reminders, calendar warnings, social nudges, break suggestions, and bedtime approach alerts. Each nudge type tracks its own escalation level independently. Focus mode acts as a voice-activated DND that suppresses non-calendar nudges. Part of Task 20 of the Voice Context Architecture.

## What's Inside

- **Sensors:** 1 history_stats sensor (`sensor.workshop_hours_today`)
- **Automations:** 2 (`ai_focus_guard_midnight_reset`, `ai_focus_mode_auto_expire`)
- **Input helpers:** 6+ (moved to consolidated helper files) -- booleans, numbers, datetimes

## Entity Reference

| Entity ID | Type | Purpose |
|---|---|---|
| `sensor.workshop_hours_today` | history_stats sensor | FP2 workshop presence ON-time today (hours) |
| `automation.ai_focus_guard_midnight_reset` | automation | Turns off focus mode at midnight |
| `automation.ai_focus_mode_auto_expire` | automation | Auto-expires focus mode after `focus_mode_max_hours` |
| `input_boolean.ai_focus_mode` | input_boolean | Voice-activated DND (suppresses non-calendar nudges) |
| `input_boolean.ai_focus_guard_enabled` | input_boolean | Kill switch (default ON) |
| `input_datetime.ai_last_meal_time` | input_datetime | User marks meals via voice/button |
| `input_datetime.ai_focus_guard_snooze_until` | input_datetime | Snooze expiry timestamp |
| `input_number.ai_focus_guard_threshold_hours` | input_number | Hours before first nudge (default 2) |
| `input_number.ai_focus_mode_max_hours` | input_number | Focus mode auto-expiry (default 2h) |
| `sensor.ai_focus_guard_status` | sensor (pyscript) | Last operation status (created by pyscript) |

## Dependencies

- **Pyscript:** `pyscript/focus_guard.py` (3 services: `focus_guard_evaluate`, `focus_guard_mark_meal`, `focus_guard_snooze`)
- **Pyscript:** `pyscript/tts_queue.py` (nudge delivery via `tts_queue_speak`)
- **Pyscript:** `pyscript/notification_dedup.py` (`dedup_check`, `dedup_register`)
- **Pyscript:** `pyscript/memory.py` (L2 snooze pattern logging)
- **Package:** `ai_context_hot.yaml` (wake/bed times, presence data)
- **Package:** `ai_identity.yaml` (identity confidence, occupancy mode)
- **Package:** `ai_llm_budget.yaml` (budget gate for agent-personality nudges)
- **Package:** `ai_test_harness.yaml` (test mode toggle)
- **Hardware:** Aqara FP2 workshop presence sensor

## Cross-References

- **Package:** `ai_context_hot.yaml` -- workshop hours and focus mode state injected into the Focus line of the Environment component
- **Voice agents:** `focus_guard_mark_meal` and `focus_guard_snooze` exposed as LLM tool functions

## Notes

- 6 nudge types with independent escalation: time check (P4-P2), meal reminder (P4-P2), calendar warning (P3-P1), social nudge (P4-P3), break suggestion (P4 only), bedtime approach (P3-P1).
- Calendar warnings always bypass focus mode. All other nudge types are suppressed when focus mode is ON.
- Focus mode auto-expires using a `for:` duration trigger that reads from `ai_focus_mode_max_hours`, supporting fractional hours.
- The `workshop_hours_today` sensor uses HA-native `history_stats` with FP2 data, immune to sensor flapping.
- Deployed: 2026-03-03.
