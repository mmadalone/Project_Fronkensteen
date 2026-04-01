"""G13 Phase 1.5: Entropy-MAE Correlation Logger & Weekly Reporter.

Queries per-arrival G13 entries from L2 memory, bins by entropy tier,
computes Pearson correlation between bucket_entropy and prediction error,
and delivers weekly reports via persistent_notification.

Sensor: sensor.ai_entropy_correlation
  State: positive / negative / none / insufficient_data / awaiting_data
  Attributes: tiers, pearson_r, direction, total_entries, lookback_days,
              hypothesis, phase2_recommendation, last_report

Services:
  pyscript.entropy_correlation_report(lookback_days=7)
    Manual trigger for on-demand analysis.

Time triggers:
  cron(30 4 * * 1) — Monday 04:30 (after daily rebuild at 04:15)
  startup — initializes sensor

Dependencies:
  pyscript/memory.py (L2 memory — SQLite)
  pyscript/away_patterns.py (writes g13_arrival:* entries)
  helpers: input_boolean.ai_entropy_correlation_enabled
           input_number.ai_entropy_tier_low
           input_number.ai_entropy_tier_high

Deployed: 2026-03-26
"""
import json
from datetime import datetime, timedelta
from pathlib import Path

from shared_utils import build_result_entity_name

# =============================================================================
# Constants
# =============================================================================
DB_PATH = Path("/config/memory.db")
RESULT_ENTITY = "sensor.ai_entropy_correlation"
MIN_CORRELATION_ENTRIES = 5  # minimum for Pearson r


# =============================================================================
# Helpers
# =============================================================================

def _is_enabled() -> bool:
    """Check kill switch."""
    val = str(state.get("input_boolean.ai_entropy_correlation_enabled") or "off")  # noqa: F821
    return val.lower() == "on"


def _set_result(sensor_state: str, **attrs):
    """Update the correlation sensor."""
    base = build_result_entity_name(RESULT_ENTITY)
    base.update({"icon": "mdi:chart-scatter-plot"})
    base.update(attrs)
    state.set(RESULT_ENTITY, value=sensor_state, new_attributes=base)  # noqa: F821


def _get_tier_thresholds() -> tuple:
    """Read tier thresholds from helpers."""
    low = float(state.get("input_number.ai_entropy_tier_low") or 1.0)  # noqa: F821
    high = float(state.get("input_number.ai_entropy_tier_high") or 2.0)  # noqa: F821
    # Ensure low < high
    if low >= high:
        high = low + 0.5
    return low, high


# =============================================================================
# Data Access — @pyscript_executor for direct SQLite (read-only)
# =============================================================================

@pyscript_executor  # noqa: F821
def _query_g13_entries(lookback_days):
    """Query g13_arrival:* entries from L2 memory.

    Returns list of dicts with parsed JSON values.
    """
    import sqlite3 as _sqlite3
    import json as _json
    from contextlib import closing as _closing
    from datetime import datetime as _dt, timedelta as _td
    from pathlib import Path as _Path

    db = _Path("/config/memory.db")
    if not db.exists():
        return []

    cutoff = (_dt.utcnow() - _td(days=lookback_days)).isoformat(timespec="seconds")
    entries = []
    try:
        with _closing(_sqlite3.connect(f"file:{db}?mode=ro", uri=True)) as conn:
            conn.row_factory = _sqlite3.Row
            rows = conn.execute(
                "SELECT key, value, created_at FROM mem "
                "WHERE key LIKE 'g13_arrival:%' AND created_at >= ? "
                "ORDER BY created_at",
                (cutoff,),
            ).fetchall()
            for row in rows:
                try:
                    data = _json.loads(row["value"])
                    data["_key"] = row["key"]
                    data["_created_at"] = row["created_at"]
                    entries.append(data)
                except (_json.JSONDecodeError, TypeError):
                    continue
    except _sqlite3.Error:
        pass
    return entries


# =============================================================================
# Analysis — @pyscript_compile for stdlib access (statistics, math)
# =============================================================================

