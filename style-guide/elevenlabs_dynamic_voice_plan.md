# ElevenLabs Dynamic Voice Settings — Implementation Plan

**Option B: Full HACS Custom Migration + Dynamic Voice Modulation**

**Status:** COMPLETE (v3 pivot)
**Date:** 2026-03-24
**Risk Level:** Low (v3 tags are text-only, stability is the only API param)
**Completed in:** 1 session

> **v3 Pivot (Phase 5c):** ElevenLabs v3 ignores `similarity_boost`, `style`, and `speed`
> VoiceSettings. Voice modulation in v3 works through **audio tags** in text (`[slurring]`,
> `[whispers]`, `[excited]`, etc.) and the **stability** slider (the one working param).
> The system was slimmed to: stability helpers + tag prefix helpers per agent.
> Agent conversation responses already inject their own tags via system prompts —
> the mood system only adds tag prefixes for **non-agent TTS** (notifications,
> announcements, briefings) routed through `tts_queue.py`.  

---

## Executive Summary

Migrate all five character voices from the official HA core ElevenLabs integration
(`tts.elevenlabs_*_text_to_speech`) to the HACS custom component
(`tts.elevenlabs_custom_tts`) with named voice profiles. This enables per-request
dynamic voice settings (stability, similarity_boost, style, speed, speaker_boost)
driven by time-of-day Jinja formulas — making the *voice itself* shift mood
throughout the day, not just the words.

---

## Why Option B Over Option A

- **Unified integration:** One TTS component to maintain, configure, and debug.
- **Dynamic settings everywhere:** Blueprint TTS *and* voice pipeline conversations
  both benefit from per-character voice profiles.
- **Voice profiles:** Named profiles ("Rick Sanchez", "Quark", etc.) map cleanly to
  the existing multi-agent architecture.
- **Future-proof:** Any new ElevenLabs API feature only needs updating in one place.

## Current State Inventory

### TTS Entities in Use (Official HA Core)

| Character         | TTS Entity                                  | Used In                                                |
|-------------------|---------------------------------------------|--------------------------------------------------------|
| Rick Sanchez      | `tts.elevenlabs_text_to_speech`             | Pipelines, agent_escalation, theatrical_mode, voice_handoff, reactive_banter, voice maps, tts_queue |
| Quark             | `tts.elevenlabs_quark_text_to_speech`       | Same as above                                          |
| Kramer            | `tts.elevenlabs_kramer_text_to_speech`      | Same as above                                          |
| Deadpool (Deepee) | `tts.deepee_text_to_speech`                 | Same as above (NOTE: may not be ElevenLabs — verify)   |
| Dr. Portuondo     | `tts.dr_portuondo_text_to_speech`           | Same as above (NOTE: may be HA Cloud — verify)         |

### Voice Maps (hardcoded semicolon-delimited strings)
Found in: `theatrical_mode.yaml`, `reactive_banter.yaml`, `voice_handoff.yaml`,
`automations.yaml` (instances), `agent_escalation.yaml`

Default pattern:
```
rick=tts.elevenlabs_text_to_speech;quark=tts.elevenlabs_quark_text_to_speech;
deadpool=tts.deepee_text_to_speech;kramer=tts.elevenlabs_kramer_text_to_speech;
doctor portuondo=tts.dr_portuondo_text_to_speech
```

### HACS Custom Component (Already Installed)
- Location: `custom_components/elevenlabs_custom_tts/`
- Entity: `tts.elevenlabs_custom_tts`
- Supports per-request: `voice`, `voice_profile`, `model_id`, `stability`,
  `similarity_boost`, `style`, `speed`, `use_speaker_boost`, `apply_text_normalization`
- Voice profiles stored in config entry options
- Model: `eleven_multilingual_v2` (default)

