# Centralized TTS Queue Manager and Audio Pipeline

Routes all TTS speech and media playback through a priority queue with presence-aware speaker targeting, automatic ducking on supported speakers, volume management, broadcast mode, and higher-priority preemption. Tracks TTS character counts and per-agent costs for the budget system. Part of DC-3, DC-10, and DC-11 of the Voice Context Architecture.

## Services

| Service | Parameters | Returns | Description |
|---------|-----------|---------|-------------|
| `pyscript.tts_queue_speak` | `text` (str), `voice` (str), `priority` (int, default 3: 0=emergency..4=ambient), `cache` (str, default "none": static/daily/session/none), `target_mode` (str, default "presence": presence/explicit/broadcast/source_room), `target` (str), `volume_level` (float), `announce` (bool, default true), `chime_path` (str), `media_file` (str), `voice_id` (str) | `{status, op, queue_length, priority, speaker, preempted, test_mode, cache_hit, cache_key}` | Enqueue TTS or audio for prioritized playback. Core entry point for all audio output. `supports_response="only"`. |
| `pyscript.tts_queue_clear` | `target` (str, optional) | `{status, op, cleared}` | Remove pending items from queue. If target specified, only remove items for that speaker. `supports_response="only"`. |
| `pyscript.tts_queue_stop` | `target` (str, optional) | `{status, op, cleared}` | Stop current playback AND clear queue. If target specified, only stop/clear that speaker. `supports_response="only"`. |
| `pyscript.tts_queue_flush_deferred` | (none) | `{status, op, flushed}` | Move items deferred during phone calls back to main queue and trigger processing. `supports_response="optional"`. |
| `pyscript.tts_cache_generate` | `text` (str, required), `voice` (str, required), `cache` (str, default "static") | `{status, op, key}` | Generate TTS and save to cache without playing. For pre-warming. `supports_response="only"`. |
| `pyscript.tts_rebuild_speaker_config` | (none) | `{status, ...}` | Scan media_player entities for area-assigned speakers, merge with `tts_speaker_config.json`, write back. Invalidates speaker cache. `supports_response="only"`. |

## Triggers

| Trigger | Function | Condition |
|---------|----------|-----------|
| `@event_trigger("tts_queue_item_added")` | `_on_queue_item_added` | Process queue when new item added. Serialized via lock. |
| `@event_trigger("tts_queue_flush_deferred")` | `_on_flush_deferred` | Process queue after deferred items flushed. |
| `@time_trigger("startup")` | `tts_queue_startup` | Create cache dir, rebuild speaker config, restore budget counters from L2. |
| `@time_trigger("cron(*/30 * * * *)")` | `_budget_periodic_save` | Save budget counters to L2 every 30 minutes. |
| `@time_trigger("cron(0 0 * * *)")` | `tts_queue_daily_housekeeping` | Cache cleanup (daily/expired/size eviction), HA TTS dir cleanup, reset daily budget counters, save to L2. |

## Key Functions

### Speaker Routing
- `_resolve_speaker(target_mode, target)` -- Resolve speaker based on mode: presence (scan FP2 zones by priority), explicit, broadcast, source_room.
- `_get_default_speaker()` -- Fallback speaker from helper or hardcoded default.
- `_rebuild_speaker_config()` -- Auto-discover speakers from entity registry area assignments + merge with config file.
- `_discover_speakers_from_registry_sync(registry_file)` -- Read entity registry, extract area-assigned media_players. `@pyscript_compile`.

### Playback
- `_play_tts(speaker, text, voice, ...)` -- Core TTS playback via `tts.speak`. Handles announce mode and voice_id options.
- `_play_media(speaker, media_file)` -- Raw audio file playback via `media_player.play_media`.
- `_play_item(item)` -- Process a single queue item: resolve cache, set volume, play TTS or media, wait for completion. Includes ElevenLabs credit gate (swaps to HA Cloud when fallback active or credits below floor).
- `_wait_for_playback_done(speaker)` -- Poll speaker state until idle/off with configurable timeout.
- `_stop_playback(speaker)` -- Stop playback on one or multiple speakers.

### Queue Management
- `_queue_add_sync(item)` -- Add item to priority-sorted queue. Thread-safe.
- `_queue_pop_sync()` -- Pop highest-priority item. Thread-safe.
- `_maybe_preempt(new_priority)` -- If new priority is higher than current playback, stop current speaker.
- `_process_queue()` -- Main queue processing loop. Serialized via lock.

