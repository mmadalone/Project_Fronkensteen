# Routine Deviation Actions (I-40)

Fires when `routine_fingerprint.py` detects that the user's zone sequence has deviated from a known routine fingerprint. Consumes the `ai_routine_deviation` event. Use it to send check-in notifications, speak TTS messages, or adjust automations when the expected routine is broken.

## How It Works

```
┌─────────────────────────────┐
│ Event: ai_routine_deviation │
│ data: fingerprint_id,       │
│   expected_zone, actual_zone│
│   step, total_steps         │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│ Conditions (all must pass): │
│  ✓ Enable toggle is ON      │
│  ✓ Progress ≥ threshold     │
│    (step/total ≥ min)       │
│  ✓ Fingerprint in filter    │
│    (or filter empty = all)  │
│  ✓ Cooldown elapsed since   │
│    last trigger              │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│ Set template variables:     │
│ expected, actual,           │
│ fingerprint_id              │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│ TTS announcement (optional) │
│ Speaks tts_message on       │
│ tts_speaker if configured   │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│ Custom deviation actions    │
│ (user-defined action block) │
└─────────────────────────────┘
```

## Features

- **Event-driven** -- triggers on `ai_routine_deviation` events from the routine fingerprint engine
- **Progress gate** -- only fires after a minimum fraction of the routine is complete (prevents early false positives)
- **Fingerprint filter** -- comma-separated list to watch specific routines, or empty for all
- **Cooldown** -- suppresses repeat triggers within a configurable window
- **Optional TTS** -- speak a custom message with `{{ expected }}` and `{{ actual }}` template variables
- **Custom actions** -- user-defined action block for notifications, scene changes, etc.

## Prerequisites

- Home Assistant 2024.10.0+
- `pyscript/routine_fingerprint.py` firing `ai_routine_deviation` events
- An `input_boolean` for the per-instance kill switch
- Optional: a `media_player` for TTS announcements

## Installation

1. Copy `routine_deviation_actions.yaml` to `config/blueprints/automation/madalone/`
2. Create automation: **Settings → Automations → Create → Use Blueprint**

## Configuration

### ① Control

| Input | Default | Description |
|-------|---------|-------------|
| **Enable toggle** | (required) | Per-instance kill switch (`input_boolean` entity) |
| **Minimum routine progress** | `0.5` | Only fire if deviation happens after this fraction (0.0--1.0) of the routine is complete |
| **Cooldown (minutes)** | `30` | Suppress repeat triggers within this window (5--180 min) |
| **Fingerprint filter** | (empty) | Comma-separated fingerprint IDs to watch; empty = all |

### ② Actions

| Input | Default | Description |
|-------|---------|-------------|
| **Deviation actions** | `[]` | User-defined actions to run on routine deviation |
| **TTS speaker** | (optional) | Media player for optional TTS check-in message |
| **TTS message** | (empty) | Static TTS message; supports `{{ expected }}` and `{{ actual }}` variables. Empty = skip TTS |

## Technical Notes

- `mode: single` with `max_exceeded: silent` -- no overlapping runs.
- Cooldown uses `this.attributes.last_triggered` to calculate elapsed time -- no helper entity needed.
- The progress gate divides `step` by `total_steps` from the event data, with safe defaults for division by zero.
- The fingerprint filter splits on commas and trims whitespace for clean matching.
- Template variables `expected`, `actual`, and `fingerprint_id` are set in a dedicated variables step and available in both TTS message and custom actions.

## Changelog

- **v1:** Initial blueprint

## Author

**madalone**

## License

See repository for license details.
