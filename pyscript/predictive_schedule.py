"""Task 17: Predictive Scheduling Engine for Bedtime and Optimal Timing.

Fuses calendar events (L3), routine fingerprint durations (L2), and
real-time state (L1) to produce bedtime advisories and general timing
recommendations. Runs a 30-minute cron loop from 20:00-02:00, fires
ai_bedtime_advisory/overdue events, and feeds back predicted-vs-actual
timing to improve accuracy over time.
"""
import asyncio
import json
import time
from datetime import datetime, timedelta
from typing import Any

from shared_utils import (
    build_result_entity_name,
    get_person_config,
    get_person_slugs,
    load_entity_config,
    resolve_active_user,
)

# =============================================================================
# Predictive Scheduling Engine — Task 17 of Voice Context Architecture
# =============================================================================
# Fuses L1 real-time state, L2 routine fingerprints, and L3 calendar data
# to produce intelligent timing recommendations.
#
# Services:
#   pyscript.schedule_bedtime_advisor
#     Flagship prediction: combines calendar events (L3), routine fingerprint
#     duration (L2), and current state (L1) to recommend when to start
#     winding down for sleep.
#
#   pyscript.schedule_optimal_timing
#     General purpose: given a target event, work backwards using prep and
#     travel time to suggest when to start preparing.
#
# Event triggers:
#   ai_routine_completed → feedback loop (compare predicted vs actual timing)
#
# Time triggers:
#   Every 30 min from 20:00-02:00 → smart bedtime check + advisory events
#   Startup → initialize
#
# Events fired:
#   ai_bedtime_advisory  — 15 min or less before target routine start
#   ai_bedtime_overdue   — past target routine start and routine not active
#
# Key design:
#   - Calendar queries cached 1 hour (avoid hammering Google API)
#   - Fallback chain: calendar API → L2 cache → default wake time helper
#   - Feedback stored in L2: compare predicted vs actual routine completion
#   - Creep factor gate: recommendations are about schedule, NEVER about
#     tracked behavior ("start winding down" not "I tracked your routine")
#   - Test mode: mock calendar data, no events fired, full logging
#
# Dependencies:
#   - pyscript/routine_fingerprint.py (Task 16 — fingerprints, completion events)
#   - pyscript/presence_patterns.py (Task 15 — frequency tables)
#   - pyscript/memory.py (L2: memory_get, memory_set, memory_search)
#   - packages/ai_predictive_schedule.yaml (helpers)
#   - packages/ai_context_hot.yaml (default wake times)
#   - packages/ai_routine_tracker.yaml (routine stage, bedtime predicted)
#   - packages/ai_test_harness.yaml (test mode toggle)
#
# Deployed: 2026-03-02
# =============================================================================


def _get_calendar_entity() -> str:
    """Resolve calendar entity from person config (Task 22).

    Uses the first person with a configured calendar, falls back to empty string.
    """
    for slug in get_person_slugs():
        cal = get_person_config(slug, "calendar", "")
        if cal:
            return cal
    return ""
RESULT_ENTITY = "sensor.ai_predictive_schedule_status"
CALENDAR_CACHE_TTL = 3600       # 1 hour
DEFAULT_ROUTINE_DURATION = 45   # minutes
DEFAULT_PREP_BUFFER = 45        # minutes
DEFAULT_SLEEP_HOURS = 7.0
FEEDBACK_GOOD_THRESHOLD = 15    # minutes — prediction within this = reinforced
FEEDBACK_BAD_THRESHOLD = 30     # minutes — prediction off by more = weakened
L2_EXPIRATION_DAYS = 365

_DEFAULT_FP2_ZONES = {
    "binary_sensor.fp2_presence_sensor_workshop": "workshop",
    "binary_sensor.fp2_presence_sensor_living_room": "living_room",
    "binary_sensor.fp2_presence_sensor_main_room": "main_room",
    "binary_sensor.fp2_presence_sensor_kitchen": "kitchen",
    "binary_sensor.fp2_presence_sensor_bed": "bed",
    "binary_sensor.fp2_presence_sensor_lobby": "lobby",
    "binary_sensor.fp2_presence_sensor_bathroom": "bathroom",
    "binary_sensor.fp2_presence_sensor_shower": "shower",
}


def _get_fp2_zones() -> dict:
    """Get entity→zone map. Falls back to hardcoded defaults if config missing."""
    cfg = load_entity_config()
    return cfg.get("fp2_zones") or _DEFAULT_FP2_ZONES

# ── Module-Level State ───────────────────────────────────────────────────────

_calendar_cache: dict | None = None  # {events: [...], fetched_at: ts, date: "YYYY-MM-DD"}
_last_advisor_result: dict | None = None
result_entity_name: dict[str, str] = {}


