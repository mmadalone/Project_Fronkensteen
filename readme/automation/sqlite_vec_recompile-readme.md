![sqlite-vec Recompile (I-2a)](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/sqlite_vec_recompile-header.jpeg)

# sqlite-vec Recompile (I-2a)

Monitors Home Assistant Core updates and recompiles `vec0.so` if the sqlite-vec extension becomes incompatible after an update. When HA Core updates, the Alpine base image (and its SQLite version) may change, making the compiled `vec0.so` incompatible. This blueprint detects the update, runs a health check, and triggers a recompile if needed.

## How It Works

```
┌─────────────────────────────┐
│ Trigger: HA Core update     │
│ entity changes to "off"     │
│ (update installed)          │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│ Condition: kill switch      │
│ is not ON                   │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│ Step 1: Wait 2 minutes      │
│ (let HA stabilize)          │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│ Step 2: Health check via    │
│ pyscript.memory_vec_        │
│ health_check                │
└──────────────┬──────────────┘
               │
          ┌────┴────┐
          ▼         ▼
     ┌────────┐ ┌───────────┐
     │ HEALTHY│ │ UNHEALTHY │
     │ Notify │ │           │
     │ OK +   │ │ Step 4:   │
     │ stop   │ │ Recompile │
     └────────┘ │ via shell │
                └─────┬─────┘
                      │
                      ▼
                ┌───────────┐
                │ Step 5:   │
                │ Re-check  │
                │ health    │
                └─────┬─────┘
                      │
                      ▼
                ┌───────────┐
                │ Step 6:   │
                │ Notify    │
                │ success   │
                │ or FAILURE│
                └───────────┘
```

## Features

- **Automatic detection** -- triggers when HA Core update is installed
- **Health check first** -- tests `vec0.so` before attempting recompile (avoids unnecessary work)
- **Shell-based recompile** -- calls `shell_command.recompile_vec0` to build from source
- **Post-recompile verification** -- re-runs health check after recompile to confirm success
- **Mobile notifications** -- sends success/failure status with persistent flag on failure
- **Kill switch** -- optional `input_boolean` to disable without removing the automation

## Prerequisites

- Home Assistant (no specific min_version declared)
- SSH addon installed and running
- `shell_command.recompile_vec0` configured in `configuration.yaml`
- `/config/scripts/recompile_vec0.sh` present on the HA instance
- `pyscript.memory_vec_health_check` service available
- A mobile notification service (e.g., `notify.mobile_app_iphone`)

## Installation

1. Copy `sqlite_vec_recompile.yaml` to `config/blueprints/automation/madalone/`
2. Create automation: **Settings → Automations → Create → Use Blueprint**

## Configuration

### ① Core

| Input | Default | Description |
|-------|---------|-------------|
| **Notification Target** | (required) | Mobile notification service (e.g., `notify.mobile_app_iphone`) |
| **Kill Switch** | (optional) | `input_boolean` to disable recompile; ON = disabled |

## Technical Notes

- `mode: single` -- only one recompile can run at a time.
- The trigger watches `update.home_assistant_core_update` transitioning to `"off"`, which means an available update was just installed.
- A 2-minute delay after the trigger lets HA Core fully stabilize before testing `vec0.so`.
- The kill switch check handles empty/None values gracefully -- if no kill switch is configured, the condition always passes.
- `continue_on_error: true` on notification actions ensures notification failures do not block the recompile flow.
- Failed recompile notifications are marked `persistent: true` so they remain visible until manually dismissed.
- The notification uses a `tag: sqlite-vec-recompile` so subsequent notifications replace rather than stack.

## Changelog

- **v1.0.0:** Initial blueprint

## Author

**madalone**

## License

See repository for license details.
