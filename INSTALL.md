# Installation Guide

Step-by-step instructions for installing Project Fronkensteen on your Home Assistant instance.

> **Read [PREREQUISITES.md](PREREQUISITES.md) first.** This guide assumes you have all required HACS components, API keys, and hardware ready.

---

## Overview

```
Step 1:  Install HACS components
Step 2:  Copy pyscript modules
Step 3:  Copy packages
Step 4:  Copy helper definitions
Step 5:  Copy blueprints (automation + script)
Step 6:  Configure entity_config.yaml and JSON configs
Step 7:  Configure helpers
Step 8:  Configure pyscript
Step 9:  Compile sqlite-vec (optional, for semantic search)
Step 10: Set up conversation agents (prompts, tools, pipelines)
Step 11: Dashboard & additional configuration
Step 12: Create blueprint instances
Step 13: Restart and verify
```

---

## Step 1: Install HACS Components

Install via HACS > Integrations > Search:

1. **pyscript** (Custom Components)
2. **Extended OpenAI Conversation**
3. **ha_text_ai**
4. **OpenAI STT**
5. **OpenAI TTS**

**For ElevenLabs Custom TTS:** Do NOT install from HACS. Copy the patched version:
```
custom_components/elevenlabs_custom_tts/ -> /config/custom_components/elevenlabs_custom_tts/
```

Install any optional components you want (SpotifyPlus, Alexa Media Player, Music Assistant, Calendar Utils).

Restart Home Assistant after installing all components.

---

## Step 2: Copy Pyscript Modules

Copy all `.py` files to your pyscript directory:

```
pyscript/*.py                    -> /config/pyscript/
pyscript/modules/shared_utils.py -> /config/pyscript/modules/shared_utils.py
```

**Files to copy (36 modules + 1 shared utility):**
- `agent_dispatcher.py`, `agent_whisper.py`, `away_patterns.py`, `calendar_promote.py`
- `common_utilities.py`, `contact_history.py`, `conversation_sensor.py`, `duck_manager.py`
- `email_promote.py`, `entity_history.py`, `entropy_correlator.py`, `focus_guard.py`
- `media_promote.py`, `memory.py`, `music_composer.py`, `music_taste.py`
- `notification_dedup.py`, `predictive_schedule.py`, `presence_identity.py`, `presence_patterns.py`
- `proactive_briefing.py`, `project_promote.py`, `routine_fingerprint.py`, `satellite_idle_reset.py`
- `scene_learner.py`, `sleep_config.py`, `state_bridge.py`, `system_health.py`
- `system_recovery.py`, `theatrical_mode.py`, `therapy_session.py`, `toggle_audit.py`
- `tts_queue.py`, `user_interview.py`, `voice_handoff.py`, `voice_session.py`
- `modules/shared_utils.py`

---

## Step 3: Copy Packages

Copy all `ai_*.yaml` packages:

```
packages/ai_*.yaml -> /config/packages/
```

**Enable packages** in your `configuration.yaml` if not already:
```yaml
homeassistant:
  packages: !include_dir_named packages
```

**43 package files.** These define template sensors, automations, scripts, and some helpers.

---

## Step 4: Copy Helper Definitions

Copy the helper YAML files to your config root:

```
helpers/helpers_input_boolean.yaml  -> /config/helpers_input_boolean.yaml
helpers/helpers_input_text.yaml     -> /config/helpers_input_text.yaml
helpers/helpers_input_number.yaml   -> /config/helpers_input_number.yaml
helpers/helpers_input_select.yaml   -> /config/helpers_input_select.yaml
helpers/helpers_input_datetime.yaml -> /config/helpers_input_datetime.yaml
helpers/helpers_input_button.yaml   -> /config/helpers_input_button.yaml
helpers/helpers_counter.yaml        -> /config/helpers_counter.yaml
```

**Include them** in your `configuration.yaml`:
```yaml
input_boolean: !include helpers_input_boolean.yaml
input_text: !include helpers_input_text.yaml
input_number: !include helpers_input_number.yaml
input_select: !include helpers_input_select.yaml
input_datetime: !include helpers_input_datetime.yaml
input_button: !include helpers_input_button.yaml
counter: !include helpers_counter.yaml
```

> **Warning:** If you already have `input_boolean:` (etc.) keys in your `configuration.yaml`, you'll need to merge them. HA does not allow duplicate top-level keys. Use `!include_dir_merge_named` for a packages-based approach, or consolidate into one file.

---

## Step 5: Copy Blueprints

Copy both automation and script blueprints:

```
automation/*.yaml -> /config/blueprints/automation/madalone/
script/*.yaml     -> /config/blueprints/script/madalone/
```

