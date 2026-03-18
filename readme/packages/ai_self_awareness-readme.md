# AI Self-Awareness

Tracks which voice agent last responded, what was discussed, and when the interaction occurred. Provides a legacy script for updating self-awareness state, though this is now primarily handled by `agent_whisper.py`. Part of Task 2 of the Voice Context Architecture.

## What's Inside

| Type | Count |
|------|-------|
| Scripts | 1 |
| Input helpers (external) | 5 |

## Entity Reference

| Entity ID | Type | Purpose |
|-----------|------|---------|
| `script.ai_update_self_awareness` | Script | Updates last agent/topic/time — queued mode, max 3. Accepts `agent_name`, `agent_entity`, `topic` fields |
| `input_text.ai_last_agent_name` | Input Text | Which agent responded (e.g. "Rick", "Quark") |
| `input_text.ai_last_agent_entity` | Input Text | Agent entity_id (e.g. `conversation.rick_extended`) |
| `input_text.ai_last_interaction_topic` | Input Text | One-line summary of what was discussed |
| `input_datetime.ai_last_interaction_time` | Input Datetime | When the last interaction occurred |
| `input_text.ai_last_satellite` | Input Text | Last satellite that responded |

## Dependencies

- **Helper files:** `helpers_input_text.yaml`, `helpers_input_datetime.yaml`

## Cross-References

- **pyscript/agent_whisper.py** — primary updater of self-awareness state (40+ call sites via `agent_whisper()` and `agent_interaction_log()`)
- **ai_context_hot.yaml** — reads last agent/topic/time for hot context injection
- **Voice agent prompts** — agents reference self-awareness data to maintain conversational continuity

## Notes

- **Deprecated (2026-03-09):** The script is kept for backward compatibility, but self-awareness is now primarily updated by `agent_whisper.py` through two paths: `agent_whisper()` after blueprint-driven interactions, and `agent_interaction_log()` as an LLM self-report tool on Extended OpenAI agents.
- The `ai_llm_call_counter` automation no longer updates self-awareness (removed 2026-03-10) because it was resetting the timestamp on every announcement/automation call, diluting the user-interaction signal.
- Script uses `mode: queued` with `max: 3` to handle rapid successive calls without dropping updates.
