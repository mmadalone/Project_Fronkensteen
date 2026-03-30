# Helper Reference

Complete reference for all Project Fronkensteen helpers, organized by feature.

**Legend:**
- **Tier E** = Essential (standalone helper files)
- **Tier U** = Per-User (clone per household member)
- **Tier D** = Dev Tuning (optional, safe defaults in code)
- **[system]** = Written by code, not user-configured
- **[config]** = User must configure for their setup

---

## Table of Contents

1. [System Setup](#1-system-setup)
2. [Agent Dispatcher](#2-agent-dispatcher)
3. [Voice Handoff](#3-voice-handoff)
4. [Agent Whisper Network](#4-agent-whisper-network)
5. [Reactive Banter](#5-reactive-banter)
6. [Escalation Follow-Through](#6-escalation-follow-through)
7. [Theatrical Mode](#7-theatrical-mode)
8. [Therapy Session](#8-therapy-session)
9. [User Interview](#9-user-interview)
10. [TTS Queue & Speakers](#10-tts-queue--speakers)
11. [Duck Manager (Volume Ducking)](#11-duck-manager-volume-ducking)
12. [Voice Mood Modulation](#12-voice-mood-modulation)
13. [Notification Follow-Me](#13-notification-follow-me)
14. [Notification Deduplication](#14-notification-deduplication)
15. [Email Follow-Me & Priority Filter](#15-email-follow-me--priority-filter)
16. [Proactive Briefing](#16-proactive-briefing)
17. [Bedtime System](#17-bedtime-system)
18. [Wind-Down System](#18-wind-down-system)
19. [Wake-Up System](#19-wake-up-system)
20. [Sleep Detection](#20-sleep-detection)
21. [Predictive Schedule](#21-predictive-schedule)
22. [Routine Tracker](#22-routine-tracker)
23. [Focus Guard (Anti-ADHD)](#23-focus-guard-anti-adhd)
24. [Presence Identity](#24-presence-identity)
25. [Presence Patterns](#25-presence-patterns)
26. [Away Patterns](#26-away-patterns)
27. [Privacy Gate](#27-privacy-gate)
28. [Hot Context](#28-hot-context)
29. [LLM Budget & Cost Control](#29-llm-budget--cost-control)
30. [Calendar Promotion](#30-calendar-promotion)
31. [Memory & Embedding](#31-memory--embedding)
32. [Media Tracking](#32-media-tracking)
33. [Music Composer](#33-music-composer)
34. [Music Taste](#34-music-taste)
35. [Music Follow-Me](#35-music-follow-me)
36. [Auto-Off / Auto-On](#36-auto-off--auto-on)
37. [Scene Learner & Circadian](#37-scene-learner--circadian)
38. [Project Tracking](#38-project-tracking)
39. [Entity History](#39-entity-history)
40. [Contact History](#40-contact-history)
41. [Entropy Correlation](#41-entropy-correlation)
42. [Conversation Sensor](#42-conversation-sensor)
43. [Phone Call Detection](#43-phone-call-detection)
44. [Alexa Integration](#44-alexa-integration)
45. [Test Harness](#45-test-harness)
46. [System Recovery](#46-system-recovery)
47. [Toggle Audit](#47-toggle-audit)
48. [Per-User Helpers](#48-per-user-helpers)

---

## 1. System Setup

| Entity ID | Type | Tier | Purpose | Default |
|-----------|------|------|---------|---------|
| `input_text.ai_primary_user` | text | E [config] | Person slug used as fallback when occupancy can't resolve the active user. Set once during setup. | — |
| `input_text.ai_context_user_name` | text | U [config] | Primary user's display name. Household-level (not per-person). | — |
| `input_text.ai_context_user_name_spoken` | text | U [config] | How TTS should pronounce the primary user's name. | — |
| `input_text.ai_context_user_languages` | text | U [config] | Languages the primary user speaks, comma-separated. | — |
| `input_text.ai_context_household` | text | U [config] | Household members description (e.g., `Miquel, Jessica (partner)`). | — |
| `input_text.ai_context_pets` | text | U [config] | Pets in the household, or `none`. | — |
| `input_datetime.ai_time_placeholder` | datetime | E | Placeholder time entity for blueprint inputs that require a time trigger. Satisfies HA validation; preference toggles gate actual firing. **Do not delete.** | — |

---

## 2. Agent Dispatcher

The dispatcher routes conversations to AI personas based on keywords, time-of-day, and mode.

| Entity ID | Type | Tier | Purpose | Default |
|-----------|------|------|---------|---------|
| `input_boolean.ai_dispatcher_enabled` | boolean | E | Master kill switch for the dispatcher. | ON |
| `input_boolean.ai_keyword_manual` | boolean | E | When ON, manually-added keywords are "sticky" (prefixed with `!` in memory). | ON |
| `input_select.ai_dispatcher_mode` | select | E | Routing mode. **auto**: keyword + era matching. **round_robin**: cycle through agents. **fixed**: always use `ai_dispatcher_fixed_agent`. **random**: random selection. | `auto` |
| `input_select.ai_dispatcher_era_morning` | select | E | Preferred persona for morning hours. **rotate** cycles through all. **none** skips era preference. Options populated dynamically from discovered pipelines. | — |
| `input_select.ai_dispatcher_era_afternoon` | select | E | Preferred persona for afternoon hours. | — |
| `input_select.ai_dispatcher_era_evening` | select | E | Preferred persona for evening hours. | — |
| `input_select.ai_dispatcher_era_late_night` | select | E | Preferred persona for late night hours. | — |
| `input_text.ai_dispatcher_fixed_agent` | text | E | Persona slug to use when mode is `fixed`. | — |
| `input_text.ai_dispatcher_agent_pool` | text | E | Comma-separated list of persona slugs to include in rotation/random. Empty = all discovered. | — |
| `input_text.ai_dispatcher_fallback_pipeline` | text | E | Pipeline to use when dispatcher cache fails (bypass mode). | `homeassistant` |
| `input_text.ai_keyword_add` | text | E | Dashboard field: type a keyword here then press Apply Config to add it to the selected agent. | — |
| `input_text.ai_keyword_remove` | text | E | Dashboard field: type a keyword to remove from the selected agent. | — |
| `input_select.ai_keyword_agent_select` | select | E | Dashboard field: which agent the keyword add/remove applies to. Options populated dynamically. | — |
| `input_button.ai_dispatcher_apply_config` | button | E | Dashboard button: applies keyword add/remove operations. | — |
| `input_number.ai_conversation_continuity_window` | number | D | Minutes to keep routing to the same agent after a conversation. Prevents mid-topic persona switches. | slider, 1-30 min |
| `input_number.ai_dispatcher_cache_ttl` | number | D | Seconds before the dispatcher's pipeline cache expires and rebuilds. | 300s |

---

## 3. Voice Handoff

Allows one AI persona to transfer a conversation to another mid-session.

| Entity ID | Type | Tier | Purpose | Default |
|-----------|------|------|---------|---------|
| `input_boolean.ai_voice_handoff_enabled` | boolean | E | Master kill switch. | ON |
| `input_boolean.ai_voice_pin_enabled` | boolean | E | When ON, handoffs require a voice PIN for security. | OFF |
| `input_text.ai_handoff_persona_aliases` | text | E | Comma-separated alias mappings (e.g., `doc=doctor_portuondo,dp=deadpool`). Lets users say nicknames. | — |
| `input_select.ai_handoff_llm_lines_mode` | select | E | How farewell/greeting lines are generated. **static**: hardcoded lines. **ha_text_ai**: LLM generates lines via ha_text_ai. **conversation_agent**: uses the conversation agent. | `static` |

---

## 4. Agent Whisper Network

Agents share context about conversations, moods, and topics via a background network.

| Entity ID | Type | Tier | Purpose | Default |
|-----------|------|------|---------|---------|
| `input_boolean.ai_whisper_enabled` | boolean | E | Master kill switch. | ON |
| `input_boolean.ai_whisper_mood_detection` | boolean | E | Detect user mood from conversations and share across agents. | ON |
| `input_number.ai_whisper_interaction_expiry_days` | number | D | Days before interaction records expire from the whisper network. | 2 |
| `input_number.ai_whisper_mood_expiry_days` | number | D | Days before mood observations expire. | 1 |
| `input_number.ai_whisper_topic_expiry_days` | number | D | Days before topic records expire. | 3 |
| `input_number.ai_whisper_mood_dedup_seconds` | number | D | Minimum seconds between mood detections for the same user. Prevents spam. | 3600 |
| `input_number.ai_whisper_max_auto_keywords` | number | D | Max auto-generated keywords per agent (manually-added `!` keywords are exempt). | 30 |
| `input_number.ai_whisper_keyword_cooldown` | number | D | Minimum seconds between keyword auto-update runs per agent. | 300 |
| `input_number.ai_whisper_topic_history_count` | number | D | Number of recent topics injected into agent prompts as hot context. | 5 |

---

## 5. Reactive Banter

Agents spontaneously comment on household events (someone arriving, lights changing, etc.).

| Entity ID | Type | Tier | Purpose | Default |
|-----------|------|------|---------|---------|
| `input_boolean.ai_reactive_banter_enabled` | boolean | E | Master kill switch. | ON |
| `input_datetime.ai_banter_last_reaction` | datetime | E [system] | Timestamp of the last banter reaction. Used for cooldown enforcement. | — |

---

## 6. Escalation Follow-Through

Agents occasionally escalate responses with physical actions (light flash, volume boost, notification, etc.).

| Entity ID | Type | Tier | Purpose | Default |
|-----------|------|------|---------|---------|
| `input_boolean.ai_escalation_enabled` | boolean | E | Master kill switch. | ON |
| `input_datetime.ai_escalation_last_followthrough` | datetime | E [system] | Last escalation time. Used for cooldown. | — |
| `input_number.ai_escalation_probability` | number | D | Global probability (%) that any response triggers an escalation. | 15% |
| `input_number.ai_escalation_cooldown_minutes` | number | D | Minimum minutes between escalations. | 30 |
| `input_number.ai_escalation_prob_persona_switch` | number | D | Probability (%) of escalation type: switch to another persona. | 10% |
| `input_number.ai_escalation_prob_play_media` | number | D | Probability: play a sound effect. | 15% |
| `input_number.ai_escalation_prob_light_flash` | number | D | Probability: flash a light. | 40% |
| `input_number.ai_escalation_prob_volume_boost` | number | D | Probability: temporarily boost volume. | 30% |
| `input_number.ai_escalation_prob_send_notification` | number | D | Probability: send a phone notification. | 50% |
| `input_number.ai_escalation_prob_prompt_barrage` | number | D | Probability: rapid-fire follow-up messages. | 25% |
| `input_number.ai_escalation_prob_run_script` | number | D | Probability: execute an HA script. | 20% |

---

## 7. Theatrical Mode

Multi-agent debates where two personas argue a topic in front of the user.

| Entity ID | Type | Tier | Purpose | Default |
|-----------|------|------|---------|---------|
| `input_boolean.ai_theatrical_mode_enabled` | boolean | E | Master kill switch. | ON |
| `input_datetime.ai_theatrical_last_exchange` | datetime | E [system] | Last debate exchange timestamp. | — |
| `input_number.ai_theatrical_turn_limit` | number | D | Max turns per debate before auto-ending. | 6 |
| `input_number.ai_theatrical_max_words` | number | D | Max words per agent turn. Keeps debates snappy. | 40 |
| `input_number.ai_theatrical_budget_floor` | number | D | Budget must be above this % to allow a debate. Prevents draining budget on debates. | 70% |
| `input_select.ai_theatrical_interrupt_mode` | select | D | How user interrupts a debate. **mic_gap**: pause when mic activates. **turn_limit**: stop at turn limit. **wake_word**: stop on wake word. | `turn_limit` |
| `input_select.ai_theatrical_context_mode` | select | D | Context given to debating agents. **full**: full hot context. **topic_only**: just the debate topic. **whisper**: whisper network context only. | `full` |
| `input_select.ai_theatrical_turn_order` | select | D | Turn ordering. **round_robin**: alternating. **random**: random selection each turn. | `round_robin` |

---

## 8. Therapy Session

Guided self-reflection sessions with a therapeutic AI persona.

| Entity ID | Type | Tier | Purpose | Default |
|-----------|------|------|---------|---------|
| `input_boolean.ai_therapy_enabled` | boolean | E | Master kill switch. | ON |
| `input_boolean.ai_therapy_mode` | boolean | E [system] | ON when a therapy session is active. Set by the system. | OFF |
| `input_datetime.ai_therapy_session_start` | datetime | E [system] | Start time of current session. | — |
| `input_datetime.ai_therapy_last_session` | datetime | E [system] | Timestamp of most recent completed session. | — |

---

## 9. User Interview

Structured interviews to learn user preferences (populated into per-user helpers).

| Entity ID | Type | Tier | Purpose | Default |
|-----------|------|------|---------|---------|
| `input_boolean.ai_interview_mode` | boolean | E [system] | ON when an interview is active. | OFF |

---

## 10. TTS Queue & Speakers

Queues TTS messages, manages speaker selection, handles playback timing.

| Entity ID | Type | Tier | Purpose | Default |
|-----------|------|------|---------|---------|
| `input_boolean.ai_tts_queue_active` | boolean | E [system] | ON while the TTS queue is processing. | OFF |
| `input_boolean.ai_tts_volume_restore` | boolean | E | Enable volume restoration after TTS playback (software ducking speakers). | ON |
| `input_boolean.ai_tts_strip_stage_directions` | boolean | E | Strip `*stage directions*` from TTS text before speaking. | ON |
| `input_text.ai_default_speaker` | text | E [config] | Entity ID of default speaker when zone detection fails. | — |
| `input_text.ai_default_tts_voice` | text | E [config] | Default TTS voice identifier. | — |
| `input_text.ai_tts_zone_priority` | text | E [config] | CSV of zone names in priority order. When multiple zones detect presence, first zone wins. | — |
| `input_text.ai_tts_restore_satellites` | text | E [config] | CSV of satellite entity IDs to monitor during dynamic volume restore. | — |
| `input_select.ai_tts_conflict_mode` | select | E | What to do when target speaker is already playing. **override**: interrupt. **wait**: queue behind current. **skip**: drop the message. | — |
| `input_select.ai_tts_restore_mode` | select | E | Volume restore strategy. **dynamic**: waits for TTS to finish. **fixed**: waits a fixed delay. | — |
| `input_number.ai_tts_playback_buffer` | number | D | Seconds of buffer before monitoring playback completion. | 0.5s |
| `input_number.ai_tts_poll_interval` | number | D | Seconds between playback state polls. | 0.25s |
| `input_number.ai_tts_max_timeout` | number | D | Max seconds to wait for playback to finish. | 30s |
| `input_number.ai_tts_post_buffer` | number | D | Seconds to wait after playback ends before restoring volume. | 0.3s |
| `input_number.ai_tts_max_ambient` | number | D | Max ambient (low-priority) messages in queue. | 3 |
| `input_number.ai_tts_default_duration` | number | D | Assumed TTS duration when actual duration unavailable. | 5s |
| `input_number.ai_tts_generation_buffer` | number | D | Seconds to wait for TTS audio file generation. | 2.0s |
| `input_number.ai_tts_stuck_timeout_minutes` | number | D | Minutes before the queue auto-clears a stuck item. | 2 min |
| `input_number.ai_tts_restore_fixed_delay` | number | D | Fixed delay before volume restore (when restore mode = fixed). | slider, 0.5-25s |
| `input_number.ai_tts_restore_timeout` | number | D | Max seconds to wait during dynamic restore. | slider, 5-25s |
| `input_number.ai_tts_cache_static_max_days` | number | D | Max age for cached TTS audio files. | — |
| `input_number.ai_tts_cache_max_size_mb` | number | D | Max TTS cache size in MB. | — |
| `input_number.ai_tts_cache_protect_hours` | number | D | Hours during which recently-used cache entries are protected from eviction. | — |

---

## 11. Duck Manager (Volume Ducking)

Lowers media volume during TTS announcements, then restores it.

| Entity ID | Type | Tier | Purpose | Default |
|-----------|------|------|---------|---------|
| `input_boolean.ai_duck_manager_enabled` | boolean | E | Master kill switch. | ON |
| `input_boolean.ai_duck_guard_enabled` | boolean | E | Allow blueprints to update volume snapshots during ducking. Prevents stale snapshot bugs. | ON |
| `input_boolean.ai_duck_allow_manual_override` | boolean | E | Allow users to change volume manually during ducking without the manager fighting them. | ON |
| `input_select.ai_duck_behavior` | select | E | Ducking strategy. **volume**: lower volume only. **pause**: pause media playback. **both**: lower volume and pause. | — |
| `input_number.ai_duck_idle_delay` | number | E | Seconds of silence before considering a speaker "idle" (eligible for ducking). | slider, 1-60s |
| `input_number.ai_tts_duck_volume` | number | E | Volume level to duck media to during TTS (0-1). | slider |
| `input_number.ai_tts_announcement_volume` | number | E | Volume level for TTS announcements (0-1). | slider |
| `input_number.ai_duck_watchdog_timeout` | number | D | Max seconds a duck session can last before watchdog force-restores. | slider, 5-600s |
| `input_number.ai_duck_pre_delay_ms` | number | D | Milliseconds to wait after ducking before starting TTS. Avoids audio pop. | 0ms |
| `input_number.ai_duck_default_volume` | number | D | Fallback volume when no pre-duck snapshot exists. | 0.5 |
| `input_number.ai_duck_volume` | number | D | Duck Manager's own duck volume (may differ from TTS duck level). | 0.1 |
| `input_number.ai_duck_announce_volume` | number | D | Duck Manager's announcement volume. | 0.5 |
| `input_number.ai_duck_restore_delay` | number | D | Seconds to wait after TTS before restoring volume. | 0.5s |
| `input_number.ai_duck_restore_timeout` | number | D | Max seconds for restore to complete before force-restoring. | 25s |
| `input_number.ai_duck_post_buffer` | number | D | Seconds after restore before allowing another duck session. | 5s |

---

## 12. Voice Mood Modulation

Adjusts ElevenLabs TTS voice parameters (stability, style tags) based on agent personality.

| Entity ID | Type | Tier | Purpose | Default |
|-----------|------|------|---------|---------|
| `input_boolean.ai_voice_mood_enabled` | boolean | E | Master kill switch for all mood modulation. | ON |
| `input_number.ai_voice_mood_rick_stability` | number | D | ElevenLabs stability parameter for Rick. Lower = more expressive. | 0.45 |
| `input_number.ai_voice_mood_quark_stability` | number | D | Stability for Quark. | 0.55 |
| `input_number.ai_voice_mood_kramer_stability` | number | D | Stability for Kramer. | 0.35 |
| `input_number.ai_voice_mood_deadpool_stability` | number | D | Stability for Deadpool. | 0.30 |
| `input_number.ai_voice_mood_doctor_portuondo_stability` | number | D | Stability for Dr. Portuondo. | 0.60 |

---

## 13. Notification Follow-Me

Routes notifications to the speaker nearest to you.

| Entity ID | Type | Tier | Purpose | Default |
|-----------|------|------|---------|---------|
| `input_boolean.ai_notification_follow_me` | boolean | E | Master kill switch. | ON |
| `input_boolean.ai_notifications_master_enabled` | boolean | E | Global gate for ALL notification types. When OFF, nothing gets announced. | ON |
| `input_text.ai_notification_follow_me_bypass_log` | text | E [system] | Log of bypass owners. Managed by refcount system. | — |
| `input_text.ai_notification_follow_me_ledger` | text | E [system] | Tracking ledger for follow-me state. | — |
| `input_text.ai_notification_last_announced_sender_name_rick` | text | E [system] | Last announced sender name (for dedup). | — |
| `input_text.ai_notification_follow_me_reminder_loop_owner` | text | E [system] | Current owner of the reminder loop. | — |
| `input_text.ai_notification_follow_me_last_post_time` | text | E [system] | Epoch of last notification. | `0` |
| `input_datetime.ai_notification_last_announced` | datetime | E [system] | Timestamp of last announced notification. | — |
| `input_datetime.ai_notification_follow_me_reminder_loop_last_tick` | datetime | E [system] | Last tick of reminder loop. | — |
| `counter.ai_notification_follow_me_bypass_refcount` | counter | E [system] | Atomic refcount: first claim (0->1) disables follow-me, last release (1->0) re-enables. Watchdog resets if stale. | 0 |

---

## 14. Notification Deduplication

Prevents the same notification from being announced multiple times.

| Entity ID | Type | Tier | Purpose | Default |
|-----------|------|------|---------|---------|
| `input_boolean.ai_dedup_enabled` | boolean | E | Master kill switch. | ON |
| `input_number.ai_dedup_default_ttl` | number | D | Default minutes before a dedup entry expires (same message can be re-announced). | box, 1-720 min |
| `input_number.ai_dedup_cleanup_hours` | number | D | Max age in hours before old dedup entries are cleaned up. | 48h |

---

## 15. Email Follow-Me & Priority Filter

Announces important emails via TTS and filters out noise.

| Entity ID | Type | Tier | Purpose | Default |
|-----------|------|------|---------|---------|
| `input_boolean.ai_email_master_toggle` | boolean | E | Master kill switch for all email features. | ON |
| `input_boolean.ai_email_promotion_enabled` | boolean | E | Enable email promotion (escalates high-priority emails to TTS). | ON |
| `input_select.ai_email_filter_mode` | select | E [config] | **whitelist**: only known contacts + keywords pass. **blacklist**: everything passes except blocked. **hybrid**: known promoted, blocked filtered, unknown filtered. | `blacklist` |
| `input_text.ai_email_known_contacts` | text | E [config] | Comma-separated trusted senders/domains. Full emails: `mom@gmail.com`. Domains: `amazon.com` (matches any sender). | — |
| `input_text.ai_email_priority_keywords` | text | E [config] | Custom priority keywords (checked against subject). Added to built-in list. | — |
| `input_text.ai_email_blocked_senders` | text | E [config] | Senders/domains to block in blacklist/hybrid mode. | — |
| `input_text.ai_email_blocked_keywords` | text | E [config] | Subject keywords to block. | — |
| `input_text.ai_email_urgent_keywords` | text | E [config] | Keywords that trigger immediate TTS announcement regardless of filter mode. | — |
| `input_text.ai_email_last_announce_sender` | text | E [system] | Last announced email sender. | — |
| `input_text.ai_email_follow_me_dedup_uids` | text | E [system] | UIDs of recently announced emails (dedup). | — |
| `input_text.ai_email_follow_me_last_subject` | text | E [system] | Last announced email subject. | — |
| `input_datetime.ai_email_last_announce` | datetime | E [system] | Timestamp of last email announcement. | — |
| `input_number.ai_email_stale_timeout` | number | D | Minutes before IMAP sensor is considered stale. | 120 min |

---

## 16. Proactive Briefing

Scheduled briefings (morning, afternoon, evening) with calendar, weather, and context.

| Entity ID | Type | Tier | Purpose | Default |
|-----------|------|------|---------|---------|
| `input_boolean.ai_proactive_briefing_enabled` | boolean | E | Master kill switch. On-demand briefings still work. | ON |
| `input_boolean.ai_briefing_evening_manual_trigger` | boolean | E | Manually trigger an evening briefing from the dashboard. | OFF |
| `input_number.ai_briefing_morning_hour` | number | E | Hour when morning briefing window opens (0-12). | 5 |
| `input_number.ai_briefing_afternoon_hour` | number | E | Hour when afternoon briefing window opens (10-18). | 12 |
| `input_number.ai_briefing_evening_hour` | number | E | Hour when evening briefing window opens (14-23). | 17 |

---

## 17. Bedtime System

Bedtime negotiation, last-call reminders, and goodnight routines.

| Entity ID | Type | Tier | Purpose | Default |
|-----------|------|------|---------|---------|
| `input_boolean.ai_bedtime_global_lock` | boolean | E [system] | Global mutex preventing concurrent bedtime routines. | OFF |
| `input_boolean.ai_bedtime_now_manual_trigger` | boolean | E | Manual trigger: start bedtime routine immediately. | OFF |
| `input_boolean.ai_bedtime_now_rick` | boolean | E | Manual trigger: Rick's bedtime NOW. | OFF |
| `input_boolean.ai_bedtime_now_quark` | boolean | E | Manual trigger: Quark's bedtime NOW. | OFF |
| `input_boolean.ai_proactive_bedtime_escalation_killswitch` | boolean | E | Kill switch for proactive bedtime nagging. | ON |
| `input_number.ai_bedtime_now_countdown_minutes` | number | E | Minutes for the "bedtime NOW" countdown before lights off. | slider, 1-30 |
| `input_datetime.ai_session_timestamp_proactive_bedtime_escalation_rick` | datetime | E [system] | Session timestamp for escalation cooldown tracking. | — |
| `input_number.ai_gn_run_debounce_seconds` | number | D | Goodnight negotiator debounce in seconds. | box, 0-3600 |
| `input_number.ai_bedtime_relaxed_extension_minutes` | number | D | Extra minutes allowed in "relaxed" bedtime mode. | slider, 30-180 min |

---

## 18. Wind-Down System

Progressive bedtime preparation with escalating scenarios.

| Entity ID | Type | Tier | Purpose | Default |
|-----------|------|------|---------|---------|
| `input_boolean.ai_winddown_enabled` | boolean | E | Master kill switch. | ON |
| `input_datetime.ai_winddown_last_offer` | datetime | E [system] | Last time a wind-down offer was made. | — |
| `input_datetime.ai_winddown_session_start` | datetime | E [system] | When the current wind-down session started. | — |
| `input_number.ai_winddown_cooldown_minutes` | number | D | Minutes after a rejected offer before trying again. | 30 min |
| `input_select.ai_winddown_last_scenario` | select | D [system] | Last wind-down scenario attempted. **sleepy_tv**: user is on couch, sleepy. **bed_tv**: watching TV in bed. **bed_idle**: in bed doing nothing. **bed_non_sleepy**: in bed but not sleepy. | `none` |

---

## 19. Wake-Up System

Smart alarm with snooze and stop controls.

| Entity ID | Type | Tier | Purpose | Default |
|-----------|------|------|---------|---------|
| `input_boolean.ai_wake_up_snooze` | boolean | E [system] | ON when user has snoozed the alarm. | OFF |
| `input_boolean.ai_wake_up_stop` | boolean | E [system] | ON when user has stopped the alarm. | OFF |
| `input_boolean.ai_wake_up_guard_stop` | boolean | E | Emergency stop for the wake-up guard. | OFF |

---

## 20. Sleep Detection

Detects when the user falls asleep using presence sensors.

| Entity ID | Type | Tier | Purpose | Default |
|-----------|------|------|---------|---------|
| `input_boolean.ai_sleep_detection_enabled` | boolean | E | Master kill switch. | ON |
| `input_boolean.ai_sleep_false_positive_flag` | boolean | E [system] | Set when the system suspects a false positive sleep detection. | OFF |
| `input_select.ai_sleep_detection_sensor` | select | E [config] | Binary sensor used for sleep detection. Pick your bed presence sensor. | — |
| `input_select.ai_sleep_lights_sensor` | select | E [config] | Presence sensor for automatic sleep lights. | — |
| `input_select.ai_sleep_lights_light_picker` | select | E [config] | Light entity for sleep lights. | — |
| `input_datetime.ai_sleep_start` | datetime | E [system] | When sleep was detected. | — |
| `input_datetime.ai_sleep_end` | datetime | E [system] | When wake-up was detected. | — |
| `input_datetime.ai_sleep_window_start` | datetime | E [config] | Time when sleep detection monitoring begins (e.g., 22:00). | — |
| `input_datetime.ai_sleep_window_end` | datetime | E [config] | Time when monitoring stops (e.g., 10:00). | — |
| `input_number.ai_sleep_min_duration` | number | D | Minimum minutes of stillness before declaring sleep. | slider, 15-180 min |

---

## 21. Predictive Schedule

Predicts wake time, bedtime, and routine start based on calendar and patterns.

| Entity ID | Type | Tier | Purpose | Default |
|-----------|------|------|---------|---------|
| `input_number.ai_target_sleep_hours` | number | E [config] | Target hours of sleep. Bedtime = wake_time - this value. | 5-10h |
| `input_number.ai_morning_prep_buffer` | number | E [config] | Minutes from waking up to being ready. wake_time = first_event - this value. | 15-90 min |
| `input_text.ai_schedule_day_overrides` | text | E | JSON per-day wake time overrides. Format: `{"thursday":"09:30","sunday":"10:00"}`. | `{}` |
| `input_datetime.ai_predicted_routine_start` | datetime | E [system] | Predicted time the bedtime routine should begin. | — |
| `input_datetime.ai_predicted_wake_time` | datetime | E [system] | Predicted wake time. Used as the dynamic alarm trigger. | — |

---

## 22. Routine Tracker

Fingerprints daily routines and detects deviations.

| Entity ID | Type | Tier | Purpose | Default |
|-----------|------|------|---------|---------|
| `input_boolean.ai_routine_tracking_enabled` | boolean | E | Master kill switch. | ON |

---

## 23. Focus Guard (Anti-ADHD)

Nudges for breaks, meals, and bedtime when you've been in the same zone too long.

| Entity ID | Type | Tier | Purpose | Default |
|-----------|------|------|---------|---------|
| `input_boolean.ai_focus_guard_enabled` | boolean | E | Master kill switch. | ON |
| `input_boolean.ai_focus_mode` | boolean | E [system] | Voice-activated DND. Set by "I need to focus" / "Focus mode on". Auto-expires after max hours. | OFF |
| `input_boolean.ai_focus_time_check_enabled` | boolean | E | Enable time-in-zone nudges. | ON |
| `input_boolean.ai_focus_meal_reminder_enabled` | boolean | E | Enable meal reminder nudges. | ON |
| `input_boolean.ai_focus_meal_ask_eaten` | boolean | E | After meal reminder TTS, open the mic so user can respond. | ON |
| `input_datetime.ai_last_meal_time` | datetime | E [system] | Last meal timestamp. Updated by voice ("I just ate") or pyscript service. | — |
| `input_datetime.ai_focus_guard_snooze_until` | datetime | E [system] | Snooze expiry. Calendar P1 (critical) nudges bypass snooze. | — |
| `input_number.ai_focus_guard_threshold_hours` | number | D | Hours in one zone before first nudge fires. | slider, 1-4h |
| `input_number.ai_focus_mode_max_hours` | number | D | Max hours before focus mode auto-expires. | slider, 0.5-4h |
| `input_number.ai_focus_meal_reminder_hours` | number | D | Hours since last meal before meal reminder fires. | slider, 2-8h |
| `input_number.ai_focus_nudge_cooldown_minutes` | number | D | Minutes between repeated nudges. | slider, 15-120 min |
| `input_number.ai_focus_social_nudge_minutes` | number | D | Minutes before a social interaction nudge. | slider, 15-120 min |
| `input_number.ai_focus_break_suggest_hours` | number | D | Hours before suggesting a break. | slider, 1-4h |
| `input_number.ai_focus_bedtime_approach_minutes` | number | D | Minutes before bedtime to start bedtime-approach nudges. | slider, 30-120 min |

---

## 24. Presence Identity

Per-person room inference using WiFi, GPS, and FP2 presence sensors.

| Entity ID | Type | Tier | Purpose | Default |
|-----------|------|------|---------|---------|
| `input_boolean.ai_presence_identity_enabled` | boolean | E | Master kill switch. | ON |
| `input_boolean.ai_guest_mode` | boolean | E [system] | ON when an unidentified person is detected. | OFF |
| `input_number.ai_presence_identity_transition_window` | number | D | Seconds to wait before committing a room transition. | 120s |
| `input_number.ai_presence_identity_confidence_floor` | number | D | Minimum confidence % to trust an identity assignment. | 20% |
| `input_number.ai_presence_identity_departure_debounce` | number | D | Seconds to wait before confirming a departure. | 60s |
| `input_number.ai_wifi_stale_timeout` | number | D | Minutes before WiFi signal is considered stale. | 20 min |
| `input_number.ai_identity_confidence_min` | number | D | Minimum overall confidence % for identity assertion. | 70% |

**WiFi Scoring Weights (Dev Tuning):**

| Entity ID | Purpose | Default |
|-----------|---------|---------|
| `input_number.ai_wifi_score_primary` | Weight for primary device. | 30 |
| `input_number.ai_wifi_score_secondary` | Weight for secondary device (GPS). | 50 |
| `input_number.ai_wifi_score_tertiary` | Weight for tertiary device. | 15 |
| `input_number.ai_wifi_score_quaternary` | Weight for quaternary device. | 5 |

**Presence Confidence Factors (Dev Tuning):**

| Entity ID | Purpose | Default |
|-----------|---------|---------|
| `input_number.ai_presence_conf_solo` | Confidence when solo at home. | 100 |
| `input_number.ai_presence_conf_voice` | Confidence from voice recognition. | 95 |
| `input_number.ai_presence_conf_departure` | Confidence from departure detection. | 95 |
| `input_number.ai_presence_conf_arrival` | Confidence from arrival detection. | 90 |
| `input_number.ai_presence_conf_count` | Confidence from occupant count. | 85 |
| `input_number.ai_presence_conf_transition` | Confidence during room transition. | 80 |
| `input_number.ai_presence_conf_markov_cap` | Max confidence from Markov chain prediction. | 50 |

**Presence Decay (Dev Tuning):**

| Entity ID | Purpose | Default |
|-----------|---------|---------|
| `input_number.ai_presence_fp2_dwell_sec` | FP2 dwell time before registering presence. | 30s |
| `input_number.ai_presence_decay_start` | Minutes before confidence starts decaying. | 15 min |
| `input_number.ai_presence_decay_cap` | Minutes at which decay reaches maximum. | 60 min |
| `input_number.ai_presence_decay_range` | Width of the decay window. | 45 min |
| `input_number.ai_presence_decay_factor` | Decay multiplier (0-1). | 0.5 |

---

## 25. Presence Patterns

Learns daily presence patterns from historical zone data.

| Entity ID | Type | Tier | Purpose | Default |
|-----------|------|------|---------|---------|
| `input_boolean.ai_presence_patterns_enabled` | boolean | E | Master kill switch. | ON |
| `input_boolean.ai_fp2_zone_workshop_enabled` | boolean | E | Include Workshop zone in presence tracking. | ON |
| `input_boolean.ai_fp2_zone_living_room_enabled` | boolean | E | Include Living Room zone. | ON |
| `input_boolean.ai_fp2_zone_main_room_enabled` | boolean | E | Include Main Room zone. | ON |
| `input_boolean.ai_fp2_zone_kitchen_enabled` | boolean | E | Include Kitchen zone. | ON |
| `input_boolean.ai_fp2_zone_bed_enabled` | boolean | E | Include Bed zone. | ON |
| `input_boolean.ai_fp2_zone_lobby_enabled` | boolean | E | Include Lobby zone. | ON |
| `input_boolean.ai_fp2_zone_bathroom_enabled` | boolean | E | Include Bathroom zone. | ON |
| `input_boolean.ai_fp2_zone_shower_enabled` | boolean | E | Include Shower zone. | ON |
| `input_number.ai_presence_pattern_lookback_days` | number | D | Days of history to analyze. | slider, 7-90 |
| `input_number.ai_presence_pattern_min_samples` | number | D | Minimum data points before patterns are considered valid. | slider, 3-50 |
| `input_number.ai_presence_transition_window` | number | D | Seconds within which a zone change counts as a transition (not a new session). | slider, 60-600s |

---

## 26. Away Patterns

Predicts departure and arrival patterns.

| Entity ID | Type | Tier | Purpose | Default |
|-----------|------|------|---------|---------|
| `input_boolean.ai_away_patterns_enabled` | boolean | E | Master kill switch. | ON |
| `input_number.ai_away_pattern_lookback_days` | number | D | Days of history to analyze. | slider, 7-90 |
| `input_number.ai_away_pattern_min_samples` | number | D | Minimum trips before predicting. | slider, 3-30 |
| `input_number.ai_away_travel_buffer_minutes` | number | D | Buffer added to predicted travel time. | slider, 10-60 min |
| `input_number.ai_away_flap_debounce_seconds` | number | D | Debounce for WiFi flapping (false departure/arrival). | 300s |
| `input_number.ai_away_prediction_update_minutes` | number | D | Interval between prediction recalculations. | 15 min |
| `input_number.ai_away_ordinal_min_samples` | number | D | Min samples for ordinal (nth-trip-of-day) predictions. | 5 |
| `input_number.ai_away_min_entropy_samples` | number | D | Min samples for entropy-based confidence. | 50 |

**Entropy Tiers (Dev Tuning):**

| Entity ID | Purpose | Default |
|-----------|---------|---------|
| `input_number.ai_entropy_tier_low` | Entropy below this = highly predictable behavior. | 1.0 |
| `input_number.ai_entropy_tier_high` | Entropy above this = unpredictable behavior. | 2.0 |

---

## 27. Privacy Gate

Suppresses features per-person based on identity confidence. Prevents acting on wrong-person data.

| Entity ID | Type | Tier | Purpose | Default |
|-----------|------|------|---------|---------|
| `input_boolean.ai_privacy_gate_enabled` | boolean | E | Master kill switch. | ON |
| `input_select.ai_privacy_gate_mode` | select | E | **auto**: confidence-based suppression. **force_suppress_all**: suppress everything. **force_allow_all**: bypass all gates. | `auto` |

Per-user privacy gate helpers are in [Per-User Helpers](#48-per-user-helpers).

---

## 28. Hot Context

Builds the real-time context block injected into all agent system prompts.

| Entity ID | Type | Tier | Purpose | Default |
|-----------|------|------|---------|---------|
| `input_boolean.ai_context_guests_present` | boolean | E | Manual flag: guests are present. Agents adjust tone/privacy. | OFF |
| `input_boolean.ai_work_day_manual_override` | boolean | E | When ON, user's manual work-day toggle overrides auto-detection. | OFF |
| `input_select.ai_context_preferred_language` | select | E [config] | Preferred response language. | `English` |
| `input_select.ai_expertise_routing_mode` | select | E | Expertise-based agent routing. **off**: disabled. **suggest**: agents suggest handing off. **auto**: dispatcher auto-routes by expertise. | `auto` |
| `input_text.ai_work_calendar_keywords` | text | E | Comma-separated calendar event keywords that indicate a work day. | `standup,sprint,meeting,...` |
| `input_datetime.ai_context_bed_time` | datetime | E [config] | Household bedtime target (used by context layer). | — |
| `input_datetime.ai_last_interaction_time` | datetime | E [system] | Last time any user interacted with any agent. | — |

---

## 29. LLM Budget & Cost Control

Tracks API costs across LLM, TTS, STT, and music generation. Enforces daily limits.

| Entity ID | Type | Tier | Purpose | Default |
|-----------|------|------|---------|---------|
| `input_boolean.ai_budget_fallback_active` | boolean | E [system] | ON when daily budget is exceeded. System switches to fallback agent. | OFF |
| `input_number.ai_llm_daily_budget` | number | E | Manual budget scale factor (%). 100 = normal, 50 = half-budget. | slider, 0-200% |
| `input_number.ai_llm_daily_limit` | number | E [config] | Max LLM calls per day. | box |
| `input_number.ai_llm_daily_token_limit` | number | E [config] | Max tokens per day. | box |
| `input_number.ai_tts_daily_limit` | number | E [config] | Max TTS calls per day. | box |
| `input_number.ai_budget_daily_cost_limit` | number | E [config] | Daily cost cap in your currency. | box, EUR |
| `input_number.ai_cost_per_1k_llm_tokens` | number | E | Estimated cost per 1K LLM tokens. | 0.001 EUR |
| `input_number.ai_cost_per_1k_tts_chars` | number | E | Estimated cost per 1K TTS characters. | 0.30 EUR |
| `input_number.ai_cost_per_stt_call` | number | E | Estimated cost per STT call. | 0.02 EUR |
| `input_number.ai_cost_per_music_generation` | number | E | Cost per music API generation. | 0.02 EUR |
| `input_number.ai_elevenlabs_credit_floor` | number | E [config] | Character count below which TTS swaps to HA Cloud (free). | 5000 chars |
| `input_number.ai_elevenlabs_credit_cap` | number | E | Credit cap override (0 = use API value). | 0 |
| `input_number.ai_elevenlabs_monthly_cost` | number | E | Your ElevenLabs monthly subscription cost in USD. | $22 |
| `input_number.ai_serper_plan_cost` | number | E | Your Serper plan cost in USD. | $50 |
| `input_number.ai_serper_plan_credits` | number | E | Credits in your Serper plan. | 50000 |
| `input_number.ai_budget_rolling_months` | number | E | Months of rolling cost history to display. | box, 1-24 |
| `input_text.ai_budget_fallback_agent` | text | E [config] | Conversation agent entity to use when budget exceeded. | `homeassistant` |
| `input_select.ai_budget_cost_source` | select | E | Which cost figure the budget gate uses. **estimated**: formula-based. **actual**: OpenRouter API. **hybrid**: MAX of both. | `hybrid` |
| `input_select.ai_budget_metric` | select | E | Dashboard display preference (all limits enforced regardless). | — |
| `input_select.ai_budget_currency` | select | E [config] | Currency display symbol. Does NOT convert values. | `EUR` |
| `input_select.ai_budget_view_level` | select | E | Per-agent budget breakdown view level. | — |
| `input_datetime.ai_budget_last_reset` | datetime | E [system] | Last date the daily reset ran. Detects missed midnight resets. | — |
| `input_button.ai_budget_manual_reset` | button | E | Dashboard button: manually reset daily budget counters. | — |
| `input_button.ai_budget_refresh_pricing` | button | E | Dashboard button: refresh OpenRouter pricing cache. | — |
| `input_number.ai_budget_personality_threshold` | number | D | Budget % below which personality features (banter, escalation) are disabled. | 30% |
| `input_number.ai_budget_threshold_low` | number | D | Low budget threshold %. | 30% |
| `input_number.ai_budget_threshold_high` | number | D | High budget threshold %. | 60% |

---

## 30. Calendar Promotion

Syncs calendar events and injects them into agent context.

| Entity ID | Type | Tier | Purpose | Default |
|-----------|------|------|---------|---------|
| `input_boolean.ai_calendar_promotion_enabled` | boolean | E | Master kill switch. | ON |
| `input_number.ai_calendar_promote_ttl` | number | D | Cache TTL for calendar data in seconds. | 300s |
| `input_number.ai_calendar_failure_threshold` | number | D | Consecutive API failures before notifying. | 3 |
| `input_number.ai_calendar_default_event_duration` | number | D | Default event duration when not specified. | 60 min |

---

## 31. Memory & Embedding

SQLite-backed memory system with vector search. Handles embedding, archiving, and relationship graphs.

| Entity ID | Type | Tier | Purpose | Default |
|-----------|------|------|---------|---------|
| `input_boolean.ai_memory_auto_archive` | boolean | E | Auto-archive old memory entries. | ON |
| `input_boolean.ai_memory_search_enrich` | boolean | E | Append graph-connected entries to search results. | ON |
| `input_boolean.ai_memory_semantic_autolink` | boolean | E | Nightly creation of content similarity edges. OFF by default (has embedding cost). | **OFF** |
| `input_boolean.ai_embedding_batch_kill_switch` | boolean | E | Kill switch for batch embedding jobs. | ON |
| `input_boolean.ai_sqlite_vec_recompile_i_2a_kill_switch` | boolean | E | Kill switch for sqlite-vec recompilation. | ON |
| `input_boolean.ai_memory_to_do_list_mirror_kill_switch` | boolean | E | Kill switch for memory-to-todo list mirroring. | ON |
| `input_text.ai_embedding_api_url` | text | E [config] | Embedding API endpoint. | `https://openrouter.ai/api/v1` |
| `input_text.ai_embedding_api_key` | text | E [config] | API key (password mode). | — |
| `input_text.ai_embedding_model` | text | E [config] | Embedding model name. | `text-embedding-3-small` |
| `input_text.ai_task_instance` | text | E [config] | ha_text_ai sensor entity for LLM task calls. | `sensor.ha_text_ai_deepseek_chat` |
| `input_text.ai_memory_archive_protection_tags` | text | E | Space-separated tags that protect entries from archiving. | `important remember pinned permanent` |
| `input_text.ai_memory_search_query` | text | E | Dashboard search field. | — |
| `input_text.ai_memory_archive_search_query` | text | E | Dashboard archive search field. | — |
| `input_text.ai_memory_edit_key` | text | E | Dashboard memory editor: key field. | — |
| `input_text.ai_memory_edit_value` | text | E | Dashboard memory editor: value field. | — |
| `input_text.ai_memory_edit_tags` | text | E | Dashboard memory editor: tags field. | — |
| `input_text.ai_memory_edit_scope` | text | E | Dashboard memory editor: scope field. | `household` |
| `input_datetime.ai_embedding_batch_time` | datetime | E | Nightly batch embedding schedule (time-only). | — |
| `input_datetime.ai_summarizer_batch_time` | datetime | E | Nightly summarizer schedule. | — |
| `input_datetime.ai_conversation_summarizer_batch_time` | datetime | E | Conversation summarizer schedule. | — |
| `input_datetime.ai_interaction_summarizer_batch_time` | datetime | E | Interaction summarizer schedule. | — |
| `input_boolean.ai_interaction_summarizer_kill_switch` | boolean | E | Kill switch for interaction summarizer. | ON |
| `input_number.ai_embedding_dimensions` | number | D | Vector embedding dimensions. | 512 |
| `input_number.ai_embedding_batch_size` | number | D | Entries per embedding batch. | 50 |
| `input_number.ai_semantic_search_results` | number | D | Max vector search results. | 5 |
| `input_number.ai_semantic_similarity_threshold` | number | D | Minimum cosine similarity to include in results. | 0.7 |
| `input_number.ai_semantic_blend_weight` | number | D | Weight of semantic vs keyword search (%). | 50% |
| `input_number.ai_memory_record_limit` | number | D | Max total memory records. | 5000 |
| `input_number.ai_memory_db_max_mb` | number | D | Max database file size in MB. | 100 MB |
| `input_number.ai_memory_archive_target_pct` | number | D | Target % of record limit before archiving kicks in. | 80% |
| `input_number.ai_memory_archive_recency_days` | number | D | Days of recency protection (entries newer than this won't archive). | 30 days |
| `input_number.ai_memory_search_enrich_max` | number | D | Max graph-connected entries to append. | 3 |
| `input_number.ai_memory_search_enrich_min_weight` | number | D | Minimum relationship weight to include. | 0.15 |
| `input_number.ai_memory_semantic_autolink_threshold` | number | D | Cosine similarity threshold for creating autolink edges. | 0.7 |
| `input_number.ai_memory_semantic_autolink_batch` | number | D | Entries per autolink batch. | 50 |
| `input_number.ai_conversation_history_retention_days` | number | D | Days to retain conversation history. | 7 |

---

## 32. Media Tracking

Tracks Radarr/Sonarr upcoming releases and recent downloads.

| Entity ID | Type | Tier | Purpose | Default |
|-----------|------|------|---------|---------|
| `input_boolean.ai_media_tracking_enabled` | boolean | E | Master kill switch. | ON |
| `input_number.ai_music_dedup_cooldown` | number | D | Seconds between duplicate music play reports. | 180s |
| `input_number.ai_music_play_expiry_days` | number | D | Days before play history records expire. | 365 |
| `input_number.ai_music_top_limit` | number | D | Max artists in "top artists" list. | 15 |

---

## 33. Music Composer

AI-powered music generation with caching.

| Entity ID | Type | Tier | Purpose | Default |
|-----------|------|------|---------|---------|
| `input_boolean.ai_music_composer_enabled` | boolean | E | Master kill switch. | ON |
| `input_number.ai_music_daily_generation_limit` | number | E | Max API generations per day (cost control). | 10 |
| `input_number.ai_music_cache_size_mb` | number | E | Max music cache in MB. | 200 MB |
| `input_button.ai_music_compose_batch` | button | E | Trigger batch music generation from dashboard. | — |

---

## 34. Music Taste

Extracts listening preferences from play history.

| Entity ID | Type | Tier | Purpose | Default |
|-----------|------|------|---------|---------|
| `input_boolean.ai_music_taste_enabled` | boolean | E | Master kill switch. | ON |
| `input_button.ai_music_taste_rebuild` | button | E | Manually rebuild taste profile. | — |

---

## 35. Music Follow-Me

Moves music playback to follow you between rooms.

| Entity ID | Type | Tier | Purpose | Default |
|-----------|------|------|---------|---------|
| `input_boolean.ai_music_follow_me` | boolean | E | Master kill switch. | ON |
| `input_datetime.ai_music_follow_me_last_move` | datetime | E [system] | Last time music was moved between speakers. | — |

---

## 36. Auto-Off / Auto-On

Automatically turn off/on lights and media based on presence.

| Entity ID | Type | Tier | Purpose | Default |
|-----------|------|------|---------|---------|
| `input_boolean.ai_auto_off_enabled` | boolean | E | Master Auto-Off kill switch. | ON |
| `input_boolean.ai_auto_off_lights_enabled` | boolean | E | Auto-off for lights specifically. | ON |
| `input_boolean.ai_auto_off_media_enabled` | boolean | E | Auto-off for media specifically. | ON |
| `input_boolean.ai_auto_on_workshop` | boolean | E | Auto-on lights in Workshop on presence. | ON |
| `input_boolean.ai_auto_on_living_room` | boolean | E | Auto-on lights in Living Room on presence. | ON |

---

## 37. Scene Learner & Circadian

Learns lighting preferences and applies circadian rhythms.

| Entity ID | Type | Tier | Purpose | Default |
|-----------|------|------|---------|---------|
| `input_boolean.ai_scene_learner_enabled` | boolean | E | Master kill switch for scene preference learning. | ON |
| `input_boolean.ai_circadian_workshop_enabled` | boolean | E | Circadian lighting for Workshop. | ON |
| `input_boolean.ai_circadian_living_room_enabled` | boolean | E | Circadian lighting for Living Room. | ON |
| `input_boolean.ai_pre_light_enabled` | boolean | E | Pre-light zones before arrival. | ON |
| `input_boolean.ai_ambient_music_enabled` | boolean | E | Ambient music autoplay. | **OFF** |
| `input_number.ai_scene_learner_min_observations` | number | D | Minimum observations before learning a scene preference. | 5 |

---

## 38. Project Tracking

Tracks project status from external project management tools.

| Entity ID | Type | Tier | Purpose | Default |
|-----------|------|------|---------|---------|
| `input_boolean.ai_project_tracking_enabled` | boolean | E | Master kill switch. | ON |
| `input_number.ai_project_hot_context_limit` | number | D | Max active projects to inject into hot context. | 5 |

---

## 39. Entity History

Allows agents to query HA entity history.

| Entity ID | Type | Tier | Purpose | Default |
|-----------|------|------|---------|---------|
| `input_boolean.ai_entity_history_enabled` | boolean | E | Master kill switch. | ON |

---

## 40. Contact History

Tracks and summarizes communication history.

| Entity ID | Type | Tier | Purpose | Default |
|-----------|------|------|---------|---------|
| `input_boolean.ai_contact_history_enabled` | boolean | E | Master kill switch. | ON |
| `input_boolean.ai_contact_history_summarizer_kill_switch` | boolean | E | Kill switch for periodic summarization. | ON |

---

## 41. Entropy Correlation

Correlates entropy patterns across different data sources.

| Entity ID | Type | Tier | Purpose | Default |
|-----------|------|------|---------|---------|
| `input_boolean.ai_entropy_correlation_enabled` | boolean | E | Master kill switch. | ON |

---

## 42. Conversation Sensor

Tracks conversation metrics (frequency, duration, topics).

| Entity ID | Type | Tier | Purpose | Default |
|-----------|------|------|---------|---------|
| `input_boolean.ai_conversation_sensor_enabled` | boolean | E | Master kill switch. | ON |

---

## 43. Phone Call Detection

Defers TTS announcements during phone calls.

| Entity ID | Type | Tier | Purpose | Default |
|-----------|------|------|---------|---------|
| `input_boolean.ai_phone_call_defer_tts` | boolean | E | When ON, TTS is deferred while a phone call is active. | ON |

---

## 44. Alexa Integration

Controls Alexa-specific briefing and email features.

| Entity ID | Type | Tier | Purpose | Default |
|-----------|------|------|---------|---------|
| `input_boolean.ai_alexa_briefing` | boolean | E | Enable/disable Alexa briefing announcements. | ON |
| `input_boolean.ai_alexa_mail_status` | boolean | E | Enable/disable Alexa email status announcements. | ON |

---

## 45. Test Harness

Testing and simulation controls. **All OFF by default. Never enable accidentally in production.**

| Entity ID | Type | Tier | Purpose | Default |
|-----------|------|------|---------|---------|
| `input_boolean.ai_test_mode` | boolean | E | Global test flag. Blueprints use mock data, TTS goes to log-only sink, identity overrides activate. | **OFF** |
| `input_boolean.ai_tts_test_mode` | boolean | E | TTS test session: runs full pipeline but swaps ElevenLabs for free HA Cloud TTS. | **OFF** |
| `input_text.ai_test_identity` | text | E | Identity override (any person slug, `guest`, or empty). Only active when test_mode ON. | — |
| `input_text.ai_test_routine_stage` | text | E | Routine stage override (`morning`, `bedtime`, `work`, `evening`, or empty). Only active when test_mode ON. | — |
| `input_text.ai_test_calendar_event` | text | E | Mock calendar event. Formats: `"Team standup at 09:00"`, `"09:00"`, or JSON `{"summary":"Standup","hour":9,"minute":0}`. Only active when test_mode ON. | — |

---

## 46. System Recovery

Auto-recovers from common failures (integration reloads, service restarts).

| Entity ID | Type | Tier | Purpose | Default |
|-----------|------|------|---------|---------|
| `input_boolean.ai_system_recovery_enabled` | boolean | E | Master kill switch. | ON |
| `input_number.ai_recovery_max_retries_per_hour` | number | D | Max recovery attempts per hour. | 3 |
| `input_number.ai_recovery_base_backoff_seconds` | number | D | Base backoff delay between retries. | 60s |

---

## 47. Toggle Audit

Logs all helper toggle changes for debugging.

| Entity ID | Type | Tier | Purpose | Default |
|-----------|------|------|---------|---------|
| `input_boolean.ai_toggle_audit_enabled` | boolean | E | Master kill switch. | ON |
| `input_number.ai_toggle_audit_retention_days` | number | D | Days to keep audit logs. | 90 |

---

## 48. Per-User Helpers

Defined in `packages/ai_per_user_helpers.yaml`. Clone each block per household member, replacing the `_{person}` suffix with your HA person slug.

### Per-User Profile (input_text)

| Pattern | Purpose |
|---------|---------|
| `ai_context_user_name_{person}` | Display name |
| `ai_context_user_name_spoken_{person}` | TTS pronunciation |
| `ai_context_user_languages_{person}` | Languages spoken |
| `ai_context_user_verbosity_{person}` | Verbosity preference (populated by interview) |
| `ai_context_user_humor_{person}` | Humor preference |
| `ai_context_user_language_context_{person}` | Language context notes |
| `ai_context_user_persona_{person}` | Preferred AI persona |
| `ai_context_user_notify_threshold_{person}` | Notification threshold preference |
| `ai_context_user_social_style_{person}` | Social interaction style |
| `ai_context_user_morning_or_night_{person}` | Morning/night person |
| `ai_context_user_values_{person}` | Personal values |
| `ai_context_user_pet_peeves_{person}` | Things that annoy them |
| `ai_context_user_stress_relief_{person}` | Stress relief activities |
| `ai_context_user_off_limits_{person}` | Topics the AI should avoid |
| `ai_context_user_proactive_comfort_{person}` | Proactive comfort preferences |
| `ai_context_user_wake_schedule_{person}` | Wake schedule description |
| `ai_context_wake_time_alt_days_{person}` | Alt-weekday day names (e.g., `tuesday,thursday`) |

### Per-User Schedule (input_datetime)

| Pattern | Purpose |
|---------|---------|
| `ai_context_wake_time_weekday_{person}` | Weekday wake time |
| `ai_context_wake_time_weekend_{person}` | Weekend wake time |
| `ai_context_bed_time_{person}` | Target bedtime |
| `ai_context_wake_time_alt_weekday_{person}` | Alt-weekday wake time |
| `ai_away_departed_{person}` | [system] Last departure timestamp |
| `ai_home_since_{person}` | [system] Last arrival timestamp |

### Per-User Calendar (input_text)

| Pattern | Purpose |
|---------|---------|
| `ai_calendar_today_summary_{person}` | [system] Today's calendar summary |
| `ai_calendar_tomorrow_summary_{person}` | [system] Tomorrow's calendar summary |

### Per-User Flags (input_boolean)

| Pattern | Purpose |
|---------|---------|
| `ai_context_work_day_{person}` | Is it a work day for this person? |
| `ai_wifi_stale_{person}` | [system] WiFi signal is stale for this person |
| `ai_privacy_gate_{person}_t1_suppressed` | [system] Privacy tier 1 active |
| `ai_privacy_gate_{person}_t2_suppressed` | [system] Privacy tier 2 active |
| `ai_privacy_gate_{person}_t3_suppressed` | [system] Privacy tier 3 active |

### Per-User Privacy Thresholds (input_number)

Privacy gate thresholds control when features are suppressed for a person. Each tier has a suppress-at and re-enable-at value (hysteresis).

| Pattern | Purpose | Default |
|---------|---------|---------|
| `ai_privacy_gate_{person}_t1_suppress_at` | Confidence above which T1 features suppress | 30 pts |
| `ai_privacy_gate_{person}_t1_reenable_at` | Confidence below which T1 features re-enable | 20 pts |
| `ai_privacy_gate_{person}_t2_suppress_at` | T2 suppress threshold | 40 pts |
| `ai_privacy_gate_{person}_t2_reenable_at` | T2 re-enable threshold | 30 pts |
| `ai_privacy_gate_{person}_t3_suppress_at` | T3 suppress threshold | 50 pts |
| `ai_privacy_gate_{person}_t3_reenable_at` | T3 re-enable threshold | 40 pts |

**Privacy Tiers:**
- **T1** (lowest): Personal announcements (bedtime, wake-up, calendar)
- **T2** (medium): Email, notification routing
- **T3** (highest): Automation triggers (auto-off, scene learning)

Higher suppress-at = more confidence needed before suppressing. The gap between suppress and re-enable prevents flapping.

### Per-User Preference (input_select)

| Pattern | Purpose |
|---------|---------|
| `ai_context_preferred_language_{person}` | Preferred response language |

### Per-User Counters

| Pattern | Purpose |
|---------|---------|
| `counter.ai_away_trip_count_{person}` | [system] Tracks nth trip of the day for away pattern prediction |

---

## Weather

| Entity ID | Type | Tier | Purpose | Default |
|-----------|------|------|---------|---------|
| `input_button.ai_weather_forecast_rebuild` | button | E | Manually rebuild tomorrow's weather forecast. | — |

