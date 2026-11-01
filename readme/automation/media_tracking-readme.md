![Media Tracking -- Radarr/Sonarr](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/media_tracking-header.jpeg)

# Media Tracking -- Radarr/Sonarr

Promotes Radarr/Sonarr data to L1 hot context, L2 memory, and optionally sends download notifications. The blueprint owns all triggers and config knobs; pyscript (`media_promote_now`) is a stateless service that fetches APIs and writes helpers/memory. Supports periodic, daily, queue-change, manual, and startup triggers.

## How It Works

```
┌─────────────────────────────────────────────────────────┐
│                      TRIGGERS                           │
│  ┌────────────────────────────────────────────────────┐ │
│  │ 1. Time pattern: every N hours (periodic)         │ │
│  │ 2. Fixed time: daily refresh (midnight default)   │ │
│  │ 3. Sonarr queue sensor state change (optional)    │ │
│  │ 4. Radarr queue sensor state change (optional)    │ │
│  │ 5. Kill switch turns ON (manual)                  │ │
│  │ 6. HA startup                                     │ │
│  └──────────────────────┬─────────────────────────────┘ │
└─────────────────────────┼───────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│                  CONDITION GATES                        │
│  • Kill switch (ai_media_tracking_enabled) is ON?      │
│  • HA start trigger → run_on_start must be true        │
│  • Daily trigger → enable_daily_refresh must be true   │
│  • Privacy gate passes?                                │
└────────────────────────┬────────────────────────────────┘
                         │ all pass
                         ▼
┌─────────────────────────────────────────────────────────┐
│                  ACTION SEQUENCE                        │
│  0. Gate: queue triggers need queue_trigger enabled    │
│  1. Map window selectors to days/hours                 │
│  2. Call pyscript.media_promote_now                    │
│     (upcoming_days, download_hours, write_l1)          │
│  3. Handle stale data flag on error                    │
│  4. Send download notification (if new downloads       │
│     detected and notifications enabled)                │
└─────────────────────────────────────────────────────────┘
```

## Features

- **Multi-trigger architecture** -- periodic (N hours), daily (fixed time), queue-change (optional Sonarr/Radarr Queue sensors), manual (kill switch), and HA startup.
- **Upcoming media window** -- configurable lookahead: today only, today + tomorrow, or weekly (7 days).
- **Download history window** -- look back 24 hours (daily) or 7 days (weekly) for recently downloaded content.
- **L1 hot context** -- writes upcoming media info to input_text helpers for agent hot context consumption.
- **L2 memory** -- stores media data in L2 memory for semantic search and agent context.
- **Download notifications** -- optional persistent notification when new downloads are detected since last check.
- **Queue-change reactivity** -- re-promotes immediately when Sonarr or Radarr queue counts change. Optional: pick the Queue sensors in the Infrastructure section, or leave them empty to refresh on the schedule only.
- **Daily refresh** -- ensures "today" data stays accurate after midnight (configurable time, default 00:01).
- **Stale data flagging** -- sets `input_boolean.ai_media_data_stale` on promotion errors.
- **Privacy gate** -- tier-based suppression.

## Prerequisites

- **Home Assistant 2024.10.0+**
- **Sonarr and/or Radarr integrations** with API access
- **Pyscript** with `media_promote_now` service
- **Queue sensors (optional)** -- the Sonarr and Radarr Queue sensors, for the queue-change triggers. Both integrations ship them disabled: enable them on the Sonarr/Radarr device page first.
- **Kill switch** -- `input_boolean.ai_media_tracking_enabled`

## Installation

1. Copy `media_tracking.yaml` to `config/blueprints/automation/madalone/`
2. Create automation: **Settings -> Automations -> Create -> Use Blueprint**

## Configuration

<details>
<summary>Section 1 -- Schedule</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `refresh_interval` | `"6"` | Hours between automatic refreshes (1/2/6/12/24) |
| `enable_daily_refresh` | `true` | Run a fixed-time daily refresh |
| `daily_refresh_time` | `00:01:00` | Time for the daily refresh |
| `queue_trigger` | `true` | Re-promote on Sonarr/Radarr queue count change |

</details>

<details>
<summary>Section 2 -- Windows</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `upcoming_window` | `today` | Upcoming lookahead: `today` (1 day), `tomorrow` (2 days), `weekly` (7 days) |
| `download_window` | `daily` | Download lookback: `daily` (24 hours) or `weekly` (7 days) |

</details>

<details>
<summary>Section 3 -- Startup</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `run_on_start` | `true` | Refresh media data on HA startup |

</details>

<details>
<summary>Section 4 -- L1 Context</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `enable_l1` | `true` | Write upcoming media to hot context helpers |

</details>

<details>
<summary>Section 5 -- Notifications</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `notify_downloads` | `false` | Send persistent notification on new downloads |
| `notification_target` | `{}` | Notify entity for download notifications |
| `notification_title` | `"Media Downloaded"` | Title for download notifications |

</details>

<details>
<summary>Section 6 -- Infrastructure</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `sonarr_queue_entity` | `[]` | Optional. Sonarr's Queue sensor (the picker lists Sonarr sensors only). Its changes refresh the data while downloads run (see `queue_trigger`). Sonarr ships it disabled: enable it on the Sonarr device page first. Empty = refresh on the schedule only |
| `radarr_queue_entity` | `[]` | Optional. Radarr's Queue sensor, like the Sonarr one. Radarr also ships it disabled. Empty = refresh on the schedule only |
| `tracking_enabled_entity` | `input_boolean.ai_media_tracking_enabled` | Kill switch for media tracking |
| `data_stale_entity` | `input_boolean.ai_media_data_stale` | Boolean flagged when media data promotion fails |

</details>

<details>
<summary>Section 7 -- Privacy</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `privacy_tier` | `off` | Privacy gate tier (off/t1/t2/t3) |
| `privacy_gate_enabled` | `input_boolean.ai_privacy_gate_enabled` | Privacy gate master toggle |
| `privacy_gate_mode` | `input_select.ai_privacy_gate_mode` | Privacy gate behavior selector |
| `privacy_gate_person` | _(empty)_ | Person entity for tier suppression lookups |

</details>

## Technical Notes

- **Mode:** `single` with `max_exceeded: silent` -- one refresh at a time.
- **Queue trigger gate:** Queue-change triggers (Sonarr/Radarr) are gated by the `queue_trigger` input in the action sequence -- if disabled, the automation stops early with `stop:`.
- **Queue inputs:** an empty queue input means its queue-change trigger never fires. The inputs only drive the triggers: the queue counts in the promoted data come from `media_promote.py`, which finds the Sonarr/Radarr Queue sensors in the entity registry itself (no queue count while they are disabled).
- **Window mapping:** `upcoming_window` maps to days (today=1, tomorrow=2, weekly=7). `download_window` maps to hours (daily=24, weekly=168).
- **Pyscript call:** `pyscript.media_promote_now` receives `upcoming_days`, `download_hours`, `write_l1`, and `force: false`. Returns `status`, `new_downloads_since_last`, and `recent_summary`.
- **Error handling:** On promotion error, sets `input_boolean.ai_media_data_stale` to flag stale data for dashboard/agent awareness.

## Changelog

- **v1.1:** Queue sensors default to empty: re-pick them to keep queue refreshes. **Breaking** if you enabled the Sonarr/Radarr Queue sensors and left these inputs at their defaults: select them in the Infrastructure section, or refreshes run on the schedule only.
- **v1:** Initial implementation.

## Author

**madalone**

## License

See repository for license details.