@pyscript_compile  # noqa: F821
def _compute_correlation(entries, low_threshold, high_threshold):
    """Bin entries by entropy tier, compute per-tier stats and Pearson r.

    Returns structured dict with tiers, correlation, and recommendation.
    """
    import statistics as _stats
    import math as _math

    result = {
        "tiers": {"low": {}, "medium": {}, "high": {}},
        "pearson_r": None,
        "direction": "insufficient_data",
        "total_entries": len(entries),
        "hypothesis": "",
        "phase2_recommendation": "",
    }

    if not entries:
        result["hypothesis"] = "No arrival data available"
        result["phase2_recommendation"] = "Wait for more arrivals"
        return result

    # ── Bin into tiers ──
    tier_bins = {"low": [], "medium": [], "high": []}
    all_entropy = []
    all_error = []

    for e in entries:
        be = float(e.get("bucket_entropy", 0.0))
        err = float(e.get("error_min", 0.0))
        all_entropy.append(be)
        all_error.append(err)

        if be < low_threshold:
            tier_bins["low"].append(e)
        elif be < high_threshold:
            tier_bins["medium"].append(e)
        else:
            tier_bins["high"].append(e)

    # ── Per-tier statistics ──
    for tier_name, items in tier_bins.items():
        if not items:
            result["tiers"][tier_name] = {
                "mean_mae": 0.0, "median_mae": 0.0, "count": 0,
                "mean_entropy": 0.0, "mean_predictability": 0.0,
            }
            continue
        errors = [float(i.get("error_min", 0.0)) for i in items]
        entropies = [float(i.get("bucket_entropy", 0.0)) for i in items]
        preds = [float(i.get("predictability", 0.0)) for i in items]
        result["tiers"][tier_name] = {
            "mean_mae": round(_stats.mean(errors), 1),
            "median_mae": round(_stats.median(errors), 1),
            "count": len(items),
            "mean_entropy": round(_stats.mean(entropies), 3),
            "mean_predictability": round(_stats.mean(preds), 3),
        }

    # ── Pearson r ──
    n = len(all_entropy)
    if n < MIN_CORRELATION_ENTRIES:
        result["hypothesis"] = f"Only {n} entries — need at least {MIN_CORRELATION_ENTRIES}"
        result["phase2_recommendation"] = "Wait for more arrivals"
        return result

    # Guard: zero variance on either axis
    try:
        entropy_stdev = _stats.stdev(all_entropy)
        error_stdev = _stats.stdev(all_error)
    except _stats.StatisticsError:
        entropy_stdev = 0.0
        error_stdev = 0.0

    if entropy_stdev < 1e-9 or error_stdev < 1e-9:
        result["direction"] = "insufficient_data"
        result["hypothesis"] = "Zero variance in entropy or error — cannot compute correlation"
        result["phase2_recommendation"] = "Wait for more diverse data"
        return result

    try:
        r = _stats.correlation(all_entropy, all_error)
    except Exception:
        result["direction"] = "insufficient_data"
        result["hypothesis"] = "Correlation computation failed"
        result["phase2_recommendation"] = "Investigate data quality"
        return result

    r = round(r, 4)
    result["pearson_r"] = r

    # ── Interpretation ──
    if r < -0.15:
        result["direction"] = "negative"
        result["hypothesis"] = (
            "Higher entropy correlates with LOWER error — unexpected. "
            "Entropy may be capturing bucket diversity rather than unpredictability."
        )
        result["phase2_recommendation"] = (
            "Investigate — negative r suggests entropy metric may need recalibration"
        )
    elif r > 0.15:
        result["direction"] = "positive"
        result["hypothesis"] = (
            "Higher entropy correlates with HIGHER error — confirms hypothesis. "
            "Low-entropy buckets produce more accurate predictions."
        )
        result["phase2_recommendation"] = (
            "Proceed to Phase 2 — entropy-weighted confidence adjustment"
        )
    else:
        result["direction"] = "none"
        result["hypothesis"] = (
            f"No meaningful correlation (r={r}). Entropy does not predict "
            "accuracy at current sample size."
        )
        result["phase2_recommendation"] = (
            "Continue collecting data — reassess after 50+ entries"
        )

    return result


