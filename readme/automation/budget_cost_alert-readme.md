# AI Budget -- Cost Alert (v1.0)

Notify and optionally auto-downgrade when daily cost exceeds configurable thresholds. Uses `numeric_state` triggers on the selected cost sensor. Warning level sends a persistent notification and optional TTS announcement. Critical level adds optional auto-downgrade that activates budget fallback mode. Cooldown prevents alert spam during sustained high-cost periods.

## How It Works

```
┌──────────────────────────────────┐
│  TRIGGERS (numeric_state)         │
│  • cost > warning threshold       │ → id: warning
│  • cost > critical threshold      │ → id: critical
└──────────────┬───────────────────┘
               │
               ▼
┌──────────────────────────────────┐
│  Cooldown gate                    │
│  (skip if last alert too recent)  │
└──────────────┬───────────────────┘
               │ pass
               ▼
┌──────────────────────────────────┐
│  Build alert message              │
│  (level, cost, % of limit)       │
└──────────────┬───────────────────┘
               │
       ┌───────┼───────┐
       │       │       │
       ▼       ▼       ▼
┌─────────┐ ┌─────────┐ ┌──────────────┐
│Persistent│ │ Push    │ │ TTS          │
│notifica- │ │ notify  │ │ announcement │
│tion      │ │(if set) │ │ (if enabled) │
│(always)  │ │         │ │ via tts_queue│
└─────────┘ └─────────┘ └──────────────┘
                              │
                              ▼
                  ┌───────────────────────┐
                  │ Auto-downgrade        │
                  │ (critical only,       │
                  │ if enabled)           │
                  │ • Turn on budget      │
                  │   fallback active     │
                  │ • Log to L2 memory    │
                  └───────────────────────┘
```

## Features

- Dual threshold system: warning and critical levels with independent triggers
- Persistent notification always created for both levels
- Optional mobile push notification via configurable notify target
- Optional TTS announcement via `tts_queue_speak` with presence routing
- TTS uses HA Cloud TTS by default (free, always available even when ElevenLabs budget is exhausted)
- Auto-downgrade on critical: activates `ai_budget_fallback_active` to switch all satellites to fallback pipelines
- Cooldown gate prevents repeated alerts of the same level
- Cost percentage calculated against `input_number.ai_budget_daily_cost_limit`
- L2 memory logging on auto-downgrade for audit trail

## Prerequisites

- Home Assistant 2024.10.0+
- `sensor.ai_total_daily_cost` (or configured cost sensor)
- `input_number.ai_budget_daily_cost_limit` (daily limit for percentage calculation)
- `input_boolean.ai_budget_fallback_active` (for auto-downgrade)
- Pyscript modules: `tts_queue` (`tts_queue_speak`), `memory` (`memory_set`) -- for TTS and auto-downgrade logging

## Installation

1. Copy `budget_cost_alert.yaml` to `config/blueprints/automation/madalone/`
2. Create automation: **Settings -> Automations -> Create -> Use Blueprint**

## Configuration

<details><summary>① Thresholds</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `cost_threshold_warning` | `3.0` | Send a warning notification when daily cost exceeds this amount (EUR) |
| `cost_threshold_critical` | `5.0` | Send a critical alert (and optionally auto-downgrade) at this amount (EUR) |
| `cost_entity` | `sensor.ai_total_daily_cost` | Sensor providing the daily cost value |

</details>

<details><summary>② Notifications</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `notify_target` | _(empty)_ | Service target for mobile/push notifications (e.g., `notify.mobile_app_phone`). Empty = skip push |
| `tts_announce` | `true` | Announce cost alerts via TTS |
| `tts_fallback_voice` | `tts.home_assistant_cloud` | TTS engine for cost alert announcements |
| `bypass_ducking` | `false` | Skip volume ducking on other speakers during TTS |

</details>

<details><summary>③ Behavior</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `auto_downgrade` | `false` | Auto-activate budget fallback mode on critical threshold |
| `cooldown_minutes` | `30` | Minimum minutes between repeated alerts of the same level |

</details>

## Technical Notes

- **Mode:** `single` -- prevents overlapping alert processing
- **Trigger type:** `numeric_state` with `above:` -- fires when sensor crosses the threshold
- **Cooldown:** Checks `this.attributes.last_triggered` to calculate elapsed time since last alert
- **TTS voice:** Defaults to `tts.home_assistant_cloud` -- free and always available even when the ElevenLabs budget that triggered the alert is itself exhausted
- **TTS priority:** Set to 1 (high) -- alerts should not be suppressed by lower-priority queue items
- **Auto-downgrade guard:** Only activates if `ai_budget_fallback_active` is currently OFF (prevents duplicate activation)
- **L2 memory log:** On auto-downgrade, stores a budget cost alert entry with `scope: system` and tags `budget,cost_alert,fallback`
- **All TTS/pyscript actions** use `continue_on_error: true`

## Author

**madalone**

## License

See [LICENSE](../../LICENSE) in the repository root.
