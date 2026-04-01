# Kodi Watch History Tracker -- Pyscript Module

Tracks what is watched on Kodi across all sources (PVR, YouTube, Netflix, Prime Video, Movistar+, library content). Classifies content via JSON-RPC source detection and EPG data, measures watch duration with configurable minimum thresholds, and logs to L2 memory. Stateless services driven by the `watch_history.yaml` blueprint -- the module has no scheduling of its own beyond startup config loading.

## Services

| Service | Parameters | Returns | Description |
|---------|-----------|---------|-------------|
| `pyscript.watch_history_start` | `title`, `category`, `source` | status dict | Start tracking a watch session. Fetches EPG data for PVR content, begins duration timer. |
| `pyscript.watch_history_stop` | -- | status dict | Stop tracking current session. Logs to L2 memory if duration exceeds threshold; otherwise counts as channel flip. |
| `pyscript.watch_history_pause` | -- | status dict | Pause/resume current watch session (for ad breaks, paused playback). |

## Triggers

| Trigger | Function | Condition |
|---------|----------|-----------|
| `@time_trigger("startup")` | `_startup` | Loads Kodi JSON-RPC connection config from `hass.config_entries.async_entries("kodi")` |

## Key Functions

- `_detect_source()` -- Calls Kodi JSON-RPC `Player.GetItem` and inspects the `file` property. Matches `plugin://` URLs against known patterns (inputstream.adaptive for Netflix/Prime/Movistar+, plugin.video.youtube, etc.)
- `_fetch_epg_data()` -- For PVR content: calls `PVR.GetBroadcasts` on the active channel, performs linear scan for `isactive=True` broadcast. Extracts season, episode number, episode name from EPG metadata.
- `_encode_auth()` -- `@pyscript_compile` function for base64 auth header encoding (sandbox blocks `import base64` in regular pyscript context)
- `_log_to_memory()` -- Writes watch session to L2 memory with key `watch_history:{category}:{title}` and tags `media,watch_history,{category},{source}`

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
- **template.yaml** -- template sensor enrichment reads watch history sensor for season/episode/source/episode_name.

## Notes

- Kodi JSON-RPC config is read from HA config entries at startup (same pattern as `media_promote.py` for Radarr/Sonarr). No hardcoded URLs or credentials.
- Channel surfing detection: below-threshold PVR watch sessions are counted as "flips" rather than logged individually. The flip count is tracked in the session sensor attributes.
- Blueprint uses `mode: restart` to handle rapid channel switches -- each new channel cancels the previous tracking session.
- EPG data enrichment: for PVR content, the module fetches live broadcast metadata to populate season/episode fields that Kodi's player info alone doesn't provide.
- Source detection is keyword-based on `plugin://` file paths. Known sources: YouTube (`plugin.video.youtube`), Netflix/Prime/Movistar+ (inputstream.adaptive patterns), PVR (no file path), library (local paths).

## Changelog

- **v1:** Initial implementation.

## Author

**madalone**

## License

See repository for license details.
