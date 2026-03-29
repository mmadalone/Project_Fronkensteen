# Duck Manager — Unified Volume Ducking Engine

Reference-counted session-based volume ducking for media players. The first session captures current volumes and ducks; the last session ending restores. Multiple sources (satellite wake, TTS queue, external callers) can overlap safely without race conditions. Includes crash recovery via JSON snapshot file and a watchdog that force-restores stale sessions.

## Services

| Service | Parameters | Returns | Description |
|---------|-----------|---------|-------------|
| `pyscript.duck_manager_duck` | `source` (default "external"), `detail` | `{status, op, session_id}` | Start a ducking session. Captures and ducks on the first session. Returns a session_id for later restore. `supports_response="only"` |
| `pyscript.duck_manager_restore` | `session_id`, `wait_for_playback` (default true) | `{status, op, restored, remaining_sessions}` | End a ducking session. Waits for announcement players to finish, then restores volumes when the last session ends. `supports_response="only"` |
| `pyscript.duck_manager_force_restore` | _(none)_ | `{status, op}` | Emergency: clear all sessions and restore volumes immediately. Used for recovery from stuck ducking state. `supports_response="only"` |
| `pyscript.duck_manager_status` | _(none)_ | `{status, op, active_sessions, sessions, snapshot_entries, snapshot, ducking_flag, last_duck_event}` | Debug: returns all active sessions, volume snapshot, and flag state. `supports_response="only"` |
| `pyscript.duck_manager_mark_user_adjusted` | `entity_id` | `{status, op, entity_id}` | I-22: Mark a media player as user-adjusted during ducking. On restore, its volume will not be reset to the pre-duck level. `supports_response="only"` |
| `pyscript.duck_manager_update_snapshot` | `entity_id`, `volume_level` | `{status, op, entity_id, old_volume, new_volume}` | Duck guard: update the snapshot for a media player so restore uses the new volume instead of the stale pre-duck level. Called by blueprints after `volume_set` during active ducking. Returns `noop` if not ducking or entity not in snapshot. `supports_response="only"` |

## Triggers

| Trigger | Function | Condition |
|---------|----------|-----------|
| `@state_trigger(assist_satellite entities)` | `_on_satellite_change` | Ducks when any configured satellite leaves idle state, restores when all satellites return to idle. 2-second debounce on restore. |
| `@time_trigger("cron(* * * * *)")` | `_duck_watchdog` | Every-minute watchdog: checks for stale sessions exceeding timeout and force-restores. Creates persistent notification on watchdog trigger. |
| `@time_trigger("startup")` | `_duck_manager_startup` | Crash recovery from snapshot file, clears stale state, initializes helper defaults |

## Key Functions

- `_capture_and_duck()` — Two-pass volume capture: Pass 1 reads volumes directly, Pass 2 uses buddy fallback or default volume for devices that failed to report. Then sets duck/announcement volumes.
- `_restore_and_verify()` — Two-pass restore: Pass 1 sets all volumes, waits 1.5s, Pass 2 verifies and retries any that didn't stick. Skips user-adjusted entities (I-22).
- `_wait_for_announcements_done()` — Dynamic or fixed-delay wait for TTS playback to finish before restoring. Dynamic mode polls announcement player states with 250ms intervals.
- `_get_volume_buddies()` — Derives buddy map from volume_sync group helpers. Alexa devices (unreliable volume reporters) use their buddy's volume as fallback.
- `_save_snapshot()` / `_load_snapshot()` — JSON file persistence for crash recovery

## State Dependencies

- `input_boolean.ai_duck_manager_enabled` — Kill switch
- `input_boolean.ai_ducking_flag` — Set ON during active ducking, used by volume_sync to skip synchronization
- `entity_config.yaml` `duck.group` — List of media players to duck (moved from `input_text` in Phase 2)
- `entity_config.yaml` `duck.announcement_players` — List of players to boost for TTS (moved from `input_text` in Phase 2)
- `entity_config.yaml` `duck.satellites` — List of satellites that trigger ducking (moved from `input_text` in Phase 2)
- `input_number.ai_duck_volume` — Volume level during ducking (0.0-1.0)
- `input_number.ai_duck_announce_volume` — Volume level for announcement players
- `input_number.ai_duck_watchdog_timeout` — Seconds before watchdog force-restores (default: 120)
- `input_select.ai_tts_restore_mode` — Restore timing: `fixed` or `dynamic`
- `input_number.ai_duck_restore_delay` / `ai_duck_restore_timeout` / `ai_duck_post_buffer` — Restore timing parameters
- `input_select.ai_duck_behavior` — I-39: `volume`, `pause`, or `both`
- `input_number.ai_duck_pre_delay_ms` — I-21: Pre-delay before first duck (0-2000ms)
- `input_boolean.ai_duck_allow_manual_override` — I-22: Whether user volume changes during duck are respected
- `input_number.ai_duck_default_volume` — Fallback volume when capture fails and no buddy available
- `entity_config.yaml` `vsync_zones` — Volume sync zone config (players + alexa lists per zone) for buddy fallback (moved from `input_text` in Phase 2)

## Package Pairing

Pairs with `packages/ai_duck_manager.yaml` which defines all ducking helpers, the ducking flag, volume sync groups, and the `sensor.ai_duck_manager_status` result entity.

## Called By

- **tts_queue.py** — calls `duck_manager_duck` / `duck_manager_restore` around TTS playback
- **Satellite state changes** — automatic via `@state_trigger` on assist_satellite entities
- **8 blueprints (19 sites)** — call `duck_manager_update_snapshot` after `volume_set` during active ducking (wake-up-guard, escalating_wakeup_guard, media_play_at_volume, bedtime_instant, goodnight_negotiator, bedtime_routine, bedtime_routine_plus, voice_play_bedtime_audiobook)
- **Dashboard** — `duck_manager_status` and `duck_manager_force_restore` for debugging

## Notes

- Reference counting is the core design: multiple concurrent duck sources (satellite wake, TTS queue, external) can overlap safely. Only the first session captures volumes, and only the last session ending restores them.
- The volume buddy system handles unreliable Alexa volume reporting: Alexa devices are mapped to a non-Alexa "buddy" in the same volume_sync group, and the buddy's captured volume is used as fallback.
- I-39 (duck behavior): supports `pause` mode (pause media instead of reducing volume) and `both` mode (pause and reduce). Media is resumed on restore.
- I-22 (manual override): if a user manually adjusts volume during ducking, that entity is skipped during restore to respect the user's intent.
- Crash recovery: the volume snapshot is persisted to `/config/pyscript/duck_snapshot.json` after every duck. On startup, if the file exists, volumes are restored and the file is cleared.
- Satellite triggers are registered dynamically at startup from `entity_config.yaml` `duck.satellites`. To add/remove satellites: update `entity_config.yaml`, then `pyscript.reload` or HA restart.
