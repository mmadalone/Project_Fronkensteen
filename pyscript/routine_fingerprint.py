"""Task 16: Routine Fingerprinting and Real-Time Position Tracker.

Builds greedy Markov chain fingerprints from Task 15 frequency tables to
detect multi-zone routines, then tracks the user's live position within a
recognized routine on each FP2 zone transition. Outputs routine stage, ETA,
and deviation detection to helpers — predictions stay invisible to the user.
"""
import asyncio
import json
import time
from datetime import datetime
from typing import Any

from shared_utils import build_result_entity_name, load_entity_config

# =============================================================================
# Routine Fingerprinting & Position Tracker — Task 16 of Voice Context Arch.
# =============================================================================
# Detects multi-zone sequences (routines) from Task 15 frequency tables and
# tracks the user's position within a recognized routine in real time.
#
# Services:
#   pyscript.routine_extract_fingerprints
#     Analyze frequency tables → build ordered zone chains → store to L2.
#
#   pyscript.routine_track_position
#     Given a zone transition, match against known fingerprints, update
#     routine stage + ETA helpers, detect deviations.
#
# State trigger:
#   FP2 binary sensors → detect transitions → feed into position tracker.
#
# Time trigger:
#   Daily fingerprint refresh at 04:15 AM (after Task 15's 04:00 rebuild).
#
# Key design:
#   - Fingerprints are greedy Markov chains from frequency tables
#   - Position tracking via sliding window of recent transitions (60 min)
#   - Deviation detection: expected vs actual next zone
#   - Bedtime prediction: arms input_boolean when bed-ending routine starts
#   - Creep factor gate: predictions are INVISIBLE — arm automations, NEVER
#     announce routine positions to the user
#   - Max 10 fingerprints (prevent noisy data explosion)
#   - Position matching < 50ms (runs on every zone transition)
#
# Dependencies:
#   - pyscript/presence_patterns.py (Task 15 frequency tables in L2)
#   - pyscript/memory.py (L2: memory_get, memory_set, memory_search, memory_forget)
#   - packages/ai_routine_tracker.yaml (helpers)
#   - packages/ai_test_harness.yaml (test mode toggle)
#
# Deployed: 2026-03-02
# =============================================================================

RESULT_ENTITY = "sensor.ai_routine_tracker_status"
MAX_FINGERPRINTS = 10
SLIDING_WINDOW_SEC = 3600      # 60 min — recent transition memory
BEDTIME_TIMEOUT_SEC = 7200     # 2 hours — auto-reset ai_bedtime_predicted
TRANSITION_WINDOW_SEC = 300    # 5 min gap between zone OFF and ON (match Task 15)
MIN_DWELL_SECONDS = 30         # flicker filter (match Task 15)
L2_EXPIRATION_DAYS = 365       # fingerprint entries persist ~1 year (refreshed daily)

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

# ── Module-Level State ───────────────────────────────────────────────────────

_known_fingerprints: list[dict] = []
_recent_transitions: list[tuple[str, str, float]] = []  # (from_zone, to_zone, unix_ts)
_current_match: dict | None = None  # {fingerprint, step, total}
_bedtime_predicted_at: float = 0.0  # monotonic() timestamp
_zone_state: dict[str, str] = {}
_zone_on_time: dict[str, float] = {}
_recent_zone_off: dict[str, float] = {}
_fp_refresh_in_progress = False
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
def _parse_pattern_key(key: str, zone_names: list = None) -> tuple[str, str, str, str] | None:
    """Parse L2 pattern key from Task 15 frequency tables.

    After memory.py colon normalization, key format is:
      pattern_transition_{zone}_{time_bucket}_{day_type}
      pattern_dwell_{zone}_{time_bucket}_{day_type}

    Parses from the end to handle zone names containing underscores.
    zone_names must be passed by callers (pyscript_compile cannot call state.get).
    Returns: (type, zone, time_bucket, day_type) or None.
    """
    if zone_names is None:
        zone_names = _DEFAULT_ZONE_NAMES
    zone_set = set(zone_names)
    for prefix, ptype in (("pattern_transition_", "transition"),
                          ("pattern_dwell_", "dwell")):
        if not key.startswith(prefix):
            continue
        rest = key[len(prefix):]
        day_type = None
        for dt in ("weekday", "weekend"):
            if rest.endswith("_" + dt):
                day_type = dt
                rest = rest[: -(len(dt) + 1)]
                break
        if not day_type:
            return None
        time_bucket = None
        for tb in ("late_night", "morning", "afternoon", "evening"):
            if rest.endswith("_" + tb):
                time_bucket = tb
                rest = rest[: -(len(tb) + 1)]
                break
        if not time_bucket:
            return None
        if rest in zone_set:
            return (ptype, rest, time_bucket, day_type)
        return None
    return None


