"""System health self-diagnostic — aggregated boot-time + periodic validator.

Checks 8 categories: module status sensors, pyscript services (module proxy),
critical helpers, pipeline entities, memory DB, JSON configs, TTS queue,
promoter health.  Weighted score maps to healthy / degraded / failing.

All check data is discovered dynamically at runtime:
  - Status sensors + services: scanned from /config/pyscript/*.py (RESULT_ENTITY + @service)
  - Helpers: scanned from /config/helpers_input_*.yaml (ai_* keys)
  - Pipeline entities: satellite_zones from entity_config.yaml + dispatcher attrs
  - JSON configs: listed in entity_config.yaml system_health.json_configs

Sensor:  sensor.ai_system_health
Service: pyscript.system_health_check (supports_response: only)
Cron:    every 30 minutes
Startup: 60 s after EVENT_HOMEASSISTANT_STARTED
"""

import asyncio
import time
from datetime import datetime
from typing import Any

from shared_utils import build_result_entity_name, load_entity_config, reload_entity_config


# ─── Constants ────────────────────────────────────────────────────────────────

RESULT_ENTITY = "sensor.ai_system_health"
DB_PATH = "/config/memory.db"
PYSCRIPT_DIR = "/config/pyscript"
HELPERS_DIR = "/config"

# Category weights (sum = 100)
WEIGHTS = {
    "status_sensors": 30,
    "services": 25,
    "helpers": 15,
    "pipeline_entities": 10,
    "memory_db": 10,
    "json_configs": 5,
    "tts_queue": 5,
}

HEALTHY_THRESHOLD = 0.80
DEGRADED_THRESHOLD = 0.50

ICONS = {
    "healthy": "mdi:shield-check",
    "degraded": "mdi:shield-alert",
    "failing": "mdi:shield-off",
    "error": "mdi:shield-bug",
    "idle": "mdi:shield-sync",
}

# ─── State transition tracking ──────────────────────────────────────────────

_previous_state: str = "idle"
_previous_category_grades: dict[str, float] = {}


