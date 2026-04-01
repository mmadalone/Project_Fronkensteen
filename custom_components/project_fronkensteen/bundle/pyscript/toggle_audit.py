"""Kill Switch Audit Trail — source attribution for all ai_* toggles.

Dynamically watches all input_boolean.ai_* entities and records who/what
toggled them: user (UI), automation, pyscript module, or unknown.  Stores
audit rows in memory.db toggle_audit table with context attribution from
the HA recorder.

Sensor:  sensor.ai_toggle_audit_status
Service: pyscript.toggle_audit_query (supports_response: only)
Cron:    daily at 03:30 for retention purge
Startup: 30 s after HA start (entity discovery + trigger registration)
"""

import asyncio
import sqlite3
import time
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from shared_utils import build_result_entity_name

# ─── Constants ────────────────────────────────────────────────────────────────

RESULT_ENTITY = "sensor.ai_toggle_audit_status"
DB_PATH = "/config/memory.db"
RECORDER_DB = Path("/config/home-assistant_v2.db")
KILL_SWITCH = "input_boolean.ai_toggle_audit_enabled"
RETENTION_HELPER = "input_number.ai_toggle_audit_retention_days"
ENTITY_PREFIX = "input_boolean.ai_"
RECORDER_SETTLE_DELAY = 0.5       # seconds to wait for recorder commit
RECORDER_RETRY_DELAY = 1.5        # second attempt if first returns no context
SKIP_STATES = {"unavailable", "unknown"}

# Log policy: log.info for user-visible events, startup, errors.
# Routine per-toggle tracing uses log.debug — enable via Logger integration.


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


# ─── Kill switch + test mode guards ─────────────────────────────────────────

def _is_enabled() -> bool:
    try:
        return state.get(KILL_SWITCH) != "off"  # noqa: F821
    except Exception:
        return True


def _is_test_mode() -> bool:
    try:
        return state.get("input_boolean.ai_test_mode") == "on"  # noqa: F821
    except Exception:
        return False


# ─── User map for context resolution ────────────────────────────────────────

_user_map: dict[str, str] = {}  # {user_id_uuid: person_slug}
_user_map_ts: float = 0.0
_USER_MAP_TTL = 300.0  # refresh every 5 min


def _refresh_user_map() -> None:
    """Build user_id → person slug map from person.* entities."""
    global _user_map, _user_map_ts
    if time.monotonic() - _user_map_ts < _USER_MAP_TTL:
        return
    new_map = {}
    try:
        for eid in state.names(domain="person"):  # noqa: F821
            attrs = state.getattr(eid) or {}  # noqa: F821
            uid = attrs.get("user_id", "")
            if uid:
                slug = eid.replace("person.", "")
                new_map[uid] = slug
    except Exception as exc:
        log.warning("toggle_audit: user map refresh failed: %s", exc)  # noqa: F821
    _user_map = new_map
    _user_map_ts = time.monotonic()


# ─── Recorder context lookup (AP-55 compliant) ──────────────────────────────

@pyscript_compile  # noqa: F821
def _get_recorder_conn() -> sqlite3.Connection:
    """Open the HA recorder DB in read-only mode."""
    conn = sqlite3.connect(f"file:{RECORDER_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000;")
    return conn


@pyscript_compile  # noqa: F821
def _resolve_metadata_id(entity_id: str) -> int | None:
    """Get metadata_id for an entity_id from recorder states_meta table."""
    with closing(_get_recorder_conn()) as conn:
        cursor = conn.execute(
            "SELECT metadata_id FROM states_meta WHERE entity_id = ?",
            (entity_id,),
        )
        row = cursor.fetchone()
        return row[0] if row else None


