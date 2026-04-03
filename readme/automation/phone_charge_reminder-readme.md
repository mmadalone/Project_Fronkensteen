![Charge reminder -- persona-aware battery nudges](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/phone_charge_reminder-header.jpeg)

# Charge reminder -- persona-aware battery nudges

Escalating TTS reminders when a device's battery drops below configurable thresholds. Works with any device that has a battery sensor and charging binary sensor -- phones, remotes, tablets, etc. Supports three delivery styles -- prompt (LLM-generated, persona-aware), factual (static, no LLM), or silent (no TTS). Congratulates on plug-in when battery was low. Each escalation tier (low, critical, urgent) has its own editable prompt/factual message, reminder count, and inter-reminder delay.

## How It Works

```
┌───────────────┐ ┌─────────────────┐ ┌──────────────────┐
│ Low battery   │ │ Critical battery│ │ Urgent battery   │
│ (< 20%)       │ │ (< 10%)         │ │ (< 5%)           │
└──────┬────────┘ └───────┬─────────┘ └────────┬─────────┘
       └──────────┬───────┘─────────────────────┘
                  │
┌─────────────────┴──────────────────┐  ┌──────────────┐
│  Conditions                        │  │ Plugged in   │
│  • Style != silent                 │  │ trigger      │
│  • Presence check (if configured)  │  └──────┬───────┘
│  • Privacy gate                    │         │
└─────────────────┬──────────────────┘         │
                  │                            │
                  ▼                            ▼
┌─────────────────────────────────┐  ┌─────────────────────┐
│ Bypass save (follow-me/duck)   │  │ Congrats TTS        │
│ Agent dispatch or manual       │  │ (if battery < low)  │
│ Tier-specific reminder loop    │  └─────────────────────┘
│  ├─ LLM prompt OR factual msg  │
│  ├─ Satellite > Player > Queue │  ┌─────────────────────┐
│  └─ Inter-tier delay           │  │ Fully charged (100%)│
│ Bypass restore                 │  │ TTS announcement    │
└─────────────────────────────────┘  └─────────────────────┘
```

## Features

- Three escalation tiers: casual (low), critical, urgent -- each with configurable thresholds
- Three delivery styles: prompt (LLM persona), factual (static), silent (no TTS)
- Per-tier configurable prompts, factual messages, and reminder counts
- **Generic device support** -- configurable `device_name` input and `{device}` placeholder in prompts
- Congratulation message when device is plugged in while battery was low
- Optional "fully charged" announcement at 100% while still charging
- Agent dispatcher support with manual pipeline fallback
- TTS delivery priority: Assist Satellite > explicit media player > TTS queue default
- Configurable TTS volume with automatic save/restore
- Follow-me bypass via refcount system
- Ducking bypass with save/restore
- Presence sensor gating (suppress when nobody home)
- Privacy gate with per-person tier suppression
- HA restart catch-up check
- `{battery}` and `{device}` placeholders in all prompts and messages

## Prerequisites

- Home Assistant 2024.10.0+
- Battery level sensor (device_class: battery)
- Charging state binary sensor
- Pyscript integration with `tts_queue_speak` and `agent_dispatch` services
- Optional: Assist Satellite for satellite-based announcements
- Optional: Refcount bypass scripts for follow-me management

## Installation

1. Copy `phone_charge_reminder.yaml` to `config/blueprints/automation/madalone/`
2. Create automation: **Settings -> Automations -> Create -> Use Blueprint**

## Configuration

<details>
<summary><strong>① Device</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| `device_name` | `phone` | Name of the device (e.g., "phone", "remote control", "tablet"). Used in prompts and dispatcher intent. Use `{device}` in custom prompts. |
| `battery_sensor` | *(required)* | Battery level sensor (device_class: battery) |
| `charging_sensor` | *(required)* | Binary sensor for charging state (on = charging) |

</details>

<details>
<summary><strong>② Thresholds & messages</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| `low_threshold` | `20` | Low tier threshold (%) |
| `low_reminder_count` | `2` | Number of low-tier reminders (30 min apart) |
| `low_prompt` | *(casual LLM prompt)* | LLM prompt for low tier |
| `low_factual` | `{device} battery at {battery}%...` | Static message for low tier |
| `critical_threshold` | `10` | Critical tier threshold (%) |
| `critical_reminder_count` | `2` | Number of critical reminders (15 min apart) |
| `critical_prompt` | *(urgent LLM prompt)* | LLM prompt for critical tier |
| `critical_factual` | `{battery}% battery. This is not a drill...` | Static message for critical tier |
| `urgent_threshold` | `5` | Urgent tier threshold (%) |
| `urgent_reminder_count` | `2` | Number of urgent reminders (5 min apart) |
| `urgent_prompt` | *(emergency LLM prompt)* | LLM prompt for urgent tier |
| `urgent_factual` | `{battery}%! Your {device} is about to die!...` | Static message for urgent tier |

