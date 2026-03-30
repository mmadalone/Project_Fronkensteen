# ElevenLabs Custom TTS — Patched Fork

Patched fork of [Loryan Strant's ElevenLabs Custom TTS](https://github.com/loryanstrant/HA-ElevenLabs-Custom-TTS) (MIT license, forked at **v0.6.3**) with voice mood modulation for Project Fronkensteen.

**HACS auto-updates must be disabled for this component.** It is distributed automatically by the Project Fronkensteen installer when the Voice Pipeline feature group is enabled.

---

## What Was Changed

The upstream component provides multi-profile ElevenLabs TTS with voice selection via Assist Pipelines. This fork adds **voice mood modulation** — the ability to shift each AI persona's voice characteristics throughout the day.

### Added: Voice Mood Modulation (v3 Pivot)

ElevenLabs v3 ignores most `VoiceSettings` parameters (`similarity_boost`, `style`, `speed`). Only two mechanisms actually affect the voice:

1. **Stability slider** — the one `VoiceSettings` parameter v3 respects. Lower values = more expressive/creative, higher = more consistent/robotic.
2. **Audio tags** — text prefixes like `[slurring]`, `[whispers]`, `[excited]` that v3 interprets as performance directions.

This fork injects both at TTS time, per-agent, based on time-of-day schedules managed by the `voice_mood_modulation.yaml` blueprint.

### Changes to `tts.py`

| Section | What Changed |
|---------|-------------|
| `__init__` | Added `self._mood_profile_map = {}` — maps ElevenLabs voice profile names to agent identifiers |
| `async_added_to_hass` | New method. Loads `voice_mood_profile_map.json` at entity init |
| `_load_mood_profile_map_sync` | New static method. Reads `/config/pyscript/voice_mood_profile_map.json` in executor thread |
| `async_get_tts_audio` | Added mood modulation block (lines 208-237). On every TTS call: looks up agent from profile map, reads stability from `input_number.ai_voice_mood_{agent}_stability`, reads tag prefix from `sensor.ai_voice_mood_{agent}_tags`, injects both into the request |
| Option merge order | Changed to: `defaults < profile < mood < per-request overrides` (mood overrides profile stability but per-request overrides everything) |
| Tag injection | Added guard: `if mood_tag_prefix and "[" not in message` — prepends tags only to non-agent text (notifications, announcements). Agent conversation responses already contain their own tags via system prompts. |

### Files Unchanged from Upstream

- `__init__.py` — integration setup, client creation
- `config_flow.py` — multi-profile config flow (upstream feature)
- `const.py` — constants and defaults
- `services.yaml` — service definitions
- `strings.json` — UI translations

---

## How It Works

```
voice_mood_modulation.yaml blueprint (1 instance per agent)
    │  fires hourly + on startup
    │  writes current time block's values to:
    │    input_number.ai_voice_mood_{agent}_stability
    │    sensor.ai_voice_mood_{agent}_tags
    │
    ▼
tts.py (this patched component)
    │  on every TTS call:
    │  1. Looks up voice profile name in voice_mood_profile_map.json
    │  2. Maps profile → agent identifier (e.g., "rick")
    │  3. Reads stability + tags from helpers/sensors
    │  4. Injects stability into VoiceSettings
    │  5. Prepends tag prefix to message text (non-agent only)
    │
    ▼
ElevenLabs API
    stability slider affects voice expressiveness
    audio tags affect performance style
```

### Example — Rick at 10pm

Blueprint writes: stability = 0.20, tags = `[slurring]`

- **Agent conversation response** (already tagged by LLM): `[slurring] listen mi— [burps] your thermostat is set to...` — tag prefix skipped (message contains `[`)
- **Notification announcement** (no tags): `You have a new email from...` → becomes `[slurring] You have a new email from...`

Both get stability 0.20 injected into `VoiceSettings`, making the voice highly expressive/unstable.

---

## Configuration Files

| File | Purpose | Managed By |
|------|---------|------------|
| `/config/pyscript/voice_mood_profile_map.json` | Maps ElevenLabs voice profile names to agent slugs. Key = exact profile name as shown in ElevenLabs, value = agent slug. | User (template provided) |
| `input_number.ai_voice_mood_{agent}_stability` | Current stability value for each agent (0-1). | `voice_mood_modulation.yaml` blueprint |
| `sensor.ai_voice_mood_{agent}_tags` | Current audio tag prefix for each agent. | `voice_mood_modulation.yaml` blueprint |
| `input_boolean.ai_voice_mood_enabled` | Global kill switch. When OFF, all mood modulation is bypassed. | User (dashboard toggle) |

### voice_mood_profile_map.json

```json
{
  "rick sanchez - rock scientist v0.1.2": "rick",
  "quark - kwork v0.6": "quark",
  "kramer - that neighbor v0.0.10": "kramer",
  "deadpool - livepuddle v0.2": "deadpool",
  "doctor portuondo - el doctor v0.01": "doctor_portuondo"
}
```

Keys must match the exact voice profile name as configured in the ElevenLabs Custom TTS integration (case-insensitive matching is applied). Values are agent slugs matching the `voice_mood_modulation.yaml` blueprint instances.

---

## Parallel Mood Path: tts_queue.py

The patched TTS component handles mood for **pipeline-routed TTS** (agent conversations routed through Assist Pipelines). For **non-pipeline TTS** (direct `tts.speak` calls from blueprints/automations), `pyscript/tts_queue.py` injects the same stability + tag prefix before calling the TTS service. Both paths read the same helpers/sensors, so the mood is consistent regardless of how TTS is invoked.

---

## Upstream Attribution

- **Original component**: [HA-ElevenLabs-Custom-TTS](https://github.com/loryanstrant/HA-ElevenLabs-Custom-TTS) by Loryan Strant (@loryanstrant)
- **License**: MIT
- **Forked at**: v0.6.3
- **Upstream features preserved**: Multi-profile voice selection, voice_id passthrough, config flow with profile management, Assist Pipeline voice picker integration
