# Kodi Watch History Tracker -- Pyscript Module

Tracks what is watched on Kodi across all sources (PVR, YouTube, Netflix, Prime Video, Movistar+, Disney+, HBO Max, Filmin, library content). Classifies content via JSON-RPC source detection, EPG data, and direct media_player entity reads. Measures watch duration with configurable minimum thresholds and logs to L2 memory. Stateless services driven by the `watch_history.yaml` blueprint -- the module has no scheduling of its own beyond startup config loading.

## Services

| Service | Parameters | Returns | Description |
|---------|-----------|---------|-------------|
| `pyscript.watch_history_start` | `entity_id`, `media_category`, `media_title`, `series_title`, `season`, `episode`, `pvr_channel`, `pvr_channel_number`, `pvr_programme`, `recovered` | status dict | Start tracking a watch session. Reads media_player entity directly for ground-truth metadata, fetches EPG data via JSON-RPC for PVR content, begins duration timer. |
| `pyscript.watch_history_stop` | `entity_id`, `min_duration_pvr`, `min_duration_content`, `retention_days`, `summary_retention_days` | status dict | Stop tracking current session. Logs to L2 memory if duration exceeds threshold; otherwise counts as channel flip. |
| `pyscript.watch_history_pause` | `entity_id` | status dict | Mark session as paused (sensor update only, no log). Session remains active for eventual stop. |

## Triggers

| Trigger | Function | Condition |
|---------|----------|-----------|
| `@time_trigger("startup")` | `_startup` | Loads Kodi JSON-RPC connection config from `hass.config_entries.async_entries("kodi")` |

## Key Functions

- `_fetch_kodi_metadata()` -- Calls Kodi JSON-RPC `Player.GetItem` and inspects the `file` property. Matches `plugin://` URLs against known source patterns (`plugin.video.youtube`, `plugin.video.netflix`, `plugin.video.filmin`, etc.). For PVR channels, also fetches EPG data via `_fetch_active_epg()`.
- `_fetch_active_epg()` -- For PVR content: calls `PVR.GetBroadcasts` on the active channel, performs linear scan in batches of 30 for `isactive=True` broadcast. Extracts season, episode number, episode name from EPG metadata.
- `_b64_encode()` -- `@pyscript_compile` function for base64 auth header encoding (sandbox blocks `import base64` in regular pyscript context).
- `_l2_set()` -- Writes watch session to L2 memory with key `watch:{date}:{index}` and tags `media,watch_history,{category},{source}`.

## State Dependencies

- `input_boolean.ai_watch_history_enabled` -- Kill switch
- `input_number.ai_watch_min_duration_pvr` -- Minimum seconds for PVR content to be logged (default 180)
- `input_number.ai_watch_min_duration_content` -- Minimum seconds for non-PVR content to be logged (default 120)
- `input_number.ai_watch_history_retention_days` -- L2 memory retention
- `sensor.ai_watch_history_status` -- Runtime state sensor (seeded by `state_bridge.py` at boot)

## Package Pairing

Pairs with `packages/ai_watch_history.yaml` (thin doc package). All triggers and scheduling are handled by the `watch_history.yaml` blueprint, not this module.

## Called By

- **watch_history.yaml (blueprint)** -- sole caller. The blueprint handles Kodi state triggers and PVR channel-switch detection (`content_change` trigger on `sensor.madteevee_now_playing`).
- **ai_context_hot.yaml** -- reads `sensor.ai_watch_history_status` for "Now watching" / "Recently watched" hot context lines.
- **template.yaml** -- `sensor.madteevee_now_playing` reads `media_source` and `episode_name` from the watch history sensor. `series_title`/`season`/`episode` read from `media_player` only (no pyscript fallback — AP-78). PVR show name carried by `pvr_programme` attribute instead.

## Notes

- Kodi JSON-RPC config is read from HA config entries at startup (same pattern as `media_promote.py` for Radarr/Sonarr). No hardcoded URLs or credentials.
- **Direct media_player read:** `watch_history_start` reads `media_series_title`, `media_season`, `media_episode`, `media_title`, and `media_content_type` directly from the media_player entity via `state.getattr()`. This avoids circular dependencies with the template sensor and ensures ground-truth metadata for library and streaming content. Blueprint-passed parameters serve as fallback only.
- **Category inference:** `media_content_type` is mapped to category (`tvshow`→`series`, `movie`→`movie`). For streaming addons that report `video` for everything, series are detected by the presence of `media_series_title`. PVR is detected by JSON-RPC source. Priority: media_player attrs > blueprint params > EPG override for PVR.
- **Episode name fallback:** For library/streaming series where EPG data doesn't exist, `current_episode_name` is populated from `media_title` (which IS the episode name for series content).
- Channel surfing detection: below-threshold PVR watch sessions are counted as "flips" rather than logged individually. The flip count is tracked in the session sensor attributes.
- Blueprint uses `mode: restart` to handle rapid channel switches -- each new channel cancels the previous tracking session.
- **Descriptive sensor state:** `_build_display_state()` sets sensor state to e.g. `"watching Seinfeld S03E10"` or `"watching Cartoon Network — Family Guy S06E01"` instead of generic `"watching"`. HA logbook shows the descriptive text in state change entries.
- EPG data enrichment: for PVR content, the module fetches live broadcast metadata to populate season/episode fields that Kodi's player info alone doesn't provide. EPG overrides all other sources for PVR.
- Source detection is keyword-based on `plugin://` file paths. Known sources: YouTube (`plugin.video.youtube`), Netflix (`plugin.video.netflix`), Prime Video (`plugin.video.amazon`), Movistar+ (`plugin.video.movistarplus`), Disney+ (`plugin.video.disney`), HBO Max (`plugin.video.hbomax`), Filmin (`plugin.video.filmin`), PVR (`pvr://`), library (local paths with `movie`/`episode` item type).

## Changelog

- **v1:** Initial implementation.
- **v1.1:** Template sensor circular dependency resolved — `series_title`/`season`/`episode` read from media_player only, no pyscript fallback (AP-78).

## Author

**madalone**

## License

See repository for license details.
