# ElevenLabs Custom TTS — Patched Fork

Patched fork of [Loryan Strant's ElevenLabs Custom TTS](https://github.com/loryanstrant/HA-ElevenLabs-Custom-TTS) (MIT license), **rebased onto v0.8.2** on 2026-10-18. It adds the three things Project Fronkensteen's voice stack depends on: streaming generation, a satellite lead-in pre-roll, and voice mood modulation.

**Do not update this component through HACS.** A HACS update replaces the whole folder and removes the patches; that happened with 0.8.2 on 2026-10-17. The component is installed by the Project Fronkensteen installer when the Voice Pipeline feature group is enabled. To take a new upstream release, port the patches onto it.

---

## What This Fork Changes

Everything is in `tts.py`, plus the `leadin_1600ms.mp3` asset.

| Change | Why |
|--------|-----|
| **Streaming** — `async_stream_tts_audio` via `text_to_speech.stream()` | The buffered endpoint renders the whole clip before sending a byte, so time-to-first-byte grows with the text (4.4 s for 195 characters). The `/stream` endpoint's first chunk arrives in about 0.8 s regardless of length. A reply that yields no audio **raises** instead of returning, so HA never caches a silent clip under the deterministic key. |
| **Satellite lead-in** — a 1.6 s silent MP3 yielded first | The ESPHome Voice PE fabricates "finished speaking" if no audio has started 2 s after HA hands it the URL, then re-opens the microphone over the reply. ffmpeg's MP3 demuxer holds output until about 1.4 s of audio has arrived. Sent only when the caller asked for a non-`wav` `preferred_format` (the satellite announcement path), so Sonos, Alexa and notifications are untouched. Kill switch: `input_boolean.ai_tts_leadin_enabled`. |
| **Voice mood** — per-agent stability and audio-tag prefix | See below. |
| **Option precedence** — defaults < profile < mood < genuine per-call overrides | HA merges `default_options` into every call; merged last, they overrode the profile's model, forcing `eleven_multilingual_v2` and making v3 tags like `[exhales]` get read aloud. With a profile, only values that differ from the defaults count as overrides. Upstream 0.8.2 instead ignores per-call options when a profile is used, which would drop the mood values `tts_queue.py` passes. |
| **Profile resolution** | Case-insensitive profile match; default voice is the first configured profile; the voice picker is hidden (`None`) when no profiles exist. |
| **Streaming deadline** | 120 s total, enforced per await on ElevenLabs. A timeout context spanning `yield`s would fire inside whatever HA's consumer task was doing between chunks. |

**Unchanged from upstream v0.8.2:** `__init__.py`, `config_flow.py`, `const.py`, `services.yaml`, `strings.json`, `translations/`, `manifest.json`. Earlier versions of this fork also widened the model list and pinned `elevenlabs==2.51.0`; 0.8.0 made both unnecessary (a dropdown of the account's models, and `elevenlabs>=2.51.0,<3`).

### Voice Mood Modulation (v3)

ElevenLabs v3 ignores most `VoiceSettings` parameters (`similarity_boost`, `style`, `speed`). Only two mechanisms actually affect the voice:

1. **Stability slider** — the one `VoiceSettings` parameter v3 respects. Lower values = more expressive/creative, higher = more consistent/robotic.
2. **Audio tags** — text prefixes like `[slurring]`, `[whispers]`, `[excited]` that v3 interprets as performance directions.

This fork injects both at TTS time, per-agent, based on time-of-day schedules managed by the `voice_mood_modulation.yaml` blueprint. The map and the lead-in clip are loaded once in `async_added_to_hass` (off the event loop); `_voice_mood()` reads the agent's helpers on every call, and the tag prefix is only added when the text has no `[` tags of its own (agent replies already carry tags from their system prompts).

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
- **Based on**: v0.8.2 (rebased 2026-10-18; earlier bases v0.6.3 and v0.7.0)
- **Upstream features preserved**: multi-profile voice selection, voice_id passthrough, config flow with profile management and the model dropdown, Assist Pipeline voice picker, and 0.8.x's fixes (an `asyncio` timeout instead of the broken `async_timeout` timer, errors raised as `HomeAssistantError` with ElevenLabs' explanation, the API-key fingerprint `unique_id` with its config-entry v2 migration, and no `language_code` for models that reject it)
