"""Calendar Promotion Engine — Task 18a of Voice Context Architecture.

Promotes Google Calendar events from L3 (API) to L2 (memory) and L1
(input_text helpers) for fast agent access. Fetches a 48-hour window
(today + tomorrow), detects work days from event keywords, and updates
hot-context helpers. Exposes pyscript.calendar_promote_now with a
5-minute promote cache to debounce rapid triggers.
"""
import json
import re
import time
from datetime import datetime, timedelta
from typing import Any

from shared_utils import (
    build_result_entity_name,
    get_person_config,
    get_person_slugs,
    load_entity_config,
    reload_entity_config,
)

# =============================================================================
# Calendar Promotion Engine — Task 18a of Voice Context Architecture
# =============================================================================
# Promotes Google Calendar data from L3 (API) to L2 (memory) for fast agent
# access. Also updates L1 input_text helpers for hot context injection.
#
# Services:
#   pyscript.calendar_promote_now
#     On-demand calendar promotion. Fetches today + tomorrow events from
#     Google Calendar, formats them, writes to L2 memory, updates helpers.
#     Called by automations (midnight sync, state change) and by agents
#     when user asks about schedule.
#
# Key design:
#   - Fetches 48h window (today + tomorrow) in one call per calendar
#   - L2 keys: calendar_today:miquel, calendar_tomorrow:miquel
#   - L1 helpers: input_text.ai_calendar_today_summary, _tomorrow_summary
#   - Stale flag: input_boolean.ai_calendar_stale (set on API failure)
#   - Promote cache: 5 min TTL to debounce rapid state-change triggers
#   - Event dedup: memory_set upserts by key — no L2 duplicates
#   - Test mode: mock data from input_text.ai_test_calendar_event
#
# Dependencies:
#   - pyscript/memory.py (L2: memory_set)
#   - pyscript/notification_dedup.py (dedup_announce for reminders)
#   - packages/ai_calendar_promotion.yaml (helpers)
#   - packages/ai_test_harness.yaml (test mode toggle)
#   - packages/ai_predictive_schedule.yaml (input_text.ai_test_calendar_event)
#   - calendar.miquel_angel_cano_gmail_com (Google Calendar)
#   - calendar.holidays_in_spain (Spanish holidays)
#   - calendar.birthdays (Google Contacts birthdays)
#
# Deployed: 2026-03-02
# =============================================================================

RESULT_ENTITY = "sensor.ai_calendar_promotion_status"


def _helper_int(entity_id, default):
    try:
        val = state.get(entity_id)  # noqa: F821
        if val and val not in ("unknown", "unavailable", ""):
            return int(float(val))
    except Exception:
        pass
    return default


def _helper_str(entity_id, default):
    try:
        val = state.get(entity_id)  # noqa: F821
        if val and val not in ("unknown", "unavailable", ""):
            return str(val)
    except Exception:
        pass
    return default


def _get_calendar_entities() -> tuple[str, str, str]:
    """Read calendar entities: helper first → entity_config fallback → log error if empty."""
    cfg = load_entity_config()
    cals = cfg.get("calendars", {})
    main = cals.get("main", "") if cals else ""
    holidays = cals.get("holidays", "") if cals else ""
    birthdays = cals.get("birthdays", "") if cals else ""
    if not main and not holidays and not birthdays:
        log.error("cal_promote: no calendar entities in entity_config.yaml")  # noqa: F821
    return (
        main or "calendar.miquel_angel_cano_gmail_com",
        holidays or "calendar.holidays_in_spain",
        birthdays or "calendar.birthdays",
    )


# ── Module-Level State ───────────────────────────────────────────────────────

_promote_cache: dict[str, Any] = {}
_calendar_triggers = []        # factory-created trigger references (keep alive)
result_entity_name: dict[str, str] = {}
_consecutive_failures: int = 0


# ── Entity Name Helpers (pattern from notification_dedup.py) ─────────────────

def _ensure_result_entity_name(force: bool = False) -> None:
    global result_entity_name
    if force or not result_entity_name:
        result_entity_name = build_result_entity_name(RESULT_ENTITY)


def _set_result(state_value: str = "ok", **attrs: Any) -> None:
    _ensure_result_entity_name()
    attrs.update(result_entity_name)
    state.set(RESULT_ENTITY, value=state_value, new_attributes=attrs)  # noqa: F821


