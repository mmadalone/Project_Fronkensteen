![AI Away Patterns](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/ai_away_patterns-header.jpeg)

# AI Away Patterns — Return Time Prediction

Learns household departure and return patterns from recorder history and predicts when absent persons will return. Supports per-person predictions with confidence ranges, calendar fusion for travel buffers, and WiFi flap debouncing. Part of I-40 of the Voice Context Architecture.

## What's Inside

- **Template sensors:** 1 (`sensor.ai_away_duration`)
- **Pyscript sensors:** 2 (`sensor.ai_away_prediction`, `sensor.ai_entropy_correlation`)
- **Input helpers:** 14+ (moved to consolidated helper files) -- 2 booleans, 9 numbers, 1 text, 2 datetimes, plus per-person counters
- **Dashboard card:** Commented YAML for Lovelace integration

## Entity Reference

| Entity ID | Type | Purpose |
|---|---|---|
| `sensor.ai_away_prediction` | sensor (pyscript) | Return prediction with full attributes (I-54, created by pyscript `state.set()`) |
| `sensor.ai_away_duration` | template sensor | Minutes since departure (live-updating, occupancy-aware) |
| `sensor.ai_entropy_correlation` | sensor (pyscript) | G13 Phase 1.5 correlation analysis result |
| `input_boolean.ai_away_patterns_enabled` | input_boolean | Kill switch (ON = active) |
| `input_boolean.ai_entropy_correlation_enabled` | input_boolean | G13 Phase 1.5 kill switch |
| `input_number.ai_away_pattern_lookback_days` | input_number | Recorder query window for pattern extraction |
| `input_number.ai_away_pattern_min_samples` | input_number | Minimum departure cycles for valid predictions |
| `input_number.ai_away_travel_buffer_minutes` | input_number | Calendar fusion buffer for travel time |
| `input_number.ai_away_flap_debounce_seconds` | input_number | WiFi flap debounce window (G14 hardening) |
| `input_number.ai_away_prediction_update_minutes` | input_number | Periodic prediction update interval (G8) |
| `input_number.ai_away_ordinal_min_samples` | input_number | Ordinal filtering threshold (I-40b) |
| `input_number.ai_away_min_entropy_samples` | input_number | Min samples for entropy calculation (G13) |
| `input_number.ai_entropy_tier_low` | input_number | G13 Phase 1.5 low entropy threshold |
| `input_number.ai_entropy_tier_high` | input_number | G13 Phase 1.5 high entropy threshold |
| `input_text.ai_away_prediction_accuracy` | input_text | Rolling MAE accuracy metric (G12) |
| `input_datetime.ai_away_departed_miquel` | input_datetime | Miquel's departure timestamp |
| `input_datetime.ai_away_departed_jessica` | input_datetime | Jessica's departure timestamp |
| `counter.ai_away_trip_count_{slug}` | counter | Per-person daily trip counter (I-40b) |
| `sensor.ai_away_pattern_status` | sensor (pyscript) | Last operation result (created by pyscript, not this package) |

## Dependencies

- **Pyscript:** `pyscript/away_patterns.py` (3 services: `away_extract_cycles`, `away_predict_return`, `away_rebuild_patterns`)
- **Pyscript:** `pyscript/entropy_correlator.py` (G13 Phase 1.5 — service: `entropy_correlation_report`)
- **Pyscript:** `pyscript/memory.py` (L2 memory storage)
- **Package:** `ai_identity.yaml` (`sensor.occupancy_mode` for away/solo detection)
- **Package:** `ai_test_harness.yaml` (test mode toggle)
- **Helpers:** `helpers_counter.yaml` (trip counters — I-40b)

## Cross-References

- **Package:** `ai_context_hot.yaml` -- away prediction data injected into the Presence component when occupancy is away/solo
- **Pyscript triggers:** Device tracker state changes log departures/arrivals; daily rebuild at 04:15 AM; periodic updates while away

## Notes

- `sensor.ai_away_prediction` is created by pyscript `state.set()` (I-54) — no 255-char limit, full attributes. The template sensor was removed.
- The prediction sensor supports both single-person and multi-person predictions (the `predictions` array format).
- Duration sensor is occupancy-aware: tracks Miquel when `solo_jessica` or `away`, tracks Jessica when `solo_miquel`.
- I-40a hardening (G1-G12, G14) added debouncing, accuracy tracking, and periodic updates.
- I-40b multi-trip: ordinal tracking, enriched samples, ordinal gate (2026-03-18).
- G13 Phase 1.5: entropy-MAE correlation logger + weekly reporter (2026-03-26).
- Deployed: 2026-03-12.
