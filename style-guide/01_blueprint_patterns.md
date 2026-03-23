# Home Assistant Style Guide — Blueprint Patterns

Sections 3 and 4 — Blueprint YAML structure, inputs, variables, templates, and script standards.

---

## 3. BLUEPRINT STRUCTURE & YAML FORMATTING

### 3.0 Blueprint-First Decision Tree (MANDATORY — apply before writing any automation)

Before writing ANY automation — package, blueprint, or raw YAML — run this gate. No exceptions.

```
  ① Is this trigger → conditions → actions?
  ② Has user-configurable parameters?
  ③ Could be reused (different zone, device, person, schedule)?

→ YES to ② or ③ (either one)        = BLUEPRINT in blueprints/automation/madalone/
→ YES to ① only (no params, no reuse) = package automation (infrastructure glue)
→ NO to all 3                         = package automation (infrastructure glue only)
```

**Decision rules:**
- **Blueprint** — user-facing feature, has inputs, reusable across zones/devices/people. Lives in `blueprints/automation/madalone/`. Instances go in `automations.yaml`.
- **Package automation** — startup housekeeping, midnight resets, pyscript coordination, internal state management with no user-facing inputs. Lives in `packages/ai_*.yaml`.
- **Raw automation in `automations.yaml`** — NEVER for new work. Legacy only. All new automations are either blueprint instances or package infrastructure glue.

**If in doubt:** It's a blueprint. The overhead of wrapping trigger→conditions→actions in a blueprint is trivial. The cost of discovering later that a package automation should have been a blueprint (and migrating it) is not.

> 📋 **QA Check BPG-1:** Every new automation must pass this decision tree before code is written. See `09_qa_audit_checklist.md`.

**Step 0 — Before even running the decision tree:** Check if an existing blueprint already does the job. List `blueprints/automation/madalone/` — can this feature be a NEW INSTANCE of an existing blueprint? If yes → create instance in `automations.yaml`, done. No new code needed. See §11.1 step 0 for the workflow version.

---

#### Pyscript Service Shelf

Every pyscript service available as a blueprint building block. Blueprints call these — they don't reimplement the logic. Before building new functionality into a blueprint, check if a service already handles it.

**Agent & Pipeline Services** (`agent_dispatcher.py`, `agent_whisper.py`)

| Service | Purpose | Blueprint usage |
|---|---|---|
| `pyscript.agent_dispatch` | Pipeline-aware persona routing — resolves pipeline to agent/TTS/persona, or dynamically selects by keyword/time | Any blueprint needing LLM conversation (coming_home, bedtime, proactive, wake-up) |
| `pyscript.dispatcher_load_keywords` | Load routing keywords for a selected agent from L2 memory | Dashboard/admin — keyword management |
| `pyscript.dispatcher_add_keyword` | Add a keyword to an agent's routing keywords | Dashboard/admin — keyword management |
| `pyscript.dispatcher_remove_keyword` | Remove a keyword from an agent's routing keywords | Dashboard/admin — keyword management |
| `pyscript.dispatcher_clear_auto_keywords` | Clear all auto (non-manual) keywords from an agent | Dashboard/admin — keyword maintenance |
| `pyscript.agent_whisper` | Post-interaction logging — writes mood, topic, interaction log to L2 memory (zero LLM calls). Updates `sensor.ai_recent_topics` with rolling topic history (C7). | Any blueprint with LLM conversation (post-interaction hook) |
| `pyscript.agent_whisper_context` | Pre-interaction context retrieval — searches L2 for recent whisper entries from OTHER agents | Any blueprint with LLM conversation (pre-interaction context) |

**TTS & Audio Services** (`tts_queue.py`, `duck_manager.py`, `volume_sync.py`)

| Service | Purpose | Blueprint usage |
|---|---|---|
| `pyscript.tts_queue_speak` | Priority TTS with presence-aware speaker targeting, preemption, dedup, caching | Any blueprint needing voice output (wake-up, proactive, notification, bedtime) |
| `pyscript.tts_queue_clear` | Remove pending items from TTS queue (optionally per-speaker) | Queue management, cleanup flows |
| `pyscript.tts_queue_stop` | Stop current playback and clear queue (optionally per-speaker) | Interrupt/stop voice output |
| `pyscript.tts_queue_flush_deferred` | Move items deferred during phone calls back to main queue | Phone call end trigger |
| `pyscript.tts_cache_generate` | Pre-warm TTS cache without playing audibly | Unwired — self-warms via opportunistic cache in `_play_item()`. Blueprint archived: `GIT_REPO/archive/tts_cache_warmup.yaml` |
| `pyscript.tts_rebuild_speaker_config` | Scan media_player entities for area-assigned speakers, rebuild config | Speaker setup changes |
| `pyscript.duck_manager_duck` | Duck media volumes for TTS playback (refcounted) | Notification/email follow-me, any TTS-over-music flow |
| `pyscript.duck_manager_restore` | Restore volumes after TTS (refcounted) | Paired with duck_manager_duck |
| `pyscript.duck_manager_force_restore` | Force-restore all ducked volumes (safety reset) | Watchdog/failsafe flows |
| `pyscript.duck_manager_status` | Get current duck state and refcount | Debugging, dashboard display |
| `pyscript.duck_manager_mark_user_adjusted` | Mark a player as user-adjusted — skip restore for that player | Volume sync coordination |
| `pyscript.volume_sync_status` | Get Alexa ↔ MA volume sync status | Dashboard display |

**Memory & Context Services** (`memory.py`, `common_utilities.py`)

