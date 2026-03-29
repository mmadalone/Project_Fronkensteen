![Voice -- Wake Guard Cleanup (Helper Script)](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/voice_wake_guard_cleanup-header.jpeg)

# Voice -- Wake Guard Cleanup (Helper Script)

Reusable stop/cleanup sequence for the wake-up-guard blueprint. Stops TTS playback, optionally announces via Assist Satellite, waits for audio drain, restores volume, and resets snooze/stop toggles. Called from stop, second-snooze, and post-snooze-stop paths in the wake-up-guard blueprint.

## How It Works

```
Called from wake-up-guard blueprint
(stop / snooze-stop / second-snooze paths)
                |
                v
  ┌─────────────────────────────┐
  │ 1) Stop TTS playback        │
  │    media_player.media_stop  │
  └───────────┬─────────────────┘
              |
              v
  ┌─────────────────────────────────┐
  │ 2) Satellite entity provided?   │
  │   YES → announce via satellite  │
  │   NO  → skip                    │
  └───────────┬─────────────────────┘
              |
              v
  ┌─────────────────────────────┐
  │ 3) Wait for audio buffer    │
  │    drain (configurable)     │
  └───────────┬─────────────────┘
              |
              v
  ┌─────────────────────────────┐
  │ 4) Restore speaker volume   │
  │    + duck snapshot update   │
  └───────────┬─────────────────┘
              |
              v
  ┌─────────────────────────────┐
  │ 5) Reset snooze & stop      │
  │    toggles to OFF           │
  └─────────────────────────────┘
```

## Features

- Reusable cleanup sequence -- eliminates duplicated stop logic across multiple blueprint paths
- Optional Assist Satellite announcement (skipped if entity is empty)
- Configurable audio drain delay before volume restore
- Duck guard integration -- updates volume snapshot after restore when ducking is active
- Resets both snooze and stop toggles in a single call
- All non-critical steps use `continue_on_error: true`

## Prerequisites

- Home Assistant with media player entities
- Assist Satellite integration (optional -- for voice confirmation)
- `input_boolean` helpers for snooze and stop flags (created by wake-up-guard blueprint)
- Duck guard system (optional -- `input_boolean.ai_ducking_flag` and `input_boolean.ai_duck_guard_enabled`)

## Installation

1. Copy `voice_wake_guard_cleanup.yaml` to `config/blueprints/script/madalone/`
2. Create script: **Settings -> Automations & Scenes -> Scripts -> Add -> Use Blueprint**

## Configuration

<details>
<summary><strong>① Infrastructure</strong></summary>

| Input | Default | Description |
|---|---|---|
| `ducking_flag` | `input_boolean.ai_ducking_flag` | Boolean indicating audio ducking is active |
| `duck_guard_enabled` | `input_boolean.ai_duck_guard_enabled` | Boolean that enables the duck guard system |

</details>

### Runtime Fields (passed by caller)

| Field | Required | Default | Description |
|---|---|---|---|
| `tts_output_player` | Yes | -- | Speaker to stop and restore volume on |
| `assist_satellite_entity` | No | `""` | Satellite for voice confirmation; empty string to skip |
| `satellite_message` | No | `"ok, stopping the wake-up alarm."` | Message for the satellite to speak |
| `tts_volume_after` | No | `0.4` | Volume level to restore after cleanup |
| `stop_restore_delay` | No | `1` | Seconds to wait for audio buffer drain before restoring volume |
| `snooze_toggle` | Yes | -- | `input_boolean` entity for the snooze flag |
| `stop_toggle` | Yes | -- | `input_boolean` entity for the stop flag |

## Technical Notes

- **Mode:** `single`, `max_exceeded: silent`
- **Version:** 1.0
- This is a helper script -- not intended to be called directly by users or LLMs; called internally by the wake-up-guard blueprint
- Duck snapshot update is conditional: only fires when both `duck_guard_enabled` and `ducking_flag` are ON
- Toggle reset uses `continue_on_error: true` so partial failures don't block cleanup
- Audio drain delay prevents volume restore from cutting off the last TTS syllable

## Changelog

- **v1.0** -- Initial version; extracted from wake-up-guard blueprint stop paths

## Author

**Madalone + Assistant**

## License

See repository for license details.
