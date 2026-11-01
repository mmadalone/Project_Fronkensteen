# Media Promotion Engine — Radarr/Sonarr to L2/L1

I-47 of the Voice Context Architecture. Fetches upcoming releases and recent downloads from Radarr and Sonarr REST APIs, promotes formatted summaries into L2 memory and L1 helpers for agent hot context and proactive briefings. Stateless service driven by the `media_tracking.yaml` blueprint -- the module has no scheduling of its own.

## Services

| Service | Parameters | Returns | Description |
|---------|-----------|---------|-------------|
| `pyscript.media_promote_now` | `upcoming_days` (1 or 7), `download_hours` (24 or 168), `write_l1` (bool), `force` (bool) | `{status, op, upcoming_tv, upcoming_movies, recent_tv, recent_movies, upcoming_summary, sonarr_line, radarr_line, recent_summary, new_downloads_since_last, tv_queue, movie_queue}` | Promote Radarr/Sonarr data to L2 memory and L1 hot context helpers. Supports daily (1 day) and weekly (7 days) windows. `supports_response="only"` |

## Triggers

| Trigger | Function | Condition |
|---------|----------|-----------|
| `@time_trigger("startup")` | `_startup` | Loads Radarr/Sonarr API keys from HA config entries, then finds the Sonarr/Radarr entities |
| `@event_trigger("entity_registry_updated")` | `_arr_registry_changed` | Finds the Sonarr/Radarr entities again 20 s after the last registry change (debounced) |

## Key Functions

- `_refresh_arr_entities()` — Finds the Sonarr Upcoming and Queue sensors and the Radarr Queue sensor and calendar in the entity registry (file read in `_resolve_arr_entities_sync()`, an executor function). Logs the result when it changes
- `_arr_entity()` — Entity ID of one of those entities, or `""` when the install has none
- `_fetch_upcoming_tv()` — For daily: reads the Sonarr Upcoming sensor's attributes (zero API cost; `[]` when the install has no such sensor). For weekly: calls Sonarr REST `/api/v3/calendar`.
- `_fetch_upcoming_movies()` — Reads the Radarr calendar's events via HA's calendar.get_events service (`[]` when the install has no Radarr calendar)
- `_get_queue_count()` — Reads a Queue sensor's state as a count; 0 when there is no sensor or it is unknown/unavailable
- `_fetch_recent_downloads()` — Calls Radarr/Sonarr REST `/api/v3/history` for recently imported media
- `_format_sonarr_line()` / `_format_radarr_line()` — Per-service L1 lines (max 255 chars each)
- `_format_upcoming_line()` — Combined upcoming summary for backward compatibility
- `_format_recent_line()` — Recent downloads for briefing helper
- `_parse_sonarr_upcoming_attrs()` — Handles two Sonarr attribute formats: structured (dict list) and flat (HA native)
- `_parse_history_response()` — Parses history API response with dedup by title

## State Dependencies

- `input_boolean.ai_media_tracking_enabled` — Kill switch
- `input_boolean.ai_media_data_stale` — Stale flag set on API failure
- `sensor.ai_media_upcoming` — Consolidated L1 sensor (state=summary, attrs: `sonarr`, `radarr`, `recent_downloads`). Replaced the four `input_text` helpers in Phase 2.
- Sonarr Upcoming sensor — Native Sonarr sensor (daily upcoming, zero API cost)
- Sonarr and Radarr Queue sensors — Queue counts. Both integrations ship them disabled: enable them for queue counts
- Radarr calendar entity — Upcoming movies

The Sonarr/Radarr entities are found in the entity registry, not named in the code (see Notes).

## Package Pairing

Pairs with `packages/ai_media_tracking.yaml` which defines all media helpers, the stale flag, and the `sensor.ai_media_promotion_status` result entity. Scheduling is handled by the `media_tracking.yaml` blueprint, not this module.

## Called By

- **media_tracking.yaml (blueprint)** — sole caller. The blueprint handles scheduling (daily/weekly/on-demand) and passes appropriate `upcoming_days` and `download_hours` parameters.
- **proactive_briefing.py** — reads L1 helpers for media sections in briefings

## Notes

- Stateless service design: this module has no cron triggers or state triggers. All scheduling is delegated to the `media_tracking.yaml` blueprint, making the pyscript module purely a data-fetch-and-format engine.
- API keys are read from HA config entries at startup (not from secrets.yaml or helpers). This means Radarr/Sonarr must be configured as HA integrations.
- Entity discovery: the Sonarr/Radarr entities are matched by registry unique_id `<config entry id>_<key>` (keys `upcoming`, `queue`, `calendar`), from the first Sonarr and the first Radarr config entry (the same entries the API calls use). Renamed, translated (e.g. `sensor.sonarr_cola`) or `_2`-suffixed entity IDs all work. Disabled entities are skipped. A missing Queue sensor counts as 0 (the queue is left out of the summary); a missing Upcoming sensor (daily window) or Radarr calendar gives an empty list. The lookup re-runs on entity registry changes, so enabling a Queue sensor or renaming an entity needs no restart. If the registry file can't be read, the previous result is kept.
- New download detection: the module tracks titles seen in the previous run via `_last_downloads` set. The `new_downloads_since_last` count in the response tells the blueprint whether to fire a new-download notification.
- 5-minute promote cache debounces rapid triggers from the blueprint. Use `force=True` to bypass.
- API failure handling mirrors calendar_promote: stale flag set on failure, existing L2 data preserved, persistent notification after 3 consecutive failures.
- Stale multi-day Radarr events (e.g., "in cinemas" events spanning weeks) are filtered by checking if the start date is before today.
- 10-second API timeout per request via `aiohttp.ClientTimeout`.
