"""System Recovery Engine — event-driven self-healing for AI subsystems.

Subscribes to health transition events from system_health.py and executes
per-category recovery playbooks with exponential backoff and circuit breaker.

Sensor:  sensor.ai_system_recovery_status
Service: pyscript.recovery_run (manual trigger, supports_response: only)
Cron:    every 5 min (recovery probe — only runs when recovering/circuit-broken)
Startup: 120 s after HA start (after system_health's first check)
"""

import asyncio
import time
from pathlib import Path
from typing import Any

from shared_utils import build_result_entity_name

# ─── Constants ────────────────────────────────────────────────────────────────

RESULT_ENTITY = "sensor.ai_system_recovery_status"
KILL_SWITCH = "input_boolean.ai_system_recovery_enabled"
MAX_RETRIES_HELPER = "input_number.ai_recovery_max_retries_per_hour"
BASE_BACKOFF_HELPER = "input_number.ai_recovery_base_backoff_seconds"
PENDING_HELPER = "sensor.ai_recovery_pending_category"
HEALTH_SENSOR = "sensor.ai_system_health"
ENTITY_REGISTRY_FILE = "/config/.storage/core.entity_registry"
MAX_BACKOFF_SECONDS = 600  # 10 min cap

# Log policy: log.info for user-visible events, startup, errors.

# Recovery playbooks — action per health category
PLAYBOOKS = {
    "status_sensors": {"action": "pyscript_reload", "description": "Reload pyscript to re-register sensors"},
    "services": {"action": "pyscript_reload", "description": "Reload pyscript to re-register services"},
    "memory_db": {"action": "memory_probe", "description": "Delegate to memory.py recovery probe"},
    "tts_queue": {"action": "pyscript_reload", "description": "Reload pyscript to restart TTS queue"},
    "pipeline_entities": {"action": "reload_config_entry", "description": "Reload integration config entries"},
    "json_configs": {"action": "alert_only", "description": "Cannot auto-fix corrupted JSON"},
    "helpers": {"action": "alert_only", "description": "Missing helpers need config reload or restart"},
}


# ─── Standard sensor pattern ─────────────────────────────────────────────────

result_entity_name: dict[str, str] = {}


def _ensure_result_entity_name(force: bool = False) -> None:
    global result_entity_name
    if force or not result_entity_name:
        result_entity_name = build_result_entity_name(RESULT_ENTITY)


def _set_result(state_value: str = "ok", **attrs: Any) -> None:
    _ensure_result_entity_name()
    attrs.update(result_entity_name)
    state.set(RESULT_ENTITY, value=state_value, new_attributes=attrs)  # noqa: F821


# ─── Kill switch + helpers ───────────────────────────────────────────────────

def _is_enabled() -> bool:
    try:
        return state.get(KILL_SWITCH) != "off"  # noqa: F821
    except Exception:
        return True


def _helper_float(entity_id: str, default: float) -> float:
    try:
        val = state.get(entity_id)  # noqa: F821
        if val and val not in ("unknown", "unavailable", ""):
            return float(val)
    except Exception:
        pass
    return default


def _helper_str(entity_id: str, default: str) -> str:
    try:
        val = state.get(entity_id)  # noqa: F821
        if val and val not in ("unknown", "unavailable", ""):
            return str(val)
    except Exception:
        pass
    return default


# ─── Recovery state ──────────────────────────────────────────────────────────

_recovery_attempts: dict[str, list[float]] = {}  # category → [monotonic timestamps]
_active_recoveries: set[str] = set()
_circuit_breaker: set[str] = set()  # categories that exhausted retries


def _circuit_open(category: str) -> bool:
    """Check if retry budget exhausted for this category in the last hour."""
    max_retries = int(_helper_float(MAX_RETRIES_HELPER, 3.0))
    attempts = _recovery_attempts.get(category, [])
    now = time.monotonic()
    recent = [t for t in attempts if now - t < 3600]
    _recovery_attempts[category] = recent
    return len(recent) >= max_retries


def _get_category_grade(category: str) -> float:
    """Read a category grade from the system health sensor attributes."""
    try:
        attrs = state.getattr(HEALTH_SENSOR) or {}  # noqa: F821
        return float(attrs.get(f"{category}_grade", 1.0))
    except Exception:
        return 1.0


# ─── Config entry resolver (AP-55 compliant) ────────────────────────────────

@pyscript_executor  # noqa: F821
def _resolve_config_entry_ids_sync(entity_ids: list[str]) -> list[str]:
    """Read entity registry and resolve entity_ids to unique config_entry_ids."""
    import json as _json

    registry_path = Path(ENTITY_REGISTRY_FILE)
    if not registry_path.exists():
        return []
    try:
        data = _json.loads(registry_path.read_text())
        entries = data.get("data", {}).get("entities", [])
        entry_ids = set()
        for ent in entries:
            eid = ent.get("entity_id", "")
            ce_id = ent.get("config_entry_id", "")
            if eid in entity_ids and ce_id:
                entry_ids.add(ce_id)
        return list(entry_ids)
    except Exception:
        return []