@pyscript_compile  # noqa: F821
def _build_chains(
    trans_cache: dict,
    dwell_cache: dict,
    min_chain_length: int,
    min_probability: float,
    time_bucket_filter: str,
    day_type_filter: str,
) -> list[dict]:
    """Build fingerprint chains by greedily following highest-probability paths.

    For each (bucket, day) context and each starting zone, follow the
    highest-probability transition until probability drops below threshold
    or a cycle is detected. Keep chains with >= min_chain_length zones.
    Filter sub-chains, sort by quality, cap at 10.
    """
    # Gather valid contexts from the frequency tables
    contexts = set()
    for key in trans_cache:
        zone, bucket, day = key
        if time_bucket_filter not in ("", "all") and bucket != time_bucket_filter:
            continue
        if day_type_filter not in ("", "all") and day != day_type_filter:
            continue
        contexts.add((bucket, day))

    all_chains: list[dict] = []

    for bucket, day in contexts:
        # Find all zones with outbound transitions in this context
        starting_zones = sorted(list({
            z for (z, b, d) in trans_cache if b == bucket and d == day
        }))

        for start in starting_zones:
            chain = [start]
            visited = {start}
            current = start
            chain_probs: list[float] = []

            while True:
                counts = trans_cache.get((current, bucket, day), {})
                total = sum(counts.values())
                if total == 0:
                    break

                # Pick highest-probability destination
                best_zone = max(counts, key=lambda z: counts[z])
                best_prob = counts[best_zone] / total

                if best_prob < min_probability or best_zone in visited:
                    break

                chain.append(best_zone)
                visited.add(best_zone)
                chain_probs.append(best_prob)
                current = best_zone

            if len(chain) < min_chain_length:
                continue

            avg_prob = sum(chain_probs) / len(chain_probs) if chain_probs else 0

            # Dwell time per step (None for last zone — no forward transition)
            step_dwells: list = []
            for zone in chain[:-1]:
                dwell_data = dwell_cache.get((zone, bucket, day), {})
                avg_min = dwell_data.get("avg_minutes", 0)
                step_dwells.append(round(avg_min, 1) if avg_min else 0)
            step_dwells.append(None)

            total_duration = sum(d for d in step_dwells if d is not None)

            confidence = (
                "high" if avg_prob >= 0.5
                else "medium" if avg_prob >= 0.3
                else "low"
            )

            fp_id = f"{bucket}_{day}_{chain[0]}_{chain[-1]}"

            all_chains.append({
                "id": fp_id,
                "sequence": chain,
                "time_bucket": bucket,
                "day_type": day,
                "avg_probability": round(avg_prob, 3),
                "avg_duration_min": round(total_duration, 1),
                "confidence": confidence,
                "step_dwells": step_dwells,
                "step_count": len(chain),
            })

    # Sort by quality: probability × chain length (longer + higher-prob first)
    all_chains.sort(
        key=lambda c: c["avg_probability"] * c["step_count"], reverse=True,
    )

    # Deduplicate by ID (same start/end in same context = same chain)
    seen_ids: set[str] = set()
    unique: list[dict] = []
    for chain in all_chains:
        if chain["id"] not in seen_ids:
            seen_ids.add(chain["id"])
            unique.append(chain)

    # Filter sub-chains: remove chain X if it's a contiguous sub-sequence
    # of a longer chain Y in the same time context
    filtered: list[dict] = []
    for chain in unique:
        is_sub = False
        for other in unique:
            if other is chain:
                continue
            if (other["time_bucket"] != chain["time_bucket"]
                    or other["day_type"] != chain["day_type"]
                    or len(other["sequence"]) <= len(chain["sequence"])):
                continue
            other_seq = other["sequence"]
            chain_seq = chain["sequence"]
            for start in range(len(other_seq) - len(chain_seq) + 1):
                if other_seq[start : start + len(chain_seq)] == chain_seq:
                    is_sub = True
                    break
            if is_sub:
                break
        if not is_sub:
            filtered.append(chain)

    return filtered[:10]  # MAX_FINGERPRINTS cap


