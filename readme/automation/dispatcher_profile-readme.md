![Dispatcher Profile](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/dispatcher_profile-header.jpeg)

# Dispatcher Profile

Centralized Agent Dispatcher configuration blueprint. Exposes all routing knobs as blueprint inputs -- dispatch mode, era personas, continuity window, handoff settings, expertise routing, TTS stage directions, and budget fallback. On trigger (HA startup or manual button press), pushes all values into the dispatcher's helpers and reloads the routing cache. Multiple instances supported (e.g., "Daytime Profile", "Guest Profile") but only one should be enabled at a time -- last-write-wins.

## How It Works

```
┌─────────────────────────────────────────────────────────┐
│                      TRIGGERS                           │
│  ┌────────────────────────────────────────────────────┐ │
│  │ 1. HA startup                                     │ │
│  │ 2. Manual apply button pressed                    │ │
│  └──────────────────────┬─────────────────────────────┘ │
└─────────────────────────┼───────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│                  CONDITION GATE                         │
│  • Privacy gate (tier-based suppression)               │
└────────────────────────┬────────────────────────────────┘
                         │ pass
                         ▼
┌─────────────────────────────────────────────────────────┐
│                  ACTION SEQUENCE                        │
│  0. On startup: wait 15s for pyscript init             │
│  1. Reload dispatcher cache (refresh agent registry)   │
│  2. Push dispatch mode (auto/fixed/random/round_robin) │
│  3. Push fixed agent persona                           │
│  3b. Push agent pool (comma-separated)                 │
│  4. Push era personas (late night/morning/afternoon/    │
│     evening)                                           │
│  5. Push continuity window                             │
│  6. Push handoff enabled/disabled                      │
│  7. Push expertise routing mode (off/suggest/auto)     │
│  8. Push budget fallback agent                         │
│  8b. Push strip stage directions on/off                │
│  9. Log completion to system_log                       │
└─────────────────────────────────────────────────────────┘
```

## Features

- **One-stop routing config** -- all dispatcher knobs in a single blueprint instance, no manual helper editing required.
- **Dispatch modes** -- Auto (full priority chain: wake word, continuity, topic, era, preference, random), Fixed (single agent), Random, or Round Robin.
- **Agent pool** -- selectable subset of agents for Random, Round Robin, and Auto rotate/fallback. Leave empty to use all discovered agents.
- **Era personas** -- assign a default agent per time-of-day window (late night, morning, afternoon, evening). "None" skips to next priority; "Rotate" picks a different agent each time.
- **Continuity window** -- keep the same agent if last interaction was within N minutes (0-60).
- **Voice handoff toggle** -- enable/disable "pass me to Rick" style mid-conversation agent switching.
- **Expertise routing** -- off, suggest (agent recommends handoff), or auto (agent hands off automatically).
- **TTS stage direction stripping** -- remove `[bracketed]` stage directions from LLM output before TTS.
- **Budget fallback agent** -- which local agent to fall back to when LLM budget is exhausted.
- **Privacy gate** -- tier-based suppression with per-person, per-tier override controls.
- **Multi-profile support** -- create multiple instances (Daytime, Guest, etc.) with different configs; last-write-wins.

## Prerequisites

- Home Assistant
- Pyscript with `dispatcher_reload_cache` service
- Agent dispatcher helper entities (see Configuration below)

## Installation

1. Copy `dispatcher_profile.yaml` to `config/blueprints/automation/madalone/`
2. Create automation: **Settings -> Automations -> Create -> Use Blueprint**

## Configuration

<details>
<summary>Trigger</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `apply_button` | `input_button.ai_dispatcher_apply_config` | Input button to manually trigger config apply |

</details>

<details>
<summary>Dispatch Mode</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `dispatch_mode` | `auto` | How the dispatcher selects agents (auto/fixed/random/round_robin) |
| `fixed_agent` | `rick` | Which persona to always route to when mode is Fixed |
| `agent_pool` | `[]` (all agents) | Which agents participate in Random, Round Robin, and Auto rotate |

</details>

<details>
<summary>Era Personas</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `era_late_night` | `none` | Default agent during 00:00-05:59 |
| `era_morning` | `none` | Default agent during 06:00-11:59 |
| `era_afternoon` | `none` | Default agent during 12:00-17:59 |
| `era_evening` | `none` | Default agent during 18:00-23:59 |

Options per era: None (skip), Rotate, Rick, Quark, Kramer, Deadpool, Doctor Portuondo, or custom.

</details>

<details>
<summary>Continuity / Handoff / Expertise</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `continuity_window` | `5` min | Minutes to keep the same agent after last interaction (0 = disable) |
| `handoff_enabled` | `true` | Allow voice handoff commands |
| `expertise_routing` | `suggest` | Out-of-domain behavior: off, suggest, or auto |
| `strip_stage_directions` | `true` | Remove `[bracketed]` stage directions from TTS output |
| `budget_fallback_agent` | `homeassistant` | Local agent for budget exhaustion fallback |

</details>

<details>
<summary>Privacy</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `privacy_tier` | `off` | Privacy gate tier (off/t1/t2/t3) |
| `privacy_gate_enabled` | `input_boolean.ai_privacy_gate_enabled` | Privacy gate master toggle |
| `privacy_gate_mode` | `input_select.ai_privacy_gate_mode` | Privacy gate behavior selector |
| `privacy_gate_person` | `miquel` | Person name for tier suppression lookups |

</details>

<details>
<summary>Infrastructure</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `tts_strip_stage_directions` | `input_boolean.ai_tts_strip_stage_directions` | Entity for stage direction stripping toggle |
| `voice_handoff_enabled` | `input_boolean.ai_voice_handoff_enabled` | Entity for voice handoff toggle |

</details>

## Technical Notes

- **Mode:** `restart` -- re-applies the entire profile if triggered again mid-run.
- **Startup delay:** 15-second wait on HA start to let pyscript initialize before pushing config.
- **Cache reload:** Step 1 calls `pyscript.dispatcher_reload_cache` with `continue_on_error: true` to populate era helper options.
- **Last-write-wins:** Multiple profile instances can exist, but only the most recently triggered one takes effect.
- **Privacy gate:** Uses the standard 3-tier template with per-automation override support.

## Changelog

- **v1.0.0:** Initial release -- centralized dispatcher configuration via blueprint inputs.

## Author

**madalone**

## License

See repository for license details.
