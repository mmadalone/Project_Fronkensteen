# Helper Setup Guide

Project Fronkensteen uses Home Assistant `input_*` helpers for user configuration. This guide tells you what to set up and in what order.

---

## Helper Tiers

| Tier | Count | Source File(s) | Description |
|------|-------|---------------|-------------|
| **Essential** | 217 | `helpers_input_boolean.yaml`, `helpers_input_text.yaml`, `helpers_input_number.yaml`, `helpers_input_select.yaml`, `helpers_input_datetime.yaml`, `helpers_input_button.yaml`, `helpers_counter.yaml` | Core helpers. Kill switches, user-facing config, system state. |
| **Per-User** | 80 | `packages/ai_per_user_helpers.yaml` | Cloned per household member. Profiles, schedules, privacy thresholds. |
| **Dev Tuning** | 126 | `packages/ai_dev_helpers.yaml` | Algorithm parameters. All have safe defaults hardcoded in pyscript modules. Optional. |

**Total: 423 helpers**

> **Dev Tuning helpers are entirely optional.** Every pyscript module has a hardcoded fallback for each parameter. Install the dev tuning package only if you want to fine-tune algorithm behavior from the UI.

---

## Quick-Start Checklist

Configure these helpers after installation. Everything else has sensible defaults.

### 1. Identity (required)

| Helper | Type | What to Set |
|--------|------|-------------|
| `input_text.ai_primary_user` | text | Your HA person slug (e.g., `alice`). Used as fallback when occupancy can't resolve who's home. |
| `input_text.ai_context_user_name` | text | Your display name (e.g., `Miquel`) |
| `input_text.ai_context_user_name_spoken` | text | How TTS should pronounce your name (e.g., `Mee-kel`) |
| `input_text.ai_context_user_languages` | text | Languages you speak, comma-separated |
| `input_text.ai_context_household` | text | Household members (e.g., `Miquel, Jessica (partner)`) |
| `input_text.ai_context_pets` | text | Pets or `none` |
| `input_select.ai_context_preferred_language` | select | Your preferred response language |

### 2. Per-User Helpers (required per person)

Clone the blocks in `packages/ai_per_user_helpers.yaml` for each person in your household. Replace the `_person1` / `_person2` suffixes with your HA person slugs.

**Must set per person:**

| Helper Pattern | Type | What to Set |
|----------------|------|-------------|
| `ai_context_user_name_{person}` | text | Person's display name |
| `ai_context_user_name_spoken_{person}` | text | TTS pronunciation |
| `ai_context_user_languages_{person}` | text | Languages spoken |
| `ai_context_wake_time_weekday_{person}` | datetime | Weekday wake time (e.g., 07:30) |
| `ai_context_wake_time_weekend_{person}` | datetime | Weekend wake time (e.g., 09:00) |
| `ai_context_bed_time_{person}` | datetime | Target bedtime (e.g., 22:30) |
| `ai_context_preferred_language_{person}` | select | Preferred language |

The remaining per-user helpers (verbosity, humor, social style, pet peeves, etc.) are populated by the **User Interview** system. You can also set them manually.

### 3. Schedule & Sleep (recommended)

| Helper | Type | Default | What to Set |
|--------|------|---------|-------------|
| `input_number.ai_target_sleep_hours` | number | — | Target hours of sleep (5-10) |
| `input_number.ai_morning_prep_buffer` | number | — | Minutes from wake to first commitment (15-90) |
| `input_datetime.ai_context_bed_time` | datetime | — | Household bedtime target |
| `input_datetime.ai_sleep_window_start` | datetime | — | When sleep detection begins monitoring |
| `input_datetime.ai_sleep_window_end` | datetime | — | When sleep detection stops monitoring |

### 4. Speakers & TTS (required for voice)

| Helper | Type | What to Set |
|--------|------|-------------|
| `input_text.ai_default_speaker` | text | Entity ID of your default speaker (e.g., `media_player.living_room`) |
| `input_text.ai_default_tts_voice` | text | Default TTS voice identifier |
| `input_text.ai_tts_zone_priority` | text | CSV of zones in priority order for speaker selection |
| `input_text.ai_tts_restore_satellites` | text | CSV of satellite entity IDs to monitor during volume restore |

