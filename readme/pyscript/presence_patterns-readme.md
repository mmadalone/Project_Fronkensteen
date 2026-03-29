# Presence Pattern Extraction and Markov Prediction

Queries the HA recorder database (read-only) for historical FP2 zone transitions, builds Markov chain frequency tables by time-of-day and day-type, and stores patterns in L2 memory. Provides a prediction service returning probability distributions for next-zone given current zone, time, and day type. Also includes sleep detection logging and passive meal detection. Part of Task 15 of the Voice Context Architecture.

## Services

| Service | Parameters | Returns | Description |
|---------|-----------|---------|-------------|
| `pyscript.presence_extract_transitions` | `lookback_days` (int, default 0 = helper), `min_confidence` (float, default 0.1) | `{status, op, transitions, patterns, zones_seen, total_states, elapsed_ms}` | Extract zone transitions from recorder DB, build frequency tables, store to L2. |
| `pyscript.presence_predict_next` | `current_zone` (str, required), `time_bucket` (str, auto-detected), `day_type` (str, auto-detected) | `{status, current_zone, time_bucket, day_type, predictions: [{zone, probability, avg_eta_minutes}], confidence, sample_count}` | Predict next zone from frequency table. Returns probability distribution. |
| `pyscript.presence_rebuild_patterns` | (none) | `{status, op, deleted, transitions, patterns, zones_seen, total_states, elapsed_ms}` | Full rebuild: delete old patterns, re-extract from recorder, re-store. Guards against concurrent rebuilds. |
| `pyscript.sleep_detect_log` | (none) | `{status, op, duration_min, confidence}` | Log sleep detection event to L2 with duration and confidence scoring (bed presence + phone charging + zone absence). |
| `pyscript.meal_passive_log` | (none) | `{status, op, meal_type, ...}` | Log passive meal detection to L2. Determines meal type from time of day. |

All services use `supports_response="only"`.

## Triggers

| Trigger | Function | Condition |
|---------|----------|-----------|
| `@state_trigger` (8 FP2 binary sensors) | `_on_fp2_change` | Incremental update: detect zone transitions (OFF -> ON within window), update frequency tables in local cache + L2. Per-zone debounce. |
| `@time_trigger("cron(0 4 * * *)")` | `_daily_rebuild` | Daily full pattern rebuild at 04:00 AM. |
| `@time_trigger("startup")` | `_startup` | Initialize: load pattern cache from L2. If cache empty, schedule full rebuild after 90s delay. |

## Key Functions

- `_extract_data_sync(lookback_days, transition_window_sec, entity_map)` -- Read-only SQLite query against recorder DB. `@pyscript_executor`.
- `_build_tables(transitions, dwells)` -- Build frequency tables from extracted transition/dwell data. `@pyscript_compile`.
- `_compute_dwell_stats(durations)` -- Compute avg, median, min, max dwell statistics. `@pyscript_compile`.
- `_predict_from_cache(current_zone, time_bucket, day_type, min_samples)` -- Local cache prediction with fallback through broader time/day contexts.
- `_parse_pattern_key(key)` -- Parse L2 pattern key handling zone names with underscores. `@pyscript_compile`.
- `_load_cache_from_l2()` -- Load transition + dwell frequency tables from L2 into local cache.
- `_update_prediction_sensor(current_zone)` -- Write top prediction to `input_text.ai_predicted_next_zone_raw`.
- `_get_time_bucket(hour)` / `_get_day_type(weekday)` -- Map hour/weekday to bucket/type strings. `@pyscript_compile`.

## State Dependencies

- `input_boolean.ai_presence_patterns_enabled` -- Kill switch
- `input_boolean.ai_test_mode` -- Test mode (mock predictions, no cache/L2 writes)
- `input_number.ai_presence_pattern_lookback_days` -- Days of recorder history to query (default 30)
- `input_number.ai_presence_pattern_min_samples` -- Minimum samples for confident predictions
- `input_number.ai_presence_transition_window` -- Seconds between zone OFF and ON to count as transition (default 300)
- `input_boolean.ai_fp2_zone_*_enabled` -- Per-zone enable toggles
- `input_datetime.ai_sleep_start` / `ai_sleep_end` -- Sleep detection timestamps
- 8 FP2 binary sensors -- Zone presence detection

## Package Pairing

Pairs with `packages/ai_presence_patterns.yaml` (lookback days, min samples, transition window, zone toggles). Output sensor: `sensor.ai_presence_pattern_status`. Prediction output: `input_text.ai_predicted_next_zone_raw`. Also reads from `packages/ai_sleep_detection.yaml` (sleep start/end).

## Called By

- **Other pyscript**: `routine_fingerprint.py` reads frequency tables from L2 for chain building; `presence_identity.py` calls `presence_predict_next` for Markov tiebreaks; `predictive_schedule.py` reads frequency data for bedtime estimation
- **Automations**: `ai_sleep_detection` automation calls `sleep_detect_log`; `ai_meal_detection` calls `meal_passive_log`
- **Depends on**: `pyscript/memory.py` (L2), HA recorder database (SQLite, read-only)

## Notes

- **Recorder DB access**: All DB queries use `sqlite3` in URI mode (`mode=ro`) to ensure read-only access. Queries run via `asyncio.to_thread` to never block the event loop.
- **Frequency table format**: L2 keys follow `pattern:transition:{zone}:{time_bucket}:{day_type}` with JSON value `{to_zone: count}`. Dwell tables use `pattern:dwell:...` with stats dict.
- **Incremental updates**: Zone transitions detected in real-time update both local cache and L2 without a full rebuild.
- **Rebuild guard**: `_rebuild_in_progress` flag prevents concurrent rebuilds.
- **Per-zone debounce**: `ZONE_DEBOUNCE_SEC` suppresses FP2 flapping within the debounce window.
- **Time buckets**: late_night (0-5), morning (6-11), afternoon (12-17), evening (18-23).
- **Prediction fallback**: If no data for exact (zone, bucket, day), falls back through broader contexts.
- **L2 expiration**: Pattern entries persist ~1 year (365 days), refreshed daily at 04:00.
