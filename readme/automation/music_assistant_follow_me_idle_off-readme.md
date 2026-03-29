# Music Assistant -- Follow Me (idle OFF + optional auto-ON)

![header](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/music_assistant_follow_me_idle_off-header.jpeg)

Manages a follow-me toggle (`input_boolean`) for Music Assistant. Automatically turns the toggle OFF when all monitored players have been idle for a configurable duration, and optionally turns it back ON when any player starts playing. Designed as a companion to the multi-room follow-me blueprint that performs the actual queue transfers.

## How It Works

```
┌──────────────────────────┐
│  Any monitored player    │
│  changes state           │
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│  Guard: actual state     │
│  transition? (not just   │
│  attribute change)       │
└────────────┬─────────────┘
             │ yes
             ▼
┌──────────────────────────┐
│  Compute:                │
│  - all_idle (duration)   │
│  - any_playing           │
└────────────┬─────────────┘
             │
      ┌──────┴──────┐
      ▼             ▼
┌───────────┐ ┌───────────────┐
│ Switch ON │ │ Switch OFF    │
│ + all     │ │ + auto-enable │
│ idle?     │ │ + any playing │
└─────┬─────┘ └──────┬────────┘
      │ yes          │ yes
      ▼              ▼
  Turn OFF       Turn ON
  follow         follow
  switch         switch
```

## Features

- Auto-disables follow-me when all players idle beyond a configurable timeout
- Optional auto-enable when any monitored player starts playback
- Mutually exclusive branches prevent toggle conflicts
- Idle duration uses `last_changed` timestamps for accurate timing
- Guards against attribute-only state changes (only reacts to real transitions)
- Input validation prevents execution with unconfigured entities

## Prerequisites

- Home Assistant 2024.10.0 or later
- Music Assistant integration with one or more media players
- An `input_boolean` entity to act as the follow-me toggle

## Installation

1. Copy `music_assistant_follow_me_idle_off.yaml` to `config/blueprints/automation/madalone/`
2. Create automation: **Settings -> Automations -> Create -> Use Blueprint**

## Configuration

### Section 1 -- Core settings

| Input | Default | Description |
|---|---|---|
| Follow music toggle | _(required)_ | The `input_boolean` that gates follow-me behavior |
| Music players to monitor | _(required)_ | One or more Music Assistant `media_player` entities that may hold queues |

### Section 2 -- Behavior

| Input | Default | Description |
|---|---|---|
| Idle minutes before disabling | 15 | Minutes ALL players must be non-playing before the toggle turns OFF |
| Auto-enable on playback | true | When ON, starting playback on any monitored player turns the toggle ON |

## Technical Notes

- **Mode:** `single` / `max_exceeded: silent`
- **Trigger:** State change on any monitored player
- **Idle calculation:** Uses `as_timestamp(now()) - as_timestamp(p.last_changed)` to verify each player has been non-playing for the configured duration
- **Mutual exclusion:** Branch 1 (auto-OFF) requires the switch to be ON; Branch 2 (auto-ON) requires the switch to be OFF -- they can never conflict

## Changelog

- **v2:** Style guide compliance -- modern syntax, aliases, collapsible inputs, header image
- **v1:** Initial version

## Author

**madalone**

## License

See repository for license details.
