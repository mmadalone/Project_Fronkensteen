# Smart Bathroom Occupancy Light Control (Door + Shower Zone Optional)

![header](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/smart-bathroom-header.jpeg)

Occupancy-aware bathroom light with optional door sensor and shower zone support. Enable toggles to activate optional sensors -- disabled sensors are ignored in all logic. When the shower zone is active (e.g. Aqara FP2 zone), the light stays on even if the main motion sensor clears behind a glass shower door. Uses a 7-branch state machine to handle all combinations of door, motion, and shower zone events.

## How It Works

```
                    ┌─────────────────┐
                    │    TRIGGERS     │
                    │ door open/close │
                    │ motion on/off   │
                    │ shower cleared  │
                    └────────┬────────┘
                             │
                             ▼
              ┌──────────────────────────┐
              │    7-BRANCH STATE MACHINE │
              └──────────────┬───────────┘
                             │
     ┌────────┬────────┬─────┼─────┬────────┬────────┐
     ▼        ▼        ▼     ▼     ▼        ▼        ▼
  Branch1  Branch2  Branch3  B4    B5     Branch6  Branch7
  Motion   Door     Door    Motion Motion  Door    Shower
  stopped  opened   opened  +open  +helper closed  cleared
  +empty   +not     +occu-  /no    off    +not    +occupied
  +no      occu-    pied    door          occu-   +motion
  shower   pied                           pied    off
     │        │        │      │      │       │       │
     ▼        ▼        ▼      ▼      ▼       ▼       ▼
  Light    Light    Wait    Light  Mark    Light   Light
  OFF      ON       for     ON +   occu-  OFF     OFF
  +clear   (entry)  exit    mark   pied          +clear
  helper            flow    occ.                  helper
```

## Features

- 7-branch state machine covers all door/motion/shower combinations
- Optional door sensor -- disable toggle to ignore door state entirely
- Optional shower zone sensor (e.g. Aqara FP2) -- keeps light on during showering
- Shower zone 5-second debounce prevents false clears
- Configurable motion sensor cooldown delay
- Exit wait timeout prevents automation from hanging if a sensor fails
- Occupancy tracking via dedicated `input_boolean` helper
- `continue_on_error` on all light actions for resilience

## Prerequisites

- Home Assistant 2024.10.0 or later
- A motion/occupancy binary sensor
- A light, switch, or input_boolean to control
- An `input_boolean` helper for occupancy tracking
- (Optional) A door/contact binary sensor
- (Optional) A shower zone presence sensor (e.g. Aqara FP2 zone)

## Installation

1. Copy `smart-bathroom.yaml` to `config/blueprints/automation/madalone/`
2. Create automation: **Settings -> Automations -> Create -> Use Blueprint**

## Configuration

### Section 1 -- Sensors & detection

| Input | Default | Description |
|---|---|---|
| Motion Sensor | _(required)_ | Primary motion/occupancy sensor for the bathroom |
| Use Door Sensor? | false | Enable to use a door/contact sensor in logic |
| Door Sensor | _(empty)_ | Door/contact sensor -- only evaluated when enabled |
| Use Shower Zone Sensor? | false | Enable to use a shower zone presence sensor |
| Shower Zone Sensor | _(empty)_ | Shower zone sensor -- only evaluated when enabled |

### Section 2 -- Lights & helpers

| Input | Default | Description |
|---|---|---|
| Bathroom Light | _(required)_ | Light, switch, or input_boolean to control |
| Occupancy Helper | _(required)_ | Dedicated `input_boolean` tracking occupancy state |

### Section 3 -- Timing

| Input | Default | Description |
|---|---|---|
| Motion Sensor Delay | 2 s | Seconds after motion clears before treating as "no motion" |
| Exit Wait Timeout | 30 min | Max time to wait for motion/shower to clear after door opens |

## Technical Notes

- **Mode:** `single`
- **AP-08 exemption:** Actions block exceeds 200-line / 4-level nesting thresholds -- accepted because the complexity is intrinsic to the 7-branch door/motion/shower state machine
- **Branch 3 depth:** Deepest at 5-6 nesting levels due to sequential wait cascades with timeout handling
- **Live state checks:** Branch 3 uses `is_state()` calls (not pre-computed variables) because state may change during preceding wait periods
- **Timeout handling:** Both motion and shower zone waits use `continue_on_timeout: true` with forced cleanup on timeout
- **Trigger variables:** Duplicated as both `trigger_variables` and `variables` because template triggers need access before the actions block

## Changelog

- **v6:** AP-08 audit exemption note, Branch 6 continue_on_error consistency fix
- **v5:** Added continue_on_error on paired light actions (6 locations), source_url, shower zone debounce (5s), sequential branch renumbering
- **v4:** Fixed AP-44 default values (collapsible sections), added motion pre-check to Branch 5 exit (AP-20)
- **v3:** Fixed stale variable race condition, consolidated choose blocks, inlined state checks
- **v2:** Full style guide compliance -- modern syntax, timeouts, aliases, collapsible inputs
- **v1:** Initial version (Murat Cesmecioglu, modified by Madalone)

## Author

**Murat Cesmecioglu** (modified by Madalone & Miquel)

## License

See repository for license details.
