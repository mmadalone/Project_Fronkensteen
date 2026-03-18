# Voice PE -- Resume Media After Conversation

![header](https://raw.githubusercontent.com/mmadalone/HA-Master-Repo/main/images/header/voice_pe_resume_media-header.jpeg)

Resumes playback only on the media players that were actually playing before a Home Assistant Voice PE conversation started. Designed to pair with a companion automation that detects active players, stores their state in `input_boolean` helpers, and pauses or ducks those players during the conversation. This blueprint handles only the resume-after-conversation part.

## How It Works

```
┌──────────────────────────────────┐
│ Trigger                          │
│  Satellite: responding → idle    │
└──────────────┬───────────────────┘
               │
    ┌──────────▼──────────┐
    │ For each media_player│
    └──────────┬──────────┘
               │
    ┌──────────▼──────────────────────────┐
    │ Build helper ID from player name    │
    │ input_boolean.<player_id>_was_playing│
    └──────────┬──────────────────────────┘
               │
        ┌──────▼──────┐
        │ Helper ON?  │
        └──┬──────┬───┘
          yes     no
           │      │
    ┌──────▼──┐   │
    │ Resume  │   │
    │ playback│   │
    └──────┬──┘   │
           │      │
    ┌──────▼──────▼───┐
    │ Turn helper OFF  │
    │ (ready for next) │
    └──────────────────┘
```

## Features

- Resumes only players that were actually playing (no false starts)
- Automatic helper cleanup after each conversation
- Supports multiple satellites and media players
- Per-player `continue_on_error` prevents one failure from blocking others
- Convention-based helper naming: `media_player.X` maps to `input_boolean.X_was_playing`

## Prerequisites

- Home Assistant 2024.10.0+
- At least one Voice PE satellite (`assist_satellite` domain)
- For each media player, a matching helper: `input_boolean.<player_id>_was_playing`
- A companion automation that sets helpers ON and pauses/ducks media when Voice PE starts

## Installation

1. Copy `voice_pe_resume_media.yaml` to `config/blueprints/automation/madalone/`
2. Create automation: **Settings -> Automations -> Create -> Use Blueprint**

## Configuration

<details><summary><strong>① Satellites & Media Players</strong></summary>

| Input | Default | Description |
|---|---|---|
| `satellites` | `[]` | Voice PE satellite(s) to monitor for responding-to-idle transitions |
| `media_players` | `[]` | Media players to resume; each needs a matching `input_boolean.<id>_was_playing` helper |

</details>

## Technical Notes

- **Mode:** `single` -- only one resume cycle runs at a time
- **Helper naming:** Strict convention -- `media_player.madteevee` requires `input_boolean.madteevee_was_playing`. If the helper does not exist, the automation logs an error for that entity.
- **Error handling:** `continue_on_error: true` on both resume and cleanup steps

## Changelog

- **v2:** Full style guide compliance -- collapsible sections, plural keys, action syntax, aliases, continue_on_error, merged resume+cleanup loop
- **v1:** Initial release -- functional resume with separate loops

## Author

**madalone**

## License

See repository for license details.
