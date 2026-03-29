# AI Media Tracking — Radarr/Sonarr Integration

Thin storage package for the media tracking subsystem (I-47). Provides helper entities that store upcoming Radarr/Sonarr release data for injection into voice agent context. All configuration knobs and trigger logic live in the blueprint.

## What's Inside

- **Input helpers:** 2 (moved to consolidated helper files) -- 2 booleans
- **Sensors:** 1 pyscript sensor (`sensor.ai_media_upcoming`)

## Entity Reference

| Entity ID | Type | Purpose |
|---|---|---|
| `input_boolean.ai_media_tracking_enabled` | input_boolean | Kill switch for media tracking |
| `input_boolean.ai_media_data_stale` | input_boolean | Set when media API fails |
| `sensor.ai_media_upcoming` | sensor (pyscript) | Media summary with `sonarr`, `radarr`, `recent_downloads` attributes (created by pyscript `state.set()`) |
| `sensor.ai_media_promotion_status` | sensor (pyscript) | Last sync result and promoted media counts |

## Dependencies

- **Pyscript:** `pyscript/media_promote.py` (data service for Radarr/Sonarr API queries)
- **Blueprint:** `blueprints/automation/madalone/media_tracking.yaml` (triggers + configuration)

## Cross-References

- **Package:** `ai_context_hot.yaml` -- `sensor.ai_media_upcoming` attributes (`sonarr`, `radarr`) injected into the Media component when tracking is enabled

## Notes

- Intentionally thin package -- the blueprint owns all configuration (API URLs, poll intervals, filters) and the pyscript module handles data fetching. This package only provides the storage layer.
- Phase 2 consolidation replaced `input_text.ai_media_upcoming_sonarr` and `input_text.ai_media_upcoming_radarr` with `sensor.ai_media_upcoming` (pyscript `state.set()`, no 255-char limit).
- Deployed: 2026-03-10.
