# Automation Trigger Monitor (Multi)

![header](https://raw.githubusercontent.com/mmadalone/HA-Master-Repo/main/images/header/automation_trigger_mon-header.jpeg)

Writes a line to Home Assistant's system log whenever any of the selected automations is triggered. Optionally logs the states of extra entities (e.g., presence sensors) at the moment of the trigger. Useful for debugging automation timing, understanding trigger sources, and correlating automation fires with sensor states.

## How It Works

```
┌────────────────────────────────┐
│ Trigger                        │
│  Event: automation_triggered   │
└──────────────┬─────────────────┘
               │
    ┌──────────▼──────────────────┐
    │ Condition                   │
    │  entity_id in monitored    │
    │  automations list?         │
    └──────────┬──────────────────┘
               │ yes
    ┌──────────▼──────────────────────┐
    │ system_log.write (info)         │
    │  ├─ Automation entity_id        │
    │  ├─ Automation name             │
    │  ├─ Trigger source              │
    │  └─ Extra entity states (if any)│
    └─────────────────────────────────┘
```

## Features

- Monitor multiple automations from a single instance
- Logs automation name, entity_id, and trigger source
- Optional extra entity state snapshot at trigger time
- Non-intrusive: writes to system log at `info` level
- Bounded queue prevents buildup from rapid-fire triggers

## Prerequisites

- Home Assistant 2024.10.0+

## Installation

1. Copy `automation_trigger_mon.yaml` to `config/blueprints/automation/madalone/`
2. Create automation: **Settings -> Automations -> Create -> Use Blueprint**

## Configuration

<details><summary><strong>① Configuration</strong></summary>

| Input | Default | Description |
|---|---|---|
| `monitored_automations` | `[]` | Automations to log when triggered (do NOT include this monitor itself) |
| `entities_to_log` | `[]` | Optional extra entities whose states are included in the log line |

</details>

## Technical Notes

- **Mode:** `queued`, `max: 10` -- handles rapid successive triggers without dropping events, bounded to prevent queue explosion
- **Log format:** `[Automation monitor] <entity_id> (<name>) triggered via <source>. States at trigger time: <entity>=<state> ...`
- **Self-monitoring warning:** Do not add this automation to its own monitored list -- it would create an infinite trigger loop

## Changelog

- **v2.1 (2026-02-19):** Audit fixes -- bounded queue, changelog dates, source_url, cleaner log output
- **v2 (2025-02-17):** Style guide compliance -- modern syntax, template safety, header image
- **v1 (2025-02-17):** Initial version

## Author

**madalone**

## License

See repository for license details.