# ── Test Mode ────────────────────────────────────────────────────────────────

def _check_test_mode() -> bool:
    try:
        return str(state.get("input_boolean.ai_test_mode") or "off").lower() == "on"  # noqa: F821
    except NameError:
        return False


# ── Pure-Python Sync Helpers ─────────────────────────────────────────────────

@pyscript_compile  # noqa: F821
def _format_time_from_iso(iso_str: str) -> str:
    """Extract HH:MM from an ISO datetime string."""
    try:
        dt = datetime.fromisoformat(iso_str)
        return dt.strftime("%H:%M")
    except (ValueError, TypeError):
        return ""


@pyscript_compile  # noqa: F821
def _is_all_day_event(event: dict) -> bool:
    """Check if event is all-day (date-only start, no T separator)."""
    start = event.get("start", "")
    if isinstance(start, str):
        return "T" not in start and len(start) <= 10
    return False


@pyscript_compile  # noqa: F821
def _is_multiday_event(event: dict, ref_date_str: str) -> tuple:
    """Check if event spans multiple days.

    Returns (is_multi, day_num, total_days).
    ref_date_str: "YYYY-MM-DD" — the date we're rendering for.
    """
    start = event.get("start", "")
    end = event.get("end", "")

    if not start or not end:
        return (False, 1, 1)

    try:
        start_date = datetime.strptime(start[:10], "%Y-%m-%d").date()
        end_date = datetime.strptime(end[:10], "%Y-%m-%d").date()
        ref_date = datetime.strptime(ref_date_str, "%Y-%m-%d").date()

        # For all-day events, end date is exclusive
        if _is_all_day_event(event):
            total_days = (end_date - start_date).days
        else:
            total_days = (end_date - start_date).days + 1
            if total_days < 1:
                total_days = 1

        if total_days <= 1:
            return (False, 1, 1)

        day_num = (ref_date - start_date).days + 1
        if day_num < 1:
            day_num = 1
        if day_num > total_days:
            day_num = total_days

        return (True, day_num, total_days)
    except (ValueError, TypeError):
        return (False, 1, 1)


@pyscript_compile  # noqa: F821
def _format_event_compact(event: dict, ref_date_str: str) -> str:
    """Format a single event for L2 storage (compact).

    Formats:
    - Timed: "10:00 Dentist"
    - All-day: "All day: Team offsite"
    - Multi-day: "All day: Conference (Day 2/3)"
    """
    summary = event.get("summary", "Untitled")
    is_multi, day_num, total_days = _is_multiday_event(event, ref_date_str)

    if _is_all_day_event(event):
        if is_multi:
            return f"All day: {summary} (Day {day_num}/{total_days})"
        return f"All day: {summary}"

    start_str = _format_time_from_iso(event.get("start", ""))
    if not start_str:
        return summary

    end_str = _format_time_from_iso(event.get("end", ""))
    if end_str and end_str != start_str:
        time_str = f"{start_str}-{end_str}"
    else:
        time_str = start_str

    if is_multi:
        return f"{time_str} {summary} (Day {day_num}/{total_days})"
    return f"{time_str} {summary}"


@pyscript_compile  # noqa: F821
def _format_events_compact(events: list, ref_date_str: str) -> str:
    """Format a list of events for L2 storage. Pipe-delimited."""
    if not events:
        return "No events"

    formatted = []
    for ev in events:
        formatted.append(_format_event_compact(ev, ref_date_str))

    return " | ".join(formatted)


@pyscript_compile  # noqa: F821
def _format_events_for_helper(events: list, ref_date_str: str) -> str:
    """Format events for input_text helper (L1). Same as compact, truncated."""
    text = _format_events_compact(events, ref_date_str)
    if len(text) > 250:
        text = text[:247] + "..."
    return text


