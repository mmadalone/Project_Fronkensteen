# Away Patterns -- Entropy Correlation Report (G13)

Weekly entropy-MAE correlation analysis for G13 Phase 1.5. Runs the `pyscript.entropy_correlation_report` service on a configurable schedule, checks the kill switch, and optionally generates a cumulative report when 4+ weeks of data exist.

## How It Works

```
┌──────────────────────────────────────┐
│          TRIGGER                     │
│  time trigger (configurable)         │
│  e.g. Monday 04:30                   │
└──────────────────┬───────────────────┘
                   │
                   ▼
┌──────────────────────────────────────┐
│          CONDITIONS                  │
│  • Kill switch ON?                   │
│  • Correct day of week?             │
└──────────────────┬───────────────────┘
                   │ pass
                   ▼
┌──────────────────────────────────────┐
│   Weekly entropy correlation report  │
│   pyscript.entropy_correlation_report│
│   (lookback = weekly_lookback_days)  │
└──────────────────┬───────────────────┘
                   │
                   ▼
┌──────────────────────────────────────┐
│   Cumulative report (conditional)    │
│   • cumulative_enabled == true       │
│   • weekly report status == ok       │
│   • entries >= cumulative_min_entries │
│   → persistent_notification.create   │
└──────────────────┬───────────────────┘
                   │
                   ▼
┌──────────────────────────────────────┐
│   Log report completion              │
│   logbook.log with status/direction  │
└──────────────────────────────────────┘
```

## Features

- Scheduled weekly entropy-MAE correlation analysis via pyscript service
- Configurable report day (Monday–Sunday) and time
- Adjustable weekly lookback window (1–30 days)
- Optional cumulative all-time report when sufficient data exists (4+ weeks default)
- Cumulative report delivered as a persistent notification with Pearson r, direction, hypothesis, and phase 2 recommendation
- Logbook entry on every run with status, direction, and entry count
- Kill switch for easy enable/disable

## Prerequisites

- Home Assistant 2024.10.0+
- Pyscript service: `pyscript.entropy_correlation_report`
- `input_boolean.ai_entropy_correlation_enabled` (kill switch)

## Installation

1. Copy `entropy_correlation_report.yaml` to `config/blueprints/automation/madalone/`
2. Create automation: **Settings -> Automations -> Create -> Use Blueprint**

## Configuration

<details><summary>① Schedule</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `report_time` | `04:30:00` | Time of day to run (recommend after daily rebuild at 04:15) |
| `report_day` | `0` | Day of the week to run (0 = Monday, 6 = Sunday) |

</details>

<details><summary>② Analysis</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `weekly_lookback_days` | `7` | How many days of arrival data to include in the weekly report |
| `cumulative_enabled` | `true` | When ON and 4+ weeks of data exist, also generates a cumulative all-time report alongside the weekly one |
| `cumulative_lookback_days` | `120` | How many days of arrival data to include in the cumulative report |
| `cumulative_min_entries` | `28` | Minimum number of arrival entries required before generating the cumulative report (~28 = 4 weeks of daily arrivals) |

</details>

<details><summary>③ Infrastructure</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `kill_switch` | `input_boolean.ai_entropy_correlation_enabled` | Correlation kill switch |

</details>

## Technical Notes

- **Mode:** `single` / `max_exceeded: silent` -- only one execution at a time
- **Trigger:** `time` at the configured `report_time`, filtered by day-of-week in conditions
- **Cumulative gating:** Requires weekly report success (`status == ok`) AND at least one entry before attempting cumulative; then checks `cumulative_min_entries` before creating the persistent notification
- **Response variables:** Both weekly and cumulative pyscript calls use `response_variable` to pass result dicts between steps

## Changelog

- **v1.0:** Initial version -- weekly + cumulative entropy correlation reporting

## Author

**madalone**

## License

See [LICENSE](../../LICENSE) in the repository root.
