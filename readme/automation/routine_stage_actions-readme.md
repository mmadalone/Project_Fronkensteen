![Routine Stage Actions (I-40)](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/routine_stage_actions-header.jpeg)

# Routine Stage Actions (I-40)

Triggers actions at specific points within a recognized routine. Consumes `input_text.ai_routine_stage` from `routine_fingerprint.py`. Two trigger modes: fire at a specific step number, or fire when the routine reaches a progress threshold.

## How It Works

```
┌─────────────────────────────┐
│ Trigger: state change on    │
│ input_text.ai_routine_stage │
│                             │
│ Format:                     │
│ fingerprint_id:step_N_of_M  │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│ Conditions (all must pass): │
│  ✓ Enable toggle is ON      │
│  ✓ Stage ≠ none/empty       │
│  ✓ Fingerprint in filter    │
│    (or filter empty = all)  │
│  ✓ Step/progress matches    │
│    the configured mode      │
│  ✓ Once-per-routine guard   │
│    (if enabled)             │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│ Execute stage actions       │
│ (user-defined action block) │
└─────────────────────────────┘
```

## Features

- **Two trigger modes** -- "step" (fire at a specific step number) or "progress" (fire at a percentage threshold)
- **Fingerprint filter** -- watch specific routines by ID, or leave empty for all
- **Once-per-routine guard** -- prevents re-firing during the same routine instance; resets when stage returns to "none"
- **Flexible actions** -- user-defined action block runs at the target stage

## Prerequisites

- Home Assistant 2024.10.0+
- `pyscript/routine_fingerprint.py` updating `input_text.ai_routine_stage`
- An `input_boolean` for the per-instance kill switch

## Installation

1. Copy `routine_stage_actions.yaml` to `config/blueprints/automation/madalone/`
2. Create automation: **Settings → Automations → Create → Use Blueprint**

## Configuration

### ① Control

| Input | Default | Description |
|-------|---------|-------------|
| **Enable toggle** | (required) | Per-instance kill switch (`input_boolean` entity) |
| **Trigger mode** | `progress` | `step` = fire at a specific step number; `progress` = fire at a percentage threshold |
| **Target step** | `0` | Step number to fire at (step mode only, 0 = disabled) |
| **Progress threshold** | `0.75` | Fire when routine is at least this fraction complete (progress mode, 0.1--1.0) |
| **Fingerprint filter** | (empty) | Comma-separated fingerprint IDs to watch; empty = all |
| **Once per routine** | `true` | Only fire once per routine instance; resets when stage goes to "none" |

### ② Actions

| Input | Default | Description |
|-------|---------|-------------|
| **Stage actions** | `[]` | User-defined actions to run at the target routine stage |

## Technical Notes

- `mode: single` with `max_exceeded: silent` -- no overlapping runs.
- Stage value format: `fingerprint_id:step_N_of_M` (e.g., `evening_weekday_living_room_bed:step_3_of_4`).
- The condition block parses step and total from the stage string using `regex_findall('step_(\\d+)_of_(\\d+)')`.
- The fingerprint filter matches only the prefix before the colon.
- The once-per-routine guard compares `this.attributes.last_triggered` against `input_text.ai_routine_stage`'s `last_changed` attribute -- if the stage changed more recently than the last trigger, it allows firing.
- Division by zero in progress mode is safely handled (returns false when total = 0).

## Changelog

- **v1:** Initial blueprint

## Author

**madalone**

## License

See repository for license details.
