"""I-40: Away Pattern Extraction from HA Recorder.

Queries the recorder database for historical device_tracker home/not_home
transitions, builds duration and return-time frequency tables, and stores
patterns in L2 memory. Triggers on device_tracker state changes and
exposes pyscript.away_predict_return for real-time return-time prediction.
"""
import asyncio
import json
import math
import sqlite3
import statistics
import time
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any

from shared_utils import (
    build_result_entity_name,
    get_person_slugs,
    get_person_tracker,
    load_entity_config,
    reload_entity_config,
)

# =============================================================================
# Away Pattern Extraction — I-40 of Voice Context Architecture
# =============================================================================
# Queries HA recorder for historical device_tracker home/not_home transitions,
# builds duration and return-time frequency tables, stores patterns in L2 memory.
# Predicts return time when user is away.
#
# Services:
#   pyscript.away_extract_cycles
#     Extract departure/arrival cycles from recorder DB, build frequency tables.
#
#   pyscript.away_predict_return
#     Given current away state → predicted return time + confidence.
#
#   pyscript.away_rebuild_patterns
#     Full rebuild: delete old away patterns, re-extract, re-store.
#
# State trigger:
#   device_tracker.oppo_a60 / oppo_a38 → log departure/arrival, run prediction.
#   Departure debounced via asyncio.sleep (reads ai_away_flap_debounce_seconds).
#
# Time trigger:
#   Daily rebuild at 04:15 AM (15 min after presence_patterns at 04:00).
#   Periodic prediction update every N minutes while someone is away.
#
# Key design:
#   - Recorder DB access is READ-ONLY (sqlite3 URI mode=ro)
#   - All DB queries via asyncio.to_thread (never block event loop)
#   - Frequency tables live in L2 memory, local cache for fast prediction
#   - Departure debounced (configurable, default 300s) — WiFi flap protection
#   - Tracks Miquel and Jessica independently (with household correlation)
#   - Calendar fusion v2: start+end time parsing, gap detection, confirmation
#   - Statistical foundation: MAD outlier filtering, exponential decay weights,
#     weighted percentile, KDE mode detection, empirical MRL for remaining time,
#     cross-bucket blending, prediction intervals, accuracy tracking
#   - G13 Phase 1 (observe only): Miller-Madow Shannon entropy + Fano
#     predictability score on return-time distributions. Diagnostic metric —
#     published as sensor attributes, no behavior change.
#
# Dependencies:
#   - HA recorder database (/config/home-assistant_v2.db) — READ ONLY
#   - pyscript/memory.py (L2: memory_get, memory_set, memory_search, memory_forget)
#   - packages/ai_away_patterns.yaml (helpers)
#   - packages/ai_identity.yaml (sensor.occupancy_mode)
#   - packages/ai_test_harness.yaml (test mode toggle)
#
# I-40a hardening: G1–G12, G14 (2026-03-12)
# G13 Phase 1: entropy-based predictability — observe only (2026-03-26)
# Deployed: 2026-03-12
# =============================================================================

RECORDER_DB = Path("/config/home-assistant_v2.db")
RESULT_ENTITY = "sensor.ai_away_pattern_status"

def _get_person_trackers() -> dict:
    """Build person→tracker map from discover_persons() (Task 22)."""
    from shared_utils import discover_persons
    persons = discover_persons()
    return {slug: p["trackers"][0] for slug, p in persons.items() if p.get("trackers")}


def _get_tracker_to_person() -> dict:
    return {v: k for k, v in _get_person_trackers().items()}

MIN_AWAY_DURATION_SEC = 300    # 5 min — minimum trip for historical data
CONFIDENCE_HIGH = 15           # sample count for "high" confidence
CONFIDENCE_MEDIUM = 5          # sample count for "medium" confidence
L2_EXPIRATION_DAYS = 365       # pattern entries persist ~1 year (refreshed daily)
MAX_HISTORY_PER_BUCKET = 200   # cap stored durations/returns per bucket

# ── I-40a: Cross-Bucket Blending (G9) ─────────────────────────────────────────
BUCKET_CENTERS = {"late_night": 2.5, "morning": 8.5, "afternoon": 14.5, "evening": 20.5}
BUCKET_ADJACENCY = {
    "late_night": ("evening", "morning"),
    "morning": ("late_night", "afternoon"),
    "afternoon": ("morning", "evening"),
    "evening": ("afternoon", "late_night"),
}

# ── I-40a: Household Correlation (G11) ────────────────────────────────────────
JOINT_TRIP_THRESHOLD_SEC = 600  # 10 min — if both left within this, same trip

# ── Module-Level State ───────────────────────────────────────────────────────

_local_duration_cache: dict[tuple[str, str, str], list] = {}   # mixed float|dict
_local_return_cache: dict[tuple[str, str, str], list] = {}     # mixed float|dict
_local_count_cache: dict[tuple[str, str], dict[str, Any]] = {}
_departure_ts: dict[str, list[float]] = {}  # I-40b: person → FIFO queue of dep timestamps
_rebuild_in_progress = False
_tracker_triggers = []         # factory-created trigger references (keep alive)
result_entity_name: dict[str, str] = {}
_prediction_log: list[dict] = []  # I-40a G12: accuracy tracking


# ── Entity Name Helpers ──────────────────────────────────────────────────────

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
def _resolve_metadata_ids(entity_ids: list[str]) -> dict[int, str]:
    """Get metadata_id → entity_id mapping from recorder states_meta table."""
    placeholders = ",".join("?" * len(entity_ids))
    with closing(_get_recorder_conn()) as conn:
        cursor = conn.execute(
            f"SELECT metadata_id, entity_id FROM states_meta "
            f"WHERE entity_id IN ({placeholders})",
            entity_ids,
        )
        return {row[0]: row[1] for row in cursor}


