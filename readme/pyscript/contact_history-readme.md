# Contact History — Per-Contact Message Logging and Summarization

I-47 of the Voice Context Architecture. Logs per-contact messages to L2 memory after notification and email announcements, retrieves recent history for LLM prompt injection, and batch-summarizes raw entries into per-contact digests via LLM. Provides agents with conversational context about recent communications with specific people.

## Services

| Service | Parameters | Returns | Description |
|---------|-----------|---------|-------------|
| `pyscript.contact_history_log` | `sender`, `channel`, `message`, `app_label`, `storage_mode` | `{status, op, logged, key, contact, elapsed_ms}` | Write a raw message entry to L2 memory. Fires `contact_history_log_complete` event for event-driven summarizer. Zero LLM calls. `storage_mode` controls what is persisted: `both` (text + summary), `summary_only`, `text_only`. `supports_response="optional"` |
| `pyscript.contact_history_context` | `sender`, `window`, `max_entries` | `{status, op, has_history, context_block, entry_count, contact, window, elapsed_ms}` | Fetch recent message history for a sender from L2. Returns a formatted context block for LLM prompt injection. Combines raw messages and digests, sorted by time. Zero LLM calls. `supports_response="only"` |
| `pyscript.contact_history_summarize` | `min_messages`, `max_contacts`, `summary_expiry_days`, `llm_instance`, `target_contact` | `{status, op, contacts_processed, digests_created, entries_processed, llm_calls, elapsed_ms}` | Batch-compress raw entries into per-contact digests via LLM. Groups unsummarized messages by contact, sends each group for compression, stores the digest, and tags source entries as summarized. `supports_response="optional"` |

## Triggers

| Trigger | Function | Condition |
|---------|----------|-----------|
| `@time_trigger("startup")` | `contact_history_startup` | Initializes `sensor.ai_contact_history_status` on HA startup |

## Key Functions

- `_normalize_contact()` — Normalizes contact names for consistent key generation (lowercase, spaces to underscores, strip special chars)
- `_build_msg_key()` / `_build_digest_key()` — L2 key generation: `contact_msg_{name}_{ts}` and `contact_digest_{name}_{ts}`
- `_build_msg_value()` — JSON value builder with storage mode support (full text, preview only, or both)
- `_format_history_block()` — Formats history entries into a context block with relative timestamps for LLM prompt injection

## State Dependencies

- `input_boolean.ai_contact_history_enabled` — Kill switch
- `input_boolean.ai_test_mode` — Test mode (log decisions, no L2 writes)

## Package Pairing

Pairs with `packages/ai_contact_history.yaml` (if it exists) or the kill switch is defined in `helpers_input_boolean.yaml`. The `sensor.ai_contact_history_status` result entity is created by pyscript at runtime.

## Called By

- **notification_follow_me.yaml** — calls `contact_history_log` after announcing notification messages, calls `contact_history_context` for LLM prompt enrichment
- **email_follow_me.yaml** — calls `contact_history_log` after email announcements
- **contact_history_summarizer.yaml** — calls `contact_history_summarize` on schedule or event-driven via `contact_history_log_complete` event

## Notes

- L2 key schema: raw messages use `contact_msg_{name}_{unix_ts}` with 3-day expiry; digests use `contact_digest_{name}_{unix_ts}` with configurable expiry (default 7 days).
- The `storage_mode` parameter controls privacy: `summary_only` stores just a 100-char preview (for later LLM summarization), while `text_only` stores the full text but skips summarization metadata.
- The `contact_history_log_complete` event enables event-driven summarization: the summarizer blueprint can trigger immediately after a log write rather than waiting for a scheduled batch run.
- Context window options: `1h`, `6h`, `24h`, `3d`, `7d`. The context block includes both raw messages and digest entries, with relative timestamps (e.g., "2h ago").
- Raw message text is capped at 1000 characters in storage to prevent L2 bloat from long messages.
