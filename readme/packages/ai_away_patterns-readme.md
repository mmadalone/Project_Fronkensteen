# AI Away Patterns — Return Time Prediction

Learns household departure and return patterns from recorder history and predicts when absent persons will return. Supports per-person predictions with confidence ranges, calendar fusion for travel buffers, and WiFi flap debouncing. Part of I-40 of the Voice Context Architecture.

## What's Inside

- **Template sensors:** 2 (`sensor.ai_away_prediction`, `sensor.ai_away_duration`)
- **Input helpers:** 8 (moved to consolidated helper files) -- 1 boolean, 4 numbers, 2 texts, 2 datetimes
- **Dashboard card:** Commented YAML for Lovelace integration

## Entity Reference

| Entity ID | Type | Purpose |
|---|---|---|
| `sensor.ai_away_prediction` | template sensor | Human-readable return prediction with time range and confidence |
| `sensor.ai_away_duration` | template sensor | Minutes since departure (live-updating, occupancy-aware) |
| `input_boolean.ai_away_patterns_enabled` | input_boolean | Kill switch (ON = active) |
| `input_number.ai_away_pattern_lookback_days` | input_number | Recorder query window for pattern extraction |
| `input_number.ai_away_pattern_min_samples` | input_number | Minimum departure cycles for valid predictions |
| `input_number.ai_away_travel_buffer_minutes` | input_number | Calendar fusion buffer for travel time |
| `input_number.ai_away_flap_debounce_seconds` | input_number | WiFi flap debounce window (G14 hardening) |
| `input_number.ai_away_prediction_update_minutes` | input_number | Periodic prediction update interval (G8) |
| `input_text.ai_away_prediction_raw` | input_text | JSON prediction data from pyscript |
| `input_text.ai_away_prediction_accuracy` | input_text | Rolling MAE accuracy metric (G12) |
| `input_datetime.ai_away_departed_miquel` | input_datetime | Miquel's departure timestamp |
| `input_datetime.ai_away_departed_jessica` | input_datetime | Jessica's departure timestamp |
| `sensor.ai_away_pattern_status` | sensor (pyscript) | Last operation result (created by pyscript, not this package) |

## Dependencies

- **Pyscript:** `pyscript/away_patterns.py` (3 services: `away_extract_cycles`, `away_predict_return`, `away_rebuild_patterns`)
- **Pyscript:** `pyscript/memory.py` (L2 memory storage)
- **Package:** `ai_identity.yaml` (`sensor.occupancy_mode` for away/solo detection)
- **Package:** `ai_test_harness.yaml` (test mode toggle)

## Cross-References

- **Package:** `ai_context_hot.yaml` -- away prediction data injected into the Presence component when occupancy is away/solo
- **Pyscript triggers:** Device tracker state changes log departures/arrivals; daily rebuild at 04:15 AM; periodic updates while away

## Notes

- The prediction sensor supports both single-person and multi-person predictions (the `predictions` array format).
- Duration sensor is occupancy-aware: tracks Miquel when `solo_jessica` or `away`, tracks Jessica when `solo_miquel`.
- I-40a hardening (G1-G12, G14) added debouncing, accuracy tracking, and periodic updates.
- Deployed: 2026-03-12.
