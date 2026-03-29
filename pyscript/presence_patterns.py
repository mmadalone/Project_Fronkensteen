"""Task 15: Presence Pattern Extraction and Markov Prediction.

Queries the HA recorder database (read-only) for historical FP2 zone
transitions, builds Markov chain frequency tables by time-of-day and
day-type, and stores patterns in L2 memory. Provides a prediction
service that returns probability distributions for next-zone given
current zone, time, and day type. Rebuilds daily at 04:00.
"""
import asyncio
import json
import sqlite3
import statistics
import time
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any

from shared_utils import build_result_entity_name, load_entity_config, reload_entity_config

# =============================================================================
# Presence Pattern Extraction — Task 15 of Voice Context Architecture
# =============================================================================
# Queries HA recorder for historical FP2 zone transitions, builds Markov chain
# frequency tables, stores patterns in L2 memory for prediction.
#
# Services:
#   pyscript.presence_extract_transitions
#     Extract zone transitions from recorder DB, build frequency tables.
#
#   pyscript.presence_predict_next
#     Given current zone + time + day_type → probability distribution.
#
#   pyscript.presence_rebuild_patterns
#     Full rebuild: delete old patterns, re-extract, re-store.
#
# State trigger:
#   FP2 binary sensors → incremental update on zone transitions.
#
# Time trigger:
#   Daily rebuild at 04:00 AM.
#
# Key design:
#   - Recorder DB access is READ-ONLY (sqlite3 URI mode=ro)
#   - All DB queries via asyncio.to_thread (never block event loop)
#   - Frequency tables live in L2 memory, local cache for fast prediction
#   - Incremental updates from state triggers, full rebuild daily
#   - ~200 LOC core logic (extraction + tables + prediction)
#   - Markov chains, not ML — simple, fast, deterministic
#
# Dependencies:
#   - HA recorder database (/config/home-assistant_v2.db) — READ ONLY
#   - pyscript/memory.py (L2: memory_get, memory_set, memory_search, memory_forget)
#   - packages/ai_presence_patterns.yaml (helpers)
#   - packages/ai_test_harness.yaml (test mode toggle)
#
# Deployed: 2026-03-02
# =============================================================================

RECORDER_DB = Path("/config/home-assistant_v2.db")
RESULT_ENTITY = "sensor.ai_presence_pattern_status"

_DEFAULT_FP2_ENTITIES = {
    "binary_sensor.fp2_presence_sensor_workshop": "workshop",
    "binary_sensor.fp2_presence_sensor_living_room": "living_room",
    "binary_sensor.fp2_presence_sensor_main_room": "main_room",
    "binary_sensor.fp2_presence_sensor_kitchen": "kitchen",
    "binary_sensor.fp2_presence_sensor_bed": "bed",
    "binary_sensor.fp2_presence_sensor_lobby": "lobby",
    "binary_sensor.fp2_presence_sensor_bathroom": "bathroom",
    "binary_sensor.fp2_presence_sensor_shower": "shower",
}


def _get_fp2_entities() -> dict:
    cfg = load_entity_config()
    return cfg.get("fp2_zones") or _DEFAULT_FP2_ENTITIES


def _get_zone_names() -> list:
    return sorted(_get_fp2_entities().values())

_DEFAULT_ZONE_NAMES = sorted(_DEFAULT_FP2_ENTITIES.values())

# TRANSITION_WINDOW_SEC — now read from input_number.ai_presence_transition_window
MIN_DWELL_SECONDS = 30       # ignore sub-30s presence (FP2 flicker at zone boundaries)
CONFIDENCE_HIGH = 50         # sample count for "high" confidence
CONFIDENCE_MEDIUM = 10       # sample count for "medium" confidence
L2_EXPIRATION_DAYS = 365     # pattern entries persist ~1 year (refreshed daily)

# ── Module-Level State ───────────────────────────────────────────────────────

_local_trans_cache: dict[tuple[str, str, str], dict[str, int]] = {}
_local_dwell_cache: dict[tuple[str, str, str], dict[str, float]] = {}
_zone_state: dict[str, str] = {}     # zone → 'on'/'off' for incremental tracking
_zone_on_time: dict[str, float] = {} # zone → unix ts when last turned ON
_recent_zone_off: dict[str, float] = {}  # zone → unix ts when last turned OFF
_zone_debounce_ts: dict[str, float] = {}  # zone → last accepted trigger time
ZONE_DEBOUNCE_SEC = 10.0  # suppress FP2 flapping within this window
_rebuild_in_progress = False
_fp2_triggers = []             # factory-created trigger references (keep alive)
result_entity_name: dict[str, str] = {}


# ── Entity Name Helpers (pattern from notification_dedup.py) ─────────────────

def _ensure_result_entity_name(force: bool = False) -> None:
    global result_entity_name
    if force or not result_entity_name:
        result_entity_name = build_result_entity_name(RESULT_ENTITY)


def _set_result(state_value: str = "ok", **attrs: Any) -> None:
    _ensure_result_entity_name()
    attrs.update(result_entity_name)
    state.set(RESULT_ENTITY, value=state_value, new_attributes=attrs)  # noqa: F821


# ── Pure-Python Sync Helpers ─────────────────────────────────────────────────

