![AI Memory - Auto Archive](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/memory_auto_archive-header.jpeg)

# AI Memory - Auto Archive

Automatically archives cold L2 memory entries when storage thresholds are breached. Triggered reactively by an `ai_memory_threshold_exceeded` event (fired by the memory health check service) or on a configurable daily schedule. Archive parameters -- target percentage, recency protection window, and protection tags -- are read from helpers at runtime, keeping the blueprint configuration minimal.

## How It Works

```
┌─────────────────────────┐     ┌──────────────────────┐
│  ai_memory_threshold_   │     │  Daily schedule       │
│  exceeded event         │     │  (default 03:45)      │
└───────────┬─────────────┘     └──────────┬───────────┘
            │                              │
            ▼                              ▼
┌───────────────────────────────────────────────────────┐
│  Conditions                                           │
│  • Blueprint enable toggle = ON                       │
│  • Helper kill switch (ai_memory_auto_archive) = ON   │
└───────────────────────────┬───────────────────────────┘
                            │
              ┌─────────────┴──────────────┐
              │ scheduled?                 │
              │ ├─ YES → health_check      │
              │ │   └─ threshold breached? │
              │ │       └─ NO → stop       │
              │ └─ NO (event) → continue   │
              └─────────────┬──────────────┘
                            │
                            ▼
              ┌─────────────────────────────┐
              │ pyscript.memory_archive     │
              │ (dry_run supported)         │
              └─────────────┬───────────────┘
                            │
                            ▼
              ┌─────────────────────────────┐
              │ Persistent notification     │
              │ (if enabled + entries moved) │
              └─────────────────────────────┘
```

## Features

- Reactive archiving on threshold breach events
- Scheduled daily archive check (runs after nightly housekeeping)
- Blueprint-level and helper-level dual kill switches
- Dry run mode for testing without moving data
- Persistent notification with archive statistics (entries archived, before/after counts, protected entries skipped)
- Reads archive configuration from helpers at runtime

## Prerequisites

- Pyscript integration with `memory_archive` and `memory_health_check` services deployed
- Helper: `input_boolean.ai_memory_auto_archive` (global toggle)
- Archive configuration helpers in `packages/ai_embedding.yaml`

## Installation

1. Copy `memory_auto_archive.yaml` to `config/blueprints/automation/madalone/`
2. Create automation: **Settings -> Automations -> Create -> Use Blueprint**

## Configuration

<details>
<summary><strong>① Control</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| `enable_archive` | `true` | Blueprint-level kill switch for archiving |
| `archive_time` | `03:45:00` | Daily time to run the archive check (after housekeeping at 03:00) |

</details>

<details>
<summary><strong>② Options</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| `notification_after_archive` | `true` | Send a persistent notification with archive stats |
| `dry_run` | `false` | Test mode -- reports what would be archived without moving data |

</details>

## Technical Notes

- **Mode:** `single` / `max_exceeded: silent`
- Archive target percentage, recency days, and protection tags are read from helpers -- not blueprint inputs
- The scheduled trigger calls `memory_health_check` first and only proceeds if a threshold is breached
- The event trigger skips the health check (the event itself confirms the breach)
- Dry run mode passes through to the pyscript service -- no data is moved

## Changelog

- **v1.0:** Initial release (I-42 Phase 2) -- reactive + scheduled archiving with dry run support

## Author

**madalone**

## License

See repository for license details.
