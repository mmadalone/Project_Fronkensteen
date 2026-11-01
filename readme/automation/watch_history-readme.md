# Kodi Watch History Tracker

Tracks what is watched on Kodi and logs it to L2 memory. Supports PVR live TV, YouTube, Netflix, Prime Video, Movistar+, Disney+, HBO Max, Filmin, and local library content. The blueprint owns all triggers and config knobs; pyscript (`watch_history_start/stop/pause`) handles JSON-RPC source detection, EPG fetching, duration measurement, and memory writes.

## How It Works

```
+-----------------------------------------------------------+
|                       TRIGGERS                            |
|  +-----------------------------------------------------+ |
|  | 1. Kodi media_player state -> playing (start)       | |
|  | 2. Kodi media_player state -> idle/off (stop)       | |
|  | 3. Kodi media_player state -> paused (pause)        | |
|  | 4. Now Playing sensor change (PVR switch, optional) | |
|  +------------------------+----------------------------+ |
+---------------------------+-------------------------------+
                            |
                            v
+-----------------------------------------------------------+
|                   CONDITION GATES                         |
|  * Kill switch (ai_watch_history_enabled) is ON?         |
|  * Privacy gate passes?                                   |
+---------------------------+-------------------------------+
                            | all pass
                            v
+-----------------------------------------------------------+
|                   ACTION SEQUENCE                         |
|  1. Determine trigger type (start/stop/pause/switch)     |
|  2. Call appropriate pyscript service:                    |
|     - watch_history_start (title, category, source)      |
|     - watch_history_stop (logs to L2 if above threshold) |
|     - watch_history_pause                                |
|  3. For PVR channel switch: stop previous + start new    |
+-----------------------------------------------------------+
```

## Features

- **Multi-source detection** -- classifies content via Kodi JSON-RPC `Player.GetItem` file property: PVR, YouTube, Netflix, Prime Video, Movistar+, Disney+, HBO Max, Filmin, local library.
- **Direct media_player reads** -- pyscript reads metadata directly from the media_player entity (defense-in-depth), avoiding circular dependencies with the template sensor.
- **Streaming series detection** -- addons that report `media_content_type: video` for everything are classified as `series` when `media_series_title` is present on the media_player entity.
- **EPG enrichment** -- for PVR content, fetches live broadcast metadata (season, episode, episode name) via `PVR.GetBroadcasts`. EPG overrides all other sources for PVR.
- **Episode name fallback** -- for library/streaming series, `current_episode_name` is populated from `media_title` when EPG data isn't available.
- **Duration thresholds** -- configurable minimum watch times before logging (PVR: 180s default, other content: 120s default).
- **Channel surfing detection** -- below-threshold PVR entries counted as "flips", not logged individually.
- **L2 memory logging** -- watch sessions stored with structured tags (`media,watch_history,{category},{source}`) for agent search.
- **Hot context integration** -- "Now watching" and "Recently watched" lines injected into `ai_context_hot.yaml`.
- **Template sensor enrichment (optional)** -- a now-playing template sensor of your own (the Now Playing input) can expose `media_source` / `episode_name` by reading `current_source` / `current_episode_name` from `sensor.ai_watch_history_status`. It should read `series_title`/`season`/`episode` from the `media_player` only (no pyscript fallback — avoids circular dependency AP-78). A PVR show name can go in its `pvr_programme` attribute (e.g. from a PVR channel sensor).
- **PVR channel switch handling** -- `content_change` trigger on the optional Now Playing sensor catches channel switches that don't transition through idle. With no sensor set, content changes while playing are not tracked.
- **Privacy gate** -- tier-based suppression.

## Prerequisites

- **Home Assistant 2024.10.0+**
- **Kodi integration** configured as HA config entry (JSON-RPC config read automatically)
- **Pyscript** with `watch_history_start`, `watch_history_stop`, `watch_history_pause` services
- **Kill switch** -- `input_boolean.ai_watch_history_enabled`
- **Duration helpers** -- `input_number.ai_watch_min_duration_pvr`, `input_number.ai_watch_min_duration_content`
- **Now Playing template sensor** (optional) -- only needed to catch content changes while playing (PVR channel switches)

## Installation

1. Copy `watch_history.yaml` to `config/blueprints/automation/madalone/`
2. Create automation: **Settings -> Automations -> Create -> Use Blueprint**

## Configuration

<details>
<summary>Section 1 -- Tracking</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `tracking_enabled_entity` | `input_boolean.ai_watch_history_enabled` | Kill switch for watch history tracking |
| `min_duration_pvr_entity` | `input_number.ai_watch_min_duration_pvr` | Minimum seconds for PVR content to be logged (default 180) |
| `min_duration_content_entity` | `input_number.ai_watch_min_duration_content` | Minimum seconds for non-PVR content to be logged (default 120) |
| `retention_days_entity` | `input_number.ai_watch_history_retention_days` | L2 memory retention in days |
| `now_playing_sensor` | _(empty)_ | Optional now-playing template sensor with the attributes `media_category`, `media_title`, `series_title`, `season`, `episode`, `pvr_channel`, `pvr_channel_number` and `pvr_programme`. Its state changes catch PVR channel switches. Leave empty if you have none: content changes while playing are then not tracked |

</details>

<details>
<summary>Section 2 -- Privacy</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `privacy_tier` | `off` | Privacy gate tier (off/t1/t2/t3) |
| `privacy_gate_enabled` | `input_boolean.ai_privacy_gate_enabled` | Privacy gate master toggle |
| `privacy_gate_mode` | `input_select.ai_privacy_gate_mode` | Privacy gate behavior selector |
| `privacy_gate_person` | `""` | Person entity for tier suppression lookups |

</details>

## Technical Notes

- **Mode:** `restart` -- rapid channel switches cancel previous tracking and start fresh.
- **Content change trigger:** Watches the Now Playing sensor's state changes (when one is set) to detect PVR channel switches and playlist advances that don't transition the media_player through idle/off states. Without one, start, pause, stop and restart recovery still work; metadata then comes from the Kodi player and JSON-RPC.
- **Metadata priority:** Pyscript reads directly from `media_player` entity via `state.getattr()` (ground truth). Blueprint-passed params from the Now Playing sensor serve as fallback (empty when no sensor is set). EPG data from JSON-RPC overrides all for PVR content.
- **JSON-RPC config:** Read from `hass.config_entries.async_entries("kodi")` at pyscript startup. No hardcoded URLs or credentials.
- **Source detection:** `Player.GetItem` file property inspected for `plugin://` patterns. Known sources: YouTube, Netflix, Prime Video, Movistar+, Disney+, HBO Max, Filmin, PVR. Keyword fallback for non-plugin URLs.
- **EPG fetch:** `PVR.GetBroadcasts` with linear scan in batches of 30 for active broadcast. Provides season/episode metadata that Kodi's player info alone doesn't expose.

## Changelog

- **v1:** Initial implementation.
- **watch_history.py v1.1:** Descriptive sensor state — logbook shows "watching Seinfeld S03E10" instead of generic "watching".
- **Now-playing template sensor v1.2:** Removed circular dependency — `series_title`/`season`/`episode` no longer fall back to pyscript sensor (AP-78). PVR show name via `pvr_programme` attribute.
- **Blueprint v1.1:** Now Playing sensor is optional (default empty, was a household ID).

## Author

**madalone**

## License

See repository for license details.