@pyscript_compile  # noqa: F821
def _get_time_bucket(hour: int) -> str:
    """Map hour (0-23) to time bucket matching dispatcher's time eras."""
    if hour < 6:
        return "late_night"
    if hour < 12:
        return "morning"
    if hour < 18:
        return "afternoon"
    return "evening"


@pyscript_compile  # noqa: F821
def _get_day_type(weekday: int) -> str:
    """Map weekday (0=Mon..6=Sun) to day_type."""
    return "weekend" if weekday >= 5 else "weekday"


@pyscript_compile  # noqa: F821
def _get_recorder_conn() -> sqlite3.Connection:
    """Open the HA recorder DB in read-only mode."""
    conn = sqlite3.connect(f"file:{RECORDER_DB}?mode=ro", uri=True)
    conn.execute("PRAGMA busy_timeout=5000;")
    return conn


@pyscript_compile  # noqa: F821
def _resolve_metadata_ids(entity_map: dict = None) -> dict[int, str]:
    """Get metadata_id → zone_name mapping from recorder states_meta table."""
    if entity_map is None:
        entity_map = dict(_DEFAULT_FP2_ENTITIES)
    entity_list = list(entity_map.keys())
    placeholders = ",".join("?" * len(entity_list))
    with closing(_get_recorder_conn()) as conn:
        cursor = conn.execute(
            f"SELECT metadata_id, entity_id FROM states_meta "
            f"WHERE entity_id IN ({placeholders})",
            entity_list,
        )
        return {row[0]: entity_map[row[1]] for row in cursor}


@pyscript_executor  # noqa: F821
def _extract_data_sync(lookback_days: int, transition_window_sec: int = 300, entity_map: dict = None) -> dict[str, Any]:
    """Extract zone transitions and dwell times from recorder DB.

    Processes all FP2 state changes chronologically, detects:
    - Transitions: zone_A OFF → zone_B ON within 5-min window
    - Dwell times: duration of zone ON→OFF per zone

    Returns dict with: transitions, dwells, zones_seen, total_states, earliest_ts.
    """
    if entity_map is None:
        entity_map = dict(_DEFAULT_FP2_ENTITIES)
    meta_map = _resolve_metadata_ids(entity_map)
    if not meta_map:
        return {
            "transitions": [], "dwells": [], "zones_seen": [],
            "total_states": 0, "earliest_ts": 0,
        }

    cutoff_ts = time.time() - (lookback_days * 86400)
    meta_ids = list(meta_map.keys())
    placeholders = ",".join("?" * len(meta_ids))

    # Retry once on OperationalError (transient lock)
    rows = []
    for attempt in range(2):
        try:
            with closing(_get_recorder_conn()) as conn:
                cursor = conn.execute(
                    f"SELECT metadata_id, state, last_updated_ts "
                    f"FROM states "
                    f"WHERE metadata_id IN ({placeholders}) "
                    f"  AND state IN ('on', 'off') "
                    f"  AND last_updated_ts > ? "
                    f"ORDER BY last_updated_ts",
                    [*meta_ids, cutoff_ts],
                )
                rows = cursor.fetchall()
            break
        except sqlite3.OperationalError:
            if attempt == 0:
                time.sleep(1)

    if not rows:
        return {
            "transitions": [], "dwells": [], "zones_seen": [],
            "total_states": 0, "earliest_ts": 0,
        }

    # ── Chronological scan: detect transitions and dwell times ───────────
    transitions: list[tuple[str, str, float]] = []
    dwells: list[tuple[str, float, float]] = []
    zones_seen: set[str] = set()
    prev_state: dict[str, str] = {}   # zone → last known state
    zone_on: dict[str, float] = {}    # zone → timestamp turned ON
    recent_off: dict[str, float] = {} # zone → timestamp turned OFF
    earliest_ts = rows[0][2] if rows[0][2] else 0

    for meta_id, state_val, ts in rows:
        if ts is None or meta_id not in meta_map:
            continue
        zone = meta_map[meta_id]
        zones_seen.add(zone)

        # Skip duplicate states (attribute-only updates, not real transitions)
        if prev_state.get(zone) == state_val:
            continue
        prev_state[zone] = state_val

        if state_val == "on":
            zone_on[zone] = ts
            # Find source zone: most recent OFF from a DIFFERENT zone within window
            best_from = None
            best_ts = 0.0
            for off_zone, off_ts in recent_off.items():
                if off_zone != zone and (ts - off_ts) < transition_window_sec:
                    if off_ts > best_ts:
                        best_from = off_zone
                        best_ts = off_ts
            if best_from:
                # Validate source zone had meaningful dwell time (not flicker)
                dwell_from = best_ts - zone_on.get(best_from, best_ts)
                if dwell_from >= MIN_DWELL_SECONDS:
                    transitions.append((best_from, zone, ts))

        elif state_val == "off":
            # Record dwell time: how long was this zone ON?
            if zone in zone_on:
                dwell = ts - zone_on[zone]
                if dwell >= MIN_DWELL_SECONDS:
                    dwells.append((zone, dwell, zone_on[zone]))
            recent_off[zone] = ts

    return {
        "transitions": transitions,
        "dwells": dwells,
        "zones_seen": sorted(zones_seen),
        "total_states": len(rows),
        "earliest_ts": earliest_ts,
    }


