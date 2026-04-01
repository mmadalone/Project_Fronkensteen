# Bedtime Routine Plus -- LLM-Driven Goodnight (Kodi)

![header](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/bedtime_routine_plus-header.jpeg)

Fully LLM-orchestrated bedtime wind-down with Kodi media playback. The TV stays ON -- Kodi plays movies, TV shows, or favourites selected via LLM conversation or preset configuration. Library pre-fetch injects the full Kodi catalog into the LLM context for intelligent content selection. Conversational modes (curated/freeform/both) use multi-turn satellite dialogue. Preset mode plays fixed content directly -- no conversation, maximum efficiency. Sleepy TV detection skips content switching if bedtime media is already playing.

> **Looking for audiobook/Music Assistant playback?** See the companion *Bedtime Routine* blueprint (`bedtime_routine.yaml`).

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
│  └─ Privacy gate                    │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  Agent selection (dispatcher/manual)│
│  Kill lights (except lamp)          │
│  Speaker reset (optional)           │
│  Stop other media players           │
│  Sleepy TV detection                │
└──────────────┬──────────────────────┘
               │
        ┌──────┴──────┐
        ▼             ▼
┌──────────────┐ ┌───────────────────┐
│  Preset mode │ │  Conversational   │
│  Play Kodi   │ │  Satellite dialog │
│  content     │ │  + Kodi library   │
│  directly    │ │  pre-fetch        │
└──────┬───────┘ └─────────┬─────────┘
       └──────────┬────────┘
                  ▼
