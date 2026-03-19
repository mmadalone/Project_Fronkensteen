# Proactive -- Presence-Based Last Call

![header](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/bedtime_last_call-header.jpeg)

Speaks a single, AI-generated "last call" message when presence is detected in an area during an allowed time window. Optionally runs an external script after the announcement (e.g. turn off lights, TV, start audio). Uses the AI agent dispatcher or a manually selected pipeline to generate and deliver the message via TTS. Intentionally has no once-per-window cooldown -- if presence is lost and re-detected, the announcement fires again.

## How It Works

```
┌─────────────────────────────────────┐
│  Presence sensor turns ON           │
│  (any configured sensor)            │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  Conditions:                        │
│  ├─ Allowed day? (cross-midnight)   │
│  ├─ Within time window?            │
│  ├─ Media not playing? (optional)  │
│  ├─ Min presence duration met?     │
│  ├─ Presence still active?         │
│  └─ Privacy gate pass?             │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  Agent selection:                   │
│  ├─ Dispatcher path (dynamic)      │
│  └─ Manual pipeline (fallback)     │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  Generate message via LLM           │
│  (conversation.process)             │
│  ├─ LLM prompt + sensor context    │
│  └─ Fallback if LLM fails          │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  Speak via TTS queue                │
│  Whisper self-awareness update      │
│  Run follow-up script (optional)    │
└─────────────────────────────────────┘
```

## Features

- AI-generated last-call message with sensor context injection
- Configurable time window with cross-midnight support
- Day-of-week gate with cross-midnight day attribution
- Minimum presence duration to reduce false triggers from brief walk-throughs
- Optional media-playing guard to avoid interrupting active playback
- Dispatcher or manual pipeline agent selection
- Rich sensor context: media players show title/artist/type, Kodi shows series/episode/PVR data
- Configurable LLM prompt with customizable user name and area name
- Optional follow-up script with configurable delay
- Privacy gate with per-feature override (T1/T2/T3 tiers)
- Fallback static message if LLM fails
- Self-awareness whisper after delivery

## Prerequisites

- Home Assistant 2024.10.0+
- Binary sensors for presence detection
- A media player entity for TTS output
- pyscript services: `agent_dispatch`, `tts_queue_speak`, `agent_whisper`
- (Optional) A conversation agent for LLM message generation

## Installation

1. Copy `bedtime_last_call.yaml` to `config/blueprints/automation/madalone/`
2. Create automation: **Settings -> Automations -> Create -> Use Blueprint**

## Configuration

<details>
<summary><strong>Section 1 -- Presence & Area</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| Presence sensors | `[]` | Binary sensors indicating presence. Automation triggers when ANY turns ON. |
| Area name | `Living room` | Friendly area name used in speech and LLM context. Custom values allowed. |
| User name | `friend` | First name or nickname the AI uses when speaking to the user. |

</details>

<details>
<summary><strong>Section 2 -- Schedule</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| Active from | `20:00:00` | Start of the active time window. |
| Active until | `01:00:00` | End of the active window. Supports cross-midnight. |
| Allowed days | All days | Days of the week this automation is allowed to run. |

</details>

<details>
<summary><strong>Section 3 -- Speech Output</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| Media player | _(required)_ | Speaker for the spoken announcement. |

</details>

<details>
<summary><strong>Section 4 -- Safety & Interruption Guards</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| Minimum presence duration | `0` s | Seconds of continuous presence before firing. |
| Block if media playing | `false` | Suppress announcement if the media player is active. |

</details>

<details>
<summary><strong>Section 5 -- AI Message Generation</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| Voice Assistant | `Rick - Bedtime` | Assist Pipeline for message generation (overridden by dispatcher). |
| Use Dispatcher | `true` | Let the AI dispatcher select the persona dynamically. |
| LLM prompt style | _(default prompt)_ | Instructions for the AI's last-call message. |
| Extra context entities | `[]` | Entities whose state is passed to the AI as context. |

</details>

<details>
<summary><strong>Section 6 -- Follow-Up Script</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| Enable follow-up script | `false` | Run a script after the announcement. |
| Delay before script | `5` s | Wait for TTS to finish before running the script. |
| Script to run | _(empty)_ | External script entity to execute. |

</details>

<details>
<summary><strong>Section 7 -- Privacy</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| Privacy gate tier | `t1` | Privacy tier (off/T1 intimate/T2 personal/T3 ambient). |
| Privacy gate enabled | `input_boolean.ai_privacy_gate_enabled` | Toggle for the privacy gate system. |
| Privacy gate mode | `input_select.ai_privacy_gate_mode` | Mode selector (auto/force_suppress/force_allow). |
| Privacy gate person | `miquel` | Person name for tier suppression lookups. |

</details>

<details>
<summary><strong>Section 8 -- Infrastructure</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| Dispatcher enabled | `input_boolean.ai_dispatcher_enabled` | Toggle for the AI agent dispatcher. |

</details>

## Technical Notes

- **Mode:** `single` (silent on overflow)
- No once-per-window cooldown by design -- re-triggers if presence is lost and re-detected
- Cross-midnight day attribution: post-midnight hours are attributed to the previous calendar day
- The LLM prompt enforces a single sentence, max 220 characters, no quotation marks
- If the LLM call fails or returns empty, a static fallback message is used
- `continue_on_error: true` on all TTS and LLM service calls

## Changelog

- **v2.2:** Audit remediation -- added user_name input (removed hardcoded name), TTS empty-entity guards, continue_on_error on TTS, follow-up script empty-entity guard, sensor_context whitespace cleanup
- **v2.1:** Cross-midnight day attribution fix -- effective_day_key shifts post-midnight hours to previous day
- **v2:** Style guide compliance -- collapsible sections, aliases, error handling
- **v1:** Initial version

## Author

**madalone**

## License

See repository for license details.
