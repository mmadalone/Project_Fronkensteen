# Radio Klara Now-Playing Awareness -- Pyscript Module

Reads a cached weekly schedule for Radio Klara (a Valencian community radio station based in Valencia, Spain) and exposes a "now playing" sensor that tells conversation agents what show is currently airing. Optionally re-fetches the schedule from the station's PDF tríptic on a configurable interval. Architected for multi-station expansion via `entity_config.yaml` `radio_stations:` section -- adding more stations requires no code changes beyond a config entry and a bootstrap JSON file.

## Services

| Service | Parameters | Returns | Description |
|---------|-----------|---------|-------------|
| `pyscript.radio_klara_refresh_schedule` | `force` (bool, default false) | status dict | Re-fetch the schedule PDF, parse via `llm_task_call`, write JSON cache. Honors `ai_radio_klara_refresh_hours` interval unless `force=true`. Returns `{status, consecutive_failures}`. |
| `pyscript.radio_klara_now_playing` | -- | dict | Returns the current show as `{status, title, start_time, end_time, day_of_week, description, language, next_show}`. Useful for blueprint variables and ad-hoc queries. |

## Triggers

| Trigger | Function | Condition |
|---------|----------|-----------|
| `@time_trigger("startup")` | `radio_klara_startup` | Loads station config from `entity_config.yaml`, reads cached schedule from disk, seeds sensor |
| `@time_trigger("cron(*/15 * * * *)")` | `radio_klara_periodic` | Recomputes now-playing sensor every 15 min + checks if a refresh is due (compares `(now - last_refresh)` against the helper value at runtime) |
| `@state_trigger(...)` | `radio_klara_on_media_change` | When `media_title` changes on workshop_ma, bathroom_ma, or living room ESP -- recomputes the sensor immediately so blueprints reading it during transfers see fresh data |

## Key Functions

- `_now_playing_from_schedule(schedule_list, weekday_idx, current_minutes)` -- Pure compile function (no HA deps). Given the schedule + day index (0=Mon..6=Sun) + minutes-since-midnight, returns the matching show dict or `None` for off-air gaps. Handles `24:00` end times. Builds `next_show` label, walking into tomorrow's first show if today's last show is current.
- `_extract_pdf_link(html, base_url)` -- Regex-extracts the latest `triptic*.pdf` link from the schedule page HTML, falling back to any `.pdf` href. Resolves relative URLs against the base.
- `_pdf_to_text(pdf_bytes)` -- `@pyscript_executor` wrapper around `pypdf.PdfReader.extract_text()`. Returns `None` gracefully if pypdf is not installed.
- `_llm_extract_schedule(text)` -- Sends PDF text to `pyscript.llm_task_call` with a structured-extraction system prompt. Strips markdown fences, parses JSON, validates `weekly_schedule` is a list with ≥5 entries, returns the dict or `None`.
- `_do_refresh()` -- Full pipeline: fetch page → extract PDF link → download PDF → text → LLM → validate → atomic write → update sensor + helpers.
- `_refresh_failure(reason)` -- Centralized failure path: increments consecutive failure counter, sets `refresh_failed` status with reason in attributes, preserves the cache, fires persistent notification on 3+ failures.
- `_update_now_playing_sensor()` -- Computes current show + writes `state.set("sensor.ai_radio_klara_now_playing", ...)`. Handles three cases: `idle` (no schedule), `off_air` (schedule gap), or current show title (with description, language, end_time, next_show, and **station_name** in attributes). The `station_name` attribute is read from `entity_config.yaml radio_stations.radio_klara.name` (default: "Radio Klara") and is consumed by the announce_music_follow_me_llm blueprint for both the station-detection keyword match and the LLM-facing display name ("The current show on **Radio Klara** is ..."). Downstream consumers should prefer `station_name` over `friendly_name`.

## State Dependencies

- `input_boolean.ai_radio_klara_enabled` -- Master kill switch (default on). When off, hot-context line is suppressed and auto-refresh skipped. Sensor still updates.
- `input_number.ai_radio_klara_refresh_hours` -- Refresh cadence (1-720h, default 168 = weekly). Read at runtime by the cron tick.
- `input_datetime.ai_radio_klara_last_refresh` -- Stamped on each successful refresh.
- `input_boolean.ai_radio_klara_data_stale` -- Set when cache > 2× refresh interval old.
- `sensor.ai_radio_klara_status` -- Module status (idle/loaded/refreshing/refresh_failed/no_cache/disabled), seeded by `state_bridge.py` at boot.
- `sensor.ai_radio_klara_now_playing` -- Current show title, seeded by `state_bridge.py` at boot.
- `entity_config.yaml` `radio_stations:` -- Per-station config (match patterns, schedule_source URL + regex, timezone, enabled flag). Loaded via `shared_utils.load_entity_config()`.
- `/config/data/radio_klara_schedule.json` -- Cache file (source of truth for the in-memory cache).

