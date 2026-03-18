# Common Utilities — Shared Infrastructure Layer

Provides the common infrastructure layer used by all other pyscript modules: SQLite-backed L2 memory cache with per-key locking (`cache.db`), per-agent budget breakdown tracking (I-33), conversation timeout wrapper, and the `ha_text_ai` LLM wrapper for tool-free text generation and embeddings. This is the foundational module that other modules depend on.

## Services

| Service | Parameters | Returns | Description |
|---------|-----------|---------|-------------|
| `pyscript.conversation_with_timeout` | `agent_id`, `text`, `timeout` | `{status, response}` | Wrapper around `conversation.process` with configurable timeout. Prevents hung LLM calls from blocking automations. `supports_response="only"` |
| `pyscript.memory_cache_get` | `key` | `{status, value, hit}` | Read from the SQLite-backed in-process memory cache (`cache.db`). Faster than L2 for hot-path reads. `supports_response="only"` |
| `pyscript.memory_cache_set` | `key`, `value`, `ttl_seconds` | `{status}` | Write to the memory cache with configurable TTL. `supports_response="only"` |
| `pyscript.memory_cache_forget` | `key` | `{status, deleted}` | Delete a single key from the memory cache. `supports_response="only"` |
| `pyscript.memory_cache_index_update` | `index_key`, `entry_key`, `entry_value`, `ttl_seconds` | `{status}` | Append an entry to a JSON index stored in cache. Used for maintaining ordered lists (e.g., conversation logs). `supports_response="only"` |
| `pyscript.budget_track_call` | `service_type`, `agent`, `tokens`, `chars`, `calls`, `model`, `reset` | _(none)_ | Track per-agent budget breakdown for LLM/TTS/STT usage. Increments counters and updates `sensor.ai_budget_breakdown`. When `reset=True`, clears all breakdown data. `@service` (no response) |
| `pyscript.budget_reload_model_map` | _(none)_ | _(none)_ | Reload the agent-to-model map from HA config entries. Called after pipeline changes. `@service` (no response) |
| `pyscript.budget_breakdown_restore` | `data` (dict) | _(none)_ | Restore budget breakdown state from a saved dict (e.g., after restart from L2 persistence). `@service` (no response) |
| `pyscript.llm_task_call` | `prompt`, `instance`, `max_tokens`, `temperature` | `{status, response_text, tokens_used}` | Tool-free LLM text generation via the `ha_text_ai` sensor pattern. Used for summarization, reformulation, and other non-conversational LLM tasks. `supports_response="only"` |
| `pyscript.llm_direct_embed` | `text`, `model`, `dimensions` | `{status, embedding, dimensions, tokens_used}` | Generate a vector embedding for text via OpenAI-compatible API. Used by `memory.py` for semantic search. `supports_response="only"` |

## Triggers

| Trigger | Function | Condition |
|---------|----------|-----------|
| `@time_trigger("startup")` | `initialize_cache_db` | Creates the cache SQLite database and schema on startup |
| `@time_trigger("cron(0 * * * *)")` | `prune_cache_db` | Hourly pruning of expired cache entries |
| `@time_trigger("startup")` | `_initialize_model_map` | Loads agent-to-model map from HA config entries on startup |

## Key Functions

- `_cache_prepare_db()` — Creates the `cache.db` SQLite database with schema, per-key locking via `_IndexLockContext`
- `_prune_expired()` — Removes expired cache entries from `cache.db`
- `_load_and_cache_model_map()` — Reads HA config entries for OpenAI/conversation agents and builds the `_AGENT_MODEL_MAP` dict
- `_VOICE_AGENT_MAP` — Maps TTS entity IDs to agent names (rick, quark, kramer, deadpool, portuondo, custom)

## State Dependencies

- `input_text.ai_task_instance` — Default `ha_text_ai` sensor entity for LLM task calls
- `input_number.ai_embedding_dimensions` — Vector embedding dimensions (default: 512)
- `input_text.ai_openai_api_key_entity` — Entity holding the OpenAI API key for direct embedding calls
- `sensor.ai_budget_breakdown` — Output sensor for per-agent budget tracking data

## Package Pairing

Pairs with `packages/ai_llm_budget.yaml` which defines budget counters, pricing helpers, currency selector, and the budget breakdown sensor. Also pairs with `packages/ai_context_hot.yaml` which hosts the `ha_text_ai` sensor template.

## Called By

- **memory.py** — calls `llm_direct_embed` for semantic search vector generation
- **contact_history.py** — calls `llm_task_call` for contact message summarization
- **music_taste.py** — calls `llm_task_call` for genre summary generation
- **agent_whisper.py** — calls `llm_task_call` for interaction summarization
- **email_promote.py** — calls `conversation_with_timeout` for persona-routed email announcements
- **All pyscript modules** — use `memory_cache_get/set` for hot-path caching
- **ai_llm_call_counter automation** — calls `budget_track_call` for LLM and STT cost tracking
- **Midnight reset automation** — calls `budget_track_call` with `reset=True`

## Notes

- The cache database (`cache.db`) is separate from the L2 memory database (`memory.db`). Cache is for fast, ephemeral, in-process reads; L2 is for persistent, searchable, cross-module storage.
- Per-key locking via `_IndexLockContext` uses a two-tier pattern: a `threading.Lock` guards the lock dictionary (microsecond hold), and per-key `asyncio.Lock`s serialize actual I/O operations. This prevents both data races and deadlocks.
- The 5-minute conversation ID TTL constant matches HA's fixed idle timeout for conversation sessions.
- `llm_task_call` is deliberately tool-free: it uses the `ha_text_ai` sensor pattern (a template sensor that calls OpenAI directly) rather than `conversation.process`, which would give the LLM access to HA tools. This prevents unintended side effects during summarization tasks.
- Budget breakdown tracking uses an in-memory dict that is periodically persisted to L2 memory. On restart, `budget_breakdown_restore` rehydrates from L2.
- `llm_direct_embed` calls the OpenAI embeddings API directly via `aiohttp`, bypassing HA's conversation integration entirely.
