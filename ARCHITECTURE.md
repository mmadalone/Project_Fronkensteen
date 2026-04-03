# Architecture Overview

How the pieces fit together.

---

## Three-Tier Execution Model

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     TIER 2 — BLUEPRINTS (Features)                      │
│  79 automation + 34 script blueprints                                   │
│  User-facing features: bedtime, wake-up, notifications, banter,         │
│  briefings, music, calendar, theatrical debates, therapy, privacy       │
│                                                                         │
│  Blueprints are templates — users create instances with their inputs.   │
│  They trigger on events, sensor states, and time. They call pyscript    │
│  services and read helper/sensor state.                                 │
└──────────┬──────────────────────────────────┬───────────────────────────┘
           │ calls pyscript services          │ triggers on events/states
           ▼                                  │
┌─────────────────────────────────────────────┼───────────────────────────┐
│              PACKAGES (Glue Layer)           │                           │
│  44 ai_*.yaml packages                      │                           │
│                                             │                           │
│  Template sensors — computed from pyscript   │                           │
│    state (budget %, cache hit rate, privacy  │                           │
│    gate status, hot context block)           │                           │
│  Script wrappers — entry points for          │                           │
│    blueprint → pyscript calls               │                           │
│  Automations — event-driven alerts,          │                           │
│    midnight resets, health monitoring        │                           │
│  REST sensors — external API polling         │                           │
│    (ElevenLabs credits, OpenRouter, Serper)  │                           │
└──────────┬──────────────────────────────────┘                           │
           │ reads sensors, calls services                                │
           ▼                                                              │
┌─────────────────────────────────────────────────────────────────────────┐
│                    TIER 1 — PYSCRIPT (Engine)                           │
│  38 Python modules · 168 services                                       │
│                                                                         │
│  Infrastructure: shared_utils (all modules), common_utilities (LLM)     │
│  Core: memory.py (SQLite + FTS5 + vec0, called by 25+ modules)          │
│  Voice: dispatcher, handoff, whisper, TTS queue, duck manager           │
│  Presence: identity, patterns, away, routine fingerprint                │
│  Scheduling: predictive_schedule, sleep_config, focus_guard             │
│  Creative: music_composer, theatrical_mode, therapy, interview          │
│  System: health, recovery, state_bridge, toggle_audit                   │
│                                                                         │
│  Owns all sensor.ai_* entities via state.set()                          │
│  Fires custom events for blueprint/package consumption                  │
│  Reads helpers for user configuration                                   │
└─────────────────────────────────────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         PERSISTENCE                                     │
│  /config/memory.db — SQLite + FTS5 + sqlite-vec (L2 memory)            │
│  /config/pyscript/budget_state.json — budget counters + snapshots       │
│  /config/pyscript/model_pricing.json — OpenRouter pricing cache         │
│  /config/pyscript/entity_config.yaml — hardware entity mapping          │
│  /config/pyscript/tts_speaker_config.json — zone-to-speaker map        │
│  helpers_input_*.yaml — user configuration (215 helpers)                │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Module Map

38 pyscript modules organized by function.

### Infrastructure (imported by all modules)

| Module | Services | Role |
|--------|----------|------|
| `modules/shared_utils.py` | — (library) | Person discovery, entity config loading, common helpers. Imported by every module. |
| `common_utilities.py` | `llm_task_call`, `conversation_with_timeout` | LLM API calls, budget tracking, OpenRouter pricing, TTS engine maps. |

### Core Storage

| Module | Services | Role |
|--------|----------|------|
| `memory.py` | `memory_set`, `memory_get`, `memory_search`, `memory_forget`, + 25 more | L2 persistence. SQLite + FTS5 full-text search + sqlite-vec embeddings. Called by 25+ modules. Single most critical dependency. |

### Voice Architecture

| Module | Services | Role |
|--------|----------|------|
| `agent_dispatcher.py` | `agent_dispatch`, `dispatcher_resolve_engine` | 7-priority routing engine. Selects which persona responds. Discovers agents from Assist Pipelines. |
| `agent_whisper.py` | `agent_whisper`, `agent_interaction_log` | Silent inter-agent context sharing. Mood detection, topic tracking, auto-keyword learning. |
| `voice_handoff.py` | `voice_handoff_*`, `save_handoff_context` | Live persona switching mid-conversation. Pipeline save/restore. |
| `voice_session.py` | `voice_session_*` | Mic lifecycle: continuous listening, session timeouts, pending queue. |
| `tts_queue.py` | `tts_queue_speak`, `tts_queue_clear` | 5-level priority queue. Speaker discovery, volume ducking, playback timing, caching, mood injection. Central audio bottleneck. |
| `duck_manager.py` | `duck_manager_*` | Reference-counted volume ducking. Snapshot/restore with user-adjustment protection. |