| Service | Purpose | Blueprint usage |
|---|---|---|
| `pyscript.memory_set` | Store key/value in L2 memory with tags, scope, expiration | Any service needing persistent state |
| `pyscript.memory_get` | Retrieve value from L2 memory by key | Any service needing stored context |
| `pyscript.memory_search` | Full-text search across L2 memory | Agent context retrieval, dashboard search |
| `pyscript.memory_forget` | Delete a memory entry by key | Memory management |
| `pyscript.memory_related` | Find related memories by key (graph traversal) | **Wired:** LLM tool `memory_related` |
| `pyscript.memory_link` | Create relationship between two memory entries | **Wired:** LLM tool `memory_link` |
| `pyscript.memory_archive_search` | Search expired/archived memories by keyword | **Wired:** LLM tool `memory_archive_search` |
| `pyscript.memory_archive_restore` | Restore archived memory to active store + re-embed | Dashboard / dev tools only (not LLM-wired) |
| `pyscript.memory_purge_expired` | Remove expired entries from L2 | Maintenance automation |
| `pyscript.memory_reindex_fts` | Rebuild full-text search index | Maintenance automation |
| `pyscript.memory_health_check` | Check L2 memory database health | Monitoring/dashboard |
| `pyscript.memory_browse` | Search and write results to sensor for dashboard display | Dashboard memory browser |
| `pyscript.memory_archive_browse` | Search archived entries or show stats → `sensor.ai_memory_archive_browse` (C4) | Dashboard archive browser |
| `pyscript.memory_related_browse` | Show relationship graph for a key → `sensor.ai_memory_related_browse` (C4) | Dashboard relationship browser |
| `pyscript.memory_edit` | Read key/value/tags from dashboard helpers, call memory_set | Dashboard memory editor |
| `pyscript.memory_delete` | Read key from dashboard helper, call memory_forget | Dashboard memory editor |
| `pyscript.memory_load` | Load memory entry into dashboard edit fields | Dashboard memory editor |
| `pyscript.conversation_with_timeout` | Wrapper around conversation.process with enforced timeout | Any blueprint calling LLM with timeout safety |
| `pyscript.memory_cache_get` | Fetch cached value by key (volatile, in-memory) | Short-term state sharing between services |
| `pyscript.memory_cache_set` | Store value in volatile cache with optional TTL | Short-term state sharing |
| `pyscript.memory_cache_forget` | Remove cached entry | Cache cleanup |
| `pyscript.memory_cache_index_update` | Atomically update a list index in cache | Index management for services |
| `pyscript.memory_embed` | Generate + store embedding for single memory entry | Maintenance, debugging |
| `pyscript.memory_embed_batch` | Batch-embed memories missing vectors | `embedding_batch.yaml` nightly job |
| `pyscript.memory_semantic_search` | Pure KNN semantic search by meaning | Agent context enrichment, debugging |
| `pyscript.memory_semantic_autolink` | Create `content_match` edges via vec0 KNN for unlinked embeddings | `embedding_batch.yaml` v2.0.0 nightly job |
| `pyscript.memory_vec_health_check` | Test-load vec0.so, report status | `sqlite_vec_recompile.yaml` |
| `pyscript.llm_task_call` | Budget-aware LLM chat via ha_text_ai | I-3 summarization (future), any background LLM task |
| `pyscript.llm_direct_embed` | Budget-aware embedding generation via OpenAI API | memory_embed, memory_semantic_search |
| `pyscript.summarize_interactions` | Batch-compress whisper interaction logs into per-agent summaries | `interaction_summarizer.yaml` nightly job |
| `memory_context_refresh` (auto) | Writes recent summaries/mood to `sensor.ai_memory_context` every 15 min + startup | Hot context injection (I-4) — not a callable service. Topics now handled by C7 `sensor.ai_recent_topics` (instant updates via `agent_whisper.py`). |
| `pyscript.memory_todo_sync` | Bidirectional sync between L2 memory and HA todo list | `memory_todo_mirror.yaml` scheduled job (I-6) |

**Notification & Dedup Services** (`notification_dedup.py`, `email_promote.py`)

| Service | Purpose | Blueprint usage |
|---|---|---|
| `pyscript.dedup_check` | Check if a topic was already announced recently | Pre-announce dedup check |
| `pyscript.dedup_register` | Register a successful announcement in L2 | Post-announce registration |
| `pyscript.dedup_announce` | Combined check + announce + register (single call for blueprints) | calendar_pre_event_reminder, proactive, proactive_bedtime_escalation |
| `pyscript.email_promote_process` | Process incoming email through priority filter | email_priority_filter blueprint |
| `pyscript.email_clear_count` | Reset priority email counter | **Wired:** LLM tool `email_clear_count` + dashboard button |

**Presence & Identity Services** (`presence_identity.py`, `presence_patterns.py`, `focus_guard.py`)

| Service | Purpose | Blueprint usage |
|---|---|---|
| `pyscript.presence_identity_status` | Debug dump of per-person zone tracking state | Dev tools debugging |
| `pyscript.presence_identity_force_anchor` | Manually pin a person to a zone | Dev tools, testing |
| `pyscript.presence_identity_reset` | Clear all tracking state and reinitialize | Dev tools, recovery |
| `pyscript.discover_persons_status` | Return person discovery cache (Task 22) | Dev tools, verifying person config |

**Presence Pattern & Activity Services** (`presence_patterns.py`, `focus_guard.py`)