def _fire_transition_events(result: dict) -> None:
    """Fire events when overall state or per-category grades change."""
    global _previous_state, _previous_category_grades
    new_state = result.get("state", "error")
    new_score = result.get("score", 0)
    cats = result.get("categories", {})

    # Overall state transition
    if new_state != _previous_state and _previous_state != "idle":
        event.fire(  # noqa: F821
            "ai_health_transition",
            old_state=_previous_state,
            new_state=new_state,
            score=new_score,
            timestamp=result.get("ts", ""),
        )

    # Per-category degradation
    for cat, data in cats.items():
        new_grade = data.get("grade", 1.0)
        old_grade = _previous_category_grades.get(cat, 1.0)
        if new_grade < old_grade and new_grade < 1.0:
            event.fire(  # noqa: F821
                "ai_health_category_degraded",
                category=cat,
                old_grade=old_grade,
                new_grade=new_grade,
                details=data,
                score=new_score,
                timestamp=result.get("ts", ""),
            )

    _previous_state = new_state
    _previous_category_grades = {
        cat: data.get("grade", 1.0) for cat, data in cats.items()
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
    attrs["icon"] = ICONS.get(state_value, ICONS["idle"])
    state.set(RESULT_ENTITY, value=state_value, new_attributes=attrs)  # noqa: F821


def _safe_get(entity_id: str) -> str | None:
    """Get entity state, returning None on NameError (entity never registered)."""
    try:
        return state.get(entity_id)  # noqa: F821
    except NameError:
        return None


# ─── Executor functions (file I/O, DB — AP-55 compliant) ─────────────────────

@pyscript_executor  # noqa: F821
def _scan_pyscript_modules_sync() -> dict:
    """Scan /config/pyscript/*.py to discover RESULT_ENTITY sensors and @service functions.

    Returns:
        {
            "sensors": ["sensor.ai_dispatcher_status", ...],
            "service_module_map": {"agent_dispatch": "sensor.ai_dispatcher_status", ...},
        }
    """
    import glob as _glob
    import re as _re

    re_result = _re.compile(r'^\s*(?:_?RESULT_ENTITY)\s*=\s*["\']([^"\']+)["\']', _re.MULTILINE)
    re_service_deco = _re.compile(r'^@service', _re.MULTILINE)
    re_func_def = _re.compile(r'^(?:async\s+)?def\s+(\w+)\s*\(', _re.MULTILINE)

    sensors = []
    svc_map = {}

    for fpath in sorted(_glob.glob(f"{PYSCRIPT_DIR}/*.py")):
        try:
            with open(fpath, encoding="utf-8") as fh:
                content = fh.read()
        except Exception:
            continue

        # Extract RESULT_ENTITY
        m = re_result.search(content)
        result_entity = m.group(1) if m else None
        if result_entity:
            sensors.append(result_entity)

        # Extract @service-decorated function names
        lines = content.split("\n")
        i = 0
        while i < len(lines):
            if re_service_deco.match(lines[i]):
                # Look at next non-empty line(s) for the def
                for j in range(i + 1, min(i + 3, len(lines))):
                    fm = re_func_def.match(lines[j])
                    if fm:
                        func_name = fm.group(1)
                        if not func_name.startswith("_") and result_entity:
                            svc_map[func_name] = result_entity
                        break
            i += 1

    return {"sensors": sensors, "service_module_map": svc_map}


@pyscript_executor  # noqa: F821
def _scan_helper_files_sync() -> list:
    """Scan /config/helpers_input_*.yaml for ai_* helper entity IDs.

    Returns list of entity IDs like ["input_boolean.ai_dispatcher_enabled", ...].
    """
    import glob as _glob
    import re as _re

    re_top_key = _re.compile(r'^(ai_\w+)\s*:', _re.MULTILINE)
    # Map filename pattern to entity domain
    type_map = {
        "boolean": "input_boolean",
        "number": "input_number",
        "select": "input_select",
        "text": "input_text",
        "datetime": "input_datetime",
        "button": "input_button",
    }

    helpers = []
    for helper_type, domain in type_map.items():
        fpath = f"{HELPERS_DIR}/helpers_input_{helper_type}.yaml"
        try:
            with open(fpath, encoding="utf-8") as fh:
                content = fh.read()
        except FileNotFoundError:
            continue
        except Exception:
            continue
        for m in re_top_key.finditer(content):
            helpers.append(f"{domain}.{m.group(1)}")

    return helpers


@pyscript_executor  # noqa: F821
def _validate_json_configs_sync(config_paths: list) -> dict:
    """Validate JSON config files exist and parse correctly."""
    import json as _json
    import os as _os

    results = {}
    for fpath in config_paths:
        try:
            if not _os.path.exists(fpath):
                results[fpath] = {"valid": False, "error": "file not found"}
                continue
            with open(fpath, encoding="utf-8") as fh:
                data = _json.load(fh)
            if not isinstance(data, (dict, list)):
                results[fpath] = {"valid": False, "error": "not dict or list"}
                continue
            results[fpath] = {"valid": True, "entries": len(data)}
        except _json.JSONDecodeError as exc:
            results[fpath] = {"valid": False, "error": f"JSON parse: {exc}"}
        except Exception as exc:
            results[fpath] = {"valid": False, "error": str(exc)[:120]}
    return results


@pyscript_executor  # noqa: F821
def _check_memory_db_sync() -> dict:
    """Check memory DB exists and is responsive."""
    import os as _os
    import sqlite3 as _sqlite3

    result = {"exists": False, "responsive": False, "size_mb": 0.0}
    try:
        if not _os.path.exists(DB_PATH):
            return result
        result["exists"] = True
        result["size_mb"] = round(_os.path.getsize(DB_PATH) / (1024 * 1024), 2)
        conn = _sqlite3.connect(DB_PATH, timeout=5)
        try:
            cursor = conn.execute("SELECT COUNT(*) FROM mem")
            result["rows"] = cursor.fetchone()[0]
            result["responsive"] = True
        finally:
            conn.close()
    except Exception as exc:
        result["error"] = str(exc)[:120]
    return result


# ─── Category check functions ────────────────────────────────────────────────

def _pct_grade(bad: int, total: int) -> float:
    """Grade by percentage: <5% = pass, 5-15% = degraded, >15% = fail."""
    if total == 0 or bad == 0:
        return 1.0
    pct = bad / total
    if pct <= 0.05:
        return 1.0
    if pct <= 0.15:
        return 0.5
    return 0.0


def _check_status_sensors(sensors: list) -> dict:
    """Check all discovered module RESULT_ENTITY sensors are alive."""
    missing = []
    errors = []
    ok_count = 0
    for sid in sensors:
        val = _safe_get(sid)
        if val is None or val in ("unknown", "unavailable"):
            missing.append(sid)
        elif val == "error":
            errors.append(sid)
        else:
            ok_count += 1
    bad = len(missing) + len(errors)
    return {
        "grade": _pct_grade(bad, len(sensors)),
        "total": len(sensors),
        "ok": ok_count,
        "missing": missing[:10],
        "errors": errors[:10],
    }


def _check_services(svc_map: dict) -> dict:
    """Check pyscript services via module-proxy (dynamically built map)."""
    potentially_missing = []
    ok_count = 0
    for svc_name, module_sensor in svc_map.items():
        val = _safe_get(module_sensor)
        if val is None or val in ("unknown", "unavailable"):
            potentially_missing.append(svc_name)
        else:
            ok_count += 1
    bad = len(potentially_missing)
    return {
        "grade": _pct_grade(bad, len(svc_map)),
        "total": len(svc_map),
        "ok": ok_count,
        "potentially_missing": potentially_missing[:10],
    }


def _check_helpers(helpers: list) -> dict:
    """Check discovered ai_* helpers exist and are not unavailable.

    "unknown" is normal for input_text (never set) and input_button (no
    persistent state) — only "unavailable" and None (missing) are problems.
    """
    missing = []
    unavailable = []
    ok_count = 0
    for eid in helpers:
        val = _safe_get(eid)
        if val is None:
            missing.append(eid)
        elif val == "unavailable":
            unavailable.append(eid)
        else:
            ok_count += 1  # "unknown" counted as ok
    bad = len(missing) + len(unavailable)
    return {
        "grade": _pct_grade(bad, len(helpers)),
        "total": len(helpers),
        "ok": ok_count,
        "missing": missing[:10],
        "unavailable": unavailable[:10],
    }


def _check_pipeline_entities(config: dict) -> dict:
    """Check pipeline infra: satellites from satellite_zones, TTS/STT from dispatcher."""
    entities = []
    # Satellites — discovered from satellite_zones in entity_config.yaml
    for sat_id in (config.get("satellite_zones") or {}):
        entities.append(sat_id)
    # TTS/STT — read from dispatcher sensor attributes (populated by pipeline cache)
    disp_attrs = state.getattr("sensor.ai_dispatcher_status") or {}  # noqa: F821
    for key in ("tts_engine", "stt_engine"):
        engine = disp_attrs.get(key)
        if engine and engine not in entities:
            entities.append(engine)

    missing = []
    ok_count = 0
    for eid in entities:
        val = _safe_get(eid)
        # "unknown" is normal for TTS/STT entities — only None means unregistered
        if val is None:
            missing.append(eid)
        else:
            ok_count += 1
    bad = len(missing)
    return {
        "grade": _pct_grade(bad, len(entities)),
        "total": len(entities),
        "ok": ok_count,
        "missing": missing[:10],
    }


def _check_tts_queue() -> dict:
    """Check TTS queue service alive + not in error state.

    Speaker config file validity is covered by the json_configs category.
    """
    val = _safe_get("sensor.ai_tts_queue_status")
    if val is None or val in ("unknown", "unavailable"):
        return {"grade": 0.0, "service": False, "state": val or "missing"}
    if val == "error":
        return {"grade": 0.5, "service": True, "state": val}
    return {"grade": 1.0, "service": True, "state": val}


async def _check_json_configs(manifest: dict) -> dict:
    """Validate JSON config files (async wrapper for executor)."""
    paths = manifest.get("json_configs", [])
    if not paths:
        return {"grade": 1.0, "total": 0, "invalid": [], "details": {}}
    results = await _validate_json_configs_sync(paths)
    invalid = [p for p, r in results.items() if not r.get("valid")]
    grade = 1.0 if len(invalid) == 0 else (0.5 if len(invalid) == 1 else 0.0)
    return {
        "grade": grade,
        "total": len(paths),
        "invalid": invalid[:10],
        "details": results,
    }


async def _check_memory_db() -> dict:
    """Check memory DB exists, is responsive, threshold not exceeded."""
    db = await _check_memory_db_sync()
    if not db.get("exists"):
        return {"grade": 0.0, **db}
    if not db.get("responsive"):
        return {"grade": 0.0, **db}
    mem_attrs = state.getattr("sensor.memory_result") or {}  # noqa: F821
    threshold = str(mem_attrs.get("threshold_exceeded", "false")).lower() == "true"
    grade = 0.5 if threshold else 1.0
    return {"grade": grade, "threshold_exceeded": threshold, **db}


# ─── Orchestrator ─────────────────────────────────────────────────────────────

async def _run_health_check() -> dict:
    """Run all 8 checks and compute weighted score."""
    t0 = time.monotonic()

    # Dynamic discovery via file scanning (executor threads)
    scan_result = await _scan_pyscript_modules_sync()
    discovered_sensors = scan_result.get("sensors", [])
    svc_map = scan_result.get("service_module_map", {})
    discovered_helpers = await _scan_helper_files_sync()

    # entity_config.yaml — only used for satellite_zones + json_configs
    full_config = load_entity_config()
    manifest = full_config.get("system_health", {})

    # Run all checks
    cats = {
        "status_sensors": _check_status_sensors(discovered_sensors),
        "services": _check_services(svc_map),
        "helpers": _check_helpers(discovered_helpers),
        "pipeline_entities": _check_pipeline_entities(full_config),
        "tts_queue": _check_tts_queue(),
    }
    cats["json_configs"] = await _check_json_configs(manifest)
    cats["memory_db"] = await _check_memory_db()

    # Weighted score
    total_weight = sum(WEIGHTS.values())
    score = sum([
        cats.get(cat, {}).get("grade", 0.0) * w
        for cat, w in WEIGHTS.items()
    ])
    score = round(score / total_weight, 3)

    if score >= HEALTHY_THRESHOLD:
        overall = "healthy"
    elif score >= DEGRADED_THRESHOLD:
        overall = "degraded"
    else:
        overall = "failing"

    return {
        "state": overall,
        "score": score,
        "categories": cats,
        "elapsed_ms": round((time.monotonic() - t0) * 1000, 1),
        "ts": datetime.now().isoformat(),
    }


def _build_sensor_attrs(result: dict) -> dict:
    """Flatten diagnostic dict into sensor-friendly attributes."""
    attrs = {
        "score": result.get("score", 0),
        "elapsed_ms": result.get("elapsed_ms", 0),
        "last_check": result.get("ts", ""),
    }
    for cat, data in result.get("categories", {}).items():
        attrs[f"{cat}_grade"] = data.get("grade", 0)
        if "total" in data:
            attrs[f"{cat}_total"] = data["total"]
        if "ok" in data:
            attrs[f"{cat}_ok"] = data["ok"]
        for key in ("missing", "errors", "potentially_missing", "unavailable", "invalid"):
            items = data.get(key, [])
            if items:
                attrs[f"{cat}_{key}"] = items[:10]
    return attrs


# ─── Service ──────────────────────────────────────────────────────────────────

@service(supports_response="only")  # noqa: F821
async def system_health_check():
    """
    yaml
    name: System Health Check
    description: >-
      Run a full diagnostic across all AI subsystems.  Returns per-category
      grades, weighted score, and overall state (healthy / degraded / failing).
      Updates sensor.ai_system_health with the result.
    """
    try:
        result = await _run_health_check()
        _set_result(result.get("state", "error"), **_build_sensor_attrs(result))
        _fire_transition_events(result)
        return result
    except Exception as exc:
        log.error("system_health_check failed: %s", exc)  # noqa: F821
        _set_result("error", error=str(exc)[:200])
        return {"state": "error", "error": str(exc)}


# ─── Triggers ─────────────────────────────────────────────────────────────────

@time_trigger("startup")  # noqa: F821
async def system_health_startup():
    """Initialize sensor and run first check after 60 s startup delay."""
    _ensure_result_entity_name(force=True)
    _set_result("idle", score=0, last_check="pending")
    log.info("system_health: sensor initialized, first check in 60 s")  # noqa: F821
    task.sleep(60)  # noqa: F821
    await asyncio.to_thread(reload_entity_config)
    try:
        result = await _run_health_check()
        overall = result.get("state", "error")
        _set_result(overall, **_build_sensor_attrs(result))
        _fire_transition_events(result)
        log.info(  # noqa: F821
            "system_health: startup check — %s (score %.3f)",
            overall, result.get("score", 0),
        )
    except Exception as exc:
        log.error("system_health: startup check failed: %s", exc)  # noqa: F821
        _set_result("error", error=str(exc)[:200])


@time_trigger("cron(*/30 * * * *)")  # noqa: F821
async def system_health_periodic():
    """Periodic health check every 30 minutes."""
    try:
        result = await _run_health_check()
        overall = result.get("state", "error")
        _set_result(overall, **_build_sensor_attrs(result))
        _fire_transition_events(result)
        if overall != "healthy":
            log.warning(  # noqa: F821
                "system_health: periodic check — %s (score %.3f)",
                overall, result.get("score", 0),
            )
    except Exception as exc:
        log.error("system_health: periodic check failed: %s", exc)  # noqa: F821
        _set_result("error", error=str(exc)[:200])
