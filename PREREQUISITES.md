# Prerequisites & Dependencies

Everything you need before installing Project Fronkensteen.

---

## Minimum Requirements

| Requirement | Minimum | Notes |
|-------------|---------|-------|
| Home Assistant | 2024.12+ | Packages, Assist Pipelines, pyscript 1.7.0 compatibility |
| HACS | 2.0+ | Required for installing custom components |
| Python | 3.12+ | Bundled with HA OS; needed for pyscript |

---

## Required HACS Components

Install these via HACS before proceeding. All are required for core functionality.

| Component | HACS Category | Purpose | Notes |
|-----------|--------------|---------|-------|
| **pyscript** | Integration | Python scripting runtime. Runs all 36 pyscript modules. | [Docs](https://hacs-pyscript.readthedocs.io/) |
| **Extended OpenAI Conversation** | Integration | LLM conversation agents. Powers all 5 AI personas. | [Repo](https://github.com/jekalmin/extended_openai_conversation) |
| **ElevenLabs Custom TTS** | Integration | Multi-voice TTS with mood modulation. | **Use the patched version in `custom_components/elevenlabs_custom_tts/`** — do NOT install from HACS. Disable HACS auto-update for this component. |
| **ha_text_ai** | Integration | LLM task execution (summarization, embedding, classification). | [Repo](https://github.com/SmartHomeEra/ha_text_ai) |
| **OpenAI STT** | Integration | Speech-to-text via OpenAI Whisper API. | Replaceable with any HA-compatible STT provider. |
| **OpenAI TTS** | Integration | Fallback TTS provider. | Used when ElevenLabs credits are low. |
| **OpenAI Whisper Cloud** | Integration | Alternative STT provider. | Optional if already using OpenAI STT. Some pipeline configs reference this. |

### Optional HACS Components

These enable specific features. The system works without them — affected features degrade gracefully.

| Component | Feature It Enables | Impact If Missing |
|-----------|-------------------|-------------------|
| **SpotifyPlus** | Music taste profile building from listening history | Music taste extraction disabled; music recommendations use generic profiles |
| **Alexa Media Player** | Alexa device TTS and media control | Alexa-specific blueprints non-functional; core voice pipeline unaffected |
| **Music Assistant** | Multi-room audio follow-me, ambient music | Music follow-me disabled; TTS still works via direct speaker control |
| **Calendar Utils** | Calendar event UID access for delete/edit operations | Voice calendar delete/edit unavailable; create and find still work |
| **Browser Mod** | Dashboard browser control | Dashboard-only; no impact on voice/automation features |

---

## Required API Accounts

| Service | What You Need | Used For | Cost |
|---------|--------------|----------|------|
| **OpenAI** (or OpenRouter) | API key | LLM conversation, TTS, STT, embeddings | Pay-per-use. ~$1-5/day typical. Budget system tracks and caps costs. |
| **ElevenLabs** | API key + subscription | Multi-voice TTS (5 distinct agent voices) | Subscription. System auto-falls back to HA Cloud TTS when credits are low. |
| **Home Assistant Cloud** (Nabu Casa) | Subscription | Fallback TTS when ElevenLabs credits exhausted | $6.50/mo (optional but strongly recommended as TTS safety net) |

### Optional API Accounts

| Service | Feature | Impact If Missing |
|---------|---------|-------------------|
| **Sonarr** | TV show tracking and upcoming calendar | Media tracking shows "no data"; proactive briefing skips media section |
| **Radarr** | Movie tracking and upcoming calendar | Same as Sonarr |
| **Spotify** (via SpotifyPlus) | Listening history for taste profiles | Music recommendations use generic profiles |
| **Google Calendar** | Calendar-aware briefings, wake time prediction | Schedule predictions use manual wake times only |
| **Serper** (web search) | Agent web search capability | Agents can't search the web; all other tools still work |

---

## Hardware Requirements

### Required: Room Presence Sensor

The project's presence identity, routine tracking, and privacy gate systems require **zone-level presence detection** — knowing which room someone is in, not just "home/away".

**Recommended:** Aqara FP2 presence sensor (mmWave, multi-zone)
- Entity pattern: `binary_sensor.fp2_presence_sensor_{zone}`
- Configure zones in `entity_config.yaml` under `fp2_zones`

**Alternatives:** Any binary sensor that provides per-room presence. You'll need to update `entity_config.yaml` zone mappings to match your sensor entity IDs.

**Without presence sensors:** The following features are disabled:
- Presence-based speaker routing (TTS goes to default speaker)
- Routine fingerprinting and deviation detection
- Sleep detection
- Privacy gate (identity confidence)
- Zone-based auto-off/auto-on
- Presence pattern learning

### Required: At Least One Speaker

Any `media_player` entity that supports TTS playback. Sonos, Google Home, HA Voice PE, ESP32 satellites, etc.

Configure your speakers in:
- `pyscript/tts_speaker_config.json` — zone-to-speaker mapping
- `pyscript/entity_config.yaml` — duck manager groups

### Recommended: Voice Satellite(s)

For voice interaction, you need at least one Assist satellite (ESP32-based, HA Voice PE, or similar).
- Entity pattern: `assist_satellite.{device_name}`
- Configure in `entity_config.yaml` under `satellite_zones`

**Without voice satellites:** Voice features (dispatcher, handoff, whisper, therapeutic sessions) are unavailable. All automation, notification, and proactive features still work.

Reference ESPHome configs for Voice PE satellites are shipped in `esphome/`. Adapt to your hardware.

---

## HA Core Integrations

These ship with Home Assistant. Ensure they're enabled (most are by default).

### Must Be Configured

| Integration | Why |
|-------------|-----|
| **Person** | Multi-person household tracking. Create a `person` entity per household member. |
| **Calendar** | At least one calendar for schedule-aware features (briefings, alarm, bedtime prediction). |
| **Recorder** | Required for entity history queries. Default config works. |
| **Media Player** | At least one configured speaker. |

### Used Automatically (no configuration needed)

These are used by blueprints/pyscript but require no special setup:

`automation`, `counter`, `input_boolean`, `input_datetime`, `input_number`, `input_select`, `input_text`, `light`, `notify`, `scene`, `script`, `sensor`, `sun`, `switch`, `todo`, `zone`

---

## File System Requirements

The pyscript integration needs file access for:

| Path | Purpose | Created By |
|------|---------|------------|
| `/config/pyscript/*.py` | Pyscript modules | Installation |
| `/config/pyscript/modules/shared_utils.py` | Shared utilities | Installation |
| `/config/pyscript/*.json` | Runtime config files | Installation |
| `/config/pyscript/entity_config.yaml` | Entity mapping config | Installation (user edits) |
| `/config/memory.db` | SQLite memory database | Created automatically on first run |
| `/config/pyscript/budget_state.json` | Budget persistence | Created automatically on first run |
| `/config/pyscript/model_pricing.json` | LLM pricing cache | Created automatically (refreshed daily from OpenRouter) |
| `/config/vec0.so` | sqlite-vec extension (semantic search) | Compiled from source (see below) |
| `/config/scripts/recompile_vec0.sh` | sqlite-vec build script | Installation |

### sqlite-vec (Optional but Recommended)

[sqlite-vec](https://github.com/asg017/sqlite-vec) is a C extension that adds vector similarity search to SQLite. It must be **compiled from source** inside the HA Core container because it links against the container's specific SQLite and musl versions.

**What it enables:**
- Semantic (embedding-based) memory search — find memories by meaning, not just keywords
- Memory auto-linking — nightly creation of `content_match` relationships between similar entries
- Search blending — combine FTS5 keyword scores with vector similarity scores

**Without it:** FTS5 keyword search and all other memory features work normally. Only semantic search is disabled. The system detects `vec0.so` at startup and adapts automatically.

**Compilation:**
- The build script (`scripts/recompile_vec0.sh`) handles everything: installs build tools, clones source, patches musl typedef conflicts, compiles, validates with a KNN test query, and cleans up.
- Build tools (`build-base`, `sqlite-dev`, `git`) are installed temporarily and removed after compilation.
- **Must be recompiled after HA Core updates** — the Alpine base image (and its SQLite version) may change. The `sqlite_vec_recompile.yaml` blueprint automates this.
- Only works on **HA OS and HA Supervised** (needs `apk` package manager inside the container). HA Container and HA Core users must compile manually for their platform.

---

## Pyscript Configuration

Pyscript must be configured to allow all imports and enable the `hass` variable. In your pyscript configuration (via UI or YAML):

```yaml
pyscript:
  allow_all_imports: true
  hass_is_global: true
```

**`allow_all_imports: true`** is required because pyscript modules use `aiohttp`, `sqlite3`, `hashlib`, `yaml`, `re`, `json`, `os`, `pathlib`, `statistics`, `math`, `random`, `time`, `datetime`, `struct`, `csv`, `tempfile`, `shutil`, `threading`, `asyncio`, and `contextlib`.

**`midiutil==1.2.1`** must be listed in pyscript `requirements:` — used by the music composer for local MIDI synthesis.

---

## Quick Compatibility Check

Before installing, verify:

- [ ] HACS is installed and working
- [ ] You have at least one LLM API key (OpenAI or OpenRouter)
- [ ] You have at least one speaker configured as a `media_player` entity
- [ ] You have a `person` entity for each household member
- [ ] You have room presence sensors (or are OK with presence features disabled)
- [ ] Your HA instance has file system access to `/config/pyscript/` (HA OS, Supervised, or Container with volume mount)
- [ ] (Optional) You can compile C extensions inside the HA container (HA OS/Supervised) for sqlite-vec semantic search
