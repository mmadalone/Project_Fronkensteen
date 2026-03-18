# Sleep Config -- Entity Picker Services

Provides add/remove picker services for managing sleep light targets stored in L2 memory, and populates dropdown options for sleep detection sensors and light entity selectors from FP2 presence sensors and the light registry. Part of the sleep management subsystem.

## Services

| Service | Parameters | Returns | Description |
|---------|-----------|---------|-------------|
| `pyscript.sleep_lights_add_target` | (none -- reads from picker helper) | `{status, added, count}` | Add light from `input_select.ai_sleep_lights_light_picker` to sleep light targets. Saves to L2. |
| `pyscript.sleep_lights_remove_target` | (none -- reads from picker helper) | `{status, removed, count}` | Remove light from sleep light targets. Saves to L2. |
| `pyscript.sleep_lights_load_display` | (none) | `{status, count}` | Refresh target display sensor from L2 memory. |
| `pyscript.sleep_config_populate_pickers` | (none) | `{status}` | Refresh all sleep-related dropdown options: light picker (all available lights), lights sensor picker (FP2 sensors), detection sensor picker (FP2 sensors). |

All services use `supports_response="optional"`.

## Triggers

| Trigger | Function | Condition |
|---------|----------|-----------|
| `@time_trigger("startup")` | `_sleep_config_startup` | Load targets from L2, populate pickers, set default sensor selections if empty. 5s delay for entity readiness. |

## Key Functions

- `_load_targets_from_l2()` -- Load light target list from L2 memory key `sleep_lights:targets`.
- `_save_targets_to_l2()` -- Save current target list to L2. Uses `expiration_days=0` (no expiry).
- `_update_display()` -- Refresh `sensor.ai_sleep_lights_display` with current targets as markdown list.
- `_set_display(content)` -- Set display sensor value with content, targets list, and count attributes.

## State Dependencies

- `input_select.ai_sleep_lights_light_picker` -- Light entity picker dropdown
- `input_select.ai_sleep_lights_sensor` -- FP2 sensor picker for sleep lights
- `input_select.ai_sleep_detection_sensor` -- FP2 sensor picker for sleep detection
- `input_boolean.ai_test_mode` -- Test mode toggle
- `state.names(domain="light")` -- All available light entities (for picker population)

## Package Pairing

Pairs with `packages/ai_sleep_lights.yaml` (light picker, sensor picker, targets) and `packages/ai_sleep_detection.yaml` (detection sensor picker). Display sensor: `sensor.ai_sleep_lights_display`.

## Called By

- **Dashboard**: Sleep config card uses the picker helpers and display sensor
- **Automations**: Sleep light automations read the target list from the display sensor attributes
- **Depends on**: `pyscript/memory.py` (L2 for target persistence)

## Notes

- **Picker pattern**: Services read from picker helpers rather than accepting entity_id parameters. The user selects in the dashboard, then clicks add/remove.
- **L2 persistence**: Targets stored as JSON array under `sleep_lights:targets` key with no expiry. Survives HA restarts.
- **Default sensor selections**: On startup, if sensor pickers are empty/unknown, defaults to `binary_sensor.fp2_presence_sensor_bed`.
- **FP2 sensor list**: Hardcoded list of 8 FP2 presence sensors matching the standard zone layout.
- **No parameters on add/remove**: These services are designed for dashboard button calls -- they read the current picker selection at call time.