# ─── Recovery actions ────────────────────────────────────────────────────────

async def _do_pyscript_reload(category: str) -> bool:
    """Reload all pyscript modules. Persist pending state for reload survival."""
    # Persist pending category so we can verify after reload
    try:
        state.set(  # noqa: F821
            PENDING_HELPER, category,
            new_attributes={
                "icon": "mdi:wrench-clock",
                "friendly_name": "AI Recovery Pending Category",
            },
        )
    except Exception:
        pass

    log.info("system_recovery: executing pyscript.reload for category '%s'", category)  # noqa: F821
    try:
        service.call("pyscript", "reload")  # noqa: F821
        return True
    except Exception as exc:
        log.error("system_recovery: pyscript.reload failed: %s", exc)  # noqa: F821
        return False


async def _do_reload_config_entries(details: dict) -> bool:
    """Reload config entries for unavailable pipeline entities."""
    missing = details.get("missing", []) + details.get("unavailable", [])
    if not missing:
        return True

    entry_ids = await _resolve_config_entry_ids_sync(missing)
    if not entry_ids:
        log.warning("system_recovery: no config_entry_ids resolved for %s", missing)  # noqa: F821
        return False

    success = True
    for ce_id in entry_ids:
        try:
            log.info("system_recovery: reloading config entry %s", ce_id)  # noqa: F821
            service.call(  # noqa: F821
                "homeassistant", "reload_config_entry",
                entry_id=ce_id,
            )
        except Exception as exc:
            log.error("system_recovery: reload_config_entry %s failed: %s", ce_id, exc)  # noqa: F821
            success = False
    return success


# ─── Recovery orchestrator ───────────────────────────────────────────────────

async def _attempt_recovery(category: str, details: dict) -> None:
    """Execute the recovery playbook for a category with backoff."""
    if category in _active_recoveries:
        return
    if category in _circuit_breaker:
        return
    if _circuit_open(category):
        _circuit_breaker.add(category)
        log.warning(  # noqa: F821
            "system_recovery: circuit breaker OPEN for '%s' — exhausted retries",
            category,
        )
        event.fire(  # noqa: F821
            "ai_recovery_exhausted",
            category=category,
            attempts=len(_recovery_attempts.get(category, [])),
            grade=_get_category_grade(category),
        )
        _update_sensor()
        return

    playbook = PLAYBOOKS.get(category)
    if not playbook:
        return
    action = playbook["action"]

    if action == "alert_only":
        event.fire(  # noqa: F821
            "ai_recovery_alert",
            category=category,
            reason=playbook["description"],
            details=details,
        )
        return

    _active_recoveries.add(category)
    _update_sensor()

    # Calculate backoff
    attempts = _recovery_attempts.get(category, [])
    attempt_num = len([t for t in attempts if time.monotonic() - t < 3600])
    base = _helper_float(BASE_BACKOFF_HELPER, 60.0)
    backoff = min(base * (2 ** attempt_num), MAX_BACKOFF_SECONDS)

    log.info(  # noqa: F821
        "system_recovery: %s — action=%s, attempt=%d, backoff=%.0fs",
        category, action, attempt_num + 1, backoff,
    )

    # Wait backoff
    await asyncio.sleep(backoff)

    # Record attempt
    _recovery_attempts.setdefault(category, []).append(time.monotonic())

    # Execute
    success = False
    if action == "pyscript_reload":
        # Coalesce: check if another category already has a pending reload
        reload_already_pending = False
        for other_cat in _active_recoveries:
            if other_cat != category:
                other_pb = PLAYBOOKS.get(other_cat, {})
                if other_pb.get("action") == "pyscript_reload":
                    reload_already_pending = True
                    break
        if not reload_already_pending:
            success = await _do_pyscript_reload(category)
            # Note: pyscript.reload will restart this module.
            # The _active_recoveries set will be reset.
            # The pending helper will be checked on startup.
            return  # module is being reloaded
        else:
            log.info("system_recovery: pyscript.reload already pending from another category")  # noqa: F821
            success = True  # piggyback on the other reload

    elif action == "reload_config_entry":
        success = await _do_reload_config_entries(details)

    elif action == "memory_probe":
        # Memory.py has its own 5-min recovery probe.
        # We just fire an alert if it doesn't recover in a reasonable time.
        log.info("system_recovery: memory_db — delegating to memory.py recovery probe")  # noqa: F821
        success = True  # we don't block; memory.py handles itself

    _active_recoveries.discard(category)

    if success:
        event.fire(  # noqa: F821
            "ai_recovery_completed",
            category=category,
            action=action,
        )

    _update_sensor()


