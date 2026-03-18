# AI Sleep Detection

Detects sleep and wake states from FP2 presence sensors with configurable detection windows, minimum duration thresholds, and occupant count gating (to mitigate cat false positives). Originally defined automations inline; now uses a single blueprint instance. Part of the I-17 integration milestone.

## What's Inside

| Type | Count |
|------|-------|
| Input helpers (external) | 8 |
| Blueprint instance (external) | 1 |

## Entity Reference

| Entity ID | Type | Purpose |
|-----------|------|---------|
| `input_boolean.ai_sleep_detected` | Input Boolean | Current sleep state |
| `input_boolean.ai_sleep_detection_enabled` | Input Boolean | Kill switch |
| `input_boolean.ai_sleep_false_positive_flag` | Input Boolean | Manual false positive override |
| `input_datetime.ai_sleep_start` | Input Datetime | Sleep start timestamp |
| `input_datetime.ai_sleep_end` | Input Datetime | Wake timestamp |
| `input_datetime.ai_sleep_window_start` | Input Datetime | Detection window start time |
| `input_datetime.ai_sleep_window_end` | Input Datetime | Detection window end time |
| `input_number.ai_sleep_min_duration` | Input Number | Minimum minutes for valid sleep detection |
| `input_select.ai_sleep_detection_sensor` | Input Select | Configurable presence sensor picker |

## Dependencies

- **Blueprint:** `sleep_detection.yaml` — combines sleep start, sleep end, and false positive handling into one lifecycle blueprint
- **Pyscript:** `pyscript/presence_patterns.py` — `sleep_detect_log` service for logging sleep events
- **Pyscript:** `pyscript/sleep_config.py` — populates the sensor picker dropdown
- **Hardware:** FP2 presence sensors (configurable via `ai_sleep_detection_sensor`)
- **Helper files:** `helpers_input_boolean.yaml`, `helpers_input_datetime.yaml`, `helpers_input_number.yaml`, `helpers_input_select.yaml`

## Cross-References

- **ai_privacy_gate.yaml** — `sleep_detection` is a T3 (Ambient) gated feature
- **ai_predictive_schedule.yaml** — sleep data informs bedtime timing recommendations
- **ai_context_hot.yaml** — sleep state may be referenced in hot context
- **Bedtime blueprints** — may check sleep detection state for coordination

## Notes

- The original inline automations (`ai_sleep_detect_start`, `ai_sleep_detect_end`, `ai_sleep_false_positive`) were refactored into a single `sleep_detection.yaml` blueprint instance.
- The sensor picker (`ai_sleep_detection_sensor`) allows switching the monitored presence sensor without editing YAML.
- Cat mitigation uses occupant count gating to avoid false sleep detection when only a pet is on the bed sensor.
