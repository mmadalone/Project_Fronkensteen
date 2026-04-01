"""Task 20: Anti-ADHD Focus Guard with Escalating Nudges.

Evaluates 6 nudge conditions (time-check, meal, calendar, social, break,
bedtime) every 15 minutes and on FP2 zone changes, delivering escalating
TTS nudges via the priority queue. Respects focus-mode and snooze states,
and logs nudge patterns to L2 memory.
"""
import time
from datetime import datetime, timedelta
import asyncio
from typing import Any

from shared_utils import build_result_entity_name, load_entity_config, reload_entity_config

# =============================================================================
# AI Focus Guard — Task 20 of Voice Context Architecture
# =============================================================================
# Anti-ADHD nudge system: evaluates 6 nudge conditions every 15 minutes
# (and on FP2 zone changes), delivers escalating TTS nudges via priority
# queue, respects focus mode and snooze, logs patterns to L2.
#
# Services:
#   pyscript.focus_guard_evaluate
#     Full evaluation of all 6 nudge conditions. Returns which nudges fired,
#     their priority levels, and escalation states. Can be called on-demand
#     or by the 15-min cron / FP2 state trigger.
#
#   pyscript.focus_guard_mark_meal
#     Set last_meal_time to now. Called by voice: "I just ate."
#
#   pyscript.focus_guard_snooze
#     Snooze all non-critical nudges for N minutes (default 30).
#     Called by voice: "Remind me in 30 minutes."
#
# Nudge types:
#   1. time_check     — workshop > threshold hours (P4→P3→P2, +30min each)
#   2. meal_reminder  — last meal > 4h, not sleeping (P4→P3→P2)
#   3. calendar_warn  — appointment < 60/30/15 min (P3→P2→P1)
#   4. social_nudge   — partner home > 30min, user solo zone (P4→P3)
#   5. break_suggest  — same zone > 2h, no change (P4 only)
#   6. bedtime_approach — within 1h of bedtime (P3→P2→P1)
#
# Escalation: each type tracks independently. Escalates every 30 minutes
# if the condition persists and the nudge hasn't been acknowledged.
#
# Focus mode: suppresses all non-calendar nudges. Calendar warnings at
# P1 (critical) always bypass focus mode AND snooze.
#
# Dependencies:
#   pyscript/agent_dispatcher.py (agent_dispatch — TTS voice selection)
#   pyscript/tts_queue.py (tts_queue_speak)
#   pyscript/notification_dedup.py (dedup_check, dedup_register)
#   pyscript/memory.py (memory_set — L2 snooze pattern logging)
#   packages/ai_focus_guard.yaml (helpers)
#   packages/ai_context_hot.yaml (bed time, presence)
#   packages/ai_identity.yaml (occupancy mode)
#   packages/ai_llm_budget.yaml (budget sensor)
#
# Deployed: 2026-03-03
# =============================================================================

RESULT_ENTITY = "sensor.ai_focus_guard_status"


def _get_fallback_tts_voice():
    """Return the default TTS voice from helper, or HA Cloud as fallback."""
    try:
        v = state.get("input_text.ai_default_tts_voice")  # noqa: F821
        if v and v not in ("unknown", "unavailable", ""):
            return str(v)
    except Exception:
        pass
    return "tts.home_assistant_cloud"


# Nudge cooldown: minimum seconds between same-type nudges
# NUDGE_COOLDOWN_SECONDS — now read from input_number.ai_focus_nudge_cooldown_minutes  # 30 minutes

# Escalation interval: seconds before escalating to next priority level
ESCALATION_INTERVAL = 1800  # 30 minutes

# Meal reminder threshold (hours since last meal)
# MEAL_REMINDER_HOURS — now read from input_number.ai_focus_meal_reminder_hours

# Calendar warning thresholds (minutes before event)
CALENDAR_WARN_THRESHOLDS = [60, 30, 15]

# Social nudge: partner must be home this many minutes before nudge
# SOCIAL_MIN_MINUTES — now read from input_number.ai_focus_social_nudge_minutes

# Break suggestion: same zone for this many hours before nudge
# BREAK_SUGGEST_HOURS — now read from input_number.ai_focus_break_suggest_hours

# Bedtime approach: nudge within this many minutes of bedtime
# BEDTIME_APPROACH_MINUTES — now read from input_number.ai_focus_bedtime_approach_minutes

# Budget threshold: below this %, skip agent-personality nudges
# BUDGET_PERSONALITY_THRESHOLD — now read from input_number.ai_budget_personality_threshold

def _get_fp2_zones() -> dict:
    """Get zone→entity map. Config stores entity→zone, so we invert."""
    cfg = load_entity_config()
    fp2 = cfg.get("fp2_zones")
    if not fp2:
        log.warning("focus_guard: fp2_zones not found in entity_config.yaml")  # noqa: F821
        return {}
    return {v: k for k, v in fp2.items()}

