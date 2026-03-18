# Agent Dispatcher — Pipeline-Aware Persona Routing

The Agent Dispatcher is DC-7 of the Voice Context Architecture. It discovers available voice agents from HA Assist Pipelines, resolves TTS/STT engines from pipeline config, and routes requests based on wake word, topic affinity, conversation continuity, time of day, user preference, and LLM budget. It also provides Priority 0 regex matching for programmatic handoff requests (e.g., "pass me to Deadpool").

## Services

| Service | Parameters | Returns | Description |
|---------|-----------|---------|-------------|
| `pyscript.agent_dispatch` | `intent_text`, `source_satellite`, `wake_word`, `verbosity`, `skip_continuity` | `{agent, persona, verbosity, variant, reason, tts_engine, tts_voice, stt_engine, pipeline_id}` | Main routing entry point. Evaluates 7-priority routing chain (handoff, wake word, continuity, topic affinity, time-of-day, random, default) and returns the selected agent with full pipeline config. `supports_response="only"` |
| `pyscript.dispatcher_reload_cache` | _(none)_ | `{status}` | Invalidate and rebuild the dispatcher's pipeline/persona cache from HA Assist Pipeline config entries. `supports_response="optional"` |
| `pyscript.dispatcher_resolve_engine` | `pipeline_name` | `{status, agent_id, pipeline_id}` | Resolve a pipeline display name to its `conversation_engine` entity ID. Used by voice_handoff and other callers that need to map a friendly name to an entity. `supports_response="optional"` |
| `pyscript.dispatcher_load_keywords` | _(none)_ | `{status, agent, keywords}` | Load topic-affinity keywords for the selected agent from L2 memory. Reads agent from `input_select.ai_dispatcher_keyword_agent`. Dashboard service. `supports_response="only"` |
| `pyscript.dispatcher_add_keyword` | _(none)_ | `{status, agent, keyword, source}` | Add a keyword to the selected agent's routing keywords in L2 memory. Reads from dashboard helpers. `supports_response="only"` |
| `pyscript.dispatcher_remove_keyword` | _(none)_ | `{status, agent, keyword}` | Remove a keyword from the selected agent's routing keywords in L2 memory. `supports_response="only"` |
| `pyscript.dispatcher_clear_auto_keywords` | _(none)_ | `{status, agent, cleared}` | Clear all auto-generated (non-manual) keywords from the selected agent. `supports_response="only"` |

## Triggers

| Trigger | Function | Condition |
|---------|----------|-----------|
| `@time_trigger("startup")` | `agent_dispatcher_startup` | Initializes status sensor, rebuilds cache on HA startup |

## Key Functions

- `_build_pipeline_cache()` — Discovers all Assist Pipelines, extracts persona/variant mappings, TTS/STT engine config, and builds the in-memory routing table
- `_check_handoff_request()` — Priority 0: regex matching for "pass me to X" patterns using alias map from `input_text.ai_handoff_persona_aliases`
- `_check_wake_word()` — Priority 1: extract explicit agent name from wake word
- `_check_continuity()` — Priority 2: return same agent if conversation is within continuity window
- `_check_topic_affinity()` — Priority 3: match intent text against per-agent topic keywords from L2 memory
- `_check_time_of_day()` — Priority 4: time-based routing from `input_text.ai_dispatcher_time_rules`
- `_resolve_tts_stt()` — Resolve TTS engine, voice, and STT engine from pipeline config for the selected agent

## State Dependencies

- `input_select.ai_dispatcher_mode` — Routing mode (auto/manual/random)
- `input_text.ai_handoff_persona_aliases` — JSON map of persona aliases for handoff detection
- `input_number.ai_dispatcher_continuity_window` — Minutes to maintain conversation continuity
- `input_text.ai_dispatcher_time_rules` — JSON time-of-day routing rules
- `input_boolean.ai_budget_fallback_active` — Budget exhaustion flag (early return to homeassistant agent)
- `input_select.ai_dispatcher_keyword_agent` — Dashboard: selected agent for keyword management

## Package Pairing

Pairs with `packages/ai_agent_dispatcher.yaml` which defines the routing helpers, mode selector, continuity window, time rules, and the keyword management dashboard entities.

## Called By

- **voice_handoff.yaml** — calls `agent_dispatch` to determine which agent should handle after a handoff
- **email_promote.py** — calls `agent_dispatch` for TTS voice selection on urgent email announcements
- **proactive_briefing.py** — calls `dispatcher_resolve_engine` to find the conversation agent for LLM briefings
- **focus_guard.py** — calls `agent_dispatch` for persona-routed nudge TTS
- **All voice pipeline automations** — indirectly via wake word triggers that route through the dispatcher
- **Dashboard** — keyword management services

## Notes

- Pipeline cache is rebuilt on startup and can be manually refreshed via `dispatcher_reload_cache`. Cache invalidation is not automatic when pipelines change in HA UI.
- The routing priority chain is strict: Priority 0 (handoff) always wins over Priority 1 (wake word), which wins over Priority 2 (continuity), etc. The first match short-circuits.
- Topic affinity keywords are stored in L2 memory with key pattern `dispatcher_keywords:{agent}`. They can be auto-generated from whisper interaction logs or manually added via the dashboard.
- Budget fallback (I-46): when `ai_budget_fallback_active` is ON, the dispatcher returns `{agent: homeassistant, reason: budget_fallback}` immediately, bypassing all routing logic.
- The `_VOICE_AGENT_MAP` is not in this module; it lives in `tts_queue.py` for TTS entity-to-agent mapping.
