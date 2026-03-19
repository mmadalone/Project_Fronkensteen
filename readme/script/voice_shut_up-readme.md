# Voice -- Shut Up (Pause All Media)

![Voice Shut Up](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/voice_shut_up-header.jpeg)

LLM tool wrapper that pauses all currently playing media players. This script triggers the "Voice -- Active Media Controls" automation with `command = "shut_up"`, which finds all candidate players in state `playing` and pauses them. From the LLM's perspective, this is a single-purpose tool: "pause everything that is currently playing sound."

## How It Works

```
LLM calls script
        |
        v
┌───────────────────────────────┐
│ Resolve automation state      │
│ Check if available & enabled  │
└──────────┬────────────────────┘
           |
     ┌─────┴─────┐
     │ Available? │
     └─────┬─────┘
       NO  |  YES
       |   |   |
       v   |   v
  ┌────────┐  ┌──────────────────────────┐
  │ Notify │  │ Trigger automation with  │
  │ (if on)│  │ command = "shut_up"      │
  │ + STOP │  │                          │
  └────────┘  │ → pauses ALL playing     │
              │   candidate players      │
              └──────────────────────────┘
```

## Features

- Single-purpose LLM tool -- "stop all sound in the house"
- Delegates to the central "Voice -- Active Media Controls" automation (single source of truth for media player candidates)
- Pre-flight validation: checks if the target automation exists and is enabled
- Optional persistent notification on misconfiguration
- Configurable phrase lists for LLM agent prompt documentation (shutdown phrases vs. conversational insults)
- Companion to "Voice -- Pause Active Media" and "Voice -- Stop Radio"

## Prerequisites

- An automation created from the **"Voice -- Active Media Controls (Kodi / MA / SpotifyPlus / Alexa / etc.)"** automation blueprint, with its `candidates` input populated
- That automation must be enabled

## Installation

1. Copy `voice_shut_up.yaml` to `config/blueprints/script/madalone/`
2. Create script: **Settings -> Automations & Scenes -> Scripts -> Add -> Use Blueprint**

## Configuration

<details>
<summary><strong>① Core Configuration</strong></summary>

| Input | Default | Description |
|---|---|---|
| `active_media_automation` | _(none)_ | The automation entity created from the "Voice -- Active Media Controls" blueprint |
| `enable_notifications` | `true` | Create a persistent notification if the automation is missing or disabled |

</details>

<details>
<summary><strong>② Phrase Documentation</strong></summary>

| Input | Default | Description |
|---|---|---|
| `shutdown_phrases` | `shut up`, `shut the fuck up`, `be quiet`, `stop everything`, `kill the sound`, `stop all the noise`, `mute everything` | Phrases that mean "stop all media" -- for LLM agent prompt, not parsed by the script |
| `conversational_phrases` | `shut up, you're wrong`, `shut the fuck up, Rick`, `shut up, that's not what I meant` | Insult/conversational phrases that do NOT mean stop media -- for LLM agent prompt |

</details>

## Technical Notes

- **Mode:** `single`, `max_exceeded: silent`
- The script itself does NOT parse user phrases -- phrase lists are documentation for your LLM agent prompt
- Automation state check catches `unavailable`, `unknown`, and `off` (disabled)
- Uses `automation.trigger` with `skip_condition: true` to bypass the automation's own conditions
- Copy the configured phrases into your LLM agent description to keep intent disambiguation in sync

## Changelog

- **v1.0** -- Initial version with pre-flight validation and phrase documentation

## Author

**Madalone + Assistant**

## License

See repository for license details.
