"""
Automation Trace Watchdog — surfaces silent automation failures.

Reads /config/.storage/trace.saved_traces and scans for automations that
crashed in their `variables:` / `conditions:` / early-actions blocks with
`state: stopped` + non-empty `error`. These crashes produce ZERO logbook
entries and no history trail — the only diagnostic is the trace JSON.

AP-82 motivation (2026-04-13): automation.alarm silently missed 4 wake-ups
across 2 weeks because `state_attr('sensor.occupancy_mode', 'persons') | first`
crashed on a missing attribute. Trace file had the evidence the whole time.

Output:
  sensor.ai_automation_trace_errors
    state: count of errors in window
    attributes:
      window_hours: current lookback window
      recent_errors: [{entity, alias, error, started_at, last_step, had_trigger}, ...]
      scanned_at: ISO timestamp
      trace_count: total traces scanned
      scan_error: present only if read failed

Helpers:
  input_boolean.ai_trace_watchdog_enabled — kill switch
  input_number.ai_trace_watchdog_window_hours — lookback (default 24)

Services:
  pyscript.automation_trace_watchdog_scan — manual scan

Triggers:
  startup + every 10 minutes
"""

import json
import os
from datetime import datetime, timezone

TRACE_FILE = "/config/.storage/trace.saved_traces"
SENSOR_ID = "sensor.ai_automation_trace_errors"
FRIENDLY = "AI Automation Trace Errors"
MAX_RECENT = 25
DEFAULT_WINDOW_HOURS = 168  # 7d — wider default because HA only flushes
                            # saved_traces to disk on shutdown, so the file
                            # often lags by several days. See mtime attribute
                            # for how stale the data source currently is.


@pyscript_executor
def _read_trace_file_sync():
    """Read and parse trace.saved_traces. Returns (data_dict, mtime_epoch).

    On failure returns ({'__error__': str}, 0.0).
    """
    try:
        if not os.path.exists(TRACE_FILE):
            return ({"__error__": "trace file not found"}, 0.0)
        mtime = os.path.getmtime(TRACE_FILE)
        with open(TRACE_FILE, "r", encoding="utf-8") as f:
            return (json.load(f), mtime)
    except Exception as exc:
        return ({"__error__": f"{type(exc).__name__}: {exc}"}, 0.0)


@pyscript_compile
def _parse_iso(ts_str):
    """Parse ISO timestamp to epoch float. Returns 0.0 on failure."""
    if not ts_str:
        return 0.0
    try:
        # Python 3.11+ handles 'Z' natively; for safety swap it out.
        s = ts_str.replace("Z", "+00:00") if ts_str.endswith("Z") else ts_str
        return datetime.fromisoformat(s).timestamp()
    except Exception:
        return 0.0


@pyscript_compile
def _extract_errors(raw, window_hours, now_epoch):
    """Walk the trace file structure and collect error entries in window.

    Structure: {version, minor_version, key, data: {entity_id: [{short_dict, extended_dict}, ...]}}

    Returns (errors_list, total_traces_scanned).
    """
    if not isinstance(raw, dict):
        return [], 0
    data = raw.get("data") or {}
    if not isinstance(data, dict):
        return [], 0

    cutoff = now_epoch - (float(window_hours) * 3600.0)
    errors = []
    total = 0

    for entity_id, wrapper_list in data.items():
        if not isinstance(wrapper_list, list):
            continue
        for wrapper in wrapper_list:
            if not isinstance(wrapper, dict):
                continue
            short = wrapper.get("short_dict") or {}
            if not isinstance(short, dict):
                continue
            total += 1

            state_val = short.get("state")
            error_val = short.get("error")
            # Only care about crashes — condition-gated stops have no error.
            if state_val != "stopped" or not error_val:
                continue

            ts_obj = short.get("timestamp") or {}
            started = ts_obj.get("start", "") if isinstance(ts_obj, dict) else ""
            started_epoch = _parse_iso(started)
            if started_epoch < cutoff:
                continue

            errors.append({
                "entity": entity_id,
                "error": str(error_val)[:250],
                "started_at": started,
                "started_epoch": started_epoch,
                "last_step": short.get("last_step"),
                "had_trigger": short.get("trigger") is not None,
                "run_id": short.get("run_id", ""),
            })

    # Newest first, cap.
    errors.sort(key=lambda r: r["started_epoch"], reverse=True)
    return errors[:MAX_RECENT], total


