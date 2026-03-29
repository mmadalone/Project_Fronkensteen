# AI Routine Tracker

Provides helper entities and a template sensor for the routine fingerprinting and position tracking engine. Matches zone transitions against learned routine fingerprints, tracks current position within a routine, estimates time to completion, and detects deviations. Part of Task 16 of the Voice Context Architecture.

## What's Inside

| Type | Count |
|------|-------|
| Template sensors | 1 |
| Input helpers (external) | 4 |
| Pyscript sensors (dynamic) | 1 |

## Entity Reference

| Entity ID | Type | Purpose |
|-----------|------|---------|
| `sensor.ai_routine_eta` | Template sensor | Estimated minutes remaining in current routine (attrs: fingerprint_id, step, total) |
| `sensor.ai_routine_tracker_status` | Pyscript sensor | Last operation result (set by pyscript via `state.set()`); attrs include `eta_raw` (JSON for ETA template sensor) |
| `input_text.ai_routine_stage` | Input Text | Current routine position, e.g. "evening_weekday_living_room_bed:step_3_of_4" |
| `input_text.ai_routine_deviation` | Input Text | Last deviation description, e.g. "expected:bathroom actual:living_room" |
| `input_boolean.ai_routine_tracking_enabled` | Input Boolean | Kill switch (ON = active) |
| `input_boolean.ai_bedtime_predicted` | Input Boolean | Set ON when a bed-ending routine starts; arms bedtime automations |

## Dependencies

- **Pyscript:** `pyscript/routine_fingerprint.py` — fingerprint extraction and position tracking services
- **Pyscript:** `pyscript/presence_patterns.py` (Task 15) — frequency tables used for fingerprint building
- **Pyscript:** `pyscript/memory.py` — L2 memory for persisting fingerprints
- **Package:** `ai_test_harness.yaml` — test mode toggle
- **Hardware:** FP2 binary sensors (zone transition detection)
- **Helper files:** `helpers_input_text.yaml`, `helpers_input_boolean.yaml`

## Cross-References

- **ai_predictive_schedule.yaml** — reads `ai_bedtime_predicted` to arm bedtime timing logic
- **Bedtime blueprints** (bedtime_routine, bedtime_instant, etc.) — trigger on `ai_bedtime_predicted` turning on
- **ai_context_hot.yaml** — may reference routine stage for contextual awareness
- **Pyscript events:** Routine completion events consumed by predictive schedule engine

## Notes

- **Creep Factor Gate:** Routine positions are invisible to the user. They arm automations but never announce tracking details. "Heading to bed soon?" is acceptable; "I see you're in step 3 of your bedtime routine" is not.
- The pyscript module performs daily fingerprint refresh at 04:15 AM and real-time position tracking on FP2 zone transitions.
- ETA is computed from average step dwell times of the matched fingerprint.
- Includes a commented-out dashboard card definition for manual deployment.
