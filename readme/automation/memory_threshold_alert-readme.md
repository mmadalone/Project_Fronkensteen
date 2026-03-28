![Memory Threshold Alert (v1.0.0)](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/memory_threshold_alert-header.jpeg)

# Memory Threshold Alert (v1.0.0)

Scheduled daily health check for L2 memory. Calls `pyscript.memory_health_check` at the configured time, which compares record count and DB file size against configurable thresholds. If any threshold is breached, a persistent notification appears in the HA sidebar with detailed metrics.

Thresholds are controlled via helpers (Settings -> Helpers): `AI Memory - Record Limit` (default 5000 records) and `AI Memory - DB Max Size` (default 100 MB). Part of I-42: Memory Lifecycle Policy (Phase 1 -- monitoring).

## How It Works

```
┌───────────────────────┐     ┌───────────────────────────┐
│  Daily time trigger   │     │  ai_memory_threshold_     │
│  (default 04:00)      │     │  exceeded event           │
└──────────┬────────────┘     └──────────┬────────────────┘
           │                             │
           ▼                             ▼
┌──────────────────────┐     ┌────────────────────────────┐
│  pyscript.memory_    │     │  Create persistent         │
│  health_check        │     │  notification with         │
│  (continue_on_error) │     │  breach details            │
└──────────────────────┘     └────────────────────────────┘
```

## Features

- Daily scheduled health check after nightly batch jobs complete
- Reactive notification on threshold breach events
- Persistent notification with breach details: record count, DB size, expired entries
- Configurable notification title
- Actionable guidance in notification text (purge expired, adjust thresholds)

## Prerequisites

- Home Assistant 2024.10.0+
- Pyscript integration with `memory_health_check` service deployed
- Threshold helpers in `packages/ai_embedding.yaml`:
  - `input_number.ai_memory_record_limit` (default 5000)
  - `input_number.ai_memory_db_max_mb` (default 100 MB)

## Installation

1. Copy `memory_threshold_alert.yaml` to `config/blueprints/automation/madalone/`
2. Create automation: **Settings -> Automations -> Create -> Use Blueprint**

## Configuration

<details>
<summary><strong>① Schedule</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| `check_time` | `04:00:00` | Daily health check time. Recommended: after nightly batch jobs complete |

</details>

<details>
<summary><strong>② Notification</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| `notification_title` | `Memory threshold exceeded` | Title for the persistent notification |

</details>

## Technical Notes

- **Mode:** `single` / `max_exceeded: silent`
- The scheduled trigger calls the health check service; the event trigger only creates the notification
- Health check call uses `continue_on_error: true` for resilience
- Notification ID `ai_memory_threshold` ensures only one notification exists at a time (overwrites previous)

## Changelog

- **v1.0.0:** Initial release (I-42 Phase 1) -- scheduled monitoring + breach notification

## Author

**madalone**

## License

See repository for license details.
