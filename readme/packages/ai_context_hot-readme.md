![AI Hot Context](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/ai_context_hot-header.jpeg)

# AI Hot Context — Layer 1 Voice Context

The central nervous system of the voice agent architecture. Assembles a live text block (`sensor.ai_hot_context`) that is injected into every agent's system prompt via `{{ state_attr('sensor.ai_hot_context', 'context') }}`. Covers time, identity, presence, media, environment, weather, schedule, projects, focus, privacy, and memory.

## What's Inside

- **Template sensors:** 6 (5 component sensors + 1 main concatenator)
- **Input helpers:** Multiple (moved to consolidated helper files) -- booleans, texts, selects, datetimes

## Entity Reference

| Entity ID | Type | Purpose |
|---|---|---|
| `sensor.ai_context_time_identity` | template sensor | Component 1: current time, day type, user identity, household |
| `sensor.ai_context_presence` | template sensor | Component 2: FP2 zone presence, per-person identity (I-48), occupancy mode, away predictions (I-40) |
| `sensor.ai_context_media` | template sensor | Component 3: active media players, Kodi now-playing, music taste (I-34), Radarr/Sonarr library |
| `sensor.ai_context_environment` | template sensor | Component 4: house mode, expertise routing (I-45), weather, alarms, schedule, projects, focus, privacy, guests, interview mode (I-36) |
| `sensor.ai_context_memory` | template sensor | Component 5: L2 memory context, last interaction self-awareness |
| `sensor.ai_hot_context` | template sensor | Main concatenator -- joins all 5 component `lines` attributes into one context block |

## Dependencies

This package reads from a wide range of entities across the system:

- **Presence:** Aqara FP2 binary sensors (8 zones), `sensor.ai_location_miquel`, `sensor.ai_location_jessica`
- **Identity:** `sensor.occupancy_mode`, `sensor.identity_confidence_*`, identity helpers
- **Media:** Music Assistant players, Sonos players, voice PE ESP players, MadTeeVee (Kodi)
- **Weather:** `weather.forecast_home` (Met.no)
- **Calendar:** `input_text.ai_calendar_today_summary`, `input_text.ai_calendar_tomorrow_summary`
- **Email:** `input_number.ai_email_priority_count`
- **Focus:** `sensor.workshop_hours_today`, `input_boolean.ai_focus_mode`, `input_datetime.ai_last_meal_time`
- **Projects:** `sensor.ai_project_hot_context_line` (`full_text` attribute for untruncated content)
- **Memory:** `sensor.ai_memory_context` (configurable via `ai_memory_context_enabled`, `ai_memory_context_summary_limit`, `ai_memory_context_mood_limit`, `ai_memory_context_max_chars`; system-activity summaries auto-filtered)
- **Media tracking:** `sensor.ai_media_upcoming` (attrs: `sonarr`, `radarr`, `recent_downloads`)
- **Music taste:** `sensor.ai_music_taste_status`
- **Away patterns:** `sensor.ai_away_prediction` (pyscript `state.set()` sensor with `predictions` attribute)
- **Schedule preferences:** `input_datetime.ai_context_wake_time_weekday_{user}`, `_weekend_{user}`, `_alt_weekday_{user}`, `input_datetime.ai_context_bed_time_{user}`, `input_text.ai_context_wake_time_alt_days_{user}`
- **Privacy:** Privacy gate helpers
- **Watch history:** `sensor.ai_watch_history_status` (pyscript `state.set()` sensor with watch session data — "Now watching" / "Recently watched" lines)
- **Packages:** `ai_identity.yaml`, `ai_away_patterns.yaml`, `ai_focus_guard.yaml`, `ai_media_tracking.yaml`, `ai_music_taste.yaml`, `ai_calendar_promotion.yaml`, `ai_email_promotion.yaml`, `ai_watch_history.yaml`

## Cross-References

- **All voice agents:** Every Standard and Extended OpenAI agent injects `sensor.ai_hot_context` into its system prompt
- **Pyscript:** `pyscript/proactive_briefing.py` reads hot context for briefing content
- **Blueprints:** Multiple blueprints reference hot context entities for conditional logic

## Notes

- The sensor uses a 5-component architecture: each component produces a `lines` attribute, and the main concatenator joins them with newlines, filtering out empty/unavailable parts.
- Per-user references are currently hardcoded to `_miquel` helpers. Task 22 will add dynamic user switching based on identity confidence.
- Interview mode (I-36) injects a large instruction block that makes the agent lead a structured preference-gathering conversation.
- The Kodi (MadTeeVee) media block strips BBCode tags and file extensions from titles.
- User preference consumption (2026-03-26): 14 blueprints/modules now read from `ai_context_user_*_{user}` helpers for LLM prompt shaping. Sleep budget calculation uses weekday/weekend/alt-day wake time routing. Alarm/routine blueprints support `use_preference_wake_time` / `use_preference_bed_time` toggles for schedule-aware triggers.
- Deployed: 2026-02-28. Updated: 2026-03-26 (preference consumption wiring).