**77 automation blueprints + 35 script blueprints.** These are templates — they don't do anything until you create instances (Step 12).

---

## Step 6: Configure Entity Mapping & JSON Configs

### 6a. Entity Config

Copy the template and customize:
```
pyscript/entity_config.yaml.template -> /config/pyscript/entity_config.yaml
```

Edit `entity_config.yaml` to map YOUR entities:

| Section | What to Configure |
|---------|------------------|
| `fp2_zones` | Your presence sensor entity IDs per zone |
| `satellite_zones` | Your voice satellite entity IDs per zone |
| `agent_zones` | Which AI persona is "based" in which zone |
| `calendars` | Your calendar entity IDs (main, holidays, birthdays) |
| `music_players` | Your Music Assistant player entity IDs |
| `spotifyplus_entity` | Your SpotifyPlus sensor entity (or empty string) |
| `imap_sensor` | Your email sensor entity (or empty string) |
| `scene_learner_lights` | Light entities per zone |
| `persons` | Per-person config: calendar, notify service, spotify, imap |
| `vsync_zones` | Speaker groups per zone with ducking strategy |
| `duck` | Duck manager group, announcement players, satellites |

### 6b. TTS Speaker Config

Copy the template and customize:
```
pyscript/tts_speaker_config.json.template -> /config/pyscript/tts_speaker_config.json
```

Map each zone to a ranked list of speakers. First available speaker wins.

### 6c. Voice Mood Profile Map

Copy the template:
```
pyscript/voice_mood_profile_map.json.template -> /config/pyscript/voice_mood_profile_map.json
```

Map your ElevenLabs voice profile names to agent slugs. The key is the exact voice name as it appears in ElevenLabs; the value is the agent slug (`rick`, `quark`, etc.).

If you're not using ElevenLabs or have fewer than 5 agents, remove entries you don't use.

---

## Step 7: Configure Helpers

Follow the [Helper Setup Guide](helpers/helpers_setup_guide.md). Priority order:

1. **Identity**: `ai_primary_user`, `ai_context_user_name`, household profile
2. **Per-user helpers**: Clone `ai_per_user_helpers.yaml` blocks per person
3. **Schedule**: Wake times, bedtime, sleep hours
4. **Speakers**: Default speaker, zone priority
5. **Budget**: API limits and cost caps
6. **Email**: Known contacts, filter mode (if using email features)
7. **Presence sensors**: FP2 zone toggles, sleep detection sensor

Everything else has sensible defaults. See [helpers_reference.md](helpers/helpers_reference.md) for the complete reference.

---

## Step 8: Configure Pyscript

Add to your `configuration.yaml`:

```yaml
pyscript:
  allow_all_imports: true
  hass_is_global: true
  requirements:
    - midiutil==1.2.1
```

- `allow_all_imports: true` — Required. Pyscript modules use `aiohttp`, `sqlite3`, `yaml`, `hashlib`, and many other standard library modules.
- `hass_is_global: true` — Required. Makes the `hass` object available in all modules.
- `midiutil==1.2.1` — Required by the music composer for local MIDI synthesis (FluidSynth fallback).

---

## Step 9: Compile sqlite-vec (Optional)

sqlite-vec adds semantic vector search to the memory system. Skip this step if you don't need embedding-based memory search — FTS5 keyword search works without it.

### 9a. Copy the Build Script

```
scripts/recompile_vec0.sh -> /config/scripts/recompile_vec0.sh
```

Make it executable:
```bash
chmod +x /config/scripts/recompile_vec0.sh
```

### 9b. Add Shell Command

Add to your `configuration.yaml`:
```yaml
shell_command:
  recompile_vec0: "bash /config/scripts/recompile_vec0.sh"
```

### 9c. Run First Compilation

Via Developer Tools > Services, call `shell_command.recompile_vec0`. This takes 1-2 minutes. It:
1. Installs build tools temporarily (`build-base`, `sqlite-dev`, `git`)
2. Clones sqlite-vec source, patches musl compatibility
3. Compiles `vec0.so` and copies to `/config/vec0.so`
4. Validates with a KNN test query
5. Removes build tools

Check logs for `=== sqlite-vec recompile complete ===` to confirm success.

### 9d. Auto-Recompile Blueprint

After HA Core updates, the SQLite version may change and break `vec0.so`. The `sqlite_vec_recompile.yaml` blueprint automates recompilation — create an instance of it in Step 12.

> **Note:** Compilation only works on **HA OS** and **HA Supervised** (requires `apk` inside the container). HA Container and HA Core users must compile for their platform manually.

