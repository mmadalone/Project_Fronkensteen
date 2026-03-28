![Proactive Briefing](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/proactive_briefing-header.jpeg)

# Proactive briefing -- universal (scheduled + presence)

Unified briefing blueprint that replaces both `proactive_briefing_morning` and `proactive_briefing_slot`. Each instance is a user-scheduled briefing with a custom label, fully self-contained. Supports scheduled time triggers (weekday/weekend), presence-based triggers, manual dashboard triggers, and self-resetting delivery flags. Includes volume set/restore with duck guard, media player pause/resume, dispatcher toggle, and custom LLM prompt with context injection.

## How It Works

```
┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────┐ ┌──────────┐
│ Scheduled    │ │ Weekend      │ │ Presence     │ │ Manual   │ │ Reset    │
│ time         │ │ time         │ │ sensor ON    │ │ toggle   │ │ flag     │
└──────┬───────┘ └──────┬───────┘ └──────┬───────┘ └────┬─────┘ └────┬─────┘
       └──────┬─────────┘────────────────┘───────────────┘            │
              │                                                       │
              ▼                                                       ▼
┌─────────────────────────────────┐                    ┌──────────────────────┐
│ Conditions                      │                    │ Turn OFF delivered   │
│ • Kill switch ON                │                    │ flag → stop          │
│ • Delivered flag OFF            │                    └──────────────────────┘
│ • Scheduled time toggle gate    │
│ • Day-of-week + weekend mode    │
│ • Hard window (presence only)   │
│ • Identity confidence >= min    │
│ • Person suppression gate       │
│ • Privacy gate                  │
└───────────────┬─────────────────┘
                │
                ▼
┌─────────────────────────────────┐
│ Auto-reset manual trigger       │
│ Set TTS volume + duck guard     │
│ Pause configured players        │
└───────────────┬─────────────────┘
                │
                ▼
┌─────────────────────────────────┐
│ pyscript.proactive_briefing_now │
│ (sections, prompt, context,     │
│  dispatcher, pipeline)          │
└───────────────┬─────────────────┘
                │
                ▼
┌─────────────────────────────────┐
│ Set delivered flag              │
│ Wait for TTS buffer drain      │
│ Resume paused players           │
│ Restore TTS volume + duck guard │
└─────────────────────────────────┘
```

## Features

- 5 trigger types: scheduled time, weekend time, presence sensors, manual toggle, flag self-reset
- Self-resetting delivery flag prevents repeat delivery (resets at configurable time)
- Weekend mode: same as weekdays, disabled on weekends, or use weekend profile with separate time
- Day-of-week gating (manual trigger bypasses)
- Hard window safety net for presence triggers (configurable start/end times)
- Identity confidence threshold gate
- Person suppression: block briefing when specific persons are home
- Configurable briefing sections (CSV): greeting, weather, calendar, email, schedule, household, memory, projects, media_today/tomorrow/weekly
- Custom LLM briefing prompt with `{content}`, `{context}`, and `{framing}` placeholders
- Jinja2 context template injection evaluated by HA before passing to pyscript
- Download window control: since midnight or rolling 24 hours
- Volume set/restore with duck guard integration
- Media player pause/resume around briefing delivery
- Agent dispatcher toggle with manual pipeline fallback
- Privacy gate with tiered suppression
- Per-instance delivered flag for multi-briefing setups (morning/afternoon/evening)

## Prerequisites

- Home Assistant 2024.10.0+
- Pyscript integration with `proactive_briefing_now`, `duck_manager_update_snapshot` services
- Kill switch helper (`input_boolean`)
- Delivered flag helper (`input_boolean`) per instance
- Optional: presence sensors, manual trigger boolean, identity confidence sensor

## Installation

1. Copy `proactive_briefing.yaml` to `config/blueprints/automation/madalone/`
2. Create per-instance helpers (delivered flags, kill switch)
3. Create automation instances: **Settings -> Automations -> Create -> Use Blueprint**

## Configuration