| Service | Purpose | Blueprint usage |
|---|---|---|
| `pyscript.presence_extract_transitions` | Extract zone transitions from recorder DB, store as L2 patterns | Pattern learning automation |
| `pyscript.presence_predict_next` | Predict next zone from frequency table | Proactive pre-positioning |
| `pyscript.presence_rebuild_patterns` | Full rebuild of presence patterns from recorder | Maintenance automation |
| `pyscript.sleep_detect_log` | Log sleep detection event to L2 memory | sleep_detection blueprint |
| `pyscript.meal_passive_log` | Log passive meal detection to L2 memory | meal_detection blueprint |
| `pyscript.focus_guard_evaluate` | Evaluate all 6 focus guard nudge conditions | Focus guard automation |
| `pyscript.focus_guard_mark_meal` | Set last_meal_time (optional `meal_time` param: `HH:MM` or `YYYY-MM-DD HH:MM:SS`) | **Wired:** LLM tool `focus_guard_mark_meal` |
| `pyscript.focus_guard_snooze` | Snooze non-critical nudges for N minutes | **Wired:** LLM tool `focus_guard_snooze` |

**Scheduling & Routine Services** (`predictive_schedule.py`, `routine_fingerprint.py`, `proactive_briefing.py`, `calendar_promote.py`)

| Service | Purpose | Blueprint usage |
|---|---|---|
| `pyscript.schedule_bedtime_advisor` | Compute bedtime recommendation from L1 + L2 + L3 data | Bedtime routine blueprints |
| `pyscript.schedule_optimal_timing` | Predict optimal timing for an event | **Wired:** LLM tool `schedule_optimal_timing` + dashboard button |
| `pyscript.routine_extract_fingerprints` | Extract routine fingerprints from frequency tables | Pattern learning automation |
| `pyscript.routine_track_position` | Track zone transition, match against known routines | FP2 state change trigger |
| `pyscript.proactive_build_briefing` | Assemble morning briefing content from all layers | proactive_briefing_morning, proactive_briefing_slot |
| `pyscript.proactive_briefing_now` | Full briefing delivery pipeline — assemble, select agent, reformulate, speak | proactive_briefing_morning, proactive_briefing_slot |
| `pyscript.calendar_promote_now` | Promote Google Calendar events to L2 memory | Calendar sync automation |

**Music Composition Services** (`music_composer.py`)

| Service | Purpose | Blueprint usage |
|---|---|---|
| `pyscript.music_compose` | Compose via ElevenLabs API (external) | `voice_compose_music.yaml` (auto/elevenlabs path) |
| `pyscript.music_compose_local` | Compose via FluidSynth (local MIDI→WAV) | `voice_compose_music.yaml` (fluidsynth path) |
| `pyscript.music_compose_approve` | Move all staging compositions to production (batch) | Admin/dashboard — bulk approval |
| `pyscript.music_compose_get` | Resolve composition by agent/type or library_id | Chime/stinger resolution in notification/email blueprints |
| `pyscript.music_library_action` | Router for LLM music library tool — list, play, delete, promote, list_soundfonts | **Wired:** LLM tool `music_library` |
| `pyscript.music_soundfont_list` | List available SoundFont instruments | **Wired:** LLM tool `music_library(list_soundfonts)` |

**Voice Session Services** (`voice_session.py`)

| Service | Purpose | Blueprint usage |
|---|---|---|
| `pyscript.voice_session_wait_audio` | Wait for satellite/speaker to finish playing audio (dual-signal: event + state) | `voice_session_mic.yaml` (step 3) |
| `pyscript.voice_session_open_mic` | Single mic open via `start_conversation` with echo guard | `voice_session_mic.yaml` (single-mic path) |
| `pyscript.voice_session_continuous` | Hot-context continuous conversation — announce media, open mic once, monitor for idle/stop/pending | `voice_session_mic.yaml` (continuous path) |
| `pyscript.voice_session_request` | Write JSON to `ai_voice_session_pending` to trigger post-pipeline automation | `voice_compose_music.yaml` (step 5) |
| `pyscript.voice_session_rediscover` | Re-scan entity registry for satellite device mappings | Admin — after adding/removing satellites |

**Voice Handoff Services** (`voice_handoff.py`)

| Service | Purpose | Blueprint usage |
|---|---|---|
| `pyscript.voice_handoff` | Full handoff sequence — farewell, pipeline switch, greeting, continuous conversation | `voice_handoff.yaml` |
| `pyscript.voice_handoff_restore` | Restore original pipeline after handoff timeout | `voice_handoff.yaml` (auto-restore) |

**HA Built-in Services (Voice)**

| Service | Purpose | Blueprint usage |
|---|---|---|
| `assist_satellite.start_conversation` | Initiate conversation on satellite — requires `start_message` or `start_media_id` (AP-64). `extra_system_prompt` alone is invalid. | `bedtime_winddown.yaml` (offer flow) |
| `assist_satellite.ask_question` | Ask yes/no question with defined answer sentences | `proactive_unified.yaml` (bedtime question ⑦) |

**Configuration Services** (`sleep_config.py`)

| Service | Purpose | Blueprint usage |
|---|---|---|
| `pyscript.sleep_lights_add_target` | Add light entity to sleep lights target list | Dashboard configuration |
| `pyscript.sleep_lights_remove_target` | Remove light entity from sleep lights target list | Dashboard configuration |
| `pyscript.sleep_lights_load_display` | Load sleep lights config for dashboard display | Dashboard display |
| `pyscript.sleep_config_populate_pickers` | Populate entity pickers for sleep config dashboard | Dashboard initialization |

---

### 3.1 Blueprint header and description image
Every blueprint must include a header image in its `description:` field. See §11.1 step 5 for image generation specs (1K, 16:9, premise from `IMG_PREMISES`). Allowed formats: `.jpeg`, `.jpg`, `.png`, `.webp`. Always ask the user for an image — never skip this step.