# Nudge text templates (gentle → firm → urgent → critical)
NUDGE_TEXTS = {
    "time_check": [
        "Hey, you've been in the workshop for {hours} hours. Just a gentle heads up.",
        "Workshop session at {hours} hours now. Maybe a quick stretch?",
        "It's been {hours} hours in the workshop. Time to come up for air.",
    ],
    "meal_reminder": [
        "It's been a while since you ate. Might be a good time for a snack.",
        "Over {hours} hours since your last meal. Your body needs fuel.",
        "Seriously, {hours} hours without eating. Go grab something.",
    ],
    "calendar_warn": [
        "Heads up, you've got {event} in about {minutes} minutes.",
        "Your {event} is in {minutes} minutes. Time to get ready.",
        "Your {event} starts in {minutes} minutes. You need to go NOW.",
    ],
    "social_nudge": [
        "Your partner's been home for a bit. Maybe say hello?",
        "Your partner's been home for a while. Don't forget about the real world.",
    ],
    "break_suggest": [
        "You've been in the same spot for {hours} hours. A change of scenery might help.",
    ],
    "bedtime_approach": [
        "Bedtime is coming up in about {minutes} minutes. Start winding down.",
        "Only {minutes} minutes until bedtime. You should really wrap up.",
        "It's past your bedtime. Sleep is important. Go to bed.",
    ],
}

# ── Module-Level State ───────────────────────────────────────────────────────

result_entity_name: dict[str, str] = {}

# Escalation state machine: tracks last fire time and escalation level
# per nudge type. Reset on midnight or when condition clears.
# {nudge_type: {"level": 0-3, "last_fire": timestamp, "last_escalation": timestamp}}
_escalation_state: dict[str, dict] = {}

# Workshop hours: tracked by sensor.workshop_hours_today (history_stats).
# No manual accumulator needed — HA computes ON-time from recorder data.

# Last known active zone (for break suggestion)
_last_zone_change_time: float = 0.0
_last_active_zone: str = ""


# ── Entity Name Helpers (standard pattern) ────────────────────────────────────

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
def _get_escalation_level(nudge_type: str, esc_state: dict) -> int:
    """Get current escalation level for a nudge type (0-indexed)."""
    entry = esc_state.get(nudge_type)
    if not entry:
        return 0
    return entry.get("level", 0)


@pyscript_compile  # noqa: F821
def _should_escalate(nudge_type: str, esc_state: dict, now_ts: float) -> bool:
    """Check if it's time to escalate a nudge to the next level."""
    entry = esc_state.get(nudge_type)
    if not entry:
        return True  # First fire
    last_esc = entry.get("last_escalation", 0)
    return (now_ts - last_esc) >= ESCALATION_INTERVAL


def _should_fire(nudge_type: str, esc_state: dict, now_ts: float) -> bool:
    """Check cooldown: has enough time passed since last fire?"""
    entry = esc_state.get(nudge_type)
    if not entry:
        return True
    last_fire = entry.get("last_fire", 0)
    return (now_ts - last_fire) >= await _get_nudge_cooldown_seconds()


@pyscript_compile  # noqa: F821
def _get_nudge_text(nudge_type: str, level: int, **kwargs) -> str:
    """Get nudge text for given type and escalation level."""
    texts = NUDGE_TEXTS.get(nudge_type, [])
    if not texts:
        return f"Focus guard: {nudge_type} alert."
    idx = level
    if idx >= len(texts):
        idx = len(texts) - 1
    text = texts[idx]
    try:
        return text.format(**kwargs)
    except (KeyError, IndexError):
        return text


@pyscript_compile  # noqa: F821
def _level_to_priority(nudge_type: str, level: int) -> int:
    """Map escalation level to TTS priority (P1=highest, P4=lowest).

    Different nudge types have different starting priorities and max levels.
    """
    priority_maps = {
        "time_check": [4, 3, 2],       # gentle→firm→urgent
        "meal_reminder": [4, 3, 2],
        "calendar_warn": [3, 2, 1],     # starts higher, can go critical
        "social_nudge": [4, 3],
        "break_suggest": [4],           # P4 only, never escalates
        "bedtime_approach": [3, 2, 1],  # starts at P3, can go critical
    }
    pmap = priority_maps.get(nudge_type, [4])
    idx = level
    if idx >= len(pmap):
        idx = len(pmap) - 1
    return pmap[idx]


@pyscript_compile  # noqa: F821
def _max_escalation_level(nudge_type: str) -> int:
    """Maximum escalation level (0-indexed) for a nudge type."""
    level_counts = {
        "time_check": 3,
        "meal_reminder": 3,
        "calendar_warn": 3,
        "social_nudge": 2,
        "break_suggest": 1,
        "bedtime_approach": 3,
    }
    return level_counts.get(nudge_type, 1) - 1


@pyscript_compile  # noqa: F821
def _parse_time_str(time_str: str) -> tuple:
    """Parse HH:MM:SS or HH:MM time string to (hours, minutes)."""
    if not time_str or time_str in ("unknown", "unavailable", "None", ""):
        return (0, 0)
    parts = time_str.split(":")
    try:
        h = int(parts[0])
        m = int(parts[1]) if len(parts) > 1 else 0
        return (h, m)
    except (ValueError, IndexError):
        return (0, 0)


@pyscript_compile  # noqa: F821
def _parse_first_calendar_event(cal_raw: str, now_hour: int, now_minute: int) -> tuple:
    """Parse first upcoming timed event from compact calendar string.

    Returns (description, minutes_until) or (None, None).
    """
    if not cal_raw or cal_raw in ("", "No events", "unknown", "unavailable", "none"):
        return (None, None)

    now_mins = now_hour * 60 + now_minute

    for part in cal_raw.split("|"):
        part = part.strip()
        if len(part) >= 6 and part[2:3] == ":":
            time_str = part[:5]
            desc = part[6:].strip()
            try:
                h = int(time_str[:2])
                m = int(time_str[3:5])
                event_mins = h * 60 + m
                if event_mins > now_mins:
                    return (desc, event_mins - now_mins)
            except (ValueError, TypeError):
                continue

    return (None, None)


