# AI TTS Queue

Provides helper entities and a cache hit rate sensor for the centralized TTS queue manager. The queue handles prioritized, deduplicated TTS playback with caching, volume ducking, phone call deferral, and per-zone routing. Part of Task 8 / DC-3, DC-10, DC-11 of the Voice Context Architecture.

## What's Inside

| Type | Count |
|------|-------|
| Template sensors | 1 |
| Input helpers (external) | ~15 |

## Entity Reference

| Entity ID | Type | Purpose |
|-----------|------|---------|
| `sensor.ai_tts_cache_hit_rate` | Template sensor | Cache hit percentage (hits / total calls, clamped 0-100%) |
| `input_boolean.ai_tts_queue_active` | Input Boolean | Kill switch for the TTS queue |
| `input_boolean.ai_tts_volume_restore` | Input Boolean | Whether to restore volume after TTS playback |
| `input_boolean.ai_tts_strip_stage_directions` | Input Boolean | Strip stage directions from TTS text |
| `input_number.ai_tts_daily_limit` | Input Number | Daily TTS call limit |
| `input_number.ai_tts_chars_today` | Input Number | TTS characters consumed today |
| `input_number.ai_tts_cache_hits_today` | Input Number | Cache hits today |
| `input_number.ai_tts_calls_today` | Input Number | Total TTS calls today |
| `input_number.ai_tts_duck_volume` | Input Number | Volume level during ducking |
| `input_number.ai_tts_announcement_volume` | Input Number | Volume level for announcements |
| `input_number.ai_tts_restore_fixed_delay` | Input Number | Fixed delay before volume restore |
| `input_number.ai_tts_restore_timeout` | Input Number | Max time to wait for restore |
| `input_number.ai_tts_restore_post_buffer` | Input Number | Buffer after restore completes |
| `input_number.ai_tts_cache_static_max_days` | Input Number | Max age for static cache entries |
| `input_number.ai_tts_cache_max_size_mb` | Input Number | Max cache size in MB |
| `input_number.ai_tts_cache_protect_hours` | Input Number | Hours to protect recent cache entries from eviction |
| `input_text.ai_tts_zone_priority` | Input Text | Zone priority ordering for multi-zone playback |
| `input_text.ai_tts_restore_satellites` | Input Text | Satellites to restore after TTS |

## Dependencies

- **Pyscript:** `pyscript/tts_queue.py` — queue manager, caching, ducking, deferred playback, daily housekeeping
- **Package:** `ai_test_harness.yaml` — test mode routes TTS to log sink
- **Package:** `ai_phone_call_detection.yaml` — deferred playback during calls
- **Helper files:** `helpers_input_boolean.yaml`, `helpers_input_number.yaml`, `helpers_input_text.yaml`

## Cross-References

- **Nearly every blueprint** that produces speech calls `pyscript.tts_queue_speak`
- **ai_phone_call_detection.yaml** — triggers `tts_queue_flush_deferred` on call end
- **Budget tracking** (`ai_budget.yaml` / `common_utilities.py`) — `ai_tts_chars_today` feeds daily cost computation
- **Duck guard** (`ai_duck_manager.yaml`) — coordinates volume ducking with TTS playback
- **Voice handoff** (`voice_handoff.yaml`) — uses TTS queue for farewell/greeting speech

## Notes

- Midnight counter reset is handled by `tts_queue_daily_housekeeping` in `pyscript/tts_queue.py`, not by a package automation.
- The cache hit rate sensor clamps output between 0-100% and handles the zero-calls case gracefully.
- `ai_tts_strip_stage_directions` removes theatrical markup (e.g. `*sighs*`) from TTS text before synthesis.
