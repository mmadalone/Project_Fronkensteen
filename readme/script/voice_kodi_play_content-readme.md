# Voice -- Kodi play content

![Voice -- Kodi play content](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/voice_kodi_play_content-header.jpeg)

Universal Kodi content router. Accepts a content type and content identifier, determines the correct playback method, and fires it. Handles direct file playback (movies, episodes), plugin/favourite URIs via JSON-RPC `Player.Open`, and TV show continuation with automatic next-unwatched-episode resolution. Designed as a tool script for LLM conversation agents but works from any automation, script call, or dashboard button.

## How It Works

```
Start (content_id, content_type)
  |
  v
+---------------------------+
| Route on content_type     |
+---------------------------+
  |
  +---------+---------+---------+------------------+
  |         |         |         |                  |
  v         v         v         v                  v
movie    episode   favourite  tvshow_continue   unknown
  |         |         |         |                  |
  v         v         v         v                  v
+-------+ +-------+ +--------+ |              +--------+
| play  | | play  | | Player | |              | Log    |
| _media| | _media| | .Open  | |              | warning|
+-------+ +-------+ +--------+ |              +--------+
                                |
                     +----------+-----------+
                     |                      |
                     v                      v
              +-------------+        +-------------+
              | GetTVShows  |        | tvshowid    |
              | by title    |        | not found   |
              +-------------+        +-> error msg |
                     |
                     v
              +-------------+
              | GetEpisodes |
              | unwatched   |
              | sort asc    |
              +-------------+
                     |
              +------+------+
              |             |
              v             v
        +----------+  +-----------+
        | Play via |  | No episode|
        | Player   |  | found     |
        | .Open    |  +-> error   |
        +----------+  +-----------+
```

## Features

- Four content type routes: movie, episode, favourite, tvshow_continue
- Direct file playback via `media_player.play_media` for movies and episodes
- Plugin/special URI playback via `kodi.call_method Player.Open` for favourites
- TV show continuation: resolves show title to `tvshowid`, finds first unwatched episode, plays it
- Configurable JSON-RPC timeout for large Kodi libraries
- Optional notification service for error reporting (falls back to logbook logging)
- Media content type override for non-video content (music, CHANNEL, DIRECTORY)
- Explicit `wait.completed` checks on JSON-RPC responses
- Default branch logs unknown content types for trace visibility

## Prerequisites

- Home Assistant 2024.10.0+
- Kodi integration with a `media_player` entity
- `kodi.call_method` service (for favourites and TV show continuation)

## Installation

1. Copy `voice_kodi_play_content.yaml` to `config/blueprints/script/madalone/`
2. Create script: **Settings -> Automations & Scenes -> Scripts -> Add -> Use Blueprint**

## Configuration

<details><summary>① Target</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `kodi_entity` | _(required)_ | Kodi media_player entity for playback and JSON-RPC lookups |

</details>

<details><summary>② Advanced</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `jsonrpc_timeout` | `10` | Seconds to wait for Kodi JSON-RPC responses |
| `error_notify_entity` | `""` | Optional notify entity for errors (e.g. `notify.mobile_app_phone`). Empty = logbook only |

</details>

### Script Fields (passed at call time)

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `content_id` | Yes | -- | Content path, file URI, plugin URI, or TV show title |
| `content_type` | Yes | -- | Routing type: `movie`, `episode`, `favourite`, `tvshow_continue` |
| `media_content_type` | No | `video` | Kodi media_content_type override for non-video content |

## Technical Notes

- **Mode:** `parallel` / `max_exceeded: silent`
- TV show continuation performs two sequential JSON-RPC calls (GetTVShows then GetEpisodes), each with a configurable timeout
- The `wait_for_trigger` blocks listen for `kodi_call_method_result` events filtered by entity ID and `result_ok: true`
- Episodes are sorted ascending by episode number, limited to 1 result (the next unwatched)
- Error handling uses a `choose` block to route errors to either notification service or logbook based on configuration

## Changelog

- **v2** -- Audit remediation: removed `continue_on_error` from JSON-RPC waits, replaced implicit `wait.trigger` guards with explicit `wait.completed` checks, added `default:` branch for unknown content_type
- **v1** -- Initial blueprint, extracted from voice_play_bedtime_kodi script

## Author

**madalone**

## License

See repository for license details.
