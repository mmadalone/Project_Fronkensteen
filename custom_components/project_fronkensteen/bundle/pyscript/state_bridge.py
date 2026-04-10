"""
State Bridge — generic bridge for blueprints to write state.set() sensors.

Blueprints cannot call state.set() directly.  This module exposes a thin
pyscript service (pyscript.set_sensor_value) that any blueprint or automation
can call to create/update a pyscript-managed sensor.

Usage from a blueprint action:
    - action: pyscript.set_sensor_value
      data:
        entity_id: sensor.ai_my_thing
        value: "hello"
        attrs_json: '{"detail": "world"}'
        icon: mdi:brain
        friendly_name: AI My Thing
"""

import json as _json  # noqa: F811 — shadow-safe alias
from datetime import datetime  # noqa: F811 — for budget state timestamps


# ── Budget State File I/O ─────────────────────────────────────────────────────
# JSON-based persistence for budget counters + midnight snapshots.
# @pyscript_executor for file I/O (AP-55 sandbox restriction).

@pyscript_executor  # noqa: F821
def _read_budget_state():
    """Read budget_state.json — native Python, file I/O allowed."""
    import json as _json
    try:
        with open("/config/pyscript/budget_state.json", "r") as f:
            return _json.load(f)
    except (FileNotFoundError, ValueError, OSError):
        return None


@pyscript_executor  # noqa: F821
def _write_budget_state(data_json):
    """Write budget_state.json atomically — native Python."""
    import os as _os
    tmp = "/config/pyscript/budget_state.json.tmp"
    with open(tmp, "w") as f:
        f.write(data_json)
    _os.replace(tmp, "/config/pyscript/budget_state.json")


# ── Budget Entity Lists ───────────────────────────────────────────────────────

_BUDGET_COUNTER_ENTITIES = [
    "sensor.ai_llm_calls_today",
    "sensor.ai_llm_tokens_today",
    "sensor.ai_tts_chars_today",
    "sensor.ai_stt_calls_today",
    "sensor.ai_model_cost_today",
    "sensor.ai_music_generations_today",
]

_BUDGET_SNAPSHOT_ENTITIES = [
    "sensor.ai_openrouter_usage_midnight",
    "sensor.ai_elevenlabs_chars_midnight",
    "sensor.ai_serper_credits_midnight",
]


# ── Startup Initialization ───────────────────────────────────────────────────
# state.set() sensors don't persist across restarts. Seed all migrated sensors
# with default values so dashboard cards don't show "Entity not found".

