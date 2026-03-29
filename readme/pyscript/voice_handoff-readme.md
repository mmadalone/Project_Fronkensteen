![Voice Handoff -- Agent Pipeline Switching](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/voice_handoff-header.jpeg)

# Voice Handoff -- Agent Pipeline Switching

Executes agent handoffs by switching the satellite's assist pipeline select entity, playing a chime, delivering a greeting in the target agent's voice, and opening the mic. Device-to-pipeline mappings are auto-discovered from the entity registry at startup. Supports timed restore, continuous conversation, and farewell from the source agent. Part of I-24 of the Voice Context Architecture.

## Services

| Service | Parameters | Returns | Description |
|---------|-----------|---------|-------------|
| `pyscript.voice_handoff` | `target` (str, required), `satellite` (str, auto from helper), `greeting` (bool, default true), `greeting_prompt` (str), `seamless` (bool, default true), `farewell` (bool, default false), `farewell_prompt` (str), `llm_lines_mode` (str), `llm_lines_agent` (str), `llm_lines_instance` (str), `continuous` (bool, default false), `continuous_timeout` (float, default 120), `silence_media_id` (str), `extra_system_prompt` (str), `mic_behavior` (str, default "llm_decides": llm_decides/single_turn), `reason` (str, default "user_request"), `restore_mode` (str, default "source"), `restore_timeout` (float, default 300) | `{success, target, source, satellite, greeting_text, elapsed_ms, self_handoff}` | Execute agent handoff: switch pipeline, announce greeting, open mic. `supports_response="optional"`. |
| `pyscript.voice_handoff_register_restore` | `satellite` (str, required), `pipeline_select` (str, required), `saved_pipeline` (str, required) | `{status, satellite, saved_pipeline}` | Register a pending restore entry. Called by blueprint after pipeline switch. `supports_response="optional"`. |
| `pyscript.voice_handoff_restore_now` | (none) | `{restored: [satellites], count}` | Immediately restore all satellites with pending handoffs. `supports_response="optional"`. |
| `pyscript.voice_handoff_clear_restore` | `satellite` (str, required) | (none) | Remove a satellite's pending restore entry. Called by blueprint after timed restore. |
| `pyscript.voice_handoff_rediscover` | (none) | `{select_map, speaker_map}` | Re-scan entity registry for satellite device mappings. |

## Triggers

| Trigger | Function | Condition |
|---------|----------|-----------|
| `@time_trigger("startup")` | `_voice_handoff_startup` | Auto-discover satellite device mappings from entity registry. |

Note: The `@event_trigger("ai_handoff_request")` listener is disabled -- the `voice_handoff.yaml` blueprint is the sole handoff handler. The service remains available for manual/programmatic calls.

## Key Functions

- `_run_discovery()` -- Fetch satellite device mappings from dispatcher cache via `pyscript.dispatcher_get_satellite_maps`.
- `_find_pipeline_option(target, options, variant)` -- Find pipeline select option matching persona name, optionally with variant suffix. `@pyscript_compile`.
- `_resolve_persona(name)` -- Resolve persona alias (e.g., deadpool -> deepee). `@pyscript_compile`.
- `_generate_llm_line(prompt, mode, agent_entity, fallback, ...)` -- Generate text via static / ha_text_ai / pipeline_agent / conversation_agent. 4-mode pattern with I-45a safety prefix for greeting/farewell.
- `_wait_for_audio_done(satellite, timeout)` -- Wait for voice_assistant IDLE then actual audio completion. Event-driven via `task.wait_until` with dual signal: `esphome.voice_tts_done` event (primary) and media_player idle (fallback).
- `_restore_pipeline(satellite, pipeline_select, saved_pipeline, delay_seconds)` -- Restore pipeline after handoff timeout. Waits for satellite idle before restoring.

## State Dependencies

- `input_text.ai_last_satellite` -- Last-used satellite (auto-detected if satellite param empty)
- `input_text.ai_last_agent_name` -- Last agent name (used for self-handoff detection and source persona)
- `sensor.ai_last_interaction` -- Output: agent name as state; attrs `handoff_reason`, `handoff_source`, `topic` updated via `set_last_interaction()`. Read for context in greeting prompt.
- `input_select.ai_handoff_llm_lines_mode` -- Default LLM lines mode (static/ha_text_ai/pipeline_agent/conversation_agent)
- `input_boolean.ai_continuous_conversation_active` -- Stop signal for continuous conversation loop
- `input_boolean.ai_test_mode` -- Test mode

## Package Pairing

Pairs with helpers defined across multiple packages: `packages/ai_self_awareness.yaml` (last satellite, last agent), `packages/ai_voice_handoff.yaml` (LLM lines mode, restore mode/seconds, handoff pending, persona aliases, commentary toggle).

## Called By

- **Blueprints**: `voice_handoff.yaml` (per-satellite, triggered by `ai_handoff_pending` flag) -- the primary consumer
- **LLM agents**: `handoff_agent` tool function fires `ai_handoff_request` event -> blueprint -> this service
- **Agent dispatcher**: Self-handoff path calls directly
- **Budget fallback**: `budget_fallback.yaml` calls `voice_handoff_restore_now` during recovery
- **Depends on**: `pyscript/agent_dispatcher.py` (dispatcher_resolve_engine for pipeline_agent mode), `pyscript/common_utilities.py` (budget_track_call)

## Notes

- **Auto-discovery**: Satellite-to-pipeline-select and satellite-to-speaker mappings are fetched from the dispatcher cache (`pyscript.dispatcher_get_satellite_maps`) at startup. Only `PERSONA_ALIAS` (display name -> conversation entity prefix) is manually configured.
- **Self-handoff**: If target matches current pipeline, just reopens the mic without switching.
- **4-mode LLM lines**: `static` (literal text), `ha_text_ai` (tool-free LLM), `pipeline_agent` (resolve pipeline -> conversation.process), `conversation_agent` (direct conversation.process). Default is `static` for zero re-entry risk.
- **I-45a safety prefix**: Greeting and farewell prompts in pipeline_agent/conversation_agent modes are prefixed with `[INTERNAL GREETING -- do NOT call handoff_agent]` to suppress tool calls.
- **Continuous conversation**: After initial greeting, enters a loop that reopens the mic after each response until timeout or stop signal. No-speech detection exits after 3 short (<12s) sessions. `_wait_for_audio_done` handles full audio completion via event-driven waits (no echo guard polling needed).
- **Restore modes**: `source` (restore to previous pipeline), `preferred` (restore to "preferred"), `never` (no auto-restore). Pending restores tracked per-satellite.
- **Thread safety**: `_handoff_lock` (threading.Lock) protects `_restore_tasks` and `_restore_info` dicts.
- **mic_behavior**: `llm_decides` = agent can ask follow-ups, `single_turn` = agent instructed to end with statements only.
