# Memory — Core L2 Persistent Memory Engine

The central persistence layer for the entire Voice Context Architecture. Manages the SQLite-backed memory database (`memory.db`) with key-value CRUD, FTS5 full-text search, optional sqlite-vec semantic embeddings, cross-key linking via a relationship graph, TTL-based expiry with grace periods, cold-storage archiving, and automatic daily housekeeping. Every other pyscript module writes to and reads from this module.

## Services

| Service | Parameters | Returns | Description |
|---------|-----------|---------|-------------|
| `pyscript.memory_set` | `key`, `value`, `scope`, `expiration_days`, `tags`, `force_new` | `{status, op, key, value, scope, tags, expires_at, key_exists, force_new_applied}` | Create or update a memory entry. Duplicate-tag detection blocks new keys with overlapping tags unless `force_new=True`. Auto-links to related entries by tag overlap. `supports_response="only"` |
| `pyscript.memory_get` | `key` | `{status, op, key, value, scope, tags, created_at, last_used_at, expires_at}` | Fetch a memory by exact key. Updates `last_used_at`. Returns `expired` with payload if entry exists but is past TTL. Returns `ambiguous` with suggestions if key not found but similar entries exist. `supports_response="only"` |
| `pyscript.memory_search` | `query`, `limit` | `{status, op, query, count, results, blended}` | FTS5 search across key/value/tags. Falls back to LIKE if MATCH fails. When sqlite-vec is available and blend weight > 0, blends FTS scores with semantic similarity. `supports_response="only"` |
| `pyscript.memory_forget` | `key` | `{status, op, key, deleted}` | Delete a memory by key. Also removes relationships and vec entries. Returns `ambiguous` with suggestions if key not found. `supports_response="only"` |
| `pyscript.memory_related` | `key`, `limit`, `depth` | `{status, op, key, count, results}` | Traverse the relationship graph to find related memories. Supports depth 1-3 (direct, friends-of-friends, 3-hop). `supports_response="only"` |
| `pyscript.memory_link` | `from_key`, `to_key`, `rel_type` | `{status, op, from_key, to_key, rel_type}` | Manually create a bidirectional relationship between two memories. Types: `manual`, `tag_overlap`, `content_match`. `supports_response="only"` |
| `pyscript.memory_purge_expired` | `grace_days` | `{status, op, grace_days, removed}` | Remove expired entries older than the grace period. Manual calls default to 0 days; daily housekeeping uses 10 days. `supports_response="only"` |
| `pyscript.memory_reindex_fts` | _(none)_ | `{status, op, removed, inserted}` | Rebuild the FTS5 index from the main table. Drops and recreates `mem_fts` with triggers. `supports_response="only"` |
| `pyscript.memory_health_check` | _(none)_ | `{status, op, rows, expired, fts_rows, rel_count, db_size_mb, record_limit, db_max_mb, threshold_exceeded, archived_count, archive_enabled}` | Health check with threshold comparison. Fires `ai_memory_threshold_exceeded` event if limits breached. Also initializes sqlite-vec on startup. `supports_response="only"` |
| `pyscript.memory_archive` | `dry_run` | `{status, op, archived, before_count, after_count, target_count, protected_skipped, dry_run}` | I-42 Phase 2: Move coldest unprotected entries to `mem_archive`. Reads target_pct, recency_days, and protection_tags from helpers. `supports_response="only"` |
| `pyscript.memory_archive_search` | `query`, `limit`, `scope` | `{status, op, query, count, results}` | LIKE-based search on archived entries (no FTS on cold storage). `supports_response="only"` |
| `pyscript.memory_archive_restore` | `key`, `reembed` | `{status, op, key, reembedded}` | Move an archived entry back to active `mem` table. Optionally re-embeds the vector. `supports_response="only"` |
| `pyscript.memory_archive_stats` | _(none)_ | `{status, op, count, oldest_archived, newest_archived}` | Return count and date range of archived entries. `supports_response="only"` |
| `pyscript.memory_browse` | `query`, `limit` | `{status, op, query, count}` | Dashboard search: writes formatted markdown results to `sensor.ai_memory_browse`. Reads query from `input_text.ai_memory_search_query` if not provided. `supports_response="only"` |
| `pyscript.memory_edit` | _(none)_ | `{status, op, key, ...}` | Dashboard: reads key/value/tags/scope from edit helpers and calls `memory_set`. `supports_response="only"` |
| `pyscript.memory_delete` | _(none)_ | `{status, op, key, deleted}` | Dashboard: reads key from edit helper and calls `memory_forget`. `supports_response="only"` |
| `pyscript.memory_load` | _(none)_ | `{status, op, key, value, ...}` | Dashboard: loads a memory entry into the edit field helpers. `supports_response="only"` |
| `pyscript.memory_vec_health_check` | _(none)_ | `{status, vec_available, vec0_path, dimensions}` | Test-load `vec0.so` and report status. `supports_response="only"` |
| `pyscript.memory_embed` | `key` | `{status, key, dimensions, tokens_used}` | Generate and store a vector embedding for a single memory entry via `llm_direct_embed`. `supports_response="only"` |
| `pyscript.memory_embed_batch` | `batch_size`, `scope` | `{status, embedded, failed, tokens_used, batch_size, reindexed}` | Embed all entries missing vectors. If `ai_embedding_reindex_needed` is ON, drops and recreates `mem_vec` first. `supports_response="only"` |
| `pyscript.memory_semantic_search` | `query`, `limit` | `{status, op, query, count, results}` | Pure semantic (vector similarity) search. Does not blend with FTS5. `supports_response="only"` |
| `pyscript.memory_semantic_autolink` | `batch_size`, `threshold` | `{status, op, linked, keys_processed}` | Create `content_match` relationships between semantically similar memories via vec0 KNN. Processes embeddings without content_match edges. `supports_response="only"` |
| `pyscript.memory_archive_browse` | `query`, `limit` | `{status, op, query, count}` | Dashboard: search archived memory and write formatted markdown to `sensor.ai_memory_archive_browse`. `supports_response="optional"` |
| `pyscript.memory_related_browse` | `key` | `{status, op, key, count}` | Dashboard: show related entries for a key and write to `sensor.ai_memory_related_browse`. `supports_response="optional"` |
| `pyscript.memory_context_force_refresh` | _(none)_ | `{status, op}` | Force-refresh `sensor.ai_memory_context` immediately (used at handoff time). `supports_response="optional"` |
| `pyscript.memory_todo_sync` | `todo_entity`, `scope_filter`, `tag_filter`, `query_filter`, `max_age_days`, `max_items`, `include_important`, `default_scope` | `{status, op, ...}` | Bidirectional sync between L2 memory and a HA todo list. Completed synced items delete the L2 entry. `supports_response="optional"` |
| `pyscript.budget_history_record` | `date`, `usage_usd`, `exchange_rate`, `llm_calls`, `llm_tokens`, `tts_chars`, `stt_calls`, `serper_credits`, `model_cost_eur`, `model_breakdown`, `music_generations` | `{status, op, ...}` | Record a daily usage row into `budget_history` table. Called from midnight budget reset automation. `supports_response="only"` |
| `pyscript.budget_history_rolling` | `months` | `{status, op, ...}` | Query `budget_history` for the rolling window and update `sensor.ai_openrouter_rolling_usage`. `supports_response="only"` |
| `pyscript.budget_history_backfill` | `fallback_rate` | `{status, op, ...}` | One-time migration: parse existing `budget_daily:*` L2 entries and insert into `budget_history`. `supports_response="only"` |