_STARTUP_SENSORS = [
    # Session 2 — text sensors (populated by promoters on startup)
    ("sensor.ai_calendar_last_sync", "", "mdi:calendar-clock", "AI Calendar Last Sync"),
    ("sensor.ai_calendar_today_summary", "", "mdi:calendar-today", "AI Calendar Today Summary"),
    ("sensor.ai_calendar_tomorrow_summary", "", "mdi:calendar-arrow-right", "AI Calendar Tomorrow Summary"),
    ("sensor.ai_project_last_sync", "", "mdi:clock-check", "AI Project Last Sync"),
    ("sensor.ai_active_projects_summary", "", "mdi:folder-star", "AI Active Projects Summary"),
    ("sensor.ai_project_hot_context_line", "", "mdi:fire", "AI Project Hot Context Line"),
    ("sensor.ai_weather_tomorrow_summary", "", "mdi:weather-partly-snowy-rainy", "AI Weather Tomorrow Summary"),
    ("sensor.ai_away_prediction_accuracy", "", "mdi:target", "AI Away Prediction Accuracy"),
    # Session 3 — budget counters
    ("sensor.ai_llm_calls_today", "0", "mdi:counter", "AI LLM Calls Today"),
    ("sensor.ai_llm_tokens_today", "0", "mdi:counter", "AI LLM Tokens Today"),
    ("sensor.ai_tts_chars_today", "0", "mdi:counter", "AI TTS Characters Today"),
    ("sensor.ai_stt_calls_today", "0", "mdi:counter", "AI STT Calls Today"),
    ("sensor.ai_model_cost_today", "0", "mdi:currency-eur", "AI Model Cost Today"),
    # Session 3 — midnight snapshots (seeded from live API values, not 0)
    # These are populated by _seed_snapshot_sensors() below instead.
    # Session 3 — email/dedup counters
    ("sensor.ai_email_priority_count", "0", "mdi:email-alert", "AI Email Priority Count"),
    ("sensor.ai_dedup_blocked_count", "0", "mdi:bell-cancel", "AI Dedup Blocked Count"),
    # Session 4 — self-awareness + escalation/recovery
    ("sensor.ai_last_satellite", "", "mdi:satellite-uplink", "AI Last Satellite"),
    ("sensor.ai_escalation_last_outcome", "", "mdi:shield-alert", "AI Escalation Last Outcome"),
    ("sensor.ai_recovery_pending_category", "", "mdi:wrench-clock", "AI Recovery Pending Category"),
    ("sensor.ai_budget_saved_pipelines", "{}", "mdi:content-save", "AI Budget Saved Pipelines"),
    ("sensor.ai_interview_progress", "0/9 complete", "mdi:clipboard-check-outline", "AI Interview Progress"),
    # Session 5 — stale flags + session mutexes (booleans)
    ("sensor.ai_calendar_stale", "off", "mdi:calendar-alert", "AI Calendar Data Stale"),
    ("sensor.ai_email_stale", "off", "mdi:email-alert", "AI Email Data Stale"),
    ("sensor.ai_media_data_stale", "off", "mdi:alert-circle-outline", "AI Media Data Stale"),
    ("sensor.ai_project_data_stale", "off", "mdi:clipboard-alert", "AI Project Data Stale"),
    ("sensor.ai_embedding_reindex_needed", "off", "mdi:database-refresh", "AI Embedding Reindex Needed"),
    ("sensor.ai_dispatcher_bypass_mode", "off", "mdi:highway", "AI Dispatcher Bypass Mode"),
    ("sensor.ai_gn_bedtime_lock", "off", "mdi:lock", "AI Goodnight Bedtime Lock"),
    ("sensor.ai_bedtime_active_mutex_proactive_bedtime_escalation", "off", "mdi:volume-mute", "AI Bedtime Active Mutex"),
    ("sensor.ai_notification_follow_me_reminder_loop_active", "off", "mdi:bell", "AI Notification Follow-Me Reminder Loop Active"),
    ("sensor.ai_winddown_active", "off", "mdi:moon-waning-crescent", "AI Wind-Down Active"),
    # Session 6 — briefing flags + stage/TTS/music counters
    ("sensor.ai_briefing_delivered_morning", "off", "mdi:check-circle", "AI Briefing Delivered Morning"),
    ("sensor.ai_briefing_delivered_afternoon", "off", "mdi:check-circle", "AI Briefing Delivered Afternoon"),
    ("sensor.ai_briefing_delivered_evening", "off", "mdi:check-circle", "AI Briefing Delivered Evening"),
    ("sensor.ai_winddown_stage", "0", "mdi:stairs", "AI Wind-Down Stage"),
    ("sensor.ai_stage_counter_helper_proactive_bedtime_escalation_rick", "0", "mdi:counter", "AI Proactive Bedtime Stage Counter"),
    ("sensor.ai_tts_calls_today", "0", "mdi:message-processing", "AI TTS Calls Today"),
    ("sensor.ai_tts_cache_hits_today", "0", "mdi:cached", "AI TTS Cache Hits Today"),
    ("sensor.ai_music_generations_today", "0", "mdi:counter", "AI Music Generations Today"),
    # Session 7 — work day flags + misc text state
    ("sensor.ai_context_work_day", "off", "mdi:briefcase", "AI Context Work Day"),
    ("sensor.ai_context_work_day_tomorrow", "off", "mdi:briefcase-clock", "AI Context Work Day Tomorrow"),
    ("sensor.ai_bedtime_predicted", "off", "mdi:bed-clock", "AI Bedtime Predicted"),
    ("sensor.ai_voice_session_pending", "", "mdi:microphone-message", "AI Voice Session Pending"),
    ("sensor.ai_music_feedback_context", "", "mdi:music-note", "AI Music Feedback Context"),
    ("sensor.ai_last_briefing_summary", "", "mdi:text-box-outline", "AI Last Briefing Summary"),
    ("sensor.ai_routine_stage", "none", "mdi:routes", "AI Routine Stage"),
    ("sensor.ai_routine_deviation", "none", "mdi:alert-decagram", "AI Routine Deviation"),
    ("sensor.ai_predicted_next_zone_raw", "", "mdi:map-marker-path", "AI Predicted Next Zone Raw"),
    ("sensor.ai_email_last_priority", "", "mdi:email-alert", "AI Email Last Priority"),
    # Session 8 — high-impact booleans + voice mood tags
    ("sensor.ai_ducking_flag", "off", "mdi:duck", "AI Ducking Flag"),
    ("sensor.ai_phone_call_active", "off", "mdi:phone-in-talk", "AI Phone Call Active"),
    ("sensor.ai_sleep_detected", "off", "mdi:sleep", "AI Sleep Detected"),
    ("sensor.ai_theatrical_mode_active", "off", "mdi:drama-masks", "AI Theatrical Mode Active"),
    ("sensor.ai_bedtime_active", "off", "mdi:bed-clock", "AI Bedtime Active"),
    ("sensor.ai_continuous_conversation_active", "off", "mdi:microphone-message", "AI Continuous Conversation Active"),
    ("sensor.ai_sustained_solo_zone", "off", "mdi:account-clock", "AI Sustained Solo Zone"),
    ("sensor.ai_voice_mood_rick_tags", "", "mdi:tag-text", "AI Voice Mood Rick Tags"),
    ("sensor.ai_voice_mood_quark_tags", "", "mdi:tag-text", "AI Voice Mood Quark Tags"),
    ("sensor.ai_voice_mood_kramer_tags", "", "mdi:tag-text", "AI Voice Mood Kramer Tags"),
    ("sensor.ai_voice_mood_deadpool_tags", "", "mdi:tag-text", "AI Voice Mood Deadpool Tags"),
    ("sensor.ai_voice_mood_doctor_portuondo_tags", "", "mdi:tag-text", "AI Voice Mood Doctor Portuondo Tags"),
    # Watch history tracker
    ("sensor.ai_watch_history_status", "idle", "mdi:television-classic", "AI Watch History"),
    # Listen history tracker
    ("sensor.ai_listen_history_status", "idle", "mdi:music-off", "AI Listen History"),
    # Radio Klara now-playing awareness (radio_klara.py)
    ("sensor.ai_radio_klara_status", "idle", "mdi:radio", "AI Radio Klara Status"),
    ("sensor.ai_radio_klara_now_playing", "idle", "mdi:radio-tower", "AI Radio Klara Now Playing"),
]


