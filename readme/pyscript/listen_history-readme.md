# Music Listen History Tracker -- Pyscript Module

Tracks music listening sessions on Music Assistant / Spotify players with duration measurement. Classifies content source (track, radio, podcast, audiobook) via `media_content_id` prefix parsing and `media_content_type` attribute detection. Measures listen duration with a configurable minimum threshold and logs to L2 memory. Stateless services driven by the `listen_history.yaml` blueprint -- the module has no scheduling of its own beyond startup initialization.

## Services

| Service | Parameters | Returns | Description |
|---------|-----------|---------|-------------|
| `pyscript.listen_history_start` | `entity_id`, `media_artist`, `media_title`, `media_album`, `media_content_id`, `media_content_type`, `recovered` | status dict | Start tracking a listen session. Classifies source, detects TTS (rejects immediately), auto-closes previous session on track change. |
| `pyscript.listen_history_stop` | `entity_id`, `min_duration`, `retention_days`, `summary_retention_days` | status dict | Stop tracking current session. Logs to L2 memory if duration exceeds threshold. Multi-player aware: shows remaining active session if any. |
| `pyscript.listen_history_pause` | `entity_id` | status dict | Mark session as paused (sensor update only, no log). Session remains active for eventual stop. |

## Triggers

| Trigger | Function | Condition |
|---------|----------|-----------|
| `@time_trigger("startup")` | `_startup` | Clears stale sessions, seeds sensor |

## Key Functions

- `_classify_source()` -- Priority chain: (1) TTS detection (`media_content_type == "tts"`, `/api/tts_proxy/`, `media-source://tts/`), (2) podcast/audiobook via `media_content_type`, (3) Spotify URI parsing (`spotify:episode:`, `spotify:audiobook:`), (4) MA content_id prefixes (`library://radio/`, `library://playlist/`, `library://album/`, `library://track/`), (5) known MA player fallback, (6) unknown.
- `_derive_room()` -- Extracts human-readable room from entity_id (`media_player.workshop_ma` -> "Workshop", `spotifyplus` -> "Spotify").
- `_format_listen_entry()` -- Content-type aware formatting: tracks ("Listened to Artist -- Title [Album]"), radio ("Listened to radio: Station"), podcasts ("Listened to podcast: Show -- Episode"), audiobooks ("Listened to audiobook: Author -- Title").
- `_close_session()` -- Duration computation, threshold check, L2 write with dynamic tags, daily entry tracking.
- `_check_daily_rollover()` -- Midnight rollover: writes yesterday's summary to L2, resets daily counters.
- `_l2_set()` -- Writes listen session to L2 memory with key `listen:{date}:{index}` and tags `media,listen_history,{source},{content_type}`.

## State Dependencies

- `input_boolean.ai_listen_history_enabled` -- Kill switch
- `input_number.ai_listen_min_duration` -- Minimum seconds before logging (default 60)
- `input_number.ai_listen_history_retention_days` -- L2 memory retention
- `sensor.ai_listen_history_status` -- Runtime state sensor (seeded by `state_bridge.py` at boot)
- `entity_config.yaml` -- `music_players` list + `spotifyplus_entity` (reused from music_taste)

## Package Pairing

Pairs with `packages/ai_listen_history.yaml` (thin doc package). All triggers and scheduling are handled by the `listen_history.yaml` blueprint, not this module.

## Called By

- **listen_history.yaml (blueprint)** -- sole caller. The blueprint handles media_player state triggers and `media_title` attribute changes for track-change detection.
- **ai_context_hot.yaml** -- reads `sensor.ai_listen_history_status` for "Now listening to" / "Recently listened to" hot context lines.

## Notes

- **Separate from `music_taste.py`:** Different purpose (chronological history with duration vs taste aggregation). Both trigger on same entities with no interference. Different L2 key namespaces (`listen:*` vs `music_play:*`).
- **Multi-player support:** `_active_sessions` dict is keyed by entity_id. Each player tracks independently. Blueprint uses `mode: queued` (max: 10) to prevent cross-player cancellation.
- **Multi-player sensor awareness:** When one player stops but another is still active, sensor reverts to the remaining active session (improvement over watch_history's single-entity design).
- **TTS rejection:** Long TTS content (conversations, banter, theatrical debates, therapy sessions) can exceed the min duration threshold. `_classify_source()` detects TTS via 3 checks and rejects before session creation.
- **`media_album_name` mapping:** Music Assistant uses `media_album_name` (not `media_album`). Blueprint reads the correct attribute and passes it as `media_album` parameter.
- **Content types supported:** track, radio, playlist, album, podcast, audiobook.
- **No Kodi JSON-RPC:** Unlike `watch_history.py`, this module reads attributes directly from media_player entities -- MA/Spotify expose clean metadata.
- **Descriptive sensor state:** `_build_display_state()` sets sensor state to e.g. `"listening to Radio Klara"` or `"listening to Artist — Title"` instead of generic `"listening"`. HA logbook shows the descriptive text in state change entries.

## Changelog

- **v1:** Initial implementation.

## Author

**madalone**

## License

See repository for license details.