## Triggers

| Trigger | Function | Condition |
|---------|----------|-----------|
| `@time_trigger("startup")` | `memory_health_check` | Runs health check, initializes sqlite-vec, reports to status sensor |
| `@time_trigger("cron(0 3 * * *)")` | `memory_daily_housekeeping` | Daily at 03:00: purge expired entries (10-day grace), prune orphan relationships |
| `@time_trigger("startup")`, `@time_trigger("cron(*/15 * * * *)")` | `memory_context_refresh` | Refreshes `sensor.ai_memory_context` with recent summaries and moods from L2. User-configurable: `ai_memory_context_enabled` (toggle), `ai_memory_context_summary_limit` (default 2), `ai_memory_context_mood_limit` (default 1), `ai_memory_context_max_chars` (default 80, 0=off). System-activity summaries auto-filtered via skip phrases. |
| `@time_trigger("cron(*/5 * * * *)")` | `_memory_recovery_probe` | Every 5 min: checks if DB is recoverable after a write failure, clears circuit breaker on success |
| `@time_trigger("startup")`, `@time_trigger("cron(5 0 * * *)")` | `budget_history_auto_refresh` | On startup and daily at 00:05: refreshes rolling budget usage sensor |
| `@state_trigger("input_number.ai_budget_rolling_months")` | `budget_history_window_change` | Re-queries rolling budget when the window size helper changes |
| `@state_trigger("sensor.openrouter_credits")` | `budget_history_credits_change` | Re-queries rolling budget when OpenRouter credits sensor changes |
| `@state_trigger("sensor.serper_account")` | `budget_history_serper_change` | Re-queries rolling budget when Serper account sensor changes |

## Key Functions