@pyscript_compile  # noqa: F821
def _build_tables(
    transitions: list[tuple[str, str, float]],
    dwells: list[tuple[str, float, float]],
) -> tuple[dict, dict]:
    """Build frequency and dwell tables from raw extraction data.

    Returns:
        (trans_tables, dwell_lists)
        trans_tables: {(from_zone, time_bucket, day_type): {to_zone: count}}
        dwell_lists:  {(zone, time_bucket, day_type): [duration_minutes]}
    """
    trans_tables: dict[tuple[str, str, str], dict[str, int]] = {}
    dwell_lists: dict[tuple[str, str, str], list[float]] = {}

    for from_zone, to_zone, ts in transitions:
        dt = datetime.fromtimestamp(ts)
        key = (from_zone, _get_time_bucket(dt.hour), _get_day_type(dt.weekday()))
        if key not in trans_tables:
            trans_tables[key] = {}
        trans_tables[key][to_zone] = trans_tables[key].get(to_zone, 0) + 1

    for zone, duration_sec, on_ts in dwells:
        dt = datetime.fromtimestamp(on_ts)
        key = (zone, _get_time_bucket(dt.hour), _get_day_type(dt.weekday()))
        if key not in dwell_lists:
            dwell_lists[key] = []
        dwell_lists[key].append(duration_sec / 60.0)

    return trans_tables, dwell_lists


@pyscript_compile  # noqa: F821
def _compute_dwell_stats(durations: list[float]) -> dict[str, float]:
    """Compute dwell stats from list of durations in minutes."""
    if not durations:
        return {"avg_minutes": 0, "median_minutes": 0, "min_minutes": 0, "max_minutes": 0}
    return {
        "avg_minutes": round(sum(durations) / len(durations), 1),
        "median_minutes": round(statistics.median(durations), 1),
        "min_minutes": round(min(durations), 1),
        "max_minutes": round(max(durations), 1),
    }


@pyscript_compile  # noqa: F821
def _filter_by_confidence(
    counts: dict[str, int], min_confidence: float,
) -> dict[str, int]:
    """Remove transitions below min_confidence probability threshold."""
    total = sum(counts.values())
    if total == 0:
        return {}
    return {z: c for z, c in counts.items() if c / total >= min_confidence}


@pyscript_compile  # noqa: F821
def _parse_pattern_key(key: str, zone_names: list = None) -> tuple[str, str, str, str] | None:
    """Parse normalized L2 key → (type, zone, time_bucket, day_type) or None.

    After memory.py normalization, key format is:
      pattern_transition_{zone}_{time_bucket}_{day_type}
      pattern_dwell_{zone}_{time_bucket}_{day_type}

    Parses from the end to handle zone names containing underscores.
    zone_names must be passed by callers (pyscript_compile cannot call state.get).
    """
    if zone_names is None:
        zone_names = _DEFAULT_ZONE_NAMES
    zone_set = set(zone_names)
    for prefix, ptype in (("pattern_transition_", "transition"), ("pattern_dwell_", "dwell")):
        if not key.startswith(prefix):
            continue
        rest = key[len(prefix):]
        # Parse day_type from end
        day_type = None
        for dt in ("weekday", "weekend"):
            if rest.endswith("_" + dt):
                day_type = dt
                rest = rest[: -(len(dt) + 1)]
                break
        if not day_type:
            return None
        # Parse time_bucket from end
        time_bucket = None
        for tb in ("late_night", "morning", "afternoon", "evening"):
            if rest.endswith("_" + tb):
                time_bucket = tb
                rest = rest[: -(len(tb) + 1)]
                break
        if not time_bucket:
            return None
        # Remaining is zone name — validate against known zones
        if rest in zone_set:
            return (ptype, rest, time_bucket, day_type)
        return None
    return None


# ── L2 Memory Helpers ────────────────────────────────────────────────────────

async def _l2_get(key: str) -> dict | None:
    """Exact-key lookup in L2 via memory_get."""
    try:
        result = pyscript.memory_get(key=key)  # noqa: F821
        return await result
    except Exception as exc:
        log.warning(f"presence: L2 get failed key={key}: {exc}")  # noqa: F821
        return None


async def _l2_set(
    key: str, value: str, tags: str,
    scope: str = "household", expiration_days: int = L2_EXPIRATION_DAYS,
) -> bool:
    """Write entry to L2 via memory_set. Returns True on success."""
    try:
        result = pyscript.memory_set(  # noqa: F821
            key=key, value=value, scope=scope,
            expiration_days=expiration_days, tags=tags, force_new=True,
        )
        resp = await result
        return resp is not None and resp.get("status") == "ok"
    except Exception as exc:
        log.warning(f"presence: L2 set failed key={key}: {exc}")  # noqa: F821
        return False


async def _l2_forget(key: str) -> bool:
    """Delete entry from L2 via memory_forget."""
    try:
        result = pyscript.memory_forget(key=key)  # noqa: F821
        resp = await result
        return resp is not None and resp.get("status") == "ok"
    except Exception as exc:
        log.warning(f"presence: L2 forget failed key={key}: {exc}")  # noqa: F821
        return False


async def _l2_search(query: str, limit: int = 200) -> list[dict[str, Any]]:
    """Search L2 via memory_search. Returns empty list on failure."""
    try:
        result = pyscript.memory_search(query=query, limit=limit)  # noqa: F821
        resp = await result
        if resp and resp.get("status") == "ok":
            return resp.get("results", [])
    except Exception as exc:
        log.warning(f"presence: L2 search failed query={query}: {exc}")  # noqa: F821
    return []