Every blueprint must include:
```yaml
blueprint:
  name: <Clear, descriptive name>
  author: <Author name>
  source_url: <GitHub URL if shared, omit if private>
  description: '![Image](<url>)

    # <Blueprint name>

    <What it does, in 2-3 sentences. Include key behaviors and safeguards.>

    ### Recent changes
    - **v3:** Added timeout handling for all wait steps
    - **v2:** Migrated service: → action: syntax throughout
    - **v1:** Initial version'
  domain: automation
  homeassistant:
    min_version: <minimum HA version — REQUIRED if using newer features>
  input:
    ...
```

**Header fields:**
- `author:` — Always include. Even for personal blueprints, it identifies ownership.
- `source_url:` — Include if the blueprint lives on GitHub or will be shared. This enables one-click reimport/update in the HA UI. Omit for strictly private blueprints. Use `GIT_REPO_URL` as the base (defined in Project Instructions).
- `description:` image URL — Use `HEADER_IMG_RAW` + `<blueprint_name>-header.<ext>` (defined in Project Instructions). Never use `github.com/blob/...` — blob URLs render HTML, not the image binary. See §11.1 step 5 for full image specs.
- `min_version:` — **Required** when using features from a specific HA version. Always verify which version introduced the features you use.
- `icon:` — **NOT valid** in the `blueprint:` schema block. HA will reject it with `extra keys not allowed @ data['blueprint']['icon']`. Icons are only available on **instances** created from blueprints, not the blueprint definition itself. See also §4.1.

**Valid `blueprint:` top-level keys (whitelist — AP-42):**

Only these keys are permitted directly under `blueprint:`. Anything else triggers `extra keys not allowed`:

`name` · `author` · `description` · `domain` · `source_url` · `homeassistant` · `input`

Common mistakes: `min_version:` and `icon:` placed directly under `blueprint:` instead of in their correct locations. `min_version` belongs **nested under `homeassistant:`** (not bare under `blueprint:`). `icon` is **not valid anywhere** in the blueprint schema — only on instances. If you catch yourself adding a key not on this list, stop and verify against HA's blueprint schema docs.

> 📋 **QA Check VER-2:** Blueprint examples must include `min_version` when using modern syntax. See `09_qa_audit_checklist.md`.

> 📋 **QA Check BP-1:** Every blueprint must have complete metadata — name, description, domain, min_version, and input name/description fields. See `09_qa_audit_checklist.md`.

**Key `min_version` thresholds:**

| Version | Feature introduced |
|---|---|
| `2024.2.0` | `conversation_agent:` blueprint selector (shows all installed agents, not just built-in) |
| `2024.4.0` | Labels and categories for automations, scripts, entities |
| `2024.6.0` | Collapsible input sections in blueprints |
| `2024.8.0` | `action:` syntax (replaces legacy `service:` — not deprecated, still works) |
| `2024.10.0` | `triggers:`, `conditions:`, `actions:` (plural syntax); `trigger:` keyword replacing `platform:` inside trigger definitions |
| `2025.12.0` | Purpose-specific triggers (Labs feature — experimental, opt-in via Settings > System > Labs; still expanding as of 2026.2) |

**Image rule (project standard — not an HA requirement):** Every blueprint MUST have an image in its description. When creating or updating a blueprint, ask the user if they want to provide an image. If they don't have one, generate one using the default specs in §11.1 step 5.

**Recent changes (project standard):** The blueprint description MUST include the last 3 version changes. Each entry is a single line, max ~80 characters — verb-first, no articles, no fluff. If a version touched multiple things, pick the most significant change.

### 3.2 Collapsible input sections (MANDATORY)
All blueprint inputs MUST be organized into collapsible sections grouped by **stage/phase of the automation flow**. Use the nested `input:` pattern:

```yaml
input:
  # ===========================================================================
  # ① DETECTION & TRIGGERS
  # ===========================================================================
  detection:
    name: "① Detection & triggers"
    icon: mdi:motion-sensor
    description: Configure how arrival/presence is detected.
    collapsed: false
    input:
      person_entity:
        name: Person
        default: ""
        ...
      entrance_sensor:
        name: Entrance occupancy sensor
        default: ""
        ...
      entrance_wait_timeout:
        name: Entrance wait timeout
        default: "0:02:00"
        ...

  # ===========================================================================
  # ② DEVICE PREPARATION
  # ===========================================================================
  preparation:
    name: "② Device preparation"
    icon: mdi:cog
    description: Devices to reset or prepare before the main flow.
    collapsed: true
    input:
      reset_switches:
        name: Reset switches
        default: []
        ...

  # ===========================================================================
  # ③ AI CONVERSATION
  # ===========================================================================
  conversation:
    name: "③ AI conversation"
    icon: mdi:robot
    description: Conversation agent and satellite settings.
    collapsed: true
    input:
      conversation_agent:
        name: Conversation agent
        default: ""
        ...

  # ===========================================================================
  # ④ CLEANUP & TIMING
  # ===========================================================================
  cleanup:
    name: "④ Cleanup & timing"
    icon: mdi:broom
    description: Post-flow cleanup and cooldown settings.
    collapsed: true
    input:
      post_conversation_delay:
        name: Post-conversation delay
        default: "0:01:00"
        ...
```

**Rules for sections:**
- Section display names use circled Unicode numbers: `"① <Phase name>"` (e.g., `"① Schedule"`, `"② Sync settings"`)
- Section YAML keys use descriptive names (e.g., `device_pairs:`, `sync_settings:`) — NOT `stage_N_xxx` or `section_N_xxx` prefixed names
- YAML comment dividers use the three-line `===` box style:
  ```yaml
  # ===========================================================================
  # ① DEVICE PAIRS
  # ===========================================================================
  ```