### Notifications & Content Promotion

| Module | Services | Role |
|--------|----------|------|
| `notification_dedup.py` | `dedup_check`, `dedup_register` | Cross-delivery duplicate prevention with fuzzy matching and TTL. |
| `email_promote.py` | `email_promote_*` | Email priority filtering, LLM summarization, sender classification. |
| `calendar_promote.py` | `calendar_promote_*`, `calendar_create_event`, `calendar_find_events`, `calendar_delete_event`, `calendar_edit_event` | Calendar sync, voice CRUD, event injection into context. |
| `media_promote.py` | `media_promote_*` | Sonarr/Radarr integration. Upcoming releases, recent downloads. |
| `project_promote.py` | `project_promote_*` | External project tracking integration. |
| `proactive_briefing.py` | `proactive_briefing_now`, `proactive_build_briefing` | Assembles briefings from 8 content sections. Calls dispatcher for TTS voice. Most interconnected content module. |

### Presence & Identity

| Module | Services | Role |
|--------|----------|------|
| `presence_identity.py` | `presence_identity_*` | Anchor-and-Track algorithm. Per-person room inference using FP2 + WiFi + GPS + voice + Markov. |
| `presence_patterns.py` | `presence_patterns_*` | Markov transition probabilities from zone history. Predicts next zone. |
| `away_patterns.py` | `away_patterns_*` | Departure/return prediction. Multi-trip tracking, entropy-based confidence. |
| `routine_fingerprint.py` | `routine_fingerprint_*` | Greedy Markov chains from zone sequences. Stage tracking, ETA, deviation detection. |

### Scheduling & Sleep

| Module | Services | Role |
|--------|----------|------|
| `predictive_schedule.py` | `predictive_schedule_*` | Calendar-aware wake/bed time prediction. Consumes routine fingerprints. |
| `sleep_config.py` | `sleep_detect_log` | Sleep state detection from FP2 bed zone. Window-based monitoring. |
| `focus_guard.py` | `focus_guard_*`, `focus_guard_mark_meal` | Anti-ADHD nudges: time checks, meal reminders, break suggestions, bedtime approach. |

### Creative

| Module | Services | Role |
|--------|----------|------|
| `music_composer.py` | `music_compose_*` | Hybrid synthesis: ElevenLabs API + FluidSynth local MIDI. 11 services, 9 content types. |
| `music_taste.py` | `music_taste_*` | Spotify + Music Assistant playback analysis. Genre/artist/mood trending. |
| `scene_learner.py` | `scene_learner_*` | Learns lighting preferences from user behavior. Per-zone, per-context. |
| `theatrical_mode.py` | `theatrical_mode_start` | Multi-agent debate orchestration. 2-5 personas, turn management, opponent-aware prompts. |
| `therapy_session.py` | `therapy_session_start`, `therapy_session_end`, `save_therapy_turn`, `therapy_report` | Guided psychoanalysis sessions. Session lifecycle, report generation, memory integration. |
| `user_interview.py` | `user_interview_*` | 9-category preference elicitation. Pre-seeds from memory. Populates per-user helpers. |

### System

| Module | Services | Role |
|--------|----------|------|
| `system_health.py` | — (sensor only) | Validates 7 subsystems every 30 min. Weighted scoring, state transitions. |
| `system_recovery.py` | — (event-driven) | 7 recovery playbooks, exponential backoff, circuit breaker. Triggered by health events. |
| `state_bridge.py` | `set_sensor_value`, `save_budget_state` | Generic bridge service for blueprints that can't call `state.set()`. Seeds 62 sensors on startup. |
| `toggle_audit.py` | — (auto-triggered) | Source-attributed logging of every AI kill switch change. SQLite storage. |
| `conversation_sensor.py` | — (event-triggered) | Tracks conversation metrics. Captures `extended_openai_conversation.conversation.finished` events. |
| `entity_history.py` | `entity_history_query` | HA recorder queries for agents. |
| `entropy_correlator.py` | `entropy_correlate` | Cross-source entropy pattern analysis. |
| `satellite_idle_reset.py` | — (auto-triggered) | Resets idle voice satellites to default pipeline. |
| `contact_history.py` | `contact_history_*` | Per-contact message logging with LLM batch compression. |

---

## Data Flow Patterns

### 1. State Flow (sensors)