# ── State Access Helpers ──────────────────────────────────────────────────────

def _is_test_mode() -> bool:
    try:
        return str(
            state.get("input_boolean.ai_test_mode") or "off"  # noqa: F821
        ).lower() == "on"
    except NameError:
        return False


def _is_enabled() -> bool:
    try:
        return str(
            state.get("input_boolean.ai_focus_guard_enabled") or "on"  # noqa: F821
        ).lower() == "on"
    except NameError:
        return True


def _is_focus_mode() -> bool:
    try:
        return str(
            state.get("input_boolean.ai_focus_mode") or "off"  # noqa: F821
        ).lower() == "on"
    except NameError:
        return False


def _is_snoozed(now_ts: float) -> bool:
    """Check if nudges are currently snoozed."""
    try:
        snooze_state = state.get("input_datetime.ai_focus_guard_snooze_until")  # noqa: F821
        if not snooze_state or snooze_state in ("unknown", "unavailable", ""):
            return False
        snooze_dt = datetime.fromisoformat(snooze_state)
        return snooze_dt.timestamp() > now_ts
    except (ValueError, TypeError, NameError):
        return False


def _is_nudge_enabled(nudge_type: str) -> bool:
    """Check if a specific nudge type is enabled via its per-type toggle."""
    entity = f"input_boolean.ai_focus_{nudge_type}_enabled"
    try:
        return str(state.get(entity) or "on").lower() == "on"  # noqa: F821
    except NameError:
        return True  # default enabled if entity missing


# Satellite entity map — zone name → assist_satellite entity
ZONE_TO_SATELLITE = {
    "workshop": "assist_satellite.home_assistant_voice_0905c5_assist_satellite",
    "living_room": "assist_satellite.home_assistant_voice_0a0109_assist_satellite",
}

# Default satellite (workshop / Rick)
DEFAULT_SATELLITE = "assist_satellite.home_assistant_voice_0905c5_assist_satellite"


def _get_presence_satellite() -> str:
    """Get the assist satellite entity in the user's current zone."""
    for zone, fp2_entity in _get_fp2_zones().items():
        try:
            if str(state.get(fp2_entity) or "off").lower() == "on":  # noqa: F821
                sat = ZONE_TO_SATELLITE.get(zone)
                if sat:
                    return sat
        except NameError:
            continue
    return DEFAULT_SATELLITE


def _get_workshop_hours() -> float:
    """Read workshop hours from history_stats sensor (auto-computed by HA)."""
    try:
        return float(
            state.get("sensor.workshop_hours_today") or 0  # noqa: F821
        )
    except (ValueError, TypeError, NameError):
        return 0.0


def _get_threshold_hours() -> float:
    try:
        return float(
            state.get("input_number.ai_focus_guard_threshold_hours") or 2  # noqa: F821
        )
    except (ValueError, TypeError, NameError):
        return 2.0


def _get_hours_since_meal(now_ts: float) -> float:
    """Get hours since last meal. Returns 0 if no meal recorded."""
    try:
        meal_state = state.get("input_datetime.ai_last_meal_time")  # noqa: F821
        if not meal_state or meal_state in ("unknown", "unavailable", ""):
            return 0.0
        meal_dt = datetime.fromisoformat(meal_state)
        diff = now_ts - meal_dt.timestamp()
        if diff < 0:
            return 0.0
        return diff / 3600.0
    except (ValueError, TypeError, NameError):
        return 0.0


def _get_bed_time_minutes() -> int:
    """Get bedtime as minutes from midnight. Uses household bedtime."""
    try:
        bed_state = state.get("input_datetime.ai_context_bed_time")  # noqa: F821
        if not bed_state or bed_state in ("unknown", "unavailable", ""):
            return 22 * 60 + 30  # default 22:30
        h, m = _parse_time_str(bed_state)
        return h * 60 + m
    except NameError:
        return 22 * 60 + 30


def _get_occupancy_mode() -> str:
    try:
        return str(state.get("sensor.occupancy_mode") or "away")  # noqa: F821
    except NameError:
        return "away"


def _get_budget_remaining() -> int:
    try:
        return int(float(
            state.get("sensor.ai_llm_budget_remaining") or "100"  # noqa: F821
        ))
    except (ValueError, TypeError, NameError):
        return 100



def _get_meal_reminder_hours() -> float:
    try:
        return float(
            state.get("input_number.ai_focus_meal_reminder_hours") or 4  # noqa: F821
        )
    except (ValueError, TypeError, NameError):
        return 4.0


def _get_nudge_cooldown_seconds() -> int:
    try:
        return int(float(
            state.get("input_number.ai_focus_nudge_cooldown_minutes") or 30  # noqa: F821
        ) * 60)
    except (ValueError, TypeError, NameError):
        return 1800


def _get_social_min_minutes() -> float:
    try:
        return float(
            state.get("input_number.ai_focus_social_nudge_minutes") or 30  # noqa: F821
        )
    except (ValueError, TypeError, NameError):
        return 30.0


def _get_break_suggest_hours() -> float:
    try:
        return float(
            state.get("input_number.ai_focus_break_suggest_hours") or 2  # noqa: F821
        )
    except (ValueError, TypeError, NameError):
        return 2.0


