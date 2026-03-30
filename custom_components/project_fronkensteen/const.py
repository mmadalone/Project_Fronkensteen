"""Constants for Project Fronkensteen installer."""

DOMAIN = "project_fronkensteen"
VERSION = "1.0.0"

# ── Feature Groups ──────────────────────────────────────────────────────────
# Each group maps to a set of files. Core is always installed.
# Users select which optional groups to install via the config flow.

FEATURE_GROUPS = {
    "voice": "Voice Pipeline",
    "bedtime": "Bedtime & Sleep",
    "notifications": "Notifications & Email",
    "music": "Music & Media",
    "budget": "Budget & Cost Tracking",
    "presence": "Presence & Identity",
    "memory": "Memory & Embedding",
    "creative": "Creative & Social",
}

# ── Install Targets ─────────────────────────────────────────────────────────
# Maps bundle subdirectory → destination under /config/

# Maps bundle subdirectory → destination path under /config/
# Used by installer.py for all file operations.
BUNDLE_TO_DEST = {
    "pyscript": "pyscript",
    "pyscript_templates": "pyscript",
    "packages": "packages",
    "blueprints_automation": "blueprints/automation/madalone",
    "blueprints_script": "blueprints/script/madalone",
    "helpers": "",  # config root
    "scripts": "scripts",
    "elevenlabs_custom_tts": "custom_components/elevenlabs_custom_tts",
    "extended_openai_conversation": "custom_components/extended_openai_conversation",
}

# Subdirectories that contain code files (always overwritten on update)
CODE_SUBDIRS = {
    "pyscript", "packages",
    "blueprints_automation", "blueprints_script",
    "elevenlabs_custom_tts", "extended_openai_conversation",
}

# Subdirectories that are never overwritten on update
SKIP_ON_UPDATE_SUBDIRS = {"pyscript_templates", "scripts"}

# ── File Manifests ──────────────────────────────────────────────────────────
# Every distributable file, mapped to its feature group.
# "core" files are always installed regardless of feature selection.

PYSCRIPT_FILES = {
    # Core (always installed)
    "common_utilities.py": "core",
    "entity_history.py": "core",
    "memory.py": "core",
    "satellite_idle_reset.py": "core",
    "state_bridge.py": "core",
    "system_health.py": "core",
    "system_recovery.py": "core",
    "toggle_audit.py": "core",
    "tts_queue.py": "core",
    "voice_session.py": "core",
    # Voice Pipeline
    "agent_dispatcher.py": "voice",
    "agent_whisper.py": "voice",
    "duck_manager.py": "voice",
    "voice_handoff.py": "voice",
    # Bedtime & Sleep
    "predictive_schedule.py": "bedtime",
    "routine_fingerprint.py": "bedtime",
    "scene_learner.py": "bedtime",
    "sleep_config.py": "bedtime",
    # Notifications
    "contact_history.py": "notifications",
    "email_promote.py": "notifications",
    "notification_dedup.py": "notifications",
    # Music & Media
    "media_promote.py": "music",
    "music_composer.py": "music",
    "music_taste.py": "music",
    # Presence & Identity
    "away_patterns.py": "presence",
    "entropy_correlator.py": "presence",
    "presence_identity.py": "presence",
    "presence_patterns.py": "presence",
    # Creative & Social
    "conversation_sensor.py": "creative",
    "focus_guard.py": "creative",
    "proactive_briefing.py": "creative",
    "project_promote.py": "creative",
    "theatrical_mode.py": "creative",
    "therapy_session.py": "creative",
    "user_interview.py": "creative",
    # Calendar (bundled with notifications since briefing uses it)
    "calendar_promote.py": "notifications",
    # shared_utils lives in pyscript/modules/ — same bundle subdir
    "modules/shared_utils.py": "core",
}