```
Pyscript module                Package template sensor           Blueprint
─────────────────              ──────────────────────           ─────────
state.set("sensor.ai_foo")  →  {{ states("sensor.ai_foo") }}  →  trigger on state
```

Pyscript owns all `sensor.ai_*` entities via `state.set()`. Package template sensors compute derived values (e.g., budget remaining %, cache hit rate). Blueprints trigger on sensor state changes or read values in conditions/templates.

### 2. Service Flow (calls)

```
Blueprint action block          Pyscript @service function
──────────────────────          ──────────────────────────
service: pyscript.tts_queue_speak  →  @service def tts_queue_speak(...)
```

Blueprints call pyscript services directly. Some packages define script wrappers (`script.ai_llm_budget_check`) that blueprints can also call.

### 3. Event Bus (custom events)

```
Pyscript module              Blueprint/Package automation
───────────────              ────────────────────────────
event.fire("ai_foo", data)  →  trigger: event: ai_foo
```

9 key custom events connect modules:

| Event | Fired By | Consumed By |
|-------|----------|-------------|
| `ai_conversation_response_ready` | conversation_sensor | reactive_banter blueprint |
| `ai_theatrical_request` | reactive_banter (escalation) | theatrical_mode blueprint |
| `ai_handoff_request` | agent prompts (via tool) | voice_handoff blueprint |
| `ai_escalation_request` | agent prompts (via tool) | agent_escalation blueprint |
| `ai_bedtime_advisory` | predictive_schedule | bedtime_winddown blueprint |
| `ai_routine_deviation` | routine_fingerprint | routine_deviation_actions blueprint |
| `ai_health_category_degraded` | system_health | system_recovery |
| `ai_recovery_exhausted` | system_recovery | system_recovery package (alert) |
| `tts_queue_item_completed` | tts_queue | theatrical_mode, focus_guard |

### 4. Helper Flow (configuration)

```
User (UI/dashboard)     Helper entity              Pyscript / Blueprint
───────────────────     ──────────────             ────────────────────
sets value          →   input_boolean.ai_foo   ←   reads via state.get()
```

Helpers are the user's configuration API. 457 helpers across 3 tiers (215 Essential, 80 Per-User, 162 Dev Tuning). Pyscript modules and blueprints read them; users and the dashboard write them. System-managed helpers (timestamps, flags) are written by code.

---

## Critical Dependency Chains

### Memory Bottleneck

`memory.py` is called by 25+ modules. If it fails, the system enters **read-only mode** with periodic recovery probes. Reads continue; writes are queued or dropped.

```
memory.py (SQLite + FTS5 + vec0)
    ├── agent_whisper (topic/mood storage)
    ├── proactive_briefing (context assembly)
    ├── focus_guard (meal/nudge tracking)
    ├── music_composer (composition cache)
    ├── budget tracking (daily cost logs)
    ├── contact_history (message logs)
    ├── routine_fingerprint (pattern storage)
    └── ... 17 more modules
```

### TTS Audio Bottleneck

All spoken output flows through `tts_queue.py`. If it stalls, a watchdog (`ai_tts_stuck_timeout_minutes`) auto-clears after 2 minutes.

```
tts_queue.py
    ├── proactive_briefing (scheduled announcements)
    ├── notification_follow_me (notification delivery)
    ├── reactive_banter (spontaneous commentary)
    ├── theatrical_mode (debate turns)
    ├── voice_handoff (farewell/greeting TTS)
    └── 10+ more blueprints
```

### Longest Processing Chain

```
presence_patterns.py          routine_fingerprint.py         predictive_schedule.py
  Zone history analysis    →    Markov stage tracking     →    Wake/bed time prediction
  (daily rebuild 04:00)         + ETA calculation               + calendar awareness
                                     │                               │
                                     ▼                               ▼
                              routine_deviation          bedtime_winddown blueprint
                              actions blueprint          + calendar_alarm blueprint
```

### Budget Sensor Fan-Out

`sensor.ai_llm_budget_remaining` is read by 8+ modules to gate expensive operations:

| Reader | Gate Behavior |
|--------|--------------|
| agent_dispatcher | Skips personality features below threshold |
| proactive_briefing | Template-only mode below 20% |
| reactive_banter | Disabled below 60% |
| theatrical_mode | Disabled below 70% |
| music_composer | Routes to local MIDI below 80% |
| email_promote | Skips LLM summarization below 30% |
| focus_guard | Skips non-essential nudges below 30% |
| escalation | Disabled below 60% |

---

## Package Glue Layer

Packages bridge pyscript and blueprints. Each `ai_*.yaml` package typically contains:

| Component | Purpose | Example |
|-----------|---------|---------|
| **Template sensors** | Computed aggregations from pyscript state | `sensor.ai_llm_budget_remaining` (% from counters + limit) |
| **REST sensors** | External API polling | ElevenLabs subscription balance, OpenRouter credits |
| **Script wrappers** | Entry points for blueprint → pyscript | `script.ai_llm_budget_check` → gate check |
| **Automations** | Event/state-driven reactions | Health alerts, midnight resets, stale data reloads |
| **Shell commands** | External tool integration | FluidSynth installation (music_composer only) |

### Notable Packages

| Package | What It Provides |
|---------|-----------------|
| `ai_context_hot.yaml` | `sensor.ai_hot_context` — the full real-time context block injected into every LLM prompt. Reads 30+ entities. |
| `ai_llm_budget.yaml` | Budget sensors, REST sensors (ElevenLabs/OpenRouter/Serper), midnight reset automation, budget check script. |
| `ai_privacy_gate.yaml` | `sensor.ai_privacy_gate_status` — template sensor computing per-person, per-tier suppression from confidence scores. 32 features mapped to 3 tiers. |
| `ai_system_recovery.yaml` | 7 event-triggered automations for health alerts, stale data reloads, and recovery notifications. |
| `ai_music_composer.yaml` | FluidSynth install automation, midnight generation counter reset, cache stats sensor. |

---

## Feature-to-Module Map

Trace any feature back to its components.

| Feature | Blueprint(s) | Package(s) | Pyscript Module(s) |
|---------|-------------|-----------|-------------------|
| **Voice Conversation** | `mass_llm_enhanced_assist_blueprint_en` | `ai_dispatcher`, `ai_context_hot` | `agent_dispatcher`, `common_utilities`, `agent_whisper` |
| **Voice Handoff** | `voice_handoff` | — | `voice_handoff`, `agent_dispatcher` |
| **Reactive Banter** | `reactive_banter` | — | `agent_dispatcher`, `tts_queue`, `agent_whisper` |
| **Theatrical Debates** | `theatrical_mode` | `ai_theatrical` | `theatrical_mode`, `tts_queue` |
| **Notification Follow-Me** | `notification_follow_me` | `ai_notification_dedup` | `notification_dedup`, `tts_queue`, `duck_manager` |
| **Email Follow-Me** | `email_follow_me`, `email_priority_filter` | `ai_email_promotion` | `email_promote`, `tts_queue` |
| **Proactive Briefing** | `proactive_briefing` | `ai_proactive_briefing` | `proactive_briefing`, `calendar_promote`, `media_promote`, `agent_dispatcher` |
| **Bedtime System** | `bedtime_winddown`, `bedtime_routine`, `bedtime_routine_plus`, `bedtime_last_call`, `proactive_bedtime_escalation` | — | `predictive_schedule`, `routine_fingerprint`, `tts_queue` |
| **Wake-Up System** | `calendar_alarm`, `wake-up-guard`, `escalating_wakeup_guard` | — | `predictive_schedule`, `tts_queue` |
| **Sleep Detection** | `sleep_detection`, `sleep_lights` | `ai_sleep_detection` | `sleep_config`, `presence_identity` |
| **Focus Guard** | — (pyscript-driven) | — | `focus_guard`, `tts_queue` |
| **Presence Identity** | `zone_presence`, `zone_vacancy`, `privacy_gate_hysteresis` | `ai_privacy_gate`, `ai_presence_identity` | `presence_identity`, `presence_patterns` |
| **Away Patterns** | `away_state_actions`, `coming_home` | `ai_away_patterns` | `away_patterns` |
| **Routine Tracking** | `routine_stage_actions`, `routine_deviation_actions` | `ai_routine_tracker` | `routine_fingerprint` |
| **Music Follow-Me** | `music_assistant_follow_me_multi_room_advanced` | — | `tts_queue`, `duck_manager` |
| **Music Composition** | `music_compose_batch_trigger`, `music_weekly_refresh` | `ai_music_composer` | `music_composer` |
| **Music Taste** | `music_taste_rebuild` | `ai_music_taste` | `music_taste` |
| **Calendar CRUD** | (via agent tools) | `ai_calendar_promotion` | `calendar_promote` |
| **Budget Tracking** | `budget_fallback`, `budget_cost_alert` | `ai_llm_budget` | `common_utilities`, `state_bridge` |
| **Voice Mood** | `voice_mood_modulation` | — | `tts_queue` (injection at TTS time) |
| **Memory System** | `memory_auto_archive`, `memory_threshold_alert`, `memory_todo_mirror`, `embedding_batch` | `ai_embedding` | `memory` |
| **Therapy Mode** | `therapy_session` | `ai_therapy` | `therapy_session`, `voice_handoff` |
| **User Interview** | `user_interview` | `ai_user_interview` | `user_interview` |
| **System Health** | `system_recovery_alert` | `ai_system_health`, `ai_system_recovery` | `system_health`, `system_recovery` |
| **Toggle Audit** | — (auto-triggered) | `ai_toggle_audit` | `toggle_audit` |
| **Auto-Off / Auto-On** | `zone_presence`, `zone_vacancy` | `ai_auto_off` | — (blueprint-only) |
| **Circadian Lighting** | `circadian_lighting` | — | `scene_learner` |
| **Contact History** | `contact_history_summarizer` | — | `contact_history` |
| **Phone Call Detection** | — (pyscript-driven) | `ai_phone_call_detection` | — (template sensor only) |
| **Dashboard** | — | — | All (reads sensors/helpers) |