@pyscript_compile  # noqa: F821
def _match_fingerprints(
    zone_sequence: list,
    fingerprints: list,
    time_bucket: str,
    day_type: str,
) -> dict | None:
    """Match a zone sequence against known fingerprints.

    Finds the latest occurrence of a fingerprint's first zone in the
    zone_sequence and checks how many subsequent zones match the
    fingerprint prefix. Returns the best match (longest prefix ≥ 2 zones).

    Returns: {"fingerprint": dict, "step": int, "total": int} or None.
    """
    if not zone_sequence or not fingerprints:
        return None

    best_fp = None
    best_step = 0

    for fp in fingerprints:
        if fp["time_bucket"] != time_bucket or fp["day_type"] != day_type:
            continue

        fp_seq = fp["sequence"]

        # Find LATEST occurrence of fp_seq[0] in zone_sequence
        for start in range(len(zone_sequence) - 1, -1, -1):
            if zone_sequence[start] != fp_seq[0]:
                continue

            # Count how many sequential zones match
            sub = zone_sequence[start:]
            matched = 0
            for i in range(min(len(sub), len(fp_seq))):
                if sub[i] == fp_seq[i]:
                    matched += 1
                else:
                    break

            if matched >= 2 and matched > best_step:
                best_fp = fp
                best_step = matched
            break  # only check latest occurrence per fingerprint

    if best_fp and best_step >= 2:
        return {
            "fingerprint": best_fp,
            "step": best_step,
            "total": len(best_fp["sequence"]),
        }
    return None


@pyscript_compile  # noqa: F821
def _compute_eta(fingerprint: dict, current_step: int) -> float:
    """Compute estimated minutes remaining in the routine.

    Includes the current step's dwell (slight overestimate since the user
    has already spent some time in the current zone) plus all remaining
    dwells. More useful than excluding it, which often yields 0.
    """
    step_dwells = fingerprint.get("step_dwells", [])
    remaining = 0.0
    start = max(current_step - 1, 0)
    for i in range(start, len(step_dwells)):
        d = step_dwells[i]
        if d is not None and isinstance(d, (int, float)):
            remaining += d
    return round(remaining, 1)


# ── L2 Memory Helpers ────────────────────────────────────────────────────────

async def _l2_get(key: str) -> dict | None:
    """Exact-key lookup in L2 via memory_get."""
    try:
        result = pyscript.memory_get(key=key)  # noqa: F821
        return await result
    except Exception as exc:
        log.warning(f"routine: L2 get failed key={key}: {exc}")  # noqa: F821
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
        log.warning(f"routine: L2 set failed key={key}: {exc}")  # noqa: F821
        return False


async def _l2_forget(key: str) -> bool:
    """Delete entry from L2 via memory_forget."""
    try:
        result = pyscript.memory_forget(key=key)  # noqa: F821
        resp = await result
        return resp is not None and resp.get("status") == "ok"
    except Exception as exc:
        log.warning(f"routine: L2 forget failed key={key}: {exc}")  # noqa: F821
        return False


async def _l2_search(query: str, limit: int = 200) -> list[dict[str, Any]]:
    """Search L2 via memory_search. Returns empty list on failure."""
    try:
        result = pyscript.memory_search(query=query, limit=limit)  # noqa: F821
        resp = await result
        if resp and resp.get("status") == "ok":
            return resp.get("results", [])
    except Exception as exc:
        log.warning(f"routine: L2 search failed query={query}: {exc}")  # noqa: F821
    return []


# ── Frequency Table Loading (from Task 15 L2 data) ──────────────────────────