---

## Step 10: Set Up Conversation Agents

This is the most involved step. Each AI persona needs a conversation agent configured with the right system prompt and tool definitions.

### 10a. Understand the Variants

Each persona supports up to 5 conversation variants (modes), each with a different prompt and tool set:

| Variant | Purpose | Required? |
|---------|---------|-----------|
| **Standard** | General conversation, home control, notifications | Yes (at least 1 persona) |
| **Bedtime** | Bedtime negotiation and goodnight routines | Optional |
| **Music Compose** | Music generation and composition | Optional |
| **Music Transfer** | Music playback and playlist control | Optional |
| **Therapy** | Psychoanalysis sessions (Doctor Portuondo only) | Optional |

Start with **Standard** variants for 1-2 personas. Add more variants and personas as you explore.

### 10b. Create Conversation Agents

For each persona + variant, create an Extended OpenAI Conversation agent in Settings > Integrations > Extended OpenAI Conversation > Add Entry.

**Naming convention** (the dispatcher auto-discovers agents from this pattern):
```
{Persona} - {Variant}
```

This creates entity `conversation.{persona}_{variant}`. Examples:
- `Rick - Standard` → `conversation.rick_standard`
- `Quark - Standard` → `conversation.quark_standard`
- `Rick - Bedtime` → `conversation.rick_bedtime`

### 10c. Configure Prompts and Tools

Prompt templates and tool definitions are in `Extended OpenAi Conversation Prompts/`:

```
Extended OpenAi Conversation Prompts/
├── Standard/
│   ├── Rick_Standard.md          <- System prompt for Rick Standard
│   ├── Quark_Standard.md
│   ├── Kramer_Standard.md
│   ├── Deadpool_Standard.md
│   ├── Portuondo_Standard.md
│   └── _Functions_Standard.md    <- Tool/function definitions for Standard mode
├── Bedtime/
│   ├── {Persona}_Bedtime.md
│   └── _Functions_Bedtime.md
├── Music Compose/
│   ├── {Persona}_Music_Compose.md
│   └── _Functions_Music_Compose.md
├── Music Transfer/
│   ├── {Persona}_Music_Transfer.md
│   └── _Functions_Music_Transfer.md
└── Therapy/
    ├── Portuondo_Therapy.md
    └── _Functions_Therapy.md
```

For each agent you create:

1. **Open** the agent's configuration in HA (Settings > Integrations > Extended OpenAI Conversation > Configure on the entry)
2. **Copy the system prompt** from the matching `{Persona}_{Variant}.md` file into the "Prompt" field
3. **Copy the tool definitions** from the matching `_Functions_{Variant}.md` into the "Functions" field
4. **Set the LLM model**: All agents use your preferred model via OpenRouter (e.g., `meta-llama/llama-4-maverick`). Therapy variant uses `anthropic/claude-opus-4-6`.
5. **Configure API settings**: Set your OpenRouter API base URL and key

> **Customizing personas:** The prompt files contain the full personality definition. You can modify personality traits, add/remove personas, or create entirely new characters. The only requirement is the naming convention (`conversation.{slug}_{variant}`) so the dispatcher can discover them.

### 10d. Create Assist Pipelines

In Settings > Voice Assistants, create a pipeline for each agent:
- **Conversation agent**: The matching conversation entity
- **Speech-to-text**: Your STT provider (OpenAI STT recommended)
- **Text-to-speech**: The matching ElevenLabs voice (or other TTS provider)
- **Wake word**: (Optional) Assign different wake words per pipeline

The dispatcher reads pipeline configs to discover available TTS engines and voices per persona.

### 10e. Assign Pipelines to Satellites

For each voice satellite, set its preferred pipeline via the `select.{satellite}_pipeline` entity.

---

## Step 11: Dashboard & Additional Configuration

### 11a. Install the Dashboard

Copy the pre-built AI management dashboard:

```
ai-dashboard.yaml -> /config/ai-dashboard.yaml
```

Add to your `configuration.yaml` (if not already present):
```yaml
lovelace:
  mode: storage
  dashboards:
    ai-dashboard:
      mode: yaml
      filename: ai-dashboard.yaml
      title: AI Dashboard
      icon: mdi:robot
      show_in_sidebar: true
```

The dashboard provides 6 tabs: Overview, Configuration, User Profiles, Presence, Debug, and Memory.

### 11b. Recorder Exclusions (recommended)

Add these recorder exclusions to prevent database bloat from high-frequency pyscript events:

```yaml
recorder:
  exclude:
    event_types:
      - extended_openai_conversation.conversation.finished
      - pyscript_running
```

