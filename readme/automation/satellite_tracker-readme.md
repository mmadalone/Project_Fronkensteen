![Satellite Tracker -- Last Active](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/satellite_tracker-header.jpeg)

# Satellite Tracker -- Last Active

Tracks when a voice assistant satellite starts responding and stores its `entity_id` in `input_text.ai_last_satellite`. Used by `voice_handoff.yaml` and other automations to route actions to the correct satellite. Create one instance per satellite.

## How It Works

```
┌─────────────────────────────┐
│ Trigger: satellite state    │
│ changes to "responding"     │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│ Store trigger.entity_id in  │
│ input_text.ai_last_satellite│
└─────────────────────────────┘
```

## Features

- **Per-satellite tracking** -- one instance per satellite, each writes to the same shared helper
- **Last-writer-wins** -- the most recently active satellite is always recorded
- **Zero conditions** -- no gates, no guards, just records the entity ID on every response event
- **Restart-safe** -- `mode: restart` ensures overlapping triggers replace cleanly

## Prerequisites

- Home Assistant 2024.10.0+
- `input_text.ai_last_satellite` helper (defined in `packages/ai_self_awareness.yaml`)
- One or more `assist_satellite` entities

## Installation

1. Copy `satellite_tracker.yaml` to `config/blueprints/automation/madalone/`
2. Create one automation per satellite: **Settings → Automations → Create → Use Blueprint**

## Configuration

### ① Satellite

| Input | Default | Description |
|-------|---------|-------------|
| **Voice PE Satellite** | (required) | The `assist_satellite` entity to track |
| **Last satellite entity** | `input_text.ai_last_satellite` | Helper that stores the last-active satellite entity_id |

## Technical Notes

- `mode: restart` -- if the same satellite triggers again while running, the previous run is replaced.
- Triggers on state change to `"responding"` -- this fires when the satellite begins processing a voice command.
- The stored value is `trigger.entity_id`, which is the full entity ID (e.g., `assist_satellite.kitchen`).
- No conditions block -- every responding event is recorded unconditionally.

## Changelog

- **v1:** Initial blueprint

## Author

**madalone**

## License

See repository for license details.
