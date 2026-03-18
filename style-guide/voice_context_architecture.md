# Voice Context Architecture — Three-Layer System

| Field | Value |
|---|---|
| **Created** | 2026-02-28 |
| **Last Updated** | 2026-03-03 |
| **Status** | `living document` |
| **Scope** | All HA voice personas (Rick, Quark, Deepee/Deadpool, Kramer, future agents) |

---

## System Profile (Audited 2026-02-28)

### Hardware

| Component | Detail |
|-----------|--------|
| **Board** | Raspberry Pi 5 |
| **CPU** | 4× ARM Cortex-A76 @ 2.4GHz (BCM2712) |
| **RAM** | 8GB LPDDR4X |
| **Storage** | 2TB WD Blue SN580 NVMe SSD (`/dev/nvme0n1`) |
| **Network** | Ethernet (`end0`) at 192.168.2.211, WiFi adapter present but unused |
| **OS** | Home Assistant OS (Alpine Linux 3.23, kernel 6.12.47-haos-raspi) |

### Software

| Component | Version | Notes |
|-----------|---------|-------|
| **Home Assistant Core** | 2026.2.3 | Migrated from Extended OpenAI Conversation to HA Voice Assistants |
| **HA Voice Assistants** | Core | 8 pipelines (consolidated from 18 sub-entries). `conversation.{persona}_{variant}` entities |
| ~~**Chime TTS**~~ | ~~v1.2.2 (HACS)~~ | **Not used.** TTS queue manager built entirely in Pyscript (`tts_queue.py`). Chime TTS evaluated but not adopted. |
| **Pyscript** | 1.7.0 (HACS) | memory.py, agent_dispatcher.py, agent_whisper.py, proactive_briefing.py, tts_queue.py, email_promote.py |
| **ElevenLabs Custom TTS** | 0.6.3 (HACS, loryanstrant) | Installed but NOT primary — official ElevenLabs integration also active |
| **ElevenLabs (official)** | HA Core | Primary TTS: Rick + Quark + Deepee + Kramer voices |
| **OpenAI STT** | HACS | GPT-4o-mini transcribe for speech-to-text |
| **OpenAI TTS** | HACS | GPT-4o-mini-tts + tts-1 engines available |

### Current Resource Usage

| Resource | Value | Headroom |
|----------|-------|----------|
| **RAM** | 2.3GB used / 7.8GB total | 5.5GB available (70% free) |
| **Swap** | 170MB used / 2.6GB total | Healthy |
| **Disk** | 46.5GB used / 1.8TB total | 1.7TB free (97% free) |
| **TTS cache** | 709MB (2,759 files) | No eviction policy yet — will grow indefinitely |
| **Recorder DB** | 2.6GB | Standard HA recorder |
| **Memory DB (Pyscript)** | 40KB | Barely used — early deployment |
| **Load average** | 0.26, 0.32, 0.29 | Low — system is comfortable |
| **Uptime** | 9+ days | Stable |

### Active Agents (4 personas, 8 pipelines — consolidated from 20 sub-entries)

| Agent | Variants | Conversation Entity | TTS Engine | TTS Voice |
|-------|----------|---------------------|------------|-----------|
| **Rick Sanchez** | standard, bedtime | `conversation.rick_standard`, `conversation.rick_bedtime` | ElevenLabs (official) | Rick Sanchez custom voice |
| **Quark** | standard, bedtime | `conversation.quark_standard`, `conversation.quark_bedtime` | ElevenLabs (official) | Quark custom voice |
| **Deepee (Deadpool)** | standard, bedtime | `conversation.deepee_standard`, `conversation.deepee_bedtime` | ElevenLabs | Deepee custom voice |
| **Kramer** | standard, bedtime | `conversation.kramer_standard`, `conversation.kramer_bedtime` | ElevenLabs | Kramer custom voice |

### Voice Pipelines (8 total — consolidated via HA Voice Assistants)

| Pipeline | Conversation Agent | TTS | STT |
|----------|--------------------|-----|-----|
| Rick Standard | `conversation.rick_standard` | ElevenLabs Rick | ElevenLabs STT |
| Rick Bedtime | `conversation.rick_bedtime` | ElevenLabs Rick | ElevenLabs STT |
| Quark Standard | `conversation.quark_standard` | ElevenLabs Quark | ElevenLabs STT |
| Quark Bedtime | `conversation.quark_bedtime` | ElevenLabs Quark | ElevenLabs STT |
| Deepee Standard | `conversation.deepee_standard` | ElevenLabs Deepee | ElevenLabs STT |
| Deepee Bedtime | `conversation.deepee_bedtime` | ElevenLabs Deepee | ElevenLabs STT |
| Kramer Standard | `conversation.kramer_standard` | ElevenLabs Kramer | ElevenLabs STT |
| Kramer Bedtime | `conversation.kramer_bedtime` | ElevenLabs Kramer | ElevenLabs STT |

### HACS Integrations (25 installed)

aemet, alexa_media, anylist, browser_mod, elevenlabs_custom_tts, extended_openai_conversation, glinet, govee, gtfs2, ha_aqara_devices, ha_text_ai, hacs, manish, openai_stt, openai_tts, openai_whisper_cloud, pyscript, spotifyplus, ssh_command, tuya_local, wakeword_installer, webrtc

### Installed Add-ons

| Add-on | Purpose |
|--------|---------|
| AI Config Agent | SSH-based config agent (this MCP connection) |
| File Browser | Web file manager |
| Portainer | Docker container management |
| Matter Server | Matter protocol support |

### Current Agent Context Baseline (Pre-Architecture)

What agents currently receive in their system prompts — before L1/L2/L3 architecture is implemented.

**Injected today:**

| Data | Method | Example |
|------|--------|---------|
| User name | Hardcoded in prompt text | `"for one user: Miquel"` / `"Mee-kel"` |
| Current time | Jinja2 `{{ now() }}` | Drives Rick drunk level, Quark mood by hour |
| Personality mode | Jinja2 time-based conditionals | Rick: hungover→drinking→drunk→hammered. Quark: groggy→polite→scheming→paranoid |
| Exposed entities | `{% for entity in exposed_entities %}` | CSV list of entity_id, name, state, aliases |
| Memory tool | Function spec in Extended OpenAI Conversation | SQLite key/value with scope (user/household/session), tags, expiration |
| Custom tools | Function specs per sub-entry | stop_radio, shut_up, pause_media, web_search, memory_tool, voice_play_bedtime_audiobook, etc. |

**NOT injected today (the gap L1 fills):**

| Missing Data | Available In HA? | Impact |
|-------------|-------------------|--------|
| User presence/location | ✅ FP2 sensors exist | Agent doesn't know WHERE user is — can't route audio or adjust tone |
| Sleep/wake schedule | ✅ Helpers exist (bedtime_active, countdown timers) | Agent doesn't know if bedtime is active unless a bedtime-specific sub-entry is used |
| Media currently playing | ✅ media_player states | Agent can check entities manually but doesn't get "Living room: playing Tool" automatically |
| Weather/outdoor conditions | ✅ AEMET integration | No environmental context for suggestions |
| Calendar/upcoming events | ❌ No Google Calendar integration yet | No awareness of appointments |
| Email status | ❌ No IMAP integration yet | No awareness of pending messages |
| Day type (work/weekend) | ❌ No helper exists | Agent doesn't know if it's a work day |
| Household context | ❌ No structured profile | Agent doesn't know about Jessica, pets, relationships |
| User preferences | ❌ Only in memory.db (barely populated, 40KB) | Agent knows nothing about music taste, temperature preferences, language prefs unless explicitly stored and recalled |
| Last interaction | ❌ No self-awareness helpers | Agent doesn't know who spoke last, what was discussed, or how long ago |
| Guest presence | ❌ No guest flag | Agent doesn't know to adjust behavior when company is present |

**Consequence:** Each agent sub-entry is an island. Rick-Extended-Verbose and Rick-Extended-Bedtime have DIFFERENT prompts with different context assumptions. The same user state information is either absent or duplicated inconsistently across 20 sub-entries. This is exactly what Task 1 (`ai_context_hot.yaml`) is designed to eliminate — one template sensor, injected everywhere, always current.

---

## Stakeholders

| Who | Role | Needs from this system |
|-----|------|----------------------|
| **Miquel** | Primary user, builder, admin | Voice assistants that are useful, entertaining, and privacy-respecting. System must be maintainable solo. Must not break existing working blueprints during migration. Anti-ADHD nudges for self-care. |
| **Jessica** | Future second user (moving in) | Privacy-scoped experience — her data never leaks to Miquel's agents. Non-intimidating onboarding. Ability to say "turn that off" and have it respected. |
| **Claude** | Co-architect (session-based) | Architecture doc must be self-contained enough that a fresh Claude session can pick up where the last left off. Decisions must include rationale. |
| **HA Community** | Potential blueprint consumers | Blueprints should be reusable without requiring the full architecture stack. Clean separation of concerns. |

---

## Constraints

Hard limits that shape every design decision. When Future Miquel asks "why didn't they just do X?" — look here first.

### Hardware

| Constraint | Impact |
|-----------|--------|
| **Raspberry Pi 5** (4-core ARM Cortex-A76, 8GB RAM) | All HA Core, Pyscript, add-ons, TTS processing, SQLite on one device. CPU/memory ceiling is real. No horizontal scaling. |
| **2TB WD Blue SN580 NVMe SSD** | Storage is not the bottleneck (1.7TB free). Write endurance is excellent vs SD card. Single point of failure remains — backup strategy still required. |
| **Aqara FP2 sensors** | mmWave presence — detects bodies, not identities. Cannot distinguish Miquel from Jessica in same zone. Identity layer must fuse other signals. |
| **Voice PE + satellite speakers** | Wake word processing is local. TTS playback depends on speaker media_player capabilities. All primary TTS targets (Sonos, Voice PE, Music Assistant players) support `MEDIA_ANNOUNCE` mode. Alexa devices and Philips TV do NOT — but these are not voice agent TTS targets. |

### Software

| Constraint | Impact |
|-----------|--------|
| **HA single-threaded automation engine** | All automations execute sequentially. Long-running LLM calls block other automations. Async Pyscript mitigates but doesn't eliminate. |
| **Extended OpenAI Conversation = HACS** | Core agent framework is a community integration, not HA Core. Developer could abandon it. No guaranteed compatibility with future HA versions. |
| ~~**Chime TTS**~~ | Evaluated but not adopted. TTS queue manager built entirely in Pyscript with direct `tts.speak` / `media_player.play_media` calls. |
| **Pyscript = HACS** | Memory engine and queue manager runtime. Another community dependency. |
| **ElevenLabs voice dropdown** | Only shows VoiceLab voices, not full community library. Must add voices to VoiceLab first on elevenlabs.io. |

### Budget

| Constraint | Impact |
|-----------|--------|
| **ElevenLabs API** | Monthly cost ceiling TBD. Per-character billing. Multi-agent patterns multiply calls. Cache system (DC-10) is cost mitigation, not optional luxury. |
| **OpenAI API** | Per-token billing via Extended OpenAI Conversation. Inter-agent patterns (deliberation, argument) multiply calls. LLM budget counter (DC-2) is cost mitigation. |
| **One builder** | Miquel is sole developer, tester, deployer, and user. No team to parallelize tasks. Build order must be sequential and each task must produce a testable checkpoint. |

### People

