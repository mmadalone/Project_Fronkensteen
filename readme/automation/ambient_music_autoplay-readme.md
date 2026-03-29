# Ambient Music Auto-Play (C6)

Automatically starts ambient music when a zone becomes occupied during qualifying context (time of day, routine stage, no active media). Supports multiple source modes: playlist, radio, composer, or taste-auto (genre from music taste profile). Auto-stops playback when the zone goes vacant.

## How It Works

```
┌──────────────────────────────────────────────────┐
│                   TRIGGER                         │
│  FP2 presence sensor: off → on                    │
│  (held for presence_delay, default 2 minutes)     │
└────────────────────────┬─────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────┐
│                 CONDITIONS                        │
│  • Kill switch ON?                                │
│  • Day-of-week matches?                           │
│  • Within time window? (cross-midnight safe)      │
│  • Player not already playing? (if skip enabled)  │
│  • TTS/ducking not active? (if skip enabled)      │
│  • Follow-me not active? (if skip enabled)        │
│  • Bedtime behavior allows?                       │
│  • Focus behavior allows?                         │
│  • Privacy gate passes?                           │
└────────────────────────┬─────────────────────────┘
                         │ all pass
                         ▼
┌──────────────────────────────────────────────────┐
│             RESOLVE EFFECTIVE SOURCE              │
│  Focus ON + focus_playlist → use focus playlist   │
│  Bedtime ON + wind_down → use composer/bedtime    │
│  Otherwise → configured source_mode               │
└────────────────────────┬─────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────┐
│              SET VOLUME + PLAY MUSIC              │
│  ┌────────────┬────────────┬───────────────────┐ │
│  │ playlist   │ radio      │ composer          │ │
│  │ MA URI     │ stream URL │ music_library_play│ │
│  ├────────────┴────────────┴───────────────────┤ │
│  │ taste_auto                                  │ │
│  │ genre from sensor.ai_music_taste_status     │ │
│  └─────────────────────────────────────────────┘ │
└────────────────────────┬─────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────┐
│          AUTO-STOP ON VACANCY (if enabled)        │
│  Wait for presence off (vacancy_delay)            │
│  → media_player.media_stop                        │
│  (timeout: 8 hours)                               │
└──────────────────────────────────────────────────┘
```

## Features

- Presence-triggered ambient music on zone entry with configurable delay
- 4 source modes: playlist (Music Assistant URI), radio (stream URL), composer (AI-generated ambient via pyscript), taste-auto (genre from music taste profile)
- Context-aware source switching: focus mode can redirect to a focus playlist; bedtime mode can switch to wind-down sounds via the composer
- Cross-midnight time window support
- Day-of-week filtering
- Playback protection: skip if player already playing, TTS/ducking active, or music follow-me in progress
- Auto-stop on vacancy with configurable delay (default 5 min)
- Focus mode integration: silent (block music), focus playlist (switch to alternative), or normal (ignore)
- Bedtime integration: skip or switch to wind-down sounds
- Guest mode gate
- Standard privacy gate (off/t1/t2/t3)

## Prerequisites

- Home Assistant 2024.10.0+
- FP2 presence sensor (binary_sensor)
- Media player entity for the target zone
- Pyscript service: `pyscript.music_library_play` (for composer mode)
- `input_boolean` for per-instance kill switch
- `input_boolean.ai_ducking_flag` (playback protection)

## Installation

1. Copy `ambient_music_autoplay.yaml` to `config/blueprints/automation/madalone/`
2. Create automation: **Settings -> Automations -> Create -> Use Blueprint**
3. Create one instance per zone

## Configuration

<details><summary>① Control</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `enable_toggle` | _(required)_ | Per-instance kill switch (input_boolean) |
| `presence_sensor` | _(required)_ | FP2 binary sensor for this zone |
| `target_player` | _(required)_ | The speaker to play music on (e.g. media_player.workshop_sonos) |
| `presence_delay` | `2 minutes` | How long presence must hold before starting music. Should be longer than light delays to feel natural |

