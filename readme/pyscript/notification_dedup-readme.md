# Notification Deduplication Engine

Prevents duplicate TTS announcements when multiple delivery systems (proactive briefing, calendar push, notification follow-me) try to announce the same information. Uses L2 hash-key lookups with TTL-based expiry and a fail-open policy to ensure announcements are never missed. Part of the DC-9 Voice Context Architecture (Task 14).

## Services

| Service | Parameters | Returns | Description |
|---------|-----------|---------|-------------|
| `pyscript.dedup_check` | `topic` (str, required), `source` (str, required), `ttl_hours` (float, default 0) | `{status, op, duplicate, reason, hash_key, topic, original_source, original_time, test_mode, elapsed_ms}` | Check if a topic has already been announced recently. Uses exact-key L2 lookup for speed (target <100ms). Fails open if L2 is unavailable. |
| `pyscript.dedup_register` | `topic` (str, required), `source` (str, required), `ttl_hours` (float, default 0) | `{status, op, registered, hash_key, topic, source, test_mode, test_skip, elapsed_ms}` | Register a successful announcement in L2 memory. Called AFTER TTS playback is queued. Idempotent. |
| `pyscript.dedup_announce` | `topic` (str, required), `source` (str, required), `ttl_hours` (float, default 0), `text` (str, required), `voice` (str, required), `voice_id` (str, default ""), `priority` (int, default 3), `target_mode` (str, default "presence"), `volume_level` (float, optional), `skip_dedup` (bool, default false), `chime_path` (str, default ""), `restore_volume` (bool, default false), `volume_restore_delay` (int, default 8), `duck` (bool, default true), `metadata` (dict, optional) | `{status, op, announced, topic, source, duplicate_detected, test_mode, elapsed_ms}` | Combined check + announce + register. Blueprints call this instead of managing check/register separately. When `skip_dedup` is true, bypasses dedup entirely. `duck` controls whether background media is lowered during TTS — passed through to `tts_queue_speak`. |

All three services use `supports_response="only"`.

## Triggers

| Trigger | Function | Condition |
|---------|----------|-----------|
| `@time_trigger("startup")` | `dedup_startup` | Initialize dedup sensor on HA startup |
| `@time_trigger("cron(5 0 * * *)")` | `dedup_daily_housekeeping` | Reset blocked counter and purge stale L2 entries older than `ai_dedup_cleanup_hours` (default 48h) |

## Key Functions

- `_normalize_topic(topic)` -- Lowercase, spaces to underscores, strip special chars. `@pyscript_compile`.
- `_build_hash_key(topic_normalized, date_str)` -- Build dedup hash key: `announced:{topic}_{YYYYMMDD}`. `@pyscript_compile`.
- `_parse_dedup_value(value)` -- Parse stored dedup value to `(source, timestamp)`. `@pyscript_compile`.
- `_is_within_ttl(created_at_iso, ttl_hours, now_utc_iso)` -- Check if created_at is within TTL window. `@pyscript_compile`.
- `_dedup_check_internal(topic, source, ttl_hours, test_mode)` -- Core check logic. Checks today AND yesterday hash keys for cross-midnight TTL.
- `_dedup_register_internal(topic, source, ttl_hours, test_mode)` -- Core register logic. Writes announcement hash to L2.
- `_l2_get`, `_l2_set`, `_l2_forget`, `_l2_search` -- L2 memory wrappers with error handling.
- `_resolve_ttl(ttl_hours)` -- Resolve TTL from parameter or helper (helper stores minutes, converts to hours).
- `_increment_blocked_counter()` -- Increment `input_number.ai_dedup_blocked_count`.

## State Dependencies

- `input_boolean.ai_dedup_enabled` -- Kill switch (off = skip all dedup)
- `input_boolean.ai_test_mode` -- Test mode (detect + log duplicates but never suppress)
- `input_number.ai_dedup_default_ttl` -- Default TTL in minutes (converted to hours internally)
- `input_number.ai_dedup_blocked_count` -- Daily blocked-duplicates counter
- `input_number.ai_dedup_cleanup_hours` -- Max age in hours for daily L2 cleanup (default 48)

## Package Pairing

Pairs with `packages/ai_notification_dedup.yaml` which defines the kill switch, default TTL, blocked counter, and test harness toggle. Status sensor: `sensor.ai_dedup_status`.

## Called By

- **Blueprints**: `proactive_briefing.yaml`, `notification_follow_me.yaml`, `calendar_push.yaml` -- via `dedup_announce`
- **Other pyscript**: `proactive_briefing.py` -- via `dedup_announce` for briefing delivery
- **Depends on**: `pyscript/memory.py` (L2), `pyscript/tts_queue.py` (TTS playback)

## Notes

- **Fail-open policy**: If L2 is unreachable for both today and yesterday keys, the announcement is allowed (better to repeat than miss).
- **Cross-midnight**: Checks both today's and yesterday's hash keys to handle TTL windows spanning midnight.
- **Test mode**: Duplicates are detected and logged but NEVER suppressed -- ensures announcements always play during testing.
- **Hash key format**: `announced:{topic_slug}_{YYYYMMDD}` -- exact key lookup, no full-text search scan.
- **Performance target**: <100ms per check (two sequential exact-key L2 lookups).
- **Cleanup**: Daily cron at 00:05 resets blocked counter and purges L2 entries older than 48h as a safety net.
