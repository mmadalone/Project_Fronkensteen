# Speaker Wake — Volume Pulse

Some active speakers and soundbars drop into standby when the signal is silent or too quiet, and only wake when a loud signal arrives. This script blueprint briefly raises a media player's volume (100% by default) for a few seconds to wake them, then restores it. You choose whether it goes back to the volume the player had just before the pulse or to a fixed volume.

## How It Works

```
script called
     │
     ▼
player not set / off / unavailable / unknown? ──yes──► stop (nothing to do)
     │ no
     ▼
work out the restore volume
  ├─ mode = remember AND volume readable AND volume < pulse level ──► current volume
  └─ otherwise ──────────────────────────────────────────────────────► fixed volume
     │
     ▼
volume_set → pulse level (default 100%)
     │
     ▼
wait pulse duration (default 3 s)
     │
     ▼
volume_set → restore volume
```

## Key Design Decisions

### Stranded-pulse guard
If a run is interrupted mid-pulse (scripts reloaded, HA restarted, script stopped), the player is left at the pulse volume. A naive "remember" run would then remember 100% and restore to 100% every time after. So when the remembered volume is already at or above the pulse level, the script restores the fixed volume instead. This also means a player you deliberately keep at 100% (with pulse at 100%) is restored to the fixed volume. Raise the fixed volume if that applies to you.

### `mode: single`
A second call during the pulse would capture the pulse volume as "current". Single mode drops overlapping calls silently.

### Mute is left alone
If the player is muted, the pulse won't reach the speakers. The script won't unmute on its own: an unexpected unmute at 100% is worse than a pulse that didn't wake anything.

## Features

- **Remember or fixed restore**: return to the pre-pulse volume, or always to a set volume
- **Configurable pulse**: volume (1–100%) and duration (1–60 s)
- **Safe on an off player**: exits cleanly instead of erroring
- **Fallback**: remember mode uses the fixed volume when the current volume can't be read

## Prerequisites

- Home Assistant 2024.10.0 or newer
- A `media_player` that supports setting volume (e.g. Kodi)

## Installation

Copy `speaker_wake_volume_pulse.yaml` to `config/blueprints/script/madalone/`, then create a script from it under **Settings → Automations & Scenes → Blueprints**.

## Configuration

### ① Target

| Input | Default | Description |
|---|---|---|
| Media player | — (required) | The player feeding the external speakers. Only volume-settable players are listed. |

### ② Pulse

| Input | Default | Description |
|---|---|---|
| Pulse volume | 100% | Volume used to wake the speakers. Must cross the speakers' auto-wake threshold. |
| Pulse duration | 3 s | How long the pulse volume is held before restoring. |

### ③ Restore

| Input | Default | Description |
|---|---|---|
| Restore mode | Remember current volume | `Remember` returns to the pre-pulse volume; `Fixed` always uses the fixed volume. |
| Fixed volume | 40% | Restore target in Fixed mode and the fallback for Remember mode. |

## Technical Notes

- Volumes are configured in % and converted to HA's 0.0–1.0 `volume_level`.
- The restore volume is captured in a step variable *before* the pulse, so it reflects the volume at call time.
- Any audio playing during the pulse is heard at the pulse volume. Keep the duration as short as your speakers allow.

## Changelog

- **v1.0:** Initial version

## Author

**Madalone + Assistant**

## License

See repository for license details.