# ── Cache Management ─────────────────────────────────────────────────────────

async def _load_cache_from_l2() -> int:
    """Load pattern cache from L2 memory. Returns number of entries loaded."""
    global _local_trans_cache, _local_dwell_cache
    loaded = 0

    zone_names = _get_zone_names()
    for query_tag in ("pattern transition", "pattern dwell"):
        results = await _l2_search(query_tag, limit=200)
        for entry in results:
            key = entry.get("key", "")
            value = entry.get("value", "")
            parsed = _parse_pattern_key(key, zone_names)
            if not parsed or not value:
                continue
            ptype, zone, bucket, day = parsed
            try:
                data = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(data, dict):
                continue
            if ptype == "transition":
                _local_trans_cache[(zone, bucket, day)] = data
                loaded += 1
            elif ptype == "dwell":
                _local_dwell_cache[(zone, bucket, day)] = data
                loaded += 1

    return loaded


async def _delete_old_patterns(test_mode: bool) -> int:
    """Delete all pattern entries from L2. Returns count deleted."""
    deleted = 0
    zone_names = _get_zone_names()
    results = await _l2_search("pattern", limit=300)
    for entry in results:
        key = entry.get("key", "")
        if _parse_pattern_key(key, zone_names) is not None:
            if test_mode:
                log.info(f"presence [TEST]: WOULD DELETE L2 key={key}")  # noqa: F821
            else:
                if await _l2_forget(key):
                    deleted += 1
    return deleted


async def _store_all_patterns(
    trans_tables: dict[tuple[str, str, str], dict[str, int]],
    dwell_lists: dict[tuple[str, str, str], list[float]],
    min_confidence: float, min_samples: int, test_mode: bool,
) -> int:
    """Store frequency tables and dwell stats to L2. Returns entries stored."""
    stored = 0

    for (zone, bucket, day), counts in trans_tables.items():
        total = sum(counts.values())
        if total < min_samples:
            continue
        filtered = _filter_by_confidence(counts, min_confidence)
        if not filtered:
            continue
        key = f"pattern:transition:{zone}:{bucket}:{day}"
        value = json.dumps(filtered, separators=(",", ":"))
        tags = f"pattern transition {zone} {bucket} {day}"
        if test_mode:
            log.info(f"presence [TEST]: WOULD STORE {key} = {value}")  # noqa: F821
        else:
            if await _l2_set(key, value, tags):
                stored += 1

    for (zone, bucket, day), durations in dwell_lists.items():
        if len(durations) < min_samples:
            continue
        stats = _compute_dwell_stats(durations)
        key = f"pattern:dwell:{zone}:{bucket}:{day}"
        value = json.dumps(stats, separators=(",", ":"))
        tags = f"pattern dwell {zone} {bucket} {day}"
        if test_mode:
            log.info(f"presence [TEST]: WOULD STORE {key} = {value}")  # noqa: F821
        else:
            if await _l2_set(key, value, tags):
                stored += 1

    return stored


# ── Prediction Logic ─────────────────────────────────────────────────────────

def _predict_from_cache(
    current_zone: str, time_bucket: str, day_type: str, min_samples: int,
) -> dict[str, Any]:
    """Compute prediction from local cache."""
    key = (current_zone, time_bucket, day_type)
    counts = _local_trans_cache.get(key, {})
    total = sum(counts.values())

    if total < min_samples:
        return {
            "status": "ok", "confidence": "insufficient",
            "message": f"Need more data (have {total}, need {min_samples})",
            "sample_count": total, "current_zone": current_zone,
            "time_bucket": time_bucket, "day_type": day_type,
            "predictions": [],
        }

    predictions = []
    for zone, count in sorted(counts.items(), key=lambda x: -x[1]):
        prob = round(count / total * 100)
        dwell = _local_dwell_cache.get((zone, time_bucket, day_type), {})
        predictions.append({
            "zone": zone, "probability": prob,
            "avg_eta_minutes": dwell.get("avg_minutes", 0),
        })

    confidence = (
        "high" if total >= CONFIDENCE_HIGH
        else "medium" if total >= CONFIDENCE_MEDIUM
        else "low"
    )
    return {
        "status": "ok", "current_zone": current_zone,
        "time_bucket": time_bucket, "day_type": day_type,
        "predictions": predictions, "confidence": confidence,
        "sample_count": total,
    }


async def _update_prediction_sensor(current_zone: str) -> None:
    """Update sensor.ai_predicted_next_zone_raw with current prediction."""
    if not _is_zone_enabled(current_zone):
        return
    now = datetime.now()
    bucket = _get_time_bucket(now.hour)
    day = _get_day_type(now.weekday())
    try:
        min_samples = int(float(
            state.get("input_number.ai_presence_pattern_min_samples") or 5  # noqa: F821
        ))
    except (TypeError, ValueError):
        min_samples = 5

    result = _predict_from_cache(current_zone, bucket, day, min_samples)
    if result.get("predictions"):
        top = result["predictions"][0]
        raw = json.dumps({
            "zone": top["zone"], "probability": top["probability"],
            "confidence": result["confidence"],
            "sample_count": result["sample_count"],
        })
    else:
        raw = ""
    try:
        state.set(  # noqa: F821
            "sensor.ai_predicted_next_zone_raw", raw,
            new_attributes={
                "icon": "mdi:map-marker-path",
                "friendly_name": "AI Predicted Next Zone Raw",
            },
        )
    except Exception:
        pass