async def _load_frequency_tables() -> tuple[dict, dict]:
    """Load Task 15 transition + dwell frequency tables from L2.

    Returns (trans_cache, dwell_cache) with tuple keys:
      trans_cache: {(zone, bucket, day): {to_zone: count}}
      dwell_cache: {(zone, bucket, day): {avg_minutes, median_minutes, ...}}
    """
    trans_cache: dict[tuple[str, str, str], dict] = {}
    dwell_cache: dict[tuple[str, str, str], dict] = {}

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
                trans_cache[(zone, bucket, day)] = data
            elif ptype == "dwell":
                dwell_cache[(zone, bucket, day)] = data

    return trans_cache, dwell_cache


# ── Fingerprint L2 Storage ───────────────────────────────────────────────────

async def _load_fingerprints_from_l2() -> int:
    """Load known fingerprints from L2. Returns count loaded."""
    global _known_fingerprints
    results = await _l2_search("routine fingerprint", limit=20)
    loaded: list[dict] = []

    for entry in results:
        key = entry.get("key", "")
        value = entry.get("value", "")
        if not key.startswith("routine_") or not value:
            continue
        try:
            fp = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(fp, dict) and "sequence" in fp and "id" in fp:
            loaded.append(fp)

    _known_fingerprints = loaded
    return len(loaded)


async def _store_fingerprint(fp: dict, test_mode: bool) -> bool:
    """Store a single fingerprint to L2."""
    key = f"routine:{fp['id']}"
    fp_with_ts = {**fp, "last_observed": datetime.now().isoformat()}
    value = json.dumps(fp_with_ts, separators=(",", ":"))
    tags = f"routine fingerprint {fp['time_bucket']} {fp['day_type']}"

    if test_mode:
        log.info(f"routine [TEST]: WOULD STORE {key}")  # noqa: F821
        return True
    return await _l2_set(key, value, tags)


async def _delete_old_fingerprints(test_mode: bool) -> int:
    """Delete all routine fingerprint entries from L2. Returns count deleted."""
    deleted = 0
    results = await _l2_search("routine fingerprint", limit=30)
    for entry in results:
        key = entry.get("key", "")
        if not key.startswith("routine_"):
            continue
        if test_mode:
            log.info(f"routine [TEST]: WOULD DELETE L2 key={key}")  # noqa: F821
        else:
            if await _l2_forget(key):
                deleted += 1
    return deleted


# ── Sliding Window Management ────────────────────────────────────────────────

def _prune_window() -> None:
    """Remove transitions older than SLIDING_WINDOW_SEC."""
    global _recent_transitions
    cutoff = time.time() - SLIDING_WINDOW_SEC
    _recent_transitions = [t for t in _recent_transitions if t[2] >= cutoff]


def _get_zone_sequence() -> list[str]:
    """Extract ordered zone sequence from recent transitions.

    Includes both from_zone and to_zone of each transition to handle
    non-sequential gaps (e.g., manual test calls or missed transitions).
    From transitions [(A,B,t1), (C,B,t2)] → [A, B, C, B].
    """
    if not _recent_transitions:
        return []
    sequence: list[str] = []
    for from_zone, to_zone, _ in _recent_transitions:
        if not sequence or from_zone != sequence[-1]:
            sequence.append(from_zone)
        if to_zone != sequence[-1]:
            sequence.append(to_zone)
    return sequence


# ── Settings Helpers ─────────────────────────────────────────────────────────

def _is_test_mode() -> bool:
    try:
        return str(state.get("input_boolean.ai_test_mode") or "off").lower() == "on"  # noqa: F821
    except NameError:
        return False  # default OFF during startup race


def _is_enabled() -> bool:
    try:
        return str(  # noqa: F821
            state.get("input_boolean.ai_routine_tracking_enabled") or "on"  # noqa: F821
        ).lower() == "on"
    except NameError:
        return True  # default ON during startup race


def _is_zone_enabled(zone: str) -> bool:
    """Check if an FP2 zone is enabled via dashboard toggle."""
    toggle = f"input_boolean.ai_fp2_zone_{zone}_enabled"
    try:
        return str(state.get(toggle) or "on").lower() != "off"  # noqa: F821
    except NameError:
        return True  # default ON if helper missing


