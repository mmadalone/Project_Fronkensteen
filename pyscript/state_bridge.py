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
    ("sensor.ai_interview_progress", "{}", "mdi:clipboard-check-outline", "AI Interview Progress"),
]


@time_trigger("startup")  # noqa: F821
def _seed_migrated_sensors():
    """Seed all migrated sensors with defaults so they exist immediately."""
    seeded = 0
    for entity_id, default, icon, fname in _STARTUP_SENSORS:
        try:
            current = state.get(entity_id)  # noqa: F821
            if current in (None, "unknown", "unavailable"):
                state.set(  # noqa: F821
                    entity_id, default,
                    new_attributes={"icon": icon, "friendly_name": fname},
                )
                seeded += 1
        except Exception:
            state.set(  # noqa: F821
                entity_id, default,
                new_attributes={"icon": icon, "friendly_name": fname},
            )
            seeded += 1
    if seeded:
        log.info(f"state_bridge: seeded {seeded} migrated sensors")  # noqa: F821

    # Seed snapshot sensors from live API values (not 0 — that would make
    # the daily delta = entire cumulative usage, blowing the budget gate).
    _seed_snapshot_sensors()


def _seed_snapshot_sensors():
    """Seed midnight snapshot sensors from current API values if missing."""
    snapshots = [
        (
            "sensor.ai_openrouter_usage_midnight",
            lambda: str(
                (state.getattr("sensor.openrouter_credits") or {}).get(  # noqa: F821
                    "total_usage", 0
                )
            ),
            "mdi:router-wireless",
            "AI OpenRouter Usage Midnight",
        ),
        (
            "sensor.ai_elevenlabs_chars_midnight",
            lambda: str(
                (state.getattr("sensor.elevenlabs_subscription") or {}).get(  # noqa: F821
                    "character_count", 0
                )
            ),
            "mdi:account-voice",
            "AI ElevenLabs Chars Midnight",
        ),
        (
            "sensor.ai_serper_credits_midnight",
            lambda: str(state.get("sensor.serper_account") or 0),  # noqa: F821
            "mdi:web",
            "AI Serper Credits Midnight",
        ),
    ]
    for entity_id, value_fn, icon, fname in snapshots:
        try:
            current = state.get(entity_id)  # noqa: F821
        except Exception:
            current = None
        if current in (None, "unknown", "unavailable", "0"):
            try:
                val = value_fn()
                state.set(  # noqa: F821
                    entity_id, val,
                    new_attributes={"icon": icon, "friendly_name": fname},
                )
                log.info(f"state_bridge: snapshot {entity_id} = {val}")  # noqa: F821
            except Exception as exc:
                # API sensor not ready yet — seed with 0, budget automation
                # will correct at midnight or next startup catch-up
                state.set(  # noqa: F821
                    entity_id, "0",
                    new_attributes={"icon": icon, "friendly_name": fname},
                )
                log.warning(f"state_bridge: snapshot fallback {entity_id}: {exc}")  # noqa: F821


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
