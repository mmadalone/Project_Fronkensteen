# Music Assistant -- Local LLM Enhanced Voice Support

![header](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/mass_llm_enhanced_assist-header.jpeg)

Uses an LLM conversation agent to parse voice commands into structured media queries, then plays them via Music Assistant. Supports area-based and player-based targeting with automatic fallback to a default player, player blacklisting with optional divert, URI shortcuts for direct playlist/station mapping, and playback verification. Originally from the Music Assistant project, with style-guide fixes and enhancements by madalone.

## How It Works

```
┌──────────────────────────┐
│  Voice trigger:          │
│  "Play/Shuffle/Listen to │
│   {query} [in area/on    │
│   player]"               │
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│  Resolve dispatcher /    │
│  conversation agent      │
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│  Send query to LLM with │
│  full prompt (media type,│
│  areas, players, etc.)   │
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│  Parse JSON response     │
│  → media_id, media_type, │
│    artist, album, areas, │
│    players               │
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│  Resolve targets:        │
│  1. Named areas/players  │
│  2. Device area fallback │
│  3. Default player       │
│  Blacklist filtering +   │
│  optional divert         │
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│  URI override check      │
│  (shortcut map)          │
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│  music_assistant.        │
│  play_media              │
│  → verify playback       │
│  → return response       │
└──────────────────────────┘
```

## Features

- Natural language voice commands via LLM parsing (Play, Shuffle, Listen to)
- Area-based and player-based targeting with fuzzy name matching via LLM
- Automatic fallback to device area, then default player
- Player blacklist with optional divert to fallback player
- URI shortcut map bypasses search for known playlists/stations
- Radio mode control (use player settings / always / never)
- Enqueue mode (replace / add / next)
- Playback verification with configurable delay
- AI dispatcher support for dynamic persona selection
- Customizable trigger sentences for multi-language support
- Fully tunable LLM prompt sections

## Prerequisites

- Home Assistant 2024.10.0 or later
- Music Assistant integration with at least one media player
- An LLM conversation agent (or AI dispatcher)

## Installation

1. Copy `mass_llm_enhanced_assist_blueprint_en.yaml` to `config/blueprints/automation/madalone/`
2. Create automation: **Settings -> Automations -> Create -> Use Blueprint**

## Configuration

### Section 1 -- Core settings

| Input | Default | Description |
|---|---|---|
| Use Dispatcher | true | When enabled, AI dispatcher selects persona dynamically |
| Voice Assistant | "Rick" | Assist Pipeline used when dispatcher is disabled |
| Default Player | _(empty)_ | Fallback MA player when no target can be determined |

### Section 2 -- Playback settings

| Input | Default | Description |
|---|---|---|
| Radio Mode | Use player settings | Controls MA radio_mode (use player settings / always / never) |
| Enqueue Mode | replace | How new media is added to the queue (replace / add / next) |
| Playback verification delay | 2 s | Seconds to wait before checking if playback started |

### Section 3 -- Player blacklist & divert

| Input | Default | Description |
|---|---|---|
| Blacklisted players | _(empty)_ | MA players that should NEVER receive music from this automation |
| Enable divert to fallback | false | Redirect to fallback player instead of just dropping the target |
| Divert fallback player | _(empty)_ | The MA player to use when a blacklisted player is excluded |

### Section 4 -- Trigger & response settings

| Input | Default | Description |
|---|---|---|
| Conversation trigger sentences | `(shuffle\|play\|listen to) {query}` | Voice trigger patterns |
| Combine word | "and" | Word joining multiple targets in responses |
| No target response | "No target could be determined..." | Error response text |
| Area response | "Now playing/shuffling ... in ..." | Response template for area targets |
| Player response | "Now playing/shuffling ... on ..." | Response template for player targets |
| Area and Player response | Combined template | Response when both targets are used |

### Section 5 -- LLM prompt tuning

| Input | Default | Description |
|---|---|---|
| Introduction for LLM prompt | _(long default)_ | Sets LLM role and expected JSON output structure |
| Media type LLM prompt | _(long default)_ | Explains 6 media_type values to the LLM |
| Media ID LLM prompt | _(long default)_ | Explains media_id formatting and multi-track patterns |
| Artist and album LLM prompt | _(long default)_ | Optional artist/album fields for search refinement |
| Examples action data LLM prompt | _(long default)_ | Concrete JSON examples for common query types |
| Media description LLM prompt | _(long default)_ | Explains the media_description key |
| Target data LLM prompt | _(long default)_ | Explains target_data for area/player routing |
| Outro for LLM prompt | _(long default)_ | Final instructions ensuring raw JSON output |
| Expose Music Assistant Players | true | Send player names to LLM for fuzzy matching |
| Expose areas with MA Players | true | Send area names to LLM for fuzzy matching |

### Section 6 -- Media URI shortcuts

| Input | Default | Description |
|---|---|---|
| URI override map | _(empty)_ | Maps voice keywords to exact MA URIs (one per line, `keyword=uri`) |

### Section 7 -- Infrastructure

| Input | Default | Description |
|---|---|---|
| Dispatcher enabled entity | `input_boolean.ai_dispatcher_enabled` | Boolean that enables the AI agent dispatcher |

## Technical Notes

- **Mode:** `parallel` / `max: 10`
- **Trigger:** Conversation trigger matching configurable sentence patterns
- **LLM output:** Expects raw JSON (no code fences) with `action_data`, `media_description`, and `target_data` keys
- **Safe-split:** Area and player names use `|||` delimiter internally because names may contain commas
- **integration_entities() guards:** All calls use `| default([])` to prevent cascade failure if MA is temporarily unavailable
- **Boolean coercion:** All boolean inputs use `| bool` guards to prevent string-coercion bugs across serialization boundaries
- **Blacklist divert:** When a blacklisted player is the only target and divert is enabled, it is replaced with the divert fallback player

## Changelog

- **v19:** Fix TemplateSyntaxError -- move Jinja comments out of mid-expression filter chains
- **v18:** Restore `| reject('none')` guard on `area_list` in step 9 response assembly
- **v17:** Add missing `| bool` guard on `divert_enabled` in blacklist divert logic; complete `| bool` guards on all expose conditionals
- **v16:** Add `| bool` guards at all boolean consumption points; add DO-NOT-HOIST warning on play_succeeded
- **v15:** Add `| default([])` guards on all `integration_entities()` calls
- **v14:** Defensive template hardening -- default guards on trigger.sentence, area_entities() fallback
- **v13:** Fix regex injection in fuzzy target matching, explicit from_json guard
- **v12:** Style guide compliance -- conversation_agent selector, section conventions

## Author

**Music Assistant Project** (style-guide fixes by madalone)

## License

See repository for license details.