@pyscript_executor  # noqa: F821
def _lookup_context_sync(entity_id: str) -> dict[str, str]:
    """Query recorder for the most recent context columns of an entity.

    Returns dict with context_id, user_id, parent_id (hex strings or empty).
    """
    import binascii as _binascii

    result = {"context_id": "", "user_id": "", "parent_id": ""}
    meta_id = _resolve_metadata_id(entity_id)
    if meta_id is None:
        return result

    try:
        with closing(_get_recorder_conn()) as conn:
            row = conn.execute(
                "SELECT context_id_bin, context_user_id_bin, context_parent_id_bin "
                "FROM states WHERE metadata_id = ? "
                "ORDER BY last_updated_ts DESC LIMIT 1",
                (meta_id,),
            ).fetchone()
            if row is None:
                return result

            for col, key in [
                ("context_id_bin", "context_id"),
                ("context_user_id_bin", "user_id"),
                ("context_parent_id_bin", "parent_id"),
            ]:
                raw = row[col]
                if raw and isinstance(raw, (bytes, bytearray)) and len(raw) > 0:
                    result[key] = _binascii.hexlify(raw).decode("ascii")
    except Exception as exc:
        # Recorder may be temporarily locked or schema mismatch
        result["_error"] = f"recorder lookup failed for {entity_id}: {exc}"

    return result


# ─── Source classification ───────────────────────────────────────────────────

def _classify_source(
    context: dict[str, str],
) -> tuple[str, str]:
    """Classify who/what caused the toggle change.

    Returns (source, source_detail).
    """
    uid = context.get("user_id", "")
    pid = context.get("parent_id", "")

    if uid:
        # UI-initiated change — resolve to person slug
        _refresh_user_map()
        person = _user_map.get(uid, "")
        if person:
            return ("user", person)
        return ("user", f"uid:{uid[:8]}")

    if pid:
        return ("automation", f"ctx:{pid[:12]}")

    return ("pyscript_or_internal", "")


# ─── Audit record writer (AP-55 compliant) ──────────────────────────────────