Merge with your existing `recorder:` config if you have one.

### 11c. ESPHome Voice Satellites (optional)

Reference ESPHome configs for Voice PE satellites are in `esphome/`. These include self-healing duplicate wake-up recovery, noise suppression, and TTS completion signaling. Adapt to your hardware.

---

## Step 12: Create Blueprint Instances

Blueprints are templates. You need to create **instances** (actual automations and scripts) from them.

Go to Settings > Automations & Scenes > Blueprints. For each blueprint you want to use, click it and fill in the inputs.

### Recommended Starting Set

Start with these core blueprints. Add more as you explore:

| Blueprint | Purpose | Priority |
|-----------|---------|----------|
| `mass_llm_enhanced_assist_blueprint_en.yaml` | Core LLM-enhanced voice interaction | Required |
| `notification_follow_me.yaml` | Route notifications to nearest speaker | High |
| `zone_presence.yaml` | Zone presence detection (1 per zone) | High |
| `zone_vacancy.yaml` | Zone vacancy detection (1 per zone) | High |
| `voice_handoff.yaml` | Agent-to-agent handoff | High |
| `reactive_banter.yaml` | Spontaneous agent commentary | Medium |
| `proactive_briefing.yaml` | Scheduled briefings | Medium |
| `calendar_alarm.yaml` | Calendar-aware smart alarm | Medium |
| `bedtime_routine.yaml` | Goodnight routine | Medium |
| `sleep_detection.yaml` | Detect sleep via presence | Medium |
| `budget_fallback.yaml` | Budget exceeded handling | Medium |
| `voice_mood_modulation.yaml` | Voice mood adjustment | Medium |
| `privacy_gate_hysteresis.yaml` | Per-person privacy gating (1 per person per tier) | Medium |
| `sqlite_vec_recompile.yaml` | Auto-recompile vec0.so after HA Core updates (if using sqlite-vec) | Medium |

See the [readme/](readme/) directory for detailed documentation on each blueprint.

---

## Step 13: Restart and Verify

1. **Check configuration**: Settings > System > Restart > Check Configuration
2. **Restart Home Assistant**
3. **Verify pyscript loaded**: Check Developer Tools > States for `pyscript.*` entities
4. **Verify helpers loaded**: Check Developer Tools > States for `input_boolean.ai_*`
5. **Verify sensors**: The `state_bridge.py` startup handler seeds ~66 `sensor.ai_*` sensors on boot
6. **Check logs**: Look for `pyscript` entries in Settings > System > Logs. Warnings are normal on first boot (empty caches, no memory data). Errors need investigation.

### First-Boot Expectations

- **Memory database** (`/config/memory.db`): Created automatically on first pyscript service call
- **Budget state** (`/config/pyscript/budget_state.json`): Created on first budget tracking event
- **Model pricing** (`/config/pyscript/model_pricing.json`): Fetched from OpenRouter on first budget calculation
- **Pipeline caches**: Built on first dispatcher/handoff/whisper invocation
- **Dispatch keywords**: Empty until conversations happen (auto-populated by whisper network)

First-boot will have no conversation history, no learned patterns, and no memory entries. The system learns over time.

---

## Troubleshooting

### "Entity not found" errors in logs
Pyscript modules reference entities from `entity_config.yaml`. If you left placeholder values, the entities won't exist. Fill in real entity IDs or remove unused sections.

### Helpers not loading
Check for duplicate `input_boolean:` (etc.) keys in `configuration.yaml`. HA silently ignores the second occurrence. Use the Configuration Check tool to catch this.

### Blueprint import fails
Blueprints reference specific helper entity IDs. If you renamed helpers or skipped the helper files, blueprint instances will fail validation. Install all helper files first.

### Pyscript "NameError: state.get" errors
Normal for entities that don't exist yet. The `state_bridge.py` startup handler creates most runtime sensors. If errors persist after restart, check that `state_bridge.py` is in `/config/pyscript/`.

### "allow_all_imports" errors
Pyscript is running in restricted mode. Set `allow_all_imports: true` in pyscript configuration and restart.

---

## Updating

When a new version is released:

1. Back up your `/config/pyscript/entity_config.yaml`, `tts_speaker_config.json`, and `voice_mood_profile_map.json`
2. Copy updated `.py` files to `/config/pyscript/`
3. Copy updated `.yaml` files to `/config/packages/`, `/config/blueprints/automation/madalone/`, `/config/blueprints/script/madalone/`, and `/config/helpers_*.yaml`
4. Restore your config files from backup
5. Check the changelog for new helpers or configuration changes
6. Restart Home Assistant
