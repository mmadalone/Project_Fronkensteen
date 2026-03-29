# AI Self-Awareness

Tracks which voice agent last responded, what was discussed, and when the interaction occurred. Provides a legacy script for updating self-awareness state, though this is now primarily handled by `agent_whisper.py`. Part of Task 2 of the Voice Context Architecture.

## What's Inside

| Type | Count |
|------|-------|
| Scripts | 1 |
| Input helpers (external) | 2 |
| Pyscript sensors (dynamic) | 1 |

## Entity Reference

| Entity ID | Type | Purpose |
|-----------|------|---------|
| `script.ai_update_self_awareness` | Script | Updates last agent/topic/time — queued mode, max 3. Accepts `agent_name`, `agent_entity`, `topic` fields. Calls `pyscript.update_last_interaction` bridge service |
| `sensor.ai_last_interaction` | Pyscript sensor | Agent name (state); attrs: `agent_entity`, `topic`, `handoff_reason`, `handoff_source` (set by `pyscript.update_last_interaction` via `state.set()`) |
| `input_datetime.ai_last_interaction_time` | Input Datetime | When the last interaction occurred |
| `input_text.ai_last_satellite` | Input Text | Last satellite that responded |

## Dependencies

- **Pyscript:** `pyscript/shared_utils.py` — `set_last_interaction()` helper; `pyscript/agent_dispatcher.py` — `pyscript.update_last_interaction` bridge service (`@service`)
- **Helper files:** `helpers_input_text.yaml`, `helpers_input_datetime.yaml`

## Cross-References

- **pyscript/agent_whisper.py** — primary updater of self-awareness state (40+ call sites via `agent_whisper()` and `agent_interaction_log()`)
- **ai_context_hot.yaml** — reads last agent/topic/time for hot context injection
- **Voice agent prompts** — agents reference self-awareness data to maintain conversational continuity

## Notes

- **Deprecated (2026-03-09):** The script is kept for backward compatibility, but self-awareness is now primarily updated by `agent_whisper.py` through two paths: `agent_whisper()` after blueprint-driven interactions, and `agent_interaction_log()` as an LLM self-report tool on Extended OpenAI agents.
- The `ai_llm_call_counter` automation no longer updates self-awareness (removed 2026-03-10) because it was resetting the timestamp on every announcement/automation call, diluting the user-interaction signal.
- Script uses `mode: queued` with `max: 3` to handle rapid successive calls without dropping updates.