@pyscript_compile  # noqa: F821
def _format_report(result, report_type="weekly"):
    """Format Markdown report for persistent_notification."""
    lines = []
    lines.append(f"## G13 Entropy Correlation — {report_type.title()} Report")
    lines.append("")

    total = result.get("total_entries", 0)
    r = result.get("pearson_r")
    direction = result.get("direction", "unknown")
    lines.append(f"**Entries analyzed:** {total}")
    lines.append(f"**Pearson r:** {r if r is not None else 'N/A'}")
    lines.append(f"**Direction:** {direction}")
    lines.append("")

    # Tier table
    tiers = result.get("tiers", {})
    lines.append("| Tier | Count | Mean MAE | Median MAE | Mean Entropy | Predictability |")
    lines.append("|------|------:|--------:|-----------:|-------------:|---------------:|")
    for tier_name in ("low", "medium", "high"):
        t = tiers.get(tier_name, {})
        cnt = t.get("count", 0)
        m_mae = t.get("mean_mae", 0.0)
        med_mae = t.get("median_mae", 0.0)
        m_ent = t.get("mean_entropy", 0.0)
        m_pred = t.get("mean_predictability", 0.0)
        lines.append(
            f"| {tier_name.title()} | {cnt} | {m_mae:.1f} min | "
            f"{med_mae:.1f} min | {m_ent:.3f} bits | {m_pred:.3f} |"
        )
    lines.append("")

    # Interpretation
    hypothesis = result.get("hypothesis", "")
    recommendation = result.get("phase2_recommendation", "")
    if hypothesis:
        lines.append(f"**Hypothesis:** {hypothesis}")
    if recommendation:
        lines.append(f"**Recommendation:** {recommendation}")

    return "\n".join(lines)


# =============================================================================
# Service — Manual Trigger
# =============================================================================

@service(supports_response="only")  # noqa: F821
async def entropy_correlation_report(lookback_days=7):
    """Run entropy-MAE correlation analysis and deliver report.

    Args:
        lookback_days: How many days of G13 arrival data to analyze (default 7).
    """
    if not _is_enabled():
        _set_result("disabled")
        return {"status": "disabled"}

    entries = await _query_g13_entries(int(lookback_days))
    if not entries:
        _set_result("no_data", total_entries=0, lookback_days=int(lookback_days))
        return {"status": "no_data", "entries": 0}

    low_t, high_t = _get_tier_thresholds()
    result = _compute_correlation(entries, low_t, high_t)
    result["lookback_days"] = int(lookback_days)
    result["last_report"] = datetime.utcnow().isoformat(timespec="seconds")

    direction = result.get("direction", "insufficient_data")
    _set_result(direction, **result)

    # Format and send persistent notification
    report_md = _format_report(result, "manual" if lookback_days != 7 else "weekly")
    try:
        await service.call(  # noqa: F821
            "persistent_notification", "create",
            title="G13 Entropy Correlation Report",
            message=report_md,
            notification_id="g13_entropy_report",
        )
    except Exception as exc:
        log.warning(f"entropy_correlator: notification failed: {exc}")  # noqa: F821

    return {"status": "ok", "direction": direction, **result}


# =============================================================================
# Startup — sensor init only (scheduling handled by blueprint)
# =============================================================================

@time_trigger("startup")  # noqa: F821
async def _entropy_correlator_startup():
    """Initialize correlation sensor on HA startup."""
    if not _is_enabled():
        _set_result("disabled")
        return

    # Check if DB exists
    if not DB_PATH.exists():
        _set_result("awaiting_data", total_entries=0)
        return

    # Check for existing data
    entries = await _query_g13_entries(120)
    if not entries:
        _set_result("awaiting_data", total_entries=0)
        return

    # Run initial analysis
    low_t, high_t = _get_tier_thresholds()
    result = _compute_correlation(entries, low_t, high_t)
    result["lookback_days"] = 120
    result["last_report"] = datetime.utcnow().isoformat(timespec="seconds")
    direction = result.get("direction", "insufficient_data")
    _set_result(direction, **result)
    log.info(  # noqa: F821
        f"entropy_correlator: startup — {len(entries)} entries, direction={direction}"
    )
