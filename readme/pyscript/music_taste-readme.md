# Music Taste — Play Logging and Taste Profile Aggregation

I-34 of the Voice Context Architecture. Logs what gets played on Music Assistant players via state triggers, pulls Spotify taste analytics via SpotifyPlus daily, merges both data sources into a unified taste profile on `sensor.ai_music_taste_status`, and stores everything in L2 memory. Enables agents to make music recommendations and reference listening habits.

## Services

| Service | Parameters | Returns | Description |
|---------|-----------|---------|-------------|
| `pyscript.music_taste_rebuild` | `llm_instance`, `summary_max_chars`, `llm_prompt` | `{status, op, top_artists, total_plays, genre_summary}` | Force a full profile aggregation now. Optionally generates an LLM genre/style summary. `supports_response="optional"` |
| `pyscript.music_taste_stats` | _(none)_ | `{status, op, summary, top_artists, top_tracks, total_plays, has_spotify, last_updated}` | Return current taste profile for debugging and dashboard display. `supports_response="optional"` |

## Triggers

| Trigger | Function | Condition |
|---------|----------|-----------|
| `@state_trigger(*MA_PLAYERS playing/media_title)` | `_on_media_playing` | Logs tracks as they start playing on configured Music Assistant players. Filters out radio streams and TTS. |
| `@time_trigger("period(0, 30)")` | `_poll_playing_media` | 30-second polling fallback: catches tracks on players not in the MA_PLAYERS list (only `media_content_type == "music"`). |
| `@time_trigger("cron(0 4 * * *)")` | `_spotify_daily_pull` | Daily at 04:00: pulls top artists (medium_term), top tracks, and recently played from SpotifyPlus. |
| `@time_trigger("cron(30 4 * * *)")` | `_daily_aggregate` | Daily at 04:30: merges MA play logs + Spotify data into a unified taste profile. Optionally generates LLM genre summary. |
| `@time_trigger("startup")` | `_startup` | Restores taste profile from L2 on startup, sets status sensor |

## Key Functions

- `_log_play()` — Shared play-logging: dedup (same artist:title within 180s cooldown), L2 upsert with play count and room tracking
- `_aggregate_profile()` — Merges MA play logs (weighted 2x) with Spotify position-based scores into a unified ranking. Top 15 artists, top 15 tracks.
- `_generate_genre_summary()` — LLM call to produce a concise genre/style summary from the raw profile text (e.g., "Indie rock with electronic and Latin influences")
- `_normalize()` — Lowercase + strip accents for dedup keys
- `_title_hash()` — MD5-based short hash for L2 key uniqueness

## State Dependencies

- `input_boolean.ai_music_taste_enabled` — Kill switch
- `input_text.ai_task_instance` — LLM instance for genre summary generation
- `media_player.spotifyplus_miquel_angel_madalone` — SpotifyPlus entity for Spotify API access
- `media_player.workshop_ma` / `media_player.bathroom_ma` — Configured Music Assistant players

## Package Pairing

Pairs with `packages/ai_music_taste.yaml` (if it exists) or the kill switch is defined in `helpers_input_boolean.yaml`. The `sensor.ai_music_taste_status` result entity is created by pyscript at runtime with attributes including `summary`, `top_artists`, `top_tracks`, `total_plays`, `has_spotify`, `genre_summary`, and `last_updated`.

## Called By

- **Self-triggered** — state triggers on MA players, polling fallback, daily Spotify pull and aggregation
- **Dashboard** — `music_taste_stats` for displaying the taste profile
- **Proactive briefing** — reads the taste profile sensor for personalized music mentions
- **Voice agents** — access `sensor.ai_music_taste_status` attributes for music recommendation context

## Notes

- Two data sources: Music Assistant (real-time state triggers + polling fallback) and Spotify (daily SpotifyPlus API pull). Both are merged into a single weighted profile.
- Dedup cooldown: same artist:title pair is ignored within 180 seconds to prevent duplicate logging from track restarts or seek operations.
- Weighted scoring for artist ranking: MA plays are weighted 2x (actual listening behavior) while Spotify position contributes a descending bonus (top artist = 15 pts, second = 14, etc.). This ensures local listening habits outweigh historical Spotify data.
- L2 key pattern: `music_play:{normalized_artist}:{title_hash}` with 365-day expiry. Each entry is a JSON object with play count, rooms, source, and last_played timestamp.
- Spotify data uses `medium_term` time range (~6 months) for top artists and tracks.
- The polling fallback (`period(0, 30)`) only catches `media_content_type == "music"` to avoid logging TTS, announcements, or video playback.
- Genre summary generation is optional and budget-gated: it only runs if an LLM instance is configured and the profile has data.
- Room tracking: each play log includes the room derived from the media player entity name, enabling per-room listening pattern analysis.