Also configure `pyscript/tts_speaker_config.json` — the single source of truth for zone-to-speaker mapping.

### 5. Budget & API Keys (required for LLM features)

| Helper | Type | Default | What to Set |
|--------|------|---------|-------------|
| `input_number.ai_llm_daily_limit` | number | — | Max LLM calls per day |
| `input_number.ai_llm_daily_token_limit` | number | — | Max tokens per day |
| `input_number.ai_tts_daily_limit` | number | — | Max TTS calls per day |
| `input_number.ai_budget_daily_cost_limit` | number | — | Daily cost cap in your currency |
| `input_text.ai_embedding_api_url` | text | OpenRouter | Your embedding API endpoint |
| `input_text.ai_embedding_api_key` | text | — | Your API key (stored as password) |
| `input_text.ai_embedding_model` | text | `text-embedding-3-small` | Embedding model name |
| `input_text.ai_task_instance` | text | `sensor.ha_text_ai_deepseek_chat` | Your ha_text_ai sensor entity |
| `input_text.ai_budget_fallback_agent` | text | `homeassistant` | Conversation agent to use when budget is exceeded |
| `input_number.ai_elevenlabs_credit_floor` | number | 5000 | Character count floor before TTS swaps to HA Cloud. Set negative to disable (allow overage). |
| `input_select.ai_budget_currency` | select | `EUR` | Your preferred currency symbol |

### 6. Email (if using email features)

| Helper | Type | What to Set |
|--------|------|-------------|
| `input_text.ai_email_known_contacts` | text | Comma-separated trusted emails/domains |
| `input_text.ai_email_priority_keywords` | text | Custom priority keywords (added to built-in list) |
| `input_text.ai_email_blocked_senders` | text | Senders/domains to block |
| `input_text.ai_email_blocked_keywords` | text | Subject keywords to block |
| `input_text.ai_email_urgent_keywords` | text | Keywords that trigger urgent announcement |
| `input_select.ai_email_filter_mode` | select | `whitelist`, `blacklist`, or `hybrid` |

### 7. Presence Sensors (if using FP2/presence features)

| Helper | Type | What to Set |
|--------|------|-------------|
| `input_select.ai_sleep_detection_sensor` | select | Your bed presence sensor |
| `input_select.ai_sleep_lights_sensor` | select | Presence sensor for sleep lights |
| `input_select.ai_sleep_lights_light_picker` | select | Light entity for sleep lights |
| `input_boolean.ai_fp2_zone_*_enabled` | boolean | Enable/disable zones for presence tracking (8 zones) |

---

## Feature Kill Switches

Every major feature has a master toggle (`input_boolean`). All default to ON unless noted. Turn OFF to disable a feature entirely without removing its configuration.

