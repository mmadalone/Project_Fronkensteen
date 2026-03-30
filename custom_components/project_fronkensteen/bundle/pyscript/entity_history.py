"""Entity History Query — Agent-facing recorder access (Gap 3).

Provides pyscript.entity_history_query for agents to answer historical
questions like "what was the temperature last night?" or "how long were
the lights on today?". Uses direct SQLite read-only access (proven
codebase pattern from away_patterns.py).
"""
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from shared_utils import build_result_entity_name

RECORDER_DB = Path("/config/home-assistant_v2.db")
RESULT_ENTITY = "sensor.ai_entity_history_status"
MAX_HOURS_BACK = 168  # 7 days max
MAX_RESULTS = 100

result_entity_name: dict[str, str] = {}


# ── Entity Name Helpers ──────────────────────────────────────────────────────


def _ensure_result_entity_name(force: bool = False) -> None:
    global result_entity_name
    if force or not result_entity_name:
        result_entity_name = build_result_entity_name(RESULT_ENTITY)


def _set_result(state_value: str = "ok", **attrs: Any) -> None:
    _ensure_result_entity_name()
    attrs.update(result_entity_name)
    state.set(RESULT_ENTITY, value=state_value, new_attributes=attrs)  # noqa: F821


# ── SQLite Helpers (proven pattern from away_patterns.py) ────────────────────


@pyscript_compile  # noqa: F821
def _get_conn() -> sqlite3.Connection:
    """Open the HA recorder DB in read-only mode."""
    conn = sqlite3.connect(f"file:{RECORDER_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000;")
    return conn


@pyscript_compile  # noqa: F821
def _resolve_metadata_id(entity_id: str) -> int | None:
    """Get metadata_id for an entity_id from recorder states_meta table."""
    with closing(_get_conn()) as conn:
        cursor = conn.execute(
            "SELECT metadata_id FROM states_meta WHERE entity_id = ?",
            (entity_id,),
        )
        row = cursor.fetchone()
        return row[0] if row else None


# ── Query Functions ──────────────────────────────────────────────────────────


@pyscript_executor  # noqa: F821
def _query_state_changes_sync(
    entity_id: str, hours_back: int, limit: int
) -> dict[str, Any]:
    """Query state change history for an entity."""
    meta_id = _resolve_metadata_id(entity_id)
    if meta_id is None:
        return {"error": f"Entity '{entity_id}' not found in recorder"}

    cutoff_ts = time.time() - (hours_back * 3600)
    with closing(_get_conn()) as conn:
        # Total count first (uncapped)
        total_row = conn.execute(
            "SELECT COUNT(*) FROM states "
            "WHERE metadata_id = ? AND last_updated_ts > ?",
            (meta_id, cutoff_ts),
        ).fetchone()
        total_count = total_row[0] if total_row else 0

        rows = conn.execute(
            "SELECT state, last_updated_ts FROM states "
            "WHERE metadata_id = ? AND last_updated_ts > ? "
            "ORDER BY last_updated_ts DESC LIMIT ?",
            (meta_id, cutoff_ts, limit),
        ).fetchall()

    if not rows:
        return {"entity": entity_id, "changes": [], "count": 0, "total_count": 0, "hours_back": hours_back}

    changes = []
    for row in rows:
        state_val = row["state"]
        ts = row["last_updated_ts"]
        if ts and state_val not in (None, ""):
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            changes.append({
                "state": state_val,
                "time": dt.strftime("%Y-%m-%d %H:%M:%S"),
            })

    return {
        "entity": entity_id,
        "changes": changes,
        "count": len(changes),
        "total_count": total_count,
        "hours_back": hours_back,
    }


@pyscript_executor  # noqa: F821
def _query_numeric_stats_sync(
    entity_id: str, hours_back: int
) -> dict[str, Any]:
    """Compute min/max/avg for numeric entities from state history."""
    meta_id = _resolve_metadata_id(entity_id)
    if meta_id is None:
        return {"error": f"Entity '{entity_id}' not found in recorder"}

    cutoff_ts = time.time() - (hours_back * 3600)
    with closing(_get_conn()) as conn:
        rows = conn.execute(
            "SELECT state FROM states "
            "WHERE metadata_id = ? AND last_updated_ts > ? "
            "AND state NOT IN ('unknown', 'unavailable', '')",
            (meta_id, cutoff_ts),
        ).fetchall()

    values = []
    for row in rows:
        try:
            values.append(float(row["state"]))
        except (ValueError, TypeError):
            continue

    if not values:
        return {"entity": entity_id, "error": "No numeric data in range", "hours_back": hours_back}

    unit = ""
    try:
        attrs = state.getattr(entity_id) or {}  # noqa: F821
        unit = attrs.get("unit_of_measurement", "")
    except Exception:
        pass

    return {
        "entity": entity_id,
        "min": round(min(values), 2),
        "max": round(max(values), 2),
        "avg": round(sum(values) / len(values), 2),
        "samples": len(values),
        "unit": unit or "",
        "hours_back": hours_back,
    }