def _update_sensor() -> None:
    """Update the recovery status sensor with current state."""
    if _active_recoveries:
        sensor_state = "recovering"
    elif _circuit_breaker:
        sensor_state = "exhausted"
    else:
        sensor_state = "idle"
    _set_result(
        sensor_state,
        active_recoveries=list(_active_recoveries),
        circuit_broken=list(_circuit_breaker),
        total_attempts_1h=sum([
            len([t for t in ts if time.monotonic() - t < 3600])
            for ts in _recovery_attempts.values()
        ]),
    )


# ─── Event handler ───────────────────────────────────────────────────────────

@event_trigger("ai_health_category_degraded")  # noqa: F821
async def _on_category_degraded(**kwargs):
    """Handle per-category degradation events from system_health.py."""
    if not _is_enabled():
        return

    category = kwargs.get("category", "")
    details = kwargs.get("details", {})

    if not category or category not in PLAYBOOKS:
        return

    log.info(  # noqa: F821
        "system_recovery: category '%s' degraded (grade %.2f → %.2f)",
        category,
        kwargs.get("old_grade", 1.0),
        kwargs.get("new_grade", 0.0),
    )

    await _attempt_recovery(category, details)


# ─── Recovery probe cron ─────────────────────────────────────────────────────

@time_trigger("cron(*/5 * * * *)")  # noqa: F821
async def _recovery_probe():
    """Check if circuit-broken categories have recovered."""
    if not _circuit_breaker:
        return

    recovered = []
    for category in list(_circuit_breaker):
        grade = _get_category_grade(category)
        if grade >= 1.0:
            recovered.append(category)

    for category in recovered:
        _circuit_breaker.discard(category)
        _recovery_attempts.pop(category, None)
        log.info(  # noqa: F821
            "system_recovery: circuit breaker CLEARED for '%s' — grade recovered to 1.0",
            category,
        )

    if recovered:
        _update_sensor()


# ─── Manual trigger service ──────────────────────────────────────────────────

@service(supports_response="only")  # noqa: F821
async def recovery_run(category: str = ""):
    """
    yaml
    name: Recovery Run
    description: >-
      Manually trigger recovery for a specific health category.
      If category is empty, shows current recovery status.
    fields:
      category:
        description: Health category to recover (status_sensors, services, memory_db, tts_queue, pipeline_entities)
        example: "status_sensors"
    """
    if not category:
        return {
            "status": "idle" if not _active_recoveries else "recovering",
            "active": list(_active_recoveries),
            "circuit_broken": list(_circuit_breaker),
            "playbooks": list(PLAYBOOKS.keys()),
        }
    if category not in PLAYBOOKS:
        return {"error": f"Unknown category: {category}", "available": list(PLAYBOOKS.keys())}

    # Force-clear circuit breaker for manual runs
    _circuit_breaker.discard(category)
    _recovery_attempts.pop(category, None)

    grade = _get_category_grade(category)
    await _attempt_recovery(category, {"manual": True, "current_grade": grade})
    return {"status": "triggered", "category": category}


# ─── Startup ─────────────────────────────────────────────────────────────────

@time_trigger("startup")  # noqa: F821
async def system_recovery_startup():
    """Initialize recovery engine after system_health completes first check."""
    _ensure_result_entity_name(force=True)
    _set_result("idle", op="startup")
    log.info("system_recovery: initializing, first probe in 120 s")  # noqa: F821

    task.sleep(120)  # noqa: F821

    # Check for pending recovery from a previous pyscript.reload
    pending = _helper_str(PENDING_HELPER, "")
    if pending:
        # Clear the marker
        try:
            state.set(  # noqa: F821
                PENDING_HELPER, "",
                new_attributes={
                    "icon": "mdi:wrench-clock",
                    "friendly_name": "AI Recovery Pending Category",
                },
            )
        except Exception:
            pass
        log.info(  # noqa: F821
            "system_recovery: found pending category '%s' from pre-reload — "
            "scheduling follow-up check in 90 s", pending,
        )
        await asyncio.sleep(90)
        grade = _get_category_grade(pending)
        if grade < 1.0:
            log.warning(  # noqa: F821
                "system_recovery: category '%s' still degraded (grade %.2f) after reload",
                pending, grade,
            )
        else:
            log.info(  # noqa: F821
                "system_recovery: category '%s' recovered after reload (grade %.2f)",
                pending, grade,
            )

    _update_sensor()
    log.info("system_recovery: loaded — idle")  # noqa: F821
