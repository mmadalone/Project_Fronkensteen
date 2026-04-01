# Bedtime Routine -- LLM-Driven Goodnight (Audiobook)

![header](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/bedtime_routine-header.jpeg)

Fully LLM-orchestrated bedtime wind-down with audiobook playback via Music Assistant. Conversational modes (curated/freeform/both) use multi-turn LLM dialogue on Assist satellites for audiobook selection. Preset mode plays a configured URI directly -- no conversation, maximum efficiency. All modes: stops the TV, kills lights (except the living room lamp), runs a countdown timer, waits for the bathroom occupancy guard to clear, then turns off the final lamp.

> **Looking for Kodi/TV playback?** See the companion *Bedtime Routine Plus* blueprint (`bedtime_routine_plus.yaml`).

## How It Works

```
┌─────────────────────────────────────┐
│  Trigger:                           │
│  ├─ Scheduled time                  │
│  ├─ Manual boolean toggle           │
│  └─ Weekend scheduled time          │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  Gates:                             │
│  ├─ Day-of-week + weekend mode      │
│  ├─ Presence gate (optional)        │
│  ├─ Privacy gate                    │
│  └─ Manual trigger bypasses gates   │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  Agent selection (dispatcher/manual)│
│  Stop TV (CEC/IR/script)           │
│  Kill lights (except lamp)          │
│  Speaker reset (optional)           │
│  Stop other media players           │
└──────────────┬──────────────────────┘
               │
        ┌──────┴──────┐
        ▼             ▼
┌──────────────┐ ┌───────────────────┐
│  Preset mode │ │  Conversational   │
│  Play URI    │ │  Satellite dialog │
│  directly    │ │  for audiobook    │
│              │ │  selection        │
└──────┬───────┘ └─────────┬─────────┘
       └──────────┬────────┘
                  ▼
┌─────────────────────────────────────┐
│  Settling-in TTS (optional)         │
│  Countdown timer                    │
│  Bathroom occupancy guard           │
│  Final goodnight TTS (optional)     │
│  Lamp off + cleanup                 │
└─────────────────────────────────────┘
```

## Features

- Four audiobook selection modes: curated list, freeform (LLM picks via MA), both, or preset (fixed URI)
- Multi-turn satellite conversation for audiobook selection in conversational modes
- Scheduled and manual triggers with cross-midnight weekend overrides
- Day-of-week gate with cross-midnight day attribution
- Optional presence sensor gate (ANY/ALL mode, minimum duration)
- TV shutdown via CEC, IR remote, or custom script
- Lights-off with lamp exclusion during countdown
- Speaker reset via power-cycle switches
- Negotiable countdown timer via LLM conversation
- Bathroom occupancy guard with grace period and max timeout
- Settling-in contextual TTS with sensor data injection (preset mode)
- Final goodnight contextual TTS with sensor data injection (preset mode)
- Privacy gate with per-feature override (T1/T2/T3 tiers)
- AI agent dispatcher or manual pipeline selection
- Duck guard snapshot updates after volume changes
- Weekend overrides: same as weekdays, disabled, or separate weekend profile

## Prerequisites

- Home Assistant 2024.10.0+
- Music Assistant integration with a configured media player
- Assist satellites for conversational modes
- pyscript services: `agent_dispatch`, `tts_queue_speak`, `agent_whisper`
- (Optional) TV entity with CEC support, IR remote, or power-off script
- (Optional) Bathroom occupancy sensor

## Installation

1. Copy `bedtime_routine.yaml` to `config/blueprints/automation/madalone/`
2. Create automation: **Settings -> Automations -> Create -> Use Blueprint**

## Configuration

<details>
<summary><strong>Section 1 -- Trigger</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| Scheduled bedtime | `23:00:00` | Time trigger. Leave empty to disable. |
| Manual trigger boolean | _(empty)_ | `input_boolean` for voice/manual triggering. |
| Presence sensors | `[]` | Optional occupancy/presence/motion sensors. Empty = no gate. |
| Minimum presence duration | `0` min | Minutes of continuous presence before the gate passes. |
| Require ALL sensors | `false` | ALL sensors must confirm (vs ANY single sensor). |
| Run on these days | All days | Day-of-week gate. Manual triggers bypass this. |

</details>

<details>
<summary><strong>Section 2 -- Devices</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| TV media player | _(empty)_ | TV entity for CEC/software power-off. |
| TV off script | _(empty)_ | Script for complex TV shutdown (IR sequences, etc.). |
| IR remote entity | _(empty)_ | Remote entity (Broadlink, SmartIR) for IR power-off. |
| IR power-off command | `Power` | Command string for `remote.send_command`. |
| IR device name | _(empty)_ | Learned device name in the IR remote. |
| Lights to turn off | `{}` | Lights/switches to kill immediately. Supports area/label targeting. |
| Living room lamp | _(empty)_ | Lamp that stays on during countdown, turned off last. |
| Speaker reset switches | `{}` | Switches to power-cycle before TTS. |
| Speaker reset delay | `0:00:02` | Delay between off and on for speaker reset. |
| Media players to stop | `{}` | Additional media players to pause/stop. |

</details>