### tts_queue.py (Pyscript)
- Calls `tts.speak` with `entity_id=voice` (the character's TTS entity)
- Only passes `options: {"voice": voice_id}` when override present
- Has ElevenLabs credit gating, fallback to HA Cloud
- Strips `[bracket tags]` via regex when `ai_tts_strip_stage_directions` is on

### Mannerism Tags
Currently working in voice pipeline path (bypasses tts_queue). Getting stripped
in the tts_queue path. This plan addresses both paths.

---

## Architecture: Target State

### Single HACS Entity with Named Voice Profiles

All five characters route through `tts.elevenlabs_custom_tts`. Each character
has a named voice profile containing their ElevenLabs voice ID + baseline
settings. Dynamic per-request overrides layer time-of-day modulation on top.

For Deadpool and Dr. Portuondo: verify whether they use ElevenLabs voices or
different providers (Deepee entity name suggests maybe). If non-ElevenLabs,
they stay on their current entities and are excluded from this migration.

### Voice Profile Definitions (HACS Config Entry)

```yaml
voice_profiles:
  "Rick Sanchez":
    voice: "<rick_voice_id>"        # From current official integration config
    model_id: "eleven_multilingual_v2"
    stability: 0.45
    similarity_boost: 0.75
    style: 0.15
    speed: 1.0
    use_speaker_boost: true
  "Quark":
    voice: "<quark_voice_id>"
    model_id: "eleven_multilingual_v2"
    stability: 0.55
    similarity_boost: 0.80
    style: 0.10
    speed: 1.05
    use_speaker_boost: true
  "Kramer":
    voice: "<kramer_voice_id>"
    model_id: "eleven_multilingual_v2"
    stability: 0.35
    similarity_boost: 0.70
    style: 0.25
    speed: 1.10
    use_speaker_boost: true
```

NOTE: Actual voice IDs must be extracted from the current official integration
config entries (Settings → Devices & Services → ElevenLabs → each instance).

### Dynamic Voice Settings — Time-of-Day Modulation

Same Jinja `now().hour` pattern used in personality prompts, but outputting
voice parameters. Implemented as template sensors or inline Jinja in tts_queue.

#### Rick Sanchez — Voice Mood Map

| Time Block     | Personality State              | stability | style | speed | similarity |
|----------------|--------------------------------|-----------|-------|-------|------------|
| 00:00–08:59    | Severely hungover              | 0.25      | 0.05  | 0.85  | 0.65       |
| 09:00–11:59    | Hungover but functional        | 0.35      | 0.10  | 0.90  | 0.70       |
| 12:00–16:59    | Casually drinking, slight slur | 0.45      | 0.15  | 0.95  | 0.75       |
| 17:00–20:59    | Noticeably drunk, slurring     | 0.30      | 0.25  | 0.88  | 0.70       |
| 21:00–23:59    | Completely hammered            | 0.20      | 0.35  | 0.80  | 0.60       |

Design rationale:
- Low stability = more vocal variation = sounds less controlled (drunk/hungover)
- High style = more expressive delivery = emotional range
- Slow speed = slurring, dragging words
- Low similarity = voice drifts from "clean" baseline = messier delivery

#### Quark — Voice Mood Map

| Time Block     | Personality State              | stability | style | speed | similarity |
|----------------|--------------------------------|-----------|-------|-------|------------|
| 00:00–08:59    | Barely open, reluctant         | 0.50      | 0.05  | 0.90  | 0.80       |
| 09:00–11:59    | Warming up, getting sharp      | 0.55      | 0.10  | 0.98  | 0.80       |
| 12:00–16:59    | Peak hours — charming, fast    | 0.60      | 0.20  | 1.08  | 0.85       |
| 17:00–21:59    | Winding down, candid           | 0.55      | 0.12  | 0.95  | 0.80       |
| 22:00–23:59    | Late night, philosophical      | 0.45      | 0.08  | 0.88  | 0.78       |

Design rationale:
- High stability = clean, professional delivery = sharp Ferengi salesman
- Peak hours: faster speed, higher style = persuasive energy
- Late night: lower everything = mask slipping, more genuine/tired

#### Kramer — Voice Mood Map

| Time Block     | Personality State              | stability | style | speed | similarity |
|----------------|--------------------------------|-----------|-------|-------|------------|
| 00:00–08:59    | Asleep / barely conscious      | 0.30      | 0.05  | 0.85  | 0.70       |
| 09:00–11:59    | Bursting in with ideas         | 0.30      | 0.30  | 1.15  | 0.70       |
| 12:00–16:59    | Full Kramer energy             | 0.25      | 0.35  | 1.20  | 0.65       |
| 17:00–21:59    | Scheme mode                    | 0.35      | 0.25  | 1.05  | 0.72       |
| 22:00–23:59    | Winding down, oddly calm       | 0.45      | 0.10  | 0.92  | 0.75       |

Design rationale:
- Kramer is always unstable vocally — low stability baseline
- Peak: fastest speed + highest style = manic energy
- High style throughout daytime = wild expressiveness

NOTE: Deadpool and Dr. Portuondo mood maps TBD — first verify their TTS provider.
If Deadpool is on a different TTS (entity name `tts.deepee_text_to_speech` doesn't
follow the `elevenlabs_` pattern) and Portuondo is HA Cloud, they're excluded from
dynamic settings but keep their current entities in voice maps.

---

## Implementation Phases

### Phase 0 — Pre-Flight Verification (1 session, low risk)

Before touching anything, verify these unknowns:

- [ ] **Extract voice IDs** from each official ElevenLabs integration config entry.
      Settings → Devices & Services → ElevenLabs → each instance → note voice_id,
      model_id, and current voice settings (stability, similarity, style, speed).
- [ ] **Verify Deadpool provider:** Is `tts.deepee_text_to_speech` an ElevenLabs
      entity or a different TTS? Check integration entries and entity registry.
- [ ] **Verify Dr. Portuondo provider:** Is `tts.dr_portuondo_text_to_speech`
      ElevenLabs or HA Cloud? (pyscript common_utilities.py shows
      `"portuondo": "ha_cloud"` in budget mode — but what's the primary?)
- [ ] **Test HACS pipeline compatibility:** Configure one test voice profile in
      the HACS component. Create a test Assist pipeline pointing to
      `tts.elevenlabs_custom_tts`. Verify the pipeline selects the correct
      profile and generates audio. This is the critical go/no-go gate.
- [ ] **Test `tts.speak` with dynamic options:** From dev tools, call tts.speak
      on `tts.elevenlabs_custom_tts` with voice_profile + overridden stability.
      Confirm the override takes effect (listen for audible difference).
- [ ] **Mannerism tag behavior:** Test sending `[burps]` and `[chuckles slyly]`
      through the HACS entity. Confirm ElevenLabs handles them as performative
      cues (as they currently do on the official entity).

**GO/NO-GO:** If the pipeline test fails (voice profile not forwarded, wrong
voice selected, or no audio), fall back to Option A (hybrid approach). Do not
proceed with Phase 1.

### Phase 1 — HACS Voice Profiles + Template Sensors (1 session, medium risk)

#### 1a. Configure Voice Profiles in HACS Component
Add all ElevenLabs characters as named voice profiles via the integration's
options flow (Settings → Devices & Services → ElevenLabs Custom TTS → Configure).
Each profile gets the voice_id + baseline settings from the mood maps above.

#### 1b. Create Dynamic Voice Settings Template Sensors
New template sensors in `packages/` or a dedicated `ai_voice_dynamics.yaml`:

```yaml
template:
  - sensor:
      - name: "Rick Voice Settings"
        unique_id: rick_voice_dynamics
        state: "active"
        attributes:
          voice_profile: "Rick Sanchez"
          stability: >-
            {% set h = now().hour %}
            {% if h < 9 %}0.25
            {% elif h < 12 %}0.35
            {% elif h < 17 %}0.45
            {% elif h < 21 %}0.30
            {% else %}0.20{% endif %}
          style: >-
            {% set h = now().hour %}
            {% if h < 9 %}0.05
            {% elif h < 12 %}0.10
            {% elif h < 17 %}0.15
            {% elif h < 21 %}0.25
            {% else %}0.35{% endif %}
```

(One sensor per character. Full Jinja for all five settings per character.)

#### 1c. Checkpoint
- Template sensors rendering correctly in dev tools
- Each sensor outputs the expected values for current time block
- HACS profiles configured and accessible via tts.speak test calls
- Create HA git checkpoint before proceeding

### Phase 2 — tts_queue.py Migration (1 session, medium risk)

#### 2a. Modify `_play_tts()` in tts_queue.py
Current signature:
```python
async def _play_tts(text, speaker, voice, volume_level=None, voice_id=""):
```
Change `tts.speak` call to use HACS entity with dynamic options:

```python
# Before (current):
kwargs = dict(entity_id=voice, media_player_entity_id=s, message=text)
if voice_id:
    kwargs["options"] = {"voice": voice_id}

# After (new):
agent = _voice_to_agent(voice)  # extracts "rick", "quark", etc.
dynamic_opts = _get_dynamic_voice_opts(agent)  # reads template sensor
kwargs = dict(
    entity_id="tts.elevenlabs_custom_tts",
    media_player_entity_id=s,
    message=text,
)
kwargs["options"] = dynamic_opts
```

#### 2b. New Helper Function: `_get_dynamic_voice_opts(agent)`

```python
_AGENT_SENSOR_MAP = {
    "rick": "sensor.rick_voice_settings",
    "quark": "sensor.quark_voice_settings",
    "kramer": "sensor.kramer_voice_settings",
    # Add deadpool/portuondo if they use ElevenLabs
}

def _get_dynamic_voice_opts(agent: str) -> dict:
    """Read dynamic voice settings from template sensor for agent."""
    sensor = _AGENT_SENSOR_MAP.get(agent)
    if not sensor:
        return {}  # Non-ElevenLabs agent, no options
    try:
        attrs = state.getattr(sensor) or {}
        opts = {
            "voice_profile": attrs.get("voice_profile", ""),
            "stability": float(attrs.get("stability", 0.5)),
            "similarity_boost": float(attrs.get("similarity_boost", 0.75)),
            "style": float(attrs.get("style", 0.0)),
            "speed": float(attrs.get("speed", 1.0)),
        }
        return {k: v for k, v in opts.items() if v}  # strip empties
    except Exception:
        return {}  # fail-open with defaults
```

#### 2c. Preserve Non-ElevenLabs Routing
If agent is Deadpool (non-ElevenLabs) or Portuondo (HA Cloud), _play_tts
must still use their original entity_id, not the HACS one. Add a guard:

```python
if agent in _AGENT_SENSOR_MAP:
    # ElevenLabs character → route through HACS with dynamic opts
    entity = "tts.elevenlabs_custom_tts"
    opts = _get_dynamic_voice_opts(agent)
else:
    # Non-ElevenLabs character → keep original entity, no dynamic opts
    entity = voice
    opts = {}
```
