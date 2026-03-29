# Agent Whisper Network — Silent Inter-Agent Context Sharing

Pattern 5 of the Voice Context Architecture. After every voice interaction, the active agent writes observations (interaction log, mood, topic) to L2 memory that other agents discover before their next interaction. This enables agents to reference what happened in previous conversations with different personas. Zero LLM calls -- pure keyword matching and memory read/write with less than 200ms latency.

## Services

| Service | Parameters | Returns | Description |
|---------|-----------|---------|-------------|
| `pyscript.agent_whisper` | `agent_name`, `user_query`, `agent_response`, `interaction_mood`, `source` | `{status, op, agent, mood, topic, writes, skipped, test_mode, elapsed_ms}` | Post-interaction write: logs interaction, detects mood via keyword matching, tracks topic. Fires after TTS response. `supports_response="optional"` |
| `pyscript.agent_whisper_context` | `agent_name`, `lookback_hours`, `max_entries` | `{status, op, agent, context, entry_count, entries, lookback_hours, elapsed_ms}` | Pre-interaction read: retrieves recent whisper entries from OTHER agents, returns a concise context string for system prompt injection. `supports_response="optional"` |
| `pyscript.summarize_interactions` | `lookback_hours`, `min_interactions`, `max_interactions`, `retention_mode`, `summary_expiry_days`, `priority_tier` | `{status, op, summary, entry_count}` | Batch-compress whisper interaction logs into per-agent summaries via LLM. Budget-gated. `supports_response="optional"` |
| `pyscript.agent_interaction_log` | `agent_name`, `topic`, `user_intent`, `source` | `{status, op, agent, topic, written, elapsed_ms}` | Self-report tool for agents: log what was just discussed. Writes whisper entry to L2 and updates self-awareness sensor. `supports_response="optional"` |
| `pyscript.save_handoff_context` | `context` | `{status, op}` | Save cross-agent handoff context to both `var.ai_handoff_context` entity and L2 memory for persistence across restarts. `supports_response="optional"` |
| `pyscript.whisper_reload_cache` | _(none)_ | `{status, personas}` | Invalidate and rebuild the whisper pipeline cache. Call after pipeline config changes. `supports_response="optional"` |
| `pyscript.whisper_retag_automation` | `dry_run` | `{status, op, retagged, checked}` | Retag old whisper L2 entries to updated tag schema. Migration utility. `supports_response="only"` |

## Triggers

| Trigger | Function | Condition |
|---------|----------|-----------|
| `@time_trigger("startup")` | `agent_whisper_startup` | Initializes whisper network sensor on HA startup |

## Key Functions

- `_detect_mood()` — Keyword-based mood detection from user query and agent response. Maps keywords to mood categories (frustrated, stressed, tired, happy, neutral). Priority order: frustrated > stressed > tired > happy > neutral.
- `_extract_topic_slug()` — Extract 1-3 keyword topic slug from user query via stop-word removal
- `_build_context_summary()` — Build a concise context string from filtered whisper entries for system prompt injection
- `_check_mood_dedup()` — Returns True if this (agent, mood) pair was written within the configurable dedup window
- `_auto_update_keywords()` — Auto-update dispatch keywords for a persona from recent whisper topics. Rate-limited per agent, caps at configurable max auto keywords. Preserves `!`-prefixed manual keywords.

## State Dependencies

- `input_boolean.ai_whisper_enabled` — Kill switch for the entire whisper network
- `input_boolean.ai_whisper_mood_detection` — Kill switch for mood detection specifically
- `input_number.ai_whisper_interaction_expiry_days` — Interaction log expiry (default: 2 days)
- `input_number.ai_whisper_mood_expiry_days` — Mood observation expiry (default: 1 day)
- `input_number.ai_whisper_topic_expiry_days` — Topic tracking expiry (default: 3 days)
- `input_number.ai_whisper_mood_dedup_seconds` — Mood dedup window (default: 3600s)
- `input_number.ai_whisper_max_auto_keywords` — Max auto-generated keywords per agent (default: 30)
- `input_number.ai_whisper_keyword_cooldown` — Cooldown between keyword updates per agent (default: 300s)
- `input_number.ai_whisper_topic_history_count` — Number of recent topics to show (for `sensor.ai_recent_topics`)
- `var.ai_handoff_context` — Cross-agent handoff context (var entity for persistence)

## Package Pairing

Pairs with `packages/ai_agent_whisper.yaml` which defines the kill switch, lookback/max_entries helpers, and the `sensor.ai_whisper_network_status` result entity.

## Called By

- **Voice agent blueprints** — call `agent_whisper` post-interaction and `agent_whisper_context` pre-interaction for system prompt enrichment
- **voice_handoff.yaml** — calls `save_handoff_context` during agent handoff to preserve conversation state
- **proactive_briefing.py** — reads whisper context to inform briefing content
- **Summarizer automation** — calls `summarize_interactions` on schedule for digest creation

## Notes

- Zero LLM calls by design (except `summarize_interactions` which is explicitly LLM-powered and budget-gated). Mood and topic detection use pure keyword matching.
- Fire-and-forget model: if L2 memory is slow or down, whisper writes do not block the voice interaction. Errors are logged but never surface to the user.
- Expiration windows (configurable via helpers): interaction logs default to 2 days (48h), mood observations to 1 day (24h), topic tracking to 3 days (72h).
- Mood dedup: same (agent, mood) pair is skipped within the configurable dedup window (default 3600s) to prevent repetitive mood entries.
- Keyword auto-update: after each whisper, `_auto_update_keywords()` updates dispatch keywords for the agent from recent topics. Rate-limited per agent, capped at configurable max. Manual keywords (prefixed with `!`) are preserved.
- Recent topic history (C7): `sensor.ai_recent_topics` is maintained via direct SQLite queries against `memory.db`, refreshed on startup and after each whisper.