PACKAGE_FILES = {
    # Core
    "ai_auto_off.yaml": "core",
    "ai_context_hot.yaml": "core",
    "ai_conversation_sensor.yaml": "core",
    "ai_dev_helpers.yaml": "core",
    "ai_dispatcher.yaml": "core",
    "ai_duck_manager.yaml": "core",
    "ai_focus_guard.yaml": "core",
    "ai_identity.yaml": "core",
    "ai_per_user_helpers.yaml": "core",
    "ai_phone_call_detection.yaml": "core",
    "ai_self_awareness.yaml": "core",
    "ai_system_health.yaml": "core",
    "ai_system_recovery.yaml": "core",
    "ai_test_harness.yaml": "core",
    "ai_toggle_audit.yaml": "core",
    # Voice Pipeline
    "ai_tts_queue.yaml": "voice",
    "ai_whisper.yaml": "voice",
    # Bedtime & Sleep
    "ai_predictive_schedule.yaml": "bedtime",
    "ai_routine_tracker.yaml": "bedtime",
    "ai_scene_learner.yaml": "bedtime",
    "ai_sleep_detection.yaml": "bedtime",
    # Notifications
    "ai_calendar_promotion.yaml": "notifications",
    "ai_email_promotion.yaml": "notifications",
    "ai_notification_dedup.yaml": "notifications",
    # Music & Media
    "ai_media_tracking.yaml": "music",
    "ai_music_composer.yaml": "music",
    "ai_music_taste.yaml": "music",
    # Budget
    "ai_llm_budget.yaml": "budget",
    # Presence & Identity
    "ai_away_patterns.yaml": "presence",
    "ai_presence_identity.yaml": "presence",
    "ai_presence_patterns.yaml": "presence",
    "ai_privacy_gate.yaml": "presence",
    "ai_privacy_gate_helpers.yaml": "presence",
    # Memory & Embedding
    "ai_embedding.yaml": "memory",
    "ai_history_context.yaml": "memory",
    # Creative & Social
    "ai_escalation.yaml": "creative",
    "ai_proactive_briefing.yaml": "creative",
    "ai_project_tracking.yaml": "creative",
    "ai_theatrical.yaml": "creative",
    "ai_therapy.yaml": "creative",
    "ai_user_interview.yaml": "creative",
    "ai_weather_forecast.yaml": "creative",
}

