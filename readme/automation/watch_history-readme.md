# Kodi Watch History Tracker

Tracks what is watched on Kodi and logs it to L2 memory. Supports PVR live TV, YouTube, Netflix, Prime Video, Movistar+, and local library content. The blueprint owns all triggers and config knobs; pyscript (`watch_history_start/stop/pause`) handles JSON-RPC source detection, EPG fetching, duration measurement, and memory writes.

## How It Works

```
+-----------------------------------------------------------+
|                       TRIGGERS                            |
|  +-----------------------------------------------------+ |
|  | 1. Kodi media_player state -> playing (start)       | |
|  | 2. Kodi media_player state -> idle/off (stop)       | |
|  | 3. Kodi media_player state -> paused (pause)        | |
|  | 4. sensor.madteevee_now_playing change (PVR switch)  | |
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

- **Multi-source detection** -- classifies content via Kodi JSON-RPC `Player.GetItem` file property: PVR, YouTube, Netflix, Prime Video, Movistar+, local library.
- **EPG enrichment** -- for PVR content, fetches live broadcast metadata (season, episode, episode name) via `PVR.GetBroadcasts`.
- **Duration thresholds** -- configurable minimum watch times before logging (PVR: 180s default, other content: 120s default).
- **Channel surfing detection** -- below-threshold PVR entries counted as "flips", not logged individually.
- **L2 memory logging** -- watch sessions stored with structured tags (`media,watch_history,{category},{source}`) for agent search.
- **Hot context integration** -- "Now watching" and "Recently watched" lines injected into `ai_context_hot.yaml`.
- **Template sensor enrichment** -- `template.yaml` media sensor enhanced with season/episode/source/episode_name from watch history.
- **PVR channel switch handling** -- `content_change` trigger on `sensor.madteevee_now_playing` catches channel switches that don't transition through idle.
- **Privacy gate** -- tier-based suppression.

## Prerequisites

- **Home Assistant 2024.10.0+**
- **Kodi integration** configured as HA config entry (JSON-RPC config read automatically)
- **Pyscript** with `watch_history_start`, `watch_history_stop`, `watch_history_pause` services
- **Kill switch** -- `input_boolean.ai_watch_history_enabled`
- **Duration helpers** -- `input_number.ai_watch_min_duration_pvr`, `input_number.ai_watch_min_duration_content`

## Installation

1. Copy `watch_history.yaml` to `config/blueprints/automation/madalone/`
2. Create automation: **Settings -> Automations -> Create -> Use Blueprint**

## Configuration

<details>
<summary>Section 1 -- Tracking</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `tracking_enabled_entity` | `input_boolean.ai_watch_history_enabled` | Kill switch for watch history tracking |
| `min_duration_pvr` | `input_number.ai_watch_min_duration_pvr` | Minimum seconds for PVR content to be logged (default 180) |
| `min_duration_content` | `input_number.ai_watch_min_duration_content` | Minimum seconds for non-PVR content to be logged (default 120) |
| `retention_days` | `input_number.ai_watch_history_retention_days` | L2 memory retention in days |

</details>

<details>
<summary>Section 2 -- Privacy</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `privacy_tier` | `off` | Privacy gate tier (off/t1/t2/t3) |
| `privacy_gate_enabled` | `input_boolean.ai_privacy_gate_enabled` | Privacy gate master toggle |
| `privacy_gate_mode` | `input_select.ai_privacy_gate_mode` | Privacy gate behavior selector |
| `privacy_gate_person` | `person.miquel` | Person entity for tier suppression lookups |

</details>

## Technical Notes

- **Mode:** `restart` -- rapid channel switches cancel previous tracking and start fresh.
- **Content change trigger:** Watches `sensor.madteevee_now_playing` state changes to detect PVR channel switches that don't transition the media_player through idle/off states.
- **JSON-RPC config:** Read from `hass.config_entries.async_entries("kodi")` at pyscript startup. No hardcoded URLs or credentials.
- **Source detection:** `Player.GetItem` file property inspected for `plugin://` patterns. Known sources mapped by keyword matching on inputstream URLs.
- **EPG fetch:** `PVR.GetBroadcasts` with linear scan for active broadcast. Provides season/episode metadata that Kodi's player info alone doesn't expose.

## Changelog

- **v1:** Initial implementation.

## Author

**madalone**

## License

See repository for license details.