# ── Helper Update Logic ─────────────────────────────────────────────────────

async def _update_routine_helpers(
    match: dict | None, test_mode: bool,
) -> None:
    """Update input_text helpers with current routine position + ETA."""
    if match:
        fp = match["fingerprint"]
        step = match["step"]
        total = match["total"]
        stage_str = f"{fp['id']}:step_{step}_of_{total}"

        eta = _compute_eta(fp, step)
        eta_raw = json.dumps({
            "eta_minutes": eta,
            "fingerprint_id": fp["id"],
            "step": step,
            "total": total,
        }, separators=(",", ":"))
    else:
        stage_str = "none"
        eta_raw = ""

    if test_mode:
        log.info(f"routine [TEST]: stage={stage_str}")  # noqa: F821
        return

    try:
        service.call(  # noqa: F821
            "input_text", "set_value",
            entity_id="input_text.ai_routine_stage", value=stage_str,
        )
    except Exception:
        pass

    try:
        service.call(  # noqa: F821
            "input_text", "set_value",
            entity_id="input_text.ai_routine_eta_raw", value=eta_raw,
        )
    except Exception:
        pass


async def _handle_deviation(
    deviation: dict | None, test_mode: bool,
) -> None:
    """Update deviation helper and fire ai_routine_deviation event."""
    if not deviation:
        return

    desc = f"expected:{deviation['expected_zone']} actual:{deviation['actual_zone']}"

    if test_mode:
        log.info(  # noqa: F821
            f"routine [TEST]: deviation in {deviation['fingerprint_id']} — {desc}"
        )
        return

    try:
        service.call(  # noqa: F821
            "input_text", "set_value",
            entity_id="input_text.ai_routine_deviation", value=desc,
        )
    except Exception:
        pass

    event.fire(  # noqa: F821
        "ai_routine_deviation",
        fingerprint_id=deviation["fingerprint_id"],
        expected_zone=deviation["expected_zone"],
        actual_zone=deviation["actual_zone"],
        step=deviation["step"],
        total=deviation["total"],
    )
    log.info(  # noqa: F821
        f"routine: deviation fired — {deviation['fingerprint_id']} {desc}"
    )


async def _check_bedtime_prediction(
    match: dict | None, test_mode: bool,
) -> None:
    """Set ai_bedtime_predicted ON when a bed-ending fingerprint is detected."""
    global _bedtime_predicted_at
    now_mono = time.monotonic()

    # Check timeout: reset if prediction has been active > 2 hours
    if _bedtime_predicted_at > 0 and (now_mono - _bedtime_predicted_at) > BEDTIME_TIMEOUT_SEC:
        _bedtime_predicted_at = 0.0
        if not test_mode:
            try:
                service.call(  # noqa: F821
                    "input_boolean", "turn_off",
                    entity_id="input_boolean.ai_bedtime_predicted",
                )
            except Exception:
                pass
            log.info("routine: bedtime prediction timed out — reset to OFF")  # noqa: F821
        else:
            log.info("routine [TEST]: bedtime prediction WOULD timeout")  # noqa: F821

    if not match:
        return

    fp = match["fingerprint"]
    # Only trigger for fingerprints ending in "bed"
    if fp["sequence"][-1] != "bed":
        return

    # Already predicted? Don't re-trigger
    if _bedtime_predicted_at > 0:
        return

    _bedtime_predicted_at = now_mono
    if test_mode:
        log.info(  # noqa: F821
            f"routine [TEST]: WOULD set ai_bedtime_predicted ON "
            f"(fingerprint={fp['id']}, step={match['step']})"
        )
    else:
        try:
            service.call(  # noqa: F821
                "input_boolean", "turn_on",
                entity_id="input_boolean.ai_bedtime_predicted",
            )
        except Exception:
            pass
        log.info(  # noqa: F821
            f"routine: bedtime predicted ON — {fp['id']} step {match['step']}"
        )


