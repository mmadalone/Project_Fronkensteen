# AI Media Tracking — Radarr/Sonarr Integration

Thin storage package for the media tracking subsystem (I-47). Provides helper entities that store upcoming Radarr/Sonarr release data for injection into voice agent context. All configuration knobs and trigger logic live in the blueprint.

## What's Inside

- **Input helpers:** 2 (moved to consolidated helper files) -- 1 boolean, 1 text (x2: Sonarr + Radarr)

## Entity Reference

| Entity ID | Type | Purpose |
|---|---|---|
| `input_boolean.ai_media_tracking_enabled` | input_boolean | Kill switch for media tracking |
| `input_text.ai_media_upcoming_sonarr` | input_text | Upcoming Sonarr (TV) releases summary |
| `input_text.ai_media_upcoming_radarr` | input_text | Upcoming Radarr (movie) releases summary |

## Dependencies

- **Pyscript:** `pyscript/media_promote.py` (data service for Radarr/Sonarr API queries)
- **Blueprint:** `blueprints/automation/madalone/media_tracking.yaml` (triggers + configuration)

## Cross-References

- **Package:** `ai_context_hot.yaml` -- Sonarr and Radarr summaries injected into the Media component when tracking is enabled

## Notes

- Intentionally thin package -- the blueprint owns all configuration (API URLs, poll intervals, filters) and the pyscript module handles data fetching. This package only provides the storage layer.
- Deployed: 2026-03-10.