---

## Failure Modes & Graceful Degradation

| Failure | Detection | Degradation Path |
|---------|-----------|-----------------|
| **Dispatcher cache failure** | 3 consecutive errors | Bypass mode: routes to `ai_dispatcher_fallback_pipeline` helper. Auto-clears on recovery. |
| **ElevenLabs exhausted** | Character count below `ai_elevenlabs_credit_floor` (disabled when floor < 0) | TTS swaps to HA Cloud (free). All features continue. Negative floor allows overage. |
| **Memory DB write failure** | 3 consecutive errors | Read-only mode. Reads continue normally. Periodic recovery probe. |
| **Budget exhausted** | Daily cost exceeds `ai_budget_daily_cost_limit` | Fallback agent (`ai_budget_fallback_agent`). Pipelines saved/restored at midnight. |
| **TTS queue stuck** | Item age exceeds `ai_tts_stuck_timeout_minutes` | Watchdog auto-clears queue. Fires `ai_tts_queue_stuck` event. |
| **Refcount stranded** | `counter.ai_notification_follow_me_bypass_refcount > 0` and stale > TTL | Watchdog resets to 0 every 2 minutes. Follow-me re-enables. |
| **System health degraded** | Weighted score below threshold | `system_recovery.py` activates: 7 playbooks, exponential backoff, circuit breaker (3 retries/hour max). |
| **Pyscript reload** | HA integration reload | `state_bridge.py` re-seeds all 62 runtime sensors. Budget state restored from JSON. |

---

## Three-Layer Context System

Every voice interaction assembles context from three layers before the LLM processes an utterance:

| Layer | Source | Latency | Contents |
|-------|--------|---------|----------|
| **L1 — Hot Context** | `sensor.ai_hot_context` (package template sensor) | 0 ms | Time, identity, presence, media state, weather, schedule, projects, memory status, user preferences |
| **L2 — Warm Context** | `memory.py` (SQLite + FTS5 + vec0) | ~200 ms | Conversation history, preferences, contact history, interaction logs, todo items, semantic search |
| **L3 — Cold Context** | `calendar_promote.py`, `email_promote.py`, `media_promote.py` | ~500 ms | Google Calendar events, Gmail priority emails, weather forecasts, Sonarr/Radarr upcoming |

L1 is injected into every agent system prompt via the `ai_context_hot.yaml` package template sensor. L2 and L3 are fetched on-demand by agent tools during conversation.

---

## File Layout

```
/config/
├── pyscript/
│   ├── *.py                          38 modules (engine)
│   ├── modules/shared_utils.py       Shared library
│   ├── entity_config.yaml            Hardware entity mapping
│   ├── tts_speaker_config.json       Zone-to-speaker map
│   ├── voice_mood_profile_map.json   Voice-to-agent map
│   ├── model_pricing.json            LLM pricing cache (auto-generated)
│   └── budget_state.json             Budget persistence (auto-generated)
├── packages/
│   └── ai_*.yaml                     44 packages (glue layer)
├── automation/*.yaml                  79 automation blueprints (features)
├── script/*.yaml                      34 script blueprints (features)
├── helpers_input_*.yaml              7 helper definition files (215 entities)
├── helpers_counter.yaml              Counter helpers
├── memory.db                         L2 memory database (auto-created)
├── ai-dashboard.yaml                 6-tab management dashboard
└── custom_components/
    ├── elevenlabs_custom_tts/        Patched TTS with mood modulation
    └── extended_openai_conversation/ Patched with tool-call speech sanitizer
```