</details>

<details>
<summary><strong>③ Agent & delivery</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| `use_dispatcher` | `true` | Use AI dispatcher for persona selection |
| `conversation_agent` | `Rick` | Voice Assistant pipeline when dispatcher is disabled |
| `style` | `prompt` | Delivery style: prompt / factual / silent |
| `congrats_prompt` | *(playful LLM prompt)* | LLM prompt for plug-in congratulation |
| `congrats_factual` | `Good call plugging that in...` | Static plug-in congratulation text |

</details>

<details>
<summary><strong>④ TTS & speaker output</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| `satellite_entity` | *(empty)* | Assist Satellite for announcements (priority over media player) |
| `tts_output_player` | *(empty)* | Media player for TTS via queue |
| `tts_volume` | `0.0` | TTS volume (0 = don't change) |
| `bypass_ducking` | `false` | Skip volume ducking on other speakers during TTS |

</details>

<details>
<summary><strong>⑤ Quiet hours & DND</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| `dnd_sensor` | *(empty)* | Phone DND sensor -- suppresses when not "off" or "unavailable" |
| `enable_quiet_hours` | `false` | Enable time-based quiet window |
| `quiet_start` | `23:00:00` | Quiet hours start time |
| `quiet_end` | `07:00:00` | Quiet hours end time |

</details>

<details>
<summary><strong>⑥ Features & presence</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| `enable_congrats` | `true` | Congratulate when phone is plugged in while battery was low |
| `enable_fully_charged` | `true` | Announce when battery reaches 100% while charging |
| `fully_charged_prompt` | *(friendly LLM prompt)* | LLM prompt for fully charged announcement |
| `fully_charged_factual` | `{device} is fully charged...` | Static fully charged message |
| `presence_sensor` | *(empty)* | Binary sensor for occupancy (suppress TTS when off) |

</details>

<details>
<summary><strong>⑦ Bypass controls</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| `bypass_follow_me` | `true` | Pause follow-me during reminder sequence |
| `bypass_claim_script` | `script.refcount_bypass_claim` | Refcount claim script |
| `bypass_release_script` | `script.refcount_bypass_release` | Refcount release script |

</details>

<details>
<summary><strong>⑧ Privacy</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| `privacy_tier` | `t2` | Privacy gate tier (off/t1/t2/t3) |
| `privacy_gate_enabled` | `input_boolean.ai_privacy_gate_enabled` | Privacy gate system toggle |
| `privacy_gate_mode` | `input_select.ai_privacy_gate_mode` | Privacy gate behavior |
| `privacy_gate_person` | `person.miquel` | Person entity for tier suppression |

</details>

<details>
<summary><strong>⑨ Infrastructure</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| `dispatcher_enabled` | `input_boolean.ai_dispatcher_enabled` | Dispatcher system toggle |

</details>

## Technical Notes

- **Mode:** `restart` / `max_exceeded: silent`
- Reminder loops stop early if the device is plugged in (charging sensor checked each iteration)
- Inter-reminder delays: low = 30 min, critical = 15 min, urgent = 5 min
- LLM failures fall back to factual messages automatically
- TTS delivery uses a 3-tier priority: satellite announce > explicit player > default queue
- HA restart trigger performs a catch-up battery check
- Fully charged trigger fires when battery crosses above 99

## Changelog

- **v6:** Generic device support -- new `device_name` input and `{device}` placeholder. Works with phones, remotes, tablets, etc. Backwards compatible (defaults to "phone").
- **v5:** Quiet hours & DND -- optional time-based quiet window and DND sensor gate
- **v4:** Optional "fully charged" TTS announcement at 100% while charging
- **v3:** Per-tier prompts and factual messages, reminder count with repeat loops, bypass follow-me and ducking, mode restart
- **v2:** Dispatcher support, conversation-agent selector, editable prompts, presence sensor
- **v1:** Initial blueprint -- replaces package `ai_phone_charge_reminder.yaml`

## Author

**madalone**

## License

See repository for license details.