- Do NOT use single-line em-dash dividers (`# ── Stage 1 — ...`) — that's the old convention
- Each section gets an appropriate `mdi:` icon
- Each section gets a short `description` explaining what it configures
- Inputs within a section are ordered logically (most important first)
- **No exceptions.** Every blueprint uses collapsible sections regardless of input count. Even a 2-input blueprint gets a section wrapper — library-wide consistency is worth more than saving three lines of YAML.
- Default collapse state (MANDATORY):
  - Section ① MUST include collapsed: false (explicit — don’t rely on HA’s default-expanded behavior).
  - Section ② MAY include collapsed: false only if it is “core setup” required in most installs (e.g., target devices). Otherwise set it to collapsed: true.
  - Sections ③+ MUST include collapsed: true.
Rationale: Keep the “first-run essentials” visible, and tuck advanced/optional configuration away.
- **Collapsible section defaults (MANDATORY — AP-44):** Every input inside **any** collapsible section — regardless of `collapsed: true` or `collapsed: false` — MUST have an explicit, non-null `default:` value. If any input in a section lacks `default:`, HA silently downgrades the entire section to non-collapsible — no error, no warning, just a missing chevron. This is the #1 reason "collapsed doesn't work" in practice. Rules:
  - Bare default: (YAML null) is prohibited everywhere — no exceptions. Always provide a real value that matches the selector’s output type.
  - Selector defaults must match output type:
    - selector: entity (single) → default: `""`
    - selector: entity (multiple: true) → default: `[]`
    - selector: target → default: `{}`
    - selector: device (single) → default: `""` ; (multiple: true) → default: `[]`
  - If an input is functionally required, do not “fake it” with a non-empty default — keep the default empty and say “required” clearly in description:.
  - Section ① inputs are **NOT exempt** from the mandatory-default requirement. HA's UI requires every input in a section to have a `default:` before it will render the collapsible chevron — regardless of the `collapsed:` value. A section with `collapsed: false` and one default-less input will render as a flat, non-collapsible block. Provide sensible defaults for all inputs in all sections, and note in the `description:` when an input is functionally required (e.g., "At least one person entity is required").
- The `collapsed:` key is part of the collapsible input sections feature introduced in HA 2024.6.0. Any blueprint using `collapsed: true` inherits the `min_version: 2024.6.0` requirement (see §3.1 threshold table)

### 3.3 Input definitions
- Every input MUST have `name` and `description`.
- The `description` must explain **what the input does and why** — not just what it is. Users should understand the feature's purpose from the description alone.
- Defaults are mandatory (see §3.2): use typed empty defaults when no meaningful value exists, and use a sensible “real” default only when it’s safe.
- Use appropriate `selector` types — never leave inputs untyped.
- **Use `select` (dropdown) selectors whenever the input has a finite set of valid options.** This prevents user error and makes configuration clearer:

```yaml
mode_selector:
  name: Operating mode
  description: >
    Choose how the automation behaves when triggered multiple times.
    "cautious" waits for confirmation; "aggressive" acts immediately.
  default: cautious
  selector:
    select:
      options:
        - label: "Cautious — wait for confirmation"
          value: cautious
        - label: "Aggressive — act immediately"
          value: aggressive
```

- **Use multi-select (`multiple: true`) when the user may want to choose more than one option** and it makes logical sense:

```yaml
enabled_features:
  name: Enabled features
  description: Choose which features this automation should use.
  default:
    - lights
    - music
  selector:
    select:
      multiple: true
      options:
        - label: "Lights control"
          value: lights
        - label: "Music playback"
          value: music
        - label: "TV control"
          value: tv
        - label: "Game mode"
          value: game_mode
```

