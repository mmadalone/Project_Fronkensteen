# Music Listen History Tracker

Tracks music listening sessions on Music Assistant / Spotify players and logs them to L2 memory. Supports tracks, radio, playlists, albums, podcasts, and audiobooks. The blueprint owns all triggers and config knobs; pyscript (`listen_history_start/stop/pause`) handles source classification, duration measurement, and memory writes.

## How It Works

```
+-----------------------------------------------------------+
|                       TRIGGERS                            |
|  +-----------------------------------------------------+ |
|  | 1. Media player state -> playing (start)            | |
|  | 2. Media player state -> idle/off/standby (stop)    | |
|  | 3. Media player state -> paused (pause)             | |
|  | 4. media_title attribute change (track change)       | |
|  | 5. HA restart (recovery)                             | |
|  +------------------------+----------------------------+ |
+---------------------------+-------------------------------+
                            |
                            v
+-----------------------------------------------------------+
|                   CONDITION GATES                         |
|  * Kill switch (ai_listen_history_enabled) is ON?        |
|  * Privacy gate passes?                                   |
+---------------------------+-------------------------------+
                            | all pass
                            v
+-----------------------------------------------------------+
|                   ACTION SEQUENCE                         |
|  1. Determine trigger type (start/stop/pause/change)     |
|  2. Read media_player attributes (artist, title, album,  |
|     content_id, content_type)                             |
|  3. Call appropriate pyscript service:                    |
|     - listen_history_start (classifies source, tracks)   |
|     - listen_history_stop (logs to L2 if above threshold)|
|     - listen_history_pause                               |
|  4. For track change: auto-close previous + start new    |
+-----------------------------------------------------------+
```

## Features

- **Multi-player support** -- tracks multiple media players independently with separate sessions. Uses `mode: queued` (max: 10) to prevent cross-player cancellation.
- **Source classification** -- detects Music Assistant (track/playlist/album/radio), Spotify (track/podcast/audiobook), and radio via `media_content_id` prefix parsing and `media_content_type` attribute.
- **TTS rejection** -- explicit TTS detection (`media_content_type == "tts"`, `/api/tts_proxy/`, `media-source://tts/`) rejects before session creation. Handles long TTS (conversations, banter, theatrical debates, therapy sessions).
- **Podcast & audiobook support** -- detected via `media_content_type` attribute or Spotify URI parsing (`spotify:episode:`, `spotify:show:`, `spotify:audiobook:`).
- **Duration thresholds** -- configurable minimum listen time before logging (default: 60s).
- **Track change detection** -- `media_title` attribute trigger catches playlist advances and radio song changes without needing a separate sensor.
- **L2 memory logging** -- listen sessions stored with structured tags (`media,listen_history,{source},{content_type}`) for agent search.
- **Daily summaries** -- automatic midnight rollover writes previous day's summary to L2 (2-day retention).
- **Hot context integration** -- "Now listening to" and "Recently listened to" lines injected into `ai_context_hot.yaml`.
- **HA restart recovery** -- iterates all tracked players after restart, recovers any still playing.
- **Multi-player sensor awareness** -- when one player stops but another is still active, sensor shows remaining active session.
- **Privacy gate** -- tier-based suppression.

## Prerequisites

- **Home Assistant 2024.10.0+**
- **Music Assistant** and/or **SpotifyPlus** integration configured
- **Pyscript** with `listen_history_start`, `listen_history_stop`, `listen_history_pause` services
- **Kill switch** -- `input_boolean.ai_listen_history_enabled`
- **Duration helper** -- `input_number.ai_listen_min_duration`

## Installation

1. Copy `listen_history.yaml` to `config/blueprints/automation/madalone/`
2. Create automation: **Settings -> Automations -> Create -> Use Blueprint**

## Configuration

<details>
<summary>Section 1 -- Target</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `target_players` | `media_player.workshop_ma`, `media_player.bathroom_ma` | Media player entities to track (multi-select) |

</details>

<details>
<summary>Section 2 -- Thresholds</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `min_duration_entity` | `input_number.ai_listen_min_duration` | Minimum listen duration in seconds before logging (default 60) |
| `attribute_delay` | `1.0` | Seconds to wait after state change before reading attributes |

</details>

<details>
<summary>Section 3 -- Memory</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `retention_days_entity` | `input_number.ai_listen_history_retention_days` | L2 memory retention in days |
| `summary_retention_days` | `2` | Daily summary retention in days |

</details>

<details>
<summary>Section 4 -- Privacy</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `privacy_tier` | `off` | Privacy gate tier (off/t1/t2/t3) |
| `privacy_gate_enabled` | `input_boolean.ai_privacy_gate_enabled` | Privacy gate master toggle |
| `privacy_gate_mode` | `input_select.ai_privacy_gate_mode` | Privacy gate behavior selector |
| `privacy_gate_person` | `""` | Person entity for tier suppression lookups |

</details>

## Technical Notes

- **Mode:** `queued` (max: 10) -- multi-player safe. Unlike `watch_history` (`restart` for single Kodi entity), this blueprint handles multiple players simultaneously.
- **Track change trigger:** Watches `media_title` attribute changes on all target players. Guard condition ensures player is still in `playing` state (avoids spurious attribute updates during stop).
- **`media_album_name`:** Music Assistant uses `media_album_name` (not `media_album`). The blueprint reads the correct attribute via `state_attr(entity, 'media_album_name')`.
- **No template sensor needed:** MA/Spotify expose clean metadata directly on the media_player entity. No intermediary sensor like watch_history's `sensor.madteevee_now_playing`.
- **HA restart recovery:** 10-second delay after HA start, then iterates all tracked players via `repeat.for_each` and recovers any still in `playing` state.

## Changelog

- **v1:** Initial implementation.

## Author

**madalone**

## License

See repository for license details.
