![AI Duck Manager](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/ai_duck_manager-header.jpeg)

# AI Duck Manager — Unified Volume Ducking

Central duck/restore engine for satellite wake words, TTS queue playback, and external volume management. Handles ducking media players when voice events occur and restoring volumes afterward, with a watchdog for stale sessions.

## What's Inside

- **Input helpers:** Multiple (moved to consolidated helper files) -- booleans, texts, numbers

Note: This package file contains only comments after helper consolidation. All entity definitions live in the respective `helpers_*.yaml` files.

## Entity Reference

| Entity ID | Type | Purpose |
|---|---|---|
| `sensor.ai_duck_manager_status` | sensor (pyscript) | Duck manager status: last_duck_source, last_duck_detail, last_duck_duration_s, last_duck_time, last_duck_sessions |
| `input_boolean.ai_duck_guard_enabled` | input_boolean | Global duck guard toggle |
| `input_boolean.ai_ducking_flag` | input_boolean | Active ducking state flag |
| `input_boolean.ai_duck_manager_enabled` | input_boolean | Duck manager master toggle |
| `input_boolean.ai_duck_allow_manual_override` | input_boolean | Allow manual volume override during ducking |
| `input_select.ai_duck_behavior` | input_select | Duck behavior mode selector |
| `input_number.ai_duck_watchdog_timeout` | input_number | Watchdog timeout for stale sessions |
| `input_number.ai_duck_pre_delay_ms` | input_number | Pre-delay before ducking starts |
| `input_number.ai_duck_default_volume` | input_number | Default volume level |
| `input_number.ai_duck_volume` | input_number | Target volume during ducking |
| `input_number.ai_duck_announce_volume` | input_number | Speaker boost volume during voice events |
| `input_number.ai_duck_restore_delay` | input_number | Delay before volume restore |
| `input_number.ai_duck_restore_timeout` | input_number | Restore timeout |
| `input_number.ai_duck_post_buffer` | input_number | Post-duck buffer time |
| `entity_config.yaml: duck.group` | config | Media players to duck (moved from input_text) |
| `entity_config.yaml: duck.announcement_players` | config | Announcement player entities |
| `entity_config.yaml: duck.satellites` | config | Assist satellite entities that trigger ducking |
| `entity_config.yaml: vsync_zones` | config | Volume sync zone configuration |

## Dependencies

- **Pyscript:** `pyscript/duck_manager.py` (duck/restore engine, snapshot management, watchdog)
- **Pyscript:** `pyscript/tts_queue.py` (TTS playback triggers ducking)
- **Reuses helpers from:** `ai_tts_queue.yaml` (shared volume/restore configuration)

## Cross-References

- **20+ blueprints** call `pyscript.duck_manager_update_snapshot` after volume changes, including: `wake-up-guard`, `escalating_wakeup_guard`, `media_play_at_volume`, `bedtime_instant`, `goodnight_negotiator_llm_driven`, `bedtime_routine`, `bedtime_routine_plus`, `voice_play_bedtime_audiobook`, `notification_follow_me`, `email_follow_me`, `speaker_volume_sync`, `proactive_briefing`, `proactive_bedtime_escalation`, `llm_alarm`, `alexa_presence_radio`, and others
- **Package:** `ai_context_hot.yaml` -- media volume state visible in hot context

## Notes

- Duck group, announcement players, satellites, and vsync zone config moved from `input_text` helpers to `entity_config.yaml` sections (`duck:` and `vsync_zones:`) during Phase 2 consolidation.
- The watchdog force-restores volumes if a ducking session exceeds the timeout, preventing permanently muted media.
- Also reuses shared helpers from `ai_tts_queue.yaml` (`input_number.ai_tts_duck_volume`, `ai_tts_announcement_volume`, `input_select.ai_tts_restore_mode`, `input_number.ai_tts_restore_fixed_delay`, `ai_tts_restore_timeout`, `input_text.ai_tts_restore_satellites`).
- Deployed as part of the duck guard implementation (2026-03-06).
