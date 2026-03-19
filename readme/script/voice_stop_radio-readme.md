# Voice -- Stop Radio (Music Assistant)

![Header](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/voice_stop_radio-header.jpeg)

LLM tool wrapper that stops or pauses Music Assistant "radio" playback. This script triggers the "Voice -- Active Media Controls" automation with `command = "stop_radio"`, which pauses all players designated as radio sources. Designed as a voice-agent tool for targeted radio control without affecting other media.

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
  │ (if on)│  │ command = "stop_radio"   │
  │ + STOP │  │                          │
  └────────┘  │ → pauses all configured  │
              │   radio players          │
              └──────────────────────────┘
```

## Features

- Single-purpose LLM tool -- "stop the radio"
- Delegates to the central "Voice -- Active Media Controls" automation
- Pre-flight validation: checks if the target automation exists and is enabled
- Optional persistent notification on misconfiguration
- Configurable phrase lists: radio-stop intent vs. non-stop radio mentions
- Companion to "Voice -- Shut Up" and "Voice -- Pause Active Media"

## Prerequisites

- An automation created from the **"Voice -- Active Media Controls (Kodi / MA / SpotifyPlus / Alexa / etc.)"** automation blueprint, with its `radio_players` input populated with Music Assistant radio players
- That automation must be enabled

## Installation

1. Copy `voice_stop_radio.yaml` to `config/blueprints/script/madalone/`
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
<summary><strong>② Phrase Lists</strong></summary>

| Input | Default | Description |
|---|---|---|
| `radio_phrases` | `stop the radio`, `turn off the radio`, `stop this radio station`, `kill the radio`, `stop the radio in here` | Phrases that should trigger stopping MA radio -- for LLM agent prompt |
| `radio_exclude_phrases` | `I like this radio station`, `which radio station is this` | Phrases where "radio" appears but does NOT mean stop -- for LLM documentation |

</details>

## Technical Notes

- **Mode:** `single`, `max_exceeded: silent`
- **Version:** 2.0
- The script itself does NOT parse user phrases -- phrase lists are documentation for your LLM agent prompt
- Automation state check catches `unavailable`, `unknown`, and `off` (disabled)
- Uses `automation.trigger` with `skip_condition: true` to bypass the automation's own conditions
- Only affects players listed in the automation's `radio_players` input -- other media continues

## Changelog

- **v2.0** -- Rebuilt as tool wrapper around central Active Media Controls automation, added phrase documentation and misconfiguration notifications

## Author

**Madalone + Assistant**

## License

See repository for license details.
