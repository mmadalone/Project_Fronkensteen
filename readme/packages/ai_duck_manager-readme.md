![AI Duck Manager](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/ai_duck_manager-header.jpeg)

# AI Duck Manager — Unified Volume Ducking

Central duck/restore engine for satellite wake words, TTS queue playback, and external volume management. Handles ducking media players when voice events occur and restoring volumes afterward, with a watchdog for stale sessions.

## What's Inside

- **Input helpers:** Multiple (moved to consolidated helper files) -- booleans, texts, numbers

Note: This package file contains only comments after helper consolidation. All entity definitions live in the respective `helpers_*.yaml` files.

## Entity Reference

| Entity ID | Type | Purpose |
|---|---|---|
| `input_boolean.ai_duck_guard_enabled` | input_boolean | Global duck guard toggle |
| `input_boolean.ducking_flag` | input_boolean | Active ducking state flag |
| `input_text.ai_duck_group` | input_text | Media players to duck (short IDs, `media_player.` prefix auto-added) |
| `input_text.ai_tts_restore_satellites` | input_text | Assist satellite entities that trigger ducking on wake |
| `input_number.ai_tts_duck_volume` | input_number | Target volume during ducking |
| `input_number.ai_tts_announcement_volume` | input_number | Speaker boost volume during voice events |
| `input_select.ai_tts_restore_mode` | input_select | Restore strategy selector |
| `input_number.ai_tts_restore_fixed_delay` | input_number | Fixed delay before restore |
| `input_number.ai_tts_restore_timeout` | input_number | Watchdog timeout for stale sessions |

## Dependencies

- **Pyscript:** `pyscript/duck_manager.py` (duck/restore engine, snapshot management, watchdog)
- **Pyscript:** `pyscript/tts_queue.py` (TTS playback triggers ducking)
- **Reuses helpers from:** `ai_tts_queue.yaml` (shared volume/restore configuration)

## Cross-References

- **8 blueprints** call `pyscript.duck_manager_update_snapshot` after volume changes: `wake-up-guard`, `escalating_wakeup_guard`, `media_play_at_volume`, `bedtime_instant`, `goodnight_negotiator_llm_driven`, `bedtime_routine`, `bedtime_routine_plus`, `voice_play_bedtime_audiobook`
- **Blueprint:** `duck_refcount_watchdog.yaml` -- refcount-based guard similar to follow-me bypass
- **Package:** `ai_context_hot.yaml` -- media volume state visible in hot context

## Notes

- The duck group uses short entity IDs (e.g., `workshop_ma`) with automatic `media_player.` prefix addition.
- The watchdog force-restores volumes if a ducking session exceeds the timeout, preventing permanently muted media.
- Deployed as part of the duck guard implementation (2026-03-06).