</details>

<details><summary>② Music source</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `source_mode` | `playlist` | How to select music: `playlist` (fixed MA playlist), `radio` (internet radio station), `composer` (AI-generated ambient), `taste_auto` (genre from taste profile) |
| `playlist_uri` | `""` | Music Assistant playlist URI (for playlist mode) |
| `radio_station` | `""` | Internet radio stream URL (for radio mode) |
| `composer_agent` | `rick` | Agent name for music_compose (for composer mode) |
| `composer_content_type` | `ambient` | Content type for music_compose (e.g. ambient, wake_melody) |
| `volume_pct` | `25` | Playback volume (5–100%) |

</details>

<details><summary>③ Context filters</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `time_start` | `06:00:00` | Start of the daily active window |
| `time_end` | `22:00:00` | End of the daily window (cross-midnight supported) |
| `run_days` | all days | Run on these days (multi-select: mon–sun) |

</details>

<details><summary>④ Playback protection</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `skip_if_playing` | `true` | Don't start music if the target player is already playing |
| `skip_if_tts_active` | `true` | Don't start music if voice ducking is active (input_boolean.ai_ducking_flag) |
| `auto_stop_vacancy` | `true` | Stop playback when the zone becomes vacant |
| `vacancy_delay` | `5 minutes` | How long vacancy must hold before stopping music |

</details>

<details><summary>⑤ Gates</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `focus_mode_entity` | `input_boolean.ai_focus_mode` | Focus mode entity |
| `focus_behavior` | `silent` | Focus mode behavior: `silent` (no music), `focus_playlist` (switch to focus playlist), `normal` (ignore focus mode) |
| `focus_playlist_uri` | `""` | Alternative playlist for focus mode (only used when focus behavior is "Focus playlist") |
| `guest_mode_entity` | `input_boolean.ai_guest_mode` | Guest mode entity |
| `bedtime_entity` | `input_boolean.ai_bedtime_active` | Bedtime entity |
| `bedtime_behavior` | `skip` | Bedtime behavior: `skip` (no music during bedtime), `wind_down` (play wind-down sounds) |
| `music_follow_me_entity` | `input_boolean.ai_music_follow_me` | Music follow-me entity |
| `skip_if_follow_me` | `true` | Don't start ambient music if music follow-me is actively moving playback between rooms |

</details>

<details><summary>⑥ Privacy</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `privacy_tier` | `off` | Privacy gate tier (off/t1/t2/t3) |
| `privacy_gate_enabled` | `input_boolean.ai_privacy_gate_enabled` | Privacy gate enabled entity |
| `privacy_gate_mode` | `input_select.ai_privacy_gate_mode` | Privacy gate mode entity |
| `privacy_gate_person` | `""` | Person entity for tier suppression lookups |

</details>

## Technical Notes

- **Mode:** `single` / `max_exceeded: silent` -- only one execution per instance at a time
- **Trigger:** FP2 presence sensor `off` -> `on` with configurable `presence_delay` (default 2 minutes)
- **Vacancy wait:** Uses `wait_for_trigger` with an 8-hour timeout; `continue_on_timeout: false` means if the zone stays occupied for 8 hours, music is not stopped (avoids false vacancy)
- **Source resolution:** Focus mode and bedtime mode can override the configured source mode at runtime -- focus switches to `focus_playlist`, bedtime switches to `composer` with bedtime content type
- **Taste auto mode:** Reads `sensor.ai_music_taste_status` attribute `genre_summary` as the search query, defaulting to "ambient" if unavailable
- **Fires `ai_scene_learner_suppress` event:** Not present in this blueprint -- music does not suppress scene learning

## Changelog

- **v1.0.0:** Initial blueprint -- C6 Layer 4

## Author

**madalone**

## License

See [LICENSE](../../LICENSE) in the repository root.
