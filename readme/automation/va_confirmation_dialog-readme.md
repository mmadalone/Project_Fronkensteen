![Voice Assistant -- Confirmation Dialog](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/va_confirmation_dialog-header.jpeg)

# Voice Assistant -- Confirmation Dialog

Routes a voice command to a confirmation script. Use for destructive or expensive operations (turning off media centers, rebooting devices) where the assistant should ask "are you sure?" before acting. Create one instance per command pair (on/off, start/stop, etc.).

## How It Works

```
┌─────────────────────────────┐
│ Trigger: conversation       │
│ command matches primary     │
│ or alternate phrase         │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│ Run confirmation script     │
│ (script.turn_on)            │
└─────────────────────────────┘
```

## Features

- **Voice-triggered** -- uses HA's `conversation` trigger to match spoken commands
- **Dual command phrases** -- primary and alternate phrasing for natural language flexibility
- **Script delegation** -- routes to an external script entity that handles the actual confirmation dialog and action
- **Per-command instances** -- create one automation per command pair for clean separation

## Prerequisites

- Home Assistant 2024.10.0+
- A **script** entity that implements the confirmation dialog and executes the guarded action
- At least one voice assistant pipeline configured

## Installation

1. Copy `va_confirmation_dialog.yaml` to `config/blueprints/automation/madalone/`
2. Create one automation per guarded command: **Settings → Automations → Create → Use Blueprint**

## Configuration

### ① Voice Command

| Input | Default | Description |
|-------|---------|-------------|
| **Primary command** | (required) | Main voice command phrase (e.g., "turn off madteevee"). Do NOT leave empty -- an empty command matches ALL voice input |
| **Alternate command** | (required) | Alternate phrasing (e.g., "switch madteevee off"). Duplicate the primary command if no alternate is needed |

### ② Confirmation Action

| Input | Default | Description |
|-------|---------|-------------|
| **Confirmation script** | (required) | Script entity that handles the confirmation dialog and executes the action if confirmed |

## Technical Notes

- `mode: single` with `max_exceeded: silent` -- no overlapping runs.
- **Warning:** An empty command field matches ALL voice input. Both `primary_command` and `alt_command` must be filled. If no alternate phrasing is needed, duplicate the primary command.
- The blueprint uses `script.turn_on` (not `script.call`) to fire the confirmation script. This means the automation does not wait for the script to complete.
- No conditions block -- every matching voice command fires unconditionally.
- The confirmation logic (asking "are you sure?" and handling the response) lives entirely in the external script, keeping this blueprint minimal and reusable.

## Changelog

- **v1:** Initial version

## Author

**madalone**

## License

See repository for license details.