┌─────────────────────────────────────┐
│  Settling-in TTS (optional)         │
│  Countdown timer (negotiable)       │
│  Bathroom occupancy guard           │
│  Final goodnight TTS (optional)     │
│  Lamp off + cleanup                 │
│  TV sleep timer (optional)          │
└─────────────────────────────────────┘
```

## Features

- Four content selection modes: curated list, freeform (LLM picks from Kodi library), both, or preset
- Kodi library pre-fetch via JSON-RPC: movies, in-progress shows, recently added episodes
- Genre filtering: preferred and excluded genres for bedtime content
- Bedtime mood descriptor injected into LLM prompt
- Sleepy TV detection: skips content switching if bedtime media is already playing (title, content ID, PVR, or combined match)
- Multi-turn satellite conversation for content selection
- Scheduled and manual triggers with cross-midnight weekend overrides
- Day-of-week gate with cross-midnight day attribution
- Optional presence sensor gate (ANY/ALL mode, minimum duration)
- TV stays ON for Kodi -- optional TV sleep timer for delayed power-off
- TV sleep timer supports CEC or custom script
- Lights-off with lamp exclusion during countdown
- Speaker reset via power-cycle switches
- Negotiable countdown timer via LLM conversation
- Bathroom occupancy guard with grace period and max timeout
- Settling-in contextual TTS with sensor data
- Final goodnight contextual TTS with sensor data
- Privacy gate with per-feature override (T1/T2/T3 tiers)
- AI agent dispatcher or manual pipeline selection
- Duck guard snapshot updates after volume changes

## Prerequisites

- Home Assistant 2024.10.0+
- Kodi integration with a configured media player
- Assist satellites for conversational modes
- pyscript services: `agent_dispatch`, `tts_queue_speak`, `agent_whisper`
- (Optional) TTS audio player separate from the TV
- (Optional) Bathroom occupancy sensor

## Installation

1. Copy `bedtime_routine_plus.yaml` to `config/blueprints/automation/madalone/`
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
| Require ALL sensors | `false` | ALL sensors must confirm (vs ANY). |
| Run on these days | All days | Day-of-week gate. Manual triggers bypass this. |

</details>

<details>
<summary><strong>Section 2 -- Devices</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| TV media player | _(empty)_ | TV entity for CEC control (used by sleep timer). |
| TV off script | _(empty)_ | Script for TV shutdown (used by sleep timer). |
| Lights to turn off | `{}` | Lights/switches to kill immediately. Supports area/label targeting. |
| Living room lamp | _(empty)_ | Lamp that stays on during countdown, turned off last. |
| Speaker reset switches | `{}` | Switches to power-cycle before TTS. |
| Speaker reset delay | `0:00:02` | Delay between off and on for speaker reset. |
| Media players to stop | `{}` | Additional media players to pause/stop (Kodi excluded automatically). |

</details>

<details>
<summary><strong>Section 3 -- AI Conversation</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| Voice Assistant | `Rick - Bedtime` | Assist Pipeline for the bedtime conversation. |
| Assist satellites | `{}` | Voice PE satellites for conversation delivery. |
| Use Dispatcher | `true` | Let the dispatcher select the persona dynamically. |
| Default countdown | `4` min | Minutes before the lamp turns off. |
| Enable countdown negotiation | `true` | Allow LLM to negotiate extra time. |
| Enable bedtime media offer | `true` | Let LLM offer bedtime content. |
| Bedtime announcement prompt | _(default)_ | LLM prompt for the bedtime announcement. |
| Goodnight prompt | _(default)_ | LLM prompt for the final goodnight (conversational modes). |

</details>

<details>
<summary><strong>Section 4 -- Kodi Playback</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| Kodi media player | _(empty)_ | Kodi entity for playback (stays playing). |
| Kodi volume target | `0.15` | Volume for bedtime (0.0-1.0). |
| Bedtime media mode | `curated` | curated, freeform, both, or preset. |
| Curated content list | _(empty)_ | Name=ContentID pairs, one per line. |
| Preset content ID | _(empty)_ | Content path/URI for preset mode. |
| Kodi media content type | `DIRECTORY` | DIRECTORY, video, CHANNEL, or music. |
| TTS audio player | _(empty)_ | Speaker for TTS (separate from the TV). |
| Post-play delay | `3` s | Wait after play_media before reading Kodi state. |
| Media conversation settle delay | `30` s | Wait after satellite conversation before continuing. |

</details>

<details>
<summary><strong>Section 5 -- Sleepy TV Detection</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| Detection method | `media_title_contains` | Title match, content ID match, playing+title, or PVR channel. |
| Match string | _(empty)_ | String to match against Kodi media_title or content_id. |
| PVR channel sensor | `sensor.madteevee_pvr_channel` | REST sensor for PVR channel matching. |

</details>

<details>
<summary><strong>Section 6 -- Kodi Library & Genre Preferences</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| Enable library pre-fetch | `true` | Fetch Kodi library via JSON-RPC for LLM selection. |
| Fetch timeout | `10` s | Timeout per JSON-RPC call. |
| Max movies to fetch | `50` | Maximum movies to retrieve. |
| Max in-progress shows | `20` | Maximum in-progress TV shows. |
| Max recently added episodes | `20` | Maximum recently added episodes. |
| Preferred bedtime genres | _(empty)_ | Comma-separated preferred genres. |
| Excluded genres | _(empty)_ | Comma-separated genres to filter out. |
| Bedtime mood descriptor | _(default)_ | Freeform text describing ideal bedtime mood. |

</details>

<details>
<summary><strong>Section 7 -- Settling-In TTS</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| Enable settling-in TTS | `false` | Brief contextual announcement after content starts. |
| Settling-in prompt | _(default)_ | LLM prompt for the settling-in message. |
| Settling-in context sensors | `[]` | Entities for LLM context. |

</details>

<details>
<summary><strong>Section 8 -- Final Goodnight TTS</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| Enable final goodnight TTS | `false` | Contextual goodnight after bathroom guard clears. |
| Final goodnight prompt | _(default)_ | LLM prompt for the final goodnight. |
| Goodnight context sensors | `[]` | Entities for LLM context. |

</details>

<details>
<summary><strong>Section 9 -- Bathroom Guard & Timing</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| Bathroom occupancy sensor | _(empty)_ | Binary sensor for bathroom occupancy. |
| Bathroom grace period | `0:02:00` | Keep lamp on this long after bathroom clears. |
| Bathroom guard max timeout | `0:10:00` | Maximum wait before forcing lamp off. |
| Countdown minutes helper | _(empty)_ | `input_number` for negotiated countdown. |
| Temporary switches | `{}` | Switches turned on during the flow, cleaned up at end. |
| Post-TTS delay | `5` s | Buffer after TTS to let streaming finish. |

</details>

<details>
<summary><strong>Section 10 -- TV Sleep Timer</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| Enable TV sleep timer | `false` | Auto power-off the TV after a delay. |
| Sleep timer duration | `60` min | Minutes to wait before powering off. |
| Sleep timer method | `cec` | CEC (media_player.turn_off) or Script (custom). |

</details>

<details>
<summary><strong>Section 11 -- Weekend Overrides</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| Weekend behavior | `same_as_weekdays` | Same, disabled on weekends, or use weekend profile. |
| Weekend days | `sat, sun` | Which days count as "weekend." |
| Weekend scheduled bedtime | `00:30:00` | Separate bedtime trigger for weekends. |

</details>

<details>
<summary><strong>Section 12 -- Infrastructure</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| Ducking flag entity | `input_boolean.ai_ducking_flag` | Audio ducking active flag. |
| Duck guard enabled | `input_boolean.ai_duck_guard_enabled` | Duck guard system toggle. |
| Dispatcher enabled | `input_boolean.ai_dispatcher_enabled` | AI agent dispatcher toggle. |
| `bypass_ducking` | `false` | Skip volume ducking on other speakers during TTS |

</details>

<details>
<summary><strong>Section 13 -- Privacy</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| Privacy gate tier | `t1` | Privacy tier (off/T1/T2/T3). |
| Privacy gate enabled | `input_boolean.ai_privacy_gate_enabled` | Privacy gate toggle. |
| Privacy gate mode | `input_select.ai_privacy_gate_mode` | Mode selector. |
| Privacy gate person | `person.miquel` | Person entity for suppression lookups. |

</details>

## Technical Notes

- **Mode:** `single` (silent on overflow)
- **Version:** 5.4.14
- Manual triggers bypass both the day-of-week gate and the presence gate
- Cross-midnight day attribution: scheduled times before noon are attributed to the previous calendar day
- The Kodi entity is automatically excluded from the "media players to stop" list
- Sleepy TV detection runs before content selection -- if bedtime media is already playing, content switching is skipped
- Library pre-fetch uses JSON-RPC with configurable timeouts per call
- In-progress TV shows bypass the excluded genres filter (continuations are always offered)
- All `post_tts_delay_val` references include `| int(5)` guards for defensive consistency
- Duck guard snapshot updates occur after every `media_player.volume_set` call

## Changelog

- **v5.4.14:** Audit fix -- `| int(5)` guard on all 7 bare `post_tts_delay_val` delay references (BRP-AUDIT-002)
- **v5.4.13:** Audit fix -- nested `| int(4)` guard on bare `int(default_countdown)` fallback (BRP-AUDIT-001)

## Author

**madalone**

## License

See repository for license details.
