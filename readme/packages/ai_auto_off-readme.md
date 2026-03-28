![AI Auto-Off](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/ai_auto_off-header.jpeg)

# AI Auto-Off — Zone Vacancy System

Global master switches for the auto-off zone vacancy system. This package provides the top-level toggles that enable or disable automatic device shutdown when zones become vacant. Per-zone configuration (which devices, delay timers, conditions) is handled entirely by blueprint instances.

## What's Inside

- **Input helpers:** 3 (master switch + 2 sub-switches for lights and media) -- moved to `helpers_input_boolean.yaml`

Note: This package file now contains only comments after the C3 helper consolidation. All helpers are defined in `helpers_input_boolean.yaml`.

## Entity Reference

| Entity ID | Type | Purpose |
|---|---|---|
| `input_boolean.ai_auto_off_enabled` | input_boolean | Master switch for the auto-off system |
| `input_boolean.ai_auto_off_lights_enabled` | input_boolean | Sub-switch: allow auto-off for lights |
| `input_boolean.ai_auto_off_media_enabled` | input_boolean | Sub-switch: allow auto-off for media players |

## Dependencies

- **Hardware:** Aqara FP2 presence sensors (`binary_sensor.fp2_presence_sensor_*`)

## Cross-References

- **Blueprint:** `blueprints/automation/ai_auto_off/zone_vacancy.yaml` -- per-zone instances consume these toggles
- **Package:** `ai_context_hot.yaml` -- presence zones referenced by the same FP2 sensors

## Notes

- All three helpers were moved to `helpers_input_boolean.yaml` as part of the C3 consolidation. The package file itself is now a documentation stub.
- Per-zone behavior (which entities to turn off, delay before shutdown, conditions) is configured in individual blueprint instances, not in this package.
- Deployed: 2026-03-04.
