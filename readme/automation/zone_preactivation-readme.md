# Zone Pre-Activation (I-40)

Pre-activates scenes, lights, or climate before the user arrives in a predicted zone. Consumes the `input_text.ai_predicted_next_zone_raw` helper from `presence_patterns.py`, which contains a JSON payload with the predicted zone, probability, and confidence level. If the prediction changes away or the user does not arrive within a configurable timeout, optional deactivation actions run to undo the pre-activation.

## How It Works

```
┌──────────────────────────────────────┐
│ Trigger                              │
│  ai_predicted_next_zone_raw changes  │
└──────────────┬───────────────────────┘
               │
    ┌──────────▼──────────────┐
    │ Conditions              │
    │  ├─ Enable toggle ON    │
    │  └─ Occupancy gate pass │
    └──────────┬──────────────┘
               │
    ┌──────────▼──────────────────────────┐
    │ Parse prediction JSON               │
    │  zone, probability, confidence      │
    └──────────┬──────────────────────────┘
               │
      ┌────────▼────────┐
      │ Zone matches &  │
      │ prob >= min &   │
      │ conf >= min?    │
      └──┬──────────┬───┘
        yes          no
         │           │
  ┌──────▼────────┐  │
  │ Run pre-      │  │
  │ activation    │  │
  │ actions       │  │
  └──────┬────────┘  │
         │           │
  ┌──────▼────────┐  │
  │ Wait timeout  │  │
  │ Re-check zone │  │
  └──┬────────┬───┘  │
   same     changed  │
    │        │       │
    │  ┌─────▼───────▼──────┐
    │  │ Run deactivation   │
    │  │ actions (if any)   │
    │  └────────────────────┘
    │
    └──▶ done (user arrived)
```

## Features

- Prediction-driven pre-activation based on Markov model output
- Configurable minimum probability threshold (10-100%)
- Three confidence levels: low, medium, high
- Occupancy gate: restrict to solo/dual household modes
- Custom pre-activation and deactivation action sequences
- Auto-deactivation after configurable timeout if user does not arrive
- Immediate deactivation when prediction changes away from target zone

## Prerequisites

- Home Assistant 2024.10.0+
- `input_text.ai_predicted_next_zone_raw` (from `presence_patterns.py`)
- `sensor.occupancy_mode` (if using occupancy gate)
- Per-instance `input_boolean` kill switch

## Installation

1. Copy `zone_preactivation.yaml` to `config/blueprints/automation/madalone/`
2. Create automation: **Settings -> Automations -> Create -> Use Blueprint**

## Configuration

<details><summary><strong>① Control</strong></summary>

| Input | Default | Description |
|---|---|---|
| `enable_toggle` | _(required)_ | Per-instance kill switch (`input_boolean`) |
| `target_zone` | _(required)_ | Zone name to watch for (e.g., kitchen, living_room, workshop) |
| `min_probability` | `60` | Minimum prediction probability (%) to trigger |
| `min_confidence` | `medium` | Minimum confidence level (low / medium / high) |
| `occupancy_gate` | `any` | Only fire when occupancy mode matches (any / solo_miquel / solo_jessica / dual) |

</details>

<details><summary><strong>② Actions</strong></summary>

| Input | Default | Description |
|---|---|---|
| `pre_activation_actions` | `[]` | Actions to run when prediction matches (e.g., lights, climate) |
| `deactivation_actions` | `[]` | Actions to run on timeout or prediction change (leave empty to skip) |
| `deactivation_timeout_minutes` | `10` | Auto-deactivation timeout (2-30 minutes) |

</details>

## Technical Notes

- **Mode:** `restart`, `max_exceeded: silent` -- new predictions immediately override any in-progress pre-activation cycle
- **JSON parsing:** Prediction helper contains `{"zone": "...", "probability": N, "confidence": "..."}`. Invalid JSON or empty values are safely handled.
- **Confidence mapping:** Internal numeric mapping (low=1, medium=2, high=3) for comparison
- **Deactivation logic:** Runs only if `deactivation_actions` is non-empty. Two paths: timeout-based (waits N minutes, then checks if zone changed) and immediate (prediction changed away from target).

## Author

**madalone**

## License

See repository for license details.