async def _reset_bedtime_prediction(test_mode: bool) -> None:
    """Reset bedtime prediction (deviation, completion, or timeout)."""
    global _bedtime_predicted_at
    if _bedtime_predicted_at == 0.0:
        return

    _bedtime_predicted_at = 0.0
    if test_mode:
        log.info("routine [TEST]: WOULD reset ai_bedtime_predicted OFF")  # noqa: F821
    else:
        try:
            service.call(  # noqa: F821
                "input_boolean", "turn_off",
                entity_id="input_boolean.ai_bedtime_predicted",
            )
        except Exception:
            pass
        log.info("routine: bedtime predicted OFF — reset")  # noqa: F821


# ── Services ─────────────────────────────────────────────────────────────────

@service(supports_response="only")  # noqa: F821
async def routine_extract_fingerprints(
    time_bucket: str = "all",
    day_type: str = "all",
    min_chain_length: int = 3,
    min_probability: float = 0.3,
):
    """Extract routine fingerprints from Task 15 frequency tables.

    Analyzes transition probability chains to identify recurring multi-zone
    sequences (routines). Stores fingerprints to L2 for position tracking.

    fields:
      time_bucket:
        description: Time bucket filter ("all" for all buckets)
        example: "evening"
        selector:
          select:
            options:
              - all
              - late_night
              - morning
              - afternoon
              - evening
      day_type:
        description: Day type filter ("all" for all types)
        example: "weekday"
        selector:
          select:
            options:
              - all
              - weekday
              - weekend
      min_chain_length:
        description: Minimum zones in a fingerprint chain
        example: 3
        selector:
          number:
            min: 2
            max: 8
      min_probability:
        description: Minimum transition probability to follow (0.0-1.0)
        example: 0.3
        selector:
          number:
            min: 0.1
            max: 0.9
            step: 0.05
    """
    global _known_fingerprints
    t0 = time.monotonic()
    test_mode = _is_test_mode()

    log.info(  # noqa: F821
        f"routine: extracting fingerprints "
        f"(bucket={time_bucket}, day={day_type}, min_len={min_chain_length}, "
        f"min_prob={min_probability}, test={test_mode})"
    )

    # Load frequency tables from Task 15's L2 data
    trans_cache, dwell_cache = await _load_frequency_tables()

    if not trans_cache:
        msg = "no frequency data — run presence_extract_transitions first"
        _set_result("ok", op="extract", fingerprints=0, message=msg)
        log.info(f"routine: {msg}")  # noqa: F821
        return {
            "status": "ok", "op": "extract", "fingerprints": [],
            "count": 0, "message": "no_data",
        }

    # Build greedy Markov chains
    chains = _build_chains(
        trans_cache, dwell_cache,
        min_chain_length, min_probability,
        time_bucket, day_type,
    )

    if test_mode:
        for ch in chains:
            log.info(  # noqa: F821
                f"routine [TEST]: fingerprint {ch['id']}: "
                f"{' -> '.join(ch['sequence'])} "
                f"(prob={ch['avg_probability']}, dur={ch['avg_duration_min']}m)"
            )

    # Log fingerprint changes (new / deprecated)
    old_ids = {fp["id"] for fp in _known_fingerprints}
    new_ids = {fp["id"] for fp in chains}
    for removed_id in old_ids - new_ids:
        log.info(f"routine: fingerprint deprecated: {removed_id}")  # noqa: F821
    for added_id in new_ids - old_ids:
        log.info(f"routine: new fingerprint detected: {added_id}")  # noqa: F821

    # Delete old fingerprints from L2 and store new ones
    deleted = await _delete_old_fingerprints(test_mode)
    stored = 0
    for fp in chains:
        if await _store_fingerprint(fp, test_mode):
            stored += 1

    # Update module-level cache (skip in test mode — no side effects)
    if not test_mode:
        _known_fingerprints = chains

    elapsed_ms = round((time.monotonic() - t0) * 1000)
    _set_result(
        "ok", op="extract", fingerprints_found=len(chains),
        fingerprints_stored=stored, deleted=deleted,
        elapsed_ms=elapsed_ms, test_mode=test_mode,
    )

    result = {
        "status": "ok", "op": "extract",
        "fingerprints": chains, "count": len(chains),
        "stored": stored, "deleted": deleted,
        "elapsed_ms": elapsed_ms,
    }
    log.info(f"routine: extract complete — {len(chains)} fingerprints found")  # noqa: F821
    return result


