# Scene Preference Apply (C6)

Applies learned light scene preferences when a zone becomes occupied. Works with `scene_learner.py` which records preferences over time from observed light states in occupied zones. Create one instance per zone.

## How It Works

```
┌──────────────────────────────────────────────────┐
│                   TRIGGER                         │
│  FP2 presence sensor: off → on                    │
│  (held for presence_delay, default 10 seconds)    │
└────────────────────────┬─────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────┐
│                 CONDITIONS                        │
│  • Kill switch ON?                                │
│  • Guest mode OFF?                                │
│  • Bedtime behavior allows?                       │
│  • Privacy gate passes?                           │
└────────────────────────┬─────────────────────────┘
                         │ all pass
                         ▼
┌──────────────────────────────────────────────────┐
│     GET LEARNED PREFERENCE                        │
│     pyscript.scene_learner_get(zone)              │
│     → observations count + light settings         │
└────────────────────────┬─────────────────────────┘
                         │
              ┌──────────┴──────────┐
              │                     │
     observations >= min    observations < min
              │                     │
              ▼                     ▼
┌────────────────────┐  ┌────────────────────┐
│ APPLY LEARNED      │  │ RUN FALLBACK       │
│                    │  │ ACTION              │
│ 1. Pause circadian │  │ (user-configured   │
│    automation       │  │  or do nothing)    │
│ 2. Fire suppress   │  └────────────────────┘
│    event           │
│ 3. scene_learner   │
│    _apply(zone)    │
│ 4. Wait resume_min │
│ 5. Re-enable       │
│    circadian       │
└────────────────────┘
```

## Features

- Presence-triggered application of learned light preferences per zone
- Configurable minimum observation threshold before applying (default 5)
- Automatic circadian lighting pause during application with configurable resume delay
- Fires `ai_scene_learner_suppress` event to prevent the scene learner from recording its own output
- Configurable fallback action when no learned preference exists
- Bedtime integration: skip entirely or apply brightness-only (dim_only mode)
- Guest mode gate: suppresses during guest presence
- Standard privacy gate (off/t1/t2/t3)
- 8 supported zones matching entity_config.yaml: workshop, living_room, main_room, kitchen, bed, lobby, bathroom, shower

## Prerequisites

- Home Assistant 2024.10.0+
- Pyscript services: `pyscript.scene_learner_get`, `pyscript.scene_learner_apply`
- FP2 presence sensor (binary_sensor)
- `input_boolean` for per-instance kill switch
- Corresponding `circadian_lighting` instance toggle (optional, for pause/resume)

## Installation

1. Copy `scene_preference_apply.yaml` to `config/blueprints/automation/madalone/`
2. Create automation: **Settings -> Automations -> Create -> Use Blueprint**
3. Create one instance per zone

## Configuration

<details><summary>① Control</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `enable_toggle` | _(required)_ | Per-instance kill switch (input_boolean) |
| `target_zone` | _(required)_ | Zone matching entity_config.yaml scene_learner_lights: workshop, living_room, main_room, kitchen, bed, lobby, bathroom, shower |
| `presence_sensor` | _(required)_ | FP2 binary sensor for this zone |
| `presence_delay` | `10 seconds` | How long presence must hold before applying |

</details>

<details><summary>② Learning thresholds</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `min_observations` | `5` | Minimum recorded observations before applying preferences. Lower = faster learning but less reliable (3–50) |

</details>

<details><summary>③ Application</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `transition_seconds` | `3` | Transition duration when applying learned preferences (1–30 s) |
| `circadian_resume_minutes` | `30` | Re-enable the circadian automation after this many minutes. Set to 0 to never re-enable (manual reset needed) (0–120 min) |
| `fallback_action` | `[]` | Action to run if no learned preference exists (e.g. turn on at circadian defaults). Leave empty to do nothing |

</details>

<details><summary>④ Gates</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `circadian_toggle` | `""` | Kill switch of the circadian_lighting instance for this zone. Turned off while learned preference is active, restored after resume delay |
| `focus_mode_entity` | `input_boolean.ai_focus_mode` | Focus mode entity |
| `guest_mode_entity` | `input_boolean.ai_guest_mode` | Guest mode entity |
| `bedtime_entity` | `input_boolean.ai_bedtime_active` | Bedtime entity |
| `bedtime_behavior` | `skip` | Bedtime behavior: `skip` (do not apply during bedtime), `dim_only` (apply brightness, ignore color) |

</details>

<details><summary>⑤ Privacy</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `privacy_tier` | `off` | Privacy gate tier (off/t1/t2/t3) |
| `privacy_gate_enabled` | `input_boolean.ai_privacy_gate_enabled` | Privacy gate enabled entity |
| `privacy_gate_mode` | `input_select.ai_privacy_gate_mode` | Privacy gate mode entity |
| `privacy_gate_person` | `""` | Person entity for tier suppression lookups |

</details>

## Technical Notes

- **Mode:** `single` / `max_exceeded: silent` -- only one execution per instance at a time
- **Trigger:** FP2 presence sensor `off` -> `on` with configurable `presence_delay` (default 10 seconds -- much shorter than ambient music's 2-minute delay, since lighting should respond quickly)
- **Sequencing:** This is C6 Layer 3. Layer 2 (zone_preactivation) fires BEFORE arrival with predicted generic values; this blueprint fires AFTER arrival and overrides with learned preferences
- **Circadian coordination:** When a circadian_toggle is configured, the blueprint turns it off before applying learned preferences and turns it back on after `circadian_resume_minutes`. This prevents the circadian automation from immediately overwriting learned values
- **Scene learner suppress:** Fires `ai_scene_learner_suppress` event to prevent the scene learner from recording the applied values as new observations (avoids feedback loop)
- **Fallback action:** Uses `choose: [] / default: !input fallback_action` pattern to execute user-configured actions when no learned preference exists

## Changelog

- **v1.0.0:** Initial blueprint -- C6 Layer 3

## Author

**madalone**

## License

See [LICENSE](../../LICENSE) in the repository root.