# ── Settings Helpers ─────────────────────────────────────────────────────────

def _is_test_mode() -> bool:
    return str(state.get("input_boolean.ai_test_mode") or "off").lower() == "on"  # noqa: F821


def _is_enabled() -> bool:
    return str(  # noqa: F821
        state.get("input_boolean.ai_presence_patterns_enabled") or "on"  # noqa: F821
    ).lower() == "on"


def _is_zone_enabled(zone: str) -> bool:
    """Check if an FP2 zone is enabled via dashboard toggle."""
    toggle = f"input_boolean.ai_fp2_zone_{zone}_enabled"
    try:
        return str(state.get(toggle) or "on").lower() != "off"  # noqa: F821
    except NameError:
        return True  # default ON if helper missing


def _get_lookback_days() -> int:
    try:
        return int(float(
            state.get("input_number.ai_presence_pattern_lookback_days") or 30  # noqa: F821
        ))
    except (TypeError, ValueError):
        return 30


def _get_min_samples() -> int:
    try:
        return int(float(
            state.get("input_number.ai_presence_pattern_min_samples") or 5  # noqa: F821
        ))
    except (TypeError, ValueError):
        return 5


# ── Services ─────────────────────────────────────────────────────────────────

@service(supports_response="only")  # noqa: F821
async def presence_extract_transitions(
    lookback_days: int = 0,
    min_confidence: float = 0.1,
):
    """Extract zone transitions from recorder DB and store as L2 patterns.

    fields:
      lookback_days:
        description: Days of history to query (0 = use helper setting)
        example: 30
        selector:
          number:
            min: 7
            max: 90
      min_confidence:
        description: Minimum transition probability to store (0.0-1.0)
        example: 0.1
        selector:
          number:
            min: 0.0
            max: 1.0
            step: 0.05
    """
    t0 = time.monotonic()
    test_mode = _is_test_mode()
    days = lookback_days if lookback_days > 0 else _get_lookback_days()
    min_samples = _get_min_samples()

    if not RECORDER_DB.exists():
        _set_result("error", op="extract", error="recorder_db_not_found")
        return {"status": "error", "op": "extract", "error": "recorder_db_not_found"}

    log.info(  # noqa: F821
        f"presence: extracting transitions (lookback={days}d, test={test_mode})"
    )

    # Build filtered entity map (only enabled zones)
    filtered_entities = {k: v for k, v in _get_fp2_entities().items() if _is_zone_enabled(v)}

    try:
        data = _extract_data_sync(days, _get_transition_window_sec(), filtered_entities)
    except Exception as exc:
        log.error(f"presence: extraction failed: {exc}")  # noqa: F821
        _set_result("error", op="extract", error=str(exc))
        return {"status": "error", "op": "extract", "error": str(exc)}

    transitions = data["transitions"]
    dwells = data["dwells"]
    zones_seen = data["zones_seen"]
    total_states = data["total_states"]

    if test_mode:
        log.info(  # noqa: F821
            f"presence [TEST]: states={total_states} transitions={len(transitions)} "
            f"dwells={len(dwells)} zones={zones_seen}"
        )

    # Build frequency tables
    trans_tables, dwell_lists = _build_tables(transitions, dwells)

    # Store to L2
    patterns_stored = await _store_all_patterns(
        trans_tables, dwell_lists, min_confidence, min_samples, test_mode,
    )

    # Update local cache (skip in test mode — no side effects)
    if not test_mode:
        global _local_trans_cache, _local_dwell_cache
        _local_trans_cache = {
            k: _filter_by_confidence(v, min_confidence)
            for k, v in trans_tables.items()
        }
        for key, durations in dwell_lists.items():
            _local_dwell_cache[key] = _compute_dwell_stats(durations)

    elapsed_ms = round((time.monotonic() - t0) * 1000)
    _set_result(
        "ok", op="extract", transitions=len(transitions),
        patterns=patterns_stored, zones_seen=zones_seen,
        total_states=total_states, elapsed_ms=elapsed_ms,
        test_mode=test_mode,
    )

    result = {
        "status": "ok", "op": "extract",
        "transitions": len(transitions), "patterns": patterns_stored,
        "zones_seen": zones_seen, "total_states": total_states,
        "elapsed_ms": elapsed_ms,
    }
    log.info(f"presence: extract complete — {result}")  # noqa: F821
    return result