## Package Pairing

Pairs with `packages/ai_radio_klara.yaml` (thin doc package). All triggers and scheduling are inside this module -- no separate blueprint.

## Called By

- **Hot context (`packages/ai_context_hot.yaml`)** -- reads `sensor.ai_radio_klara_now_playing` to inject "On Radio Klara: <show> (<desc>) [lang] -- ends HH:MM" into the agent context block, gated on the kill switch and a non-idle sensor state.
- **Music transfer announcement (`blueprints/script/madalone/announce_music_follow_me_llm.yaml`)** -- exposes a `radio_now_playing_sensors` entity-selector input (`multiple: true`, `domain: sensor`). Users pick one or more sensors from a dropdown; the blueprint iterates, reads each sensor's `station_name` attribute, matches it against `media_title` / `media_content_id`, and populates a `radio_show_context` template variable from the matching sensor. The variable is appended to the existing radio detection block in the LLM prompt and exposed as a `{radio_show}` placeholder for user prompt templates.
- **`pyscript.radio_klara_now_playing` service** -- callable from any blueprint or automation that wants the current show as a dict.

## Notes

- **Bootstrap workflow:** The first cache file was extracted by feeding the PDF to `mcp__gemini__gemini-analyze-document` (high media resolution) -- 93 shows × 7 days in one call. The auto-refresh path uses the same approach via `pyscript.llm_task_call`, but with `pypdf` extracting text first because pyscript can't reach MCP tools directly.
- **pypdf dependency:** Declared in `configuration.yaml` `pyscript: requirements:` for future installs. On existing setups, install manually: `docker exec homeassistant pip install pypdf==4.3.1`. The module degrades gracefully if pypdf is missing -- `_pdf_to_text` returns `None`, refresh fails with `pdf_text_extract_failed`, cache is preserved.
- **PDF URL stability:** The PDF URL has a date in it (e.g., `2025/08/triptic.pdf`), so the station may publish new files at new paths when the schedule changes. The refresh pipeline scrapes the schedule page first to find the current link via regex -- handles seasonal URL changes automatically.
- **Runtime-configurable refresh interval:** Pyscript `@time_trigger("cron(...)")` decorators are static -- they can't read helper values at decoration time. The 15-min cron tick reads `input_number.ai_radio_klara_refresh_hours` inside the function body and only fires the actual refresh if `(now - last_refresh) >= configured_hours`. This is the only sane way to expose refresh cadence as a dashboard slider.
- **Sensor scope (decision):** The sensor always reflects the schedule (even when nobody is listening), so agents can answer "what's on Radio Klara now?" out of context. The hot-context line is gated separately on the kill switch and a non-idle sensor state.
- **No breaking changes:** The existing `is_radio` detection in `announce_music_follow_me_llm.yaml` is preserved -- the new `radio_show_context` is appended only when the station matches "klara" in `media_title`. The existing `automation.alexa_presence_radio_radio_klara` instance is untouched. Music Assistant continues to resolve and stream the URL exactly as before.
- **Failure handling pattern:** Mirrors `project_promote.py` -- consecutive failure counter, persistent notification on 3+ failures, stale flag when cache > 2× interval. The cache is always preserved on failure (never overwritten with bad data).
- **Multi-station extensibility:** Adding more stations (Catalunya Ràdio, etc.) requires only: (1) a new entry under `entity_config.yaml radio_stations:`, (2) a bootstrap JSON cache file at `/config/data/radio_<slug>_schedule.json`, (3) optionally a new sensor name if the station should have its own context line. Zero code changes for stations sharing the `pdf_via_page` parser type.
- **MA content_type gotcha (AP-81):** Music Assistant reports `media_content_type: 'music'` for radio streams (not `'radio'`). The station-detection matching logic must NOT rely on `content_type` alone -- use `media_content_id` (MA sets `library://radio/...` for radio streams) plus a keyword fallback on the title/artist. The announce_music_follow_me_llm blueprint handles this correctly; downstream consumers should too.

## Changelog

- **v1 (2026-04-09):** Initial implementation. MVP cache loader + sensor + hot-context injection + announcement variable. Phase 2 auto-refresh pipeline with pypdf + `llm_task_call`. Bootstrap from Gemini MCP -- 93 shows extracted from the 2025-08 tríptic.
- **v1.1 (2026-04-09, same session):** Added `station_name` sensor attribute (read from `entity_config.yaml radio_stations.radio_klara.name`) so downstream consumers can display the clean station name instead of the sensor's friendly_name. The announce_music_follow_me_llm blueprint now reads this attribute for the `{radio_show}` context line.

## Author

**madalone**

## License

See repository for license details.
