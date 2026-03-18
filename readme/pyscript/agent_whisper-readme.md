# Agent Whisper Network — Silent Inter-Agent Context Sharing

Pattern 5 of the Voice Context Architecture. After every voice interaction, the active agent writes observations (interaction log, mood, topic) to L2 memory that other agents discover before their next interaction. This enables agents to reference what happened in previous conversations with different personas. Zero LLM calls -- pure keyword matching and memory read/write with less than 200ms latency.

## Services

| Service | Parameters | Returns | Description |
|---------|-----------|---------|-------------|
| `pyscript.agent_whisper` | `agent_name`, `intent_text`, `response_text`, `satellite`, `**kwargs` | `{status, op, agent, mood, topic, wrote_interaction, wrote_mood, wrote_topic}` | Post-interaction write: logs interaction, detects mood via keyword matching, tracks topic. Fires after TTS response. `supports_response="optional"` |
| `pyscript.agent_whisper_context` | `agent_name`, `lookback_hours`, `max_entries` | `{status, op, context_block, entry_count}` | Pre-interaction read: retrieves recent whisper entries from OTHER agents, returns a concise context string for system prompt injection. `supports_response="optional"` |
| `pyscript.summarize_interactions` | `lookback_hours`, `max_entries`, `llm_instance` | `{status, op, summary, entry_count}` | Batch-summarize recent interaction logs into a concise digest via LLM. Budget-gated. `supports_response="optional"` |
| `pyscript.agent_interaction_log` | `agent_name`, `intent_text`, `response_text`, `satellite`, `**kwargs` | `{status, op, logged}` | Write a raw interaction log entry to L2 memory. Standalone logging without mood/topic detection. `supports_response="optional"` |
| `pyscript.save_handoff_context` | `context` | `{status, op}` | Save cross-agent handoff context to both `var.ai_handoff_context` entity and L2 memory for persistence across restarts. `supports_response="optional"` |
| `pyscript.whisper_retag_automation` | `dry_run` | `{status, op, retagged, checked}` | Retag old whisper L2 entries to updated tag schema. Migration utility. `supports_response="only"` |

## Triggers

| Trigger | Function | Condition |
|---------|----------|-----------|
| `@time_trigger("startup")` | `agent_whisper_startup` | Initializes whisper network sensor on HA startup |

## Key Functions

- `_detect_mood()` — Keyword-based mood detection from response text. Maps keywords to mood categories (happy, frustrated, curious, tired, etc.)
- `_detect_topic()` — Extract primary topic from intent text via keyword matching against a topic taxonomy
- `_format_whisper_entry()` — Format a single whisper entry for context block injection
- `_dedup_mood()` — Prevents same (agent, mood) pair from being written within 1 hour

## State Dependencies

- `input_boolean.ai_whisper_enabled` — Kill switch for the entire whisper network
- `input_number.ai_whisper_lookback_hours` — Default lookback window for context retrieval
- `input_number.ai_whisper_max_entries` — Default max entries for context retrieval
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
- Expiration windows: interaction logs expire in 2 days (48h), mood observations in 1 day (24h), topic tracking in 7 days.
- Mood dedup: same (agent, mood) pair is skipped within 1 hour to prevent repetitive mood entries.
- The `**kwargs` on `agent_whisper` and `agent_interaction_log` allows blueprints to pass additional metadata without breaking the service signature.