@service(supports_response="only")  # noqa: F821
async def routine_track_position(
    from_zone: str = "",
    to_zone: str = "",
):
    """Track a zone transition and match against known routine fingerprints.

    Called automatically by FP2 state trigger on every zone transition.
    Also callable manually for testing.

    fields:
      from_zone:
        description: Zone the user left
        example: "kitchen"
        selector:
          text:
      to_zone:
        description: Zone the user entered
        example: "bathroom"
        selector:
          text:
    """
    global _current_match, _recent_transitions
    test_mode = _is_test_mode()

    if not from_zone or not to_zone:
        return {"status": "error", "error": "from_zone and to_zone required"}

    now = time.time()

    # Add to sliding window and prune old entries
    _recent_transitions.append((from_zone, to_zone, now))
    _prune_window()

    dt = datetime.fromtimestamp(now)
    bucket = _get_time_bucket(dt.hour)
    day = _get_day_type(dt.weekday())

    # ── Deviation check BEFORE re-matching ────────────────────────────────
    deviation = None
    if _current_match:
        fp = _current_match["fingerprint"]
        step = _current_match["step"]
        total = _current_match["total"]
        if step < total:
            # step = zones matched; sequence[step] = expected next zone (0-indexed)
            expected = fp["sequence"][step]
            if to_zone != expected:
                deviation = {
                    "fingerprint_id": fp["id"],
                    "expected_zone": expected,
                    "actual_zone": to_zone,
                    "step": step,
                    "total": total,
                }

    # Handle deviation: fire event, reset state, trim window
    if deviation:
        await _handle_deviation(deviation, test_mode)
        await _reset_bedtime_prediction(test_mode)
        _current_match = None
        # Fresh start — keep only the latest transition
        _recent_transitions = [(from_zone, to_zone, now)]

    zone_seq = _get_zone_sequence()

    # Lazy-load fingerprints from L2 if cache is empty
    if not _known_fingerprints:
        loaded = await _load_fingerprints_from_l2()
        if loaded:
            log.info(f"routine: lazy-loaded {loaded} fingerprints from L2")  # noqa: F821

    # Match zone sequence against known fingerprints
    match = _match_fingerprints(zone_seq, _known_fingerprints, bucket, day)

    # Check for routine completion (all zones matched)
    if match and match["step"] == match["total"]:
        fp_id = match["fingerprint"]["id"]
        if not test_mode:
            log.info(f"routine: completed {fp_id}!")  # noqa: F821
            event.fire(  # noqa: F821
                "ai_routine_completed",
                fingerprint_id=fp_id,
            )
        else:
            log.info(f"routine [TEST]: completed {fp_id}")  # noqa: F821
        await _reset_bedtime_prediction(test_mode)
        match = None  # routine done

    _current_match = match

    # Update HA helpers
    await _update_routine_helpers(match, test_mode)
    await _check_bedtime_prediction(match, test_mode)

    # Build response
    result: dict[str, Any] = {
        "status": "ok",
        "from_zone": from_zone,
        "to_zone": to_zone,
        "zone_sequence": zone_seq,
        "time_bucket": bucket,
        "day_type": day,
    }

    if match:
        result["routine_match"] = {
            "fingerprint_id": match["fingerprint"]["id"],
            "step": match["step"],
            "total": match["total"],
            "eta_minutes": _compute_eta(match["fingerprint"], match["step"]),
        }
    else:
        result["routine_match"] = None

    if deviation:
        result["deviation"] = deviation

    # Update status sensor for observability
    match_id = result["routine_match"]["fingerprint_id"] if result.get("routine_match") else "none"
    _set_result(
        "ok", op="track", from_zone=from_zone, to_zone=to_zone,
        time_bucket=bucket, day_type=day,
        match=match_id,
        zone_sequence=",".join(zone_seq),
        known_fingerprints=len(_known_fingerprints),
    )

    return result


