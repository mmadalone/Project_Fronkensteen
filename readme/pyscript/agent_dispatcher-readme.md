# Agent Dispatcher — Pipeline-Aware Persona Routing

The Agent Dispatcher is DC-7 of the Voice Context Architecture. It discovers available voice agents from HA Assist Pipelines, resolves TTS/STT engines from pipeline config, and routes requests based on wake word, topic affinity, conversation continuity, time of day, user preference, and LLM budget. It also provides Priority 0 regex matching for programmatic handoff requests (e.g., "pass me to Deadpool").

## Services

| Service | Parameters | Returns | Description |
|---------|-----------|---------|-------------|
| `pyscript.agent_dispatch` | `intent_text`, `source_satellite`, `wake_word`, `verbosity`, `skip_continuity`, `pipeline_id`, `pipeline_name` | `{agent, persona, verbosity, variant, reason, tts_engine, tts_voice, stt_engine, pipeline_id}` | Main routing entry point. When `pipeline_id` is provided, resolves that specific pipeline (no dynamic selection). Otherwise evaluates 7-priority routing chain (handoff, wake word, continuity, topic affinity, time-of-day, random, default) and returns the selected agent with full pipeline config. `supports_response="only"` |
| `pyscript.dispatcher_reload_cache` | _(none)_ | `{status, personas, display_map}` | Invalidate and rebuild the dispatcher's pipeline/persona cache from HA Assist Pipeline config entries. `supports_response="optional"` |
| `pyscript.dispatcher_resolve_engine` | `pipeline_name` | `{engine, tts_voice, tts_engine}` | Resolve a pipeline display name to its `conversation_engine` entity ID and TTS config. Used by voice_handoff and other callers that need to map a friendly name to an entity. `supports_response="optional"` |
| `pyscript.dispatcher_get_satellite_maps` | _(none)_ | `{satellite_select_map, satellite_speaker_map}` | Return satellite device maps from dispatcher cache. Used by voice_handoff and voice_session to avoid duplicating entity registry discovery. `supports_response="only"` |
| `pyscript.update_last_interaction` | `agent_name`, `agent_entity`, `topic`, `handoff_reason`, `handoff_source` | _(none)_ | Bridge service: updates `sensor.ai_last_interaction`. Only non-empty fields are applied; others are preserved. `@service` (no response) |
| `pyscript.dispatcher_load_keywords` | _(none)_ | `{status, agent, count}` | Load topic-affinity keywords for the selected agent from L2 memory. Reads agent from `input_select.ai_keyword_agent_select`. Dashboard service. `supports_response="only"` |
| `pyscript.dispatcher_add_keyword` | _(none)_ | `{status, agent, keyword}` | Add a keyword to the selected agent's routing keywords in L2 memory. Reads from dashboard helpers. `supports_response="only"` |
| `pyscript.dispatcher_remove_keyword` | _(none)_ | `{status, agent, keyword}` | Remove a keyword from the selected agent's routing keywords in L2 memory. `supports_response="only"` |
| `pyscript.dispatcher_clear_auto_keywords` | _(none)_ | `{status, agent, cleared}` | Clear all auto-generated (non-manual) keywords from the selected agent. `supports_response="only"` |

## Triggers

| Trigger | Function | Condition |
|---------|----------|-----------|
| `@time_trigger("startup")` | `agent_dispatcher_startup` | Initializes status sensor, rebuilds cache on HA startup |

## Key Functions

- `_build_from_pipelines()` — Derives personas from pipeline display names, builds entity_map, wake_word_map, pipeline_map, display_map
- `_ensure_cache()` — Lazy-loads the full cache (pipelines, keywords, aliases, satellite maps) with TTL-based refresh
- `_detect_user_handoff()` — Priority 0: regex matching for "pass me to X" patterns using alias map from `input_text.ai_handoff_persona_aliases`
- `_extract_persona_from_wake_word()` — Priority 1: extract explicit agent name from wake word
- `_check_continuity()` — Priority 2: return same agent if conversation is within continuity window
- `_match_topic_affinity()` — Priority 3: match intent text against per-agent topic keywords from L2 memory
- `_get_era_persona()` / `_get_time_era()` — Priority 4: time-based routing from `input_select.ai_dispatcher_era_{late_night,morning,afternoon,evening}` helpers
- `_check_user_preference()` — Priority 5: reads `input_text.ai_context_user_persona_{user}` (L1 helper via `resolve_active_user()` from `shared_utils`). Falls back to L2 memory search for `"preference agent"` if helper is empty or "no preference". Skipped when P4 sets a persona via round-robin.
- `_get_pipeline_info()` — Resolve TTS engine, voice, STT engine, and pipeline_id from pipeline config for the selected agent

## State Dependencies

- `input_select.ai_dispatcher_mode` — Routing mode (auto/manual/random)
- `input_text.ai_handoff_persona_aliases` — Comma-separated alias=persona pairs for handoff detection
- `input_number.ai_conversation_continuity_window` — Minutes to maintain conversation continuity
- `input_select.ai_dispatcher_era_{late_night,morning,afternoon,evening}` — Per-era persona selection (dynamically populated with discovered personas + "none" + "rotate")
- `input_boolean.ai_budget_fallback_active` — Budget exhaustion flag (early return to homeassistant agent)
- `input_text.ai_context_user_persona_{user}` — User's preferred persona (L1 preference, read at Priority 5)
- `input_select.ai_keyword_agent_select` — Dashboard: selected agent for keyword management
- `input_number.ai_dispatcher_cache_ttl` — Cache TTL in seconds (default: 300)

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
- Topic affinity keywords are stored in L2 memory with key pattern `dispatch_keywords:{persona}`. They can be auto-generated from whisper interaction logs or manually added via the dashboard.
- Budget fallback (I-46): when `ai_budget_fallback_active` is ON, the dispatcher returns `{agent: homeassistant, reason: budget_fallback}` immediately, bypassing all routing logic.
- Degradation mode: after 3 consecutive cache load failures, the dispatcher enters BYPASS mode (`input_boolean.ai_dispatcher_bypass_mode` turns ON). Cache recovery automatically exits bypass mode.