@pyscript_executor  # noqa: F821
def _query_duration_sync(
    entity_id: str, target_state: str, hours_back: int
) -> dict[str, Any]:
    """Calculate total time an entity spent in a given state."""
    meta_id = _resolve_metadata_id(entity_id)
    if meta_id is None:
        return {"error": f"Entity '{entity_id}' not found in recorder"}

    cutoff_ts = time.time() - (hours_back * 3600)
    now_ts = time.time()

    with closing(_get_conn()) as conn:
        rows = conn.execute(
            "SELECT state, last_updated_ts FROM states "
            "WHERE metadata_id = ? AND last_updated_ts > ? "
            "ORDER BY last_updated_ts",
            (meta_id, cutoff_ts),
        ).fetchall()

    total_seconds = 0.0
    count = 0
    in_state_since = None

    for row in rows:
        state_val = row["state"]
        ts = row["last_updated_ts"]
        if state_val == target_state and in_state_since is None:
            in_state_since = ts
            count += 1
        elif state_val != target_state and in_state_since is not None:
            total_seconds += ts - in_state_since
            in_state_since = None

    # If still in target state, count up to now
    if in_state_since is not None:
        total_seconds += now_ts - in_state_since

    return {
        "entity": entity_id,
        "target_state": target_state,
        "total_hours": round(total_seconds / 3600, 2),
        "total_minutes": round(total_seconds / 60, 1),
        "occurrences": count,
        "hours_back": hours_back,
    }


# ── Public Service ───────────────────────────────────────────────────────────


@service(supports_response="only")  # noqa: F821
async def entity_history_query(
    entity_id: str = "",
    hours_back: int = 24,
    limit: int = 20,
    stat_type: str = "changes",
    target_state: str = "",
):
    """
    yaml
    name: Entity History Query
    description: >-
      Query entity state history from the recorder database. Three modes:
      changes (state transition list), stats (min/max/avg for numeric),
      duration (time spent in a specific state).
    fields:
      entity_id:
        name: Entity ID
        description: Full entity_id to query.
        required: true
        example: "sensor.living_room_temperature"
        selector:
          entity:
      hours_back:
        name: Hours Back
        description: How many hours to look back (1-168).
        default: 24
        selector:
          number:
            min: 1
            max: 168
            mode: box
      limit:
        name: Limit
        description: Max state changes to return (changes mode only).
        default: 20
        selector:
          number:
            min: 1
            max: 100
            mode: box
      stat_type:
        name: Stat Type
        description: "Query type: changes, stats, or duration."
        default: changes
        selector:
          select:
            options:
              - changes
              - stats
              - duration
      target_state:
        name: Target State
        description: "For duration queries: the state to measure (e.g., on, home)."
        default: ""
        selector:
          text:
    """
    # Kill switch
    try:
        enabled = state.get("input_boolean.ai_entity_history_enabled")  # noqa: F821
        if str(enabled).lower() == "off":
            return {"status": "ok", "skipped": True, "reason": "disabled"}
    except (NameError, AttributeError):
        pass

    if not entity_id:
        return {"status": "error", "error": "entity_id is required"}

    hours_back = min(max(1, int(hours_back or 24)), MAX_HOURS_BACK)
    limit = min(max(1, int(limit or 20)), MAX_RESULTS)

    t_start = time.monotonic()

    try:
        if stat_type == "stats":
            result = _query_numeric_stats_sync(entity_id, hours_back)
        elif stat_type == "duration":
            if not target_state:
                return {"status": "error", "error": "target_state required for duration query"}
            result = _query_duration_sync(entity_id, target_state, hours_back)
        else:
            result = _query_state_changes_sync(entity_id, hours_back, limit)
    except Exception as e:
        log.error(f"entity_history_query failed: {e}")  # noqa: F821
        _set_result("error", op=stat_type, entity=entity_id, error=str(e))
        return {"status": "error", "op": stat_type, "entity": entity_id, "error": str(e)}

    elapsed = round((time.monotonic() - t_start) * 1000, 1)
    result["elapsed_ms"] = elapsed
    result["status"] = "error" if "error" in result else "ok"
    result["op"] = stat_type

    _set_result(result.get("status", "ok"), **{
        k: v for k, v in result.items()
        if k not in ("changes",)  # Don't put full change list in sensor attrs
    })
    return result


# ── Startup ──────────────────────────────────────────────────────────────────


@time_trigger("startup")  # noqa: F821
async def entity_history_startup():
    """Initialize entity history status sensor."""
    _ensure_result_entity_name(force=True)
    _set_result("idle", op="startup")
    log.info("entity_history.py loaded — recorder query service ready")  # noqa: F821