@pyscript_compile  # noqa: F821
def _extract_events_for_date(all_events: list, date_str: str) -> list:
    """Filter events that overlap with a specific date.

    An event overlaps if its start date <= date <= end date (exclusive for
    all-day, inclusive for timed).
    """
    if not all_events:
        return []

    try:
        ref_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return []

    matching = []
    for ev in all_events:
        start = ev.get("start", "")
        end = ev.get("end", "")

        if not start:
            continue

        try:
            start_date = datetime.strptime(start[:10], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            continue

        try:
            end_date = datetime.strptime(end[:10], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            end_date = start_date + timedelta(days=1)

        is_all_day = _is_all_day_event(ev)

        if is_all_day:
            # All-day: end is exclusive
            if start_date <= ref_date < end_date:
                matching.append(ev)
        else:
            # Timed: end is inclusive (event active on both start and end day)
            if start_date <= ref_date <= end_date:
                matching.append(ev)

    return matching


@pyscript_compile  # noqa: F821
def _filter_ended_events(events: list, now_iso: str) -> list:
    """Remove timed events whose end time has already passed.

    Prevents cross-midnight events (e.g., 23:56–00:16) from appearing in the
    morning briefing. All-day events are always kept.
    """
    if not events or not now_iso:
        return events

    try:
        now_dt = datetime.fromisoformat(now_iso)
    except (ValueError, TypeError):
        return events

    kept = []
    for ev in events:
        if _is_all_day_event(ev):
            kept.append(ev)
            continue
        end = ev.get("end", "")
        if not end or "T" not in end:
            kept.append(ev)
            continue
        try:
            end_dt = datetime.fromisoformat(end)
            if end_dt >= now_dt:
                kept.append(ev)
        except (ValueError, TypeError):
            kept.append(ev)
    return kept


@pyscript_compile  # noqa: F821
def _sort_events(events: list) -> list:
    """Sort events: timed first (by start time), then all-day."""
    timed = []
    all_day = []

    for ev in events:
        if _is_all_day_event(ev):
            all_day.append(ev)
        else:
            timed.append(ev)

    timed.sort(key=lambda e: e.get("start", ""))
    all_day.sort(key=lambda e: e.get("summary", "").lower())

    return timed + all_day


@pyscript_compile  # noqa: F821
def _parse_mock_events(mock_str: str) -> list:
    """Parse mock calendar event string into event-like dicts.

    Supported formats:
    - Pipe-delimited: "10:00 Dentist | 14:00 Meeting | All day: Holiday"
    - Single: "Team standup at 09:00"
    - JSON list: [{"summary": "...", "start": "...", "end": "..."}]
    """
    if not mock_str or not mock_str.strip():
        return []

    mock_str = mock_str.strip()

    # Try JSON first
    if mock_str.startswith("["):
        try:
            return json.loads(mock_str)
        except (json.JSONDecodeError, TypeError):
            pass

    # Pipe-delimited or single
    if "|" in mock_str:
        parts = [p.strip() for p in mock_str.split("|") if p.strip()]
    else:
        parts = [mock_str.strip()]

    events = []
    today_str = datetime.now().strftime("%Y-%m-%d")
    tomorrow_str = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

    for part in parts:
        # "All day: Holiday"
        if part.lower().startswith("all day:"):
            summary = part[8:].strip()
            events.append({
                "summary": summary,
                "start": today_str,
                "end": (datetime.strptime(today_str, "%Y-%m-%d")
                        + timedelta(days=2)).strftime("%Y-%m-%d"),
            })
            continue

        # "10:00 Dentist" (HH:MM prefix)
        time_match = re.match(r"^(\d{1,2}:\d{2})\s+(.+)$", part)
        if time_match:
            t, summary = time_match.group(1), time_match.group(2)
            # Create for both today and tomorrow (test both paths)
            events.append({
                "summary": summary,
                "start": f"{today_str}T{t}:00",
                "end": f"{today_str}T{t}:00",
            })
            events.append({
                "summary": summary,
                "start": f"{tomorrow_str}T{t}:00",
                "end": f"{tomorrow_str}T{t}:00",
            })
            continue

        # "Dentist at 10:00"
        at_match = re.match(r"^(.+?)\s+at\s+(\d{1,2}:\d{2})$", part,
                            re.IGNORECASE)
        if at_match:
            summary, t = at_match.group(1), at_match.group(2)
            events.append({
                "summary": summary,
                "start": f"{today_str}T{t}:00",
                "end": f"{today_str}T{t}:00",
            })
            events.append({
                "summary": summary,
                "start": f"{tomorrow_str}T{t}:00",
                "end": f"{tomorrow_str}T{t}:00",
            })
            continue

        # Fallback: all-day event with just a title
        events.append({
            "summary": part,
            "start": today_str,
            "end": (datetime.strptime(today_str, "%Y-%m-%d")
                    + timedelta(days=2)).strftime("%Y-%m-%d"),
        })

    return events


# ── L2 Memory Helper ────────────────────────────────────────────────────────

async def _l2_set(
    key: str, value: str, tags: str,
    scope: str = "user", expiration_days: int = 1,
) -> bool:
    """Write entry to L2 via memory_set. Returns True on success."""
    try:
        result = pyscript.memory_set(  # noqa: F821
            key=key, value=value, scope=scope,
            expiration_days=expiration_days,
            tags=tags, force_new=True,
        )
        resp = await result
        return resp is not None and resp.get("status") == "ok"
    except Exception as exc:
        log.warning(f"cal_promote: L2 set failed key={key}: {exc}")  # noqa: F821
        return False


# ── Calendar Fetch ───────────────────────────────────────────────────────────

async def _fetch_calendar_events(
    entity_id: str, start_str: str, end_str: str,
) -> list | None:
    """Fetch events from a HA calendar entity.

    Returns list of event dicts on success, None on API failure.
    None vs [] distinction: None = API error (set stale flag),
    [] = API success but no events.
    """
    try:
        result = calendar.get_events(  # noqa: F821
            entity_id=entity_id,
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

        return events
    except Exception as exc:
        log.warning(  # noqa: F821
            f"cal_promote: fetch failed {entity_id}: {exc}"
        )
        return None


# ── HA Helper Updates ────────────────────────────────────────────────────────

def _update_helper(entity_id: str, value: str) -> None:
    """Update an input_text helper, truncating to 255 chars."""
    try:
        service.call(  # noqa: F821
            "input_text", "set_value",
            entity_id=entity_id, value=str(value)[:255],
        )
    except Exception as exc:
        log.warning(  # noqa: F821
            f"cal_promote: helper update failed {entity_id}: {exc}"
        )


def _set_stale_flag(stale: bool) -> None:
    """Set or clear the calendar stale flag."""
    try:
        svc = "turn_on" if stale else "turn_off"
        service.call(  # noqa: F821
            "input_boolean", svc,
            entity_id="input_boolean.ai_calendar_stale",
        )
    except Exception as exc:
        log.warning(f"cal_promote: stale flag failed: {exc}")  # noqa: F821


def _update_last_sync() -> None:
    """Update last sync timestamp."""
    try:
        now_iso = datetime.now().isoformat(timespec="seconds")
        service.call(  # noqa: F821
            "input_text", "set_value",
            entity_id="input_text.ai_calendar_last_sync",
            value=now_iso,
        )
    except Exception as exc:
        log.warning(f"cal_promote: last sync failed: {exc}")  # noqa: F821


# ── I-27: Workday Detection ──────────────────────────────────────────────────

def _detect_work_day(events: list, keywords: list) -> bool:
    """Check if any event summary contains a work-related keyword (case-insensitive)."""
    for event in events:
        summary = (event.get("summary") or "").lower()
        for kw in keywords:
            if kw in summary:
                return True
    return False


# ── Core Promotion Logic ─────────────────────────────────────────────────────

async def _promote_internal(test_mode: bool, force: bool) -> dict:
    """Core promotion logic.

    Fetches 48h window, splits into today/tomorrow, formats, writes L2 + L1.
    Returns result dict.
    """
    global _promote_cache

    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    tomorrow = now.date() + timedelta(days=1)
    tomorrow_str = tomorrow.strftime("%Y-%m-%d")

    # ── Cache check (debounce rapid triggers) ──
    cache_ttl = _helper_int("input_number.ai_calendar_promote_ttl", 300)
    if (not force
            and not test_mode
            and _promote_cache.get("date") == today_str
            and (time.time() - _promote_cache.get("fetched_at", 0))
                < cache_ttl):
        return {
            "status": "ok", "op": "promote",
            "skipped": True, "reason": "cache_valid",
        }

    # ── Kill switch ──
    try:
        enabled = str(
            state.get("input_boolean.ai_calendar_promotion_enabled")  # noqa: F821
            or "on"
        ).lower()
    except NameError:
        enabled = "on"

    if enabled == "off" and not force:
        return {
            "status": "ok", "op": "promote",
            "skipped": True, "reason": "disabled",
        }

    # ── Fetch events ──
    all_main_events = None
    all_holiday_events = None
    all_birthday_events = None
    api_failed = False

    if test_mode:
        try:
            mock = str(
                state.get("input_text.ai_test_calendar_event") or ""  # noqa: F821
            )
        except NameError:
            mock = ""

        if mock:
            all_main_events = _parse_mock_events(mock)
            log.info(  # noqa: F821
                f"cal_promote [TEST]: parsed {len(all_main_events)} mock events"
            )
        else:
            all_main_events = []
            log.info("cal_promote [TEST]: no mock events configured")  # noqa: F821

        all_holiday_events = []
        all_birthday_events = []
    else:
        # Real calendar queries — 48h window
        start_dt = f"{today_str}T00:00:00"
        end_dt = f"{tomorrow_str}T23:59:59"

        cal_main, cal_holidays, cal_birthdays = _get_calendar_entities()

        all_main_events = await _fetch_calendar_events(
            cal_main, start_dt, end_dt,
        )
        all_holiday_events = await _fetch_calendar_events(
            cal_holidays, start_dt, end_dt,
        )
        all_birthday_events = await _fetch_calendar_events(
            cal_birthdays, start_dt, end_dt,
        )

        if all_main_events is None:
            api_failed = True
            all_main_events = []
        if all_holiday_events is None:
            all_holiday_events = []
        if all_birthday_events is None:
            all_birthday_events = []

    # ── Handle API failure ──
    if api_failed and not test_mode:
        global _consecutive_failures
        _consecutive_failures += 1
        _set_stale_flag(True)
        log.warning(  # noqa: F821
            "cal_promote: main calendar API failed — stale flag set, "
            f"preserving existing L2 data (failures={_consecutive_failures})"
        )
        # ── T24-3b: Persistent notification after repeated failures ──
        failure_threshold = _helper_int("input_number.ai_calendar_failure_threshold", 3)
        if _consecutive_failures >= failure_threshold:
            try:
                service.call(  # noqa: F821
                    "persistent_notification", "create",
                    title="Calendar Integration: Repeated Failures",
                    message=(
                        f"Google Calendar API has failed {_consecutive_failures} "
                        f"consecutive times. Check Google auth and calendar "
                        f"integration in Settings → Integrations."
                    ),
                    notification_id="ai_calendar_api_failure",
                )
            except Exception:
                pass
        return {
            "status": "ok", "op": "promote",
            "api_failed": True, "stale": True,
            "consecutive_failures": _consecutive_failures,
        }

    # ── T24-3b: Reset failure counter on success ──
    global _consecutive_failures
    if _consecutive_failures > 0:
        _consecutive_failures = 0
        try:
            service.call(  # noqa: F821
                "persistent_notification", "dismiss",
                notification_id="ai_calendar_api_failure",
            )
        except Exception:
            pass

    # ── Merge all event sources ──
    all_events = list(all_main_events)

    for ev in all_holiday_events:
        all_events.append(ev)

    for ev in all_birthday_events:
        all_events.append(ev)

    # ── Split by day ──
    today_events = _sort_events(
        _extract_events_for_date(all_events, today_str)
    )
    tomorrow_events = _sort_events(
        _extract_events_for_date(all_events, tomorrow_str)
    )

    # ── Filter out ended timed events for today (I-26: cross-midnight fix) ──
    # A 23:56–00:16 event should not appear at 08:00.
    now_iso = now.isoformat()
    today_events = _filter_ended_events(today_events, now_iso)

    # ── Format ──
    today_compact = _format_events_compact(today_events, today_str)
    tomorrow_compact = _format_events_compact(tomorrow_events, tomorrow_str)
    today_helper = _format_events_for_helper(today_events, today_str)
    tomorrow_helper = _format_events_for_helper(tomorrow_events, tomorrow_str)

    l2_today_ok = False
    l2_tomorrow_ok = False

    if test_mode:
        log.info(  # noqa: F821
            f"cal_promote [TEST]: today ({len(today_events)} events): "
            f"{today_compact}"
        )
        log.info(  # noqa: F821
            f"cal_promote [TEST]: tomorrow ({len(tomorrow_events)} events): "
            f"{tomorrow_compact}"
        )
        slugs = get_person_slugs()
        log.info(  # noqa: F821
            "cal_promote [TEST]: WOULD write L2 keys for persons: %s",
            slugs,
        )
        l2_today_ok = True
        l2_tomorrow_ok = True
    else:
        # ── Write to L2 per-person (Task 22) ──
        # For now, all persons share the same household calendar data.
        # Per-person calendar filtering uses get_person_config(slug, "calendar").
        for slug in get_person_slugs():
            person_cal = get_person_config(slug, "calendar", "")
            # Skip persons with no calendar configured (they share household data)
            cal_tag = f"calendar {slug} schedule"
            await _l2_set(
                key=f"calendar_today:{slug}",
                value=today_compact,
                tags=f"{cal_tag} today",
                scope="user",
                expiration_days=1,
            )
            await _l2_set(
                key=f"calendar_tomorrow:{slug}",
                value=tomorrow_compact,
                tags=f"{cal_tag} tomorrow",
                scope="user",
                expiration_days=2,
            )
        l2_today_ok = True
        l2_tomorrow_ok = True

        # ── Update L1 helpers (shared household summary) ──
        _update_helper(
            "input_text.ai_calendar_today_summary", today_helper,
        )
        _update_helper(
            "input_text.ai_calendar_tomorrow_summary", tomorrow_helper,
        )

        # ── Per-person L1 helpers (Gap 1: identity-aware hot context) ──
        for slug in get_person_slugs():
            _update_helper(
                f"input_text.ai_calendar_today_summary_{slug}", today_helper,
            )
            _update_helper(
                f"input_text.ai_calendar_tomorrow_summary_{slug}", tomorrow_helper,
            )

        _update_last_sync()
        _set_stale_flag(False)

        # ── I-27: Auto-detect work day from calendar keywords ──
        try:
            override_on = state.get(  # noqa: F821
                "input_boolean.ai_work_day_manual_override"
            )
            if override_on != "on":
                keywords_csv = state.get(  # noqa: F821
                    "input_text.ai_work_calendar_keywords"
                ) or "standup,sprint,meeting,client,1:1,work,office,scrum,daily"
                keywords = [
                    k.strip().lower() for k in keywords_csv.split(",")
                    if k.strip()
                ]
                is_work = _detect_work_day(today_events, keywords)
                target_val = "on" if is_work else "off"
                # Update shared household helper
                current = state.get(  # noqa: F821
                    "input_boolean.ai_context_work_day"
                )
                if current != target_val:
                    service.call(  # noqa: F821
                        "input_boolean",
                        "turn_on" if is_work else "turn_off",
                        entity_id="input_boolean.ai_context_work_day",
                    )
                    log.info(  # noqa: F821
                        f"cal_promote: auto-set work_day={is_work} "
                        f"(matched keywords in today events)"
                    )
                # Update per-person work day helpers (Task 22)
                for slug in get_person_slugs():
                    eid = f"input_boolean.ai_context_work_day_{slug}"
                    try:
                        if state.get(eid) != target_val:  # noqa: F821
                            service.call(  # noqa: F821
                                "input_boolean",
                                "turn_on" if is_work else "turn_off",
                                entity_id=eid,
                            )
                    except Exception:
                        pass  # helper may not exist for all persons
        except Exception as exc:
            log.warning(f"cal_promote: work day detection failed: {exc}")  # noqa: F821

        # ── I-29: Auto-detect work day for TOMORROW ──
        try:
            if override_on != "on":
                is_work_tomorrow = _detect_work_day(tomorrow_events, keywords)
                target_tmrw = "on" if is_work_tomorrow else "off"
                current_tmrw = state.get(  # noqa: F821
                    "input_boolean.ai_context_work_day_tomorrow"
                )
                if current_tmrw != target_tmrw:
                    service.call(  # noqa: F821
                        "input_boolean",
                        "turn_on" if is_work_tomorrow else "turn_off",
                        entity_id="input_boolean.ai_context_work_day_tomorrow",
                    )
                    log.info(  # noqa: F821
                        f"cal_promote: auto-set work_day_tomorrow="
                        f"{is_work_tomorrow}"
                    )
        except Exception as exc:
            log.warning(  # noqa: F821
                f"cal_promote: tomorrow work day detection failed: {exc}"
            )

    # ── Update cache ──
    _promote_cache = {
        "date": today_str,
        "fetched_at": time.time(),
    }

    return {
        "status": "ok",
        "op": "promote",
        "today_events": len(today_events),
        "tomorrow_events": len(tomorrow_events),
        "today_summary": today_compact,
        "tomorrow_summary": tomorrow_compact,
        "l2_today": l2_today_ok,
        "l2_tomorrow": l2_tomorrow_ok,
        "api_failed": False,
        "stale": False,
        "test_mode": test_mode,
    }


# ── Services ─────────────────────────────────────────────────────────────────

@service(supports_response="only")  # noqa: F821
async def calendar_promote_now(force: bool = False):
    """
    yaml
    name: Calendar Promote Now
    description: >-
      Promote Google Calendar events to L2 memory. Fetches today + tomorrow
      events from Google Calendar (plus holidays and birthdays), formats them
      for agent consumption, writes to L2 memory and updates L1 input_text
      helpers. Called automatically at midnight and on calendar state changes.
      Use force=true for on-demand refresh bypassing cache.
    fields:
      force:
        name: Force
        description: Bypass cache and kill switch — force a fresh promotion.
        default: false
        selector:
          boolean:
    """
    t_start = time.monotonic()
    test_mode = _check_test_mode()

    result = await _promote_internal(test_mode, bool(force))

    elapsed = round((time.monotonic() - t_start) * 1000, 1)
    result["elapsed_ms"] = elapsed

    sensor_state = "test" if test_mode else result.get("status", "ok")
    _set_result(sensor_state, **result)

    if result.get("skipped"):
        log.info(  # noqa: F821
            f"cal_promote: skipped ({result.get('reason', '')}) {elapsed}ms"
        )
    else:
        log.info(  # noqa: F821
            f"cal_promote: promoted today={result.get('today_events', 0)} "
            f"tomorrow={result.get('tomorrow_events', 0)} "
            f"stale={result.get('stale', False)} "
            f"{elapsed}ms{' [TEST]' if test_mode else ''}"
        )

    return result


# ── Startup ──────────────────────────────────────────────────────────────────

@time_trigger("startup")  # noqa: F821
async def calendar_promote_startup():
    """Initialize status sensor and run initial promotion."""
    # Wait for SMB mount + force re-read of entity_config.yaml
    task.sleep(10)  # noqa: F821
    reload_entity_config()

    _ensure_result_entity_name(force=True)
    _set_result("idle", op="startup")

    # Register calendar triggers dynamically from config
    global _calendar_triggers
    main_cal = _get_calendar_entities()[0]
    _calendar_triggers = [_calendar_trigger_factory(main_cal)]
    log.info(f"calendar_promote: registered {len(_calendar_triggers)} calendar triggers")  # noqa: F821

    log.info("calendar_promote.py loaded — running initial promotion")  # noqa: F821

    # Initial promotion — calendar entities should be loaded by now
    await calendar_promote_now(force=True)


# ── Midnight Sync ────────────────────────────────────────────────────────────

@time_trigger("cron(5 0 * * *)")  # noqa: F821
async def calendar_promote_midnight():
    """Midnight sync — clear cache and refresh today + tomorrow data."""
    global _promote_cache
    _promote_cache = {}  # Clear cache for new day
    log.info("cal_promote: midnight sync triggered")  # noqa: F821
    await calendar_promote_now(force=True)


# ── Calendar State Change ────────────────────────────────────────────────────

def _calendar_trigger_factory(entity_id):
    """Create @state_trigger for a calendar entity (state + .message attribute)."""
    @state_trigger(entity_id, f"{entity_id}.message")  # noqa: F821
    async def _trig(**kwargs):
        await _on_calendar_state_changed(**kwargs)
    return _trig


async def _on_calendar_state_changed(**kwargs):
    """Re-promote when calendar entity state or next-event changes.

    Cache debounces rapid-fire triggers (5 min TTL).
    """
    log.info("cal_promote: calendar state change detected")  # noqa: F821
    await calendar_promote_now(force=False)
