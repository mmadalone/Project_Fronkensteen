# User Preference Interview Engine

Provides services for agent-driven conversational onboarding -- LLM agents call `save_user_preference` to persist answers to L1 helpers (known keys like wake time) or L2 memory (freeform preferences). Tracks interview progress per user in a JSON helper and exposes status for agents to decide what to ask next. Part of I-36 of the Voice Context Architecture.

## Services

| Service | Parameters | Returns | Description |
|---------|-----------|---------|-------------|
| `pyscript.user_interview_save` | `user` (str, default "miquel"), `category` (str, required), `key` (str, required), `value` (str, required) | `{status, target (l1_text/l1_select/l1_datetime/l2), entity_id or l2_key, saved, elapsed_ms, user, category, key}` | Save a user preference. Routes to L1 helper or L2 memory based on category/key mapping. Called by LLM agents via tool function. |
| `pyscript.user_interview_status` | `user` (str, default "miquel") | `{status, user, completion_pct, filled, total, next_category, next_keys, categories: {cat: {total, done, remaining, complete}}}` | Return interview progress -- which categories/keys are filled vs empty. |
| `pyscript.user_interview_reset` | `user` (str, default "miquel") | `{status, user, action}` | Clear interview progress tracker for a user. Does NOT delete saved preferences from L1/L2. |
| `pyscript.user_interview_preseed` | `user` (str, default "miquel") | `{status, user, seeded_count, already_done, checked, seeded: [{category, key, source}], elapsed_ms}` | Scan L1 helpers and L2 memory for existing answers, pre-mark as done in progress. Call before first interview to skip already-answered topics. |

All services use `supports_response="only"`.

## Triggers

| Trigger | Function | Condition |
|---------|----------|-----------|
| `@time_trigger("startup")` | `_startup` | Initialize status sensor. |

## Key Functions

- `_save_preference(user, category, key, value)` -- Core routing: check L1 text map -> L1 select map -> L1 datetime map -> L2 fallback.
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
  - `input_datetime.ai_context_wake_time_weekday_{user}`, `_weekend_{user}`, `ai_context_bed_time_{user}`

## Package Pairing

Pairs with `packages/ai_user_interview.yaml` (interview mode toggle, progress tracker). Status sensor: `sensor.ai_user_interview_status`. Also writes to helpers defined in `packages/ai_context_hot.yaml` and other identity/schedule packages.

## Called By

- **LLM agents**: Via `save_user_preference` tool function during interview conversations
- **Agent system prompts**: Call `user_interview_status` to determine what to ask next
- **Automations**: Can call `user_interview_preseed` before starting an interview session
- **Depends on**: `pyscript/memory.py` (L2 for freeform preferences)

## Notes

- **Agent-driven**: The LLM conducts the interview naturally using its system prompt + hot context guidance. No pyscript-driven conversation loops.
- **9 categories, 38 keys**: identity (6), household (3), work (5), schedule (6), health (3), environment (4), media (6), communication (5), privacy (2).
- **L1 map**: Known helpers (wake time, bedtime, name, etc.) get set directly via HA service calls. Everything else falls back to L2 memory with key format `preference:{category}:{key}:{user}`.
- **Progress compaction**: Fully-complete categories stored as `"*"` wildcard instead of full key list to stay within 255-char `input_text` limit.
- **Preseed**: Scans all L1 mapped helpers and L2 preference keys to pre-mark already-answered topics, so the agent does not re-ask known information.
- **Reset vs delete**: `user_interview_reset` clears the progress tracker but does NOT delete saved preferences from L1 or L2. Use it to re-interview a user about topics they already answered.
