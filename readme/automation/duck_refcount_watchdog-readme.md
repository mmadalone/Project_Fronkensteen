# Duck Refcount Watchdog

Safety net for the duck refcount system used by Notification Follow-Me, Email Follow-Me, and other TTS blueprints that duck media player volumes during announcements. When parallel TTS runs die mid-flight (automation reload, HA restart, supersede exit), the duck refcount stays above zero, the ducking flag stays ON, and media players remain permanently ducked at low volume. This watchdog detects the stranded state and force-restores everything.

## How It Works

```
┌─────────────────────────────────────────────────────────┐
│                      TRIGGERS                           │
│  ┌────────────────────────────────────────────────────┐ │
│  │ 1. Time pattern: every 3 minutes (poll)           │ │
│  │ 2. HA startup                                     │ │
│  │ 3. automation_reloaded event                      │ │
│  └──────────────────────┬─────────────────────────────┘ │
└─────────────────────────┼───────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│                  CONDITION GATE                         │
│  • Duck refcount helper > 0?                           │
└────────────────────────┬────────────────────────────────┘
                         │ yes
                         ▼
┌─────────────────────────────────────────────────────────┐
│                  ACTION SEQUENCE                        │
│  0. Entity settle delay (10s, startup/reload only)     │
│  1. Parse duck volume snapshot JSON                    │
│  1a. Restore each ducked player to pre-duck volume     │
│  2a. Clear duck volume snapshot helper                 │
│  2b. Clear satellite volume snapshot (if configured)   │
│  3. Reset duck refcount to 0                           │
│  4. Turn off ducking flag                              │
│  5. Send persistent notification (optional)            │
└─────────────────────────────────────────────────────────┘
```

## Features

- **3-minute poll** -- catches stranded duck state even when the original transition was missed.
- **Startup/reload instant reset** -- clears orphaned state immediately on HA restart or automation reload, no timeout wait.
- **Snapshot-based volume restore** -- reads the JSON snapshot helper and restores each ducked player to its exact pre-duck volume.
- **Full helper cleanup** -- resets refcount to 0, clears ducking flag, wipes snapshot helpers.
- **Optional persistent notification** -- shows trigger source (poll/startup/reload) and which players were restored.
- **Satellite snapshot cleanup** -- optionally clears a satellite volume snapshot helper to prevent stale data on next run.

## Prerequisites

- Home Assistant
- Duck refcount system helpers (shared with Notification Follow-Me, Email Follow-Me, etc.):
  - `input_number` for duck refcount
  - `input_boolean` for ducking flag
  - `input_text` for duck volume snapshot (JSON)

## Installation

1. Copy `duck_refcount_watchdog.yaml` to `config/blueprints/automation/madalone/`
2. Create automation: **Settings -> Automations -> Create -> Use Blueprint**

## Configuration

<details>
<summary>Section 1 -- Core -- Duck System Helpers</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `duck_refcount_helper` | *(required)* | Input number tracking active duck cycles across parallel runs |
| `ducking_flag` | *(required)* | Input boolean signaling an active duck cycle |
| `duck_snapshot_helper` | *(required)* | Input text storing the JSON snapshot of ducked player volumes |

</details>

<details>
<summary>Section 2 -- Optional</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `satellite_volume_snapshot` | `""` | Optional input text for satellite pre-TTS volume snapshot |
| `notify_on_reset` | `true` | Send persistent notification when the watchdog fires |

</details>

## Technical Notes

- **Mode:** `single` -- only one watchdog run at a time; `max_exceeded: silent`.
- **Poll vs. trigger:** v1.2.0 replaced the one-shot `numeric_state` trigger with `time_pattern /3` because `numeric_state above: 0 for: X` fires exactly once per transition above zero -- if the refcount was already stranded, the trigger would never re-fire.
- **Entity settle delay:** Startup/reload triggers wait 10 seconds before acting to let helpers become available.
- **continue_on_error:** All restore and cleanup actions use `continue_on_error: true` to prevent a single failed player from blocking the reset sequence.

## Changelog

- **v1.2.0:** Replace one-shot `numeric_state` trigger with `time_pattern /3` poll. Removed `timeout_minutes` input. Condition block gates on refcount > 0.
- **v1.1.0:** Startup/reload instant reset -- adds HA start and `automation_reloaded` triggers for immediate cleanup.
- **v1.0.0:** Initial release -- numeric_state trigger with configurable timeout, snapshot-based volume restore.

## Author

**madalone**

## License

See repository for license details.