# ── State Trigger: FP2 Zone Changes ─────────────────────────────────────────

def _fp2_trigger_factory(entity_id):
    """Create a @state_trigger for a single FP2 entity."""
    @state_trigger(entity_id)  # noqa: F821
    async def _trig(var_name=None, value=None):
        await _on_fp2_zone_change(var_name=var_name, value=value)
    return _trig


async def _on_fp2_zone_change(var_name=None, value=None):
    """Track FP2 zone changes for routine position detection.

    Detects transitions (zone_A OFF → zone_B ON within 5-min window)
    and feeds them into the position tracker.
    """
    if not _is_enabled() or _fp_refresh_in_progress:
        return

    zone = _get_fp2_entities().get(var_name)
    if not zone or value not in ("on", "off"):
        return

    if not _is_zone_enabled(zone):
        return

    # Skip duplicate states
    old = _zone_state.get(zone)
    _zone_state[zone] = value
    if old == value:
        return

    now = time.time()

    if value == "off":
        _recent_zone_off[zone] = now
        return

    # value == "on" — zone activated
    _zone_on_time[zone] = now

    # Find source zone: most recent OFF from a different zone within window
    best_from = None
    best_ts = 0.0
    for off_zone, off_ts in _recent_zone_off.items():
        if off_zone != zone and (now - off_ts) < TRANSITION_WINDOW_SEC:
            if off_ts > best_ts:
                best_from = off_zone
                best_ts = off_ts

    if not best_from:
        return

    # Validate source zone dwell time (flicker filter)
    dwell_from = best_ts - _zone_on_time.get(best_from, best_ts)
    if dwell_from < MIN_DWELL_SECONDS:
        return

    # ── Transition detected: best_from → zone ────────────────────────────
    log.info(f"routine: transition {best_from} -> {zone}")  # noqa: F821
    await routine_track_position(from_zone=best_from, to_zone=zone)


# ── Time Triggers ────────────────────────────────────────────────────────────

@time_trigger("cron(15 4 * * *)")  # noqa: F821
async def _daily_fingerprint_refresh():
    """Daily fingerprint refresh at 04:15 AM.

    Runs 15 minutes after Task 15's 04:00 pattern rebuild to ensure
    fresh frequency tables are available.
    """
    global _fp_refresh_in_progress
    if not _is_enabled():
        log.info("routine: daily refresh skipped (disabled)")  # noqa: F821
        return

    _fp_refresh_in_progress = True
    try:
        log.info("routine: daily fingerprint refresh starting")  # noqa: F821
        result = await routine_extract_fingerprints()
        count = result.get("count", 0) if isinstance(result, dict) else 0
        log.info(f"routine: daily refresh — {count} fingerprints")  # noqa: F821
    except Exception as exc:
        log.error(f"routine: daily refresh failed: {exc}")  # noqa: F821
    finally:
        _fp_refresh_in_progress = False


@time_trigger("startup")  # noqa: F821
async def _startup():
    """Initialize on startup: load known fingerprints from L2."""
    _ensure_result_entity_name(force=True)
    _set_result("ok", op="startup", message="initializing")

    # Register FP2 triggers dynamically from config
    global _fp2_triggers
    fp2_entities = _get_fp2_entities().keys()
    _fp2_triggers = [_fp2_trigger_factory(e) for e in fp2_entities]
    log.info(f"routine: registered {len(_fp2_triggers)} FP2 triggers")  # noqa: F821

    loaded = await _load_fingerprints_from_l2()
    log.info(  # noqa: F821
        f"routine: startup — loaded {loaded} fingerprints from L2"
    )
    _set_result("ok", op="startup", fingerprints_loaded=loaded)

    # -- Bootstrap: extract fingerprints if none exist ---------------------
    if loaded == 0 and _is_enabled():
        log.info("routine: no fingerprints -- scheduling startup extraction in 180s")  # noqa: F821
        await asyncio.sleep(180)  # 90s after presence rebuild starts
        if _is_enabled():
            result = await routine_extract_fingerprints()
            count = result.get("count", 0) if isinstance(result, dict) else 0
            log.info(f"routine: startup extraction -- {count} fingerprints")  # noqa: F821
