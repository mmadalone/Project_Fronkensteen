# Away Patterns — Departure/Return Prediction Engine

I-40 of the Voice Context Architecture. Queries the HA recorder database for historical `device_tracker` home/not_home transitions, builds duration and return-time frequency tables, stores patterns in L2 memory, and predicts return times when a household member is away. Combines recorder history with real-time state triggers for continuous prediction updates.

## Services

| Service | Parameters | Returns | Description |
|---------|-----------|---------|-------------|
| `pyscript.away_extract_cycles` | `lookback_days` | `{status, op, cycles_found, patterns_stored, elapsed_ms}` | Extract departure/arrival cycles from the HA recorder SQLite database. Builds frequency tables for departure times, durations, and return times. Stores results in L2 memory. `supports_response="only"` |
| `pyscript.away_predict_return` | `person` | `{status, op, predictions, elapsed_ms}` | Given current away state, predict return time and confidence for absent person(s). Uses frequency tables from L2, current time-of-day, and day-of-week weighting. `supports_response="only"` |
| `pyscript.away_rebuild_patterns` | _(none)_ | `{status, op, elapsed_ms}` | Full rebuild: delete old away patterns from L2, re-extract from recorder, re-store. Used for recovery or after recorder data changes. `supports_response="only"` |

## Triggers

| Trigger | Function | Condition |
|---------|----------|-----------|
| `@state_trigger("device_tracker.oppo_a60", "device_tracker.oppo_a38")` | `_on_tracker_change` | Logs departure/arrival events, runs prediction on state change. Departure debounced via `asyncio.sleep` using `ai_away_flap_debounce_seconds`. |
| `@time_trigger("cron(15 4 * * *)")` | `_daily_rebuild` | Daily full pattern rebuild at 04:15 (15 min after presence_patterns at 04:00) |
| `@time_trigger("cron(*/5 * * * *)")` | `_periodic_prediction_update` | Re-runs predictions every 5 minutes while someone is away |
| `@time_trigger("startup")` | `_startup` | Initializes status sensor, loads cached patterns from L2, syncs current tracker state |

## Key Functions

- `_query_recorder_sync()` — Runs raw SQL against the HA recorder SQLite database to extract state change history for device_tracker entities
- `_build_frequency_tables()` — Converts raw departure/arrival pairs into time-bucketed frequency distributions
- `_predict_return_for_person()` — Computes predicted return time using frequency table lookup, time-of-day weighting, and day-of-week adjustment
- `_log_departure()` / `_log_arrival()` — Real-time event logging with flap debounce

## State Dependencies

- `input_boolean.ai_away_patterns_enabled` — Kill switch
- `input_number.ai_away_lookback_days` — How many days of recorder history to query (default: 90)
- `input_number.ai_away_flap_debounce_seconds` — Debounce window for departure detection (prevents rapid home/away flapping)
- `input_number.ai_away_prediction_confidence_floor` — Minimum confidence threshold for predictions
- `device_tracker.oppo_a60` / `device_tracker.oppo_a38` — Phone-based device trackers for Miquel and Jessica

## Package Pairing

Pairs with `packages/ai_away_patterns.yaml` which defines the kill switch, lookback days, debounce window, confidence floor helpers, and the `sensor.ai_away_patterns_status` result entity.

## Called By

- **proactive_briefing.py** — reads away predictions for briefing content (e.g., "Jessica expected back around 6 PM")
- **ai_context_hot.yaml** — reads prediction helpers for hot context injection
- **Self-triggered** — state triggers on device_tracker entities and periodic cron for continuous prediction updates

## Notes

- Recorder access uses direct SQLite queries against `/config/home-assistant_v2.db` (the HA recorder database). This is read-only and uses a short-lived connection to avoid locking.
- The frequency table approach avoids ML complexity: it simply counts how often departures happen at each hour and how long they typically last, weighted by recency. Day-of-week patterns (weekday vs. weekend) are tracked separately.
- Departure debounce is critical: phone-based trackers can flap between home/not_home rapidly (e.g., weak WiFi). The configurable debounce window via `asyncio.sleep` prevents false departure logging.
- Daily rebuild at 04:15 is scheduled 15 minutes after `presence_patterns` (04:00) to avoid concurrent recorder access.
- All pattern data is stored in L2 memory with key prefix `away_pattern:` and 365-day expiry. Predictions are stored with shorter TTLs.