<details>
<summary><strong>Section 3 -- AI Conversation</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| Voice Assistant | `Rick - Bedtime` | Assist Pipeline for the bedtime conversation. |
| Assist satellites | `{}` | Voice PE satellites for bedtime conversation delivery. |
| Use Dispatcher | `true` | Let the dispatcher select the persona dynamically. |
| Default countdown | `4` min | Minutes before the lamp turns off. Negotiable in conversational modes. |
| Enable countdown negotiation | `true` | Allow LLM to negotiate extra time. |
| Enable audiobook offer | `true` | Let LLM offer a bedtime audiobook. |
| Bedtime announcement prompt | _(default)_ | LLM prompt for the bedtime announcement. |
| Goodnight prompt | _(default)_ | LLM prompt for the final goodnight (conversational modes only). |

</details>

<details>
<summary><strong>Section 4 -- Audiobook</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| Music Assistant player | _(empty)_ | MA player for audiobook playback. |
| Audiobook selection mode | `both` | curated, freeform, both, or preset. |
| Curated audiobook list | _(example titles)_ | Comma-separated titles for curated/both modes. |
| Preset audiobook URI | _(empty)_ | MA content ID for preset mode. |
| Audiobook media type | `auto` | How MA resolves the audiobook (auto/audiobook/album/playlist/track). |
| Audiobook playback volume | `0.25` | Volume level for audiobook playback. |

</details>

<details>
<summary><strong>Section 5 -- Bathroom Guard & Timing</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| Bathroom occupancy sensor | _(empty)_ | Binary sensor for bathroom occupancy. |
| Bathroom grace period | `0:02:00` | Keep lamp on this long after bathroom clears. |
| Bathroom guard max timeout | `0:10:00` | Maximum wait before forcing lamp off. |
| Countdown minutes helper | _(empty)_ | `input_number` for negotiated countdown duration. |
| Temporary switches | `{}` | Switches turned on during the flow, cleaned up at end. |
| Post-TTS delay | `5` s | Buffer after TTS to let streaming audio finish. |

</details>

<details>
<summary><strong>Section 6 -- Settling-In TTS (preset mode)</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| Enable settling-in TTS | `false` | Brief contextual announcement after audiobook starts. |
| Settling-in prompt | _(default)_ | LLM prompt for the settling-in message. |
| Settling-in context sensors | `[]` | Entities for LLM context (temperature, weather, etc.). |

</details>

<details>
<summary><strong>Section 7 -- Final Goodnight TTS (preset mode)</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| Enable final goodnight TTS | `false` | Contextual goodnight after bathroom guard clears. |
| Final goodnight prompt | _(default)_ | LLM prompt for the final goodnight message. |
| Goodnight context sensors | `[]` | Entities for LLM context. |

</details>

<details>
<summary><strong>Section 8 -- Weekend Overrides</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| Weekend behavior | `same_as_weekdays` | Same, disabled on weekends, or use weekend profile. |
| Weekend days | `sat, sun` | Which days count as "weekend." |
| Weekend scheduled bedtime | `01:00:00` | Separate bedtime trigger for weekends. |

</details>

<details>
<summary><strong>Section 9 -- Infrastructure</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| Ducking flag entity | `input_boolean.ai_ducking_flag` | Audio ducking active flag. |
| Duck guard enabled | `input_boolean.ai_duck_guard_enabled` | Duck guard system toggle. |
| Dispatcher enabled | `input_boolean.ai_dispatcher_enabled` | AI agent dispatcher toggle. |
| `bypass_ducking` | `false` | Skip volume ducking on other speakers during TTS |

</details>

<details>
<summary><strong>Section 10 -- Privacy</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| Privacy gate tier | `t1` | Privacy tier (off/T1/T2/T3). |
| Privacy gate enabled | `input_boolean.ai_privacy_gate_enabled` | Privacy gate toggle. |
| Privacy gate mode | `input_select.ai_privacy_gate_mode` | Mode selector. |
| Privacy gate person | `person.miquel` | Person entity for suppression lookups. |

</details>

## Technical Notes

- **Mode:** `single` (silent on overflow)
- Manual triggers bypass both the day-of-week gate and the presence gate
- Cross-midnight day attribution: scheduled times before noon are attributed to the previous calendar day
- In preset mode, media pause is attempted first with a fallback to stop
- The settling-in and final goodnight TTS slots are only active in preset audiobook mode
- LLM error responses (response_type guard) are not spoken as TTS
- Duck guard snapshot updates occur after every `media_player.volume_set` call

## Changelog

- **v4.2.1:** Audit fixes -- presence duration gate fix (states[].last_changed), default() guard on TV states, explicit defaults on all inputs, collapsed sections, time defaults
- **v4.2.0:** Weekend overrides -- run_days gate, optional weekend profile, cross-midnight day attribution
- **v4.1.1:** Fixed LLM error messages spoken as TTS -- added response_type guard
- **v4.1.0:** Optional presence sensor gate (ANY/ALL, min duration, manual bypass)
- **v4.0.1:** Clarified name/description -- this is the Audiobook/MA variant
- **v4:** Preset audiobook mode, media pause-with-fallback, settling-in and final-goodnight contextual TTS

## Author

**madalone**

## License

See repository for license details.