@time_trigger("startup")  # noqa: F821
def _seed_migrated_sensors():
    """Seed all migrated sensors with defaults so they exist immediately."""
    # ── Budget restore from JSON file (zero startup dependencies) ──
    budget_data = _read_budget_state()
    today = datetime.now().strftime("%Y-%m-%d")  # noqa: F821
    budget_counters = {}
    budget_snapshots = {}
    if budget_data and budget_data.get("date") == today:
        budget_counters = budget_data.get("counters", {})
        budget_snapshots = budget_data.get("snapshots", {})
        log.info(  # noqa: F821
            f"state_bridge: restoring budget state from JSON "
            f"(saved {budget_data.get('timestamp', '?')})"
        )

    # ── Seed all sensors (use restored values for budget entities) ──
    seeded = 0
    for entity_id, default, icon, fname in _STARTUP_SENSORS:
        restored_val = budget_counters.get(entity_id)
        seed_val = str(restored_val) if restored_val is not None else default
        try:
            current = state.get(entity_id)  # noqa: F821
            if current in (None, "unknown", "unavailable"):
                state.set(  # noqa: F821
                    entity_id, seed_val,
                    new_attributes={"icon": icon, "friendly_name": fname},
                )
                seeded += 1
        except Exception:
            state.set(  # noqa: F821
                entity_id, seed_val,
                new_attributes={"icon": icon, "friendly_name": fname},
            )
            seeded += 1
    if seeded:
        log.info(f"state_bridge: seeded {seeded} migrated sensors")  # noqa: F821

    # Seed snapshot sensors — first pass may get 0 if REST sensors aren't
    # ready yet. Retry after 60s to catch them once loaded.
    _seed_snapshot_sensors(budget_snapshots)
    task.sleep(60)  # noqa: F821
    _seed_snapshot_sensors(budget_snapshots)


