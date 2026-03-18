# Routine Fingerprinting and Real-Time Position Tracker

Builds greedy Markov chain fingerprints from Task 15 frequency tables to detect multi-zone routines, then tracks the user's live position within a recognized routine on each FP2 zone transition. Outputs routine stage, ETA, and deviation detection to helpers -- predictions stay invisible to the user. Part of Task 16 of the Voice Context Architecture.

## Services

| Service | Parameters | Returns | Description |
|---------|-----------|---------|-------------|
| `pyscript.routine_extract_fingerprints` | `time_bucket` (str, default "all"), `day_type` (str, default "all"), `min_chain_length` (int, default 3), `min_probability` (float, default 0.3) | `{status, op, fingerprints: [chain_dicts], count, stored, deleted, elapsed_ms}` | Analyze frequency tables from Task 15, build ordered zone chains (greedy Markov), store to L2. |
| `pyscript.routine_track_position` | `from_zone` (str, required), `to_zone` (str, required) | `{status, from_zone, to_zone, zone_sequence, time_bucket, day_type, routine_match: {fingerprint_id, step, total, eta_minutes} or null, deviation: {...} or null}` | Track a zone transition against known fingerprints. Update routine stage + ETA helpers, detect deviations. |

Both services use `supports_response="only"`.

## Triggers

| Trigger | Function | Condition |
|---------|----------|-----------|
| `@state_trigger` (8 FP2 binary sensors) | `_on_fp2_zone_change` | Detect zone transitions (OFF -> ON within 5-min window, 30s dwell filter). Feeds transitions into `routine_track_position`. |
| `@time_trigger("cron(15 4 * * *)")` | `_daily_fingerprint_refresh` | Daily fingerprint refresh at 04:15 AM (15 min after Task 15's 04:00 rebuild). |
| `@time_trigger("startup")` | `_startup` | Load known fingerprints from L2. If none exist, schedule bootstrap extraction after 180s delay. |

## Key Functions

- `_build_chains(trans_cache, dwell_cache, ...)` -- Build fingerprint chains by greedily following highest-probability paths. Deduplicates, filters sub-chains, caps at 10. `@pyscript_compile`.
- `_match_fingerprints(zone_sequence, fingerprints, time_bucket, day_type)` -- Match zone sequence against known fingerprints. Finds latest occurrence of chain start, counts sequential matches. Requires >= 2 zone match. `@pyscript_compile`.
- `_compute_eta(fingerprint, current_step)` -- Estimated minutes remaining in the routine from current step. `@pyscript_compile`.
- `_parse_pattern_key(key)` -- Parse L2 pattern key format handling zone names with underscores. `@pyscript_compile`.
- `_load_frequency_tables()` -- Load Task 15 transition + dwell frequency tables from L2.
- `_load_fingerprints_from_l2()` -- Load known fingerprints from L2 into module cache.
- `_update_routine_helpers(match, test_mode)` -- Update `ai_routine_stage` and `ai_routine_eta_raw` helpers.
- `_handle_deviation(deviation, test_mode)` -- Fire `ai_routine_deviation` event when expected zone does not match actual.
- `_check_bedtime_prediction(match, test_mode)` -- Set `ai_bedtime_predicted` ON when a bed-ending fingerprint is detected.
- `_prune_window()` -- Remove transitions older than 60 min from sliding window.

## State Dependencies

- `input_boolean.ai_routine_tracking_enabled` -- Kill switch
- `input_boolean.ai_test_mode` -- Test mode
- `input_boolean.ai_fp2_zone_*_enabled` -- Per-zone enable toggles
- `input_text.ai_routine_stage` -- Output: current routine position (e.g., `evening_weekday_kitchen_bed:step_3_of_5`)
- `input_text.ai_routine_eta_raw` -- Output: JSON with ETA minutes, fingerprint ID, step, total
- `input_text.ai_routine_deviation` -- Output: deviation description
- `input_boolean.ai_bedtime_predicted` -- Output: set ON when bed-ending routine detected
- 8 FP2 binary sensors -- Zone presence detection

## Package Pairing

Pairs with `packages/ai_routine_tracker.yaml` (kill switch, routine stage, ETA raw, deviation, bedtime predicted). Status sensor: `sensor.ai_routine_tracker_status`.

## Called By

- **Other pyscript**: `predictive_schedule.py` reads fingerprint durations from L2 for bedtime calculation; `presence_identity.py` benefits from routine context
- **Events fired**: `ai_routine_completed` (triggers feedback in predictive_schedule.py), `ai_routine_deviation` (can trigger automations)
- **Depends on**: `pyscript/presence_patterns.py` (Task 15 frequency tables in L2), `pyscript/memory.py` (L2)

## Notes

- **Creep factor gate**: Predictions are INVISIBLE to the user. They arm automations (bedtime prediction) but are NEVER announced as "I detected your routine."
- **Greedy Markov chains**: For each starting zone in each time/day context, follow highest-probability transition until probability drops below threshold or cycle detected.
- **Max 10 fingerprints**: Cap prevents noisy data explosion.
- **Position matching target**: <50ms (runs on every zone transition).
- **Sliding window**: 60-minute window of recent transitions for sequence matching.
- **Deviation handling**: When expected next zone does not match actual zone, fires event, resets bedtime prediction, trims sliding window to fresh start.
- **Bedtime timeout**: `ai_bedtime_predicted` auto-resets after 2 hours if routine hasn't completed.
- **Chain quality sorting**: `probability * chain_length` (longer + higher-probability chains ranked first).
- **Sub-chain filtering**: If chain X is a contiguous sub-sequence of a longer chain Y in the same time context, X is removed.
- **Refresh guard**: `_fp_refresh_in_progress` flag disables FP2 triggers during fingerprint extraction.
