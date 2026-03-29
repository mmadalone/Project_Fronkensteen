![Music -- Weekly Composition Refresh](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/music_weekly_refresh-header.jpeg)

# Music -- Weekly Composition Refresh

Scheduled weekly regeneration of dynamic music compositions (wake-up melodies, bedtime wind-downs). Runs at a configurable day/time. Budget-gated -- skips API generation if daily budget is below the configured threshold, falling back to local FluidSynth generation.

## How It Works

```
┌──────────────────────────────────────┐
│          TRIGGER                     │
│  time trigger (configurable)         │
│  default: Monday 03:00              │
└──────────────────┬───────────────────┘
                   │
                   ▼
┌──────────────────────────────────────┐
│          CONDITIONS                  │
│  • Kill switch ON?                   │
│  • Monday (weekday == 0)?            │
└──────────────────┬───────────────────┘
                   │ pass
                   ▼
┌──────────────────────────────────────┐
│   Read budget remaining              │
│   Check if API generation allowed    │
│   Resolve effective agent lists      │
└──────────────────┬───────────────────┘
                   │
          ┌────────┴────────┐
          │                 │
          ▼                 ▼
┌────────────────┐ ┌────────────────────┐
│ Wake melodies  │ │ Bedtime wind-downs │
│ (if enabled)   │ │ (if enabled)       │
│                │ │                    │
│ For each agent:│ │ For each agent:    │
│ ┌──────────┐   │ │ ┌──────────┐      │
│ │ API OK?  │   │ │ │ API OK?  │      │
│ │ Y: music │   │ │ │ Y: music │      │
│ │   _compose│  │ │ │   _compose│     │
│ │ N: music │   │ │ │ N: music │      │
│ │   _compose│  │ │ │   _compose│     │
│ │   _local  │  │ │ │   _local  │     │
│ └──────────┘   │ │ └──────────┘      │
└────────────────┘ └────────────────────┘
          │                 │
          └────────┬────────┘
                   ▼
┌──────────────────────────────────────┐
│   Log refresh completion             │
│   logbook.log with status summary    │
└──────────────────────────────────────┘
```

## Features

- Scheduled weekly regeneration of dynamic music compositions
- Seed-based reproducibility: same melody all week (ISO week number seed)
- Wake-up melody generation for all or selected agents
- Bedtime wind-down pre-generation to save latency at bedtime
- 3 generation sources: auto (API first, local fallback), ElevenLabs API only, FluidSynth local only
- Budget gate: skips API generation when daily budget remaining is below threshold; FluidSynth fallback still runs (free)
- Per-agent iteration with `continue_on_error: true` so one failure doesn't block others
- Logbook entry with refresh summary on completion

## Prerequisites

- Home Assistant 2024.10.0+
- Pyscript services: `pyscript.music_compose`, `pyscript.music_compose_local`
- `input_boolean.ai_music_composer_enabled` (kill switch)
- `sensor.ai_llm_budget_remaining` (budget gate)

## Installation

1. Copy `music_weekly_refresh.yaml` to `config/blueprints/automation/madalone/`
2. Create automation: **Settings -> Automations -> Create -> Use Blueprint**

## Configuration

<details><summary>① Schedule</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `refresh_time` | `03:00:00` | Time of day to run the refresh (recommend early morning) |

</details>

<details><summary>② Generation</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `wake_melody_enabled` | `true` | Generate new wake-up melodies for the coming week. Uses seed-based reproducibility (same melody all week) |
| `wake_melody_agents` | `[]` (all agents) | Which agents to generate wake melodies for. Leave empty for all agents |
| `bedtime_pregenerate` | `false` | Pre-generate bedtime compositions in advance (saves latency at bedtime). If disabled, bedtime music generates on-demand when triggered |
| `bedtime_agents` | `[]` (all agents) | Which agents to pre-generate bedtime compositions for. Leave empty for all agents |
| `generation_source` | `auto` | Generation source: `auto` (API first, local fallback), `elevenlabs` (API only, high quality, costs credits), `fluidsynth` (local only, instant, free, MIDI quality) |

</details>

<details><summary>③ Infrastructure</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `kill_switch` | `input_boolean.ai_music_composer_enabled` | Music composer kill switch |
| `budget_gate_pct` | `60` | Skip API generation if daily budget remaining is below this %. FluidSynth fallback still runs (free) |

</details>

## Technical Notes

- **Mode:** `single` / `max_exceeded: silent` -- only one refresh at a time
- **Trigger:** `time` at the configured `refresh_time`, runs daily but conditions filter to Monday only (`now().weekday() == 0`)
- **Weekly seed:** `ISO year * 100 + ISO week number` ensures the same seed produces the same melody all week, regenerating only on Monday
- **Budget gating:** Reads `sensor.ai_llm_budget_remaining` and compares against `budget_gate_pct`. When budget is low, the API path is skipped but FluidSynth local generation still runs
- **Agent list:** Empty agent lists default to all 5 agents (rick, quark, deadpool, kramer, portuondo)
- **Content durations:** Wake melodies use `duration_s: 45` for FluidSynth; bedtime compositions use `duration_s: 180`

## Changelog

- **v1.0:** Initial version -- weekly wake melody + bedtime composition refresh

## Author

**madalone**

## License

See [LICENSE](../../LICENSE) in the repository root.