def _seed_snapshot_sensors(restored=None):
    """Seed midnight snapshot sensors from restored JSON or API values.

    No lambdas — pyscript AST can't resolve builtins inside lambdas.
    """
    restored = restored or {}
    _seed_one_snapshot(
        "sensor.ai_openrouter_usage_midnight",
        "sensor.openrouter_credits", "total_usage", True,
        "mdi:router-wireless", "AI OpenRouter Usage Midnight",
        restored.get("sensor.ai_openrouter_usage_midnight"),
    )
    _seed_one_snapshot(
        "sensor.ai_elevenlabs_chars_midnight",
        "sensor.elevenlabs_subscription", "character_count", True,
        "mdi:account-voice", "AI ElevenLabs Chars Midnight",
        restored.get("sensor.ai_elevenlabs_chars_midnight"),
    )
    _seed_one_snapshot(
        "sensor.ai_serper_credits_midnight",
        "sensor.serper_account", None, False,
        "mdi:web", "AI Serper Credits Midnight",
        restored.get("sensor.ai_serper_credits_midnight"),
    )


def _seed_one_snapshot(entity_id, source_entity, attr_key, use_attr, icon, fname,
                       restored_val=None):
    """Seed a single snapshot sensor — prefer restored JSON value over live API."""
    current = None
    try:
        current = state.get(entity_id)  # noqa: F821
    except Exception:
        pass
    if current not in (None, "unknown", "unavailable", "0"):
        return  # already has a real value

    # Prefer restored value from budget_state.json over live API
    if restored_val is not None:
        val = str(restored_val)
    else:
        # Fallback: read from the API sensor
        val = "0"
        try:
            if use_attr:
                attrs = state.getattr(source_entity) or {}  # noqa: F821
                val = str(attrs.get(attr_key, 0))
            else:
                val = str(state.get(source_entity) or 0)  # noqa: F821
        except Exception:
            pass

    state.set(  # noqa: F821
        entity_id, val,
        new_attributes={"icon": icon, "friendly_name": fname},
    )
    log.info(f"state_bridge: snapshot {entity_id} = {val}")  # noqa: F821