BLUEPRINT_AUTOMATION_FILES = {
    # Core
    "automation_trigger_mon.yaml": "core",
    "calendar_alarm.yaml": "core",
    "calendar_pre_event_reminder.yaml": "core",
    "circadian_lighting.yaml": "core",
    "coming_home.yaml": "core",
    "device_power_cycle.yaml": "core",
    "dispatcher_profile.yaml": "core",
    "follow_me_refcount_watchdog.yaml": "core",
    "llm_alarm.yaml": "core",
    "mass_llm_enhanced_assist_blueprint_en.yaml": "core",
    "meal_detection.yaml": "core",
    "phone_charge_reminder.yaml": "core",
    "project_sync.yaml": "core",
    "scene_preference_apply.yaml": "core",
    "smart-bathroom.yaml": "core",
    "speaker_volume_sync.yaml": "core",
    "sqlite_vec_recompile.yaml": "core",
    "system_recovery_alert.yaml": "core",
    "temp_hub.yaml": "core",
    "ups_notify.yaml": "core",
    "va_confirmation_dialog.yaml": "core",
    # Voice Pipeline
    "satellite_tracker.yaml": "voice",
    "voice_active_media_controls.yaml": "voice",
    "voice_handoff.yaml": "voice",
    "voice_mood_modulation.yaml": "voice",
    "voice_pe_resume_media.yaml": "voice",
    "voice_session_mic.yaml": "voice",
    # Bedtime & Sleep
    "bedtime_advisory_actions.yaml": "bedtime",
    "bedtime_last_call.yaml": "bedtime",
    "bedtime_routine.yaml": "bedtime",
    "bedtime_routine_plus.yaml": "bedtime",
    "bedtime_winddown.yaml": "bedtime",
    "escalating_wakeup_guard.yaml": "bedtime",
    "proactive_bedtime_escalation.yaml": "bedtime",
    "routine_deviation_actions.yaml": "bedtime",
    "routine_stage_actions.yaml": "bedtime",
    "sleep_detection.yaml": "bedtime",
    "sleep_lights.yaml": "bedtime",
    "wake-up-guard.yaml": "bedtime",
    "wake_up_guard_external_alarm.yaml": "bedtime",
    "wakeup_guard_mobile_notify.yaml": "bedtime",
    # Notifications
    "contact_history_summarizer.yaml": "notifications",
    "email_follow_me.yaml": "notifications",
    "email_priority_filter.yaml": "notifications",
    "interaction_summarizer.yaml": "notifications",
    "notification_follow_me.yaml": "notifications",
    # Music & Media
    "alexa_on_demand_briefing.yaml": "music",
    "alexa_presence_radio.yaml": "music",
    "alexa_presence_radio_stop.yaml": "music",
    "ambient_music_autoplay.yaml": "music",
    "media_tracking.yaml": "music",
    "music_assistant_follow_me_idle_off.yaml": "music",
    "music_assistant_follow_me_multi_room_advanced.yaml": "music",
    "music_compose_batch_trigger.yaml": "music",
    "music_taste_rebuild.yaml": "music",
    "music_weekly_refresh.yaml": "music",
    # Budget
    "budget_cost_alert.yaml": "budget",
    "budget_fallback.yaml": "budget",
    # Presence & Identity
    "away_state_actions.yaml": "presence",
    "privacy_gate_hysteresis.yaml": "presence",
    "zone_preactivation.yaml": "presence",
    "zone_presence.yaml": "presence",
    "zone_vacancy.yaml": "presence",
    # Memory & Embedding
    "embedding_batch.yaml": "memory",
    "entropy_correlation_report.yaml": "memory",
    "memory_auto_archive.yaml": "memory",
    "memory_threshold_alert.yaml": "memory",
    "memory_todo_mirror.yaml": "memory",
    # Creative & Social
    "agent_escalation.yaml": "creative",
    "conversation_summarizer.yaml": "creative",
    "proactive_briefing.yaml": "creative",
    "proactive_unified.yaml": "creative",
    "reactive_banter.yaml": "creative",
    "theatrical_mode.yaml": "creative",
    "therapy_session.yaml": "creative",
    "user_interview.yaml": "creative",
    "weather_forecast_promote.yaml": "creative",
}

BLUEPRINT_SCRIPT_FILES = {
    # Core
    "agent_randomizer.yaml": "core",
    "device_power_cycle_script.yaml": "core",
    "media_play_at_volume.yaml": "core",
    "mobile_action_toggle.yaml": "core",
    "notification_replay.yaml": "core",
    "refcount_bypass_claim.yaml": "core",
    "refcount_bypass_release.yaml": "core",
    "rickyellsplusalexa.yaml": "core",
    # Voice Pipeline
    "llm_voice_script.yaml": "voice",
    "voice_calendar_event.yaml": "voice",
    "voice_compose_music.yaml": "voice",
    "voice_confirm_device_toggle.yaml": "voice",
    "voice_kodi_play_content.yaml": "voice",
    "voice_media_pause.yaml": "voice",
    "voice_pin_action.yaml": "voice",
    "voice_shut_up.yaml": "voice",
    "voice_stop_radio.yaml": "voice",
    "voice_wake_guard_cleanup.yaml": "voice",
    "voice_wake_guard_tts_router.yaml": "voice",
    # Bedtime & Sleep
    "bedtime_instant.yaml": "bedtime",
    "bedtime_media_play_wrapper.yaml": "bedtime",
    "bedtime_routine_core.yaml": "bedtime",
    "goodnight_negotiator_hybrid.yaml": "bedtime",
    "goodnight_negotiator_llm_driven.yaml": "bedtime",
    "goodnight_routine_music_assistant.yaml": "bedtime",
    "voice_play_bedtime_audiobook.yaml": "bedtime",
    "voice_set_bedtime_countdown.yaml": "bedtime",
    "wakeup_chime.yaml": "bedtime",
    "wakeup_music_alexa.yaml": "bedtime",
    "wakeup_music_ma.yaml": "bedtime",
    # Notifications
    "announce_music_follow_me.yaml": "notifications",
    "announce_music_follow_me_llm.yaml": "notifications",
    # Music & Media
    "music_compose_approve.yaml": "music",
    # Memory
    "voice_memory_semantic_search.yaml": "memory",
}