# ── Entity Name Helpers (pattern from notification_dedup.py) ─────────────────

def _ensure_result_entity_name(force: bool = False) -> None:
    global result_entity_name
    if force or not result_entity_name:
        result_entity_name = build_result_entity_name(RESULT_ENTITY)


_CARRY_FORWARD_ATTRS = ("bedtime_recommendation", "schedule_sources_raw")


def _set_result(state_value: str = "ok", **attrs: Any) -> None:
    _ensure_result_entity_name()
    attrs.update(result_entity_name)
    # Carry forward consolidated attributes across status updates
    try:
        existing = state.getattr(RESULT_ENTITY) or {}  # noqa: F821
        for key in _CARRY_FORWARD_ATTRS:
            if key not in attrs and key in existing:
                attrs[key] = existing[key]
    except Exception:
        pass
    state.set(RESULT_ENTITY, value=state_value, new_attributes=attrs)  # noqa: F821


# ── Pure-Python Sync Helpers ─────────────────────────────────────────────────

@pyscript_compile  # noqa: F821
def _parse_time_string(time_str: str) -> tuple | None:
    """Parse HH:MM or ISO datetime string to (hour, minute) tuple.

    Handles:
      "09:00"                     → (9, 0)
      "2026-03-03T09:00:00+01:00" → (9, 0)
      "23:45:00"                  → (23, 45)
    """
    if not time_str:
        return None
    s = str(time_str).strip()
    # ISO format: contains 'T'
    if "T" in s:
        try:
            time_part = s.split("T")[1]
            hm = time_part.split(":")
            return (int(hm[0]), int(hm[1]))
        except (IndexError, ValueError):
            return None
    # HH:MM or HH:MM:SS format
    if ":" in s:
        parts = s.split(":")
        try:
            return (int(parts[0]), int(parts[1]))
        except (IndexError, ValueError):
            return None
    return None


@pyscript_compile  # noqa: F821
def _compute_bedtime_plan(
    event_hour: int,
    event_minute: int,
    routine_duration_min: float,
    target_sleep_hours: float,
    prep_buffer_min: int,
    current_hour: int,
    current_minute: int,
) -> dict:
    """Compute bedtime timing plan using 48-hour minute number line.

    Times are computed on a 48-hour line where today noon=720,
    today midnight=1440, tomorrow morning=1440+hours*60.
    Post-midnight hours (0-5) are treated as 'still tonight' (+1440).
    """
    # Event is tomorrow morning: offset by 1440 (one full day)
    event_mins = 1440 + event_hour * 60 + event_minute
    wake_mins = event_mins - prep_buffer_min
    sleep_target_mins = int(target_sleep_hours * 60)
    sleep_mins = wake_mins - sleep_target_mins
    routine_start_mins = sleep_mins - int(routine_duration_min)

    # Current time: post-midnight hours (0-5) are "still tonight"
    current_mins = current_hour * 60 + current_minute
    if current_hour < 6:
        current_mins += 1440

    minutes_until = routine_start_mins - current_mins

    def fmt(total_mins):
        m = total_mins % 1440
        if m < 0:
            m += 1440
        h = m // 60
        mi = m % 60
        return f"{h:02d}:{mi:02d}"

    return {
        "required_wake_time": fmt(wake_mins),
        "target_sleep_time": fmt(sleep_mins),
        "target_routine_start": fmt(routine_start_mins),
        "minutes_until_routine": int(minutes_until),
        "routine_duration_min": int(routine_duration_min),
        "target_sleep_hours": target_sleep_hours,
    }


@pyscript_compile  # noqa: F821
def _extract_earliest_timed_event(events_raw: list) -> dict | None:
    """Extract earliest timed event (skip all-day) from calendar event list.

    All-day events have start as date string ("2026-03-03") without 'T'.
    Timed events: "2026-03-03T09:00:00+01:00".
    """
    earliest = None
    earliest_mins = 99999
    for ev in events_raw:
        start = ev.get("start", "")
        start_str = str(start)
        if "T" not in start_str:
            continue  # all-day event — skip
        try:
            time_part = start_str.split("T")[1]
            hm = time_part.split(":")
            hour = int(hm[0])
            minute = int(hm[1])
        except (IndexError, ValueError):
            continue
        total = hour * 60 + minute
        if total < earliest_mins:
            earliest_mins = total
            earliest = {
                "hour": hour,
                "minute": minute,
                "summary": ev.get("summary", "Event"),
                "start_raw": start_str,
            }
    return earliest


