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

Also publishes, for YAML templates, which cannot read entity_config.yaml:
  sensor.ai_zone_map        fp2_zones and satellite_zones from entity_config.yaml
  sensor.ai_weather_sources the weather entity and the outdoor temperature source
                            (entity_config.yaml, else met.no, else the first one)
  sensor.ai_media_map       now_playing_sensors from entity_config.yaml
"""

import json as _json  # noqa: F811 — shadow-safe alias
from datetime import datetime  # noqa: F811 — for budget state timestamps

from shared_utils import load_entity_config, reload_entity_config


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


# ── Last-Satellite Persistence ────────────────────────────────────────────────
# sensor.ai_last_satellite is runtime state (state.set) so it does NOT survive a
# restart. Seeding it to "" leaves voice_handoff.yaml's satellite-match condition
# unsatisfiable (both clauses false: last_satellite=="" and satellite idle), so
# the FIRST handoff after every reboot is silently dropped. Persist it instead.

@pyscript_executor  # noqa: F821
def _read_last_satellite():
    """Read last_satellite.json — native Python, file I/O allowed (AP-55)."""
    import json as _json
    try:
        with open("/config/pyscript/last_satellite.json", "r") as f:
            return _json.load(f).get("entity_id") or ""
    except (FileNotFoundError, ValueError, OSError, AttributeError):
        return ""


@pyscript_executor  # noqa: F821
def _write_last_satellite(entity_id):
    """Write last_satellite.json atomically — native Python."""
    import json as _json
    import os as _os
    tmp = "/config/pyscript/last_satellite.json.tmp"
    with open(tmp, "w") as f:
        f.write(_json.dumps({"entity_id": entity_id}))
    _os.replace(tmp, "/config/pyscript/last_satellite.json")


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
    ("sensor.ai_email_reader_status", "idle", "mdi:email-search", "AI Email Reader Status"),
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
    ("sensor.ai_theatrical_status", "idle", "mdi:drama-masks", "AI Theatrical Status"),
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
    # Each person's Companion App phone sensors (person_phones.py)
    ("sensor.ai_person_phones", "0", "mdi:cellphone-link", "AI Person Phones"),
]


# ── Zone map for YAML templates ──────────────────────────────────────────────
# Templates cannot read entity_config.yaml, so the zone maps they need are
# published here in the config's own {entity: zone} shape. Pyscript modules
# keep reading the config directly.

ZONE_MAP_ENTITY = "sensor.ai_zone_map"


@time_trigger("startup")  # noqa: F821
def _publish_zone_map():
    """Publish fp2_zones and satellite_zones from entity_config.yaml."""
    cfg = reload_entity_config()
    fp2_zones = dict(cfg.get("fp2_zones") or {})
    satellite_zones = dict(cfg.get("satellite_zones") or {})
    state.set(  # noqa: F821
        ZONE_MAP_ENTITY, str(len(fp2_zones)),
        new_attributes={
            "fp2_zones": fp2_zones,
            "satellite_zones": satellite_zones,
            "friendly_name": "AI Zone Map",
            "icon": "mdi:floor-plan",
        },
    )


# ── Weather sources and media map for YAML templates ─────────────────────────
# Same reason as the zone map: templates cannot read entity_config.yaml.
# sensor.ai_weather_sources names the weather entity and the outdoor
# temperature source; sensor.ai_media_map names the companion "now playing"
# sensor of each media player that has one.

WEATHER_SOURCES_ENTITY = "sensor.ai_weather_sources"
MEDIA_MAP_ENTITY = "sensor.ai_media_map"
_ENTITY_REGISTRY_FILE = "/config/.storage/core.entity_registry"
# The entity registry reaches disk 10 s after a change while HA is running.
_REGISTRY_SETTLE_S = 20

_last_weather_sources = None


@pyscript_executor  # noqa: F821
def _met_weather_entities(registry_file, home_entry_ids):
    """Enabled weather entities of the met.no integration, best first (AP-55).

    Best = the one whose config entry follows the home location (HA's
    onboarding creates it, track_home), then the oldest, so adding a second
    met.no city never moves the weather away from home. Returns None when the
    registry cannot be read.
    """
    import orjson as _orjson

    try:
        with open(registry_file, "rb") as f:
            entities = _orjson.loads(f.read()).get("data", {}).get("entities", [])
    except Exception:
        return None
    found = [
        ent for ent in entities
        if ent.get("platform") == "met"
        and str(ent.get("entity_id", "")).startswith("weather.")
        and not ent.get("disabled_by")
    ]
    found.sort(key=lambda ent: (
        0 if ent.get("config_entry_id") in home_entry_ids else 1,
        ent.get("created_at") or "",
        ent["entity_id"],
    ))
    return [ent["entity_id"] for ent in found]


def _config_entity(cfg, key):
    """A single entity ID from entity_config.yaml, or "" when unset."""
    value = cfg.get(key)
    return value.strip() if isinstance(value, str) else ""


def _entity_exists(entity_id):
    try:
        state.get(entity_id)  # noqa: F821
        return True
    except NameError:
        return False


def _publish_weather_sources(reason, cfg):
    """Resolve and publish the weather entity and the outdoor temperature source.

    Weather entity: entity_config.yaml weather_entity, else the met.no entity
    (the one HA's onboarding creates), else the first weather entity, else
    none. A configured entity is used even if it does not exist, so a typo
    shows up as "Weather: Unavailable." instead of a silent switch of source.

    Temperature: entity_config.yaml weather_temperature_entity, else the
    weather entity's own temperature attribute. The template mirror in
    packages/ai_history_context.yaml reads both.
    """
    global _last_weather_sources

    weather = _config_entity(cfg, "weather_entity")
    weather_source = "entity_config" if weather else ""
    if not weather:
        home_entry_ids = []
        for entry in hass.config_entries.async_entries("met"):  # noqa: F821
            if (entry.data or {}).get("track_home"):
                home_entry_ids.append(entry.entry_id)
        met = _met_weather_entities(_ENTITY_REGISTRY_FILE, home_entry_ids)
        if met is None:
            log.warning(  # noqa: F821
                f"state_bridge: entity registry unreadable ({reason}); "
                f"keeping the previous weather sources"
            )
            return
        if met:
            weather, weather_source = met[0], "met.no"
    if not weather:
        names = sorted(state.names("weather"))  # noqa: F821
        if names:
            weather, weather_source = names[0], "first weather entity"
    if not weather:
        weather_source = "none"

    temperature = _config_entity(cfg, "weather_temperature_entity")
    if temperature:
        temperature_source = "entity_config"
    elif weather:
        temperature_source = "weather entity"
    else:
        temperature_source = "none"

    state.set(  # noqa: F821
        WEATHER_SOURCES_ENTITY, weather or "none",
        new_attributes={
            "weather_entity": weather,
            "weather_source": weather_source,
            "temperature_entity": temperature,
            "temperature_source": temperature_source,
            "friendly_name": "AI Weather Sources",
            "icon": "mdi:weather-partly-cloudy",
        },
    )

    current = (weather, weather_source, temperature, temperature_source)
    if current != _last_weather_sources:
        missing = [e for e in (weather, temperature) if e and not _entity_exists(e)]
        log.info(  # noqa: F821
            f"state_bridge: weather sources after {reason}: "
            f"weather={weather or 'none'} ({weather_source}), "
            f"temperature={temperature or 'the weather entity'} ({temperature_source})"
            + (f" — not found: {', '.join(missing)}" if missing else "")
        )
        _last_weather_sources = current


@time_trigger("startup")  # noqa: F821
def _weather_sources_startup():
    _publish_weather_sources("startup", reload_entity_config())


@event_trigger("entity_registry_updated")  # noqa: F821
def _weather_sources_registry_changed(**kwargs):
    """Re-resolve after entities are added, removed or renamed.

    Debounced, like person_phones: a burst of registry events yields one
    refresh, once the registry has been written to disk. Uses the cached
    config: a re-read here would push a half-edited entity_config.yaml to
    every module before the planned pyscript reload.
    """
    task.unique("state_bridge_weather_sources_refresh")  # noqa: F821
    task.sleep(_REGISTRY_SETTLE_S)  # noqa: F821
    _publish_weather_sources("entity registry change", load_entity_config())


@time_trigger("startup")  # noqa: F821
def _publish_media_map():
    """Publish now_playing_sensors ({media_player: sensor}) from entity_config.yaml."""
    cfg = reload_entity_config()
    raw = cfg.get("now_playing_sensors") or {}
    now_playing = {}
    if isinstance(raw, dict):
        for player, sensor in raw.items():
            if isinstance(player, str) and isinstance(sensor, str) and sensor.strip():
                now_playing[player.strip()] = sensor.strip()
    else:
        log.warning(  # noqa: F821
            "state_bridge: entity_config.yaml now_playing_sensors must map "
            "media_player to sensor; ignoring it"
        )
    state.set(  # noqa: F821
        MEDIA_MAP_ENTITY, str(len(now_playing)),
        new_attributes={
            "now_playing_sensors": now_playing,
            "friendly_name": "AI Media Map",
            "icon": "mdi:television-play",
        },
    )


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
    # Restore last-satellite so the first handoff after a reboot is not dropped.
    last_sat = _read_last_satellite() or ""

    seeded = 0
    for entity_id, default, icon, fname in _STARTUP_SENSORS:
        restored_val = budget_counters.get(entity_id)
        if entity_id == "sensor.ai_last_satellite" and last_sat:
            restored_val = last_sat
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


# ── Persist last-satellite on every change ────────────────────────────────────

@state_trigger("sensor.ai_last_satellite")  # noqa: F821
def _persist_last_satellite(**kwargs):
    """Mirror sensor.ai_last_satellite to disk so it survives a restart."""
    val = kwargs.get("value")
    if val and val not in ("unknown", "unavailable", ""):
        _write_last_satellite(val)