@service(supports_response="only")  # noqa: F821
async def presence_predict_next(
    current_zone: str = "",
    time_bucket: str = "",
    day_type: str = "",
):
    """Predict next zone from frequency table.

    fields:
      current_zone:
        description: Current zone name (e.g. "kitchen")
        example: "kitchen"
        selector:
          text:
      time_bucket:
        description: Time bucket (auto-detected from current time if empty)
        example: "evening"
        selector:
          select:
            options:
              - late_night
              - morning
              - afternoon
              - evening
      day_type:
        description: Day type (auto-detected from current day if empty)
        example: "weekday"
        selector:
          select:
            options:
              - weekday
              - weekend
    """
    test_mode = _is_test_mode()
    min_samples = _get_min_samples()

    if not current_zone:
        _set_result("error", op="predict", error="current_zone_required")
        return {"status": "error", "op": "predict", "error": "current_zone_required"}

    zone_set = set(_get_zone_names())
    if current_zone not in zone_set:
        _set_result("error", op="predict", error=f"unknown_zone: {current_zone}")
        return {"status": "error", "op": "predict", "error": f"unknown_zone: {current_zone}"}

    now = datetime.now()
    if not time_bucket:
        time_bucket = _get_time_bucket(now.hour)
    if not day_type:
        day_type = _get_day_type(now.weekday())

    if test_mode:
        mock = {
            "status": "ok", "current_zone": current_zone,
            "time_bucket": time_bucket, "day_type": day_type,
            "predictions": [
                {"zone": "bed", "probability": 67, "avg_eta_minutes": 12},
                {"zone": "bathroom", "probability": 20, "avg_eta_minutes": 5},
                {"zone": "living_room", "probability": 13, "avg_eta_minutes": 8},
            ],
            "confidence": "mock", "sample_count": 0, "test_mode": True,
        }
        _set_result("ok", op="predict", current_zone=current_zone,
                     time_bucket=time_bucket, day_type=day_type, confidence="mock")
        log.info(  # noqa: F821
            f"presence [TEST]: predict mock for {current_zone}/{time_bucket}/{day_type}"
        )
        return mock

    # Lazy-load cache from L2 if empty
    if not _local_trans_cache:
        loaded = await _load_cache_from_l2()
        log.info(f"presence: lazy-loaded {loaded} cache entries from L2")  # noqa: F821

    result = _predict_from_cache(current_zone, time_bucket, day_type, min_samples)
    _set_result(
        "ok", op="predict", current_zone=current_zone,
        time_bucket=time_bucket, day_type=day_type,
        confidence=result.get("confidence", "unknown"),
        sample_count=result.get("sample_count", 0),
    )
    return result


@service(supports_response="only")  # noqa: F821
async def presence_rebuild_patterns():
    """Full rebuild: delete old patterns, re-extract from recorder, re-store.

    fields: {}
    """
    global _rebuild_in_progress
    if _rebuild_in_progress:
        return {"status": "error", "op": "rebuild", "error": "rebuild_already_in_progress"}

    _rebuild_in_progress = True
    t0 = time.monotonic()
    test_mode = _is_test_mode()
    days = _get_lookback_days()
    min_samples = _get_min_samples()

    log.info(  # noqa: F821
        f"presence: starting full rebuild (lookback={days}d, test={test_mode})"
    )

    try:
        # Step 1: Delete old patterns from L2
        deleted = await _delete_old_patterns(test_mode)
        log.info(f"presence: deleted {deleted} old pattern entries")  # noqa: F821

        # Step 2: Extract fresh data from recorder (only enabled zones)
        filtered_entities = {k: v for k, v in _get_fp2_entities().items() if _is_zone_enabled(v)}
        data = _extract_data_sync(days, _get_transition_window_sec(), filtered_entities)
        transitions = data["transitions"]
        dwells = data["dwells"]
        zones_seen = data["zones_seen"]
        total_states = data["total_states"]

        # Step 3: Build and store tables
        trans_tables, dwell_lists = _build_tables(transitions, dwells)
        stored = await _store_all_patterns(
            trans_tables, dwell_lists, 0.1, min_samples, test_mode,
        )

        # Step 4: Update local cache (skip in test mode)
        if not test_mode:
            global _local_trans_cache, _local_dwell_cache
            _local_trans_cache = {
                k: _filter_by_confidence(v, 0.1) for k, v in trans_tables.items()
            }
            _local_dwell_cache = {}
            for key, durations in dwell_lists.items():
                _local_dwell_cache[key] = _compute_dwell_stats(durations)

        # Log zones with insufficient data
        for zone in _get_zone_names():
            zone_trans = 0
            for k in trans_tables:
                if k[0] == zone:
                    zone_trans += 1
            if zone_trans == 0:
                log.info(f"presence: zone '{zone}' has NO transition data")  # noqa: F821

        elapsed_ms = round((time.monotonic() - t0) * 1000)
        _set_result(
            "ok", op="rebuild", deleted=deleted,
            transitions=len(transitions), patterns=stored,
            zones_seen=zones_seen, elapsed_ms=elapsed_ms,
            test_mode=test_mode,
        )

        result = {
            "status": "ok", "op": "rebuild",
            "deleted": deleted, "transitions": len(transitions),
            "patterns": stored, "zones_seen": zones_seen,
            "total_states": total_states, "elapsed_ms": elapsed_ms,
        }
        log.info(f"presence: rebuild complete — {result}")  # noqa: F821
        return result

    except Exception as exc:
        log.error(f"presence: rebuild failed: {exc}")  # noqa: F821
        _set_result("error", op="rebuild", error=str(exc))
        return {"status": "error", "op": "rebuild", "error": str(exc)}

    finally:
        _rebuild_in_progress = False


# ── State Trigger: Incremental Update on Zone Transitions ────────────────────

def _fp2_trigger_factory(entity_id):
    """Create a @state_trigger for a single FP2 entity."""
    @state_trigger(entity_id)  # noqa: F821
    async def _trig(var_name=None, value=None):
        await _on_fp2_change(var_name=var_name, value=value)
    return _trig