@pyscript_executor  # noqa: F821
def _extract_cycles_sync(
    lookback_days: int,
    entity_ids: list[str],
    tracker_person_map: dict[str, str],
) -> dict[str, Any]:
    """Extract away cycles from recorder DB.

    Scans device_tracker state changes chronologically, detects:
    - Departure: home → not_home
    - Arrival: not_home → home
    - Pairs them into cycles with duration.

    Returns dict with: cycles (list of dicts), total_states.
    """
    meta_map = _resolve_metadata_ids(entity_ids)
    if not meta_map:
        return {"cycles": [], "total_states": 0}

    # Build metadata_id → person mapping
    meta_person = {}
    for meta_id, entity_id in meta_map.items():
        person = tracker_person_map.get(entity_id)
        if person:
            meta_person[meta_id] = person

    cutoff_ts = time.time() - (lookback_days * 86400)
    meta_ids = list(meta_person.keys())
    placeholders = ",".join("?" * len(meta_ids))

    rows = []
    for attempt in range(2):
        try:
            with closing(_get_recorder_conn()) as conn:
                cursor = conn.execute(
                    f"SELECT metadata_id, state, last_updated_ts "
                    f"FROM states "
                    f"WHERE metadata_id IN ({placeholders}) "
                    f"  AND state IN ('home', 'not_home') "
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
        return {"cycles": [], "total_states": 0}

    # ── Chronological scan: pair departure/arrival into cycles ────────
    cycles: list[dict] = []
    prev_state: dict[str, str] = {}     # person → last known state
    departure_ts: dict[str, float] = {} # person → departure timestamp

    for meta_id, state_val, ts in rows:
        if ts is None or meta_id not in meta_person:
            continue
        person = meta_person[meta_id]

        # Skip duplicate states
        if prev_state.get(person) == state_val:
            continue
        prev_state[person] = state_val

        if state_val == "not_home":
            departure_ts[person] = ts
        elif state_val == "home" and person in departure_ts:
            dep_ts = departure_ts.pop(person)
            duration_sec = ts - dep_ts
            # Skip short away periods (WiFi flapping / router reboot)
            if duration_sec < MIN_AWAY_DURATION_SEC:
                continue
            dep_dt = datetime.fromtimestamp(dep_ts)
            ret_dt = datetime.fromtimestamp(ts)
            cycles.append({
                "person": person,
                "departed_ts": dep_ts,
                "returned_ts": ts,
                "departed_hour": dep_dt.hour + dep_dt.minute / 60.0,
                "returned_hour": ret_dt.hour + ret_dt.minute / 60.0,
                "departed_bucket": _get_time_bucket(dep_dt.hour),
                "day_of_week": dep_dt.strftime("%A").lower(),
                "day_type": _get_day_type(dep_dt.weekday()),
                "duration_minutes": round(duration_sec / 60.0, 1),
            })

    return {"cycles": cycles, "total_states": len(rows)}


@pyscript_compile  # noqa: F821
def _build_tables(
    cycles: list[dict],
) -> tuple[dict, dict, dict]:
    """Build frequency tables from raw cycle data.

    Returns:
        (duration_tables, return_tables, count_tables)
        duration_tables: {(person, bucket, day_type): [float | {"d": float, "o": int}]}
        return_tables:   {(person, bucket, day_type): [float | {"r": float, "o": int}]}
        count_tables:    {(person, day_type): {avg_trips, max_trips, days_sampled, ordinal_dist}}

    I-40b: Bare floats = ordinal 1 (backward compat), dicts = ordinal 2+.
    ordinal_dist: {"1": N, "2": N, ...} — how many days had at least that ordinal.
    """
    duration_tables: dict[tuple[str, str, str], list] = {}
    return_tables: dict[tuple[str, str, str], list] = {}
    daily_trips: dict[tuple[str, str, str], int] = {}  # (person, day_type, date_str) → count

    # I-40b: Sort cycles by (person, date, departed_ts) to assign ordinals
    sorted_cycles = sorted(cycles, key=lambda c: (c["person"], c["departed_ts"]))

    # Assign ordinals per (person, date) group
    ordinal_tracker: dict[tuple[str, str], int] = {}  # (person, date_str) → next ordinal
    for cycle in sorted_cycles:
        person = cycle["person"]
        bucket = cycle["departed_bucket"]
        day_type = cycle["day_type"]
        key = (person, bucket, day_type)
        date_str = datetime.fromtimestamp(cycle["departed_ts"]).strftime("%Y-%m-%d")
        ord_key = (person, date_str)
        ordinal = ordinal_tracker.get(ord_key, 0) + 1
        ordinal_tracker[ord_key] = ordinal

        dur = cycle["duration_minutes"]
        ret = cycle["returned_hour"]

        if key not in duration_tables:
            duration_tables[key] = []
        if key not in return_tables:
            return_tables[key] = []

        # I-40b: Enriched samples — bare float for ordinal 1, dict for 2+
        if ordinal == 1:
            duration_tables[key].append(dur)
            return_tables[key].append(ret)
        else:
            duration_tables[key].append({"d": dur, "o": ordinal})
            return_tables[key].append({"r": ret, "o": ordinal})

        # Count trips per day
        trip_key = (person, day_type, date_str)
        daily_trips[trip_key] = daily_trips.get(trip_key, 0) + 1

    # Aggregate daily trip counts
    count_tables: dict[tuple[str, str], dict] = {}
    # Group by (person, day_type)
    grouped: dict[tuple[str, str], list[int]] = {}
    for (person, day_type, _date), count in daily_trips.items():
        gkey = (person, day_type)
        if gkey not in grouped:
            grouped[gkey] = []
        grouped[gkey].append(count)

    for gkey, counts in grouped.items():
        # I-40b: Build ordinal distribution from daily trip counts
        ordinal_dist: dict[str, int] = {}
        for c in counts:
            for i in range(1, c + 1):
                ordinal_dist[str(i)] = ordinal_dist.get(str(i), 0) + 1
        count_tables[gkey] = {
            "avg_trips": round(sum(counts) / len(counts), 1),
            "max_trips": max(counts),
            "days_sampled": len(counts),
            "ordinal_dist": ordinal_dist,
        }

    return duration_tables, return_tables, count_tables


# ── I-40a: Statistical Foundation (G1–G5) ────────────────────────────────────

@pyscript_compile  # noqa: F821
def _filter_outliers(values: list[float], threshold: float = 3.5) -> list[float]:
    """MAD-based outlier removal (Iglewicz & Hoaglin 1993).

    Modified Z-Score: M = 0.6745 * |x - median| / MAD. Reject if M > threshold.
    Preserves chronological order. Returns original if n < 5 or MAD ≈ 0.
    """
    if len(values) < 5:
        return values
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    median = (sorted_vals[n // 2] + sorted_vals[(n - 1) // 2]) / 2.0
    abs_devs = sorted([abs(v - median) for v in values])
    mad = (abs_devs[n // 2] + abs_devs[(n - 1) // 2]) / 2.0
    if mad < 1e-9:
        return values
    filtered = [v for v in values if 0.6745 * abs(v - median) / mad <= threshold]
    return filtered if filtered else values


# ── I-40b: Ordinal-Aware Helpers ──────────────────────────────────────────────

@pyscript_compile  # noqa: F821
def _extract_values(samples: list, field: str = "d") -> list[float]:
    """Extract numeric values from mixed legacy/enriched array.

    Legacy samples are bare floats (treated as ordinal 1).
    Enriched samples are dicts like {"d": 120.5, "o": 2}.
    """
    result = []
    for s in samples:
        if isinstance(s, (int, float)):
            result.append(float(s))
        elif isinstance(s, dict) and field in s:
            result.append(float(s[field]))
    return result


@pyscript_compile  # noqa: F821
def _filter_by_ordinal_with_weights(
    samples: list,
    weights: list[float],
    ordinal: int,
    field: str = "d",
    min_samples: int = 5,
) -> tuple[list[float], list[float]]:
    """Filter samples by trip ordinal, returning (values, matching_weights).

    Bare floats are treated as ordinal 1.
    Enriched dicts matched by {"o": ordinal}.
    Falls back to all ordinals if filtered count < min_samples.
    """
    filtered_vals = []
    filtered_weights = []
    for i, s in enumerate(samples):
        w = weights[i] if i < len(weights) else 1.0
        if isinstance(s, (int, float)):
            if ordinal == 1:
                filtered_vals.append(float(s))
                filtered_weights.append(w)
        elif isinstance(s, dict) and field in s:
            if s.get("o", 1) == ordinal:
                filtered_vals.append(float(s[field]))
                filtered_weights.append(w)
    if len(filtered_vals) >= min_samples:
        return (filtered_vals, filtered_weights)
    # Fallback: all ordinals — zero quality loss vs pre-I-40b
    all_vals = _extract_values(samples, field)
    return (all_vals, weights[:len(all_vals)])


@pyscript_compile  # noqa: F821
def _compute_decay_weights(n: int, half_life: float = 30.0) -> list[float]:
    """Exponential decay weights (chronological order, most recent last).

    Formula: w(i) = exp(-ln(2)/half_life * age(i))
    Reference: Standard EWMA, half-life parameterization.
    """
    if n <= 0:
        return []
    if n == 1:
        return [1.0]
    lam = 0.693147 / half_life
    return [math.exp(-lam * (n - 1 - i)) for i in range(n)]


@pyscript_compile  # noqa: F821
def _weighted_percentile(values: list[float], weights: list[float], percentile: float = 0.5) -> float:
    """Weighted percentile via cumulative weight interpolation.

    Standard algorithm: sort by value, accumulate weights, find crossover at
    q × total_weight with linear interpolation between bracketing values.
    Reference: NumPy inverted_cdf, statsmodels DescrStatsW.quantile.
    """
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    pairs = sorted(zip(values, weights), key=lambda x: x[0])
    total_w = sum([w for _, w in pairs])
    target = percentile * total_w
    cumulative = 0.0
    for i, (v, w) in enumerate(pairs):
        cumulative += w
        if cumulative >= target:
            if i > 0 and cumulative - w < target:
                prev_v = pairs[i - 1][0]
                frac = (target - (cumulative - w)) / w
                return prev_v + frac * (v - prev_v)
            return v
    return pairs[-1][0]


@pyscript_compile  # noqa: F821
def _weighted_std_dev(values: list[float], weights: list[float]) -> float:
    """Weighted standard deviation for prediction intervals."""
    if len(values) < 2:
        return 0.0
    total_w = sum(weights)
    if total_w < 1e-9:
        return 0.0
    w_mean = sum([v * w for v, w in zip(values, weights)]) / total_w
    variance = sum([w * (v - w_mean) ** 2 for v, w in zip(values, weights)]) / total_w
    return variance ** 0.5


@pyscript_compile  # noqa: F821
def _get_confidence(sample_count: int, high: int, medium: int, std_dev: float = 0.0) -> str:
    """Spread-adjusted confidence: tight spread promotes, wide demotes.

    Thresholds: < 1.0h = tight (promote), > 2.0h = wide (demote).
    Backward-compatible: std_dev=0.0 gives original behavior.
    """
    if sample_count >= high:
        base = 2
    elif sample_count >= medium:
        base = 1
    else:
        base = 0
    if sample_count >= medium and std_dev > 0:
        if std_dev < 1.0:
            base = min(base + 1, 2)
        elif std_dev > 2.0:
            base = max(base - 1, 0)
    return ("low", "medium", "high")[base]


# ── G13: Entropy-Based Predictability (Phase 1 — observe only) ───────────────
# Miller-Madow corrected Shannon entropy on discretized return-time histograms.
# Fano's inequality converts entropy to a 0–1 predictability upper bound.
# Phase 1: diagnostic metric only — no behavior change, no confidence gating.
# References: Miller (1955), Nowozin (2014), Fano (1961).

ENTROPY_BIN_WIDTH = 0.25  # 15-min bins for return-time discretization (hours)


@pyscript_compile  # noqa: F821
def _shannon_entropy_mm(values: list[float], bin_width: float) -> tuple[float, int]:
    """Miller-Madow corrected Shannon entropy on discretized values.

    Discretizes continuous return-time hours into bins, computes plugin
    Shannon entropy, applies Miller-Madow bias correction.
    Formula: H_MM = -sum(p_i * log2(p_i)) + (K_observed - 1) / (2N)
    Reference: Miller (1955), Nowozin (2014).

    Returns (entropy_bits, n_bins_observed).
    """
    import math as _math
    n = len(values)
    if n < 2:
        return (0.0, 0)
    # Discretize into bins
    counts: dict[int, int] = {}
    for v in values:
        b = int(v / bin_width)
        counts[b] = counts.get(b, 0) + 1
    k_observed = len(counts)
    if k_observed < 2:
        return (0.0, k_observed)  # single bin = perfectly predictable
    # Plugin Shannon entropy (bits)
    h = 0.0
    for c in counts.values():
        p = c / n
        if p > 0:
            h -= p * _math.log2(p)
    # Miller-Madow correction: (K-1) / (2N)
    h += (k_observed - 1) / (2 * n)
    return (max(h, 0.0), k_observed)


@pyscript_compile  # noqa: F821
def _fano_predictability(entropy: float, n_bins: int) -> float:
    """Predictability upper bound via Fano's inequality.

    Given entropy S (bits) and alphabet size N, finds Pi_max in (1/N, 1)
    such that: S = -Pi*log2(Pi) - (1-Pi)*log2(1-Pi) + (1-Pi)*log2(N-1).
    Solved by binary search (guaranteed convergence, monotonic function).
    Reference: Song et al. (2010), Fano (1961).

    Returns predictability score in [0.0, 1.0].
    """
    import math as _math
    # Edge cases
    if n_bins <= 1 or entropy <= 0.0:
        return 1.0
    max_entropy = _math.log2(n_bins)
    if entropy >= max_entropy:
        return 1.0 / n_bins
    # Binary search for Pi_max on (1/N, 1)
    lo = 1.0 / n_bins + 1e-10
    hi = 1.0 - 1e-10
    for _ in range(64):  # 64 iterations = ~19 decimal digits precision
        mid = (lo + hi) / 2.0
        # Compute H(Pi) + (1-Pi)*log2(N-1)
        h_pi = 0.0
        if mid > 0:
            h_pi -= mid * _math.log2(mid)
        if mid < 1:
            h_pi -= (1.0 - mid) * _math.log2(1.0 - mid)
        if n_bins > 2:
            h_pi += (1.0 - mid) * _math.log2(n_bins - 1)
        if h_pi > entropy:
            lo = mid  # need higher Pi (lower H)
        else:
            hi = mid
    return round((lo + hi) / 2.0, 6)


# ── I-40a: KDE Mode Detection (G7) ───────────────────────────────────────────

@pyscript_compile  # noqa: F821
def _kde_evaluate(x: float, data: list[float], bandwidth: float) -> float:
    """Evaluate Gaussian KDE at point x.

    KDE(x) = (1/nh) × Σ K((x-xᵢ)/h) where K is Gaussian kernel.
    Reference: Silverman (1986), Density Estimation for Statistics and Data Analysis.
    """
    n = len(data)
    if n == 0 or bandwidth <= 0:
        return 0.0
    sqrt_2pi = 2.5066282746310002  # math.sqrt(2 * math.pi)
    total = 0.0
    for xi in data:
        z = (x - xi) / bandwidth
        total += math.exp(-0.5 * z * z)
    return total / (n * bandwidth * sqrt_2pi)


@pyscript_compile  # noqa: F821
def _kde_find_modes(
    values: list[float],
    weights: list[float] | None = None,
    min_separation: float = 1.0,
) -> list[tuple[float, float]]:
    """Find modes (peaks) of return-time distribution using Gaussian KDE.

    Returns list of (mode_hour, density) sorted by density descending.
    min_separation: minimum hours between distinct modes (prevents noise peaks).

    Reference: Silverman (1981), bandwidth = 1.06 × σ × n^(-1/5).
    """
    if not values:
        return []
    if len(values) < 5:
        # Too few for meaningful KDE — single mode at weighted median
        if weights:
            med = _weighted_percentile(values, weights)
        else:
            s = sorted(values)
            med = s[len(s) // 2]
        return [(med, 1.0)]

    n = len(values)
    mean = sum(values) / n
    std = (sum([(v - mean) ** 2 for v in values]) / n) ** 0.5
    if std < 0.01:
        return [(mean, 1.0)]

    # Silverman bandwidth
    bandwidth = 1.06 * std * (n ** -0.2)

    # Evaluate KDE at fine grid across data range
    lo = min(values) - 2 * bandwidth
    hi = max(values) + 2 * bandwidth
    n_points = 200
    step = (hi - lo) / n_points
    grid = [lo + i * step for i in range(n_points + 1)]
    densities = [_kde_evaluate(x, values, bandwidth) for x in grid]

    # Find local maxima
    peaks = []
    for i in range(1, len(grid) - 1):
        if densities[i] > densities[i - 1] and densities[i] > densities[i + 1]:
            peaks.append((grid[i], densities[i]))

    if not peaks:
        # Monotonic — use global max
        max_idx = densities.index(max(densities))
        return [(grid[max_idx], densities[max_idx])]

    # Merge peaks closer than min_separation (keep higher density)
    peaks.sort(key=lambda p: -p[1])  # sort by density descending
    merged = []
    for peak_hour, peak_density in peaks:
        too_close = False
        for existing_hour, _ in merged:
            if abs(peak_hour - existing_hour) < min_separation:
                too_close = True
                break
        if not too_close:
            merged.append((peak_hour, peak_density))

    return merged


@pyscript_compile  # noqa: F821
def _select_best_mode(
    modes: list[tuple[float, float]],
    current_hour: float,
    elapsed_minutes: float,
) -> float:
    """Select the most likely return-time mode given current context.

    If multimodal:
    - If still early in trip: nearest future mode with highest density
    - If trip running long: latest mode (likely deeper activity)
    """
    if not modes:
        return 0.0
    if len(modes) == 1:
        return modes[0][0]

    # Filter to future modes (past modes already missed)
    future_modes = [(h, d) for h, d in modes if h > current_hour]
    if not future_modes:
        # All modes in past — return latest (highest hour)
        return max([m[0] for m in modes])

    # If early in trip (< 60 min), prefer nearest future mode
    # If late in trip (> 120 min), prefer highest-density future mode
    if elapsed_minutes < 60:
        return min(future_modes, key=lambda m: m[0])[0]
    else:
        return max(future_modes, key=lambda m: m[1])[0]


# ── I-40a: Empirical Mean Residual Life (G6) ─────────────────────────────────

@pyscript_compile  # noqa: F821
def _empirical_mrl(
    durations: list[float],
    elapsed_minutes: float,
    weights: list[float] | None = None,
) -> tuple[float, float, str]:
    """Empirical Mean Residual Life (Kaplan-Meier framework).

    For uncensored data: mrl(t₀) = weighted_mean(dᵢ - t₀) for dᵢ > t₀.
    Also returns std dev of remaining times for prediction interval.

    Returns (remaining_minutes, remaining_std, method_note).
    Reference: Hall & Wellner (1981), empirical MRL estimation.
    """
    if not durations or elapsed_minutes < 0:
        return (60.0, 30.0, "default_fallback")

    # Surviving trips: those that lasted ≥ elapsed
    surviving = []
    surviving_w = []
    for i, d in enumerate(durations):
        if d >= elapsed_minutes:
            surviving.append(d - elapsed_minutes)
            surviving_w.append(weights[i] if weights and i < len(weights) else 1.0)

    if not surviving:
        # No historical trip lasted this long — outlier trip
        max_dur = max(durations) if durations else 0
        overshoot = elapsed_minutes / max_dur if max_dur > 0 else 2.0
        if overshoot < 1.5:
            return (30.0, 15.0, "mild_outlier")
        else:
            return (15.0, 10.0, "extreme_outlier")

    # Weighted MRL
    total_w = sum(surviving_w)
    if total_w < 1e-9:
        return (surviving[0], 0.0, "single_survivor")

    mrl = sum([r * w for r, w in zip(surviving, surviving_w)]) / total_w

    # Weighted std dev of remaining times (for prediction interval)
    if len(surviving) >= 2:
        var = sum([w * (r - mrl) ** 2 for r, w in zip(surviving, surviving_w)]) / total_w
        std = var ** 0.5
    else:
        std = 0.0

    return (max(mrl, 5.0), std, "mrl_estimate")


# ── I-40a: Cross-Bucket Blending (G9) ────────────────────────────────────────

@pyscript_compile  # noqa: F821
def _circular_distance(h1: float, h2: float) -> float:
    """Distance between two hours on a 24-hour circle."""
    diff = abs(h1 - h2)
    return min(diff, 24.0 - diff)


@pyscript_compile  # noqa: F821
def _blend_buckets(
    departure_hour: float,
    person: str,
    day_type: str,
    duration_cache: dict,
    return_cache: dict,
) -> tuple[list[float], list[float], list[float]]:
    """Blend primary + adjacent bucket data weighted by proximity.

    Quadratic falloff from bucket center. Standard kernel smoothing approach.
    Returns (blended_durations, blended_returns, blend_weights).
    """
    primary_bucket = _get_time_bucket(int(departure_hour))
    primary_key = (person, primary_bucket, day_type)
    primary_dur = duration_cache.get(primary_key, [])
    primary_ret = return_cache.get(primary_key, [])

    if not primary_dur and not primary_ret:
        return ([], [], [])

    result_dur = list(primary_dur)
    result_ret = list(primary_ret)
    result_weights = [1.0] * len(primary_dur)

    for adj_bucket in BUCKET_ADJACENCY.get(primary_bucket, ()):
        adj_key = (person, adj_bucket, day_type)
        adj_dur = duration_cache.get(adj_key, [])
        adj_ret = return_cache.get(adj_key, [])
        if not adj_dur:
            continue
        dist = _circular_distance(departure_hour, BUCKET_CENTERS[adj_bucket])
        adj_weight = max(0.0, 1.0 - (dist / 6.0)) ** 2
        if adj_weight < 0.05:
            continue
        result_dur.extend(adj_dur)
        result_ret.extend(adj_ret)
        result_weights.extend([adj_weight] * len(adj_dur))

    return (result_dur, result_ret, result_weights)


# ── I-40a: Calendar Fusion v2 (G10) ──────────────────────────────────────────

@pyscript_compile  # noqa: F821
def _parse_calendar_events(calendar_summary: str) -> list[tuple[float | None, float | None]]:
    """Parse "09:00-10:00 Dentist | 14:00-15:00 Meeting" into [(9.0, 10.0), (14.0, 15.0)]."""
    if not calendar_summary:
        return []
    events = []
    for part in calendar_summary.split("|"):
        part = part.strip()
        if part.startswith("All day"):
            continue
        start_h = end_h = None
        found_range = False
        for sep in ("-", "\u2013", "\u2014"):
            if sep in part[:12]:
                time_parts = part.split(sep, 1)
                try:
                    sh, sm = time_parts[0].strip()[:5].split(":")
                    start_h = int(sh) + int(sm) / 60.0
                except (ValueError, IndexError):
                    break
                try:
                    eh, em = time_parts[1].strip()[:5].split(":")
                    end_h = int(eh) + int(em) / 60.0
                except (ValueError, IndexError):
                    pass
                found_range = True
                break
        if not found_range:
            try:
                sh, sm = part[:5].split(":")
                start_h = int(sh) + int(sm) / 60.0
            except (ValueError, IndexError):
                pass
        if start_h is not None:
            events.append((start_h, end_h))
    events.sort(key=lambda e: e[0] or 0)
    return events


@pyscript_compile  # noqa: F821
def _calendar_fusion_v2(
    predicted_return_hour: float,
    current_hour: float,
    calendar_summary: str,
    travel_buffer_min: float,
) -> tuple[float, str]:
    """Enhanced calendar fusion with gap detection and confirmation signal.

    Returns (adjusted_return_hour, method_note):
    - "no_calendar": no timed events
    - "calendar_confirms": all events end before prediction (higher confidence)
    - "calendar_gap_return": 2+ hour gap between events → possible home visit
    - "calendar_override": latest event end + buffer exceeds prediction
    """
    events = _parse_calendar_events(calendar_summary)
    if not events:
        return (predicted_return_hour, "no_calendar")

    buffer_h = travel_buffer_min / 60.0
    latest_end = None
    for _, end_h in events:
        if end_h is not None and (latest_end is None or end_h > latest_end):
            latest_end = end_h

    # (a) All events end before prediction → confirms historical
    if latest_end is not None and latest_end + buffer_h <= predicted_return_hour:
        return (predicted_return_hour, "calendar_confirms")

    # (b) Gap detection: 2+ hour gap → possible home visit
    if len(events) >= 2:
        for i in range(len(events) - 1):
            this_end = events[i][1]
            next_start = events[i + 1][0]
            if this_end is None or next_start is None:
                continue
            if next_start - this_end >= 2.0:
                gap_return = this_end + buffer_h
                if current_hour <= gap_return <= next_start - 0.5:
                    return (gap_return, "calendar_gap_return")

    # (c) Standard override: latest end + buffer > prediction
    if latest_end is not None:
        cal_return = latest_end + buffer_h
        if cal_return > predicted_return_hour and cal_return > current_hour:
            return (cal_return, "calendar_override")

    return (predicted_return_hour, "no_calendar")


@pyscript_compile  # noqa: F821
def _hour_to_time_str(hour: float) -> str:
    """Convert fractional hour (17.5) to time string ('17:30')."""
    h = int(hour)
    m = int((hour - h) * 60)
    return f"{h:02d}:{m:02d}"


# ── L2 Memory Helpers ────────────────────────────────────────────────────────

async def _l2_get(key: str) -> dict | None:
    """Exact-key lookup in L2 via memory_get."""
    try:
        result = pyscript.memory_get(key=key)  # noqa: F821
        return await result
    except Exception as exc:
        log.warning(f"away: L2 get failed key={key}: {exc}")  # noqa: F821
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
        log.warning(f"away: L2 set failed key={key}: {exc}")  # noqa: F821
        return False


async def _l2_forget(key: str) -> bool:
    """Delete entry from L2 via memory_forget."""
    try:
        result = pyscript.memory_forget(key=key)  # noqa: F821
        resp = await result
        return resp is not None and resp.get("status") == "ok"
    except Exception as exc:
        log.warning(f"away: L2 forget failed key={key}: {exc}")  # noqa: F821
        return False


async def _l2_search(query: str, limit: int = 200) -> list[dict[str, Any]]:
    """Search L2 via memory_search. Returns empty list on failure."""
    try:
        result = pyscript.memory_search(query=query, limit=limit)  # noqa: F821
        resp = await result
        if resp and resp.get("status") == "ok":
            return resp.get("results", [])
    except Exception as exc:
        log.warning(f"away: L2 search failed query={query}: {exc}")  # noqa: F821
    return []


# ── Cache Management ─────────────────────────────────────────────────────────

async def _load_cache_from_l2() -> int:
    """Load away pattern cache from L2 memory. Returns number of entries loaded."""
    global _local_duration_cache, _local_return_cache, _local_count_cache
    loaded = 0

    # Resolve valid persons once (outside @pyscript_compile context)
    _valid = set(get_person_slugs())

    for query_tag in ("away duration", "away return", "away count"):
        results = await _l2_search(query_tag, limit=200)
        for entry in results:
            key = entry.get("key", "")
            value = entry.get("value", "")
            if not value:
                continue
            try:
                data = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                continue

            if key.startswith("away_durations_"):
                parts = _parse_away_key(key, "away_durations_", _valid)
                if parts and isinstance(data, list):
                    _local_duration_cache[parts] = data
                    loaded += 1
            elif key.startswith("away_returns_"):
                parts = _parse_away_key(key, "away_returns_", _valid)
                if parts and isinstance(data, list):
                    _local_return_cache[parts] = data
                    loaded += 1
            elif key.startswith("away_daily_counts_"):
                rest = key[len("away_daily_counts_"):]
                # Format: {person}_{day_type}
                for dt in ("weekday", "weekend"):
                    if rest.endswith("_" + dt):
                        person = rest[:-(len(dt) + 1)]
                        if person in _valid and isinstance(data, dict):
                            _local_count_cache[(person, dt)] = data
                            loaded += 1
                        break

    return loaded


@pyscript_compile  # noqa: F821
def _parse_away_key(key: str, prefix: str, valid_persons: set) -> tuple[str, str, str] | None:
    """Parse L2 key → (person, bucket, day_type).

    Key format after normalization: {prefix}{person}_{bucket}_{day_type}
    valid_persons: set of person slugs (passed from caller — @pyscript_compile
    cannot call pyscript-aware functions like get_person_slugs()).
    """
    rest = key[len(prefix):]
    # Parse day_type from end
    for dt in ("weekday", "weekend"):
        if rest.endswith("_" + dt):
            rest2 = rest[:-(len(dt) + 1)]
            # Parse bucket from end
            for tb in ("late_night", "morning", "afternoon", "evening"):
                if rest2.endswith("_" + tb):
                    person = rest2[:-(len(tb) + 1)]
                    if person in valid_persons:
                        return (person, tb, dt)
            break
    return None


# ── Settings Helpers ─────────────────────────────────────────────────────────

def _is_test_mode() -> bool:
    try:
        return str(state.get("input_boolean.ai_test_mode") or "off").lower() == "on"  # noqa: F821
    except NameError:
        return False


def _is_enabled() -> bool:
    try:
        return str(  # noqa: F821
            state.get("input_boolean.ai_away_patterns_enabled") or "on"  # noqa: F821
        ).lower() == "on"
    except NameError:
        return True


def _get_lookback_days() -> int:
    try:
        return int(float(
            state.get("input_number.ai_away_pattern_lookback_days") or 30  # noqa: F821
        ))
    except (ValueError, TypeError, NameError):
        return 30


def _get_min_samples() -> int:
    try:
        return int(float(
            state.get("input_number.ai_away_pattern_min_samples") or 5  # noqa: F821
        ))
    except (ValueError, TypeError, NameError):
        return 5


def _get_travel_buffer() -> float:
    try:
        return float(
            state.get("input_number.ai_away_travel_buffer_minutes") or 30  # noqa: F821
        )
    except (ValueError, TypeError, NameError):
        return 30.0


def _get_debounce_seconds() -> int:
    """Read debounce duration from helper (G14). Default 300s."""
    try:
        return int(float(
            state.get("input_number.ai_away_flap_debounce_seconds") or 300  # noqa: F821
        ))
    except (ValueError, TypeError, NameError):
        return 300


def _get_update_interval() -> int:
    """Read prediction update interval from helper (G8). Default 15 min."""
    try:
        return int(float(
            state.get("input_number.ai_away_prediction_update_minutes") or 15  # noqa: F821
        ))
    except (ValueError, TypeError, NameError):
        return 15


def _update_helper(entity_id: str, value: str) -> None:
    """Update an input_text helper, truncating to 255 chars."""
    try:
        service.call(  # noqa: F821
            "input_text", "set_value",
            entity_id=entity_id, value=str(value)[:255],
        )
    except Exception:
        pass


# ── Store Tables to L2 ──────────────────────────────────────────────────────

async def _store_tables(
    duration_tables: dict[tuple[str, str, str], list[float]],
    return_tables: dict[tuple[str, str, str], list[float]],
    count_tables: dict[tuple[str, str], dict[str, float]],
) -> int:
    """Store frequency tables to L2 memory. Returns number of entries stored."""
    global _local_duration_cache, _local_return_cache, _local_count_cache
    stored = 0

    for key, values in duration_tables.items():
        person, bucket, day_type = key
        # Trim to max history, keeping most recent
        trimmed = values[-MAX_HISTORY_PER_BUCKET:]
        l2_key = f"away:durations:{person}:{bucket}:{day_type}"
        ok = await _l2_set(
            l2_key, json.dumps(trimmed),
            tags=f"away duration {person}",
        )
        if ok:
            _local_duration_cache[key] = trimmed
            stored += 1

    for key, values in return_tables.items():
        person, bucket, day_type = key
        trimmed = values[-MAX_HISTORY_PER_BUCKET:]
        l2_key = f"away:returns:{person}:{bucket}:{day_type}"
        ok = await _l2_set(
            l2_key, json.dumps(trimmed),
            tags=f"away return {person}",
        )
        if ok:
            _local_return_cache[key] = trimmed
            stored += 1

    for key, counts in count_tables.items():
        person, day_type = key
        l2_key = f"away:daily_counts:{person}:{day_type}"
        ok = await _l2_set(
            l2_key, json.dumps(counts),
            tags=f"away count {person}",
        )
        if ok:
            _local_count_cache[key] = counts
            stored += 1

    return stored


# ── I-40a: Household Correlation (G11) ───────────────────────────────────────

async def _check_joint_departure(person: str) -> str | None:
    """If both people departed within 10 min, return the other person's name."""
    if len(_departure_ts) < 2:
        return None
    other = [p for p in _departure_ts if p != person]
    if not other:
        return None
    other_p = other[0]
    # I-40b: _departure_ts is now list — use last entry for delta
    my_ts = _departure_ts[person][-1] if _departure_ts.get(person) else 0
    other_ts = _departure_ts[other_p][-1] if _departure_ts.get(other_p) else 0
    delta = abs(my_ts - other_ts)
    if delta <= JOINT_TRIP_THRESHOLD_SEC:
        return other_p
    return None


# ── I-40a: Accuracy Tracking (G12) ──────────────────────────────────────────

async def _log_prediction_accuracy(person: str, actual_return_hour: float,
                                    bucket: str = "", day_type: str = ""):
    """Log prediction accuracy for rolling MAE calculation.

    Also writes per-arrival entropy+MAE entry to L2 for G13 Phase 1.5
    correlation analysis (when entropy was computed and kill switch is ON).
    """
    global _prediction_log
    try:
        # I-54: Read from pyscript sensor attributes instead of input_text
        preds = state.getattr("sensor.ai_away_prediction")  # noqa: F821
        if not preds or not preds.get("predictions"):
            return
        pred_list = preds.get("predictions", [])
        for pred in pred_list:
            if pred.get("person") == person and pred.get("predicted_return_time"):
                # Parse predicted time
                ph, pm = pred["predicted_return_time"].split(":")
                predicted_hour = int(ph) + int(pm) / 60.0
                error_min = abs(actual_return_hour - predicted_hour) * 60.0
                entry = {
                    "person": person,
                    "predicted": predicted_hour,
                    "actual": actual_return_hour,
                    "error_min": round(error_min, 1),
                    "method": pred.get("method", "unknown"),
                }
                _prediction_log.append(entry)
                # Keep last 100 entries
                if len(_prediction_log) > 100:
                    _prediction_log.pop(0)
                # Update accuracy helper
                if len(_prediction_log) >= 5:
                    errors = [e["error_min"] for e in _prediction_log[-20:]]
                    mae = round(sum(errors) / len(errors), 1)
                    _update_helper(
                        "input_text.ai_away_prediction_accuracy",
                        f"MAE: {mae} min (last {len(errors)} trips)",
                    )

                # ── G13 Phase 1.5: Per-arrival entropy+MAE to L2 ──
                try:
                    be = float(pred.get("bucket_entropy", 0.0))
                    corr_on = str(
                        state.get("input_boolean.ai_entropy_correlation_enabled")  # noqa: F821
                        or "off"
                    ).lower()
                    if be > 0.0 and corr_on == "on":
                        ts_now = datetime.utcnow().isoformat(timespec="seconds")
                        g13_val = json.dumps({
                            "bucket_entropy": be,
                            "predictability": pred.get("predictability", 0.0),
                            "error_min": round(error_min, 1),
                            "confidence": pred.get("confidence", 0),
                            "method": pred.get("method", "unknown"),
                            "sample_count": pred.get("sample_count", 0),
                            "bucket": bucket,
                            "day_type": day_type,
                            "trip_ordinal": pred.get("trip_ordinal", 1),
                            "timestamp": ts_now,
                        })
                        await _l2_set(
                            key=f"g13_arrival:{person}:{ts_now}",
                            value=g13_val,
                            tags=f"g13 entropy arrival {person}",
                            expiration_days=120,
                        )
                except Exception as g13_exc:
                    log.warning(f"away: G13 L2 write failed: {g13_exc}")  # noqa: F821

                break
    except Exception:
        pass


# ── Services ─────────────────────────────────────────────────────────────────

@service(supports_response="only")  # noqa: F821
async def away_extract_cycles(lookback_days=0):
    """Extract away cycles from recorder DB and build frequency tables.

    Args:
        lookback_days: Days of recorder history to query (0 = use helper).
    """
    try:
        test_mode = _is_test_mode()
        days = int(lookback_days) if lookback_days else _get_lookback_days()

        if test_mode:
            log.info(f"away [TEST]: extract_cycles lookback={days}d")  # noqa: F821

        _set_result("extracting", operation="extract", lookback_days=days)

        trackers = _get_person_trackers()
        entity_ids = list(trackers.values())
        tracker_person = {v: k for k, v in trackers.items()}

        raw = _extract_cycles_sync(days, entity_ids, tracker_person)

        cycles = raw.get("cycles", [])
        if not cycles:
            _set_result("ok", operation="extract", cycles_found=0,
                         total_states=raw.get("total_states", 0))
            return {
                "status": "ok", "cycles_found": 0,
                "total_states": raw.get("total_states", 0),
                "per_person": {p: 0 for p in get_person_slugs()},
            }

        duration_tables, return_tables, count_tables = _build_tables(cycles)
        stored = await _store_tables(duration_tables, return_tables, count_tables)

        per_person = {}
        for person in get_person_slugs():
            count = 0
            for c in cycles:
                if c["person"] == person:
                    count += 1
            per_person[person] = count

        _set_result("ok", operation="extract", cycles_found=len(cycles),
                     stored=stored, total_states=raw.get("total_states", 0),
                     per_person=per_person)

        if test_mode:
            log.info(  # noqa: F821
                f"away [TEST]: found {len(cycles)} cycles, stored {stored} patterns. "
                f"Per person: {per_person}"
            )

        return {
            "status": "ok",
            "cycles_found": len(cycles),
            "stored": stored,
            "total_states": raw.get("total_states", 0),
            "per_person": per_person,
        }
    except Exception as exc:
        log.error(f"away: extract_cycles failed: {exc}")  # noqa: F821
        try:
            _set_result("error", error=str(exc))
        except Exception:
            pass
        return {"status": "error", "error": str(exc)}


@service(supports_response="only")  # noqa: F821
async def away_predict_return(person=""):
    """Predict return time for absent person(s).

    Args:
        person: Person slug (empty = predict for whoever is away).
    """
    try:
        return await _predict_return_inner(person)
    except Exception as exc:
        log.error(f"away: predict_return failed: {exc}")  # noqa: F821
        return {"status": "error", "error": str(exc)}


async def _predict_return_inner(person=""):
    """Full prediction pipeline (I-40a hardened).

    Pipeline:
    1. Determine departure bucket + hour
    2. _blend_buckets() → expanded data pool (G9)
    3. _filter_outliers() on returns + durations (G2)
    4. _compute_decay_weights() (G3)
    5. _kde_find_modes() on filtered returns (G7)
       → if multimodal: _select_best_mode() for point estimate
       → if unimodal: _weighted_percentile() for point estimate
    6. _weighted_std_dev() → prediction interval ±1σ (G4)
    7. _get_confidence() with spread adjustment (G5)
    8. _calendar_fusion_v2() → shift or confirm (G10)
    9. If predicted < current_hour:
       _empirical_mrl() → conditional remaining time (G6)
    10. _check_joint_departure() → sync predictions (G11)
    11. Output: {predicted_return_time, confidence, range_low, range_high, method, ...}
    """
    test_mode = _is_test_mode()
    min_samples = _get_min_samples()
    travel_buffer = _get_travel_buffer()
    now = datetime.now()
    current_hour = now.hour + now.minute / 60.0
    current_day_type = _get_day_type(now.weekday())

    # Determine who is away
    persons_to_predict = []
    if person:
        persons_to_predict = [person]
    else:
        for p, tracker in _get_person_trackers().items():
            try:
                tracker_state = str(state.get(tracker) or "unknown")  # noqa: F821
            except NameError:
                tracker_state = "unknown"
            if tracker_state == "not_home":
                persons_to_predict.append(p)

    if not persons_to_predict:
        # Nobody is away — clear prediction (I-54: pyscript sensor + L2)
        try:
            state.set("sensor.ai_away_prediction", value="not_away", new_attributes={  # noqa: F821
                "friendly_name": "AI Away Prediction",
                "icon": "mdi:home-clock-outline",
                "person": "none", "predictions": [],
            })
            for _p in get_person_slugs():
                pyscript.memory_forget(key=f"away_pred:{_p}")  # noqa: F821
        except Exception:
            pass
        return {"status": "ok", "message": "nobody_away"}

    # Get calendar data for fusion
    cal_summary = ""
    try:
        cal_summary = str(
            state.get("input_text.ai_calendar_today_summary") or ""  # noqa: F821
        )
    except NameError:
        pass

    predictions = []
    for p in persons_to_predict:
        # ── Step 1: Determine departure bucket + hour ──
        dep_hour = current_hour
        dep_bucket = _get_time_bucket(now.hour)
        elapsed_minutes = 0.0
        dep_entity = f"input_datetime.ai_away_departed_{p}"
        try:
            dep_str = str(state.get(dep_entity) or "")  # noqa: F821
            if dep_str and dep_str not in ("unknown", "unavailable", "",
                                            "1970-01-01 00:00:00"):
                dep_dt = datetime.fromisoformat(dep_str)
                dep_hour = dep_dt.hour + dep_dt.minute / 60.0
                dep_bucket = _get_time_bucket(dep_dt.hour)
                elapsed_minutes = (time.time() - dep_dt.timestamp()) / 60.0
        except (NameError, ValueError):
            pass

        # Also check module-level departure timestamp (I-40b: list — use first entry)
        if p in _departure_ts and _departure_ts[p] and elapsed_minutes <= 0:
            elapsed_minutes = (time.time() - _departure_ts[p][0]) / 60.0

        # ── Step 2: Blend buckets (G9) ──
        blended_dur, blended_ret, blend_weights = _blend_buckets(
            dep_hour, p, current_day_type,
            _local_duration_cache, _local_return_cache,
        )

        # Fallback: try loading from L2 if cache empty
        if not blended_dur and not blended_ret:
            cache_key = (p, dep_bucket, current_day_type)
            l2_dur = await _l2_get(f"away:durations:{p}:{dep_bucket}:{current_day_type}")
            if l2_dur and l2_dur.get("value"):
                try:
                    _local_duration_cache[cache_key] = json.loads(l2_dur["value"])
                except (json.JSONDecodeError, TypeError):
                    pass
            l2_ret = await _l2_get(f"away:returns:{p}:{dep_bucket}:{current_day_type}")
            if l2_ret and l2_ret.get("value"):
                try:
                    _local_return_cache[cache_key] = json.loads(l2_ret["value"])
                except (json.JSONDecodeError, TypeError):
                    pass
            # Re-blend after loading
            blended_dur, blended_ret, blend_weights = _blend_buckets(
                dep_hour, p, current_day_type,
                _local_duration_cache, _local_return_cache,
            )

        # ── Step 2b: Ordinal-aware filtering (I-40b) ──
        # Read current trip ordinal from HA counter
        counter_entity = f"counter.ai_away_trip_count_{p}"
        try:
            _completed = int(float(state.get(counter_entity) or 0))  # noqa: F821
        except (ValueError, TypeError):
            _completed = 0
        trip_ordinal = _completed + 1

        # Read ordinal min_samples threshold from helper
        try:
            ordinal_min = int(float(
                state.get("input_number.ai_away_ordinal_min_samples") or 5  # noqa: F821
            ))
        except (ValueError, TypeError):
            ordinal_min = 5

        # Filter by ordinal (extracts clean floats from mixed arrays)
        ordinal_dur, ordinal_dur_w = _filter_by_ordinal_with_weights(
            blended_dur, blend_weights, trip_ordinal, "d", ordinal_min,
        )
        ordinal_ret, ordinal_ret_w = _filter_by_ordinal_with_weights(
            blended_ret, blend_weights, trip_ordinal, "r", ordinal_min,
        )
        ordinal_sample_count = len(ordinal_ret)

        # Compute trip probability from daily counts
        count_key = (p, current_day_type)
        day_counts = _local_count_cache.get(count_key, {})
        ordinal_dist = day_counts.get("ordinal_dist", {})
        _ord_this = ordinal_dist.get(str(trip_ordinal), 0)
        _ord_next = ordinal_dist.get(str(trip_ordinal + 1), 0)
        prob_another_trip = round(_ord_next / max(_ord_this, 1), 2)

        # Use ordinal-filtered data for downstream pipeline
        blended_dur = ordinal_dur
        blended_ret = ordinal_ret
        blend_weights = ordinal_dur_w  # weights aligned to filtered data

        sample_count = len(blended_ret)

        if sample_count < 1:
            predictions.append({
                "person": p,
                "predicted_return_time": "",
                "confidence": "insufficient",
                "avg_duration_min": 0,
                "sample_count": 0,
                "method": "no_data",
                "trip_ordinal": trip_ordinal,
                "ordinal_sample_count": 0,
                "prob_another_trip": prob_another_trip,
                # G13 Phase 1: observe only
                "bucket_entropy": 0.0,
                "predictability": 0.0,
            })
            continue

        # Wire up min_samples gate
        if sample_count < min_samples:
            predictions.append({
                "person": p,
                "predicted_return_time": "",
                "confidence": "insufficient",
                "avg_duration_min": 0,
                "sample_count": sample_count,
                "method": "insufficient_samples",
                "trip_ordinal": trip_ordinal,
                "ordinal_sample_count": ordinal_sample_count,
                "prob_another_trip": prob_another_trip,
                # G13 Phase 1: observe only
                "bucket_entropy": 0.0,
                "predictability": 0.0,
            })
            continue

        # ── Step 3: Filter outliers (G2) ──
        filtered_ret = _filter_outliers(blended_ret)
        filtered_dur = _filter_outliers(blended_dur)

        # Rebuild weights to match filtered data (preserve alignment)
        # Since _filter_outliers preserves chronological order but may remove items,
        # we need to match weights. Use positional tracking.
        ret_set = set()
        filtered_ret_weights = []
        for i, v in enumerate(blended_ret):
            if v in filtered_ret and i not in ret_set:
                w = blend_weights[i] if i < len(blend_weights) else 1.0
                filtered_ret_weights.append(w)
                ret_set.add(i)
                if len(filtered_ret_weights) >= len(filtered_ret):
                    break

        dur_set = set()
        filtered_dur_weights = []
        for i, v in enumerate(blended_dur):
            if v in filtered_dur and i not in dur_set:
                w = blend_weights[i] if i < len(blend_weights) else 1.0
                filtered_dur_weights.append(w)
                dur_set.add(i)
                if len(filtered_dur_weights) >= len(filtered_dur):
                    break

        # ── Step 4: Compute decay weights (G3) ──
        n_ret = len(filtered_ret)
        n_dur = len(filtered_dur)
        decay_ret = _compute_decay_weights(n_ret)
        decay_dur = _compute_decay_weights(n_dur)

        # Combine blend weights × decay weights
        final_ret_weights = [
            filtered_ret_weights[i] * decay_ret[i] if i < len(filtered_ret_weights) else decay_ret[i]
            for i in range(n_ret)
        ]
        final_dur_weights = [
            filtered_dur_weights[i] * decay_dur[i] if i < len(filtered_dur_weights) else decay_dur[i]
            for i in range(n_dur)
        ]

        # ── Step 5: KDE mode detection (G7) ──
        modes = _kde_find_modes(filtered_ret, final_ret_weights)
        if len(modes) > 1:
            predicted_return_hour = _select_best_mode(modes, current_hour, elapsed_minutes)
            method = "kde_multimodal"
        else:
            predicted_return_hour = _weighted_percentile(filtered_ret, final_ret_weights)
            method = "historical"

        # ── Step 6: Prediction interval ±1σ (G4) ──
        std_dev = _weighted_std_dev(filtered_ret, final_ret_weights)
        range_low_hour = predicted_return_hour - std_dev
        range_high_hour = predicted_return_hour + std_dev

        # ── Step 7: Spread-adjusted confidence (G5) ──
        confidence = _get_confidence(
            sample_count, CONFIDENCE_HIGH, CONFIDENCE_MEDIUM, std_dev,
        )

        avg_duration = round(sum(filtered_dur) / len(filtered_dur), 1) if filtered_dur else 0

        # ── Step 7b: Entropy-based predictability (G13 Phase 1 — observe only) ──
        bucket_entropy = 0.0
        predictability = 0.0
        entropy_n_bins = 0
        min_entropy_n = int(float(
            state.get("input_number.ai_away_min_entropy_samples") or 50  # noqa: F821
        ))
        if sample_count >= min_entropy_n and filtered_ret:
            bucket_entropy, entropy_n_bins = _shannon_entropy_mm(
                filtered_ret, ENTROPY_BIN_WIDTH,
            )
            predictability = _fano_predictability(
                bucket_entropy, max(entropy_n_bins, 2),
            )

        # ── Step 8: Calendar fusion v2 (G10) ──
        if cal_summary:
            fused_hour, cal_method = _calendar_fusion_v2(
                predicted_return_hour, current_hour, cal_summary, travel_buffer,
            )
            if cal_method != "no_calendar":
                predicted_return_hour = fused_hour
                method = cal_method
                # Adjust range if calendar shifted the prediction
                if fused_hour > range_high_hour:
                    range_high_hour = fused_hour + std_dev * 0.5
                    range_low_hour = fused_hour - std_dev

        # ── Step 9: MRL for late predictions (G6, G8) ──
        if predicted_return_hour < current_hour and filtered_dur:
            mrl_remaining, mrl_std, mrl_note = _empirical_mrl(
                filtered_dur, elapsed_minutes, final_dur_weights,
            )
            predicted_return_hour = current_hour + mrl_remaining / 60.0
            range_low_hour = current_hour + max(mrl_remaining - mrl_std, 5.0) / 60.0
            range_high_hour = current_hour + (mrl_remaining + mrl_std) / 60.0
            method = mrl_note

        # Cap at 23:59
        predicted_return_hour = min(predicted_return_hour, 23.99)
        range_low_hour = max(range_low_hour, 0.0)
        range_high_hour = min(range_high_hour, 23.99)

        # Ensure range_low <= predicted <= range_high
        range_low_hour = min(range_low_hour, predicted_return_hour)
        range_high_hour = max(range_high_hour, predicted_return_hour)

        pred_dict = {
            "person": p,
            "predicted_return_time": _hour_to_time_str(predicted_return_hour),
            "confidence": confidence,
            "range_low": _hour_to_time_str(range_low_hour),
            "range_high": _hour_to_time_str(range_high_hour),
            "avg_duration_min": avg_duration,
            "sample_count": sample_count,
            "method": method,
            # I-40b: multi-trip awareness
            "trip_ordinal": trip_ordinal,
            "ordinal_sample_count": ordinal_sample_count,
            "prob_another_trip": prob_another_trip,
            # G13 Phase 1: observe only
            "bucket_entropy": round(bucket_entropy, 4),
            "predictability": predictability,
        }

        predictions.append(pred_dict)

    # ── Step 10: Household correlation (G11) ──
    if len(predictions) == 2:
        p0, p1 = predictions[0], predictions[1]
        if (p0.get("predicted_return_time") and p1.get("predicted_return_time")
                and p0.get("method") != "no_data" and p1.get("method") != "no_data"):
            joint = await _check_joint_departure(persons_to_predict[0])
            if joint:
                # Use prediction with more samples
                if p0["sample_count"] >= p1["sample_count"]:
                    p1["predicted_return_time"] = p0["predicted_return_time"]
                    p1["range_low"] = p0.get("range_low", "")
                    p1["range_high"] = p0.get("range_high", "")
                    p1["method"] = "joint_trip"
                    p1["confidence"] = p0["confidence"]
                else:
                    p0["predicted_return_time"] = p1["predicted_return_time"]
                    p0["range_low"] = p1.get("range_low", "")
                    p0["range_high"] = p1.get("range_high", "")
                    p0["method"] = "joint_trip"
                    p0["confidence"] = p1["confidence"]

    # ── Step 11: Update sensor + persist to L2 (I-54) ──
    if not test_mode:
        try:
            # Persist each prediction to L2 memory (survives restarts)
            for pred in predictions:
                person = pred.get("person", "unknown")
                pred_json = json.dumps(pred)
                pyscript.memory_set(  # noqa: F821
                    key=f"away_pred:{person}", value=pred_json,
                    scope="system", tags=f"away prediction {person}",
                    expiration_days=1, force_new=True,
                )

            # Set pyscript sensor with full attributes (no 255-char limit)
            if len(predictions) == 1:
                p = predictions[0]
                summary = f"{p['person']} ~{p.get('predicted_return_time', '?')} ({p.get('confidence', 'low')})"
                state.set("sensor.ai_away_prediction", value=summary, new_attributes={  # noqa: F821
                    "friendly_name": "AI Away Prediction",
                    "icon": "mdi:home-clock-outline",
                    "person": p.get("person", "unknown"),
                    "predicted_return_time": p.get("predicted_return_time", ""),
                    "confidence": p.get("confidence", "unknown"),
                    "range_low": p.get("range_low", ""),
                    "range_high": p.get("range_high", ""),
                    "method": p.get("method", "unknown"),
                    "avg_duration_min": p.get("avg_duration_min", 0),
                    "sample_count": p.get("sample_count", 0),
                    "predictions": predictions,
                })
            else:
                parts = [f"{p['person']} ~{p.get('predicted_return_time', '?')}" for p in predictions]
                summary = ", ".join(parts)
                state.set("sensor.ai_away_prediction", value=summary, new_attributes={  # noqa: F821
                    "friendly_name": "AI Away Prediction",
                    "icon": "mdi:home-clock-outline",
                    "person": ", ".join([p.get("person", "?") for p in predictions]),
                    "predictions": predictions,
                })
        except Exception:
            pass
    else:
        log.info(f"away [TEST]: prediction = {json.dumps(predictions)}")  # noqa: F821

    if len(predictions) == 1:
        return {"status": "ok", **predictions[0]}
    return {"status": "ok", "predictions": predictions}


@service(supports_response="only")  # noqa: F821
async def away_rebuild_patterns():
    """Full rebuild: delete old away patterns, re-extract from recorder, re-store."""
    global _rebuild_in_progress, _local_duration_cache, _local_return_cache, _local_count_cache
    if _rebuild_in_progress:
        return {"status": "skipped", "reason": "rebuild_in_progress"}

    _rebuild_in_progress = True
    try:
        test_mode = _is_test_mode()
        _set_result("rebuilding", operation="rebuild")

        # Delete old L2 entries
        deleted = 0
        for tag in ("away duration", "away return", "away count", "away departure"):
            results = await _l2_search(tag, limit=200)
            for entry in results:
                key = entry.get("key", "")
                if key:
                    ok = await _l2_forget(key)
                    if ok:
                        deleted += 1

        # Clear local caches
        _local_duration_cache.clear()
        _local_return_cache.clear()
        _local_count_cache.clear()

        # I-40b: Reset daily trip counters
        for person in get_person_slugs():
            counter_entity = f"counter.ai_away_trip_count_{person}"
            try:
                service.call("counter", "reset", entity_id=counter_entity)  # noqa: F821
            except Exception:
                pass

        if test_mode:
            log.info(f"away [TEST]: rebuild deleted {deleted} L2 entries")  # noqa: F821

        # Re-extract
        result = await away_extract_cycles(lookback_days=0)

        _set_result("ok", operation="rebuild", deleted=deleted,
                     cycles_found=result.get("cycles_found", 0),
                     stored=result.get("stored", 0))

        return {
            "status": "ok",
            "deleted": deleted,
            "cycles_found": result.get("cycles_found", 0),
            "stored": result.get("stored", 0),
        }
    except Exception as exc:
        log.error(f"away: rebuild failed: {exc}")  # noqa: F821
        return {"status": "error", "error": str(exc)}
    finally:
        _rebuild_in_progress = False


# ── State Triggers (G14: Split departure/arrival, debounced departure) ───────

def _tracker_trigger_factory(entity_id):
    """Create a @state_trigger for a single WiFi tracker entity."""
    @state_trigger(entity_id)  # noqa: F821
    async def _trig(**kwargs):
        await _on_tracker_change(**kwargs)
    return _trig


async def _on_tracker_change(**kwargs):
    """Handle device_tracker state changes for departure/arrival logging.

    G14: Departure is debounced — waits for state to remain not_home for
    configurable duration (ai_away_flap_debounce_seconds). Arrival is immediate.
    """
    if not _is_enabled():
        return

    entity_id = kwargs.get("var_name", "")
    new_state = kwargs.get("value", "")
    old_state = kwargs.get("old_value", "")

    person = _get_tracker_to_person().get(entity_id)
    if not person:
        return

    test_mode = _is_test_mode()

    if old_state == "home" and new_state == "not_home":
        # ── DEPARTURE (debounced — G14) ──────────────────────────────
        debounce = _get_debounce_seconds()
        if debounce > 0:
            await asyncio.sleep(debounce)
            # Verify still not_home after debounce
            try:
                current = str(state.get(entity_id) or "home")  # noqa: F821
            except NameError:
                current = "home"
            if current != "not_home":
                if test_mode:
                    log.info(  # noqa: F821
                        f"away [TEST]: {person} debounce abort — "
                        f"returned to {current} within {debounce}s"
                    )
                return  # WiFi flap — abort

        now = datetime.now()
        ts = time.time()

        # I-40b: append to FIFO departure queue (not scalar overwrite)
        if person not in _departure_ts:
            _departure_ts[person] = []
        _departure_ts[person].append(ts)

        # I-40b: read trip ordinal from HA counter (persists across restarts)
        counter_entity = f"counter.ai_away_trip_count_{person}"
        try:
            completed_trips = int(float(state.get(counter_entity) or 0))  # noqa: F821
        except (ValueError, TypeError):
            completed_trips = 0
        trip_ordinal = completed_trips + 1

        departure_data = {
            "ts": ts,
            "bucket": _get_time_bucket(now.hour),
            "day_type": _get_day_type(now.weekday()),
            "day_of_week": now.strftime("%A").lower(),
            "ordinal": trip_ordinal,  # I-40b
        }

        if test_mode:
            log.info(  # noqa: F821
                f"away [TEST]: {person} departed at {now.isoformat()} "
                f"(trip #{trip_ordinal})"
            )
        else:
            # Set departure timestamp helper
            dep_entity = f"input_datetime.ai_away_departed_{person}"
            try:
                service.call(  # noqa: F821
                    "input_datetime", "set_datetime",
                    entity_id=dep_entity,
                    datetime=now.strftime("%Y-%m-%d %H:%M:%S"),
                )
            except Exception:
                pass

            # Log departure to L2
            await _l2_set(
                f"away:last_departure:{person}",
                json.dumps(departure_data),
                tags=f"away departure {person}",
                expiration_days=30,
            )

        # Run prediction after a short delay (let occupancy_mode settle)
        await asyncio.sleep(10)
        await away_predict_return(person=person)

    elif old_state == "not_home" and new_state == "home":
        # ── ARRIVAL (immediate — no debounce) ────────────────────────
        ts = time.time()

        # I-40b: FIFO pop from departure queue
        dep_list = _departure_ts.get(person, [])
        dep_ts = dep_list.pop(0) if dep_list else None
        if not dep_list:
            _departure_ts.pop(person, None)

        now = datetime.now()

        # I-40b: read trip ordinal from counter
        counter_entity = f"counter.ai_away_trip_count_{person}"
        try:
            completed_trips = int(float(state.get(counter_entity) or 0))  # noqa: F821
        except (ValueError, TypeError):
            completed_trips = 0
        trip_ordinal = completed_trips + 1

        if dep_ts is not None:
            duration_sec = ts - dep_ts
            if duration_sec >= MIN_AWAY_DURATION_SEC:
                dep_dt = datetime.fromtimestamp(dep_ts)
                ret_dt = datetime.fromtimestamp(ts)
                bucket = _get_time_bucket(dep_dt.hour)
                day_type = _get_day_type(dep_dt.weekday())
                cache_key = (person, bucket, day_type)

                # Append to local cache
                duration_min = round(duration_sec / 60.0, 1)
                return_hour = ret_dt.hour + ret_dt.minute / 60.0

                if cache_key not in _local_duration_cache:
                    _local_duration_cache[cache_key] = []
                if cache_key not in _local_return_cache:
                    _local_return_cache[cache_key] = []

                # I-40b: enriched samples for ordinal > 1, bare floats for ordinal 1
                if trip_ordinal == 1:
                    _local_duration_cache[cache_key].append(duration_min)
                    _local_return_cache[cache_key].append(return_hour)
                else:
                    _local_duration_cache[cache_key].append(
                        {"d": duration_min, "o": trip_ordinal}
                    )
                    _local_return_cache[cache_key].append(
                        {"r": return_hour, "o": trip_ordinal}
                    )

                # Persist to L2
                dur_key = f"away:durations:{person}:{bucket}:{day_type}"
                trimmed_dur = _local_duration_cache[cache_key][-MAX_HISTORY_PER_BUCKET:]
                await _l2_set(dur_key, json.dumps(trimmed_dur),
                              tags=f"away duration {person}")

                ret_key = f"away:returns:{person}:{bucket}:{day_type}"
                trimmed_ret = _local_return_cache[cache_key][-MAX_HISTORY_PER_BUCKET:]
                await _l2_set(ret_key, json.dumps(trimmed_ret),
                              tags=f"away return {person}")

                # I-40b: increment trip counter (atomic, persistent)
                try:
                    service.call(  # noqa: F821
                        "counter", "increment",
                        entity_id=counter_entity,
                    )
                except Exception:
                    log.warning(  # noqa: F821
                        f"away: failed to increment {counter_entity}"
                    )

                if test_mode:
                    log.info(  # noqa: F821
                        f"away [TEST]: {person} returned after {duration_min:.0f} min "
                        f"(bucket={bucket}, day_type={day_type}, trip #{trip_ordinal})"
                    )

                # G12: Log prediction accuracy (+ G13 Phase 1.5 L2 entry)
                await _log_prediction_accuracy(person, return_hour, bucket, day_type)

        if not test_mode:
            # Clear prediction (I-54: pyscript sensor + L2)
            try:
                state.set("sensor.ai_away_prediction", value="not_away", new_attributes={  # noqa: F821
                    "friendly_name": "AI Away Prediction",
                    "icon": "mdi:home-clock-outline",
                    "person": "none", "predictions": [],
                })
                for _p in get_person_slugs():
                    pyscript.memory_forget(key=f"away_pred:{_p}")  # noqa: F821
            except Exception:
                pass

            # Clear departure helper
            dep_entity = f"input_datetime.ai_away_departed_{person}"
            try:
                # Set to a sentinel "cleared" value (epoch)
                service.call(  # noqa: F821
                    "input_datetime", "set_datetime",
                    entity_id=dep_entity,
                    datetime="1970-01-01 00:00:00",
                )
            except Exception:
                pass

        # Check if the other person is still away — re-run prediction for them
        for other_p, other_tracker in _get_person_trackers().items():
            if other_p != person:
                try:
                    other_state = str(state.get(other_tracker) or "home")  # noqa: F821
                except NameError:
                    other_state = "home"
                if other_state == "not_home":
                    await away_predict_return(person=other_p)


# ── Time Triggers ────────────────────────────────────────────────────────────

@time_trigger("cron(15 4 * * *)")  # noqa: F821
async def _daily_rebuild():
    """Daily rebuild at 04:15 (15 min after presence_patterns at 04:00)."""
    if not _is_enabled():
        return
    log.info("away: daily rebuild starting")  # noqa: F821
    result = await away_rebuild_patterns()
    log.info(f"away: daily rebuild done — {result}")  # noqa: F821


@time_trigger("cron(*/5 * * * *)")  # noqa: F821
async def _periodic_prediction_update():
    """Re-run predictions while someone is away (G8).

    Prediction sharpens as elapsed time increases — MRL naturally conditions
    on the trip already being t₀ minutes long (sequential Bayesian principle).
    Interval configurable via ai_away_prediction_update_minutes helper.
    """
    if not _departure_ts:
        return
    if not _is_enabled():
        return

    # Check if enough time has passed since last update
    # The cron fires every 5 min; we only re-predict at the configured interval
    update_interval = _get_update_interval()
    # Use minute-of-hour to gate: only fire when minute is divisible by interval
    current_minute = datetime.now().minute
    if update_interval > 5 and current_minute % update_interval != 0:
        return

    await _predict_return_inner()


@time_trigger("startup")  # noqa: F821
async def _startup():
    """Initialize on startup: load cache, sync current state."""
    task.sleep(10)  # noqa: F821
    await asyncio.to_thread(reload_entity_config)

    _ensure_result_entity_name(force=True)
    _set_result("starting", operation="startup")

    # Register WiFi tracker triggers dynamically from config
    global _tracker_triggers
    trackers = list(_get_person_trackers().values())
    _tracker_triggers = [_tracker_trigger_factory(t) for t in trackers]
    log.info(f"away: registered {len(_tracker_triggers)} tracker triggers")  # noqa: F821

    loaded = await _load_cache_from_l2()
    log.info(f"away: startup loaded {loaded} cache entries from L2")  # noqa: F821

    # Check if anyone is currently away and set departure tracking
    for person, tracker in _get_person_trackers().items():
        try:
            tracker_state = str(state.get(tracker) or "unknown")  # noqa: F821
        except NameError:
            tracker_state = "unknown"
        if tracker_state == "not_home":
            # Check if we already have a departure timestamp
            dep_entity = f"input_datetime.ai_away_departed_{person}"
            try:
                dep_str = str(state.get(dep_entity) or "")  # noqa: F821
                if dep_str and dep_str not in ("unknown", "unavailable", "",
                                                "1970-01-01 00:00:00"):
                    dep_dt = datetime.fromisoformat(dep_str)
                    # I-40b: _departure_ts is now a list
                    _departure_ts[person] = [dep_dt.timestamp()]
                    log.info(  # noqa: F821
                        f"away: startup — {person} is away since {dep_str}"
                    )
                else:
                    # No departure timestamp — use now as approximation
                    _departure_ts[person] = [time.time()]
                    log.info(  # noqa: F821
                        f"away: startup — {person} is away (no departure ts, using now)"
                    )
            except (NameError, ValueError):
                _departure_ts[person] = [time.time()]

            # Run prediction
            await away_predict_return(person=person)

    # I-54: Ensure sensor exists on startup (prevents 'unavailable' state)
    try:
        cur = state.get("sensor.ai_away_prediction")  # noqa: F821
        if cur in (None, "unavailable", "unknown"):
            state.set("sensor.ai_away_prediction", value="not_away", new_attributes={  # noqa: F821
                "friendly_name": "AI Away Prediction",
                "icon": "mdi:home-clock-outline",
                "person": "none", "predictions": [],
            })
    except Exception:
        pass

    _set_result("ok", operation="startup", cache_entries=loaded)