### Caching
- `_cache_key_sync(text, voice)` -- SHA256 hash of text+voice for cache key. `@pyscript_compile`.
- `_cache_check_sync(key)` -- Check if cached audio file exists. `@pyscript_compile`.
- `_cache_save_sync(key, source_path, duration, hint)` -- Copy TTS output to cache dir. `@pyscript_compile`.
- `_cache_cleanup_daily_sync()` -- Remove non-static cache entries daily. `@pyscript_compile`.
- `_cache_evict_by_size_sync(max_size_mb, protect_age_hours)` -- LRU eviction when cache exceeds size limit. `@pyscript_compile`.

### Budget Tracking
- `_increment_counter_by(entity_id, amount)` -- Increment budget counter (used for TTS char counting).
- `_budget_restore_from_l2()` -- Restore budget counters from L2 on startup with exponential backoff retry.
- `_budget_save_to_l2()` -- Save counters + per-agent breakdown to L2.

### Sanitization
- `_sanitize_tool_narration(text)` -- Strip leaked function names, JSON fragments, entity IDs, URLs, email artifacts, and other non-speech content from LLM output before TTS.

## State Dependencies

- `input_boolean.ai_tts_queue_active` -- Kill switch (off = reject all TTS)
- `input_boolean.ai_test_mode` -- Test mode
- `input_boolean.ai_budget_fallback_active` -- Budget fallback flag (swap ElevenLabs to HA Cloud)
- `input_text.ai_tts_default_speaker` -- Default speaker entity
- `input_number.ai_tts_playback_timeout` -- Playback timeout override
- `input_number.ai_tts_chars_today` -- Output: daily TTS character counter
- `input_number.ai_llm_calls_today`, `ai_llm_tokens_today`, `ai_tts_calls_today`, `ai_stt_calls_today` -- Budget counters
- `input_number.ai_tts_cache_static_max_days`, `ai_tts_cache_max_size_mb`, `ai_tts_cache_protect_hours` -- Cache eviction settings
- `input_number.ai_elevenlabs_credit_floor` -- ElevenLabs credit floor for fallback
- `sensor.elevenlabs_credits_remaining` -- Current ElevenLabs credits
- 8 FP2 binary sensors -- Zone presence for speaker routing
- `input_boolean.ai_fp2_zone_*_enabled` -- Per-zone toggles

## Package Pairing

Pairs with `packages/ai_tts_queue.yaml` (kill switch, default speaker, playback timeout, cache settings) and `packages/ai_budget.yaml` (daily counters, cost sensors, budget fallback). Status sensor: `sensor.ai_tts_queue_status`.

## Called By

- **Every module that produces audio**: `notification_dedup.py`, `proactive_briefing.py`, `voice_handoff.py`, and all TTS-producing blueprints
- **Budget system**: Counter values read by `sensor.ai_total_daily_cost` template sensor and `ai_budget.yaml` package
- **Blueprints**: All blueprint TTS calls route through `tts_queue_speak`

## Notes

- **Thread safety**: Queue operations use `threading.Lock`. Only one `_process_queue` runs at a time.
- **Priority preemption**: Higher-priority item triggers `media_stop` on current speaker. Preempted items are NOT re-queued (truncated, not retried).
- **Ambient queue cap**: Maximum 3 ambient (priority 4) items in queue to prevent flood.
- **Tool narration sanitization**: Extensive regex patterns strip leaked function names, JSON fragments, entity IDs, URLs, CSS, email artifacts, and other non-speech content before TTS playback.
- **ElevenLabs credit gate**: In `_play_item`, ElevenLabs voices are swapped to HA Cloud when budget fallback is active OR credits are below floor. Fail-open design.
- **Voice agent map**: Maps TTS entity to agent name (rick, quark, kramer, deadpool, portuondo, custom) for per-agent budget tracking.
- **Speaker config**: Zone-to-speaker mapping auto-discovered from entity registry area assignments, merged with manual `tts_speaker_config.json`, cached in memory.
- **Cache tiers**: static (90-day expiry), daily (cleaned daily), session (cleaned daily), none (no caching). Cache check before TTS generation to avoid duplicate API calls.
- **Budget persistence**: Counters saved to L2 every 30 minutes and at midnight. Restored from L2 on startup with 3-attempt exponential backoff.
- **Deferred queue**: Items queued during phone calls are deferred and flushed back when the call ends.