async def _on_fp2_change(var_name=None, value=None):
    """Track FP2 zone changes for incremental pattern updates.

    When zone_A turns OFF and zone_B turns ON within TRANSITION_WINDOW_SEC,
    increment the frequency table for (zone_A → zone_B) in both local cache
    and L2 memory.
    """
    if not _is_enabled() or _rebuild_in_progress:
        return

    zone = _get_fp2_entities().get(var_name)
    if not zone or value not in ("on", "off"):
        return

    if not _is_zone_enabled(zone):
        return

    # Track state internally to detect actual state changes
    old = _zone_state.get(zone)
    _zone_state[zone] = value
    if old == value:
        return

    now = time.time()

    # Per-zone debounce: suppress FP2 flapping within ZONE_DEBOUNCE_SEC
    last_trigger = _zone_debounce_ts.get(zone, 0.0)
    if (now - last_trigger) < ZONE_DEBOUNCE_SEC:
        return
    _zone_debounce_ts[zone] = now
    test_mode = _is_test_mode()

    if value == "off":
        # Zone deactivated — record OFF time for transition pairing
        _recent_zone_off[zone] = now
        return

    # value == "on" — zone activated
    _zone_on_time[zone] = now

    # Find source zone: most recent OFF from another zone within window
    best_from = None
    best_ts = 0.0
    for off_zone, off_ts in _recent_zone_off.items():
        if off_zone != zone and (now - off_ts) < _get_transition_window_sec():
            if off_ts > best_ts:
                best_from = off_zone
                best_ts = off_ts

    if not best_from:
        # No transition detected — just update prediction sensor
        await _update_prediction_sensor(zone)
        return

    # Validate source zone dwell time
    dwell_from = best_ts - _zone_on_time.get(best_from, best_ts)
    if dwell_from < MIN_DWELL_SECONDS:
        await _update_prediction_sensor(zone)
        return

    # ── Transition detected: best_from → zone ────────────────────────────
    dt = datetime.fromtimestamp(now)
    bucket = _get_time_bucket(dt.hour)
    day = _get_day_type(dt.weekday())

    if test_mode:
        log.info(  # noqa: F821
            f"presence [TEST]: transition {best_from} → {zone} "
            f"({bucket}/{day}) — no cache/L2 writes"
        )
        await _update_prediction_sensor(zone)
        return

    log.info(  # noqa: F821
        f"presence: incremental transition {best_from} → {zone} ({bucket}/{day})"
    )

    # Ensure cache entry exists (load from L2 on first access)
    cache_key = (best_from, bucket, day)
    if cache_key not in _local_trans_cache:
        l2_key = f"pattern:transition:{best_from}:{bucket}:{day}"
        resp = await _l2_get(l2_key)
        if resp and resp.get("status") == "ok":
            try:
                _local_trans_cache[cache_key] = json.loads(resp.get("value", "{}"))
            except (json.JSONDecodeError, TypeError):
                _local_trans_cache[cache_key] = {}
        else:
            _local_trans_cache[cache_key] = {}

    # Increment local cache
    _local_trans_cache[cache_key][zone] = (
        _local_trans_cache[cache_key].get(zone, 0) + 1
    )

    # Persist to L2
    l2_key = f"pattern:transition:{best_from}:{bucket}:{day}"
    l2_value = json.dumps(_local_trans_cache[cache_key], separators=(",", ":"))
    l2_tags = f"pattern transition {best_from} {bucket} {day}"
    await _l2_set(l2_key, l2_value, l2_tags)

    # Update prediction sensor with new zone context
    await _update_prediction_sensor(zone)


# ── Time Triggers ────────────────────────────────────────────────────────────

@time_trigger("cron(0 4 * * *)")  # noqa: F821
async def _daily_rebuild():
    """Daily full pattern rebuild at 04:00 AM."""
    if not _is_enabled():
        log.info("presence: daily rebuild skipped (disabled)")  # noqa: F821
        return
    log.info("presence: daily rebuild starting")  # noqa: F821
    result = await presence_rebuild_patterns()
    log.info(f"presence: daily rebuild result — {result}")  # noqa: F821


@time_trigger("startup")  # noqa: F821
async def _startup():
    """Initialize on startup: set entity name, load cache from L2."""
    task.sleep(10)  # noqa: F821
    await asyncio.to_thread(reload_entity_config)

    _ensure_result_entity_name(force=True)
    _set_result("ok", op="startup", message="initializing")

    if not RECORDER_DB.exists():
        log.warning(  # noqa: F821
            f"presence: recorder DB not found at {RECORDER_DB}"
        )
        _set_result("warning", op="startup", error="recorder_db_not_found")
        return

    # Register FP2 triggers dynamically from config
    global _fp2_triggers
    fp2_entities = _get_fp2_entities().keys()
    _fp2_triggers = [_fp2_trigger_factory(e) for e in fp2_entities]
    log.info(f"presence: registered {len(_fp2_triggers)} FP2 triggers")  # noqa: F821

    loaded = await _load_cache_from_l2()
    log.info(  # noqa: F821
        f"presence: startup — loaded {loaded} pattern entries from L2 cache"
    )
    _set_result("ok", op="startup", cache_entries=loaded)

    # -- Bootstrap: rebuild from recorder if cache is empty ----------------
    if loaded == 0 and _is_enabled():
        log.info("presence: empty cache -- scheduling startup rebuild in 90s")  # noqa: F821
        await asyncio.sleep(90)
        if _is_enabled():
            result = await presence_rebuild_patterns()
            log.info(f"presence: startup rebuild result -- {result}")  # noqa: F821