def _get_bedtime_approach_minutes() -> int:
    try:
        return int(float(
            state.get("input_number.ai_focus_bedtime_approach_minutes") or 60  # noqa: F821
        ))
    except (ValueError, TypeError, NameError):
        return 60


def _get_budget_personality_threshold() -> int:
    try:
        return int(float(
            state.get("input_number.ai_budget_personality_threshold") or 20  # noqa: F821
        ))
    except (ValueError, TypeError, NameError):
        return 20

def _get_active_zones() -> list:
    """Get list of currently active FP2 zones."""
    active = []
    for zone_name, entity_id in _get_fp2_zones().items():
        try:
            if str(state.get(entity_id) or "off").lower() == "on":  # noqa: F821
                active.append(zone_name)
        except NameError:
            pass
    return active


def _is_in_workshop() -> bool:
    try:
        return str(
            state.get(_get_fp2_zones()["workshop"]) or "off"  # noqa: F821
        ).lower() == "on"
    except NameError:
        return False


def _is_sleeping() -> bool:
    """Heuristic: in bed zone + house in bedtime mode."""
    try:
        in_bed = str(
            state.get(_get_fp2_zones()["bed"]) or "off"  # noqa: F821
        ).lower() == "on"
        bedtime_active = str(
            state.get("sensor.ai_bedtime_active") or "off"  # noqa: F821
        ).lower() == "on"
        bedtime_locked = str(
            state.get("input_boolean.ai_bedtime_global_lock") or "off"  # noqa: F821
        ).lower() == "on"
        return in_bed and (bedtime_active or bedtime_locked)
    except NameError:
        return False


# ── Workshop Time Tracking ───────────────────────────────────────────────────

# _update_workshop_accumulator: REMOVED — workshop hours now tracked by
# sensor.workshop_hours_today (history_stats platform, auto-computed by HA).


# ── Escalation State Management ──────────────────────────────────────────────

def _record_fire(nudge_type: str, level: int, now_ts: float) -> None:
    """Record that a nudge fired at a given level."""
    global _escalation_state
    _escalation_state[nudge_type] = {
        "level": level,
        "last_fire": now_ts,
        "last_escalation": now_ts,
    }


def _clear_escalation(nudge_type: str) -> None:
    """Clear escalation state when condition resolves."""
    global _escalation_state
    if nudge_type in _escalation_state:
        del _escalation_state[nudge_type]


def _advance_escalation(nudge_type: str, now_ts: float) -> int:
    """Advance escalation level if interval has passed. Returns new level."""
    global _escalation_state
    entry = _escalation_state.get(nudge_type)
    if not entry:
        return 0

    max_level = _max_escalation_level(nudge_type)
    current_level = entry.get("level", 0)

    if current_level >= max_level:
        return current_level

    if _should_escalate(nudge_type, _escalation_state, now_ts):
        new_level = current_level + 1
        if new_level > max_level:
            new_level = max_level
        entry["level"] = new_level
        entry["last_escalation"] = now_ts
        return new_level

    return current_level


# ── Nudge Condition Evaluators ───────────────────────────────────────────────

def _eval_time_check(now_ts: float) -> dict:
    """Evaluate workshop time check nudge."""
    workshop_hours = _get_workshop_hours()
    threshold = _get_threshold_hours()

    if workshop_hours < threshold:
        _clear_escalation("time_check")
        return {"fire": False, "reason": "below_threshold"}

    if not _should_fire("time_check", _escalation_state, now_ts):
        return {"fire": False, "reason": "cooldown"}

    level = _advance_escalation("time_check", now_ts)
    if "time_check" not in _escalation_state:
        level = 0

    priority = _level_to_priority("time_check", level)
    text = _get_nudge_text("time_check", level, hours=round(workshop_hours, 1))

    _record_fire("time_check", level, now_ts)

    return {
        "fire": True,
        "type": "time_check",
        "level": level,
        "priority": priority,
        "text": text,
        "workshop_hours": round(workshop_hours, 1),
    }


def _eval_meal_reminder(now_ts: float) -> dict:
    """Evaluate meal reminder nudge."""
    if _is_sleeping():
        _clear_escalation("meal_reminder")
        return {"fire": False, "reason": "sleeping"}

    hours_since = _get_hours_since_meal(now_ts)
    if hours_since <= 0:
        return {"fire": False, "reason": "no_meal_recorded"}

    if hours_since < _get_meal_reminder_hours():
        _clear_escalation("meal_reminder")
        return {"fire": False, "reason": "recent_meal"}

    if not _should_fire("meal_reminder", _escalation_state, now_ts):
        return {"fire": False, "reason": "cooldown"}

    level = _advance_escalation("meal_reminder", now_ts)
    if "meal_reminder" not in _escalation_state:
        level = 0

    priority = _level_to_priority("meal_reminder", level)
    text = _get_nudge_text("meal_reminder", level, hours=round(hours_since, 1))

    _record_fire("meal_reminder", level, now_ts)

    return {
        "fire": True,
        "type": "meal_reminder",
        "level": level,
        "priority": priority,
        "text": text,
        "hours_since_meal": round(hours_since, 1),
    }