<details>
<summary><strong>① Schedule & triggers</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| `briefing_label` | `briefing` | Free-text name for dedup, whisper, and logging |
| `enable_scheduled_time` | `true` | Toggle the scheduled time trigger |
| `scheduled_time` | `07:30:00` | Primary time trigger |
| `presence_sensors` | `[]` | Presence-based trigger sensors |
| `manual_trigger` | *(empty)* | input_boolean for voice/dashboard trigger |
| `run_days` | All days | Day-of-week gate |
| `weekend_mode` | `same_as_weekdays` | same / disabled / use_weekend_profile |
| `weekend_days` | `sat, sun` | Days considered weekend |
| `weekend_scheduled_time` | `09:00:00` | Weekend time trigger |
| `hard_window_start` | `05:00:00` | Safety net start (presence only) |
| `hard_window_end` | `23:00:00` | Safety net end (presence only) |

</details>

<details>
<summary><strong>② Identity & presence gate</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| `identity_sensor` | *(empty)* | Identity confidence sensor |
| `min_confidence` | `50` | Minimum confidence to deliver (pts) |
| `suppress_persons` | `[]` | Person entities -- suppress if ANY are home |
| `suppress_persons_enabled` | `false` | Toggle person suppression gate |

</details>

<details>
<summary><strong>③ Delivery control</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| `kill_switch` | *(empty)* | Master enable/disable toggle |
| `delivered_flag` | *(empty)* | Per-instance delivery flag (auto-resets) |
| `reset_time` | `00:01:00` | Time to self-reset delivered flag |

</details>

<details>
<summary><strong>④ Content configuration</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| `sections` | `greeting,weather,calendar,email,schedule,household,memory,projects,media_today` | Enabled sections (CSV) |
| `household_entities` | *(empty)* | Entity IDs for household section (CSV) |
| `briefing_prompt` | *(empty)* | Custom LLM prompt with `{content}`, `{context}`, `{framing}` |
| `context_template` | *(empty)* | Jinja2 template injected into `{context}` |
| `download_window` | `since_midnight` | Radarr/Sonarr window: since_midnight / rolling_24h |

</details>

<details>
<summary><strong>⑤ Volume & media</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| `output_speaker` | *(empty)* | TTS target (empty = auto follow presence) |
| `tts_volume` | `0.0` | Volume before TTS (0 = don't change) |
| `tts_volume_restore` | `0.0` | Volume after TTS (0 = don't restore) |
| `volume_restore_delay` | `5` | Seconds to wait before restoring volume |
| `use_duck_guard` | `true` | Update duck manager snapshot after volume changes |
| `pause_players` | `[]` | Media players to pause/resume around briefing |

</details>

<details>
<summary><strong>⑥ Infrastructure</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| `use_dispatcher` | `true` | Use agent dispatcher for persona selection |
| `conversation_agent` | `Rick` | Pipeline when dispatcher is disabled |
| `ducking_flag` | `input_boolean.ducking_flag` | Ducking active flag |
| `duck_guard_enabled` | `input_boolean.ai_duck_guard_enabled` | Duck guard system toggle |

</details>

<details>
<summary><strong>⑦ Privacy</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| `privacy_tier` | `t2` | Privacy gate tier (off/t1/t2/t3) |
| `privacy_gate_enabled` | `input_boolean.ai_privacy_gate_enabled` | Privacy gate system toggle |
| `privacy_gate_mode` | `input_select.ai_privacy_gate_mode` | Privacy gate behavior |
| `privacy_gate_person` | `miquel` | Person name for tier suppression |

</details>

## Technical Notes

- **Mode:** `single` / `max_exceeded: silent`
- Reset trigger bypasses all conditions via per-condition OR gates
- Manual trigger auto-resets after 1-second delay
- Duck guard snapshot updates only fire when ducking is actively in progress
- Pyscript call uses `continue_on_error: true`; failure is logged to logbook
- Context template is evaluated as Jinja2 by HA before being passed to pyscript
- Privacy gate evaluates per-automation override via `input_select.ai_privacy_gate_proactive_briefing`

## Changelog

- **v1:** Merge of morning + slot blueprints into universal design

## Author

**madalone**

## License

See repository for license details.