# ── Configurable Helper Getter ────────────────────────────────────────────────

def _get_transition_window_sec() -> int:
    """Read transition window from helper; fallback 300."""
    try:
        return int(float(state.get("input_number.ai_presence_transition_window")))  # noqa: F821
    except (TypeError, ValueError, NameError):
        return 300


# ── I-17: Sleep Detection Log ────────────────────────────────────────────────

@service(supports_response="only")  # noqa: F821
async def sleep_detect_log():
    """
    yaml
    name: Sleep Detect Log
    description: >-
      Log sleep detection event to L2 memory with duration and confidence.
      Called by ai_sleep_detection automation on sleep end.
    """
    try:
        start_str = state.get("input_datetime.ai_sleep_start") or ""  # noqa: F821
        end_str = state.get("input_datetime.ai_sleep_end") or ""  # noqa: F821

        if not start_str or start_str in ("unknown", "unavailable"):
            return {"status": "error", "op": "sleep_detect_log",
                    "error": "no sleep start time"}

        # Compute duration
        from datetime import datetime as _dt
        try:
            start_dt = _dt.fromisoformat(start_str)
            end_dt = _dt.fromisoformat(end_str) if end_str and end_str not in ("unknown", "unavailable") else _dt.now()
            duration_min = round((end_dt - start_dt).total_seconds() / 60)
        except Exception:
            duration_min = 0

        # Confidence scoring
        confidence = 50  # base
        # Continuous bed presence = higher confidence
        if duration_min > 300:  # 5+ hours
            confidence += 30
        elif duration_min > 120:  # 2+ hours
            confidence += 15

        # Phone charging bonus
        try:
            if state.get("binary_sensor.madaringer_is_charging") == "on":  # noqa: F821
                confidence += 10
        except Exception:
            pass

        # Other zone absence bonus
        other_zones = [
            "binary_sensor.fp2_presence_sensor_workshop",
            "binary_sensor.fp2_presence_sensor_living_room",
            "binary_sensor.fp2_presence_sensor_kitchen",
        ]
        all_clear = True
        for zone in other_zones:
            try:
                if state.get(zone) == "on":  # noqa: F821
                    all_clear = False
                    break
            except Exception:
                pass
        if all_clear:
            confidence += 10

        confidence = min(100, confidence)

        # Log to L2 memory
        today = _dt.now().strftime("%Y-%m-%d")
        value = (
            f"duration={duration_min}min, "
            f"start={start_str}, end={end_str}, "
            f"confidence={confidence}"
        )

        try:
            await hass.services.async_call(  # noqa: F821
                "pyscript", "memory_set",
                {
                    "key": f"sleep:{today}",
                    "value": value,
                    "scope": "user",
                    "tags": "sleep,health,pattern",
                },
                blocking=True, return_response=True,
            )
        except Exception as exc:
            log.warning(f"presence: sleep L2 log failed: {exc}")  # noqa: F821

        log.info(  # noqa: F821
            f"presence: sleep logged — {duration_min}min, "
            f"confidence={confidence}"
        )

        return {
            "status": "ok", "op": "sleep_detect_log",
            "duration_min": duration_min,
            "confidence": confidence,
        }

    except Exception as exc:
        log.error(f"presence: sleep_detect_log failed: {exc}")  # noqa: F821
        return {"status": "error", "op": "sleep_detect_log", "error": str(exc)}


# ── I-19: Meal Passive Log ───────────────────────────────────────────────────

@service(supports_response="only")  # noqa: F821
async def meal_passive_log():
    """
    yaml
    name: Meal Passive Log
    description: >-
      Log passive meal detection to L2 memory. Determines meal type from
      time of day. Called by ai_meal_detection automation.
    """
    try:
        from datetime import datetime as _dt
        now = _dt.now()
        hour = now.hour

        # Determine meal type
        if 7 <= hour < 9:
            meal_type = "breakfast"
        elif 12 <= hour < 14:
            meal_type = "lunch"
        elif 19 <= hour < 21:
            meal_type = "dinner"
        else:
            meal_type = "snack"

        today = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H:%M")
        value = f"{meal_type} at {time_str}"

        try:
            await hass.services.async_call(  # noqa: F821
                "pyscript", "memory_set",
                {
                    "key": f"meal:{today}:{meal_type}",
                    "value": value,
                    "scope": "user",
                    "tags": "meal,health,pattern",
                },
                blocking=True, return_response=True,
            )
        except Exception as exc:
            log.warning(f"presence: meal L2 log failed: {exc}")  # noqa: F821

        log.info(  # noqa: F821
            f"presence: meal logged — {meal_type} at {time_str}"
        )

        return {
            "status": "ok", "op": "meal_passive_log",
            "meal_type": meal_type,
            "time": time_str,
        }

    except Exception as exc:
        log.error(f"presence: meal_passive_log failed: {exc}")  # noqa: F821
        return {"status": "error", "op": "meal_passive_log", "error": str(exc)}