def _eval_calendar_warn(now_ts: float) -> dict:
    """Evaluate calendar warning nudge."""
    try:
        cal_raw = state.get(  # noqa: F821
            "sensor.ai_calendar_today_summary",
        ) or ""
    except (NameError, Exception):
        return {"fire": False, "reason": "no_calendar_data"}

    now_dt = datetime.now()
    event_desc, minutes_until = _parse_first_calendar_event(
        cal_raw, now_dt.hour, now_dt.minute,
    )

    if event_desc is None or minutes_until is None:
        _clear_escalation("calendar_warn")
        return {"fire": False, "reason": "no_upcoming_event"}

    if minutes_until > CALENDAR_WARN_THRESHOLDS[0]:
        _clear_escalation("calendar_warn")
        return {"fire": False, "reason": "event_too_far"}

    if not _should_fire("calendar_warn", _escalation_state, now_ts):
        return {"fire": False, "reason": "cooldown"}

    # Determine level based on time remaining
    if minutes_until <= CALENDAR_WARN_THRESHOLDS[2]:
        level = 2  # Critical
    elif minutes_until <= CALENDAR_WARN_THRESHOLDS[1]:
        level = 1  # Urgent
    else:
        level = 0  # Firm

    priority = _level_to_priority("calendar_warn", level)
    text = _get_nudge_text(
        "calendar_warn", level,
        event=event_desc, minutes=minutes_until,
    )

    _record_fire("calendar_warn", level, now_ts)

    return {
        "fire": True,
        "type": "calendar_warn",
        "level": level,
        "priority": priority,
        "text": text,
        "event": event_desc,
        "minutes_until": minutes_until,
        "bypasses_focus": True,
    }


def _eval_social_nudge(now_ts: float) -> dict:
    """Evaluate social nudge: partner home, user in solo zone."""
    occupancy = _get_occupancy_mode()

    if occupancy != "dual":
        _clear_escalation("social_nudge")
        return {"fire": False, "reason": "not_dual_occupancy"}

    # Check if user is in a solo zone (workshop typically)
    active_zones = _get_active_zones()
    if len(active_zones) != 1 or active_zones[0] not in ("workshop",):
        _clear_escalation("social_nudge")
        return {"fire": False, "reason": "not_in_solo_zone"}

    # Check partner has been home long enough
    # We use the sustained solo zone check as a proxy — if dual mode
    # has been active for 30+ minutes and user is still in workshop
    if not _should_fire("social_nudge", _escalation_state, now_ts):
        return {"fire": False, "reason": "cooldown"}

    # Only fire if workshop hours > 0.5h (to avoid instant nudge on arrival)
    workshop_hours = _get_workshop_hours()
    if workshop_hours < 0.5:
        return {"fire": False, "reason": "just_started"}

    level = _advance_escalation("social_nudge", now_ts)
    if "social_nudge" not in _escalation_state:
        level = 0

    priority = _level_to_priority("social_nudge", level)
    text = _get_nudge_text("social_nudge", level)

    _record_fire("social_nudge", level, now_ts)

    return {
        "fire": True,
        "type": "social_nudge",
        "level": level,
        "priority": priority,
        "text": text,
    }


def _eval_break_suggest(now_ts: float) -> dict:
    """Evaluate break suggestion: same zone for > 2h."""
    global _last_zone_change_time, _last_active_zone

    active_zones = _get_active_zones()

    if not active_zones:
        _clear_escalation("break_suggest")
        return {"fire": False, "reason": "no_presence"}

    current_zone = active_zones[0] if len(active_zones) == 1 else ""

    if not current_zone:
        _clear_escalation("break_suggest")
        return {"fire": False, "reason": "multi_zone"}

    # Track zone changes
    if current_zone != _last_active_zone:
        _last_active_zone = current_zone
        _last_zone_change_time = now_ts
        _clear_escalation("break_suggest")
        return {"fire": False, "reason": "zone_changed"}

    if _last_zone_change_time == 0:
        _last_zone_change_time = now_ts
        return {"fire": False, "reason": "tracking_started"}

    hours_same_zone = (now_ts - _last_zone_change_time) / 3600.0

    if hours_same_zone < _get_break_suggest_hours():
        return {"fire": False, "reason": "too_short"}

    if not _should_fire("break_suggest", _escalation_state, now_ts):
        return {"fire": False, "reason": "cooldown"}

    level = 0  # Break suggest never escalates
    priority = _level_to_priority("break_suggest", level)
    text = _get_nudge_text(
        "break_suggest", level,
        hours=round(hours_same_zone, 1),
    )

    _record_fire("break_suggest", level, now_ts)

    return {
        "fire": True,
        "type": "break_suggest",
        "level": level,
        "priority": priority,
        "text": text,
        "hours_same_zone": round(hours_same_zone, 1),
        "zone": current_zone,
    }


def _eval_bedtime_approach(now_ts: float) -> dict:
    """Evaluate bedtime approach nudge."""
    if _is_sleeping():
        _clear_escalation("bedtime_approach")
        return {"fire": False, "reason": "already_sleeping"}

    now_dt = datetime.now()
    now_minutes = now_dt.hour * 60 + now_dt.minute
    bed_minutes = _get_bed_time_minutes()

    # Handle midnight crossing
    diff = bed_minutes - now_minutes
    if diff < -120:
        diff += 1440  # Next day
    elif diff < 0:
        # Past bedtime
        diff = 0

    if diff > _get_bedtime_approach_minutes():
        _clear_escalation("bedtime_approach")
        return {"fire": False, "reason": "bedtime_far"}

    if not _should_fire("bedtime_approach", _escalation_state, now_ts):
        return {"fire": False, "reason": "cooldown"}

    # Determine level based on time remaining
    if diff <= 0:
        level = 2  # Past bedtime → critical
    elif diff <= 15:
        level = 2  # Very close → urgent
    elif diff <= 30:
        level = 1
    else:
        level = 0

    # Also check escalation progression
    esc_level = _advance_escalation("bedtime_approach", now_ts)
    if "bedtime_approach" not in _escalation_state:
        esc_level = 0
    level = max(level, esc_level)  # Use whichever is higher

    max_level = _max_escalation_level("bedtime_approach")
    if level > max_level:
        level = max_level

    priority = _level_to_priority("bedtime_approach", level)
    text = _get_nudge_text(
        "bedtime_approach", level,
        minutes=max(diff, 0),
    )

    _record_fire("bedtime_approach", level, now_ts)

    return {
        "fire": True,
        "type": "bedtime_approach",
        "level": level,
        "priority": priority,
        "text": text,
        "minutes_to_bed": diff,
    }