@pyscript_executor  # noqa: F821
def _write_audit_row(
    entity_id: str,
    old_state: str,
    new_state: str,
    source: str,
    source_detail: str,
    timestamp_iso: str,
    context_id: str,
    user_id: str,
    parent_id: str,
) -> bool:
    """Insert a row into toggle_audit table in memory.db."""
    import sqlite3 as _sqlite3

    try:
        conn = _sqlite3.connect(DB_PATH, timeout=5)
        conn.execute("PRAGMA busy_timeout=3000;")
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute(
            """
            INSERT INTO toggle_audit(
                entity_id, old_state, new_state, source, source_detail,
                timestamp, context_id, user_id, parent_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entity_id, old_state, new_state, source, source_detail,
                timestamp_iso, context_id, user_id, parent_id,
            ),
        )
        conn.commit()
        conn.close()
        return True, None
    except Exception as exc:
        return False, f"DB write failed: {exc}"


# ─── Retention purge (AP-55 compliant) ───────────────────────────────────────

@pyscript_executor  # noqa: F821
def _purge_old_audit_rows(cutoff_iso: str) -> int:
    """Delete audit rows older than cutoff. Returns rows deleted."""
    import sqlite3 as _sqlite3

    try:
        conn = _sqlite3.connect(DB_PATH, timeout=5)
        conn.execute("PRAGMA busy_timeout=3000;")
        cur = conn.execute(
            "DELETE FROM toggle_audit WHERE timestamp < ?",
            (cutoff_iso,),
        )
        deleted = cur.rowcount
        conn.commit()
        conn.close()
        return deleted, None
    except Exception as exc:
        return 0, f"purge failed: {exc}"


# ─── Query executor (AP-55 compliant) ───────────────────────────────────────

@pyscript_executor  # noqa: F821
def _query_audit_rows(
    entity_id: str,
    source: str,
    cutoff_iso: str,
    limit: int,
) -> list[dict]:
    """Query toggle_audit table with optional filters."""
    import sqlite3 as _sqlite3

    clauses = ["timestamp > ?"]
    params: list = [cutoff_iso]
    if entity_id:
        clauses.append("entity_id = ?")
        params.append(entity_id)
    if source:
        clauses.append("source = ?")
        params.append(source)
    where = " AND ".join(clauses)

    try:
        conn = _sqlite3.connect(DB_PATH, timeout=5)
        conn.execute("PRAGMA busy_timeout=3000;")
        conn.row_factory = _sqlite3.Row
        rows = conn.execute(
            f"SELECT * FROM toggle_audit WHERE {where} "  # noqa: S608
            "ORDER BY timestamp DESC LIMIT ?",
            params + [limit],
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as exc:
        log.warning("toggle_audit: query failed: %s", exc)  # noqa: F821
        return []


# ─── Core toggle handler ────────────────────────────────────────────────────

_last_sensor_attrs: dict[str, Any] = {}


async def _on_toggle_change(**kwargs):
    """Handle ai_* toggle state change — record audit row with attribution."""
    if not _is_enabled():
        return

    entity_id = kwargs.get("var_name", "") or ""
    new_state = str(kwargs.get("value", "") or "")
    old_state = str(kwargs.get("old_value", "") or "")

    # Skip boot noise and same-state
    if new_state in SKIP_STATES or old_state in SKIP_STATES:
        return
    if new_state == old_state:
        return

    now_iso = datetime.now(UTC).isoformat()

    # Try to get context directly from pyscript kwargs (avoids recorder timing)
    ctx = kwargs.get("context", None)
    context = {"context_id": "", "user_id": "", "parent_id": ""}
    if ctx is not None:
        # Pyscript passes context as a Context object with .id, .user_id, .parent_id
        context["context_id"] = str(getattr(ctx, "id", "") or "")
        context["user_id"] = str(getattr(ctx, "user_id", "") or "")
        context["parent_id"] = str(getattr(ctx, "parent_id", "") or "")
        log.debug(  # noqa: F821
            "toggle_audit: context from kwargs — id=%s user=%s parent=%s",
            context["context_id"][:12], context["user_id"][:8] if context["user_id"] else "",
            context["parent_id"][:12] if context["parent_id"] else "",
        )

    # Fall back to recorder lookup if kwargs didn't have context
    if not context.get("user_id") and not context.get("parent_id"):
        await asyncio.sleep(RECORDER_SETTLE_DELAY)
        context = await _lookup_context_sync(entity_id)
        if context.get("_error"):
            log.debug("toggle_audit: %s", context["_error"])  # noqa: F821

        # Retry once if recorder was slow
        if not context.get("user_id") and not context.get("parent_id"):
            await asyncio.sleep(RECORDER_RETRY_DELAY)
            context = await _lookup_context_sync(entity_id)
            if context.get("_error"):
                log.debug("toggle_audit: %s (retry)", context["_error"])  # noqa: F821

    source, source_detail = _classify_source(context)

    log.debug(  # noqa: F821
        "toggle_audit: %s %s→%s source=%s detail=%s",
        entity_id, old_state, new_state, source, source_detail,
    )

    # Write to SQLite
    _wrote, _write_err = await _write_audit_row(
        entity_id, old_state, new_state, source, source_detail,
        now_iso, context.get("context_id", ""),
        context.get("user_id", ""), context.get("parent_id", ""),
    )
    if _write_err:
        log.warning("toggle_audit: %s", _write_err)  # noqa: F821

    # Write to HA logbook for Activity panel visibility
    short_name = entity_id.replace("input_boolean.", "")
    try:
        await service.call(  # noqa: F821
            "logbook", "log",
            name="Toggle Audit",
            message=f"{short_name} → {new_state} (by {source}: {source_detail or 'n/a'})",
            entity_id=entity_id,
        )
    except Exception:
        pass  # logbook write is best-effort

    # Fire event for downstream consumers
    event.fire(  # noqa: F821
        "ai_toggle_audited",
        entity_id=entity_id,
        old_state=old_state,
        new_state=new_state,
        source=source,
        source_detail=source_detail,
    )

    # Update sensor with last toggle info
    global _last_sensor_attrs
    _last_sensor_attrs = {
        "last_entity": entity_id,
        "last_from": old_state,
        "last_to": new_state,
        "last_source": source,
        "last_detail": source_detail,
        "last_at": now_iso,
    }
    _set_result("monitoring", **_last_sensor_attrs)


# ─── Trigger factory (pattern: duck_manager.py:755-760) ─────────────────────

def _toggle_trigger_factory(entity_id):
    """Create a @state_trigger for a single input_boolean entity."""
    @state_trigger(entity_id)  # noqa: F821
    async def _trig(**kwargs):
        await _on_toggle_change(**kwargs)
    return _trig


# ─── Startup ─────────────────────────────────────────────────────────────────

_registered_triggers: list = []


@time_trigger("startup")  # noqa: F821
async def toggle_audit_startup():
    """Discover ai_* booleans and register dynamic triggers."""
    global _registered_triggers
    _ensure_result_entity_name(force=True)
    _set_result("idle", op="startup")
    log.info("toggle_audit: initializing, first scan in 30 s")  # noqa: F821

    task.sleep(30)  # noqa: F821

    # Discover all input_boolean.ai_* entities
    all_booleans = []
    try:
        for eid in state.names(domain="input_boolean"):  # noqa: F821
            short = eid.replace("input_boolean.", "")
            if short.startswith("ai_"):
                all_booleans.append(eid)
    except Exception as exc:
        log.error("toggle_audit: entity discovery failed: %s", exc)  # noqa: F821
        _set_result("error", error=str(exc)[:200])
        return

    # Register trigger factory for each
    _registered_triggers = [_toggle_trigger_factory(eid) for eid in all_booleans]

    # Build initial user map
    _refresh_user_map()

    log.info(  # noqa: F821
        "toggle_audit: monitoring %d entities (%d person mappings)",
        len(all_booleans), len(_user_map),
    )
    _set_result(
        "monitoring",
        monitored_count=len(all_booleans),
        person_mappings=len(_user_map),
        op="startup_complete",
    )


# ─── Retention purge cron ────────────────────────────────────────────────────

@time_trigger("cron(30 3 * * *)")  # noqa: F821
async def toggle_audit_purge():
    """Daily retention purge of old audit rows."""
    if not _is_enabled():
        return

    try:
        days = float(state.get(RETENTION_HELPER) or "90")  # noqa: F821
    except Exception:
        days = 90.0

    cutoff = datetime.now(UTC) - timedelta(days=days)
    deleted, purge_err = await _purge_old_audit_rows(cutoff.isoformat())

    if purge_err:
        log.warning("toggle_audit: %s", purge_err)  # noqa: F821
    elif deleted > 0:
        log.info("toggle_audit: purged %d rows older than %d days", deleted, int(days))  # noqa: F821


# ─── Query service ───────────────────────────────────────────────────────────

@service(supports_response="only")  # noqa: F821
async def toggle_audit_query(
    entity_id: str = "",
    source: str = "",
    hours_back: int = 24,
    limit: int = 50,
):
    """
    yaml
    name: Toggle Audit Query
    description: >-
      Query the kill switch audit trail.  Returns recent toggle changes
      with source attribution (user, automation, pyscript_or_internal).
    fields:
      entity_id:
        description: Filter by entity ID (e.g. input_boolean.ai_reactive_banter_enabled)
        example: ""
      source:
        description: Filter by source type (user, automation, pyscript_or_internal)
        example: ""
      hours_back:
        description: How many hours back to search (default 24)
        example: 24
      limit:
        description: Maximum results (default 50)
        example: 50
    """
    hours_back = min(max(int(hours_back or 24), 1), 8760)
    limit = min(max(int(limit or 50), 1), 200)
    cutoff = datetime.now(UTC) - timedelta(hours=hours_back)
    rows = await _query_audit_rows(entity_id, source, cutoff.isoformat(), limit)
    return {"count": len(rows), "rows": rows}
