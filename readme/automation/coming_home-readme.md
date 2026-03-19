# Coming Home -- AI Welcome

![header](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/coming_home-header.jpeg)

Triggers when a person arrives home, waits for entrance occupancy to confirm physical presence (GPS alone is not reliable), resets speakers by power-cycling switches, activates temporary helper switches, generates an AI greeting via a conversation agent, then starts an Assist conversation on Voice PE satellites. Includes GPS-bounce cooldown, timeout handling on every wait, and guaranteed cleanup of temporary switches on all exit paths.

## How It Works

```
┌─────────────────────────────────────┐
│  Person entity: not_home -> home    │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  Conditions:                        │
│  ├─ GPS bounce cooldown             │
│  └─ Privacy gate                    │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  Clean up stale arrival switches    │
│  (from interrupted mode:restart)    │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  Wait for entrance occupancy        │
│  (skip if already triggered)        │
│  └─ Timeout -> abort cleanly        │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  Power-cycle speaker switches       │
│  Turn on temporary switches         │
│  Wait for entrance to clear         │
│  └─ Timeout -> cleanup + abort      │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  Agent selection (dispatcher/manual)│
│  Generate AI greeting               │
│  Start Assist conversation on sats  │
│  Whisper self-awareness update      │
│  Log greeting for troubleshooting   │
│  Post-conversation delay            │
│  Clean up temporary switches        │
└─────────────────────────────────────┘
```

## Features

- GPS state change triggers with entrance occupancy confirmation
- GPS-bounce cooldown (configurable, default 900s)
- Speaker power-cycle reset to clear stale Bluetooth/audio connections
- Temporary switch activation with guaranteed cleanup on all exit paths (including timeouts and mode:restart)
- AI-generated personalized greeting via conversation agent
- Multi-person support with custom arrival names
- Assist satellite conversation for follow-up interaction (lights, TV, music)
- AI agent dispatcher or manual pipeline selection
- Privacy gate with per-feature override (T1/T2/T3 tiers)
- Self-awareness whisper after greeting
- Logbook entry for troubleshooting silent satellite failures
- Timeout handling on entrance wait and entrance-clear wait

## Prerequisites

- Home Assistant 2025.4.0+ (required for `assist_satellite.start_conversation`)
- Person entities with GPS tracking
- Binary sensor for entrance occupancy (Aqara FP2, PIR, etc.)
- Assist satellites for voice interaction
- pyscript services: `agent_dispatch`, `agent_whisper`

## Installation

1. Copy `coming_home.yaml` to `config/blueprints/automation/madalone/`
2. Create automation: **Settings -> Automations -> Create -> Use Blueprint**

## Configuration

<details>
<summary><strong>Section 1 -- Detection & Triggers</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| Persons | `[]` | Person entities whose home/not_home transition triggers the flow. |
| Arrival names | _(empty)_ | Custom names for the greeting (one per line). Overrides person friendly names. |
| Entrance occupancy sensor | _(required)_ | Binary sensor confirming physical presence at the entrance. |
| Entrance wait timeout | `0:02:00` | How long to wait for the entrance sensor before aborting. |
| Cooldown | `900` s | Minimum seconds between runs to suppress GPS bounce. |

</details>

<details>
<summary><strong>Section 2 -- Device Preparation</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| Reset switches | `[]` | Switches to power-cycle (OFF -> delay -> ON) to reset speakers. |
| Reset delay | `0:00:02` | Pause between turning switches off and on. |
| Temporary switches | `[]` | Switches activated during the flow, guaranteed cleanup on exit. |

</details>

<details>
<summary><strong>Section 3 -- AI Conversation</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| Voice Assistant | `Rick` | Assist Pipeline for the greeting. Overridden by dispatcher. |
| Use Dispatcher | `true` | Let the dispatcher select the persona dynamically. |
| AI greeting prompt | _(default)_ | Prompt for the greeting. Supports `{{ person_name }}`. |
| Assist satellites | `{}` | Voice PE satellites for the greeting and follow-up conversation. |

</details>

<details>
<summary><strong>Section 4 -- Cleanup & Timing</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| Post-conversation delay | `0:01:00` | How long to wait after starting conversation before switch cleanup. |

</details>

<details>
<summary><strong>Section 5 -- Privacy</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| Privacy gate tier | `off` | Privacy tier (off/T1/T2/T3). |
| Privacy gate enabled | `input_boolean.ai_privacy_gate_enabled` | Privacy gate toggle. |
| Privacy gate mode | `input_select.ai_privacy_gate_mode` | Mode selector. |
| Privacy gate person | `miquel` | Person name for suppression lookups. |

</details>

<details>
<summary><strong>Section 6 -- Infrastructure</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| Dispatcher enabled | `input_boolean.ai_dispatcher_enabled` | AI agent dispatcher toggle. |

</details>

## Technical Notes

- **Mode:** `restart` -- if a second person arrives while the first flow is running, the first run is cancelled and temporary switches may remain ON until the new run completes its cleanup
- The first action cleans up stale temporary switches from previous interrupted runs
- Entrance sensor checks use "already triggered" shortcuts to skip unnecessary waits
- All switch operations use `continue_on_error: true`
- Person name template uses `{%- -%}` whitespace control to prevent leading whitespace
- If the conversation agent is not configured, the greeting generation step is skipped
- If no satellites are configured, the `start_conversation` step is skipped
- The greeting fallback includes a device choice prompt (workshop, living room, or both)

## Changelog

- **v4.8:** Fixed leading whitespace in `person_name`, added `choose` guards on `conversation.process` and `assist_satellite.start_conversation`
- **v4.7:** Added "Required." to `entrance_sensor` and `conversation_agent` descriptions
- **v4.6:** Bumped `min_version` to 2025.4.0 (`assist_satellite.start_conversation` requires it), added `source_url`

## Author

**madalone**

## License

See repository for license details.
