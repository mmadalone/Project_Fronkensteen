# AI Presence Patterns

Provides the helper entities and template sensor for presence-based pattern recognition and zone transition predictions. Builds frequency tables from FP2 zone transitions and predicts the next likely zone with probability and confidence scores. Part of Task 15 of the Voice Context Architecture.

## What's Inside

| Type | Count |
|------|-------|
| Template sensors | 1 |
| Input helpers (external) | 4 |
| Pyscript sensors (dynamic) | 1 |

## Entity Reference

| Entity ID | Type | Purpose |
|-----------|------|---------|
| `sensor.ai_predicted_next_zone` | Template sensor | Human-readable prediction, e.g. "bed (67%)" — with zone, probability, confidence, and sample_count attributes |
| `sensor.ai_presence_pattern_status` | Pyscript sensor | Last operation result (set by pyscript via `state.set()`) |
| `input_boolean.ai_presence_patterns_enabled` | Input Boolean | Kill switch (ON = active) |
| `input_number.ai_presence_pattern_lookback_days` | Input Number | Recorder query window for historical transitions |
| `input_number.ai_presence_pattern_min_samples` | Input Number | Minimum transitions required for a valid prediction |
| `input_text.ai_predicted_next_zone_raw` | Input Text | JSON payload from pyscript for the template sensor |

## Dependencies

- **Pyscript:** `pyscript/presence_patterns.py` — 3 services (extract, predict, rebuild), state trigger on FP2 zones, daily rebuild at 04:00
- **Pyscript:** `pyscript/memory.py` — L2 memory for persisting frequency tables
- **Package:** `ai_test_harness.yaml` — test mode toggle
- **Hardware:** FP2 binary sensors (zone transition detection)
- **Helper files:** `helpers_input_boolean.yaml`, `helpers_input_number.yaml`, `helpers_input_text.yaml`

## Cross-References

- **ai_routine_tracker.yaml** / `pyscript/routine_fingerprint.py` — consumes frequency tables for routine fingerprinting
- **ai_predictive_schedule.yaml** / `pyscript/predictive_schedule.py` — uses presence data as L1 input for schedule confidence
- **ai_presence_identity.yaml** / `pyscript/presence_identity.py` — calls `presence_predict_next()` for Markov tiebreaks
- **ai_context_hot.yaml** — may reference predicted zone data for hot context injection

## Notes

- Template sensor attributes expose `zone`, `probability`, `confidence`, and `sample_count` parsed from the raw JSON helper.
- The pyscript module performs incremental updates on each FP2 zone transition and a full rebuild daily at 04:00.
- Includes a commented-out dashboard card definition for manual deployment.