- Entity inputs should specify `domain` (and `device_class` where applicable) in the selector filter.
- **Conversation agent inputs MUST use the `conversation_agent:` selector** — never `entity: domain: conversation`. The `entity` selector only shows built-in HA Conversation agents, hiding Extended OpenAI Conversation, OpenAI Conversation, and other third-party agents. The `conversation_agent:` selector shows **all** installed conversation agents and outputs their ID. The corresponding `conversation.process` call uses `agent_id:` to reference the selected agent. **Requires HA 2024.2+** — the selector was introduced in that release and fails silently on older installs. *(Verified against official HA selector docs, 2025.12.1 — see https://www.home-assistant.io/docs/blueprint/selectors/#conversation-agent-selector)*:

```yaml
# ✅ CORRECT — shows all conversation agents including Extended OpenAI
conversation_agent:
  name: Conversation / LLM agent
  description: >
    Conversation agent that generates messages. Can be OpenAI
    Conversation, Extended OpenAI Conversation, Llama, or any
    agent that supports conversation.process.
  selector:
    conversation_agent:

# Action usage:
- action: conversation.process
  data:
    agent_id: !input conversation_agent
    text: "{{ my_prompt }}"
```

> **Dispatcher pattern note:** In this setup, the `conversation_agent` input is used as a **fallback only**. The standard path routes through `pyscript.agent_dispatch`, which selects the agent, voice, and persona dynamically (see §14.5.1 Pattern 1). The blueprint input still uses the `conversation_agent:` selector so users can override the dispatcher choice, and so the blueprint works standalone if the pyscript layer is unavailable. Include a `use_dispatcher` boolean input (default `true`) to let users opt in/out.

> **Pyscript integration inputs are always optional.** Every pyscript toggle input (`use_dispatcher`, `use_tts_queue`, `use_dedup`, `use_whisper`) MUST default to `true` with a `boolean:` selector. Numeric pyscript inputs (timeouts, thresholds) MUST have sensible defaults. The input `description:` MUST document the fallback behavior when the feature is off (e.g., "When off, falls back to tts.speak directly"). See §14.5.1 Design Principle for the full pattern and reference input template.

```yaml
# ❌ WRONG — only shows built-in HA agents, hides Extended OpenAI etc.
conversation_agent:
  selector:
    entity:
      domain: conversation
```

- **Use `target:` selector when actions need flexible targeting.** The `target:` selector is distinct from `entity:` — it lets users pick any combination of entities, devices, areas, or labels. This is the preferred selector when the action uses a `target:` field (which most service calls do). The output is a dict with `entity_id`, `device_id`, `area_id`, and `label_id` lists. *(Note: device filter was removed from the target selector in October 2025 — only entity filters are supported.)*

```yaml
# ✅ target: selector — flexible targeting by entity, device, area, or label
light_target:
  name: Lights to control
  description: >-
    Select the lights this automation should control. You can pick
    individual entities, entire devices, areas, or labels.
  selector:
    target:
      entity:
        domain: light

# Usage in actions — pass directly to target:
- alias: "Turn on selected lights"
  action: light.turn_on
  target: !input light_target
```

```yaml
# When to use target: vs entity:
#   target: → action uses `target:` field, user may want area/device/label targeting
#   entity: → you need a single entity_id for templates, state checks, or triggers
```

- **Never hardcode entity IDs in the action section.** If an action references an entity, it must come from an `!input` reference or a variable derived from one.

> 📋 **QA Check [SEC-3]:** Blueprint inputs with `text` or `template` selectors that flow into Jinja templates must be constrained and validated. See `09_qa_audit_checklist.md`.

> 📋 **QA Check BP-2:** Every input must use the most appropriate selector type — don't use `text:` where `entity:`, `select:`, `number:`, or `time:` would constrain input. See `09_qa_audit_checklist.md`.

### 3.4 Variables block
Declare a top-level `variables:` block immediately after `conditions:` to resolve `!input` references into template-usable variables:

```yaml
variables:
  person_entity: !input person_entity
  person_name: "{{ state_attr(person_entity, 'friendly_name') | default('someone') }}"
```

This avoids repeating `!input` throughout the action section and makes templates cleaner.

**Variable scope and propagation:** All variables defined at the top level (including resolved `!input` values and trigger variables like `trigger.to_state`) are available inside `wait_for_trigger`, `choose`, `if/then`, and nested actions. You can use them in dynamic wait conditions.

**⚠️ Caveat — `repeat` loops:** Top-level variables are NOT re-evaluated on each iteration of a `repeat` loop. If a variable calls `states()` and you need it to reflect the *current* value each iteration, you must define a local `variables:` block inside the `repeat.sequence`. Otherwise you'll get the stale value from when the automation started.

```yaml
variables:
  target_person: !input person_entity
  person_name: "{{ state_attr(target_person, 'friendly_name') | default('someone') }}"

actions:
  # The wait_for_trigger can reference variables defined above
  - alias: "Wait for person to leave the zone"
    wait_for_trigger:
      - trigger: state
        entity_id: !input person_entity
        from: "home"
    timeout:
      minutes: 30
    continue_on_timeout: true

  # Trigger variables from the original trigger are also available
  - alias: "Log the original trigger"
    action: logbook.log
    data:
      name: "Automation"
      message: "Triggered by {{ trigger.to_state.state | default('unknown') }} for {{ person_name }}"
```

### 3.5 Action aliases (STRONGLY RECOMMENDED)
Every distinct step or phase in the action sequence SHOULD have an `alias:` field. Aliases are not required by HA for functionality — blueprints and automations work fine without them — but they are **strongly recommended** because they dramatically improve debugging. The `alias:` value is what shows up in HA's trace UI, making it the primary documentation for each step when something goes wrong.

**Why this matters so much:** Without aliases, traces show generic step types (`service`, `wait_for_trigger`, `choose`) with no context. Debugging a 15-step automation without aliases means clicking into every damn step to figure out what it does. With aliases, the trace reads like a story. This is especially critical for vibe-coded automations where the AI generated the logic — aliases are the breadcrumb trail.

> 📋 **QA Check CQ-1:** Every action step should have an `alias:` field for trace readability. See `09_qa_audit_checklist.md`.

**Aliases must describe both the *what* and the *why*.** A good alias makes YAML comments redundant — it's readable in the raw file AND in traces.

```yaml
actions:
  - alias: "Wait for entrance sensor — GPS alone isn't enough, need physical presence"
    wait_for_trigger:
      - trigger: state
        entity_id: !input entrance_sensor
        to: "on"
    timeout: !input entrance_timeout
    continue_on_timeout: true

  - alias: "Handle entrance timeout — clean up and bail if nobody showed"
    if:
      - condition: template
        value_template: "{{ not wait.completed }}"
    then:
      - stop: "Entrance sensor timed out — nobody detected."

  - alias: "Reset speakers — power-cycle to clear stale Bluetooth connections"
    action: switch.turn_off
    target: !input speaker_switches
```

**Rules:**
- Every action should get an `alias:`. Every `choose` branch, every `if/then`, every service call. The only acceptable omissions are trivially obvious one-liners in a simple automation (e.g., a single `light.turn_on`).
- Write aliases as `"What — why"` when the reason isn't obvious from the action itself.
- For simple, self-evident actions (e.g., `light.turn_on` targeting a variable called `welcome_lights`), a short alias like `"Turn on welcome lights"` is fine — don't force a reason when there isn't one.
- YAML comments (`#`) are **optional** — use them only when the alias alone can't convey complex reasoning (e.g., explaining a non-obvious template, documenting a workaround for a HA bug, or noting why a particular approach was chosen over an alternative).

### 3.6 Template safety (MANDATORY)
All templates MUST use `| default()` filters to handle unavailable/unknown entities gracefully.

**Basic pattern — always apply:**
```yaml
# ✅ Safe
"{{ states('sensor.temperature') | float(0) }}"
"{{ state_attr(entity, 'friendly_name') | default('unknown') }}"
"{{ states(person_entity) | default('unknown') }}"

# ❌ Broken — will fail or produce errors if entity is unavailable
"{{ states('sensor.temperature') | float }}"
"{{ state_attr(entity, 'friendly_name') }}"
```

**What broken templates actually look like at runtime:**

```yaml
# ❌ BROKEN — chained math without defaults
variables:
  volume_pct: "{{ (state_attr(speaker, 'volume_level') * 100) | int }}"
# When speaker is unavailable:
#   state_attr() returns None
#   None * 100 → TypeError: unsupported operand type(s)
#   Automation silently stops. No error in UI. Only visible in traces.
#   User sees: automation triggered but "nothing happened."

# ✅ FIXED
variables:
  volume_pct: "{{ ((state_attr(speaker, 'volume_level') | float(0)) * 100) | int }}"
```

```yaml
# ❌ BROKEN — list comprehension with unguarded states()
variables:
  active_players: >-
    {{ states.media_player
       | selectattr('state', 'eq', 'playing')
       | map(attribute='entity_id')
       | list }}
  first_player: "{{ active_players[0] }}"
# When no players are playing:
#   active_players = []
#   active_players[0] → IndexError
#   Trace shows: "Error: list index out of range"

# ✅ FIXED
variables:
  active_players: >-
    {{ states.media_player
       | selectattr('state', 'eq', 'playing')
       | map(attribute='entity_id')
       | list }}
  first_player: "{{ active_players[0] if active_players | count > 0 else 'none' }}"
```

```yaml
# ❌ BROKEN — variable scope stale in repeat loop
variables:
  current_temp: "{{ states('sensor.bedroom_temp') | float(0) }}"

actions:
  - repeat:
      while:
        - condition: template
          value_template: "{{ current_temp < 22 }}"
      sequence:
        - action: climate.set_temperature
          target: { entity_id: climate.bedroom }
          data: { temperature: 22 }
        - delay: { minutes: 5 }
# current_temp NEVER updates — it was resolved once at automation start.
# Loop runs forever (or until HA kills it). See §3.4 caveat.

# ✅ FIXED — re-read inside the loop
actions:
  - repeat:
      while:
        - condition: numeric_state
          entity_id: sensor.bedroom_temp
          below: 22
      sequence:
        - action: climate.set_temperature
          target: { entity_id: climate.bedroom }
          data: { temperature: 22 }
        - delay: { minutes: 5 }
```

**`| default()` vs validation — choosing deliberately:**

Not every value *should* have a silent fallback. **Inputs still get empty typed defaults** (`""`/`[]`/`{}`) to keep HA’s UI stable, but “required-ness” must be enforced explicitly.

Decision rule:
- **Optional runtime state (entity readings, attrs, math)** → use `| default(fallback)` / `| float(0)` / `| int(0)` to prevent trace-only failures.
- **Required user configuration (must be set by the user)** → keep the input default empty, then **validate early** and `stop:` with a clear message if it wasn’t configured. Don’t “invent” a value in templates that hides misconfiguration.

When in doubt, ask: “Should this continue safely, or fail loudly with guidance?” If it must be loud: validate + stop.

**Rules:**
- Every `states()` call that feeds into math MUST have `| float(0)` or `| int(0)` with an explicit default.
- Every `state_attr()` call MUST have `| default(fallback_value)`.
- Every template condition should handle the `unavailable` and `unknown` states explicitly when they could affect logic.
- In `wait_for_trigger` templates, guard against the entity not existing at all.
- List operations (`[0]`, `| first`, `| last`) MUST guard against empty lists.
- **Paired/parallel list indexing** — when an index derived from list A is used to access list B, MUST check `idx < list_b | length` before access. Lists may have different sizes even when the user intends them to be paired (e.g., `alexa_list[idx]` where `idx` came from `ma_list.index()`).
- Variables used in `repeat` loops that need current state MUST be re-read inside the loop (see §3.4 caveat) or use native conditions that HA re-evaluates each iteration.

> 📋 **QA Check BP-3:** Mentally instantiate every blueprint with edge-case inputs (all defaults, empty lists, min/max values, unavailable entities) and verify it doesn't break. See `09_qa_audit_checklist.md`.

### 3.7 YAML formatting
- 2-space indentation throughout.
- Use `>-` for multi-line strings that should fold into one line (templates, prompts).
- Use `>` for multi-line strings that should preserve paragraph breaks (descriptions).
- Use `|` only when literal newlines matter (shell commands, code blocks).
- No trailing whitespace.
- Blank line between each top-level action step.

**Multi-line string operators — the differences matter:**

```yaml
# >- folds lines into one, STRIPS final newline (use for templates/prompts)
prompt: >-
  You are a helpful assistant.
  The user's name is {{ person_name }}.
  Respond in one sentence.
# Result: "You are a helpful assistant. The user's name is Alice. Respond in one sentence."
# No trailing newline — clean for passing to APIs and conversation.process

# > folds lines into one, KEEPS final newline (use for descriptions)
description: >
  This automation turns on the porch light when
  someone arrives home after sunset.
# Result: "This automation turns on the porch light when someone arrives home after sunset.\n"
# Trailing newline — fine for display text, awkward in templates

# | preserves ALL newlines literally, KEEPS final newline (use for shell commands, code blocks)
command: |
  #!/bin/bash
  echo "Starting backup"
  rsync -av /config /backup/
# Result: "#!/bin/bash\necho \"Starting backup\"\nrsync -av /config /backup/\n"

# |- preserves ALL newlines literally, STRIPS final newline
# (use for multi-line templates where trailing newline breaks string comparisons)
value_template: |-
  {% set temp = states('sensor.temp') | float(0) %}
  {{ temp > 25 }}
# Result: "{% set temp = states('sensor.temp') | float(0) %}\n{{ temp > 25 }}"
# No trailing newline — critical when the result feeds into == comparisons or API payloads
```

**Rule of thumb:** Default to `>-` for single-paragraph templates and API call payloads. Use `|-` for multi-line Jinja that must preserve line breaks but NOT a trailing newline (template conditions, multi-line `value_template` blocks). Use `>` only for human-readable descriptions where a trailing newline is harmless. Use `|` when you explicitly need a trailing newline (shell scripts, heredocs).

### 3.8 HA 2024.10+ syntax (MANDATORY)
All blueprints MUST use the newer HA syntax introduced in 2024.10.0. This applies to both new blueprints and existing ones when they're next edited.

**Top-level keys — use plural form:**
```yaml
# ✅ CORRECT (2024.10+ syntax)
triggers:
  - alias: "Alexa volume changed"
    trigger: state
    ...

conditions:
  - condition: template
    ...

actions:
  - alias: "Sync volume"
    action: media_player.volume_set
    ...
```
```yaml
# ❌ OLD — do not use in new code
trigger:
  - platform: state
    ...

condition:
  - condition: template
    ...

action:
  - service: media_player.volume_set
    ...
```

**Inside trigger definitions — use `trigger:` keyword, not `platform:`:**
```yaml
# ✅ CORRECT
triggers:
  - alias: "Motion detected"
    trigger: state
    entity_id: !input motion_sensor
    to: "on"
```
```yaml
# ❌ OLD
trigger:
  - alias: "Motion detected"
    platform: state
    entity_id: !input motion_sensor
    to: "on"
```

**Inside action steps — use `action:` not `service:`:**
```yaml
# ✅ CORRECT
- alias: "Turn on lights"
  action: light.turn_on
  target:
    entity_id: "{{ target_light }}"
```
```yaml
# ❌ OLD
- alias: "Turn on lights"
  service: light.turn_on
  target:
    entity_id: "{{ target_light }}"
```

**Fleet note:** Older blueprints still using the legacy syntax are not broken — HA supports both. Update them to the new syntax when they're next touched for any reason. No need for a dedicated migration pass.

### 3.9 Minimal complete blueprint — copy-paste-ready reference
This skeleton includes every mandatory element from this guide. Copy it, replace the placeholders, and you've got a compliant starting point:

```yaml
blueprint:
  name: "My Blueprint — Short description"
  author: madalone
  description: >
    What this blueprint does, in 2–3 sentences.

    ### Recent changes
    - **v1:** Initial version
  domain: automation
  homeassistant:
    min_version: "2024.10.0"
  input:
    # ===========================================================================
    # ① CORE SETTINGS
    # ===========================================================================
    core_settings:
      name: "① Core settings"
      icon: mdi:cog
      description: Primary configuration.
      collapsed: false
      input:
        target_entity:
          name: Target entity
          description: The entity this automation acts on.
          default: ""
          selector:
            entity:
              domain: light

    # ===========================================================================
    # ② TIMING
    # ===========================================================================
    timing:
      name: "② Timing"
      icon: mdi:clock-outline
      description: Timeout and delay settings.
      collapsed: true
      input:
        wait_timeout:
          name: Wait timeout
          description: How long to wait before giving up (seconds).
          default: 30
          selector:
            number:
              min: 5
              max: 300
              unit_of_measurement: seconds

variables:
  target_entity: !input target_entity
  wait_timeout: !input wait_timeout

triggers:
  - alias: "Example trigger — entity turns on"
    trigger: state
    entity_id: !input target_entity
    to: "on"

conditions: []

actions:
  - alias: "Wait for entity to turn off"
    wait_for_trigger:
      - trigger: state
        entity_id: !input target_entity
        to: "off"
    timeout:
      seconds: "{{ wait_timeout }}"
    continue_on_timeout: true

  - alias: "Handle timeout — clean up if wait expired"
    if:
      - condition: template
        value_template: "{{ not wait.completed }}"
    then:
      - alias: "Log timeout"
        action: logbook.log
        data:
          name: "My Blueprint"
          message: "Wait timed out for {{ target_entity }}"
```

---

## 4. SCRIPT STANDARDS

### 4.1 Required fields
Every **standalone script** (created via UI or YAML) MUST include:
- `alias`: Human-readable name
- `description`: What the script does and why it exists
- `icon`: Appropriate `mdi:` icon

> **⚠️ Blueprint exception:** The `icon:` field is NOT valid inside the `blueprint:` schema block. HA will reject it with `extra keys not allowed @ data['blueprint']['icon']`. Script blueprints cannot set an icon — the icon is only available on the **instances** created from the blueprint, not the blueprint definition itself. Do not add `icon:` to the `blueprint:` header.

**Minimal script skeleton:**

```yaml
script:
  my_script_id:
    alias: "My Script Name"
    description: "What this script does and why it exists."
    icon: mdi:script-text
    mode: single
    fields:
      example_field:
        description: "Describe the field."
        required: true
        selector:
          text:
    sequence:
      - alias: "First step — describe what and why"
        action: homeassistant.turn_on
        target:
          entity_id: "{{ example_field }}"
```

### 4.2 Inline explanations
Script sequences follow the same alias rules as blueprint actions (see §3.5). Every step gets a descriptive `alias:` that covers the what and why. YAML comments are optional — use them only when the alias can't carry the full explanation.

### 4.3 Changelog in description
For scripts that are actively developed (not simple one-liners), include the last 3 changes in the `description` field, same format as blueprints.