- `_ensure_db()` — Creates database schema: `mem` table, `mem_fts` FTS5 virtual table with triggers, `mem_rel` relationship table, `mem_archive` cold storage table, `budget_history` table, and `mem_vec` (if vec0.so available)
- `_build_fts_queries()` — Generates 5 FTS5 query variants ordered by precision: PHRASE, NEAR, AND, OR*, RAW
- `_calculate_match_score()` — Blends Jaccard tag overlap with BM25 rank for relevance scoring
- `_search_tag_candidates()` — Finds related entries by normalized tag overlap (used for duplicate detection and auto-linking)
- `_memory_archive_db_sync()` — Archive engine: selects coldest unprotected entries, moves to `mem_archive`, cleans relationships and vectors
- `_normalize_key()` — Normalizes keys to `[a-z0-9_]` with diacritic stripping
- `_normalize_search_text()` — Lowercase, strip diacritics, collapse whitespace for search
- `_strip_diacritics()` — Handles Vietnamese, Turkish, Spanish, Germanic, and Nordic character normalization via `EXTRA_CHAR_REPLACEMENTS` map

## State Dependencies

- `input_number.ai_memory_record_limit` — Max rows before threshold alert (default: 5000)
- `input_number.ai_memory_db_max_mb` — Max DB size before threshold alert (default: 100 MB)
- `input_boolean.ai_memory_auto_archive` — Enable automatic archiving
- `input_number.ai_memory_archive_target_pct` — Archive to this % of record_limit (default: 80%)
- `input_number.ai_memory_archive_recency_days` — Protect entries accessed within this many days (default: 30)
- `input_text.ai_memory_archive_protection_tags` — Space-separated tags that protect entries from archiving
- `input_number.ai_semantic_blend_weight` — 0-100, controls FTS vs. semantic balance in blended search
- `input_number.ai_semantic_similarity_threshold` — Minimum similarity score for vector results (default: 0.7)
- `input_number.ai_embedding_dimensions` — Vector dimensions (default: 512)
- `input_boolean.ai_embedding_reindex_needed` — When ON, `memory_embed_batch` drops and recreates `mem_vec`
- `input_text.ai_memory_search_query` — Dashboard search input
- `input_text.ai_memory_edit_key` / `_value` / `_tags` / `_scope` — Dashboard editor fields
- `input_boolean.ai_memory_context_enabled` — Master toggle for L1 context injection (default: on)
- `input_number.ai_memory_context_summary_limit` — Max summaries in L1 context (default: 2)
- `input_number.ai_memory_context_mood_limit` — Max moods in L1 context (default: 1)
- `input_number.ai_memory_context_max_chars` — Per-entry truncation limit (default: 80, 0=no truncation)

## Package Pairing

Pairs with `packages/ai_memory.yaml` which defines all memory-related helpers, threshold limits, archive settings, embedding config, dashboard helpers, and the `sensor.memory_result` status entity.

## Called By

- **Every pyscript module** — all modules use `memory_set`, `memory_get`, and `memory_search` for L2 persistence
- **LLM tool functions** — Extended OpenAI agents use memory services as tool functions for voice-driven "remember this" / "what did I say about X" interactions
- **Dashboard** — `memory_browse`, `memory_edit`, `memory_delete`, `memory_load` for the memory management UI
- **Nightly embedding blueprint** — calls `memory_embed_batch` for incremental vector index building
- **Memory housekeeping automation** — threshold events trigger archiving or cleanup actions

## Notes

- Database schema: 4 tables (`mem`, `mem_fts`, `mem_rel`, `mem_archive`) plus optional `mem_vec` (sqlite-vec) and `budget_history`.
- FTS5 search strategy: 5 query variants tried in order of precision (PHRASE > NEAR > AND > OR* > RAW). First variant to return results wins. LIKE fallback if all FTS variants fail.
- Duplicate detection: when creating a new key, tag overlap is checked against existing entries. If matches are found, a `duplicate_tags` error is returned unless `force_new=True`. This prevents accidental overwrites by LLM agents.
- Auto-linking: on every `memory_set`, the module searches for tag-overlapping entries and creates bidirectional relationships in `mem_rel` with Jaccard similarity weights. This builds the relationship graph incrementally.
- Archive protection: entries are protected from archiving by recency (accessed within N days), scope (permanent user entries), and tags (configurable protection tags like "important", "pinned").
- Thread safety: all SQLite operations run in `asyncio.to_thread()` to avoid blocking the event loop. `@pyscript_compile` decorators allow pure-Python functions to run outside pyscript's async context.
- Retry pattern: all DB operations retry once with a forced schema rebuild on `sqlite3.OperationalError`, handling cases where tables or triggers are missing after a database corruption.
- Semantic search (I-2): optional sqlite-vec integration. When `vec0.so` is available, `memory_search` blends FTS5 scores with KNN vector similarity using the configurable blend weight. Pure semantic search is also available via `memory_semantic_search`.
- This is the largest pyscript module (~5000 lines, 29 services). Treat it as the "database layer" -- other modules should never access `memory.db` directly.