HELPER_FILES = [
    "helpers_input_boolean.yaml",
    "helpers_input_text.yaml",
    "helpers_input_number.yaml",
    "helpers_input_select.yaml",
    "helpers_input_datetime.yaml",
    "helpers_input_button.yaml",
    "helpers_counter.yaml",
]

CONFIG_TEMPLATES = [
    "entity_config.yaml.template",
    "tts_speaker_config.json.template",
    "voice_mood_profile_map.json.template",
]

SCRIPT_FILES = [
    "recompile_vec0.sh",
]

# Patched ElevenLabs Custom TTS — voice mood modulation fork.
# Installed as a separate custom_component by the installer when
# the Voice Pipeline feature group is enabled. HACS auto-updates
# must be disabled for this component (it's a patched fork).
# manifest.json is stored as manifest.json.bundle in the bundle to prevent
# HACS from scanning it as a second integration. The installer renames it
# back to manifest.json when copying to the target directory.
ELEVENLABS_TTS_FILES = [
    "__init__.py",
    "config_flow.py",
    "const.py",
    "manifest.json.bundle",
    "services.yaml",
    "strings.json",
    "tts.py",
]

ELEVENLABS_RENAME = {"manifest.json.bundle": "manifest.json"}

# Patched Extended OpenAI Conversation — tool-call speech sanitizer.
# Installed as a separate custom_component by the installer. HACS
# auto-updates must be disabled for this component (it's a patched fork).
EOC_FILES = [
    "__init__.py",
    "config_flow.py",
    "const.py",
    "conversation.py",
    "exceptions.py",
    "helpers.py",
    "manifest.json.bundle",
    "services.py",
    "services.yaml",
    "strings.json",
]

EOC_RENAME = {"manifest.json.bundle": "manifest.json"}

# Combined rename map for all patched components
COMPONENT_RENAMES = {**ELEVENLABS_RENAME, **EOC_RENAME}


def get_files_for_groups(selected_groups: list[str]) -> dict[str, list[str]]:
    """Return files to install for the selected feature groups.

    Always includes 'core' files. Returns a dict mapping
    bundle subdirectory → list of filenames.
    """
    active = {"core"} | set(selected_groups)

    result = {
        "pyscript": [f for f, g in PYSCRIPT_FILES.items() if g in active],
        "packages": [f for f, g in PACKAGE_FILES.items() if g in active],
        "blueprints_automation": [
            f for f, g in BLUEPRINT_AUTOMATION_FILES.items() if g in active
        ],
        "blueprints_script": [
            f for f, g in BLUEPRINT_SCRIPT_FILES.items() if g in active
        ],
        "helpers": HELPER_FILES,  # Always all helpers
        "pyscript_templates": CONFIG_TEMPLATES,  # Always all templates
        "scripts": SCRIPT_FILES,  # Always all scripts
    }

    # Patched ElevenLabs TTS — installed with Voice Pipeline
    if "voice" in active:
        result["elevenlabs_custom_tts"] = ELEVENLABS_TTS_FILES

    # Patched Extended OpenAI Conversation — always installed (core dependency)
    result["extended_openai_conversation"] = EOC_FILES

    return result