| Constraint | Impact |
|-----------|--------|
| **ADHD focus patterns** | Builder loses track of time during implementation sessions. Long build phases need break points. Tasks should be completable in 1-2 hour sessions where possible. |
| **Jessica's comfort level** | Second user is non-technical. System must not require CLI access, YAML editing, or HA developer tools for daily use. "Turn it off" must work instantly. |
| **No Node-RED** | All automation logic in native HA YAML + Pyscript. No external orchestration engines. Explicit design constraint (Decision #33). |

---

## Overview

Every voice interaction needs context to produce useful responses. The architecture splits context into three layers by **latency**, **volatility**, and **ownership**. Each layer answers a different question:

| Layer | Question | Latency | Volatility | Owner |
|-------|----------|---------|------------|-------|
| **L1 — Hot Context** | "What's happening right now?" | 0 ms (state read) | Seconds–minutes | HA Core (template sensor) |
| **L2 — Warm Context** | "What do I know about this person?" | ~200 ms (SQLite) | Days–permanent | Pyscript memory tool |
| **L3 — Cold Context** | "What's coming up / what happened?" | ~500 ms+ (API/DB) | Hours–days | External services |

The voice agent's system prompt assembles context from all three layers before the LLM processes any utterance. L1 is always injected. L2 and L3 are queried on demand or pre-fetched by automations.

---

## Two-Tier Execution Model — Pyscript Services + Blueprint Consumers

The system separates **engine** (pyscript services) from **features** (blueprints). Blueprints consume pyscript services. Packages hold shared state (helpers) consumed by both tiers. Raw automations in `automations.yaml` are blueprint instances only.

### Tier 1 — Pyscript Service Layer (the engine)

These modules expose services that blueprints call. They are NOT user-facing — they are infrastructure.

| Module | Services | Purpose |
|---|---|---|
| **agent_dispatcher.py** | `agent_dispatch`, `dispatcher_load_keywords`, `dispatcher_add_keyword`, `dispatcher_remove_keyword`, `dispatcher_clear_auto_keywords` | Pipeline-aware persona routing, keyword-based agent selection |
| ~~**agent_handoff.py**~~ | ~~`agent_handoff_detect`, `agent_handoff`, `agent_handoff_live`~~ | ~~Archived — superseded by `voice_handoff.yaml` blueprint (I-24)~~ |
| **agent_whisper.py** | `agent_whisper`, `agent_whisper_context` | Post-interaction logging and pre-interaction context retrieval (L2) |
| **tts_queue.py** | `tts_queue_speak`, `tts_queue_clear`, `tts_queue_stop`, `tts_queue_flush_deferred`, `tts_cache_generate`, `tts_rebuild_speaker_config` | Priority TTS pipeline with presence-aware routing, caching, dedup |
| **duck_manager.py** | `duck_manager_duck`, `duck_manager_restore`, `duck_manager_force_restore`, `duck_manager_status`, `duck_manager_mark_user_adjusted` | Refcounted volume ducking for TTS-over-music |
| **volume_sync.py** | `volume_sync_status` | Alexa ↔ MA volume synchronization status |
| **memory.py** | `memory_set`, `memory_get`, `memory_search`, `memory_forget`, `memory_related`, `memory_link`, `memory_purge_expired`, `memory_reindex_fts`, `memory_health_check`, `memory_browse`, `memory_edit`, `memory_delete`, `memory_load` | L2 persistent memory (SQLite key/value with tags, scope, FTS) |
| **common_utilities.py** | `conversation_with_timeout`, `memory_cache_get`, `memory_cache_set`, `memory_cache_forget`, `memory_cache_index_update` | Shared utilities — timeout-safe LLM calls, volatile in-memory cache |
| **notification_dedup.py** | `dedup_check`, `dedup_register`, `dedup_announce` | Announcement deduplication via L2 lookup |
| **email_promote.py** | `email_promote_process`, `email_clear_count` | Email priority filtering via known contacts + keywords |
| **presence_patterns.py** | `presence_extract_transitions`, `presence_predict_next`, `presence_rebuild_patterns`, `sleep_detect_log`, `meal_passive_log` | Zone transition learning, sleep/meal logging to L2 |
| **focus_guard.py** | `focus_guard_evaluate`, `focus_guard_mark_meal(meal_time=)`, `focus_guard_snooze` | ADHD-aware nudge engine with 6 condition types, per-type toggles, meal mic follow-up |
| **predictive_schedule.py** | `schedule_bedtime_advisor`, `schedule_optimal_timing` | Bedtime recommendation and optimal event timing |
| **routine_fingerprint.py** | `routine_extract_fingerprints`, `routine_track_position` | Routine pattern extraction and real-time matching |
| **proactive_briefing.py** | `proactive_build_briefing`, `proactive_briefing_now` | Morning briefing assembly and delivery pipeline |
| **calendar_promote.py** | `calendar_promote_now` | Google Calendar event promotion to L2 memory |
| **sleep_config.py** | `sleep_lights_add_target`, `sleep_lights_remove_target`, `sleep_lights_load_display`, `sleep_config_populate_pickers` | Sleep lights dashboard configuration |

### Tier 2 — Blueprint Consumer Layer (the features)

These blueprints deliver user-facing features. Each calls Tier 1 services as building blocks.

| Blueprint | What it does | Tier 1 services called |
|---|---|---|
| `bedtime_last_call` | Proactive last call announcement | agent_dispatch, agent_whisper, tts_queue_speak |
| `bedtime_routine` | LLM-driven goodnight (audiobook) | agent_dispatch, agent_whisper, tts_queue_speak |
| `bedtime_routine_plus` | LLM-driven goodnight (Kodi) | agent_dispatch, agent_whisper, tts_queue_speak |
| `calendar_pre_event_reminder` | Calendar pre-event TTS reminder | agent_dispatch, dedup_announce, tts_queue_speak |
| `coming_home` | AI welcome on arrival | agent_dispatch, agent_whisper |
| `email_follow_me` | Email notification follow-me routing | agent_dispatch, agent_whisper |
| `email_priority_filter` | IMAP to pyscript priority pipeline | email_promote_process |
| `escalating_wakeup_guard` | Escalating wake-up with inverted presence | agent_dispatch, agent_whisper, tts_queue_speak |
| `llm_alarm` | Wake-up alarm with LLM context | agent_dispatch, agent_whisper, tts_queue_speak |
| `mass_llm_enhanced_assist_blueprint_en` | MA local LLM enhanced voice support | agent_dispatch |
| `meal_detection` | Passive kitchen presence meal logging | meal_passive_log |
| `notification_follow_me` | Notification follow-me via satellites | agent_dispatch, agent_whisper |
| `phone_charge_reminder` | Persona-aware battery charge nudges | tts_queue_speak |
| `proactive` | Presence-based proactive suggestions (v6) | agent_dispatch, agent_whisper, dedup_announce |
| `proactive_bedtime_escalation` | Bedtime nags with inline routine | agent_dispatch, agent_whisper, dedup_announce, tts_queue_speak |
| `proactive_briefing_morning` | Morning briefing (presence-triggered) | proactive_briefing_now |
| `proactive_briefing_slot` | Scheduled briefing slot (afternoon/evening) | proactive_briefing_now |
| `proactive_llm` | Presence-based suggestions (direct LLM) | agent_dispatch, agent_whisper |
| `proactive_llm_sensors` | Presence-based suggestions (sensor variant) | agent_dispatch, agent_whisper |
| `proactive_unified` | Unified proactive presence engine | agent_dispatch, agent_whisper, conversation_with_timeout, dedup_announce |
| `sleep_detection` | Presence-based sleep lifecycle | sleep_detect_log |
| `wake-up-guard` | Wake-up guard with snooze/stop + TTS + mobile | agent_dispatch, agent_whisper, tts_queue_speak |

Blueprints without Tier 1 dependencies (standalone — no pyscript services):

`alexa_ma_volume_sync`, `alexa_presence_radio`, `alexa_presence_radio_stop`, `automation_trigger_mon`, `device_power_cycle`, `duck_refcount_watchdog`, `music_assistant_follow_me_idle_off`, `music_assistant_follow_me_multi_room_advanced`, `satellite_tracker`, `sleep_lights`, `smart-bathroom`, `temp_hub`, `ups_notify`, `va_confirmation_dialog`, `voice_active_media_controls`, `voice_pe_duck_media_volumes`, `voice_pe_restore_media_volumes`, `voice_pe_resume_media`, `wake_up_guard_external_alarm`, `wakeup_guard_mobile_notify`, `zone_vacancy`

### Relationship Summary

```
┌──────────────────────────────────────────────────────┐
│  automations.yaml  (blueprint instances only)        │
│  ┌──────────────────────────────────────────────┐    │
│  │  Blueprint Instances (user-configured)        │    │
│  └──────────────┬───────────────────────────────┘    │
└─────────────────┼────────────────────────────────────┘
                  │ created from
┌─────────────────▼────────────────────────────────────┐
│  blueprints/automation/madalone/  (Tier 2 — features)│
│  49 blueprints — user-facing automation logic        │
└─────────────────┬────────────────────────────────────┘
                  │ calls
┌─────────────────▼────────────────────────────────────┐
│  pyscript/*.py  (Tier 1 — engine)                    │
│  17 modules, 74 services — orchestration layer       │
└─────────────────┬────────────────────────────────────┘
                  │ reads/writes
┌─────────────────▼────────────────────────────────────┐
│  packages/ai_*.yaml  (shared state)                  │
│  Helpers consumed by both tiers + dashboards         │
│  Infrastructure automations (glue only)              │
└──────────────────────────────────────────────────────┘
```

---

## Layer 1 — Hot Context (Real-Time State)

### Purpose

Give the agent instant awareness of the physical environment and system state. This is the "situational awareness" layer — time of day, who's home, what's playing, what mode the house is in.

### Engine

A single HA template sensor (`sensor.ai_hot_context`) that compiles state from native HA entities into a text block. Zero external dependencies. Updated in real-time by HA's state machine.

### Data Sources

| Category | Source Entities | Example Output |
|----------|----------------|----------------|
| **Time & Schedule** | `now()`, `input_datetime` wake/bed times, `input_boolean.ai_context_work_day` | `Time: 03:45 AM (CET). Bedtime window active. Work day tomorrow.` |
| **Presence** | Aqara FP2 binary sensors (living room, workshop, bedroom) | `Miquel is in the workshop.` |
| **Media** | Music Assistant players (`media_player.ma_*`), Kodi | `Living room: playing "Lateralus" by Tool via Music Assistant.` |
| **House Mode** | `input_boolean.bedtime_active`, `input_boolean.bedtime_global_lock` | `Bedtime routine active. Global lock engaged.` |
| **Wake/Sleep** | `input_boolean.rick_wake_up_snooze`, `input_boolean.rick_wake_up_stop` | `Wake-up alarm snoozed.` |
| **Ducking** | `input_boolean` ducking flags, `input_number` pre-duck volumes | `Audio ducking active (living room pre-duck: 65%).` |
| **Identity** | `input_text.ai_context_user_name` | `User: Miquel` |
| **Guests** | `input_boolean.ai_context_guests_present` | `Guests present — adjust language/topics.` |

### Implementation

Package file: `/config/packages/ai_context_hot.yaml`

Contains:
- **New helpers** (~7): centralized user identity, schedule times, work day flag, guest flag
- **Template sensor**: `sensor.ai_hot_context` — Jinja2 template referencing all source entities, outputs formatted text block
- **No automations**: pure reactive state, updated by HA's template engine

### Integration Point

Each voice agent's system prompt includes:

```
{{ states('sensor.ai_hot_context') }}
```

This replaces the per-blueprint `variables:` context blocks that currently build time/media/presence strings redundantly in every blueprint.

### User Context Profile

Structured user data that L1 must make available to agents. Split into static (rarely changes) and dynamic (changes throughout the day).

**Static user profile (stored in helpers, injected into L1 template):**

| Field | Helper | Purpose | Example |
|-------|--------|---------|---------|
| Name | `input_text.ai_context_user_name` | How agents address the user | `Miquel` |
| Pronunciation | `input_text.ai_context_user_name_spoken` | How TTS should pronounce the name | `Mee-kel` (for Quark) / `Miquel` (for Rick) |
| Languages | `input_text.ai_context_user_languages` | Languages user speaks — agents can switch | `English, Spanish, Valencian, Dutch, Portuguese` |
| Preferred language | `input_select.ai_context_preferred_language` | Default response language | `English` |
| Wake time (weekday) | `input_datetime.ai_context_wake_time_weekday` | Earliest proactive announcement time | `07:30` |
| Wake time (weekend) | `input_datetime.ai_context_wake_time_weekend` | Weekend variant | `09:00` |
| Bedtime target | `input_datetime.ai_context_bed_time` | When bedtime routine should trigger | `22:30` |
| Work day flag | `input_boolean.ai_context_work_day` | Adjusts schedule awareness | `on` / `off` |
| Guest flag | `input_boolean.ai_context_guests_present` | Adjusts language, topics, volume | `off` |
| Household members | `input_text.ai_context_household` | Who lives here | `Miquel, Jessica (partner)` |
| Pets | `input_text.ai_context_pets` | For relevant context | `none` (or future pet name) |

**Dynamic context (computed by template sensor, refreshed in real-time):**

| Field | Source | Purpose | Example |
|-------|--------|---------|---------|
| Current presence | FP2 binary sensors | Where user is right now | `Miquel is in the workshop (2h 15m)` |
| Active media | media_player entities | What's playing and where | `Workshop: Lateralus by Tool via Music Assistant` |
| House mode | bedtime/wakeup booleans | Current system state | `Normal mode` / `Bedtime active` / `Wake-up in progress` |
| Weather | AEMET sensor | Outdoor conditions | `Clear, 18°C, humidity 45%` |
| Next alarm | sensor.madaringer_next_alarm | Phone alarm time | `Next alarm: 07:30` |
| Calendar one-liner | L2 promoted data (Task 18c) | Today's key event | `Dentist at 14:00` |
| Email count | L2 promoted data (Task 18c) | Pending priority messages | `2 priority emails` |
| Last interaction | self-awareness helpers (Task 2) | Who spoke last, when, about what | `Last: Rick, 15 min ago, about workshop lights` |
| Focus mode | `input_boolean.focus_mode` (Task 20) | Anti-ADHD DND status | `Focus mode: ON (45 min remaining)` |
| LLM budget | `input_number.ai_llm_daily_budget` (Task 9) | Remaining budget percentage | `Budget: 72% remaining` |
| Memory context | `sensor.ai_memory_context` (I-4) | Recent L2 summaries, moods, topics | `Recent summaries: deepee responded to 'morning briefing'...` |
| Occupancy | `sensor.occupancy_mode` (Identity Layer) | Who is home | `Both Miquel and Jessica are home` |

**Template sensor output format (target):**

```
Time: 3:45 PM (CET). Saturday. Weekend.
User: Miquel (speaks English, Spanish, Valencian, Dutch, Portuguese).
Household: Miquel, Jessica (partner).
Presence: Workshop (2h 15m continuous).
Media: Workshop Sonos — Lateralus by Tool.
House mode: Normal.
Weather: Clear, 18°C, humidity 45%.
Next alarm: tomorrow 07:30.
Schedule: Dentist at 14:00 (in 3h 15m). 2 priority emails.
Last interaction: Rick, 15 min ago, about workshop lights.
Focus mode: OFF.
LLM budget: 72% remaining.
```

**Agent prompt injection:**

```yaml
# In each Extended OpenAI Conversation system prompt:
{{ states('sensor.ai_hot_context') }}
```

One line. All context. All agents. Always current. Replaces the 20 different hardcoded context approaches currently scattered across sub-entries.

**Per-user scoping (Task 22):**

When Jessica moves in, the template sensor splits into `sensor.ai_hot_context_miquel` and `sensor.ai_hot_context_jessica`. Each agent sub-entry references the correct user's sensor. The identity layer (Task 6) determines which user is speaking and routes to the correct sensor. Jessica's presence data, calendar, and preferences never leak into Miquel's context, and vice versa.

### Status

**Running.** L1 hot context is operational. Implementation notes:
- Package YAML with helpers deployed (`ai_context_hot.yaml`)
- Template sensor `sensor.ai_hot_context` active — injected into all agent system prompts
- Self-awareness helpers (`last_agent`, `last_topic`, `last_time`) operational
- Agent prompts consolidated from 18 sub-entries to 8 pipelines (4 personas × 2 variants)
- Blueprint context variable migration complete
- **Memory context section (I-4):** `sensor.ai_memory_context` injected into hot context — recent summaries, moods, topics from L2 (refreshed every 15 min by `memory_context_refresh` in `memory.py`)
- **Occupancy section:** `sensor.occupancy_mode` injected (solo_miquel/solo_jessica/dual/away/guest)
- **Dashboard card:** LCARS-styled L1 Hot Context card on `ai-dashboard.yaml` — real-time view of what agents see

---

## Layer 2 — Warm Context (Persistent Memory)

### Purpose

Give the agent knowledge about the user that persists across conversations and sessions. Facts, preferences, learned information, relationships between concepts. This is the "I remember you" layer.

### Engine

**luuquangvu Voice Assistant Long-term Memory** — native Pyscript integration with SQLite + FTS5 full-text search. Runs inside HA Core. No external processes, no container networking, no MCP servers.

- **GitHub:** https://github.com/luuquangvu/tutorials
- **DB file:** `/config/memory.db`
- **Pyscript files:** `/config/pyscript/memory.py`, `/config/pyscript/common_utilities.py`
- **Blueprint:** `luuquangvu/memory_tool_full_llm.yaml`
- **Script:** `script.voice_memory_tool` (exposed to Assist)

### Schema

```sql
CREATE TABLE mem (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    key          TEXT UNIQUE NOT NULL,
    value        TEXT NOT NULL,
    scope        TEXT NOT NULL,        -- 'user' or 'household'
    tags         TEXT NOT NULL,
    tags_search  TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    last_used_at TEXT NOT NULL,
    expires_at   TEXT                  -- TTL support
);

-- FTS5 virtual table for full-text search
CREATE VIRTUAL TABLE mem_fts USING fts5(
    key, value, tags,
    content='mem', content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);
```

### Services

| Service | Purpose | Called By |
|---------|---------|----------|
| `pyscript.memory_set` | Store/update memory with duplicate detection | LLM via script |
| `pyscript.memory_get` | Fetch by key with fuzzy fallback | LLM via script |
| `pyscript.memory_search` | FTS5 + BM25/Jaccard scoring | LLM via script |
| `pyscript.memory_forget` | Delete by key | LLM via script |
| `pyscript.memory_purge_expired` | TTL cleanup | Automation (daily) |
| `pyscript.memory_reindex_fts` | Rebuild FTS index | Manual/maintenance |
| `pyscript.memory_health_check` | Stats + startup probe | Automation (startup) |

### Integration Point

The LLM conversation agent calls `script.voice_memory_tool` as an exposed tool. The blueprint translates natural language intent into the appropriate Pyscript service call. The LLM decides when to store, search, or forget — the blueprint handles the mechanics.

### Current Data (as of 2026-02-28)

8 records including: user birthday, girlfriend's name, bedtime timestamps, time format preferences, test entries.

### Status

**Running.** Verified intact 2026-02-28. All components confirmed:
- Pyscript integration installed and configured
- memory.py + common_utilities.py in place
- Blueprint imported, script created and exposed to Assist
- SQLite database healthy (integrity_check: ok)
- **sqlite-vec semantic search (I-2):** vec0.so compiled, 4 services + blended FTS5/KNN search active
- **Interaction summarization (I-3):** nightly compression of whisper logs into persistent summaries
- **Semantic search LLM tool (I-4):** `voice_memory_semantic_search.yaml` script blueprint exposed to Assist
- **Todo list mirror (I-6):** bidirectional sync to `todo.ai_memory` via `memory_todo_sync` + `memory_todo_mirror.yaml` blueprint
- **Dashboard:** LCARS-styled L2 Memory Core card (entries, expired, FTS, relations, status) + Sync Todo button

---

## Layer 2 Enhancement — Auto-Relationships Graph

### Purpose

Make L2 memory associative. When the agent searches for "Jessica," it should also surface "girlfriend" and "birthday" without the user having to tag everything perfectly. Memories that share tags or content should be linked automatically.

### Engine

Extension to luuquangvu's `memory.py`. Adds a relationship table (`mem_rel`) and hooks into the existing `memory_set` flow. The duplicate-tag detection code already computes match scores between memories via `_search_tag_candidates()` + BM25/Jaccard — it currently discards the results. The extension persists them instead.

### New Schema

```sql
CREATE TABLE IF NOT EXISTS mem_rel (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    from_key    TEXT NOT NULL,
    to_key      TEXT NOT NULL,
    weight      REAL NOT NULL DEFAULT 0.0,  -- Jaccard/BM25 blend
    rel_type    TEXT NOT NULL DEFAULT 'tag_overlap',
    created_at  TEXT NOT NULL,
    UNIQUE(from_key, to_key, rel_type)
);
```

Bidirectional: A→B and B→A both stored. Relationship types: `tag_overlap` (auto), `content_match` (future), `manual` (explicit).

### New Services

| Service | Purpose |
|---------|---------|
| `pyscript.memory_related` | Traverse relationship graph (depth 1–3) |
| `pyscript.memory_link` | Manually link two memories |

### Hook Points

- **`memory_set`**: after successful store, calls `_memory_auto_link()` to persist tag overlap relationships
- **`memory_forget`**: cascade deletes relationships for the forgotten key
- **`memory_search`** (Option A): auto-appends related memories to search results for voice latency optimization
- **`memory_health_check`**: includes `rel_count` in stats

### Voice Agent Integration

Two strategies:

| Strategy | Approach | Best For |
|----------|----------|----------|
| **Option A** (search-time enrichment) | `memory_search` auto-appends related entries | Voice (latency-sensitive, one round-trip) |
| **Option B** (explicit service) | LLM calls `memory_related` after search | Automations/blueprints (LLM has control) |

Recommendation: Option A for voice personas, Option B exposed for blueprint use.

### Status

**Queued.** Full spec in `_build_logs/2026-02-28_memory_auto_relationships_spec.md`. Priority: after `notification_follow_me` v3.18.0 memory buffer build. Estimated ~150 lines added to memory.py.

---

## Layer 2 Enhancement — Semantic Search (sqlite-vec)

### Purpose

Add vector similarity search alongside FTS5 keyword search. When the agent searches for "feeling tired," it should also surface memories about "sleep quality," "late nights," and "insomnia" — even if those exact words don't appear in the query. FTS5 finds keyword matches. sqlite-vec finds meaning matches.

### Engine

**sqlite-vec** — loadable SQLite extension that adds vector column types and KNN (k-nearest-neighbor) queries. Runs inside the same `memory.db` database alongside `mem`, `mem_fts`, and `mem_rel`. No external processes, no PostgreSQL, no container networking.

- **Extension file:** `/config/vec0.so`
- **Loaded by:** `memory.py` via `conn.load_extension('/config/vec0')`
- **Embedding source:** OpenAI `text-embedding-3-small` (or equivalent cheap model)

### Build & Compilation

Tested and deployed on HA Core container (Alpine 3.23, Python 3.12.12, SQLite 3.51.2, musl 1.2.5, aarch64):

- `load_extension` is ENABLED in HA Core's SQLite build
- No pip wheels exist for `musllinux_aarch64` — must compile from source
- Compilation requires: (1) remove 3 BSD-style `u_int*_t` typedefs in `sqlite-vec.c`, (2) manually generate `sqlite-vec.h` (envsubst unavailable on minimal Alpine)
- Automated recompile after HA Core updates via `sqlite_vec_recompile.yaml` blueprint + `/config/scripts/recompile_vec0.sh`

**Build recipe:**
```bash
apk add build-base sqlite-dev gettext git
git clone --depth 1 https://github.com/asg017/sqlite-vec.git
cd sqlite-vec
# Patch: remove u_int8_t, u_int16_t, u_int64_t typedefs
sed -i '/^typedef u_int8_t uint8_t;$/d' sqlite-vec.c
sed -i '/^typedef u_int16_t uint16_t;$/d' sqlite-vec.c
sed -i '/^typedef u_int64_t uint64_t;$/d' sqlite-vec.c
# Generate header manually (envsubst not on minimal Alpine)
# See /config/scripts/recompile_vec0.sh for full header template
mkdir -p dist
cc -fPIC -shared -Ivendor/ -O3 -lm sqlite-vec.c -o dist/vec0.so
cp dist/vec0.so /config/vec0.so
```

### Schema

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS mem_vec USING vec0(
    key TEXT PRIMARY KEY,
    embedding float[512]    -- configurable via input_number.ai_embedding_dimensions
);
```

Dimensions default to 512 (sufficient for ~400 records, cheapest). Changing the dimension helper triggers automatic reindex via package automation.

### Services

| Service | Purpose |
|---------|---------|
| `pyscript.memory_semantic_search` | KNN query: find N closest memories by embedding similarity |
| `pyscript.memory_embed` | Generate + store embedding for a single memory entry |
| `pyscript.memory_embed_batch` | Batch-embed all memories missing vectors (nightly job) |
| `pyscript.memory_vec_health_check` | Test-load vec0.so, report status (startup + recompile blueprint) |

### Embedding Strategy

- **Batch, not write-path.** Memories are written normally via `memory_set`. A nightly blueprint (`embedding_batch.yaml`) generates embeddings for entries without vectors. No write-path latency.
- **Input:** `f"{tags} {value}"` — tags provide topical anchoring, value provides content.
- **Model:** OpenAI `text-embedding-3-small` via `pyscript.llm_direct_embed` (direct aiohttp, budget-gated).
- **Blended search:** `memory_search` auto-blends FTS5 + semantic results when vec0 is loaded. Weight controlled by `input_number.ai_semantic_blend_weight` (0=FTS5 only, 100=semantic only, default 50). Falls back gracefully to FTS5-only when vec0 unavailable.

### Relationship to Other L2 Capabilities

| Capability | What it finds | Speed | Cost |
|------------|---------------|-------|------|
| **FTS5** | Exact/stemmed keyword matches | ~1ms | Free |
| **Auto-relationships** | Tag-overlap graph neighbors | ~5ms | Free |
| **sqlite-vec** | Semantically similar content | ~10ms query | Embedding generation per batch (~$0.0016 for 397 records at 512d) |

All three are additive. Comprehensive search: FTS5 for direct hits → auto-relationships for graph expansion → sqlite-vec for semantic neighbors not reachable by keywords or tags.

### Maintenance

`vec0.so` persists across HA reboots (lives in `/config/`). Recompilation needed only after HA Core base image updates (new Alpine/SQLite major version). Automated via `sqlite_vec_recompile.yaml` blueprint which monitors `update.home_assistant_core_update`, test-loads vec0, recompiles if broken, and notifies. Manual recompile: `shell_command.recompile_vec0`.

### Status

**Deployed 2026-03-05.** vec0.so compiled, 4 services live, blended search active, nightly batch blueprint ready. End-to-end verified: embed → store → KNN search → budget tracking.

---

## Layer 3 — Cold Context (External Data)

### Purpose

Give the agent awareness of upcoming events, recent communications, and historical patterns. This is the "what's coming up" and "what happened before" layer.

### Data Sources

| Source | Integration | Latency | Use Case |
|--------|-------------|---------|----------|
| **Google Calendar** | HA Google Calendar integration | ~500 ms | "What's on my schedule tomorrow?" / proactive morning briefings |
| **Gmail / IMAP Email** | HA IMAP integration (or Gmail-specific) | ~500 ms | "Any important emails?" / proactive delivery notifications |
| **HA Recorder** | Native HA database | ~200 ms | "When did I last turn off the lights?" / pattern analysis |

### Integration Points

L3 data is NOT injected into every conversation. It's pulled on demand by:

1. **Proactive automations**: daily calendar sync writes today's agenda into an L2 memory entry (or a dedicated `input_text` helper), making it available at L1/L2 speed
2. **LLM tool calls**: agent calls calendar/email services when the user asks about schedules or messages
3. **Trigger-based**: IMAP trigger fires automation that announces via voice ("Package shipped" notification)

### Promotion Pattern

Cold → Warm → Hot:
- Google Calendar event for tomorrow → automation writes summary to L2 memory → L1 template sensor shows "Calendar: 2 events tomorrow"
- This "promotion" pattern means agents rarely need to query L3 directly during conversation — the data is pre-staged

### Google Calendar — Detailed Integration

Google Calendar is the richest L3 source — structured, time-bound, and highly promotable.

**Per-layer role:**

| Layer | Role | Content |
|-------|------|---------|
| **L3** | Raw source. HA's `calendar.google` entity. Queried via `calendar.get_events` service | Event title, start/end time, location, description, recurrence |
| **L2** | Promoted daily agenda. Automation writes structured summary to memory | `memory_set("calendar_today:miquel", "10:00 Dentist, 14:00 Team standup, 18:00 Dinner with Jessica", tags=["calendar", "miquel", "schedule"])` |
| **L1** | Hot context one-liner derived from L2 | `Calendar: 3 events today. Next: Dentist at 10:00 (in 2h15m).` |

**Promotion automation (runs daily + on calendar update):**

```yaml
# Pseudocode — L3→L2 calendar promotion
trigger:
  - platform: time
    at: "00:05:00"          # Daily at midnight
  - platform: state
    entity_id: calendar.google  # Also on calendar update

action:
  - service: calendar.get_events
    target:
      entity_id: calendar.google
    data:
      duration:
        hours: 24
    response_variable: events

  - service: pyscript.memory_set
    data:
      key: "calendar_today:miquel"
      value: >-
        {% for event in events.events %}
        {{ event.start | as_timestamp | timestamp_custom('%H:%M') }} {{ event.summary }}
        {% endfor %}
      tags: ["calendar", "miquel", "schedule"]

  # L1 picks this up automatically via template sensor
  # sensor.ai_hot_context reads from L2 calendar entry
```

**Proactive triggers:**

| Trigger | Timing | Agent Action |
|---------|--------|-------------|
| Morning briefing | On wake-up confirmation or scheduled time | Agent reads L2 calendar summary — already promoted, zero L3 latency |
| Pre-event reminder | 15 min before event start (HA calendar trigger) | "Hey genius, dentist in fifteen minutes. Try not to drool." |
| On-demand query | User asks "what's on my schedule?" | Agent reads L2 first (fast), falls back to L3 direct `calendar.get_events` if L2 is stale or empty |
| Evening preview | Bedtime routine or explicit ask | Tomorrow's agenda promoted to L2 at same midnight sync |

**L2 pattern storage (long-term):** Over time, L2 accumulates calendar patterns: "user has standup every weekday at 14:00", "dentist appointments happen roughly quarterly". These patterns feed into the prediction engine (Presence-Based Predictions) for proactive scheduling fusion — combining routine fingerprints + calendar + real-time presence.

### Gmail / Email — Detailed Integration

Email is high-volume and mostly garbage. The key challenge is **filtering** — only promote messages worth the agent's attention.

**Per-layer role:**

| Layer | Role | Content |
|-------|------|---------|
| **L3** | Raw source. HA's IMAP integration watches inbox. Triggers on new mail | Sender, subject, timestamp, snippet (first ~200 chars) |
| **L2** | Promoted **priority emails only**. Filtered subset written to memory | `memory_set("email_priority:miquel", "Amazon: package shipped, arrives Thursday", tags=["email", "miquel", "notification"])` |
| **L1** | Hot context counter only — no content | `Email: 2 priority unread.` Content too verbose and sensitive for always-on injection |

**Priority filter automation:**

```yaml
# Pseudocode — email priority filter
trigger:
  - platform: event
    event_type: imap_content
    event_data:
      sender: !secret imap_account

action:
  # Extract sender and subject from trigger data
  - variables:
      sender: "{{ trigger.event.data.sender }}"
      subject: "{{ trigger.event.data.subject }}"
      is_priority: >-
        {{ sender in state_attr('input_text.ai_email_known_contacts', 'contacts')
           or 'shipping' in subject | lower
           or 'delivery' in subject | lower
           or 'appointment' in subject | lower
           or 'urgent' in subject | lower
           or 'invoice' in subject | lower }}

  - condition: "{{ is_priority }}"

  - service: pyscript.memory_set
    data:
      key: "email_priority:miquel"
      value: "{{ sender }}: {{ subject }}"
      tags: ["email", "miquel", "priority"]

  # Optionally announce high-urgency emails via TTS
  - condition: "{{ 'urgent' in subject | lower }}"
  - service: script.tts_queue_speak
    data:
      text: "Priority email from {{ sender.split('@')[0] }}. Subject: {{ subject }}."
      voice: tts.elevenlabs_quark
      target_mode: presence
      priority: 3
      cache: none
```

**Filter configuration:** `input_text.ai_email_known_contacts` stores a list of known/trusted senders. Could also use HA labels, a helper list, or an L2 memory entry with the contact list. The filter rules are configurable — user adds/removes senders and keywords without touching automation code.

**What gets filtered OUT (never promoted):**
- Marketing newsletters, promotional emails
- Automated notifications from services (unless they match keywords)
- Unknown senders without priority keywords
- Anything the user hasn't explicitly whitelisted

**Privacy & multi-user scoping:**

Email is deeply personal. The per-user L2 scopes from the Identity Layer apply here with hard enforcement:

| Scenario | Behavior |
|----------|----------|
| Miquel identified (confidence > 70) | Agent can reference `email_priority:miquel` scope |
| Jessica identified (confidence > 70) | Agent can reference `email_priority:jessica` scope. Miquel's email NEVER accessible |
| Guest mode / low confidence | Email data completely suppressed — agent acts as if no email integration exists |
| Household scope | No email data in household scope. Email is always per-user, never shared |

Each user needs their own IMAP integration (separate email accounts) or a filter that routes emails to the correct user scope based on the destination address.

### L3 Performance & Staleness

| Source | Promotion Frequency | Max Staleness | Fallback if Stale |
|--------|-------------------|---------------|-------------------|
| Google Calendar | Every midnight + on calendar update events | ~24h (worst case: event added just after sync) | Direct L3 query via `calendar.get_events` — 500ms penalty |
| Gmail | Real-time (IMAP push trigger) | Minutes (depends on IMAP polling interval) | Agent acknowledges "email sync may be delayed" |
| HA Recorder | On demand (no promotion needed for most queries) | Real-time (native HA) | Always available |

### Status

**Partially wired.** Google Calendar and IMAP integrations exist in HA. Proactive announcement automations exist for some scenarios. The promotion pattern (L3 → L2 → L1) is designed above but not yet implemented as a formal pipeline. Implementation is Task 18 in the build order.

---

## Architecture Diagram

### System Context (External Boundary)

What the system touches. Everything outside the box is someone else's problem (or API bill).

```
                        ┌──────────────┐
                        │   Miquel     │
                        │  (primary)   │
                        └──────┬───────┘
                               │ voice / dashboard
                        ┌──────▼───────┐
                        │   Jessica    │
                        │  (future)    │
                        └──────┬───────┘
                               │ voice / dashboard
    ┌──────────────────────────▼──────────────────────────┐
    │                                                     │
    │          VOICE CONTEXT ARCHITECTURE                  │
    │          (HA on Raspberry Pi 5)                      │
    │                                                     │
    │  ┌─────────┐ ┌──────────┐ ┌───────────────────┐    │
    │  │ L1 Hot  │ │ L2 Warm  │ │ L3 Cold           │    │
    │  │ Context │ │ Memory   │ │ External Data     │    │
    │  └─────────┘ └──────────┘ └───────────────────┘    │
    │  ┌──────────────────┐ ┌────────────────────┐       │
    │  │ Agent Framework  │ │ TTS Queue Manager  │       │
    │  │ (Multi-persona)  │ │ (Pyscript native)  │       │
    │  └──────────────────┘ └────────────────────┘       │
    │  ┌──────────────────┐ ┌────────────────────┐       │
    │  │ Focus Guards     │ │ Prediction Engine  │       │
    │  │ (DC-12)          │ │ (Markov/Pyscript)  │       │
    │  └──────────────────┘ └────────────────────┘       │
    │                                                     │
    └──┬──────┬──────┬──────┬──────┬──────┬──────┬───────┘
       │      │      │      │      │      │      │
  ┌────▼──┐┌──▼───┐┌─▼────┐┌▼─────┐┌─▼──┐┌▼────┐┌▼──────┐
  │OpenAI ││Eleven││Google││Gmail ││FP2 ││Voice││Music  │
  │API    ││Labs  ││Cal   ││IMAP  ││mmW ││PE + ││Asst.  │
  │(GPT-4)││(TTS) ││API   ││      ││    ││Spkrs││(MA)   │
  └───────┘└──────┘└──────┘└──────┘└────┘└─────┘└───────┘
  Internet ─────────────────────┘  LAN ──────────────────┘
```

### Internal Layer View

```
┌─────────────────────────────────────────────────────────┐
│                   VOICE AGENT (LLM)                     │
│         Rick / Quark / future personas                  │
│                                                         │
│  System Prompt:                                         │
│  ┌─────────────────────────────────────────────────┐    │
│  │ {{ states('sensor.ai_hot_context') }}     [L1]  │    │
│  │ + Memory Tool instructions                [L2]  │    │
│  │ + Calendar/Email tool access              [L3]  │    │
│  └─────────────────────────────────────────────────┘    │
└────────────┬──────────────┬──────────────┬──────────────┘
             │              │              │
    ┌────────▼────────┐ ┌───▼────────┐ ┌──▼──────────────┐
    │   L1: HOT       │ │ L2: WARM   │ │ L3: COLD        │
    │                 │ │            │ │                  │
    │ Template Sensor │ │ Pyscript   │ │ Google Calendar  │
    │ HA Helpers      │ │ SQLite+FTS │ │ IMAP Email       │
    │ Entity States   │ │ mem + rel  │ │ HA Recorder      │
    │                 │ │            │ │                  │
    │ 0 ms            │ │ ~200 ms    │ │ ~500 ms+         │
    │ Always injected │ │ On demand  │ │ Pre-staged or    │
    │                 │ │ via tool   │ │ on demand        │
    └─────────────────┘ └────────────┘ └──────────────────┘
                              │
                    ┌─────────▼─────────┐
                    │  AUTO-RELATIONS   │
                    │  (L2 enhancement) │
                    │                   │
                    │  mem_rel table    │
                    │  Graph traversal  │
                    │  Tag overlap      │
                    │  BM25/Jaccard     │
                    └───────────────────┘
```

---

## Data Flow Examples

### Example 1: "Hey Rick, what time is it?"

```
L1 only → sensor.ai_hot_context includes current time
LLM reads context, responds immediately
No L2/L3 needed
```

### Example 2: "Hey Rick, when's my birthday?"

```
L1 → context injected (time, presence, etc.)
L2 → LLM calls script.voice_memory_tool → memory_search("birthday")
     → returns "11th of August 1981"
     → (with auto-relationships) also surfaces "girlfriend: Jessica" (tag overlap)
LLM assembles response from L1 + L2
```

### Example 3: "Hey Rick, what's on my calendar tomorrow?"

```
L1 → context injected
L3 → LLM calls Google Calendar service
     → returns events
     OR
L2 → if promotion automation ran overnight, agenda is already in memory
LLM responds from whichever path has the data
```

### Example 4: Proactive morning briefing (no user prompt)

```
Automation triggers at wake time (from L1 helper)
L3 → queries Google Calendar for today's events
L3 → queries IMAP for overnight emails
L2 → stores summary as memory entry ("today_briefing")
L1 → presence sensor confirms user is in room
Automation → TTS announcement via voice agent
```

---

## Migration Notes

### What Changes in Existing Blueprints

Current blueprints build context in their `variables:` section:

```yaml
variables:
  time_ctx_line: >-
    {% set hour = now().hour %}
    ...build time context string...
  media_ctx_line: >-
    {% if is_state('media_player.ma_living_room', 'playing') %}
    ...build media context string...
  context_block: >-
    {{ time_ctx_line }}
    {{ media_ctx_line }}
```

After L1: blueprints drop these variables entirely. The agent's system prompt injects `sensor.ai_hot_context` which provides all of this pre-built.

### What Stays the Same

- luuquangvu memory tool: untouched (L2 already running)
- Blueprint actions/triggers/conditions: unchanged
- Voice pipeline configuration: unchanged
- Agent personas and wake words: unchanged

---

## Build Order

> **See Updated Build Order at end of document** (17 tasks covering all layers, multi-agent, identity, and predictions).

---

## Decisions Log

> **See consolidated Decisions Log at end of document** (15 entries covering all architecture decisions).

---

## Multi-Agent System

### Overview

This is not a single-agent architecture. Multiple LLM personas coexist, each with distinct personality, voice, and conversation style. The system must handle agent selection, self-awareness, and shared context without persona bleed.

### Agent Roster

| Persona | Conversation Entity (Standard) | Conversation Entity (Bedtime) | TTS Voice |
|---------|-------------------------------|-------------------------------|-----------|
| **Rick Sanchez** | `conversation.rick_standard` | `conversation.rick_bedtime` | `tts.elevenlabs_text_to_speech` |
| **Quark** | `conversation.quark_standard` | `conversation.quark_bedtime` | `tts.elevenlabs_quark_text_to_speech` |
| **Deadpool (Deepee)** | `conversation.deepee_standard` | `conversation.deepee_bedtime` | `tts.deepee_text_to_speech` |
| **Kramer** | `conversation.kramer_standard` | `conversation.kramer_bedtime` | `tts.elevenlabs_kramer_text_to_speech` |

### Context-Specific Variants (Consolidated — Decision #43)

Two variants per agent. L1 hot context eliminated the need for verbose/music/coming_home variants. Consolidated from 18 sub-entries to 8 pipelines.

| Variant | Purpose | Tools | Entity naming |
|---------|---------|-------|---------------|
| **standard** | All non-bedtime interactions | execute_service(s), memory_tool, web_search, pause_media, shut_up, stop_radio | `conversation.{persona}_standard` |
| **bedtime** | Sleep transition, audiobook, countdown | execute_service(s), memory_tool, web_search, audiobook, countdown, skip | `conversation.{persona}_bedtime` |

Blueprint automations select the appropriate variant based on trigger context (bedtime blueprints use `*_bedtime`, everything else uses `*_standard`). The dispatcher selects between personas' standard entities using 6-level routing.

### Agent Randomizer

**Blueprint:** `madalone/agent_randomizer.yaml`
**Script:** `script.agent_randomizer_extended_verbose`

The randomizer selects a persona at random for general-purpose voice interactions where no specific context dictates the choice. It maps each persona to its conversation entity, TTS voice, and name aliases.

```
User triggers general wake word
  → Randomizer picks persona (1 of 4)
  → Routes to that persona's conversation entity + TTS
  → Response delivered in character
```

The randomizer is intentionally dumb — pure random selection. It does not consider context, user preference, or conversation history. That's the dispatcher's job.

### Future: Agent Dispatcher

The dispatcher replaces random selection with intelligent routing. It evaluates the request against available context to pick the best persona for the job.

**Routing signals (proposed):**

| Signal | Source | Example |
|--------|--------|---------|
| **User preference** | L2 memory | "Miquel prefers Rick for tech questions" |
| **Topic affinity** | System prompt analysis | Quark for negotiations/scheduling, Rick for tech/science |
| **Time of day** | L1 hot context | Kramer for casual evening banter, not 3 AM |
| **Conversation continuity** | L2 memory / HA state | If Rick started a multi-turn conversation, Rick continues |
| **Mood/tone** | STT analysis (future) | Deadpool for when user sounds frustrated |
| **Explicit request** | Wake word / name mention | "Hey Rick" bypasses dispatcher, goes straight to Rick |

**Architecture:**
- Dispatcher sits between wake word detection and conversation agent routing
- Reads L1 (current state) + L2 (user preferences, recent agent history) to make selection
- Falls back to randomizer if no strong signal
- Explicit name mentions always override dispatcher

**Status:** Running — pipeline-aware, 6-level routing. Dispatcher (`agent_dispatcher.py`) discovers personas from Assist Pipelines at startup. Routing levels: (1) explicit name mention, (2) wake word mapping, (3) conversation continuity, (4) topic keyword affinity, (5) time-of-day era defaults, (6) random fallback. Cache structure holds personas, entity_map, wake_word_map, pipeline_map, and topic_keywords. Era helpers (`input_select.ai_dispatcher_era_{period}`) populated dynamically.

### Agent Self-Awareness

Each persona must know:

1. **Who it is** — its own name, personality traits, speech patterns
2. **Who the others are** — that other personas exist and handle different interactions
3. **Who spoke last** — which agent had the previous conversation (avoids "who are you?" confusion)
4. **Shared memory** — all agents read/write the same L2 memory store (scope: `user` and `household`)

**Implementation (in system prompt):**

```
You are Rick Sanchez. You are one of several AI personas in this household:
- Rick Sanchez (you): science, tech, sarcasm, problem-solving
- Quark: negotiations, scheduling, business, Ferengi wisdom
- Deadpool (Deepee): humor, irreverence, breaking the fourth wall
- Kramer: enthusiasm, physical comedy energy, wild ideas

The user may have been talking to a different persona before you.
Check memory for recent conversation context before assuming
you know what's being discussed.

All personas share the same memory system. What you remember,
they can access. What they store, you can read.
```

**Self-awareness state helpers (proposed):**

| Helper | Purpose |
|--------|---------|
| `input_text.ai_last_agent_name` | Name of the last persona that responded |
| `input_text.ai_last_agent_entity` | Entity ID of last conversation agent used |
| `input_datetime.ai_last_interaction_time` | Timestamp of last voice interaction |
| `input_text.ai_last_interaction_topic` | Brief topic tag from last conversation |

These feed into L1 (`sensor.ai_hot_context`) so every agent knows who spoke last and roughly what about. Prevents the jarring experience of switching from Rick to Quark mid-topic with zero continuity.

### Memory Scoping in Multi-Agent Context

All agents share the same SQLite database. Memory scoping works at the data level, not the agent level:

| Scope | Visibility | Example |
|-------|-----------|---------|
| `user` | All agents, personal to Miquel | "birthday: August 11, 1981" |
| `household` | All agents, shared facts | "bedtime_actual: 2026-02-24 03:19" |

There is no per-agent memory scope. Rick doesn't have "Rick's memories" — he has access to all memories, same as Quark. The persona difference is in *how* they use and present the information, not *what* they can access.

**Future consideration:** If guests or additional household members get voice profiles, a `guest` scope or per-user scoping may be needed. Not required for single-user household.

### Current Agent Function Inventory (Audited 2026-02-28)

Functions exposed to LLM agents via Extended OpenAI Conversation's function calling. Audited across all 18 sub-entries.

| Function | Sub-entries | Purpose | Post-consolidation |
|----------|------------|---------|-------------------|
| `execute_service` | 18/18 | Call any HA service | Universal — keep in all |
| `execute_services` | 18/18 | Call multiple HA services | Universal — keep in all |
| `memory_tool` | 17/18 | L2 memory read/write/search/forget | Universal — keep in all (was missing from Kramer bedtime, now fixed) |
| `web_search` | 17/18 | Internet search during conversation | Universal — keep in all (was missing from Kramer bedtime, now fixed) |
| `pause_media` | 14/18 | Pause active media player | Standard only — not needed during bedtime |
| `shut_up` | 14/18 | Stop all media playback | Standard only — not needed during bedtime |
| `stop_radio` | 14/18 | Stop Music Assistant radio | Standard only — not needed during bedtime |
| `voice_play_bedtime_audiobook` | 3/18 | Start bedtime audiobook | Bedtime only |
| `voice_set_bedtime_countdown` | 3/18 | Set sleep countdown timer | Bedtime only |
| `voice_skip_audiobook` | 3/18 | Skip to next audiobook chapter | Bedtime only |
| `get_current_time_12h` | 2/18 | Get formatted time string | **REMOVE** — L1 hot context makes this obsolete |

**Findings:** Clean split between standard tools (media controls) and bedtime tools (audiobook/countdown). Validates Option B consolidation.

### Sub-Entry Consolidation Plan (Decision #43)

**Decision: Option B — Two sub-entries per agent (Standard + Bedtime). Target: 8 total, down from 18.**

**Rationale:** With L1 hot context providing time, presence, media, and house mode to every agent, the only reason for separate sub-entries is **different tool sets**. Bedtime has genuinely different tools (audiobook, countdown) and safety concerns (user is falling asleep). Everything else — verbose, music, coming-home — is prompt flavor that L1 context handles naturally.

**Consolidation mapping:**

| Current sub-entries (per agent) | Consolidated to | Why |
|--------------------------------|----------------|-----|
| Standard | **→ Standard** | Base agent |
| Verbose | **→ Standard** | L1 context determines response depth; no separate tools needed |
| Music | **→ Standard** | L1 reports media state; same tools as standard |
| Coming Home | **→ Standard** | L1 reports presence transitions; same tools |
| Bedtime | **→ Bedtime** | Different tool set (audiobook, countdown); safety-sensitive mode |

**Per-agent result:**

| Agent | Standard sub-entry | Bedtime sub-entry |
|-------|-------------------|-------------------|
| Rick | `conversation.rick_standard` | `conversation.rick_bedtime` |
| Quark | `conversation.quark_standard` | `conversation.quark_bedtime` |
| Deepee | `conversation.deepee_standard` | `conversation.deepee_bedtime` |
| Kramer | `conversation.kramer_standard` | `conversation.kramer_bedtime` |

**Standard sub-entry tools:** `execute_service`, `execute_services`, `memory_tool`, `web_search`, `pause_media`, `shut_up`, `stop_radio`

**Bedtime sub-entry tools:** `execute_service`, `execute_services`, `memory_tool`, `web_search`, `voice_play_bedtime_audiobook`, `voice_set_bedtime_countdown`, `voice_skip_audiobook`

**Migration path:** Create new consolidated sub-entries → update blueprint `!input` defaults → test each blueprint → delete old sub-entries. Non-destructive: old sub-entries remain until all blueprints are migrated.

**Blueprint impact:** Blueprints that currently select mode-specific agents (e.g., `conversation.rick_extended_coming_home_2`) will select `conversation.rick_standard` instead. Bedtime blueprints select `conversation.rick_bedtime`. The `agent_randomizer` simplifies to 4 standard entities.

### Standard Agent Prompt Template

All agent prompts must follow this structure. Sections marked **UNIVERSAL** are identical across all agents. Sections marked **PERSONA** are unique per character. This eliminates the current inconsistency where 18 prompts cover the same ground differently.

**Template structure (in order):**

```
┌─────────────────────────────────────────┐
│ 1. IDENTITY BLOCK [PERSONA]             │
│    Who am I? Character voice, traits,   │
│    speech patterns, mannerisms.          │
│    ~200-400 tokens                       │
├─────────────────────────────────────────┤
│ 2. HOT CONTEXT INJECTION [UNIVERSAL]    │
│    {{ states('sensor.ai_hot_context') }}│
│    ~100-200 tokens (dynamic)            │
├─────────────────────────────────────────┤
│ 3. MULTI-AGENT AWARENESS [UNIVERSAL]    │
│    Other personas exist. Check memory   │
│    for recent context. Who spoke last.  │
│    ~100 tokens                          │
├─────────────────────────────────────────┤
│ 4. MEMORY INSTRUCTIONS [UNIVERSAL]      │
│    How to use memory_tool. Scopes.      │
│    When to store vs retrieve.           │
│    ~150 tokens                          │
├─────────────────────────────────────────┤
│ 5. TTS RULES [UNIVERSAL]               │
│    Output formatting for speech. No     │
│    markdown, no emojis, max length.     │
│    SSML rules if applicable.            │
│    ~100 tokens                          │
├─────────────────────────────────────────┤
│ 6. TOOL USAGE POLICY [UNIVERSAL]        │
│    When to call services vs respond     │
│    verbally. Error handling. Safety.    │
│    ~100 tokens                          │
├─────────────────────────────────────────┤
│ 7. PERSONALITY RULES [PERSONA]          │
│    Character-specific behavioral rules. │
│    Mood system (time-based persona      │
│    shifts). Catchphrases. Boundaries.   │
│    ~200-400 tokens                      │
├─────────────────────────────────────────┤
│ 8. MODE-SPECIFIC INSTRUCTIONS [VARIANT] │
│    Bedtime sub-entry: audiobook rules,  │
│    countdown behavior, sleep safety.    │
│    Standard sub-entry: empty or minimal.│
│    ~0-150 tokens                        │
└─────────────────────────────────────────┘

Target total: 950-1600 tokens (~3,800-6,400 chars)
Current average: ~9,500 chars = ~2,375 tokens (OVER BUDGET)
```

**Why this order matters:**

- Identity first: LLM attention is strongest at the start. Character voice must anchor the response.
- Hot context second: situational awareness immediately after identity. The agent knows who it is and where/when it is before processing anything else.
- Universal sections in the middle: these are "plumbing" — important but not attention-critical.
- Personality rules near the end: character-specific behavioral constraints that the LLM can reference but don't need prime attention real estate.
- Mode-specific last: only relevant for bedtime variant; empty for standard.

**Token budget (DC-4 compliance):**

Current prompts average ~2,375 tokens before entity list injection. The `exposed_entities` list adds variable tokens depending on how many entities are exposed. With L1 replacing per-prompt context building and consolidation removing redundant variants, target is:

- System prompt (sections 1-8): ≤1,200 tokens
- L1 hot context injection: ~150 tokens
- Exposed entity list: ~300-500 tokens (audit needed — currently exposing too many?)
- **Total prompt overhead: ≤1,850 tokens per call**

This leaves ~2,150 tokens for the actual conversation turn (user message + tool calls + response) within a 4K-token budget window, or much more with GPT-4o's 128K context.

**Implementation:** Each agent's prompt is built from a base template with Jinja2 includes or a package YAML that assembles sections. The universal sections exist once and are shared. Only sections 1, 7, and 8 differ per agent/variant.

**Baseline prompt (current Rick Extended) will be documented in build phase** — it becomes the "before" reference for refactoring. Not included here to avoid the architecture doc becoming a prompt repository.

---

## Updated Architecture Diagram

```
┌──────────────────────────────────────────────────────────────┐
│                    WAKE WORD DETECTION                        │
│              ESPHome Voice PE Satellites                      │
└──────────────┬───────────────────────────────────┬───────────┘
               │                                   │
        Named trigger                        Generic trigger
        ("Hey Rick")                         (no name)
               │                                   │
               ▼                                   ▼
┌──────────────────────────────────────────────────────────────┐
│                 AGENT DISPATCHER (6-level)                    │
│              agent_dispatcher.py (Pyscript)                  │
│                                                              │
│  1. Explicit name  →  direct route                           │
│  2. Wake word map  →  pipeline lookup                        │
│  3. Continuity     →  last_agent within window               │
│  4. Topic keywords →  persona affinity match                 │
│  5. Time-of-day    →  era helper defaults                    │
│  6. Random         →  weighted fallback                      │
│                                                              │
│  Cache: personas, entity_map, wake_word_map, pipeline_map    │
└──────────────────────────────┬───────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────┐
│           CONVERSATION AGENTS (HA Voice Assistants)           │
│              8 pipelines = 4 personas × 2 variants           │
│                                                              │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐       │
│  │   RICK   │ │  QUARK   │ │ DEADPOOL │ │  KRAMER  │       │
│  │          │ │          │ │ (Deepee) │ │          │       │
│  │ standard │ │ standard │ │ standard │ │ standard │       │
│  │ bedtime  │ │ bedtime  │ │ bedtime  │ │ bedtime  │       │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘       │
│       │             │            │             │             │
│       └─────────────┴─────┬──────┴─────────────┘             │
│                           │                                  │
│                    SHARED CONTEXT                             │
│  ┌─────────────────────────────────────────────────────┐     │
│  │ L1: sensor.ai_hot_context  (always injected)        │     │
│  │ L2: script.voice_memory_tool (on demand)            │     │
│  │ L3: Calendar/Email services (on demand/pre-staged)  │     │
│  │                                                     │     │
│  │ Self-awareness: last_agent, last_topic, last_time   │     │
│  └─────────────────────────────────────────────────────┘     │
└──────────────────────────────────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────────────────┐
│              TTS QUEUE MANAGER (tts_queue.py)                 │
│                                                              │
│  Priority queue → presence-aware speaker targeting           │
│  Cache: static/daily/session tiers (DC-10)                   │
│  Playback: tts.speak or cached media_player.play_media       │
│  ElevenLabs per-persona voices → ESPHome Voice PE speakers   │
└──────────────────────────────────────────────────────────────┘
```

---

## Inter-Agent Communication Patterns

Five patterns for agent-to-agent interaction, ranging from simple sequential TTS to invisible background coordination. All depend on the self-awareness helpers and shared L2 memory established in the Multi-Agent System section above.

### Pattern 1: Reactive Banter (External)

Agent A responds to the user. A post-response hook evaluates whether a second voice should chime in — a heckle, a correction, a commentary. Agent A's response text feeds into Agent B's conversation entity as context ("React to what Rick just said: [response]"). B's output goes to B's TTS. Sequential playback on the same speaker.

**Trigger:** Probabilistic (20% chance) or contextual (topic affinity). Needs a cooldown timer and relevance gate to prevent annoyance.

**Infrastructure:** Post-response script that chains two `conversation.process` + `tts.speak` calls. No new architecture — orchestration logic in the calling blueprint.

**Risk:** Gets annoying fast without tight gating.

### Pattern 2: Deliberation (Internal → External Summary)

User asks a complex question. Instead of one agent answering, the dispatcher routes it through 2-3 agents internally. Each produces a response. A synthesis agent (meta-agent — fifth conversation entity) merges them into one answer or presents the disagreement.

User hears: *"Rick says recalibrate the flux capacitor. Quark says sell it. I'm going with Rick."*

**Infrastructure:** Meta-agent conversation entity with system prompt: "You are the moderator. Given these responses from Rick, Quark, and Deepee, synthesize." Three LLM calls + synthesis = 4 total. Latency: 8-15 seconds for voice response.

**When to use:** High-stakes decisions only. Not for "what time is it."

### Pattern 3: Handoff with Commentary (External)

The active agent recognizes it's out of its depth or that another persona fits better. It signals a handoff via structured output (`[HANDOFF:quark]` tag or tool call). The orchestrating blueprint parses this, feeds context to the next agent, chains TTS.

Rick: *"Look, I could explain the financial implications, but — [burp] — that's Quark's whole thing."*
Quark: *"Thank you, Rick. Now, about your portfolio..."*

**Infrastructure:** Handoff tag parsing in the orchestrating blueprint. Self-awareness helpers make it feel natural — Quark *knows* Rick just punted. Two LLM calls.

**Decision:** This is the most natural-feeling pattern. Recommended as the first multi-agent pattern to implement.

### Pattern 4: Argument (External, Staged)

Theatrical mode. Two agents openly disagree. A "debate" blueprint takes a topic, two agent entities, generates opposing prompts from the same seed, calls both, plays both sequentially.

**Infrastructure:** Debate script blueprint. Could add a third agent as "judge." Natural home: bedtime negotiation system (should you stay up? Rick says no, Quark says profit from more entertainment).

**Use case:** Entertainment, bedtime negotiation, decision support.

### Pattern 5: Whisper Network (Internal Only)

Agents share context through L2 memory without the user hearing the exchange. Rick stores: `memory_set("Miquel seemed stressed today", tags=["mood", "observation"])`. Later, Quark searches L2, finds Rick's note, adjusts his tone — softer sell, less aggressive.

**Infrastructure:** Running. All four agents share the same L2 database. `agent_whisper.py` writes interaction logs, mood observations, and topic slugs to L2 after each conversation. Additionally, `_auto_update_keywords()` feeds recent topics back into the dispatcher's keyword affinity routing (Decision #53), closing the loop between conversation content and persona selection.

**Decision:** Subtlest and most powerful pattern. User never hears it, just notices the house feels more responsive over time.

### The Conductor Problem

All five patterns need someone deciding *when* to invoke multi-agent behavior. Three options:

| Option | Description | Pros | Cons |
|--------|-------------|------|------|
| **A: Blueprint-driven** | Specific blueprints hardcode multi-agent moments | Controlled, predictable | Rigid, manual |
| **B: Agent-driven** | Active agent decides via tool calls (`call_agent`) | Most flexible | Loop risk (Rick→Quark→Rick→∞), LLM abuse |
| **C: Dispatcher-driven** | Intelligent dispatcher evaluates every interaction | Endgame architecture | Depends on L1+L2 operational |

**Decision:** Start with A, layer in B for handoffs (Pattern 3), build toward C. The conductor must always be **configurable** — blueprints should expose which patterns are enabled, with what probability, and between which agents. Never hardcode the orchestration mode.

### Multi-Speaker Spatial Audio

Extension of Patterns 1, 3, and 4: instead of sequential TTS on one speaker, agents speak on *different* physical speakers simultaneously.

**Concept:** Rick's voice from the office satellite, Quark's from the living room. They argue across physical space. The user is between two AI personas.

**Implementation:** Two parallel `tts.speak` calls to different `media_player` entities. HA processes service calls asynchronously — they overlap naturally. Stagger by 500ms-1s so they *overlap* without becoming unintelligible.

**Three spatial modes:**

| Mode | Description | Use Case |
|------|-------------|----------|
| Co-located debate | Two speakers in same/adjacent rooms | Banter, argument patterns |
| Room-to-room handoff | Active agent in current room, next agent in destination room | Follow-me with persona persistence |
| Surround argument | 3-4 speakers, different persona each | Party trick, "house meeting" |

**Ducking implications:** The ducking refcount system assumes one voice interaction at a time. Multi-speaker dialogue means refcount can hit 2+ simultaneously. The `duck_refcount_watchdog` needs a "multi-agent dialogue" flag so it doesn't treat this as a stuck state.

**Decision:** Spatial audio is a nice-to-have extension of the core patterns. Implement core patterns first (single speaker), add spatial routing later.

---

## Presence-Based Pattern Recognition & Predictions

The FP2 sensors report zone presence with timestamps. The HA recorder database has months of this data, currently unused for prediction. This section defines how to transform historical presence data into a predictive engine.

### Sequence Detection (Transition Probabilities)

The simplest prediction: given (current_zone, time_of_day, day_type), what's the probable next zone and when?

Example: "Miquel entered the kitchen at 11:15 PM. Historical data says 85% of the time, he's in the bedroom within 12 minutes."

**Action on prediction:** Don't trigger automations — *arm* them. Set `input_boolean.ai_bedtime_predicted` so the bedtime routine launches instantly when bedroom presence actually fires. Shave 3-5 seconds off response time. The house anticipates.

**Proactive use:** If kitchen-at-11PM predicts bedroom-in-12-minutes with high confidence, the proactive system says *"Heading to bed soon? Want me to queue your audiobook?"* while you're still in the kitchen. Concierge, not nag.

### Routine Fingerprinting

Zoom out from single transitions to full sequences. A routine fingerprint is an ordered sequence of zones with typical dwell times.

Example weeknight fingerprint: `living_room → kitchen → bathroom → bedroom` (avg 47 min total).

**Detection:** Compare current zone + time against known fingerprints. "Miquel just hit step 3 of 4 in his weeknight bedtime routine."

**Deviation detection:** Still in the living room at 1 AM when the fingerprint predicts bedroom by midnight = late movie, insomnia, or guests. The system can ask instead of assume: *"Burning the midnight oil or should I keep the bedtime routine on standby?"*

**Storage:** Fingerprints are L2 data: `memory_set("weeknight_routine", value="living_room→kitchen→bathroom→bedroom, avg_duration=47min", tags=["routine", "pattern", "weeknight"])`. Detection of current position in a routine is L1: `input_text.ai_routine_stage` = `"weeknight_bedtime:step_3_of_4"`.

### Predictive Scheduling

Combine routine fingerprints (L2) with calendar data (L3) and real-time state (L1).

Example: L3 knows 7 AM meeting tomorrow. L2 knows bedtime routine takes 47 minutes. L1 knows routine hasn't started at 11:30 PM. Calculated recommendation: *"You need to be up by 6:15. Your routine takes 47 minutes. Start winding down in about 15 minutes for 7 hours of sleep."*

This makes the bedtime escalation trigger timing *intelligent* instead of fixed-schedule.

### Learning Loop (Feedback)

The system makes predictions. Outcomes become training signals.

- Predicted "bedroom in 12 min" → actually went to bed in 10 → reinforce, bump confidence
- Predicted "bedroom in 12 min" → went back to living room → weaken

**Implementation:** Frequency table per `(zone, time_bucket, day_type)` tuple. Store probability distribution of next zones + dwell times. Update on every transition. This is a Markov chain with a time dimension — implementable in ~200 lines of Pyscript with the existing SQLite database.

No ML libraries needed. No external services. Statistics on top of data already being collected.

### Creep Factor Gate (Hard Design Constraint)

**Rule: Predictions inform timing and preparation, never announcements about behavior.**

The system should never say *"I notice you usually go to the bathroom at 11:23 PM."* That's surveillance. It should say *"Want me to start your bedtime routine?"* — using the prediction invisibly to improve timing.

The user should feel like the house is responsive, not like it's watching through a one-way mirror.

### Multi-Agent Integration

Behavioral deviation from routine = state change signal for the dispatcher. Still up way late + pacing between rooms = stress or insomnia. The dispatcher could select a different persona based on routine deviation without explicit mood detection (no cameras/microphones for mood — sensor-only behavioral proxy).

### Prediction Engine Build Path

| Step | Description | Layer |
|------|-------------|-------|
| 1 | Data extraction — Pyscript service queries recorder for zone transitions, builds frequency tables | L2 |
| 2 | Pattern storage — New L2 table or memory entries for routine fingerprints | L2 |
| 3 | Transition predictor — Template sensor: given (zone, time, day_type) → predicted_next_zone + confidence + ETA | L1 |
| 4 | Routine position tracker — `input_text.ai_routine_stage` | L1 |
| 5 | Feedback loop — Automation compares predictions to actuals, updates frequency tables | L2 |
| 6 | Integration hooks — Feed predictions into bedtime timing, proactive triggers, dispatcher signals | All |

---

## Identity Layer & Multi-User Architecture

### The Problem

The entire system is implicitly single-user. Every blueprint assumes "presence detected = Miquel." The moment a second person is home, every personal automation becomes a liability — Rick screaming "GET OUT OF BED" at Jessica is not a great look.

The FP2 can tell how many bodies are in a zone (poorly — 30-second cloud poll, lossy), but cannot identify *who*. HomeKit gives fast binary presence but it's anonymous. We've established in previous sessions that reliable per-person room tracking is a no-go with current hardware.

### Design Principle: Design for Two, Implement for One

Jessica will move in. Every helper, template sensor, and blueprint input should be designed with the assumption of two users, even if the single-user path is built first. Expand when she moves in.

### Identity Signals

Three signals to fuse for identity confidence:

| Signal | Source | Coverage | Reliability | Latency |
|--------|--------|----------|-------------|---------|
| G3 face recognition | Aqara Camera Hub G3 (cloud integration) | One room (camera FOV) | Good when visible | Seconds (cloud poll) |
| Phone presence | `device_tracker` (WiFi/BLE) | Whole house (home/away) | High for home/away, no room-level | Real-time |
| Guest mode toggle | `input_boolean.guest_mode` (Alexa-exposed) | Manual | 100% when used | Instant |

**Note:** The G3 face recognition identity data exposure through the HACS integration needs investigation — may only expose "face detected" boolean, not *whose* face. To be verified.

### Confidence Model

Template sensor fusing all signals into a per-user confidence score:

```
sensor.ai_identity_confidence_miquel:
  base: 0
  phone_home: +40
  face_recognized_recently (<5min): +50
  face_recognized_stale (>5min): +20
  guest_mode_off: +10
  people_count == 1: +10
  people_count > 1: -30
  phone_not_home: -80
```

| Threshold | Behavior |
|-----------|----------|
| > 70 | Full personal automation (bedtime, proactive, music, personas) |
| 30–70 | Limited automation (lights yes, personal nags no) |
| < 30 | Guest/polite mode — household automations only |

### Household vs Personal Automation Split

| Category | Examples | Identity Gate |
|----------|----------|---------------|
| **Household** | Bathroom lights, climate, UPS notifications, smart-bathroom | None — fires for anyone |
| **Personal** | Bedtime nags, wake-up alarms, proactive calendar announcements, music taste, agent personas | Confidence > 70 for target user |
| **Shared** | Coming home welcome, dinner reminders, shared calendar events | Any resident identified |

### Cohabitation Scenarios

| Scenario | Detection | System Behavior |
|----------|-----------|-----------------|
| Both home, different rooms | Phone + FP2 per room | Independent automation streams per user |
| Both home, same room | People count ≥ 2 | Household-only; suppress personal stuff |
| One leaves, one stays | Phone departure event | Remaining person's automations activate, departed person's go dormant |
| Conflicting schedules | Per-user bedtime/wake helpers | Each user's sleep system operates independently |
| Shared triggers (coming home) | G3 face at entrance | Personalized welcome: "Welcome home Miquel, Jessica's in the living room" |

### Per-User Scoping

**L2 Memory Scopes:**

| Scope | Contents | Who Can Access |
|-------|----------|----------------|
| `miquel` | Birthday, preferences, routines, bedtime patterns | Agents when identity = Miquel |
| `jessica` | Birthday, preferences, routines | Agents when identity = Jessica |
| `household` | Shared facts, anniversary, shared preferences | All agents always |

**Privacy fence:** When identity = Jessica, agents query `jessica` + `household` scopes ONLY. Cannot access `miquel` scope. Prevents accidental disclosure ("Rick blurting out what you bought her for her birthday").

**Notification routing:** Personal notifications (email, calendar) only play on room speakers when the target user's phone is nearby. If phone isn't in proximity, route to phone push notifications instead.

### Per-User Helpers (Proposed)

Existing helpers that need per-user variants when Jessica moves in:

```
# Bedtime system
input_boolean.bedtime_active → input_boolean.bedtime_active_miquel / _jessica
input_boolean.bedtime_global_lock → per-user or keep global with multi-user logic

# Wake-up system
input_boolean.rick_wake_up_snooze → input_boolean.wakeup_snooze_miquel / _jessica
input_datetime.wake_up_time → input_datetime.wake_up_time_miquel / _jessica

# Identity
input_text.ai_last_identified_person (NEW)
input_datetime.ai_last_identification_time (NEW)
input_boolean.guest_mode (NEW — Alexa-exposed)
input_text.ai_home_occupants (NEW — comma-separated: "miquel,jessica" or "miquel")
```

### Per-User Agent Preferences

Stored in L2, scoped per user:

- Preferred persona (maybe Jessica likes Quark, hates Rick)
- Voice interaction preference (full personas vs neutral TTS vs no voice at all)
- Proactive announcement tolerance (all, important-only, none)
- Music taste profile (for follow-me queue selection)

The dispatcher reads per-user preferences from L2 before selecting persona.

### Blueprint Impact Summary

Every personal automation blueprint needs:
1. A `target_user` input or derived identity from `sensor.ai_identity_confidence_{user}`
2. A confidence threshold condition before firing personal actions
3. TTS routing that considers both "where" (presence) and "who" (identity)
4. Per-user helper references instead of global helpers

### The Jessica Problem (Pragmatic First Step)

Most common multi-user scenario is not a house party — it's Jessica being over. Two-person situation:
- Register Jessica's face in G3
- Add her phone as device tracker
- Both phones home + people count ≥ 2 → couple mode
- Your phone home + hers not → single user, full automation
- Her phone home + yours not → she's home alone, minimal automation
- `input_boolean.guest_mode` for anyone else

This covers 95% of real-world scenarios without room-level person tracking.

---

## Blueprint Inventory & Architecture Mapping

The `madalone` namespace contains 33 automation blueprints and 23 script blueprints (plus 1 luuquangvu script blueprint). They group into functional domains that map onto the three-layer system, the multi-agent system, and the voice pipeline infrastructure.

### Domain 1: Voice Pipeline Infrastructure

These blueprints manage the audio plumbing — ducking, volume control, media pause/resume during voice interactions. They are **layer-agnostic** infrastructure that all voice interactions depend on.

| Blueprint | Type | Purpose |
|-----------|------|---------|
| `voice_pe_duck_media_volumes` | Auto | Duck media volumes when Voice PE starts listening |
| `voice_pe_restore_media_volumes` | Auto | Restore volumes after conversation ends |
| `voice_pe_resume_media` | Auto | Resume paused media after conversation |
| `duck_refcount_watchdog` | Auto | Prevent stuck ducking states (refcount safety net) |
| `alexa_ma_volume_sync` | Auto | Sync Alexa ↔ Music Assistant volume levels |
| ~~`chime_tts_simple_announce`~~ | ~~Script~~ | Removed — TTS queue manager handles announcements directly |

**L1 dependency:** These read/write the ducking helpers (`input_boolean` flags, `input_number` pre-duck volumes) that L1's `sensor.ai_hot_context` reports on. The template sensor reflects ducking state; these blueprints manage it.

### Domain 2: Voice Tool Scripts (LLM-Exposed)

Scripts that the LLM conversation agents call as tools during voice interactions. These are the agent's "hands" — how it controls media, queries content, and takes actions.

| Blueprint | Type | Purpose | Exposed To |
|-----------|------|---------|------------|
| `voice_shut_up` | Script | Pause all active media | Assist |
| `voice_stop_radio` | Script | Stop Music Assistant radio playback | Assist |
| `voice_media_pause` | Script | Pause active media (selective) | Assist |
| `voice_active_media_controls` | Auto | Kodi / MA / Spotify / Alexa media controls | Assist |
| `voice_kodi_play_content` | Script | LLM-driven Kodi content search + play | Assist |
| `voice_play_bedtime_audiobook` | Script | Start bedtime audiobook via MA | Assist |
| `voice_set_bedtime_countdown` | Script | Set bedtime countdown timer | Assist |
| `llm_voice_script` | Script | LLM-enhanced Music Assistant voice requests | Assist |
| `memory_tool_full_llm` (luuquangvu) | Script | L2 memory set/get/search/forget | Assist |

**L1 dependency:** Media controls need to know what's playing (from `sensor.ai_hot_context`).
**L2 dependency:** `memory_tool_full_llm` IS L2. `voice_kodi_play_content` could use L2 to remember preferences.
**Multi-agent:** All personas share these tools. The exposed script is agent-agnostic.

### Domain 3: Music & Presence Automation

Blueprints that react to physical presence to manage music playback across rooms. Presence is an L1 data source; these blueprints consume it.

| Blueprint | Type | Purpose |
|-----------|------|---------|
| `alexa_presence_radio` | Auto | Start radio in room when presence detected |
| `alexa_presence_radio_stop` | Auto | Stop radio when room vacated |
| `music_assistant_follow_me_idle_off` | Auto | Turn off MA player when idle + presence lost |
| `music_assistant_follow_me_multi_room_advanced` | Auto | Advanced multi-room follow-me with queue handoff |
| `announce_music_follow_me` | Script | TTS announcement of follow-me music state |
| `announce_music_follow_me_llm` | Script | LLM-driven follow-me announcement |
| `mass_llm_enhanced_assist_blueprint_en` | Auto | Music Assistant voice control with LLM enhancement |

**L1 dependency:** All read FP2 presence sensors. Music state feeds into `sensor.ai_hot_context`.
**Multi-agent:** `announce_music_follow_me_llm` selects a persona for the announcement. Currently hardcoded agent — future dispatcher candidate.

### Domain 4: Proactive Announcements

Blueprints that initiate voice interactions without user prompt — the house talks first. These are the primary consumers of L1 context and potential consumers of L2/L3.

| Blueprint | Type | Purpose |
|-----------|------|---------|
| `proactive` | Auto | Presence-based suggestions (template-driven) |
| `proactive_llm` | Auto | Presence-based suggestions (direct LLM call) |
| `proactive_llm_sensors` | Auto | Presence-based suggestions with sensor data injection |
| `notification_follow_me` | Auto | Route notifications to current room via TTS |
| `email_follow_me` | Auto | Route email notifications via presence-aware TTS |
| `notification_replay` | Script | Replay missed notifications on demand |

**L1 dependency:** All read presence sensors to determine where to announce. `proactive_llm_sensors` injects sensor readings into LLM context — this is proto-L1 (the kind of context building that `sensor.ai_hot_context` will centralize).
**L2 dependency:** `notification_follow_me` v3.18.0 spec includes memory buffer integration. Proactive blueprints could use L2 to avoid repeating announcements.
**L3 dependency:** `email_follow_me` IS an L3 consumer (IMAP). Future: proactive morning briefings pull from L3 calendar.
**Multi-agent:** `notification_follow_me` and proactive blueprints select a persona for delivery. Currently use agent inputs or randomizer — future dispatcher candidates.

### Domain 5: Bedtime System

A complex multi-blueprint system managing the transition from awake → bedtime → sleep. Multiple LLM interactions, media control, negotiation logic, and escalation.

| Blueprint | Type | Purpose |
|-----------|------|---------|
| `bedtime_routine` | Auto | LLM-driven goodnight with audiobook |
| `bedtime_routine_plus` | Auto | LLM-driven goodnight with Kodi |
| `proactive_bedtime_escalation` | Auto | Presence-based bedtime nags with inline routine |
| `bedtime_last_call` | Auto | Final bedtime announcement before hard cutoff |
| `goodnight_negotiator_hybrid` | Script | Hybrid negotiation (template + LLM fallback) |
| `goodnight_negotiator_llm_driven` | Script | Pure LLM bedtime negotiation with agent personas |
| `goodnight_routine_music_assistant` | Script | Bedtime music setup via MA |
| `bedtime_media_play_wrapper` | Script | Media play abstraction for bedtime routines |
| `voice_play_bedtime_audiobook` | Script | Start audiobook for bedtime |
| `voice_set_bedtime_countdown` | Script | Set countdown timer for bedtime |

**L1 dependency:** Heavy. Reads/writes `bedtime_active`, `bedtime_global_lock`, presence sensors, media state. Bedtime mode is a core L1 state flag.
**L2 dependency:** Bedtime negotiator could use L2 to remember "Miquel usually negotiates for 15 more minutes" or "last audiobook was chapter 7." The `bedtime_agent_prompt_rick.md` and `bedtime_agent_prompt_quark.md` files are persona-specific system prompts — these would inject L1 context.
**Multi-agent:** `goodnight_negotiator_llm_driven` explicitly supports agent personas. `proactive_bedtime_escalation` selects agent for nag delivery.

### Domain 6: Wake-Up System

Mirror of bedtime — manages the transition from sleep → awake. Escalating alarms, presence detection, snooze/stop logic.

| Blueprint | Type | Purpose |
|-----------|------|---------|
| `wake-up-guard` | Auto | Snooze/stop alarm with TTS + mobile fallback |
| `escalating_wakeup_guard` | Auto | Escalating alarm with inverted presence (get out of bed) |
| `wake_up_guard_external_alarm` | Auto | External alarm trigger (Android / Alexa) |
| `wakeup_guard_mobile_notify` | Auto | Mobile notification snooze/stop handler |
| `llm_alarm` | Auto | Wake-up alarm with LLM context |
| `rickyellsplusalexa` | Script | Rick TTS + Alexa music wake-up |
| `wakeup_chime` | Script | Simple chime for wake-up |
| `wakeup_music_alexa` | Script | Alexa-based wake-up music |
| `wakeup_music_ma` | Script | Music Assistant wake-up music |

**L1 dependency:** Reads/writes `rick_wake_up_snooze`, `rick_wake_up_stop` helpers. Wake schedule from `input_datetime` helpers feeds L1.
**L2 dependency:** `llm_alarm` could use L2 to personalize wake-up message ("you have a meeting at 9" from calendar memory).
**L3 dependency:** `llm_alarm` is a natural L3 consumer — pull today's calendar for the wake-up briefing.
**Multi-agent:** `rickyellsplusalexa` is Rick-specific. Other wake-up blueprints are agent-agnostic but could use dispatcher for persona selection.

### Domain 7: Multi-Agent Management

Blueprints that handle persona selection and agent coordination.

| Blueprint | Type | Purpose |
|-----------|------|---------|
| `agent_randomizer` | Script | Random persona selection for general voice interactions |

**Multi-agent:** This IS the current agent selection system. Future dispatcher replaces/extends it.
**L1 dependency:** Future dispatcher reads L1 for time-of-day and context signals.
**L2 dependency:** Future dispatcher reads L2 for user persona preferences.

### Domain 8: Coming Home

| Blueprint | Type | Purpose |
|-----------|------|---------|
| `coming_home` | Auto | AI-driven welcome-home announcement |

**L1 dependency:** Presence trigger (device tracker or FP2). Reads house state for context.
**L2 dependency:** Could personalize welcome ("welcome home, your package arrived while you were out" from L2 memory).
**L3 dependency:** Natural L3 consumer — "you have 2 emails and a calendar event tonight."
**Multi-agent:** Uses agent input — dispatcher candidate.

### Domain 9: Non-Voice Utility

Blueprints that don't involve voice or the context architecture at all.

| Blueprint | Type | Purpose |
|-----------|------|---------|
| `smart-bathroom` | Auto | Occupancy-based light control |
| `temp_hub` | Auto | Temperature-triggered cooling fan |
| `ups_notify` | Auto | UPS power event notifications |
| `automation_trigger_mon` | Auto | Debug: monitor automation triggers |

**Layer dependency:** None. These are standalone HA automations.

---

### Blueprint ↔ Layer Dependency Matrix

```
                          L1    L2    L3    Multi-Agent
                         Hot   Warm  Cold   Aware
                         ────  ────  ────  ──────────
Voice Pipeline Infra      ✓     ·     ·      ·
Voice Tool Scripts        ✓     ✓     ·      ·  (shared tools)
Music & Presence          ✓     ·     ·      △  (announce_llm)
Proactive Announcements   ✓     △     ✓      △  (agent selection)
Bedtime System            ✓     △     ·      ✓  (persona prompts)
Wake-Up System            ✓     △     △      △  (persona selection)
Multi-Agent Management    △     △     ·      ✓  (IS the system)
Coming Home               ✓     △     △      △  (agent selection)
Non-Voice Utility         ·     ·     ·      ·

Legend: ✓ = active dependency   △ = future/planned   · = none
```

### Context Building: Current vs Future

**Current state:** Each LLM-calling blueprint builds its own context block in `variables:`. This means:
- Duplicate Jinja2 across 15+ blueprints
- Inconsistent context (some include media state, some don't)
- No shared awareness between blueprints
- Agent self-awareness is per-blueprint, not centralized

**Future state (with L1):** All blueprints read `sensor.ai_hot_context` for situational awareness. Blueprints that call LLM agents pass it via the system prompt. Context is consistent, centralized, and maintained in one place.

**Blueprints that currently build their own context and will benefit from L1 centralization:**
- `proactive_llm_sensors` — heaviest context builder (sensor data injection)
- `proactive_llm` — builds time/presence context
- `bedtime_routine` / `bedtime_routine_plus` — builds time/media/mode context
- `notification_follow_me` — builds presence/media context for announcement routing
- `coming_home` — builds arrival context
- `llm_alarm` — builds morning context
- `goodnight_negotiator_llm_driven` — builds bedtime state context
- `announce_music_follow_me_llm` — builds music/presence context

### Blueprint → Agent Call Map

Every blueprint that calls `conversation.process` is a Task 4 refactoring target. This map documents what each blueprint sends to the LLM so we know exactly what L1 replaces.

**Legend:** `!input` = user-selectable agent. `{{ var }}` = variable-driven. Context = what the blueprint injects into the `text:` field alongside the task prompt.

| Blueprint | Type | conv.process calls | Agent selection | Context injected (L1 replaces) | Mode |
|-----------|------|-------------------|----------------|-------------------------------|------|
| `proactive_llm` | Auto | 2 | `!input conversation_agent` | area, time_of_day, trigger_type, current_time | Standard |
| `proactive_llm_sensors` | Auto | 2 | `!input conversation_agent` | area, time, sensor readings (heaviest context builder) | Standard |
| `proactive_bedtime_escalation` | Auto | 8 | `{{ bedtime_conversation_agent }}` + `{{ proactive_conversation_agent }}` (two separate agents) | area, time, bedtime state, media | Bedtime |
| `bedtime_routine` | Auto | 5 | `{{ conversation_agent }}` (default: `quark_extended_bedtime`) | bedtime_prompt_tpl, countdown, mode flags | Bedtime |
| `bedtime_routine_plus` | Auto | 6 | `{{ conversation_agent }}` (default: `quark_extended_bedtime`) | bedtime_prompt_tpl, countdown, negotiation flags, Kodi state | Bedtime |
| `bedtime_last_call` | Auto | 1 | `!input conversation_agent` | area, current_time, sensor_context | Bedtime |
| `coming_home` | Auto | 1 | `{{ conversation_agent_id }}` via `!input` | ai_greeting_prompt (user-defined), arrival context | Standard |
| `email_follow_me` | Auto | 2 | `!input conversation_agent` | email body, sender, notification_prompt, agent_name | Standard |
| `notification_follow_me` | Auto | 3 | `{{ llm_agent }}` | notification body, sender display name, agent_name, conversation_id | Standard |
| `escalating_wakeup_guard` | Auto | 1 | `{{ v_llm_agent }}` | wake-up stage, area, time | Standard |
| `llm_alarm` | Auto | 1 | `{{ v_conversation_agent }}` | morning context, alarm time | Standard |
| `wake-up-guard` | Auto | 1 | `{{ v_llm_agent_id }}` | LLM prompt (user input), wake-up state | Standard |
| `mass_llm_enhanced_assist_blueprint_en` | Auto | 1 | `!input` (conversation_agent selector) | MA queue state, player context | Standard |
| `goodnight_negotiator_hybrid` | Script | 23 | `!input conversation_agent` | area, user_name, time_ctx_line, media_ctx_line via `context_block` | Bedtime |
| `goodnight_negotiator_llm_driven` | Script | 5 | `{{ agent_id }}` via `!input` | negotiation state, bedtime context, countdown | Bedtime |
| `announce_music_follow_me_llm` | Script | 1 | `{{ llm_agent or omit }}` | music state, player, area | Standard |
| `notification_replay` | Script | 1 | `!input conversation_agent` | stored notifications, replay context | Standard |
| `agent_randomizer` | Script | 1 | `{{ randomizer.agent }}` | none (pure routing) | Standard |

**Key findings:**

1. **18 blueprints**, **65 total `conversation.process` calls** — every one of these passes context that L1 centralizes.
2. **All use `!input` or variable-based agent selection** — no hardcoded agents. The dispatcher (Task 11) can plug in cleanly.
3. **Context patterns are consistent:** area + time + media + mode. Exactly what `sensor.ai_hot_context` provides.
4. **Bedtime is distinct:** 6 blueprints with 48 calls use bedtime-specific context (countdown, negotiation, audiobook state). This validates Option B consolidation — bedtime needs its own sub-entry.
5. **`goodnight_negotiator_hybrid` alone has 23 calls** — this blueprint is the single biggest refactoring target. Multi-turn negotiation with context injection at every turn.
6. **`proactive_bedtime_escalation` uses TWO agents** — separate proactive and bedtime agents. The only blueprint with dual-agent architecture.

---

## Design Considerations

Ten cross-cutting concerns that don't belong to any single layer but will cause pain if discovered during implementation instead of design.

### DC-1: Graceful Degradation

Every layer must define its failure mode. The user should never hear an error — just experience reduced capability.

| Layer/Component | Failure Mode | Degradation |
|----------------|--------------|-------------|
| L1 (template sensor) | Jinja2 error, entity unavailable | Blueprints fall back to inline context building (current behavior) |
| L2 (Pyscript/SQLite) | Database locked, memory.py crash | Agents operate without memory — functional but amnesiac |
| L3 (calendar, email) | API timeout, auth expired | Promotion stops; existing L2 cache serves stale data |
| Identity layer | G3 offline, phone tracker lost | Fall back to single-user mode (treat all presence as primary user) |
| Prediction engine | No historical data, corrupted frequency table | Fall back to fixed schedules (current behavior) |
| LLM API | Extended OpenAI Conversation timeout | Template-based TTS fallback — pre-written messages, no LLM |
| TTS (ElevenLabs) | API down, quota exceeded | Fall back to local HA TTS engine (lower quality, instant) |

**Implementation:** Each blueprint that depends on a layer should have a `default()` filter or a `try/except`-style condition that detects the failure and routes to the fallback path. No silent failures — log at `warning` level so the issue is discoverable, but never surface to the user via TTS.

### DC-2: LLM Cost Control & Rate Limiting

Every LLM call costs money and latency. With inter-agent patterns multiplying calls, an unbounded system could run up serious costs.

**Budget concept:** `input_number.ai_llm_daily_budget` — daily call counter. Blueprints check before non-essential calls.

| Priority | Examples | Budget Gate |
|----------|----------|-------------|
| Essential | Wake-up alarm, direct voice command, bedtime routine trigger | Always allowed |
| Standard | Proactive announcements, coming home, notification follow-me | Allowed if budget > 30% remaining |
| Luxury | Reactive banter (Pattern 1), deliberation (Pattern 2), argument (Pattern 4) | Allowed if budget > 60% remaining |

Reset counter at midnight via automation. Log daily totals to L2 for trend analysis.

### DC-3: TTS Queue & Priority

Multiple automations speaking simultaneously = garbled mess. A centralized TTS queue with priority levels prevents collisions.

**Proposed priority levels:**

| Level | Examples | Behavior |
|-------|----------|----------|
| 0 — Emergency | Fire alarm, security alert, UPS critical | Interrupt everything, max volume |
| 1 — Alarm | Wake-up alarm, bedtime hard cutoff | Interrupt non-essential, scheduled volume |
| 2 — Interactive | Direct voice response, agent dialogue | Queue after alarm, preempt proactive |
| 3 — Proactive | Announcements, notifications, briefings | Queue behind interactive |
| 4 — Ambient | Banter, whisper network externalized, chimes | Queue behind everything, drop if queue > 3 |

**Implementation:** A script blueprint (`tts_queue_manager`) that all TTS-producing automations call instead of `tts.speak` directly. Maintains a queue in `input_text` helpers or a Pyscript in-memory list. Processes sequentially with priority preemption.

### DC-4: Agent Context Window Budget

As L1 grows richer, L2 accumulates memories, and self-awareness blocks are added — the system prompt for each conversation entity inflates. Extended OpenAI Conversation has token limits. Silent truncation or API errors result from exceeding them.

**Token budget targets per agent interaction:**

| Component | Target | Notes |
|-----------|--------|-------|
| Base system prompt (persona) | ~500 tokens | Fixed, per-agent |
| L1 hot context injection | ~200 tokens | Template sensor output, keep compact |
| Self-awareness block | ~100 tokens | Last agent, last topic, current user |
| L2 memory results | ~300 tokens (top-5) | Limit `memory_search` results, summaryOnly |
| Inter-agent context (handoff) | ~200 tokens | Previous agent's response summary |
| User message + conversation history | ~500 tokens | HA manages this |
| **Total target** | **~1,800 tokens** | Leaves headroom for model response |

**Implementation:** L1 sensor output should be pre-truncated by the template. L2 queries should use `limit` and `summaryOnly` parameters. The dispatcher should calculate available budget before adding optional context.

### DC-5: Testing & Simulation Harness

How do you test the identity layer without Jessica? How do you test routine fingerprinting without three weeks of data? How do you test inter-agent dialogue without waking the house?

**Required components:**

| Component | Purpose |
|-----------|---------|
| `input_boolean.ai_test_mode` | Global test flag — blueprints check this to use mock data |
| `input_text.ai_test_identity` | Override identity confidence ("miquel", "jessica", "guest") |
| `input_text.ai_test_routine_stage` | Override routine position for prediction testing |
| Synthetic recorder data script | Pyscript that injects fake zone transitions for fingerprint development |
| TTS sink | Test mode routes TTS to a log entry instead of speakers |
| Mock L2 data | Seed script that populates memory with test entries across all scopes |

The `proactive_bedtime_escalation` blueprint already has a `test_mode` input — this pattern should be standardized across all personal automation blueprints.

### DC-6: L2 Data Integrity & Backup

If a buggy automation writes garbage to the memory database — wrong scopes, corrupted fingerprints, bad relationship links — recovery is needed.

**Requirements:**
- Automated SQLite backup on a schedule (daily, to a persistent path outside `/homeassistant/`)
- `memory_health_check` service extended to cover `mem_rel` table and fingerprint entries
- Scope validation: reject `memory_set` calls with invalid scope values
- Deduplication on write: the auto-relationships spec already addresses this, but fingerprint writes need the same guard

**Backup implementation:** Pyscript automation or shell script via SSH add-on `init_commands`. Destination: `/backup/memory/` or a mounted share. Keep 7 daily snapshots.

### DC-7: Wake Word → Persona Routing

The architecture doc describes the dispatcher selecting personas but doesn't map wake words to the routing logic.

**Current state:** "Hey" and "Yo" variants map to verbosity levels, each tied to a specific persona via Voice PE satellite configuration.

**Design question:** When the dispatcher exists, does a wake word still lock to a persona?

**Proposed mapping:**

| Wake Word | Routing |
|-----------|---------|
| "Hey Rick" / "Yo Rick" | Forces Rick (bypass dispatcher) |
| "Hey Quark" / "Yo Quark" | Forces Quark (bypass dispatcher) |
| "Hey Deepee" / "Yo Deepee" | Forces Deadpool (bypass dispatcher) |
| "Hey Kramer" / "Yo Kramer" | Forces Kramer (bypass dispatcher) |
| Generic wake word (e.g., "Hey Jarvis") | Dispatcher selects best persona based on context |

**Verbosity:** "Hey" = standard, "Yo" = verbose. This applies regardless of whether the dispatcher or explicit name selects the persona. Verbosity is orthogonal to persona selection.

**Impact:** Voice PE satellite config maps wake words to HA assist pipelines. Each pipeline routes to a conversation entity. Named wake words → fixed pipelines. Generic wake word → pipeline that invokes the dispatcher script first, then routes to the selected conversation entity.

### DC-8: Latency Budget

Voice interactions have a hard UX ceiling — if the user waits more than 3-4 seconds for a response, it feels broken.

**Latency budget per component:**

| Component | Target | Notes |
|-----------|--------|-------|
| L1 read (template sensor) | <50ms | Jinja2 rendering |
| L2 search (SQLite FTS5) | <100ms | Already benchmarked by luuquangvu |
| Identity confidence calc | <50ms | Template sensor |
| LLM call (Extended OpenAI) | 1–3s | Network + inference, dominant cost |
| TTS generation (ElevenLabs) | 0.5–1s | Network + synthesis |
| TTS playback start | <200ms | HA media_player latency |
| **Single-agent total** | **2–4.5s** | Acceptable |

**Multi-agent latency implications:**

| Pattern | Calls | Expected Latency | Acceptable for Voice? |
|---------|-------|------|----------------------|
| Pattern 1 (Banter) | 2 LLM + 2 TTS | 4–8s | Borderline — stagger, don't block |
| Pattern 2 (Deliberation) | 4 LLM + 1 TTS | 8–15s | No — async only, announce "let me think" |
| Pattern 3 (Handoff) | 2 LLM + 2 TTS | 4–8s | Yes — first response is fast, second follows |
| Pattern 4 (Argument) | 2 LLM + 2 TTS | 4–8s | Yes — theatrical, user expects delay |
| Pattern 5 (Whisper) | 1 LLM + 1 TTS + background write | 2–5s | Yes — invisible to user |

**Rule:** Any pattern exceeding 5s must play a "thinking" indicator (chime, brief acknowledgment) before the response arrives.

### DC-9: Notification Deduplication

With proactive announcements, notification follow-me, email follow-me, and predictions all potentially delivering the same information — dedup is essential.

**Example:** "You have a meeting at 9 AM" could come from:
- Proactive morning briefing (L1 + L3)
- Calendar notification (L3 push)
- Predictive scheduler ("based on your routine, reminding you now")

**Implementation:** Store announcement hashes in L2 with a TTL:
```
memory_set("announced:meeting_9am_20260301", value="delivered via proactive", 
           tags=["dedup", "announcement"], expires_at=<+4h>)
```

Before any announcement, query: `memory_search("announced:meeting_9am_*")`. If found and not expired, skip. The `memory_purge_expired` service cleans up automatically.

**Hash key format:** `announced:{topic_slug}_{date}` — specific enough to dedup same-day repeats, not so specific that minor wording differences bypass it.

### DC-10: TTS Caching & Reuse

ElevenLabs API calls cost money and add latency. Many TTS outputs are identical or near-identical across invocations — regenerating "Good morning, Miquel" with the same voice, text, and settings every day is pure waste.

**Scope clarification:** The TTS cache is **system-level infrastructure**, owned by the TTS queue manager (Task 8). One cache directory, one lookup engine, one eviction policy — shared by all blueprints and all agents. What's blueprint-level is only the **cache hint** (`static`, `daily`, `session`, `none`) — metadata that the blueprint author declares because only they know whether their text is hardcoded or dynamic. The system can't auto-detect determinism. The blueprint doesn't manage the cache; it just tells the cache how to treat its content.

**Decision Logic — Text Determinism**

Every TTS call reduces to: `text + voice_id + voice_settings = audio`. If those three inputs are identical, the output is identical. The cache key is `sha256(text + voice_id + settings)`. The blueprint author declares the cacheability tier — the system doesn't need to guess.

**Cache hint values (declared by blueprint author):**

| Hint | Expiry | Use Case |
|------|--------|----------|
| `static` | Never | Hardcoded strings, chimes, alarm phrases, agent theme jingles |
| `daily` | Midnight | Date-dependent greetings, schedule announcements |
| `session` | When automation completes | Repeated phrase within one bedtime escalation run |
| `none` | Never cached | LLM output, unique responses |

**Three tiers of TTS content:**

| Tier | Description | Cache Behavior | Examples |
|------|-------------|---------------|----------|
| **1 — Static** | Blueprint author wrote the string literally | Permanent cache; generate on first use, reuse forever | "Bedtime in fifteen minutes", "Get out of bed", chime wrappers |
| **2 — Templated** | Fixed structure, bounded variable slots | Pre-generate full matrix at midnight; zero API latency at runtime | "Good morning Miquel, it's Saturday" (7 day variants × names) |
| **3 — Dynamic** | LLM-generated, always unique | Never cache the content; *do* cache the wrapper (chime, "I'm thinking", transition phrase) | Agent responses, personalized briefings, banter |

**TTS queue manager cache flow:**

```
Blueprint calls script.tts_queue_speak:
  text: "Bedtime in fifteen minutes."
  voice: tts.elevenlabs_quark
  priority: 3
  cache: static

Queue manager:
  1. hash = sha256(text + voice_id + settings)
  2. Check /homeassistant/tts_cache/{hash}.mp3
  3. HIT  → media_player.play_media (local file, <200ms)
  4. MISS → ElevenLabs API call → save {hash}.mp3 → play (500ms-1s)
```

**Midnight cache warmup automation:** Runs at 00:05. Reads tomorrow's schedule from L1/L3. Resolves all templated phrases (Tier 2) for the day. Pre-generates any missing cache entries. By 6 AM, Rick's alarm audio is already on disk — the API call happened at midnight when latency doesn't matter.

**Per-agent caching:** Hash includes voice_id. Rick's "Get out of bed" and Quark's "Get out of bed" are separate cache entries. Automatic.

**Layer integration:**

| Layer | Role in Caching |
|-------|----------------|
| L1 | Informs cache invalidation — state change (e.g., wake-up time changed) triggers midnight warmup to regenerate affected entries |
| L2 | Stores cache statistics for cost analysis (daily hit rate, API calls saved, monthly cost trending) |
| Infra | Cache lives in TTS queue manager (Task 8), not in any context layer |

**Cache management:**

| Parameter | Value |
|-----------|-------|
| Storage | `/homeassistant/tts_cache/` (persistent across restarts) |
| Size limit | Configurable, LRU eviction for non-static entries |
| Cleanup | Automation purges expired `daily`/`session` entries |
| Monitoring | `sensor.ai_tts_cache_hit_rate` template sensor for dashboard visibility |

**Cost savings estimate:** ~50 daily TTS events, ~60% static/semi-static = 30 API calls eliminated per day. Significant ElevenLabs cost reduction over a month. Latency improvement: 200ms (cached) vs 500ms-1s (API) for every cached phrase.

### DC-11: Audio Routing & Speaker Targeting

Voice and music are different media with different routing needs. The current design (DC-3) routes all TTS to the nearest speaker based on presence. But composed audio, ambient music, wake-up melodies, and agent theme jingles may need to play from a *different* speaker than where voice comes out — or from multiple speakers simultaneously.

**Two routing concepts:**

| Routing Type | Purpose | Target Logic | Examples |
|-------------|---------|--------------|----------|
| **Voice routing** | Agent speech follows the user | Presence-based: resolves to nearest speaker via FP2 zone | All TTS output, interactive responses, announcements |
| **Audio routing** | Music/compositions go to intentional placement | Explicit target: blueprint author specifies speaker or group | Wake-up melody on living room to lure user out of bed, ambient jazz in living room while voice follows to workshop |

**Target modes for TTS queue manager (`script.tts_queue_speak`):**

| Mode | Behavior | Use Case |
|------|----------|----------|
| `presence` | Resolve target speaker from current FP2 presence data | Default for all voice TTS |
| `explicit` | Use the named `media_player` entity directly | Music compositions, zone-specific ambient, multi-room audio |
| `broadcast` | Send to all speakers simultaneously | Emergency alerts (priority 0), household announcements |
| `source_room` | Play on the speaker in the room where the trigger originated | Voice responses to wake-word commands (respond where you were asked) |

**Unified service interface:**

```yaml
# Voice — follows user
script.tts_queue_speak:
  text: "Rise and shine, you magnificent bastard."
  voice: tts.elevenlabs_rick
  target_mode: presence
  priority: 2
  cache: static

# Music — explicit speaker
script.tts_queue_speak:
  media_file: /homeassistant/tts_cache/music/rick_wakeup_melody_v3.mp3
  target_mode: explicit
  target: media_player.living_room_sonos
  priority: 3
  duck_on_voice: true

# Emergency — all speakers
script.tts_queue_speak:
  text: "Fire alarm triggered. Kitchen smoke detector."
  voice: tts.elevenlabs_rick
  target_mode: broadcast
  priority: 0
  cache: static
```

**Ducking coordination:** When voice and audio target different speakers simultaneously, the audio speaker ducks automatically if `duck_on_voice: true`. This reuses the existing ducking infrastructure from the bedtime/wake-up blueprints. The TTS queue manager orchestrates the duck/restore cycle — blueprints don't manage it. Per-speaker ducking mode configured in `tts_speaker_config.json` → `speaker_options`: `"hardware"` (Sonos announce, default) or `"software"` (pyscript capture/restore). See Decision #52.

**Music Assistant interaction:** For composed tracks that should be managed by Music Assistant (queue, playlist, volume normalization), the audio routing hands off to MA's `media_player.play_media` service instead of playing raw files. The TTS queue manager still controls *when* the track plays (priority gating) but delegates *how* to MA.

**Presence resolution fallback:** If `target_mode: presence` can't determine a speaker (no FP2 presence detected, user in an unmonitored zone), fall back to a configurable default speaker (`input_text.ai_default_speaker`). Never fail silently — log a warning and play on the default.

### DC-12: Anti-ADHD Focus Guards

A proactive nudge system that helps Miquel (and future users) maintain awareness of time, responsibilities, and self-care during deep focus sessions — particularly workshop/project immersion.

**The problem:** ADHD hyperfocus means hours pass unnoticed. Meals skipped, calendar appointments missed, partner ignored, bedtime blown. The house knows where you are, what time it is, and what's on your calendar. It should use that knowledge to help.

**Inputs consumed:**

| Source | Data | Layer |
|--------|------|-------|
| FP2 presence sensor | Zone occupancy + duration (workshop, living room, etc.) | L1 |
| Time of day | Current time, work day flag | L1 |
| Calendar | Upcoming appointments with lead time | L3→L2→L1 |
| Meal tracking | `input_datetime.last_meal_time` (user marks meals via voice or button) | L1 |
| Partner presence | Jessica home? How long since shared-space time? | L1 |
| Bedtime schedule | `input_datetime.ai_context_bed_time` | L1 |

**Nudge types:**

| Type | Trigger | Example |
|------|---------|---------|
| **Time check** | Workshop occupancy > configurable threshold (default 2h) | "You've been in the workshop for 3 hours." |
| **Meal reminder** | Last meal > 4 hours AND not sleeping | "It's 2 PM and you haven't eaten since breakfast." |
| **Calendar warning** | Appointment in < configurable lead time (60/30/15 min) | "You have a dentist appointment in 30 minutes." |
| **Social nudge** | Partner home > 30 min AND user in solo zone AND no shared-space time today > threshold | "Jessica's been home for an hour. Maybe say hi?" |
| **Break suggestion** | Continuous same-zone occupancy > 2h with no zone change | "You've been at it for 2 hours straight. Stretch?" |
| **Bedtime approach** | Current time within 1h of bedtime AND user not in wind-down zone | "Bedtime in 45 minutes. Start wrapping up." |

**Escalation pattern — maps to TTS priority levels:**

| Stage | Timing | TTS Priority | Delivery Style |
|-------|--------|-------------|----------------|
| Gentle | First nudge | 4 (Ambient) | Soft chime + brief one-liner |
| Firm | +30 min if unacknowledged | 3 (Proactive) | Agent personality with humor |
| Urgent | +30 min if still unacknowledged | 2 (Interactive) | Direct, harder to ignore |
| Critical | Calendar <15 min OR bedtime passed | 1 (Alarm) | Full alarm behavior, max insistence |

**Agent personality examples (Firm stage):**

Rick: *"Hey genius, you've been in here four hours. Your girlfriend exists, you know."*
Quark: *"Rule of Acquisition #211: Employees are the rungs on the ladder of success. But SHE is not your employee, and your stomach has been filing complaints since noon."*

**Anti-annoyance safeguards:**

- `input_boolean.focus_mode` — voice-activated "do not disturb" that suppresses non-calendar nudges. Auto-expires after configurable max duration (default 2h, then nudges resume regardless).
- **Per-type toggles** — `input_boolean.ai_focus_{type}_enabled` for each of the 6 nudge types. Allows disabling individual nudge categories without killing the whole system. All default ON.
- Minimum 30-minute cooldown between same-type nudges.
- Voice snooze: "Remind me in 30 minutes" acknowledged via intent.
- Calendar warnings **always** bypass focus mode. Emergency alerts **always** bypass everything.
- L2 learns snooze patterns: if user always snoozes meal reminders at noon but eats at 1 PM, adjust timing over time.

**Meal reminder follow-up:** When `input_boolean.ai_focus_meal_ask_eaten` is ON (default), meal reminder TTS is followed by opening the satellite mic via `assist_satellite.start_conversation`. The agent receives an `extra_system_prompt` explaining the meal context, so the user can respond naturally ("I ate at 14:00" or "I just ate"). The agent calls `focus_guard_mark_meal` with the optional `meal_time` parameter.

**Helpers required:**

```yaml
input_boolean.focus_mode          # Voice-activated DND
input_boolean.ai_focus_guard_enabled  # Kill switch (default ON)
input_boolean.ai_focus_time_check_enabled      # Per-type toggle
input_boolean.ai_focus_meal_reminder_enabled    # Per-type toggle
input_boolean.ai_focus_calendar_warn_enabled    # Per-type toggle
input_boolean.ai_focus_social_nudge_enabled     # Per-type toggle
input_boolean.ai_focus_break_suggest_enabled    # Per-type toggle
input_boolean.ai_focus_bedtime_approach_enabled # Per-type toggle
input_boolean.ai_focus_meal_ask_eaten  # Meal mic follow-up (default ON)
input_datetime.last_meal_time     # Last meal timestamp
input_number.workshop_hours_today # Daily workshop accumulator
input_number.focus_guard_threshold_hours  # Configurable focus duration before first nudge
```

**Template sensor addition to L1:**

```yaml
# Addition to sensor.ai_hot_context
Workshop focus: {{ workshop_duration_hours }}h continuous
  (focus mode: {{ 'ON - ' ~ focus_mode_remaining ~ ' remaining' if focus_mode else 'OFF' }}).
Last meal: {{ last_meal_hours }}h ago.
```

**Implementation:** `pyscript/focus_guard.py` + `packages/ai_focus_guard.yaml` — cron-triggered (every 15 min) + event-triggered (FP2 zone change). Delivers via `pyscript.tts_queue_speak` with appropriate priority level. Snooze handling via `input_datetime.focus_guard_snooze_until`. `focus_guard_mark_meal` accepts optional `meal_time` parameter (`HH:MM` or full datetime). Meal reminder TTS optionally opens satellite mic for voice response via `assist_satellite.start_conversation`.

**Build dependency:** Requires Tasks 1 (L1 helpers), 7 (per-user helpers), 8 (TTS queue), 18a (calendar promotion). Best placed after Task 19 (proactive briefing) since it's architecturally similar — another proactive announcement use case.

---

## Agent Music Composition

Extension of the multi-agent system: agents don't just speak — they compose and perform personalized audio content. Each persona has a musical identity alongside their voice and personality.

### Generation Approaches

| Option | Method | Quality | Latency | Cost | Best For |
|--------|--------|---------|---------|------|----------|
| **A: External API** | LLM describes music → Suno/Udio API generates | High (full production) | 30-120s | Per-track API cost | Base themes, wake-up melodies |
| **B: Local Synthesis** | LLM outputs note sequence → Pyscript + fluidsynth renders | Simple (MIDI-quality) | 1-5s | Free (local CPU) | Jingles, chimes, stingers, variations |
| **C: Hybrid** | Base theme via Option A (once) + variations via Option B (daily) | High base + adaptive | Seconds for variations | One-time generation cost | Production approach |

**Decision:** Option C (Hybrid) is the target architecture. Expensive generation happens once per theme. Cheap local synthesis handles daily variation.

### LLM Note Sequence Format

For Option B / variation generation, agents output structured note data:

```json
{
  "bpm": 120,
  "key": "C_major",
  "instrument": "synth_pad",
  "notes": [
    {"pitch": "C4", "duration": 0.5, "velocity": 0.8},
    {"pitch": "E4", "duration": 0.5, "velocity": 0.7},
    {"pitch": "G4", "duration": 0.25, "velocity": 0.9},
    {"pitch": "C5", "duration": 1.0, "velocity": 0.6}
  ]
}
```

A Pyscript service converts this to audio via `midiutil` → MIDI → `fluidsynth` + SoundFont → WAV/MP3. Stored in `/homeassistant/tts_cache/music/`.

### Agent Musical Identity

Each persona has musical taste as part of their character definition:

| Agent | Musical Style | Instruments | Tempo Range | Mood |
|-------|--------------|-------------|-------------|------|
| Rick | Chaotic sci-fi synth, dissonant | Distorted synth, theremin, electric guitar | 130-160 BPM | Manic, unpredictable |
| Quark | Smooth lounge jazz, Ferengi bar ambiance | Saxophone, upright bass, piano | 80-110 BPM | Suave, calculating |
| Deadpool | Inappropriately upbeat pop, 4th-wall-breaking | Pop synths, chiptune, ironic orchestral | 120-140 BPM | Chaotic good |
| Kramer | Eccentric improv, unexpected genre shifts | Slap bass, bongos, random brass | Variable | Unpredictable, physical |

Musical preferences stored in L2: `memory_set("agent_music_profile:quark", value="{style, instruments, bpm_range}", tags=["agent", "music", "quark"])`.

### Composed Audio Types

| Content | Duration | Purpose | Generation | Cache |
|---------|----------|---------|------------|-------|
| Agent theme jingle | 3-5s | Audio identity — plays before agent speaks | Option A, once | Static (permanent) |
| Notification chime | 1-2s | Per-agent notification sound | Option A/B, once | Static |
| Thinking music | 5-15s loop | During Pattern 2 deliberation delay (DC-8) | Option A, once | Static |
| Handoff stinger | 2-3s | Transition between agents in Pattern 3 | Option B, per agent pair | Static |
| Wake-up melody | 30-60s | Personalized alarm tone, evolves weekly | Option C | Daily |
| Bedtime wind-down | 2-5 min | Ambient piece, mood-based variations | Option C | Session |
| Mood-reactive ambient | Continuous | Background layer that shifts with behavioral state | Option B real-time | None |

### Layer Integration

**L1 feeds variation parameters:** Escalation stage → tempo increase. Time of day → key selection (major morning, minor evening). Routine position → energy level. Behavioral deviation → dissonance level. The template sensor exposes these as numeric values consumed by the synthesis engine.

**L2 stores compositions and preferences:** Base themes, agent musical profiles, composition history. Agents can iterate: "Last week's wake-up melody was too aggressive" → L2 feedback → next generation adjusts. Per-user preferences: Miquel prefers Rick's chaotic alarm, Jessica might prefer something gentler.

**Multi-agent:** Musical identity is part of persona definition alongside voice_id and system prompt. Theme jingle = audio catchphrase. Inter-agent transitions get unique stingers per agent pair (Rick→Quark bridge sounds different from Quark→Rick).

**Music Assistant integration:** Generated tracks added to MA library for playback through existing multi-room audio infrastructure. An agent could say "I composed something for your bedtime tonight" and queue it in Music Assistant via the existing `mass_llm_enhanced_assist` blueprint.

**TTS Cache integration:** Composed audio stored in `/homeassistant/tts_cache/music/`. TTS queue manager handles music playback in the same priority queue as speech. Theme jingle at priority 3, thinking music at priority 2.

### Dependencies

| Requirement | Purpose |
|-------------|---------|
| `fluidsynth` + SoundFont on RPi5 | Option B local synthesis |
| External music API (Suno/Udio) | Option A base theme generation |
| Pyscript `music_compose.py` | New service alongside `memory.py` |
| TTS queue manager (Task 8) | Unified audio playback pipeline |

### Build Priority

This is a **luxury feature** — entertaining and unique, but not infrastructure. Recommended after Tasks 1-14 are operational. The architecture supports it naturally because it's another type of audio content flowing through the TTS queue with cache management. The layers already provide the context signals.

---

## Ported Components & External Dependencies

### Design Principle

**Build the architecture, steal the plumbing.** Every component below was evaluated against our design requirements. We port existing community solutions where they handle well-solved problems (audio combining, volume ducking, speaker management), and build custom only where nobody has solved the problem (priority queuing, presence routing, memory layers, inter-agent communication). No Node-RED. No external orchestration engines. All automation logic stays in native HA YAML and Pyscript.

### ~~Chime TTS~~ — Evaluated, Not Adopted

**Source:** [nimroddolev/chime_tts](https://github.com/nimroddolev/chime_tts) (HACS custom integration)

**Status:** Evaluated during Task 8 design but not adopted. The TTS queue manager (`tts_queue.py`) was built entirely in Pyscript with direct `tts.speak` and `media_player.play_media` calls. Volume ducking handled per-speaker: hardware (Sonos announce mode) or software (pyscript capture/restore, Decision #52). This eliminated the HACS dependency and the Chime TTS compatibility risk (R-2).

**Integration pattern (actual):**

```
Blueprint/Agent → pyscript.tts_queue_speak
    → priority check → cache lookup → routing decision
    → tts.speak / media_player.play_media (direct HA services)
        → media_player target(s)
```

### ElevenLabs TTS — Multi-Entity Voice Architecture

**Source:** Official HA core integration (`homeassistant.components.elevenlabs`, since 2024.8)
**Role:** Per-agent voice identity via separate TTS entities.

**Pattern:** Add the ElevenLabs integration multiple times (same API key, different default voice each time). Each entry creates a dedicated TTS entity:

| Entity | Default Voice | Agent |
|--------|---------------|-------|
| `tts.elevenlabs_rick` | Rick's cloned/selected voice_id | Rick Sanchez persona |
| `tts.elevenlabs_quark` | Quark's cloned/selected voice_id | Quark DS9 persona |
| `tts.elevenlabs_deadpool` | Deadpool voice_id | Future agent |

**Why multiple entities over voice profiles:**

The loryanstrant Custom TTS integration offers named voice profiles (`voice_profile: "Rick"`) on a single entity. We evaluated this and chose the official multi-entity approach because:

- **Declarative identity:** Each agent's TTS pipeline points to its own entity. No runtime parameter passing, no profile name strings. The voice identity is baked into the entity.
- **No HACS dependency for core TTS:** Official integration updates with HA core. No compatibility breakage risk from custom component on HA version upgrades.
- **Simpler debug surface:** `tts.elevenlabs_rick` in traces/logs immediately tells you which agent spoke.
- **Pipeline alignment:** Each Extended OpenAI Conversation agent → its own Assist pipeline → its own TTS entity. Clean 1:1:1 mapping.

**Known limitations of official integration (as of HA 2025.12):**

- Voice dropdown only shows voices from your **ElevenLabs VoiceLab** — NOT the full community library. Add desired voices to VoiceLab on elevenlabs.io first.
- No `stability`, `similarity_boost`, `style`, or `speed` parameters exposed in `options`. Only `voice` and `model` overrides available per-call.
- Community has reported voice availability discrepancies between HA dropdown and ElevenLabs website (Nov 2025 thread, still open).

**Mitigation:** If speed/stability control becomes critical for agent personality differentiation, the loryanstrant Custom TTS can be added as a *supplement* alongside the official integration — not a replacement. Evaluate after initial agent voices are configured and tested.

### PEveleigh's Dispatcher Pattern — Agent Routing Wiring (Task 11 Reference)

**Source:** [HA Community thread](https://community.home-assistant.io/), Aug 2024 — multiple specialized agents via Extended OpenAI Conversation
**Role:** Reference implementation for `conversation.process` routing between agent instances.

**What we take:** The basic wiring pattern — a dispatcher agent that receives all queries and uses `call_agent_by_id` function spec to route to specialized agents. Approximately 30 lines of YAML. Clean, proven, minimal.

**What we extend beyond his pattern:**

- Conductor personality and commentary (his dispatcher is a silent router; ours has character)
- Inter-agent memory sharing via L2 whisper network
- Handoff commentary (transition audio between agents)
- Identity-aware routing (different agent preferences per user)
- Named wake word bypass (explicit persona request skips dispatcher)

### HA Native TTS Cache — File Storage Base Layer

**Source:** Built into HA Core TTS platform (`cache: true` parameter)
**Role:** Base file-level caching that our tier system sits on top of.

**What we use:** HA's existing mechanism: same text + same voice + same options = same cached MP3 file served from disk. We don't replace this — we add hash-keyed tier management, determinism classification, midnight warmup, and cost tracking as a layer above it.

### EL-HARP Feature Engineering — Prediction Feature Definitions (Task 15 Reference)

**Source:** Academic paper (PMC) — ML-based activity prediction on RPi5
**Role:** Feature definition reference for our Markov chain presence prediction.

**What we take:** Their feature taxonomy — time-of-day bucketing, day-of-week encoding, dwell-time tracking, sequence ordering, transition probability calculation. These are well-validated feature definitions for activity prediction.

**What we explicitly do NOT take:** Their ML framework (LightGBM), their sensor hardware (ESP32-CAM, NFC, ultrasonic), or their model training pipeline. Our implementation is ~200 LOC Pyscript using Markov chains on existing FP2 zone data. Massively simpler, purpose-built for our use case.

### Piper TTS — Local Fallback (SHELVED)

**Status:** Documented as future option. Not in current build scope.
**Rationale:** Piper provides fast, local, offline TTS with no API costs. Ideal as:

- Fallback when ElevenLabs is unreachable (internet outage, quota exhausted)
- Low-priority ambient announcements that don't justify ElevenLabs API cost
- Development/testing voice to avoid burning ElevenLabs credits

The TTS queue manager's cache tier system already classifies messages by priority, which naturally maps to "use ElevenLabs for high-priority, Piper for ambient." When ready, adding Piper is a configuration change — not an architecture change.

**Shelved because:** Current focus is getting the architecture operational with ElevenLabs voices that match agent personalities. Piper voices don't have the character quality needed for Rick/Quark personas. Adding Piper later for fallback/ambient is a Task 8 configuration update, not a redesign.

### Summary — What We Build vs What We Port

| Component | Build or Port | Source | Effort Saved |
|-----------|--------------|--------|-------------|
| TTS priority queue (5-level) | **BUILD** | No existing solution | — |
| Audio playback + ducking + volume restore | **BUILD** | Custom Pyscript (tts_queue.py) | Direct `tts.speak` / `media_player.play_media` calls |
| Per-agent voice entities | **PORT** | Official ElevenLabs (multi-entry) | Voice config helpers eliminated |
| Agent dispatcher wiring | **PORT + EXTEND** | PEveleigh's pattern | Basic routing proven, we add personality |
| File-level TTS caching | **PORT** | HA native `cache: true` | Storage layer for free |
| Cache tier management + warmup | **BUILD** | No existing solution | — |
| Presence-aware speaker routing | **BUILD** | No existing solution | — |
| Memory layers (L1/L2/L3) | **BUILD** | No existing solution | — |
| Inter-agent communication | **BUILD** | No existing solution | — |
| Identity layer + privacy scoping | **BUILD** | No existing solution | — |
| Prediction feature definitions | **PORT** (concepts only) | EL-HARP paper | Feature taxonomy validated |
| Local TTS fallback | **SHELVED** | Piper (add when ready) | Config change, not architecture |

---

## Quality Scenarios (Acceptance Criteria)

Testable requirements. If these aren't met, the system isn't done — no matter how many features work.

| ID | Scenario | Threshold | Test Method |
|----|----------|-----------|-------------|
| QS-1 | Voice response latency (single agent, cached TTS) | < 3 seconds end-to-end | Stopwatch test: wake word → first audio out |
| QS-2 | Voice response latency (single agent, fresh TTS) | < 5 seconds end-to-end | Same as QS-1, clear TTS cache first |
| QS-3 | Multi-agent handoff latency (Pattern 3) | < 8 seconds for full exchange | Timed from conductor response to specialist response |
| QS-4 | System functions with internet down | L1 + L2 fully operational, L3 stale but present, TTS falls back to local | Kill WAN interface, run through test scenarios |
| QS-5 | No cross-user data leakage | Jessica's L2 data never appears in Miquel's agent context, and vice versa | Create test memories for both users, verify isolation |
| QS-6 | Monthly API cost stays within budget | < €TBD/month (ElevenLabs + OpenAI combined) | Review `sensor.ai_llm_daily_budget` + ElevenLabs dashboard monthly |
| QS-7 | Existing blueprints survive migration | Every blueprint that worked before Task 1 still works after Task 4 | Full regression test after blueprint context variable removal |
| QS-8 | Focus guard nudge fires correctly | Workshop > 2h triggers gentle nudge within 15 min | Sit in workshop for 2h 15min, verify TTS delivery |
| QS-9 | HA restart recovers all state | All helpers, template sensors, queues resume within 60 seconds | `ha core restart`, verify L1 sensor populated and TTS queue empty |
| QS-10 | "Turn it off" works immediately | Any user can disable AI voice features instantly | Voice command or dashboard toggle → silence within 5 seconds |

---

## Risks & Technical Debt

Known threats, sorted by likelihood × impact. Review this section at each build phase boundary.

| ID | Risk | Likelihood | Impact | Mitigation |
|----|------|-----------|--------|------------|
| R-1 | **Extended OpenAI Conversation abandoned** | Medium | Critical — entire agent framework depends on it | Monitor GitHub activity. Fallback: HA's native OpenAI conversation agent (less capable but core-maintained). Begin evaluating alternatives if no commits for 6+ months. |
| ~~R-2~~ | ~~**Chime TTS beta never promoted to stable**~~ | — | — | **Resolved.** Chime TTS not adopted. TTS queue manager built in Pyscript with direct HA service calls. No HACS playback dependency. |
| R-3 | **NVMe SSD failure** | Low (over 3+ years) | Critical — full system loss | NVMe has far better write endurance than SD card. Maintain HA snapshot backups (automated weekly to NAS/cloud). L2 SQLite backed up to separate storage (Task 23). |
| R-4 | **ElevenLabs pricing change or API deprecation** | Medium | High — agent voice identity depends on it | TTS queue manager uses `tts.speak` which wraps any HA TTS platform. Piper shelved as fallback. Monitor ElevenLabs changelog. |
| R-5 | **RPi5 resource exhaustion** | Low-Medium | Medium — system slowdown, automation delays | Profile CPU/memory during Task 10 (test harness). Set alerts for > 80% sustained. NVMe SSD handles I/O well but monitor swap usage (currently 170MB/2.6GB used). |
| R-6 | **HA major version breaks multiple HACS integrations** | Medium | High — Pyscript + other HACS integrations break simultaneously | Pin HA version during critical build phases. Test upgrades on snapshot copy before production. Never upgrade HA during active feature development. |
| R-7 | **FP2 sensor misidentifies person in multi-user mode** | High (by design) | Medium — wrong user gets personal announcements | Identity confidence model (DC: Identity Layer) fuses FP2 + phone presence + G3 face. Below 70% confidence → generic mode, no personal data. |
| R-8 | **OAuth token expiry for Google Calendar / Gmail** | High (periodic) | Low — L3 promotion stops, stale L2 data persists | Graceful degradation (DC-1): agents work with stale L2 + L1 only. HA notification on auth failure for manual re-auth. |
| R-9 | **Builder burnout / ADHD project abandonment** | Medium | Critical — incomplete system worse than no system | Build order designed for useful checkpoints. Tasks 1-4 produce a working L1 system. Tasks 5-10 produce working infrastructure. Each phase is independently valuable. Focus guards (DC-12) help. |
| R-10 | **Power outage recovery** | Medium | Low-Medium — helpers reset to defaults, queue lost | HA `initial:` values on critical helpers. TTS queue is ephemeral (acceptable loss). L2 persists in SQLite. Template sensors auto-rebuild from state. |

---

## Pre-Flight Checklist — Questions That Will Bite You

Questions organized by build phase. Review the relevant section BEFORE starting each phase. If you can't answer a question, it's a blocker — design the answer first.

### Phase 1: Foundation (Tasks 1–4)

- **Template sensor size limit?** HA templates have a ~256KB rendered size limit. Our `sensor.ai_hot_context` must stay well under. Test with `developer-tools/template` before deploying.
- **Which entities don't exist yet?** The template sensor references helpers that Task 1 creates. Audit every entity reference. Missing entity = Jinja2 error = blank context = agent amnesia.
- **Migration order for blueprint context removal (Task 4)?** Do NOT remove all blueprint context variables at once. Migrate one blueprint at a time, test, commit, move on. Rollback must be possible per-blueprint.
- **How do you know Task 4 didn't break something?** QS-7 — full regression test. Every voice command that worked before must work after. Write a test script with 10 representative commands.

### Phase 2: Memory & Identity (Tasks 5–7)

- **SQLite concurrent access?** Pyscript runs async. Two blueprints triggering `memory_set` simultaneously could lock SQLite. Verify Pyscript memory engine handles this (queue writes internally, or use WAL mode).
- **What's identity confidence when living alone?** Before Jessica moves in, confidence should be 100% (only user = Miquel). Design the system to work at both 1-user and 2-user, but don't over-engineer identity fusion until there ARE two users.
- **Per-user helper explosion?** Every per-user helper × 2 users = double the entities. Dashboard impact? Automation complexity? Keep the helper count lean — only create per-user copies for genuinely user-specific data.

### Phase 3: Infrastructure (Tasks 8–10)

- **Queue persistence across HA restart?** Pyscript in-memory queue disappears on restart. Acceptable — stale announcements are worse than lost ones. Documented as intentional.
- **TTS cache disk usage?** ElevenLabs generates ~10KB per sentence. 100 cached phrases = 1MB. 10,000 = 100MB. Cache eviction policy (LRU, max age, max size) implemented.
- **Test harness: silent mode?** `test_mode` flag routes TTS to a log-only sink. Working.

### Phase 4: Multi-Agent (Tasks 11–14)

- **Simultaneous `conversation.process` calls?** If two automations trigger different agents at the same time, does Extended OpenAI Conversation handle this? Test explicitly — send two requests 100ms apart.
- **Conductor latency budget?** Pattern 3 (Handoff) = 2 LLM calls. Pattern 2 (Deliberation) = 2+ calls. QS-3 says < 8 seconds. Profile actual latency with your internet connection and API response times.
- **What if the dispatcher picks the wrong agent?** User asks Rick a question, dispatcher sends it to Quark. User is annoyed. Escape hatch: named wake word always bypasses dispatcher (Decision #21). Test this path.

### Phase 5: Prediction & L3 (Tasks 15–19)

- **Cold start: how much data before predictions work?** Markov chains need minimum ~2 weeks of presence data to establish meaningful transition probabilities. System must gracefully return "no prediction available" during ramp-up.
- **Calendar OAuth: what happens when token expires at 3 AM?** HA logs a warning, L3 promotion stops, L2 serves stale calendar data. Agent says "I think you have..." instead of "You have..." — degrade language confidence when data is stale.
- **Proactive briefings: what if nobody's home?** Presence check before briefing. Never deliver to an empty room. Queue for arrival if briefing is time-sensitive.

### Phase 6: Advanced (Tasks 20–25)

- **Multi-speaker: what if target speaker is offline?** Fallback to `input_text.ai_default_speaker`. Never fail silently — log warning, play on available speaker.
- **Privacy fence verification?** How do you PROVE Jessica's data doesn't leak? Automated test: create memories in both user scopes, query from each agent, assert cross-scope results are empty. Run this as part of Task 23 (graceful degradation audit).
- **Focus guards: will Miquel just disable them?** Design for this. If `focus_mode` is activated more than 3 times in a day, L2 records this pattern. Agent can acknowledge: "You've hit focus mode three times today. I'll back off, but your dentist appointment is in an hour." Calendar always wins.

---

## Updated Build Order

| Priority | Task | Layer | Dependency | DC Ref | Status |
|----------|------|-------|------------|--------|--------|
| 1 | `ai_context_hot.yaml` package (helpers + template sensor) | L1 | None | — | Done |
| 2 | Self-awareness helpers (last_agent, last_topic, last_time) | L1 | Task 1 | — | Done |
| 3 | Agent prompt standardization + sub-entry consolidation (18 → 8) + L1 injection | L1 | Tasks 1–2 | DC-4, #43, #44 | Done |
| 4 | Blueprint agent reference migration + context variable removal (65 conv.process calls) | L1 | Task 3 | #46 | Done |
| 5 | Auto-relationships extension (`mem_rel`) | L2 | notification_follow_me v3.18.0 | DC-6 | Done |
| 6 | Identity layer — WiFi+GPS+FP2 confidence sensors + guest mode | L1 | Task 1 | — | Done |
| 7 | Per-user helper design (bedtime, wake-up, preferences) | L1 | Task 6 | — | Done |
| 8 | TTS queue manager (Pyscript queue + priority + cache + playback) | Infra | — | DC-3, DC-10, DC-11 | Done |
| 9 | LLM budget counter + rate limiting helpers | Infra | None (can build early) | DC-2 | Done |
| 10 | Test harness (global test_mode, mock helpers, TTS sink) | Infra | Task 1 | DC-5 | Done |
| 11 | Agent dispatcher spec + build (pipeline-aware, 6-level routing) | Multi-agent | Tasks 1–6 | DC-7 | Done |
| 12 | Inter-agent Pattern 3 (Handoff with Commentary) | Multi-agent | Tasks 2, 11 | DC-8 | Done |
| 13 | Inter-agent Pattern 5 (Whisper Network — L2 mood writes) | Multi-agent | Tasks 5, 11 | — | Done |
| 14 | Notification deduplication layer | L2 | Task 5 | DC-9 | Done |
| 15 | Presence pattern extraction — Pyscript recorder query + frequency tables | L2 | Task 1 | DC-5 | Done |
| 16 | Routine fingerprinting + position tracker | L1+L2 | Task 15 | — | Done |
| 17 | Predictive scheduling (L1+L2+L3 fusion) | All | Tasks 15–16, L3 wiring | DC-8 | Done |
| 18a | L3 → L2 calendar promotion automation (daily sync + event triggers) | L3→L2 | Tasks 1, 5 | — | Done |
| 18b | L3 → L2 email priority filter automation (IMAP trigger + contact whitelist) | L3→L2 | Tasks 1, 5, 6 | — | Done |
| 18c | L1 hot context: calendar one-liner + email counter from L2 | L1 | Tasks 18a, 18b | — | Done |
| 19 | Proactive briefing automation | All | Tasks 1–18 | DC-1 | Done |
| 20 | Anti-ADHD focus guards (nudge system + meal/calendar/social awareness) | All | Tasks 1, 7, 8, 18a | DC-12 | Not Started |
| 21 | Multi-speaker spatial audio routing | Multi-agent | Tasks 8, 11–12 | DC-8, DC-11 | Done |
| 22 | Per-user scoping + privacy fence (Jessica move-in) | L2 | Tasks 6–7 | DC-6 | Not Started |
| 23 | L2 automated backup + health checks | Infra | Task 5 | DC-6 | Not Started |
| 24 | Graceful degradation audit (all layers) | All | Tasks 1–22 | DC-1 | Not Started |
| 25 | Agent music composition engine (Pyscript + fluidsynth) | Luxury | Tasks 8, 11 | DC-10 | Not Started |
| 26 | Music Assistant integration for composed tracks | Luxury | Task 25 | — | Not Started |

---

## Decisions Log

| # | Decision | Rationale |
|---|----------|-----------|
| 1 | L2 engine = luuquangvu Pyscript | Native to HA Core, no container networking, already installed |
| 2 | simple-memory-mcp removed from HA | Bound to localhost in SSH add-on, unreachable by HA Core |
| 3 | simple-memory-mcp installed on Claude Desktop | For Claude's own persistent memory across sessions |
| 4 | Auto-relationships = L2 enhancement | Not a new layer; hooks into existing memory_set |
| 5 | L3 promotion pattern (cold→warm→hot) | Preferred over real-time L3 queries for voice latency |
| 6 | Option A (search-time enrichment) for voice | Option B (explicit service) for blueprints |
| 7 | Conductor always configurable | Blueprints expose pattern enable, probability, agent selection |
| 8 | Start with blueprint-driven (A), layer in agent-driven (B), build toward dispatcher (C) | Incremental complexity |
| 9 | Handoff with Commentary = first multi-agent pattern | Most natural, only 2 LLM calls, low risk |
| 10 | Predictions inform timing, never announce behavior | Creep factor gate — hard design constraint |
| 11 | Routine fingerprints via Markov chain in Pyscript | ~200 LOC, no ML libraries, no external services |
| 12 | Design for two users, implement for one | Jessica moving in — every helper/sensor designed for multi-user |
| 13 | ~~Identity = G3 face + phone presence + guest mode fusion~~ | ~~No reliable per-room person tracking with current hardware~~ — **Superseded by #51** |
| 14 | Per-user L2 scopes: miquel, jessica, household | Privacy fence prevents cross-user data leakage |
| 15 | Personal automations gate on identity confidence > 70 | Below 30 = guest mode, 30-70 = limited, 70+ = full personal |
| 16 | TTS cache for static/semi-static content | ElevenLabs costs money; ~40-60% of daily calls are cacheable |
| 17 | Centralized TTS queue with priority levels | Prevents simultaneous speech collisions across blueprints |
| 18 | LLM daily budget counter with tiered gating | Prevents runaway costs from multi-agent patterns |
| 19 | Latency > 5s requires "thinking" indicator | Hard UX rule; Pattern 2 always async with acknowledgment |
| 20 | Notification dedup via L2 hash + TTL | Prevents same info announced by multiple systems |
| 21 | Named wake word bypasses dispatcher; generic goes through it | Explicit persona request honored, otherwise dispatcher decides |
| 22 | Hybrid music composition (Option C): external API base + local variations | Expensive generation once, cheap synthesis daily |
| 23 | TTS cache hint declared by blueprint author, not auto-detected | System doesn't guess cacheability — author knows intent |
| 24 | Midnight cache warmup pre-generates Tier 2 phrases | Zero API latency at runtime for templated TTS |
| 25 | TTS cache is system-level infrastructure; cache hints are blueprint-level metadata | Blueprint authors declare cacheability, system manages the cache. No ambiguity about ownership |
| 26 | Audio routing separate from voice routing: voice follows presence, music targets explicit speakers | Wake-up melody on living room speaker while voice alarm on bedroom speaker — different routing needs |
| 27 | TTS queue manager supports 4 target modes: presence, explicit, broadcast, source_room | Unified service interface covers all speaker targeting scenarios |
| 28 | Email promotion requires priority filter — not all email gets promoted to L2 | High-volume inbox would overwhelm agent context; whitelist + keyword filtering gates promotion |
| 29 | Email data is always per-user scoped, never in household L2 scope | Privacy hard constraint — agent must never reference wrong user's email |
| 30 | Calendar promotion runs at midnight + on calendar update events; email promotion is real-time via IMAP trigger | Calendar is batch-promotable; email needs reactive trigger for timely notifications |
| 31 | ~~Chime TTS = audio playback backend~~ → TTS queue manager built entirely in Pyscript | Chime TTS evaluated but not adopted. `tts_queue.py` handles priority queue, cache tiers, routing, ducking (hardware + software, Decision #52), and playback via direct `tts.speak` / `media_player.play_media` calls. No HACS playback dependency. |
| 32 | Official ElevenLabs integration with multiple entries (one per agent voice) over custom integration voice profiles | Declarative identity, no HACS dependency for core TTS, clean 1:1:1 agent→pipeline→TTS entity mapping |
| 33 | No Node-RED or external orchestration engines — all logic in native HA YAML + Pyscript | Node-RED creates parallel state management, can't expose flows as blueprints, doubles debug surface |
| 34 | Piper TTS shelved — future local fallback/ambient option, not current build scope | ElevenLabs voices needed for agent personality quality. Piper = config change when ready, not architecture change |
| 35 | Port proven patterns (PEveleigh dispatcher, HA native cache), build custom layers (memory, TTS queue, routing, inter-agent) | "Build the architecture, steal the plumbing" — don't reinvent solved problems, innovate where nobody has. TTS queue built custom after evaluating Chime TTS. |
| 36 | Anti-ADHD focus guards as first-class architecture feature, not afterthought | Builder has ADHD. System that helps you focus is as important as system that entertains. Uses same proactive infrastructure (L1+L2+L3, TTS queue, agent personality) |
| 37 | Focus mode has max duration (2h default), calendar always bypasses | Prevents user from silencing the system permanently when the system's job is to prevent exactly that behavior |
| 38 | Each build phase must produce independently useful checkpoint | Risk R-9 mitigation. If builder abandons at any phase boundary, what exists still works. No phase leaves the system in a broken intermediate state |
| 39 | Architecture doc follows arc42-inspired structure with lean ADR-style decisions log | Industry standard (adapted). Sections: Stakeholders, Constraints, Quality Scenarios, Risks, Design Considerations, Build Order, Glossary |
| 40 | User Context Profile defined as structured spec within L1 | Agents fly blind today — name and time only. Spec defines static profile (helpers) + dynamic context (template sensor) + target output format. Single injection point for all 20 agent sub-entries |
| 41 | System Profile section added with live-audited hardware/software inventory | Architecture doc must reflect real system, not assumptions. RPi5 + 2TB NVMe SSD + 8GB RAM + 4 agents + 13 pipelines + 25 HACS integrations documented from SSH audit |
| 42 | Agent roster: Rick, Quark, Deepee (Deadpool), Kramer — four active personas, not two | Doc previously referenced "Rick, Quark, future agents" — reality is 4 personas with 20 sub-entries across 5 modes (default, verbose, bedtime, coming home, music) |
| 43 | Sub-entry consolidation: Option B — Standard + Bedtime per agent (8 total, down from 18) | Bedtime has genuinely different tools (audiobook, countdown) and safety concerns. All other variants (verbose, music, coming home) are context flavors that L1 hot context eliminates. |
| 44 | Standard Agent Prompt Template defined — 8-section ordered structure | Identity → L1 injection → multi-agent awareness → memory → TTS rules → tool policy → personality → mode instructions. Universal sections shared, persona sections unique. Target ≤1,200 tokens. |
| 45 | `get_current_time_12h` function to be removed from all agents — L1 makes it obsolete | Only present in 2/18 sub-entries (Rick standard, Kramer standard). L1 hot context injects time continuously. |
| 46 | Blueprint → Agent Call Map documented — 18 blueprints, 65 conversation.process calls | Full mapping of which blueprint calls which agent with what context. All context patterns (area, time, media, mode) map to L1 sensor fields. Bedtime blueprints account for 48/65 calls. |
| 47 | OpenWebUI Conversation integration removed — installed July 2025, never configured, uninstalled via HACS | Dead code cleanup. 24 HACS integrations remaining. |
| 48 | All primary TTS speakers support MEDIA_ANNOUNCE — constraint updated | Sonos, Voice PE, Music Assistant players all support announce mode. Only Alexa devices and Philips TV don't, but these aren't voice agent TTS targets. |
| 49 | Migration from Extended OpenAI Conversation to HA Voice Assistants | Native Assist Pipelines provide declarative 1:1:1 mapping of conversation agent → TTS → STT per pipeline. Eliminates HACS dependency for core agent routing. 8 pipelines replace 20 sub-entries. |
| 50 | Pipeline-aware dispatcher discovers personas from Assist Pipelines | Dispatcher reads `.storage/assist_pipeline.pipelines` at startup, builds cache of personas, entity_map, wake_word_map, pipeline_map. Convention: `conversation.{persona}_{variant}`. No hardcoded agent dicts. |
| 51 | Identity layer uses WiFi+GPS+FP2 instead of G3 face recognition | G3 face recognition unreliable for single-user household. WiFi presence + GPS geofencing + FP2 zone sensors provide sufficient identity confidence. Decision #13 superseded. |
| 52 | Dual-mode volume ducking: hardware (Sonos announce) or software (pyscript capture/restore) per speaker | `tts_speaker_config.json` `speaker_options` section. Hardware = speaker handles ducking natively (default). Software = tts_queue.py captures volume before TTS, restores after PLAYBACK_BUFFER delay. Toggle: `input_boolean.ai_tts_volume_restore`. |
| 53 | Dispatch keywords auto-updated from whisper topics after each conversation | `agent_whisper.py` `_auto_update_keywords()` merges recent L2 topic slugs into `dispatch_keywords:{agent}`. Manual keywords (`!`-prefixed) preserved. Capped at 30 auto keywords, rate-limited 5min/agent. |

---

## Glossary

Architecture-specific terms used throughout this document. If a term isn't here, it's either standard HA terminology or standard English.

| Term | Definition |
|------|-----------|
| **L1 / Hot Context** | Real-time state data (time, presence, media, house mode) from HA template sensor. Zero latency. |
| **L2 / Warm Context** | Persistent memory in Pyscript SQLite. User preferences, conversation history, learned patterns. ~200ms query. |
| **L3 / Cold Context** | External service data (calendar, email). High latency, promoted to L2 by automations. |
| **Promotion** | Moving L3 data into L2 for faster access. E.g., calendar events promoted to L2 at midnight. |
| **Cache Hint** | Blueprint-declared metadata indicating TTS cacheability: `static`, `daily`, `session`, or `none`. |
| **Cache Tier** | Classification of TTS output by how often it changes. Tier 1 (static) = cache forever. Tier 2 (daily) = regenerate at midnight. |
| **Midnight Warmup** | Pre-generating Tier 2 TTS phrases at midnight so they're cached before first use. |
| **Conductor** | The dispatcher agent that decides which specialist agent handles a query. Has its own personality. |
| **Handoff with Commentary** | Inter-agent Pattern 3: conductor responds, then hands off to specialist with a transition comment. |
| **Whisper Network** | Inter-agent Pattern 5: agents write mood/context to L2 without externalizing to user. Internal-only. |
| **Creep Factor Gate** | Hard constraint: predictions inform timing of actions, never announce predicted behavior. The system never says "I knew you'd do that." |
| **Duck / Ducking** | Temporarily lowering media volume when TTS speaks, then restoring. Hardware mode (Sonos announce) or software mode (tts_queue.py capture/restore). |
| **Focus Mode** | User-activated DND that suppresses non-essential nudges. Max duration 2h. Calendar always bypasses. |
| **Focus Guards** | DC-12. Proactive nudge system for time awareness, meal reminders, social nudges, calendar warnings. |
| **Identity Confidence** | 0-100% score fusing FP2 presence + phone tracking + face detection. > 70% = full personal, < 30% = guest mode. |
| **Privacy Fence** | Per-user L2 scoping that prevents cross-user data leakage. Miquel's memories never appear in Jessica's agent context. |
| **TTS Queue Manager** | Custom Pyscript service (`pyscript.tts_queue_speak`) wrapping all TTS calls. Priority queue + cache + routing + direct `tts.speak`/`media_player.play_media` playback. |
| **Target Mode** | Speaker routing strategy: `presence` (follow user), `explicit` (named speaker), `broadcast` (all), `source_room` (respond where asked). |
| **Extended OpenAI Conversation** | HACS integration enabling GPT-4 as HA conversation agent with function calling. Core of our agent framework. |
| **Pyscript** | HACS integration adding Python scripting to HA. Runs our L2 memory engine and TTS queue manager. |
| **FP2** | Aqara FP2 mmWave presence sensor. Detects human presence by zone but cannot distinguish individuals. |
| **Blueprint** | HA reusable automation template. Our voice system is organized as a library of blueprints across 9 domains. |
| **DC** | Design Consideration. Cross-cutting architectural concern (DC-1 through DC-12). |
| **ADR** | Architecture Decision Record. Our Decisions Log is a lean ADR implementation. |

---

## References

- Build log: `_build_logs/2026-02-28_memory_auto_relationships_spec.md`
- luuquangvu GitHub: https://github.com/luuquangvu/tutorials
- HA Community thread: https://community.home-assistant.io/t/voice-assistant-long-term-memory/935090
- Migration plan: Phase 1 in `ha_voice_migration_plan.md`
- simple-memory-mcp (Claude Desktop): https://github.com/chrisribe/simple-memory-mcp
- ~~Chime TTS~~ (evaluated, not adopted): https://github.com/nimroddolev/chime_tts
- ElevenLabs official integration: https://www.home-assistant.io/integrations/elevenlabs/
- loryanstrant Custom TTS (evaluated, not adopted): https://github.com/loryanstrant/HA-ElevenLabs-Custom-TTS
- PEveleigh multi-agent dispatcher: HA Community, Aug 2024 (Extended OpenAI Conversation multi-agent routing)
- EL-HARP activity prediction paper: PMC (feature engineering reference only)
- arc42 architecture documentation template: https://arc42.org/ (structural inspiration for this document)
- C4 model for software architecture: https://c4model.com/ (context boundary diagram approach)
- Architecture Decision Records: https://adr.github.io/ (ADR methodology reference)
