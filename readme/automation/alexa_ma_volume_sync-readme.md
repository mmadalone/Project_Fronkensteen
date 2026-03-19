# Alexa / Music Assistant Volume Sync

![header](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/alexa_ma_volume_sync_blueprint-header.jpeg)

Keeps the volume of paired media players in sync -- bidirectionally. Change the volume on either device and its partner follows. Supports two sync modes: **Paired** (1:1 by list order) and **Group** (all devices sync together). Includes mute sync, duck guard integration with I-22 manual override support, and ESP boot protection for Voice PE satellites.

## How It Works

```
┌─────────────────────────────────────┐
│  List A volume/mute changes         │
│  List B volume/mute changes         │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  Gates:                             │
│  ├─ Valid target(s) found?          │
│  ├─ Source device available?        │
│  ├─ Ducking gate (I-22 override)    │
│  ├─ Ducking grace period elapsed?   │
│  ├─ Sync direction allowed?        │
│  ├─ Boot/mute protection pass?     │
│  └─ Device playing? (optional)     │
└──────────────┬──────────────────────┘
               │
        ┌──────┴──────┐
        ▼             ▼
┌──────────────┐ ┌──────────────────┐
│  Mute sync   │ │  Volume sync     │
│  to targets  │ │  ├─ Tolerance    │
└──────────────┘ │  ├─ Cooldown     │
                 │  ├─ Re-read vol  │
                 │  ├─ Sync mute    │
                 │  ├─ Sync volume  │
                 │  └─ Duck snap    │
                 └──────────────────┘
```

## Features

- Bidirectional volume sync between two lists of media players
- Paired mode (1:1 matching by list order) or Group mode (all devices sync together)
- Mute state synchronization
- Configurable sync direction (both ways, A to B only, B to A only)
- Volume tolerance threshold to prevent unnecessary updates
- Cooldown delay to absorb rapid volume changes
- Ducking flag integration -- pauses sync during TTS playback
- I-22 manual override -- notifies duck manager of user adjustments during ducking
- Ducking grace period after TTS finishes
- ESP boot protection -- ignores zero-volume reports from freshly booted devices
- Physical mute switch detection for Voice PE satellites
- Optional "only sync when playing" filter
- Duck guard snapshot updates after volume sync

## Prerequisites

- Home Assistant 2024.10.0+
- Media player entities (Alexa, Music Assistant, Sonos, ESP, etc.)
- An `input_boolean` entity for the ducking flag
- (Optional) ESPHome Voice PE satellites with physical mute switches

## Installation

1. Copy `alexa_ma_volume_sync.yaml` to `config/blueprints/automation/madalone/`
2. Create automation: **Settings -> Automations -> Create -> Use Blueprint**

## Configuration

<details>
<summary><strong>Section 1 -- Device Pairing</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| List A -- media players | `[]` | First group of media players (e.g. Alexa Echo devices). Order must match List B in paired mode. |
| List B -- media players | `[]` | Second group of media players (e.g. Music Assistant speakers). Order must match List A in paired mode. |

</details>

<details>
<summary><strong>Section 2 -- Sync Settings</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| Sync mode | `paired` | Paired (1:1 matching) or Group (all devices sync together). |
| Ducking flag | _(required)_ | `input_boolean` used by the Voice PE duck/restore system. |
| Ducking grace period | `3` s | Seconds to ignore volume changes after ducking ends. |
| Allow manual override during ducking | `true` | When enabled, manual volume changes during ducking notify the duck manager (I-22). |
| Sync direction | `both` | Both ways, A->B only, or B->A only. |
| Volume tolerance | `3` % | Minimum volume difference before sync fires. |
| Sync cooldown | `1` s | Minimum time between syncs; absorbs rapid changes. |
| Only sync when playing | `false` | If enabled, sync only fires when at least one device is playing. |

</details>

<details>
<summary><strong>Section 3 -- ESP Boot Protection</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| ESP physical mute switches | `[]` | Hardware mute switch entities for Voice PE satellites, same order as List B. |
| Boot protection window | `60` s | Seconds after a device comes back from unavailable to ignore zero-volume reports. |

</details>

## Technical Notes

- **Mode:** `queued` (max 4, silent on overflow)
- After the cooldown delay, the source volume is re-read to capture the final level after rapid changes
- Boot protection and mute switch checks only apply to zero-volume events -- non-zero volume always syncs
- Duck guard snapshot is updated for each target after volume sync when ducking is active
- Works with any `media_player` entity -- Alexa, Sonos, ESP, Music Assistant, etc.

## Changelog

No versioned changelog in blueprint description. Current state includes bidirectional volume/mute sync, paired and group modes, ducking integration with I-22 manual override, ESP boot protection, and duck guard snapshot updates.

## Author

**madalone**

## License

See repository for license details.