@service  # noqa: F821
async def set_sensor_value(
    entity_id: str = "",
    value: str = "",
    attrs_json: str = "",
    icon: str = "",
    friendly_name: str = "",
):
    """
    yaml
    name: Set Sensor Value
    description: >-
      Generic bridge — creates or updates a pyscript-managed sensor via
      state.set().  Blueprints and automations can call this instead of
      needing their own pyscript bridge service.
    fields:
      entity_id:
        name: Entity ID
        description: "Full entity ID, e.g. sensor.ai_my_thing"
        required: true
        selector:
          text:
      value:
        name: Value
        description: "State value to set"
        required: true
        selector:
          text:
      attrs_json:
        name: Attributes JSON
        description: >-
          Optional JSON string of extra attributes to merge.
          Existing attributes are preserved; only keys present in the
          JSON are overwritten.
        required: false
        selector:
          text:
      icon:
        name: Icon
        description: "Optional MDI icon, e.g. mdi:brain"
        required: false
        selector:
          icon:
      friendly_name:
        name: Friendly Name
        description: "Optional friendly name for the sensor"
        required: false
        selector:
          text:
    """
    if not entity_id:
        log.error("state_bridge: entity_id is required")  # noqa: F821
        return

    if not entity_id.startswith("sensor."):
        log.error(  # noqa: F821
            "state_bridge: entity_id must start with 'sensor.' — got %s",
            entity_id,
        )
        return

    # Build attributes — preserve existing, merge new
    try:
        existing_attrs = dict(state.getattr(entity_id) or {})  # noqa: F821
    except Exception:
        existing_attrs = {}

    if attrs_json:
        try:
            new_attrs = _json.loads(attrs_json)
            if isinstance(new_attrs, dict):
                existing_attrs.update(new_attrs)
            else:
                log.warning(  # noqa: F821
                    "state_bridge: attrs_json must be a JSON object — got %s",
                    type(new_attrs).__name__,
                )
        except _json.JSONDecodeError as exc:
            log.warning("state_bridge: invalid attrs_json — %s", exc)  # noqa: F821

    if icon:
        existing_attrs["icon"] = icon
    if friendly_name:
        existing_attrs["friendly_name"] = friendly_name

    state.set(entity_id, value, new_attributes=existing_attrs)  # noqa: F821
    log.debug(  # noqa: F821
        "state_bridge: set %s = %s (attrs=%s)",
        entity_id,
        value,
        list(existing_attrs.keys()),
    )


# ── Budget State Persistence (save service + periodic + shutdown) ─────────────

@service  # noqa: F821
async def save_budget_state():
    """
    yaml
    name: Save Budget State
    description: >-
      Save budget counters + midnight snapshots to budget_state.json for
      restart persistence.  Called periodically (every 15 min), on HA
      shutdown, and after midnight reset.
    """
    today = datetime.now().strftime("%Y-%m-%d")  # noqa: F821
    counters = {}
    for eid in _BUDGET_COUNTER_ENTITIES:
        try:
            counters[eid] = state.get(eid) or "0"  # noqa: F821
        except Exception:
            counters[eid] = "0"
    snapshots = {}
    for eid in _BUDGET_SNAPSHOT_ENTITIES:
        try:
            snapshots[eid] = state.get(eid) or "0"  # noqa: F821
        except Exception:
            snapshots[eid] = "0"
    data = {
        "date": today,
        "timestamp": datetime.now().isoformat(),  # noqa: F821
        "counters": counters,
        "snapshots": snapshots,
    }
    _write_budget_state(_json.dumps(data, indent=2))
    log.debug("state_bridge: budget state saved to JSON")  # noqa: F821


@time_trigger("cron(*/15 * * * *)")  # noqa: F821
async def _budget_periodic_file_save():
    """Save budget state to JSON every 15 minutes."""
    await save_budget_state()


@time_trigger("shutdown")  # noqa: F821
def _budget_shutdown_save():
    """Save budget state to JSON on HA shutdown / pyscript reload.

    Non-async to avoid task cancellation.  Uses pathlib.Path.write_text()
    which works in the pyscript AST interpreter during shutdown (confirmed
    by testing — produces a harmless 'blocking call' HA warning).  Does
    NOT use @pyscript_executor (thread pool unavailable during reload).
    """
    from pathlib import Path
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        counters = {}
        for eid in _BUDGET_COUNTER_ENTITIES:
            try:
                counters[eid] = str(state.get(eid) or "0")  # noqa: F821
            except Exception:
                counters[eid] = "0"
        snapshots = {}
        for eid in _BUDGET_SNAPSHOT_ENTITIES:
            try:
                snapshots[eid] = str(state.get(eid) or "0")  # noqa: F821
            except Exception:
                snapshots[eid] = "0"
        data = {
            "date": today,
            "timestamp": datetime.now().isoformat(),
            "counters": counters,
            "snapshots": snapshots,
        }
        Path("/config/pyscript/budget_state.json").write_text(
            _json.dumps(data, indent=2)
        )
    except Exception:
        pass  # Best-effort — 15-min cron JSON is the primary safety net