@pyscript_compile  # noqa: F821
def _compute_optimal_plan(
    event_hour: int,
    event_minute: int,
    prep_minutes: int,
    travel_minutes: int,
) -> dict:
    """Compute optimal prep/leave/reminder times for a given event."""
    event_mins = event_hour * 60 + event_minute
    leave_mins = event_mins - travel_minutes
    prep_start_mins = leave_mins - prep_minutes
    reminder_mins = prep_start_mins - 15  # 15-min advance reminder

    def fmt(total_mins):
        m = total_mins % 1440
        if m < 0:
            m += 1440
        h = m // 60
        mi = m % 60
        return f"{h:02d}:{mi:02d}"

    return {
        "leave_by": fmt(leave_mins),
        "start_prep": fmt(prep_start_mins),
        "reminder_time": fmt(reminder_mins),
    }


@pyscript_compile  # noqa: F821
def _build_recommendation(minutes_until: int, sleep_hours: float) -> str:
    """Build human-readable recommendation (creep factor safe).

    Never references tracked behavior. Only talks about schedule and sleep.
    """
    hrs = f"{sleep_hours:.0f}" if sleep_hours == int(sleep_hours) else f"{sleep_hours:.1f}"
    if minutes_until <= 0:
        return f"You might want to start winding down now for {hrs} hours of sleep."
    if minutes_until <= 5:
        return f"Time to start winding down for {hrs} hours of sleep."
    # Round to nearest 5 for natural phrasing
    rounded = ((minutes_until + 2) // 5) * 5
    return f"Start winding down in about {rounded} minutes for {hrs} hours of sleep."


# ── L2 Memory Helpers ────────────────────────────────────────────────────────

async def _l2_get(key: str) -> dict | None:
    """Exact-key lookup in L2 via memory_get."""
    try:
        result = pyscript.memory_get(key=key)  # noqa: F821
        return await result
    except Exception as exc:
        log.warning(f"schedule: L2 get failed key={key}: {exc}")  # noqa: F821
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
        log.warning(f"schedule: L2 set failed key={key}: {exc}")  # noqa: F821
        return False


async def _l2_search(query: str, limit: int = 200) -> list:
    """Search L2 via memory_search. Returns empty list on failure."""
    try:
        result = pyscript.memory_search(query=query, limit=limit)  # noqa: F821
        resp = await result
        if resp and resp.get("status") == "ok":
            return resp.get("results", [])
    except Exception as exc:
        log.warning(f"schedule: L2 search failed query={query}: {exc}")  # noqa: F821
    return []


# ── Settings Helpers ─────────────────────────────────────────────────────────

def _is_test_mode() -> bool:
    try:
        return str(state.get("input_boolean.ai_test_mode") or "off").lower() == "on"  # noqa: F821
    except NameError:
        return False


def _is_zone_enabled(zone: str) -> bool:
    """Check if an FP2 zone is enabled via dashboard toggle."""
    toggle = f"input_boolean.ai_fp2_zone_{zone}_enabled"
    try:
        return str(state.get(toggle) or "on").lower() != "off"  # noqa: F821
    except NameError:
        return True  # default ON if helper missing


def _get_target_sleep_hours() -> float:
    try:
        val = float(state.get("input_number.ai_target_sleep_hours") or DEFAULT_SLEEP_HOURS)  # noqa: F821
        return val if 4.0 <= val <= 12.0 else DEFAULT_SLEEP_HOURS
    except (NameError, TypeError, ValueError):
        return DEFAULT_SLEEP_HOURS


def _get_prep_buffer() -> int:
    try:
        return int(float(state.get("input_number.ai_morning_prep_buffer") or DEFAULT_PREP_BUFFER))  # noqa: F821
    except (NameError, TypeError, ValueError):
        return DEFAULT_PREP_BUFFER


def _get_current_zone() -> str:
    """Get the currently active FP2 zone (or 'unknown')."""
    for entity_id, zone in _get_fp2_zones().items():
        try:
            if not _is_zone_enabled(zone):
                continue
            if str(state.get(entity_id) or "").lower() == "on":  # noqa: F821
                return zone
        except NameError:
            continue
    return "unknown"


def _has_presence() -> bool:
    """Check if any FP2 zone is active."""
    for entity_id, zone in _get_fp2_zones().items():
        try:
            if not _is_zone_enabled(zone):
                continue
            if str(state.get(entity_id) or "").lower() == "on":  # noqa: F821
                return True
        except NameError:
            continue
    return False


# ── Calendar Query ───────────────────────────────────────────────────────────

async def _fetch_calendar_tomorrow() -> list:
    """Fetch tomorrow's events from HA calendar. Returns list of event dicts.

    Cached for CALENDAR_CACHE_TTL seconds. Cache invalidated on date change.
    """
    global _calendar_cache
    now_ts = time.time()
    dt_now = datetime.now()
    tomorrow = dt_now.date() + timedelta(days=1)
    tomorrow_str = tomorrow.isoformat()

    # Check cache: valid if same date AND within TTL
    if (_calendar_cache
            and _calendar_cache.get("date") == tomorrow_str
            and (now_ts - _calendar_cache.get("fetched_at", 0)) < CALENDAR_CACHE_TTL):
        return _calendar_cache.get("events", [])

    start_str = f"{tomorrow_str}T00:00:00"
    end_str = f"{tomorrow_str}T23:59:59"

    cal_entity = _get_calendar_entity()
    try:
        result = calendar.get_events(  # noqa: F821
            entity_id=cal_entity,
            start_date_time=start_str,
            end_date_time=end_str,
        )
        resp = await result

        events = []
        if isinstance(resp, dict):
            # Standard format: {entity_id: {events: [...]}}
            for key in resp:
                val = resp[key]
                if isinstance(val, dict) and "events" in val:
                    events = val["events"]
                    break
            # Alternate format: {events: [...]}
            if not events and "events" in resp:
                events = resp["events"]
        elif isinstance(resp, list):
            events = resp

        _calendar_cache = {
            "events": events,
            "fetched_at": now_ts,
            "date": tomorrow_str,
        }

        # Store earliest event in L2 for fallback on next API failure
        if events:
            earliest = _extract_earliest_timed_event(events)
            if earliest:
                cache_val = json.dumps({
                    "summary": earliest["summary"],
                    "hour": earliest["hour"],
                    "minute": earliest["minute"],
                    "date": tomorrow_str,
                }, separators=(",", ":"))
                await _l2_set(
                    "calendar_tomorrow_first_event",
                    cache_val,
                    "calendar prediction schedule",
                )

        log.info(  # noqa: F821
            f"schedule: fetched {len(events)} calendar events for {tomorrow_str}"
        )
        return events

    except Exception as exc:
        log.warning(f"schedule: calendar fetch failed: {exc}")  # noqa: F821
        return []


async def _get_first_event_tomorrow() -> tuple:
    """Get first timed event tomorrow.

    Returns: (event_dict_or_None, from_calendar_bool)

    Fallback chain:
      1. Calendar API (with 1-hour cache)
      2. L2 cached calendar data (from previous successful fetch)
      3. None (caller uses default wake time)
    """
    test_mode = _is_test_mode()

    # ── Test mode: mock calendar ──
    if test_mode:
        try:
            mock = str(state.get("input_text.ai_test_calendar_event") or "")  # noqa: F821
        except NameError:
            mock = ""

        if mock:
            # Try "Summary at HH:MM" format
            if " at " in mock:
                parts = mock.rsplit(" at ", 1)
                parsed = _parse_time_string(parts[1])
                if parsed:
                    log.info(  # noqa: F821
                        f"schedule [TEST]: mock calendar: {parts[0]} at "
                        f"{parsed[0]:02d}:{parsed[1]:02d}"
                    )
                    return {
                        "hour": parsed[0], "minute": parsed[1],
                        "summary": parts[0],
                    }, True

            # Try bare "HH:MM" format
            parsed = _parse_time_string(mock)
            if parsed:
                log.info(  # noqa: F821
                    f"schedule [TEST]: mock calendar: event at "
                    f"{parsed[0]:02d}:{parsed[1]:02d}"
                )
                return {
                    "hour": parsed[0], "minute": parsed[1],
                    "summary": "Test event",
                }, True

            # Try JSON: {"summary": "...", "hour": N, "minute": N}
            try:
                data = json.loads(mock)
                if isinstance(data, dict) and "hour" in data:
                    log.info("schedule [TEST]: mock calendar from JSON")  # noqa: F821
                    return data, True
            except (json.JSONDecodeError, TypeError):
                pass

            log.warning(f"schedule [TEST]: could not parse mock calendar: {mock}")  # noqa: F821
        return None, False

    # ── 1. Calendar API ──
    events = await _fetch_calendar_tomorrow()
    if events:
        earliest = _extract_earliest_timed_event(events)
        if earliest:
            return earliest, True

    # ── 2. L2 cached calendar data ──
    resp = await _l2_get("calendar_tomorrow_first_event")
    if resp and resp.get("status") == "ok":
        try:
            data = json.loads(resp.get("value", "{}"))
            if isinstance(data, dict) and "hour" in data:
                tomorrow_str = (datetime.now().date() + timedelta(days=1)).isoformat()
                if data.get("date") == tomorrow_str:
                    log.info("schedule: using L2 cached calendar data")  # noqa: F821
                    return data, True
        except (json.JSONDecodeError, TypeError):
            pass

    # ── 3. No calendar data ──
    return None, False


# ── Fingerprint Duration Lookup ──────────────────────────────────────────────

async def _get_bedtime_routine_duration() -> tuple:
    """Get average duration of bed-ending routines from L2 fingerprints.

    Returns: (duration_minutes_or_None, from_fingerprint_bool)
    """
    test_mode = _is_test_mode()
    if test_mode:
        log.info(  # noqa: F821
            f"schedule [TEST]: using default routine duration "
            f"{DEFAULT_ROUTINE_DURATION}m"
        )
        return float(DEFAULT_ROUTINE_DURATION), False

    results = await _l2_search("routine fingerprint", limit=20)
    bed_durations: list[float] = []
    for entry in results:
        value = entry.get("value", "")
        if not value:
            continue
        try:
            fp = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(fp, dict):
            continue
        seq = fp.get("sequence", [])
        if seq and seq[-1] == "bed":
            dur = fp.get("avg_duration_min", 0)
            if dur > 0:
                bed_durations.append(float(dur))

    if bed_durations:
        total = 0.0
        for d in bed_durations:
            total += d
        avg = total / len(bed_durations)
        return round(avg, 1), True
    return None, False


async def _get_default_wake_time(for_tomorrow: bool = True) -> tuple:
    """Get default wake time from context helpers. Returns (hour, minute).

    I-28: Checks per-day-of-week overrides first, then falls back to
    weekday/weekend defaults.
    """
    now = datetime.now()
    target_date = (now + timedelta(days=1)) if for_tomorrow else now
    day_name = target_date.strftime("%A").lower()  # e.g. "thursday"
    is_weekend = target_date.weekday() >= 5

    # I-28: Check per-day override first
    try:
        overrides_raw = state.get(  # noqa: F821
            "input_text.ai_schedule_day_overrides"
        ) or "{}"
        if overrides_raw and overrides_raw not in ("unknown", "unavailable", ""):
            overrides = json.loads(overrides_raw)
            if day_name in overrides:
                parsed = _parse_time_string(overrides[day_name])
                if parsed:
                    log.info(  # noqa: F821
                        f"schedule: using day override for {day_name}: "
                        f"{parsed[0]:02d}:{parsed[1]:02d}"
                    )
                    return parsed
    except Exception:
        pass

    # Per-user weekday/weekend wake time (unified with blueprint pattern)
    user = resolve_active_user()
    user_entity = (
        f"input_datetime.ai_context_wake_time_weekend_{user}"
        if is_weekend
        else f"input_datetime.ai_context_wake_time_weekday_{user}"
    )
    try:
        val = str(state.get(user_entity) or "")  # noqa: F821
        parsed = _parse_time_string(val)
        if parsed:
            return parsed
    except NameError:
        pass

    # Hard defaults if helpers unavailable
    return (9, 0) if is_weekend else (7, 30)


# ── Helper Updates ───────────────────────────────────────────────────────────

async def _update_helpers(result: dict, test_mode: bool) -> None:
    """Update HA helpers with bedtime advisor results."""
    if test_mode:
        log.info(  # noqa: F821
            f"schedule [TEST]: WOULD update helpers — "
            f"{result.get('recommendation', '')}"
        )
        return

    # Recommendation text → attribute on status sensor
    rec = result.get("recommendation", "")
    try:
        cur_attrs = state.getattr(RESULT_ENTITY) or {}  # noqa: F821
        cur_attrs["bedtime_recommendation"] = rec[:255]
        state.set(  # noqa: F821
            RESULT_ENTITY,
            value=state.get(RESULT_ENTITY) or "ok",  # noqa: F821
            new_attributes=cur_attrs,
        )
    except Exception:
        pass

    # Predicted routine start time (HH:MM → HH:MM:SS for input_datetime)
    routine_start = result.get("target_routine_start", "")
    if routine_start and ":" in routine_start:
        try:
            service.call(  # noqa: F821
                "input_datetime", "set_datetime",
                entity_id="input_datetime.ai_predicted_routine_start",
                time=routine_start + ":00",
            )
        except Exception:
            pass

    # I-29: Predicted wake time (for calendar_alarm blueprint)
    wake_time = result.get("required_wake_time", "")
    if wake_time and ":" in wake_time:
        try:
            service.call(  # noqa: F821
                "input_datetime", "set_datetime",
                entity_id="input_datetime.ai_predicted_wake_time",
                time=wake_time + ":00" if wake_time.count(":") == 1 else wake_time,
            )
        except Exception:
            pass

    # Sources JSON → attribute on status sensor
    sources = result.get("sources", {})
    try:
        cur_attrs = state.getattr(RESULT_ENTITY) or {}  # noqa: F821
        cur_attrs["schedule_sources_raw"] = json.dumps(sources, separators=(",", ":"))
        state.set(  # noqa: F821
            RESULT_ENTITY,
            value=state.get(RESULT_ENTITY) or "ok",  # noqa: F821
            new_attributes=cur_attrs,
        )
    except Exception:
        pass


# ── Services ─────────────────────────────────────────────────────────────────

@service(supports_response="only")  # noqa: F821
async def schedule_bedtime_advisor(
    target_sleep_hours: float = 0.0,
    prep_buffer_minutes: int = 0,
):
    """Compute bedtime recommendation fusing L1 + L2 + L3 data.

    Combines tomorrow's first calendar event (L3), bedtime routine duration
    from fingerprints (L2), and current zone/time (L1) to calculate when
    to start winding down for optimal sleep.

    fields:
      target_sleep_hours:
        description: Target hours of sleep (0 = use helper setting)
        example: 7
        selector:
          number:
            min: 5
            max: 10
            step: 0.5
      prep_buffer_minutes:
        description: Minutes from wake to leaving house (0 = use helper)
        example: 45
        selector:
          number:
            min: 15
            max: 90
            step: 5
    """
    global _last_advisor_result
    t0 = time.monotonic()
    test_mode = _is_test_mode()

    log.info(f"schedule: bedtime advisor starting (test={test_mode})")  # noqa: F821

    # ── Resolve parameters ──
    sleep_hours = (
        target_sleep_hours if target_sleep_hours > 0
        else _get_target_sleep_hours()
    )
    prep_buffer = (
        prep_buffer_minutes if prep_buffer_minutes > 0
        else _get_prep_buffer()
    )

    # ── L3: Calendar data ──
    event_data, from_calendar = await _get_first_event_tomorrow()

    # ── L2: Routine fingerprint duration ──
    routine_dur, from_fingerprint = await _get_bedtime_routine_duration()
    if routine_dur is None:
        routine_dur = float(DEFAULT_ROUTINE_DURATION)

    # ── L1: Current state ──
    current_zone = _get_current_zone()
    presence = _has_presence()
    now = datetime.now()

    # ── Determine event time (with fallback chain) ──
    relaxed_mode = False
    if event_data:
        ev_hour = event_data.get("hour", 9)
        ev_minute = event_data.get("minute", 0)
        ev_summary = event_data.get("summary", "Event")
        first_event_desc = f"{ev_summary} at {ev_hour:02d}:{ev_minute:02d}"
    else:
        # No calendar data — use default wake time
        ev_hour, ev_minute = await _get_default_wake_time(for_tomorrow=True)
        first_event_desc = f"default wake time {ev_hour:02d}:{ev_minute:02d}"
        from_calendar = False
        relaxed_mode = True  # I-29: no timed event = relaxed mode

    # ── Compute plan ──
    plan = _compute_bedtime_plan(
        ev_hour, ev_minute,
        routine_dur, sleep_hours, prep_buffer,
        now.hour, now.minute,
    )

    # ── I-29: Apply relaxed extension if no timed work event tomorrow ──
    if relaxed_mode:
        try:
            ext_min = int(float(
                state.get("input_number.ai_bedtime_relaxed_extension_minutes")  # noqa: F821
                or 90
            ))
        except Exception:
            ext_min = 90
        plan["minutes_until_routine"] += ext_min
        # Recalculate display times
        new_routine_mins = plan["minutes_until_routine"]
        log.info(  # noqa: F821
            f"schedule: relaxed mode — added {ext_min}min extension "
            f"(no timed event tomorrow)"
        )

    # ── Build recommendation (creep factor safe) ──
    recommendation = _build_recommendation(
        plan["minutes_until_routine"], sleep_hours,
    )

    # ── Confidence ──
    sources = {
        "calendar": from_calendar,
        "fingerprint": from_fingerprint,
        "presence": presence,
    }
    if from_calendar and from_fingerprint:
        confidence = "high"
    elif from_fingerprint:
        confidence = "medium"
    else:
        confidence = "low"

    elapsed_ms = round((time.monotonic() - t0) * 1000)

    # I-29: Read tomorrow workday status from calendar_promote helper
    is_work_tomorrow = False
    try:
        is_work_tomorrow = (
            state.get("input_boolean.ai_context_work_day_tomorrow") == "on"  # noqa: F821
        )
    except NameError:
        pass

    result = {
        "status": "ok",
        "first_event_tomorrow": first_event_desc,
        "is_work_tomorrow": is_work_tomorrow,
        "required_wake_time": plan["required_wake_time"],
        "target_sleep_time": plan["target_sleep_time"],
        "routine_duration_min": plan["routine_duration_min"],
        "target_routine_start": plan["target_routine_start"],
        "minutes_until_routine": plan["minutes_until_routine"],
        "recommendation": recommendation,
        "confidence": confidence,
        "sources": sources,
        "current_zone": current_zone,
        "relaxed_mode": relaxed_mode,  # I-29
        "elapsed_ms": elapsed_ms,
    }

    _last_advisor_result = result

    # Update HA helpers
    await _update_helpers(result, test_mode)

    # Update status sensor
    _set_result(
        "ok", op="bedtime_advisor",
        confidence=confidence,
        minutes_until=plan["minutes_until_routine"],
        first_event=first_event_desc,
        test_mode=test_mode,
        elapsed_ms=elapsed_ms,
    )

    if test_mode:
        log.info(f"schedule [TEST]: advisor result = {json.dumps(result, separators=(',', ':'))}")  # noqa: F821
    else:
        log.info(  # noqa: F821
            f"schedule: advisor — {recommendation} "
            f"(confidence={confidence}, event={first_event_desc})"
        )

    return result


@service(supports_response="only")  # noqa: F821
async def schedule_optimal_timing(
    event_description: str = "",
    event_time: str = "",
    prep_minutes: int = 30,
    travel_minutes: int = 0,
):
    """Compute optimal preparation timing for a given event.

    Works backwards from event time using prep and travel durations to
    suggest when to start preparing, when to leave, and when to set a
    reminder.

    fields:
      event_description:
        description: What the event is
        example: "dentist appointment"
        selector:
          text:
      event_time:
        description: Event time (HH:MM or ISO format)
        example: "13:00"
        selector:
          text:
      prep_minutes:
        description: Minutes needed to prepare
        example: 30
        selector:
          number:
            min: 5
            max: 120
      travel_minutes:
        description: Travel time in minutes
        example: 20
        selector:
          number:
            min: 0
            max: 180
    """
    test_mode = _is_test_mode()

    if not event_time:
        return {"status": "error", "error": "event_time is required"}

    parsed = _parse_time_string(event_time)
    if not parsed:
        return {"status": "error", "error": f"cannot parse time: {event_time}"}

    ev_hour, ev_minute = parsed
    plan = _compute_optimal_plan(ev_hour, ev_minute, prep_minutes, travel_minutes)

    desc = event_description or "event"

    result = {
        "status": "ok",
        "event": desc,
        "event_time": f"{ev_hour:02d}:{ev_minute:02d}",
        "leave_by": plan["leave_by"],
        "start_prep": plan["start_prep"],
        "reminder_time": plan["reminder_time"],
        "prep_minutes": prep_minutes,
        "travel_minutes": travel_minutes,
    }

    _set_result(
        "ok", op="optimal_timing",
        event=desc,
        event_time=f"{ev_hour:02d}:{ev_minute:02d}",
        leave_by=plan["leave_by"],
    )

    if test_mode:
        log.info(  # noqa: F821
            f"schedule [TEST]: optimal timing = "
            f"{json.dumps(result, separators=(',', ':'))}"
        )
    else:
        log.info(  # noqa: F821
            f"schedule: optimal timing for {desc} at "
            f"{ev_hour:02d}:{ev_minute:02d} — "
            f"prep {plan['start_prep']}, leave {plan['leave_by']}"
        )

    return result


# ── Prediction Feedback Loop ─────────────────────────────────────────────────

@event_trigger("ai_routine_completed")  # noqa: F821
async def _on_routine_completed(**kwargs):
    """Record prediction feedback when a routine completes.

    Compares predicted routine start time (from advisor) against actual
    completion time. Classifies as reinforced / neutral / weakened and
    stores in L2.
    """
    test_mode = _is_test_mode()
    fp_id = kwargs.get("fingerprint_id", "")

    if not fp_id:
        return

    # Only track bed-ending routines for bedtime prediction feedback
    if not fp_id.endswith("_bed"):
        return

    now = datetime.now()
    actual_time_str = now.strftime("%H:%M")

    # Get predicted routine start from helper
    predicted_str = ""
    try:
        predicted_str = str(
            state.get("input_datetime.ai_predicted_routine_start") or ""  # noqa: F821
        )
    except NameError:
        pass

    # Compute delta (actual completion vs predicted start)
    delta_minutes = None
    if predicted_str and ":" in predicted_str:
        predicted_parsed = _parse_time_string(predicted_str)
        if predicted_parsed:
            pred_mins = predicted_parsed[0] * 60 + predicted_parsed[1]
            actual_mins = now.hour * 60 + now.minute
            # Handle midnight wrap
            delta = actual_mins - pred_mins
            if delta < -720:
                delta += 1440
            elif delta > 720:
                delta -= 1440
            delta_minutes = delta

    # Classify outcome
    if delta_minutes is not None:
        abs_delta = abs(delta_minutes)
        if abs_delta <= FEEDBACK_GOOD_THRESHOLD:
            outcome = "reinforced"
        elif abs_delta > FEEDBACK_BAD_THRESHOLD:
            outcome = "weakened"
        else:
            outcome = "neutral"
    else:
        outcome = "no_prediction"

    # Build feedback entry
    feedback = {
        "fingerprint_id": fp_id,
        "predicted_time": predicted_str,
        "actual_time": actual_time_str,
        "delta_minutes": delta_minutes,
        "outcome": outcome,
        "timestamp": now.isoformat(),
    }

    date_str = now.strftime("%Y-%m-%d")
    l2_key = f"prediction:feedback:{date_str}"
    l2_value = json.dumps(feedback, separators=(",", ":"))
    l2_tags = f"prediction feedback {fp_id}"

    if test_mode:
        log.info(  # noqa: F821
            f"schedule [TEST]: WOULD store feedback: {feedback}"
        )
    else:
        await _l2_set(l2_key, l2_value, l2_tags, expiration_days=90)
        log.info(  # noqa: F821
            f"schedule: feedback — {outcome} "
            f"(delta={delta_minutes}m, fp={fp_id})"
        )


# ── Smart Bedtime Trigger ────────────────────────────────────────────────────

@time_trigger(  # noqa: F821
    "cron(0,30 20-23 * * *)",
    "cron(0,30 0-1 * * *)",
    "cron(0 2 * * *)",
)
async def _bedtime_check():
    """Periodic bedtime advisory (every 30 min, 20:00-02:00).

    Runs the bedtime advisor and fires events:
      ai_bedtime_advisory  — when <=15 min to target routine start
      ai_bedtime_overdue   — when past target and routine not active
    """
    test_mode = _is_test_mode()

    # Run the advisor (updates helpers as a side effect)
    result = await schedule_bedtime_advisor()
    if not isinstance(result, dict) or result.get("status") != "ok":
        return

    minutes_until = result.get("minutes_until_routine", 999)
    recommendation = result.get("recommendation", "")

    # Check if bedtime routine is already active
    try:
        routine_stage = str(
            state.get("input_text.ai_routine_stage") or "none"  # noqa: F821
        )
    except NameError:
        routine_stage = "none"
    routine_active = routine_stage != "none" and "bed" in routine_stage

    try:
        bedtime_predicted = (
            str(state.get("input_boolean.ai_bedtime_predicted") or "off").lower()  # noqa: F821
            == "on"
        )
    except NameError:
        bedtime_predicted = False

    if test_mode:
        log.info(  # noqa: F821
            f"schedule [TEST]: bedtime check — "
            f"minutes_until={minutes_until}, "
            f"routine_active={routine_active}, "
            f"bedtime_predicted={bedtime_predicted}"
        )
        return  # Don't fire events in test mode

    # ── Overdue: past target AND routine hasn't started ──
    if minutes_until <= 0 and not routine_active:
        event.fire(  # noqa: F821
            "ai_bedtime_overdue",
            recommendation=recommendation,
            minutes_overdue=abs(minutes_until),
            confidence=result.get("confidence", "low"),
        )
        log.info(  # noqa: F821
            f"schedule: OVERDUE fired — "
            f"{abs(minutes_until)}m past target"
        )

    # ── Advisory: <=15 min AND bedtime not already predicted/active ──
    elif minutes_until <= 15 and not bedtime_predicted and not routine_active:
        event.fire(  # noqa: F821
            "ai_bedtime_advisory",
            recommendation=recommendation,
            minutes_until=minutes_until,
            confidence=result.get("confidence", "low"),
            first_event=result.get("first_event_tomorrow", ""),
        )
        log.info(  # noqa: F821
            f"schedule: advisory fired — {recommendation}"
        )


# ── Startup ──────────────────────────────────────────────────────────────────

@time_trigger("startup")  # noqa: F821
async def _startup():
    """Initialize on startup."""
    _ensure_result_entity_name(force=True)
    _set_result("ok", op="startup", message="initializing")
    log.info("schedule: predictive scheduling engine starting")  # noqa: F821
    _set_result("ok", op="startup", message="ready")

    # -- Bootstrap: run initial analysis after fingerprints populate --------
    await asyncio.sleep(240)  # after routine extraction completes
    try:
        result = await schedule_bedtime_advisor()
        log.info(f"schedule: startup advisory -- {result}")  # noqa: F821
    except Exception as exc:
        log.warning(f"schedule: startup advisory failed: {exc}")  # noqa: F821
