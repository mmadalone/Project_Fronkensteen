# User Preference Interview Engine

Provides services for agent-driven conversational onboarding -- LLM agents call `save_user_preference` to persist answers to L1 helpers (known keys like wake time) or L2 memory (freeform preferences). Tracks interview progress per user in a JSON helper and exposes status for agents to decide what to ask next. Part of I-36 of the Voice Context Architecture.

## Services

| Service | Parameters | Returns | Description |
|---------|-----------|---------|-------------|
| `pyscript.user_interview_save` | `user` (str, default "miquel"), `category` (str, required), `key` (str, required), `value` (str, required) | `{status, target (l1_text/l1_select/l1_datetime/l2), entity_id or l2_key, saved, elapsed_ms, user, category, key}` | Save a user preference. Routes to L1 helper or L2 memory based on category/key mapping. Called by LLM agents via tool function. |
| `pyscript.user_interview_status` | `user` (str, default "miquel") | `{status, user, completion_pct, filled, total, next_category, next_keys, categories: {cat: {total, done, remaining, complete}}}` | Return interview progress -- which categories/keys are filled vs empty. |
| `pyscript.user_interview_reset` | `user` (str, default "miquel") | `{status, user, action}` | Clear interview progress tracker for a user. Does NOT delete saved preferences from L1/L2. |
| `pyscript.user_interview_preseed` | `user` (str, default "miquel") | `{status, user, seeded_count, already_done, checked, seeded: [{category, key, source}], elapsed_ms}` | Scan L1 helpers and L2 memory for existing answers, pre-mark as done in progress. Call before first interview to skip already-answered topics. |
| `pyscript.user_interview_import` | `file` (str, required) | `{status, user, file, saved, skipped, errors, elapsed_ms}` | Import interview answers from a YAML file in `/config/interview/`. Batch-optimized: direct L1/auto-detect/L2 routing, single progress write, single sensor refresh. |
| `pyscript.user_interview_auto_import` | *(none)* | `{imported: [filenames], skipped: [filenames]}` | Scan `/config/interview/` for `interview_*.yaml` files and import any matching a configured `person.*` entity. Called on HA startup by the blueprint. |
| `pyscript.user_interview_refresh_preferences` | `user` (str, default active user) | `{status, user}` | Rebuild `sensor.ai_preferences_context` from auto-discovered helpers. Called automatically after save/import, or manually. |
| `pyscript.user_interview_exchanges` | `user` (str, default "miquel"), `limit` (int, default 20) | `{status, user, count, exchanges: [...]}` | Return recent interview exchange logs from L2 memory. |

`user_interview_save`, `_status`, `_reset`, `_preseed`, `_import`, `_exchanges` use `supports_response="only"`. `_auto_import` and `_refresh_preferences` use `supports_response="optional"`.

## Triggers

| Trigger | Function | Condition |
|---------|----------|-----------|
| `@time_trigger("startup")` | `_startup` | Initialize status sensor. |

## Key Functions

- `_save_preference(user, category, key, value)` -- Core routing: L1 text map -> L1 select map -> L1 datetime map -> auto-detect (`input_text.ai_context_user_{key}_{user}`) -> L2 fallback.
- `_format_preferences_text(user)` -- Auto-discover all `input_text.ai_context_user_*_{user}` helpers via `state.names(domain="input_text")`, skip identity keys (`_SKIP_IN_PREFS`), output sorted `key: value` pairs.
- `_scan_interview_directory()` -- `@pyscript_executor`. Scan `/config/interview/` for `interview_*.yaml` files, return `[{file, user}]`.
- `_save_to_l1_text(entity_id, value)` -- Save to `input_text` helper via `set_value`.
- `_save_to_l1_select(entity_id, value)` -- Save to `input_select` helper via `select_option`.
- `_save_to_l1_datetime(entity_id, value)` -- Save to `input_datetime` helper via `set_datetime`. Normalizes HH:MM to HH:MM:SS.
- `_load_progress(user)` / `_save_progress(user, progress)` -- Read/write interview progress from `input_text.ai_interview_progress` JSON. Compacts fully-complete categories to `"*"` to stay under 255 chars.
- `_mark_done(user, category, key)` -- Mark a specific key as completed in progress tracking.
- `_l1_has_value(entity_id, domain_hint)` -- Check if an L1 helper has a meaningful non-empty value.