# ── Core Evaluation Logic ────────────────────────────────────────────────────

async def _evaluate_all(test_mode: bool = False) -> dict:
    """Evaluate all nudge conditions and fire applicable ones.

    Returns summary dict with all evaluations and actions taken.
    """
    t_start = time.monotonic()
    now_ts = time.time()

    # Workshop hours: read from sensor.workshop_hours_today (history_stats)

    # Check global gates
    if not _is_enabled():
        elapsed = round((time.monotonic() - t_start) * 1000, 1)
        return {
            "status": "ok", "op": "evaluate",
            "skipped": True, "reason": "disabled",
            "elapsed_ms": elapsed,
        }

    focus_on = _is_focus_mode()
    snoozed = _is_snoozed(now_ts)

    # Evaluate all nudge conditions
    evaluations = {}
    nudges_to_fire = []

    # 1. Time check
    if _is_nudge_enabled("time_check"):
        tc = _eval_time_check(now_ts)
        evaluations["time_check"] = tc
        if tc.get("fire"):
            if not focus_on and not snoozed:
                nudges_to_fire.append(tc)
            elif test_mode:
                tc["suppressed_by"] = "focus_mode" if focus_on else "snooze"
    else:
        evaluations["time_check"] = {"fire": False, "reason": "disabled"}

    # 2. Meal reminder
    if _is_nudge_enabled("meal_reminder"):
        mr = _eval_meal_reminder(now_ts)
        evaluations["meal_reminder"] = mr
        if mr.get("fire"):
            if not focus_on and not snoozed:
                nudges_to_fire.append(mr)
            elif test_mode:
                mr["suppressed_by"] = "focus_mode" if focus_on else "snooze"
    else:
        evaluations["meal_reminder"] = {"fire": False, "reason": "disabled"}

    # 3. Calendar warning (BYPASSES focus mode and snooze at P1)
    if _is_nudge_enabled("calendar_warn"):
        cw = _eval_calendar_warn(now_ts)
        evaluations["calendar_warn"] = cw
        if cw.get("fire"):
            bypasses = cw.get("bypasses_focus", False) and cw.get("priority", 4) <= 1
            if bypasses or (not focus_on and not snoozed):
                nudges_to_fire.append(cw)
            elif not snoozed and not focus_on:
                nudges_to_fire.append(cw)
            elif test_mode:
                cw["suppressed_by"] = "focus_mode" if focus_on else "snooze"
            else:
                # Calendar always fires regardless of focus/snooze
                nudges_to_fire.append(cw)
    else:
        evaluations["calendar_warn"] = {"fire": False, "reason": "disabled"}

    # 4. Social nudge
    if _is_nudge_enabled("social_nudge"):
        sn = _eval_social_nudge(now_ts)
        evaluations["social_nudge"] = sn
        if sn.get("fire"):
            if not focus_on and not snoozed:
                nudges_to_fire.append(sn)
            elif test_mode:
                sn["suppressed_by"] = "focus_mode" if focus_on else "snooze"
    else:
        evaluations["social_nudge"] = {"fire": False, "reason": "disabled"}

    # 5. Break suggestion
    if _is_nudge_enabled("break_suggest"):
        bs = _eval_break_suggest(now_ts)
        evaluations["break_suggest"] = bs
        if bs.get("fire"):
            if not focus_on and not snoozed:
                nudges_to_fire.append(bs)
            elif test_mode:
                bs["suppressed_by"] = "focus_mode" if focus_on else "snooze"
    else:
        evaluations["break_suggest"] = {"fire": False, "reason": "disabled"}

    # 6. Bedtime approach
    if _is_nudge_enabled("bedtime_approach"):
        ba = _eval_bedtime_approach(now_ts)
        evaluations["bedtime_approach"] = ba
        if ba.get("fire"):
            if not focus_on and not snoozed:
                nudges_to_fire.append(ba)
            elif test_mode:
                ba["suppressed_by"] = "focus_mode" if focus_on else "snooze"
    else:
        evaluations["bedtime_approach"] = {"fire": False, "reason": "disabled"}

    # ── Dispatcher: resolve TTS voice for nudge delivery ──
    voice = _get_fallback_tts_voice()
    voice_id = ""
    try:
        dispatch_call = pyscript.agent_dispatch(  # noqa: F821
            wake_word="focus_guard",
            intent_text="focus guard nudge",
            skip_continuity=True,
        )
        dispatch_resp = await dispatch_call
        if dispatch_resp and dispatch_resp.get("tts_engine"):
            voice = dispatch_resp["tts_engine"]
            voice_id = dispatch_resp.get("tts_voice", "")
    except Exception:
        pass  # fallback voice is fine

    # Fire nudges via TTS queue
    fired = []
    for nudge in nudges_to_fire:
        nudge_type = nudge.get("type", "unknown")
        text = nudge.get("text", "")
        priority = nudge.get("priority", 4)

        if test_mode:
            log.info(  # noqa: F821
                f"focus_guard [TEST]: WOULD fire {nudge_type} "
                f"(P{priority}, level={nudge.get('level', 0)}): {text}"
            )
            fired.append({
                "type": nudge_type,
                "priority": priority,
                "level": nudge.get("level", 0),
                "text": text,
                "delivered": False,
                "test_mode": True,
            })
            continue

        # Deliver via TTS queue
        tts_ok = False
        try:
            tts_call = pyscript.tts_queue_speak(  # noqa: F821
                text=text,
                voice=voice,
                voice_id=voice_id,
                priority=priority,
                target_mode="presence",
            )
            tts_resp = await tts_call
            tts_ok = (
                tts_resp is not None
                and tts_resp.get("status") == "queued"
            )
        except Exception as exc:
            log.error(  # noqa: F821
                f"focus_guard: TTS delivery failed for {nudge_type}: {exc}"
            )

        fired.append({
            "type": nudge_type,
            "priority": priority,
            "level": nudge.get("level", 0),
            "text": text,
            "delivered": tts_ok,
        })

        if tts_ok:
            log.info(  # noqa: F821
                f"focus_guard: fired {nudge_type} P{priority} "
                f"level={nudge.get('level', 0)}"
            )

            # Meal reminder mic follow-up: open satellite for voice response
            if nudge_type == "meal_reminder":
                try:
                    ask_eaten = str(
                        state.get("input_boolean.ai_focus_meal_ask_eaten") or "off"  # noqa: F821
                    ).lower() == "on"
                except NameError:
                    ask_eaten = False
                if ask_eaten:
                    try:
                        await asyncio.sleep(2)
                        await service.call(  # noqa: F821
                            "assist_satellite", "start_conversation",
                            entity_id=_get_presence_satellite(),
                            preannounce=False,
                            extra_system_prompt=(
                                "The user just heard a meal reminder. They may tell you "
                                "when they last ate (e.g. 'I ate at 14:00'). If so, call "
                                "pyscript.focus_guard_mark_meal with meal_time set to the "
                                "time they mentioned. If they say 'I just ate' without a "
                                "specific time, call it without meal_time to stamp now."
                            ),
                        )
                    except Exception as exc:
                        log.error(f"focus_guard: mic follow-up failed: {exc}")  # noqa: F821

    elapsed = round((time.monotonic() - t_start) * 1000, 1)

    result = {
        "status": "ok",
        "op": "evaluate",
        "focus_mode": focus_on,
        "snoozed": snoozed,
        "workshop_hours": round(_get_workshop_hours(), 2),
        "nudges_evaluated": len(evaluations),
        "nudges_fired": len(fired),
        "fired": fired,
        "test_mode": test_mode,
        "elapsed_ms": elapsed,
    }

    if test_mode:
        result["evaluations"] = evaluations

    # Update status sensor
    sensor_state = "test" if test_mode else ("active" if fired else "ok")
    _set_result(
        sensor_state,
        op="evaluate",
        focus_mode=focus_on,
        snoozed=snoozed,
        workshop_hours=round(_get_workshop_hours(), 2),
        nudges_fired=len(fired),
        last_nudge=fired[-1]["type"] if fired else "none",
        test_mode=test_mode,
        elapsed_ms=elapsed,
    )

    return result