| Kill Switch | Feature | Default |
|-------------|---------|---------|
| `ai_dispatcher_enabled` | Agent Dispatcher | ON |
| `ai_voice_handoff_enabled` | Voice Handoff | ON |
| `ai_whisper_enabled` | Agent Whisper Network | ON |
| `ai_reactive_banter_enabled` | Reactive Banter | ON |
| `ai_proactive_briefing_enabled` | Proactive Briefing | ON |
| `ai_notification_follow_me` | Notification Follow-Me | ON |
| `ai_email_master_toggle` | Email Follow-Me | ON |
| `ai_email_promotion_enabled` | Email Promotion | ON |
| `ai_dedup_enabled` | Notification Dedup | ON |
| `ai_duck_manager_enabled` | Volume Ducking | ON |
| `ai_music_follow_me` | Music Follow-Me | ON |
| `ai_music_composer_enabled` | Music Composition | ON |
| `ai_music_taste_enabled` | Music Taste Extraction | ON |
| `ai_calendar_promotion_enabled` | Calendar Promotion | ON |
| `ai_routine_tracking_enabled` | Routine Tracker | ON |
| `ai_presence_patterns_enabled` | Presence Patterns | ON |
| `ai_presence_identity_enabled` | Per-Person Room Inference | ON |
| `ai_sleep_detection_enabled` | Sleep Detection | ON |
| `ai_focus_guard_enabled` | Focus Guard (anti-ADHD) | ON |
| `ai_winddown_enabled` | Bedtime Wind-Down | ON |
| `ai_theatrical_mode_enabled` | Theatrical Debates | ON |
| `ai_therapy_enabled` | Therapy Mode | ON |
| `ai_escalation_enabled` | Escalation Follow-Through | ON |
| `ai_privacy_gate_enabled` | Privacy Gate | ON |
| `ai_auto_off_enabled` | Auto-Off (lights/media) | ON |
| `ai_entity_history_enabled` | Entity History Queries | ON |
| `ai_media_tracking_enabled` | Radarr/Sonarr Tracking | ON |
| `ai_project_tracking_enabled` | Project Tracking | ON |
| `ai_contact_history_enabled` | Contact History | ON |
| `ai_away_patterns_enabled` | Away Patterns | ON |
| `ai_entropy_correlation_enabled` | Entropy Correlation | ON |
| `ai_scene_learner_enabled` | Scene Preference Learning | ON |
| `ai_voice_mood_enabled` | Voice Mood Modulation | ON |
| `ai_conversation_sensor_enabled` | Conversation Sensor | ON |
| `ai_toggle_audit_enabled` | Toggle Audit Trail | ON |
| `ai_system_recovery_enabled` | System Recovery Engine | ON |
| `ai_memory_auto_archive` | Memory Auto-Archive | ON |
| `ai_memory_search_enrich` | Memory Search Enrichment | ON |
| `ai_memory_semantic_autolink` | Semantic Autolink | **OFF** |
| `ai_ambient_music_enabled` | Ambient Music | **OFF** |
| `ai_notifications_master_enabled` | All Notifications (gate) | ON |
| `ai_budget_fallback_active` | Budget Fallback Mode | OFF (set by system) |
| `ai_test_mode` | Test Mode | **OFF** |
| `ai_tts_test_mode` | TTS Test Mode (HA Cloud) | **OFF** |

---

## What NOT to Touch

These helpers are **system-managed** (written by code, not by users). Don't set them manually:

- `input_boolean.ai_tts_queue_active` — Set by TTS queue when processing
- `input_boolean.ai_bedtime_global_lock` — Set by bedtime negotiator
- `input_boolean.ai_focus_mode` — Set by voice command ("I need to focus")
- `input_boolean.ai_guest_mode` — Set by presence identity system
- `input_boolean.ai_interview_mode` — Set by interview system
- `input_boolean.ai_therapy_mode` — Set by therapy system
- `input_boolean.ai_sleep_false_positive_flag` — Set by sleep detection
- `input_boolean.ai_wake_up_snooze` / `ai_wake_up_stop` — Set by wake-up guard
- `input_boolean.ai_budget_fallback_active` — Set by budget gate
- `input_text.ai_notification_follow_me_*` — Managed by notification system
- `input_text.ai_email_follow_me_*` — Managed by email system
- `input_text.ai_memory_*` — Dashboard UI fields
- `input_datetime.ai_*_last_*` / `ai_*_session_*` — Timestamps set by automations
- `counter.ai_notification_follow_me_bypass_refcount` — Managed by refcount system

---

## File Locations

| File | Path | Description |
|------|------|-------------|
| Essential helpers | `config/helpers_input_*.yaml`, `helpers_counter.yaml` | Core helper definitions |
| Per-user helpers | `config/packages/ai_per_user_helpers.yaml` | Clone per household member |
| Dev tuning | `config/packages/ai_dev_helpers.yaml` | Optional algorithm parameters |
| Speaker config | `config/pyscript/tts_speaker_config.json` | Zone-to-speaker mapping |
| Entity config | `config/pyscript/entity_config.yaml` | Persons, duck groups, vsync zones |
| Voice mood map | `config/pyscript/voice_mood_profile_map.json` | Voice profile-to-agent mapping |

---

## Next Steps

- See [helpers_reference.md](helpers_reference.md) for the full reference of every helper with detailed descriptions.
- See [entity_config.yaml](../pyscript/entity_config.yaml) for person, duck, and vsync zone configuration.
- See [tts_speaker_config.json](../pyscript/tts_speaker_config.json) for speaker zone mapping.
