# Voice -- Active Media Controls (Kodi / MA / SpotifyPlus / Alexa / etc.)

![header](https://raw.githubusercontent.com/mmadalone/HA-Master-Repo/main/images/header/voice_active_media_controls.jpeg)

Centralized voice media control automation. It does not listen to voice directly -- instead, thin wrapper scripts (created from companion script blueprints) call this automation with a `command` variable. This pattern keeps all logic in one place while giving the LLM agent clean, single-purpose tools to call. Supports three commands: `pause_active`, `stop_radio`, and `shut_up`.

## How It Works

```
┌──────────────────────────┐
│  Script calls automation │
│  with command variable   │
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│  Phase 1: Validate       │
│  requirements            │
│  (candidates/radio list) │
└────────────┬─────────────┘
             │
      ┌──────┴──── missing? ─────┐
      │                          │
      ▼                          ▼
  Notify user              Stop with error
  (persistent              (requirements
   notification)            not met)
             │
             ▼
┌──────────────────────────┐
│  Phase 2: Dispatch       │
└────────────┬─────────────┘
             │
    ┌────────┼────────────┐
    ▼        ▼            ▼
┌────────┐┌──────────┐┌────────┐
│ pause  ││ stop     ││ shut   │
│ active ││ radio    ││ up     │
│        ││          ││        │
│ First  ││ Pause    ││ Pause  │
│ active ││ all MA   ││ ALL    │
│ player ││ radio    ││playing │
│ by     ││ players  ││candi-  │
│priority││          ││dates   │
└────────┘└──────────┘└────────┘
```

## Features

- **pause_active:** Pauses the highest-priority candidate that is playing or paused
- **stop_radio:** Pauses all configured Music Assistant radio players
- **shut_up:** Pauses ALL currently playing candidates at once
- Priority-ordered candidate list (TV first, then speakers, etc.)
- Misconfiguration notifications help with setup (can be disabled once stable)
- Unknown command detection with notification
- Invoked programmatically via scripts, not directly by voice

## Prerequisites

- Home Assistant 2024.10.0 or later
- One or more `media_player` entities
- Companion wrapper scripts (created from script blueprints) that call this automation

## Installation

1. Copy `voice_active_media_controls.yaml` to `config/blueprints/automation/madalone/`
2. Create automation: **Settings -> Automations -> Create -> Use Blueprint**
3. Create wrapper scripts from companion script blueprints that pass the `command` variable

## Configuration

### Section 1 -- Media players

| Input | Default | Description |
|---|---|---|
| Candidate media players | _(empty)_ | Priority-ordered list of all controllable media players. Required for `pause_active` and `shut_up` |
| Music Assistant "radio" players | _(empty)_ | MA players considered "radio" for the `stop_radio` command |

### Section 2 -- Notifications

| Input | Default | Description |
|---|---|---|
| Enable persistent notifications | true | Creates HA persistent notifications when a command is invoked but required players are not configured |

## Technical Notes

- **Mode:** `restart`
- **Trigger:** Dummy `automation_reloaded` event -- the automation is only invoked programmatically by scripts passing a `command` variable
- **Two-phase design:** Phase 1 validates requirements and notifies on misconfiguration; Phase 2 dispatches the command
- **Error handling:** All `media_player.media_pause` calls use `continue_on_error: true`
- **No-op safety:** If no candidates are playing/paused, a notification is created instead of a silent failure

## Changelog

- **v3:** Audit fixes -- collapsible sections, defaults on all inputs, source_url
- **v2:** Restructured choose architecture, migrated to 2024.10+ syntax
- **v1:** Initial version -- unified voice media control dispatcher

## Author

**madalone**

## License

See repository for license details.