# ── Services ─────────────────────────────────────────────────────────────────

@service(supports_response="only")  # noqa: F821
async def focus_guard_evaluate():
    """
    yaml
    name: Focus Guard Evaluate
    description: >-
      Evaluate all 6 focus guard nudge conditions and fire applicable ones.
      Each nudge type tracks its own escalation level independently.
      Focus mode suppresses non-calendar nudges. Calendar warnings at P1
      always bypass focus mode and snooze. Called by 15-min cron, FP2
      zone changes, or on-demand.
    """
    test_mode = _is_test_mode()
    return await _evaluate_all(test_mode=test_mode)


@service(supports_response="only")  # noqa: F821
async def focus_guard_mark_meal(meal_time=None):
    """
    yaml
    name: Focus Guard - Mark Meal
    description: >-
      Set last_meal_time to a given timestamp (or now if omitted). Call via
      voice command ("I just ate" or "I ate at 14:00") or button press to
      reset the meal reminder timer.
    fields:
      meal_time:
        description: >-
          Optional time the meal was eaten. Accepts "HH:MM" (assumes today)
          or "YYYY-MM-DD HH:MM:SS". Omit to stamp current time.
        required: false
        example: "14:00"
        selector:
          text:
    """
    if meal_time is not None:
        meal_time = str(meal_time).strip()
        now_dt = None
        # Try HH:MM (assume today)
        try:
            parsed = datetime.strptime(meal_time, "%H:%M")
            now_dt = datetime.now().replace(
                hour=parsed.hour, minute=parsed.minute, second=0, microsecond=0,
            )
        except ValueError:
            pass
        # Try full datetime
        if now_dt is None:
            try:
                now_dt = datetime.strptime(meal_time, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                pass
        if now_dt is None:
            return {
                "status": "error",
                "error": f"Invalid meal_time format: {meal_time}. Use HH:MM or YYYY-MM-DD HH:MM:SS.",
            }
    else:
        now_dt = datetime.now()

    now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")

    try:
        await service.call(  # noqa: F821
            "input_datetime", "set_datetime",
            entity_id="input_datetime.ai_last_meal_time",
            datetime=now_str,
        )
    except Exception as exc:
        log.error(f"focus_guard: failed to set meal time: {exc}")  # noqa: F821
        return {"status": "error", "error": str(exc)}

    # Clear meal reminder escalation
    _clear_escalation("meal_reminder")

    log.info(f"focus_guard: meal marked at {now_str}")  # noqa: F821

    _set_result("ok", op="mark_meal", meal_time=now_str)

    return {
        "status": "ok",
        "op": "mark_meal",
        "meal_time": now_str,
    }


@service(supports_response="only")  # noqa: F821
async def focus_guard_snooze(minutes=30):
    """
    yaml
    name: Focus Guard - Snooze
    description: >-
      Snooze all non-critical nudges for N minutes (default 30). Calendar
      P1 nudges still bypass snooze. Voice command: "remind me in 30 minutes."
    fields:
      minutes:
        description: "Minutes to snooze (default 30)"
        required: false
        default: 30
        example: "30"
        selector:
          number:
            min: 5
            max: 120
    """
    try:
        mins = int(float(minutes or 30))
    except (ValueError, TypeError):
        mins = 30

    snooze_until = datetime.now() + timedelta(minutes=mins)
    snooze_str = snooze_until.strftime("%Y-%m-%d %H:%M:%S")

    try:
        await service.call(  # noqa: F821
            "input_datetime", "set_datetime",
            entity_id="input_datetime.ai_focus_guard_snooze_until",
            datetime=snooze_str,
        )
    except Exception as exc:
        log.error(f"focus_guard: failed to set snooze: {exc}")  # noqa: F821
        return {"status": "error", "error": str(exc)}

    # Log snooze pattern to L2 (best-effort)
    try:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        mem_call = pyscript.memory_set(  # noqa: F821
            key=f"focus_snooze:{now_str}",
            value=f"Snoozed for {mins} minutes at {now_str}",
            scope="system",
            tags="focus,snooze,pattern",
        )
        await mem_call
    except Exception:
        pass  # L2 logging is best-effort

    log.info(  # noqa: F821
        f"focus_guard: snoozed for {mins} minutes until {snooze_str}"
    )

    _set_result("ok", op="snooze", minutes=mins, until=snooze_str)

    return {
        "status": "ok",
        "op": "snooze",
        "minutes": mins,
        "snooze_until": snooze_str,
    }


# ── Triggers ─────────────────────────────────────────────────────────────────

@time_trigger("cron(*/15 * * * *)")  # noqa: F821
async def _cron_evaluate():
    """15-minute evaluation cycle."""
    if not _is_enabled():
        return

    test_mode = _is_test_mode()
    result = await _evaluate_all(test_mode=test_mode)

    if result.get("nudges_fired", 0) > 0:
        log.info(  # noqa: F821
            f"focus_guard [cron]: {result['nudges_fired']} nudges fired"
        )


@state_trigger(  # noqa: F821
    "binary_sensor.fp2_presence_sensor_workshop",
    state_check_now=False,
)
async def _workshop_zone_change(**kwargs):
    """React to workshop zone changes for immediate re-evaluation."""
    if not _is_enabled():
        return

    # Let zone settle through FP2 flapping (was 2s, raised to 10s)
    await asyncio.sleep(10)  # noqa: F821

    test_mode = _is_test_mode()
    result = await _evaluate_all(test_mode=test_mode)

    if result.get("nudges_fired", 0) > 0:
        log.info(  # noqa: F821
            f"focus_guard [zone]: {result['nudges_fired']} nudges fired"
        )


@state_trigger(  # noqa: F821
    "binary_sensor.fp2_presence_sensor_living_room == 'on'",
    "binary_sensor.fp2_presence_sensor_kitchen == 'on'",
    "binary_sensor.fp2_presence_sensor_bathroom == 'on'",
    "binary_sensor.fp2_presence_sensor_bed == 'on'",
    "binary_sensor.fp2_presence_sensor_main_room == 'on'",
    state_check_now=False,
)
async def _zone_change_re_eval(**kwargs):
    """React to any zone becoming active for break suggestion tracking."""
    global _last_zone_change_time, _last_active_zone

    if not _is_enabled():
        return

    # Update zone tracking
    active = _get_active_zones()
    if len(active) == 1 and active[0] != _last_active_zone:
        _last_active_zone = active[0]
        _last_zone_change_time = time.time()
        _clear_escalation("break_suggest")


# ── Startup ──────────────────────────────────────────────────────────────────

@time_trigger("startup")  # noqa: F821
async def _startup():
    """Initialize focus guard status sensor and workshop tracking."""
    task.sleep(10)  # noqa: F821
    await asyncio.to_thread(reload_entity_config)

    global _last_zone_change_time, _last_active_zone

    _ensure_result_entity_name(force=True)
    _set_result("idle", op="startup")

    # Initialize zone tracking
    active = _get_active_zones()
    if active:
        _last_active_zone = active[0] if len(active) == 1 else ""
        _last_zone_change_time = time.time()

    log.info("focus_guard.py loaded — focus guard idle")  # noqa: F821
