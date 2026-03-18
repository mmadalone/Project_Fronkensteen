# Music Assistant -- Follow me (multi-room advanced)

![header](https://raw.githubusercontent.com/mmadalone/HA-Master-Repo/main/images/header/music_assistant_follow_me_multi_room_advanced-header.jpeg)

Presence-driven follow-me for Music Assistant queues across multiple zones. Transfers the active queue to whichever room you walk into, with priority ordering, anti-flicker, cooldown, playback protection, source-occupied detection, optional pre/post announcements, and a TTS duration filter to ignore short clips. Supports separate TTS speakers for pre- and post-transfer announcements to avoid collisions with music playback.

## How It Works

```
┌──────────────────────────────┐
│  Presence sensor turned ON   │
│  (after min hold time)       │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│  CONDITIONS:                 │
│  - Follow switch ON          │
│  - Persons home (optional)   │
│  - Cooldown elapsed          │
│  - Voice guard inactive      │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│  Resolve target/source       │
│  players and indices         │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│  GATES:                      │
│  - Music playing or paused   │
│  - Valid target != source    │
│  - Source in allowed list    │
│  - Source not in blacklist   │
│  - Source room not occupied  │
│  - Priority anchor check    │
│  - Target not already       │
│    playing                   │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│  Pre-transfer announcement   │
│  (optional script call)      │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│  Delay → Transfer queue      │
│  (auto_play based on state)  │
│  → Post-transfer settle      │
└──────────────┬───────────────┘
               │
         ┌─────┴─────┐
         ▼           ▼
    ┌─────────┐ ┌──────────┐
    │ SUCCESS │ │ FAILURE  │
    │ Cooldown│ │ Announce │
    │ stamp   │ │ failure  │
    │ Silence │ │ (opt.)   │
    │ others  │ └──────────┘
    │ Post-   │
    │ announce│
    └─────────┘
```

## Features

- Presence-driven queue transfer via parallel-array mapping (sensor[N] -> player[N])
- Priority ordering -- first sensor in list has highest priority
- Priority anchor prevents downgrade moves while high-priority zone is occupied
- Source-occupied gate prevents stealing music from another listener
- Target playback protection skips transfer if target is already playing
- Allowed/excluded source player lists (whitelist + blacklist)
- Configurable anti-flicker (minimum presence hold time before triggering)
- Global cooldown between transfers with `input_datetime` helper
- Configurable post-transfer settling delay for slow backends
- Separate pre-transfer and post-transfer TTS speakers per zone
- Follow paused music (transfers queue without auto-play)
- TTS duration filter ignores short clips (configurable threshold)
- Silence other players after transfer (exclusive room mode)
- Voice assistant guard blocks during active TTS/voice
- Person gate restricts follow-me to when specific people are home
- Transfer success verification with failure announcement support
- `continue_on_error` on all non-critical service calls

## Prerequisites

- Home Assistant 2024.10.0 or later
- Music Assistant integration with multiple media players
- One binary sensor per zone for presence detection
- An `input_boolean` as the follow-me toggle
- (Optional) `input_datetime` helper for cooldown tracking
- (Optional) Announcement scripts for pre/post transfer TTS

## Installation

1. Copy `music_assistant_follow_me_multi_room_advanced.yaml` to `config/blueprints/automation/madalone/`
2. Create automation: **Settings -> Automations -> Create -> Use Blueprint**

## Configuration

### Section 1 -- Core setup

| Input | Default | Description |
|---|---|---|
| Follow music toggle | _(required)_ | Global on/off switch for follow-me |
| Presence sensors | _(required)_ | Binary sensors in priority order (first = highest) |
| Music Assistant players | _(required)_ | MA players in same order as presence sensors |
| TTS players for pre-transfer | _(empty)_ | Hardware speakers for pre-transfer announcements (same order) |
| TTS players for post-transfer | _(empty)_ | Hardware speakers for post-transfer announcements (same order) |

### Section 2 -- Persons gate

| Input | Default | Description |
|---|---|---|
| Require persons to be home | false | Only run when selected persons are home |
| Persons | _(empty)_ | Person entities that must be home |

### Section 3 -- Playback filters

| Input | Default | Description |
|---|---|---|
| Only follow when playing | true | Only transfer when music is actively playing/paused |
| Follow paused music | false | Include paused sessions as transfer candidates |
| Min media duration | 20 s | Ignore playback shorter than this (filters TTS clips) |
| Treat unknown duration as music | true | Count media_duration=0 as music (good for streams) |
| Skip if target already playing | true | Don't hijack existing sessions |
| Skip if source room occupied | true | Don't steal music from occupied rooms |
| Allowed source players | _(empty)_ | Whitelist of allowed source players |
| Excluded source players | _(empty)_ | Blacklist of excluded source players |
| Silence other players after transfer | false | Stop all non-target players after transfer |

### Section 4 -- Priority & timing

| Input | Default | Description |
|---|---|---|
| Enforce priority anchor | false | Prevent moves from high to low priority while source has presence |
| Min zone presence time | 0 s | Hold time before triggering follow-me |
| Delay before transfer | 0 s | Delay between pre-announcement and transfer |
| Cooldown after transfer | 0 s | Minimum seconds between successful transfers |
| Cooldown helper | _(empty)_ | `input_datetime` for cooldown tracking |
| Post-transfer settling delay | 2 s | Wait time before checking transfer success |

### Section 5 -- Announcements

| Input | Default | Description |
|---|---|---|
| Run pre-transfer announcement | false | Call script before moving queue |
| Pre-transfer script | _(empty)_ | Script entity for pre-transfer announcement |
| Run post-transfer announcement | true | Call script after moving queue |
| Post-transfer script | _(empty)_ | Script entity for post-transfer announcement |
| Announce transfer failures | true | Call post-transfer script with failure context on errors |

### Section 6 -- Safety

| Input | Default | Description |
|---|---|---|
| Voice assistant guard | _(empty)_ | Boolean/sensor that blocks follow-me during voice activity |

## Technical Notes

- **Mode:** `restart` / `max_exceeded: silent`
- **Trigger:** Presence sensor turns ON with configurable hold time (`for:` duration)
- **Parallel arrays:** Presence sensors, target players, TTS pre-players, and TTS post-players must be in matching order -- index N maps across all lists
- **Transfer auto_play:** When music is actively playing, transfers with `auto_play: true`; when only paused, uses `auto_play: false`
- **Success detection:** After settling delay, checks if target player state is in `['playing', 'paused', 'buffering']`
- **Blacklist after whitelist:** Excluded source players filter runs after allowed source players filter

## Changelog

- **v12:** Consistency pass -- added `| bool` filter to all six flag checks in condition templates
- **v11:** Post-audit hardening -- `continue_on_error: true` on all non-critical calls; configurable post-transfer settling delay
- **v10:** Collapsible section compliance -- collapsed keys, replaced null defaults with empty strings
- **v9:** Source-occupied gate -- don't transfer away from rooms with presence
- **v8:** Style guide compliance -- header image, min_version bump, trigger alias, box-style dividers

## Author

**madalone**

## License

See repository for license details.