def _build_alias_index():
    """Scan all live automation entities and build {numeric_id: (entity_id, alias)}.

    Trace keys use the format `automation.<id_or_slug>` where `<id_or_slug>`
    may be the automation's numeric ID (from automations.yaml `id:`) or its
    object slug. Live automation entities expose the numeric ID via their
    `id` attribute and a human-readable `friendly_name`. We index by both
    numeric ID and by entity_id so trace lookups resolve either way.
    """
    index = {}
    try:
        for entity_id in state.names("automation"):  # noqa: F821
            try:
                attrs = state.getattr(entity_id)  # noqa: F821
            except Exception:
                continue
            if not isinstance(attrs, dict):
                continue
            alias = attrs.get("friendly_name") or entity_id
            numeric_id = attrs.get("id")
            index[entity_id] = (entity_id, alias)
            if numeric_id:
                index[f"automation.{numeric_id}"] = (entity_id, alias)
    except Exception:
        pass
    return index


def _enrich_with_alias(errors):
    """Add friendly alias + live entity_id from HA state registry for each error."""
    index = _build_alias_index()
    for e in errors:
        trace_key = e["entity"]
        live_entity, alias = index.get(trace_key, (trace_key, trace_key))
        e["alias"] = alias
        e["live_entity"] = live_entity
        # Drop internal epoch field from final output
        e.pop("started_epoch", None)
    return errors


def _get_window_hours():
    """Read input_number helper with fallback to default."""
    try:
        raw = state.get("input_number.ai_trace_watchdog_window_hours")  # noqa: F821
        if raw in (None, "unknown", "unavailable", ""):
            return DEFAULT_WINDOW_HOURS
        return max(1, int(float(raw)))
    except Exception:
        return DEFAULT_WINDOW_HOURS


def _enabled():
    """Check kill switch. Default ON if helper missing."""
    try:
        val = state.get("input_boolean.ai_trace_watchdog_enabled")  # noqa: F821
        if val in (None, "unknown", "unavailable", ""):
            return True
        return val == "on"
    except Exception:
        return True


async def _scan_and_publish():
    """Core routine: read trace file, extract errors, publish sensor."""
    now_iso = datetime.now(timezone.utc).isoformat()

    if not _enabled():
        state.set(  # noqa: F821
            SENSOR_ID, "disabled",
            new_attributes={
                "icon": "mdi:shield-off-outline",
                "friendly_name": FRIENDLY,
                "scanned_at": now_iso,
                "recent_errors": [],
            },
        )
        return

    window = _get_window_hours()
    raw, mtime = await _read_trace_file_sync()

    # Translate mtime to ISO + age-in-hours for user visibility.
    trace_file_mtime_iso = ""
    trace_file_age_hours = None
    if mtime > 0:
        trace_file_mtime_iso = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
        trace_file_age_hours = round((datetime.now(timezone.utc).timestamp() - mtime) / 3600.0, 1)

    if isinstance(raw, dict) and "__error__" in raw:
        state.set(  # noqa: F821
            SENSOR_ID, "unavailable",
            new_attributes={
                "icon": "mdi:alert",
                "friendly_name": FRIENDLY,
                "scan_error": raw["__error__"],
                "scanned_at": now_iso,
                "window_hours": window,
                "recent_errors": [],
            },
        )
        log.warning(  # noqa: F821
            f"automation_trace_watchdog: failed to read trace file: {raw['__error__']}"
        )
        return

    now_epoch = datetime.now(timezone.utc).timestamp()
    errors, total_scanned = _extract_errors(raw, window, now_epoch)
    errors = _enrich_with_alias(errors)

    # Group by entity for summary (unique automations affected).
    affected = {}
    for e in errors:
        key = e["alias"] or e["entity"]
        affected[key] = affected.get(key, 0) + 1

    state.set(  # noqa: F821
        SENSOR_ID, str(len(errors)),
        new_attributes={
            "icon": "mdi:alert-circle" if errors else "mdi:check-circle-outline",
            "friendly_name": FRIENDLY,
            "unit_of_measurement": "errors",
            "window_hours": window,
            "trace_count": total_scanned,
            "trace_file_mtime": trace_file_mtime_iso,
            "trace_file_age_hours": trace_file_age_hours,
            "scanned_at": now_iso,
            "affected_automations": affected,
            "recent_errors": errors,
        },
    )

    if errors:
        log.warning(  # noqa: F821
            f"automation_trace_watchdog: {len(errors)} silent failures in last "
            f"{window}h (most recent: {errors[0]['alias']} — {errors[0]['error'][:80]})"
        )


@time_trigger("startup", "cron(*/10 * * * *)")
async def automation_trace_watchdog_periodic():
    """Scan on startup and every 10 minutes."""
    await _scan_and_publish()


@service
async def automation_trace_watchdog_scan():
    """Service: pyscript.automation_trace_watchdog_scan — force a scan now."""
    await _scan_and_publish()
    return {"success": True}
