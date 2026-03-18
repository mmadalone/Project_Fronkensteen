# AI Project Sync

Periodically syncs project files from `/config/projects/` into L2 memory and L1 helpers for voice agent awareness. Fires persistent notifications on sync failure or project status changes. Thin orchestration wrapper -- all logic lives in `pyscript/project_promote.py`.

## How It Works

```
┌─────────────────────────────┐
│ Triggers (any of):          │
│  • Time pattern (N minutes) │
│  • Manual boolean → ON      │
│  • HA startup               │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│ Condition: enable == true   │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│ Step 1: Call pyscript        │
│ project_promote_now          │
│ (force=true if manual)       │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│ Step 2: Reset manual trigger │
│ boolean if it was used       │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│ Step 3: Stale notification   │
│ (persistent_notification if  │
│  sync returned stale=true)   │
└─────────────────────────────┘
```

## Features

- **Periodic sync** -- configurable interval (5--1440 minutes)
- **Manual trigger** -- toggle an input boolean for immediate sync
- **Startup sync** -- runs on HA restart to ensure fresh data
- **Stale notifications** -- persistent notification on sync failure with consecutive failure count
- **Status change notifications** -- optional alert when a project changes status (e.g., active to blocked)
- **Pyscript cache-aware** -- engine has a 5-minute cache, so intervals under 5 are effectively 5

## Prerequisites

- Home Assistant (no specific min_version declared)
- `pyscript.project_promote_now` service (from `pyscript/project_promote.py`)
- Project files in `/config/projects/*.md` with YAML frontmatter
- An `input_boolean` for manual trigger (default: `input_boolean.ai_project_data_stale`)

## Installation

1. Copy `project_sync.yaml` to `config/blueprints/automation/madalone/`
2. Create automation: **Settings → Automations → Create → Use Blueprint**

## Configuration

### ① Core

| Input | Default | Description |
|-------|---------|-------------|
| **Enable** | `true` | Kill switch for this automation instance |
| **Sync interval (minutes)** | `30` | How often to sync project files (min 5, max 1440, step 5) |
| **Manual trigger** | `input_boolean.ai_project_data_stale` | Input boolean to trigger an immediate sync; auto-resets after |

### ② Notifications & Paths

| Input | Default | Description |
|-------|---------|-------------|
| **Project directory** | `/config/projects` | Path to the directory containing project `.md` files |
| **Notify on stale** | `true` | Send a persistent notification when project sync fails |
| **Notify on status change** | `false` | Send a notification when a project changes status |

## Technical Notes

- `mode: single` with `max_exceeded: silent` -- no overlapping runs.
- The `force` parameter is passed to pyscript only when the manual trigger fires, bypassing the engine's 5-minute cache.
- The stale notification check uses `promote_result.get('stale', false)` with safe defaults.
- Manual trigger boolean is reset to OFF after sync completes regardless of result.

## Changelog

- **v1:** Initial blueprint

## Author

**madalone**

## License

See repository for license details.