## State Dependencies

- `input_boolean.ai_interview_mode` -- Gates hot context injection (agents see interview guidance)
- `input_boolean.ai_test_mode` -- Test mode
- `input_text.ai_interview_progress` -- JSON progress tracker per user (255 char limit, uses `"*"` compaction)
- L1 mapped helpers (read/write):
  - `input_text.ai_context_user_name_{user}`, `_name_spoken_{user}`, `_languages_{user}`
  - `input_text.ai_context_household`, `ai_context_pets`
  - `input_text.ai_work_calendar_keywords`
  - `input_select.ai_context_preferred_language_{user}`
  - `input_datetime.ai_context_wake_time_weekday_{user}`, `_weekend_{user}`, `_alt_weekday_{user}`, `ai_context_bed_time_{user}`
  - `input_text.ai_context_wake_time_alt_days_{user}` — which days use alt wake time (English 3-letter CSV)

## Sensors

| Sensor | Description |
|--------|-------------|
| `sensor.ai_user_interview_status` | Interview engine status (idle/importing/error). Attributes: last op, user, saved/skipped/error counts. |
| `sensor.ai_preferences_context` | Auto-discovered user preferences for hot context injection. Attribute `context` contains formatted `key: value` block. Auto-refreshed on save/import/startup. |

## Package Pairing

Pairs with `packages/ai_user_interview.yaml` (interview mode toggle, progress tracker). Also writes to helpers defined in `packages/ai_context_hot.yaml` and other identity/schedule packages.

## Called By

- **LLM agents**: Via `save_user_preference` tool function during interview conversations
- **Agent system prompts**: Call `user_interview_status` to determine what to ask next
- **Automations**: Can call `user_interview_preseed` before starting an interview session
- **Depends on**: `pyscript/memory.py` (L2 for freeform preferences)

## Notes

- **Agent-driven**: The LLM conducts the interview naturally using its system prompt + hot context guidance. No pyscript-driven conversation loops.
- **9 categories, 38 keys**: identity (6), household (3), work (5), schedule (6), health (3), environment (4), media (6), communication (5), privacy (2).
- **L1 map**: Known helpers (wake time, bedtime, name, etc.) get set directly via HA service calls. Everything else falls back to L2 memory with key format `preference:{category}:{key}:{user}`. Includes `wake_alt_weekday` (input_datetime) and `wake_alt_days` (input_text) for per-day wake time variation.
- **Day-name normalization**: `_DAY_ABBREV_NORM` translates Spanish day abbreviations on ingest (`jue→thu`, `vie→fri`, `lun→mon`, etc.) since `strftime` uses C/en_US locale. Applied in both `user_interview_save` and `user_interview_import` paths via `_normalize_l1_value()`.
- **Auto-detect**: If no L1 map entry exists but `input_text.ai_context_user_{key}_{user}` exists as a helper, writes directly to it. New convention-named helpers are auto-writable AND auto-discoverable with zero code changes.
- **Auto-discovery sensor**: `sensor.ai_preferences_context` scans all `input_text.ai_context_user_*_{user}` entities, skips identity keys (name, name_spoken, languages), outputs sorted `key: value` pairs for hot context. Adding a new preference = create the helper.
- **Auto-import on startup**: Blueprint fires `pyscript.user_interview_auto_import` on HA start. Scans `/config/interview/` for `interview_*.yaml` files, imports any matching a `person.*` entity.
- **Batch import optimization**: File import uses direct routing (skip `_save_preference` overhead), single progress write at end, no exchange logs, single sensor refresh. 50 keys import in ~2-3s (was 90s+).
- **Progress compaction**: Fully-complete categories stored as `"*"` wildcard instead of full key list to stay within 255-char `input_text` limit.
- **Preseed**: Scans all L1 mapped helpers and L2 preference keys to pre-mark already-answered topics, so the agent does not re-ask known information.
- **Reset vs delete**: `user_interview_reset` clears the progress tracker but does NOT delete saved preferences from L1 or L2. Use it to re-interview a user about topics they already answered.
