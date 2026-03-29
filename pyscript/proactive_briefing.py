"""Task 19: Universal Proactive Briefing Assembly and Delivery.

Aggregates content from all architecture layers -- weather, calendar,
email, schedule, household state, memory highlights, and projects --
into a personalized briefing. Supports full mode (LLM reformulation +
ElevenLabs TTS) and stripped mode (raw text + fallback TTS) based on
remaining budget. Driven by the unified proactive_briefing.yaml blueprint.
"""
import time
from datetime import UTC, datetime
from typing import Any

from shared_utils import build_result_entity_name, resolve_active_user

# =============================================================================
# Proactive Briefing — Task 19 of Voice Context Architecture
# =============================================================================
# Universal briefing module: assembles and delivers a personalized briefing
# using data from ALL architecture layers. Driven by the unified
# proactive_briefing.yaml blueprint (label-based, no slots).
#
# Services:
#   pyscript.proactive_build_briefing
#     Assemble briefing content from all available layers. Each section
#     fails independently — partial briefings are fine. Returns assembled
#     text + per-section breakdown. No TTS, no LLM. For inspection/testing.
#
#   pyscript.proactive_briefing_now
#     Full delivery pipeline: build → agent dispatch → LLM reformulation
#     → TTS playback → dedup register → whisper. On-demand — skips all
#     trigger conditions. For "give me my briefing" and automation calls.
#
# Briefing sections (each independently optional):
#   1. Greeting     — time-aware greeting (pure Python)
#   2. Weather      — from weather.forecast_home entity
#   3. Calendar     — from L2 (calendar_today:{person}) / L1 helper
#   4. Email        — from input_number.ai_email_priority_count
#   5. Schedule     — first upcoming event advisory
#   6. Household    — unusual smart home states (user-configured entities)
#   7. Memory       — mood highlights from whisper network (L2, last 24h)
#
# Budget awareness:
#   budget >= 20%  → full mode (agent dispatch + LLM reformulation + ElevenLabs)
#   budget < 20%   → stripped mode (raw text + fallback TTS, no LLM call)
#
# Test mode (ai_test_mode ON):
#   Build all sections + dispatch agent + log everything.
#   No conversation.process, no TTS, no delivered flag, no dedup.
#   Returns full content in service response.
#
# Dependencies:
#   - pyscript/tts_queue.py (tts_queue_speak)
#   - pyscript/agent_dispatcher.py (agent_dispatch)
#   - pyscript/agent_whisper.py (agent_whisper)
#   - pyscript/notification_dedup.py (dedup_check, dedup_register)
#   - pyscript/memory.py (memory_search)
#   - pyscript/calendar_promote.py (L2 calendar data)
#   - pyscript/email_promote.py (email priority count)
#   - packages/ai_proactive_briefing.yaml (kill switch + last summary)
#   - packages/ai_context_hot.yaml (weather, presence, wake times)
#   - packages/ai_identity.yaml (identity confidence)
#   - packages/ai_llm_budget.yaml (budget sensor)
#   - packages/ai_test_harness.yaml (test mode)
#
# Deployed: 2026-03-02 | Unified: 2026-03-07
# =============================================================================

RESULT_ENTITY = "sensor.ai_proactive_briefing_status"
_FALLBACK_TTS_VOICE_DEFAULT = "tts.home_assistant_cloud"


# ── Configurable Helper Getters ──────────────────────────────────────────────

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


def _get_fallback_tts_voice():
    return _helper_str("input_text.ai_default_tts_voice", _FALLBACK_TTS_VOICE_DEFAULT)


def _get_morning_hour():
    return _helper_int("input_number.ai_briefing_morning_hour", 5)


def _get_afternoon_hour():
    return _helper_int("input_number.ai_briefing_afternoon_hour", 12)


def _get_evening_hour():
    return _helper_int("input_number.ai_briefing_evening_hour", 17)

# BUDGET_STRIPPED_THRESHOLD — now read from input_number.ai_budget_personality_threshold

WEATHER_MAP = {
    "clear-night": "clear",
    "cloudy": "cloudy",
    "fog": "foggy",
    "hail": "hail",
    "lightning": "thunderstorm",
    "lightning-rainy": "thunderstorm with rain",
    "partlycloudy": "partly cloudy",
    "pouring": "pouring rain",
    "rainy": "rainy",
    "snowy": "snowy",
    "snowy-rainy": "snow and rain",
    "sunny": "sunny",
    "windy": "windy",
    "windy-variant": "windy",
}

ALL_SECTIONS = (
    "greeting", "weather", "calendar", "email",
    "schedule", "household", "memory", "projects",
    "media_today", "media_tomorrow", "media_weekly", "media",
)

# Gentle mood phrasing (creep factor gate: never say "I tracked your emotions")
MOOD_GENTLE_MAP = {
    "frustrated": "you seemed a bit frustrated",
    "stressed": "you seemed stressed",
    "tired": "you seemed tired",
}

def _briefing_framing_for_hour(hour: int) -> str:
    """Return time-appropriate framing instructions for the LLM."""
    afternoon_hour = _get_afternoon_hour()
    evening_hour = _get_evening_hour()
    if hour < afternoon_hour:
        return (
            "This is a morning briefing. Set the tone for the day ahead."
        )
    elif hour < evening_hour:
        return (
            "This is an afternoon update. Frame it as a mid-day check-in."
        )
    else:
        return (
            "This is an evening briefing. Frame it as a day-in-review and "
            "wind-down. Don't present tomorrow's schedule as something "
            "imminent — focus on wrapping up today."
        )


def _verbosity_word_range() -> str:
    """Read user verbosity preference, return word count range for prompt."""
    user = resolve_active_user()
    raw = state.get(f"input_text.ai_context_user_verbosity_{user}")
    if raw is None or str(raw) in ("unknown", "unavailable", "", "None"):
        return "200-400 words"
    v = str(raw).strip().lower()
    if v in ("brief", "short", "concise", "minimal"):
        return "80-150 words"
    if v in ("detailed", "thorough", "verbose", "long"):
        return "400-600 words"
    return "200-400 words"  # "normal" or unrecognized → default


def _briefing_prompt_for_hour(hour: int) -> str:
    """Return a time-appropriate default LLM prompt for the briefing."""
    framing = _briefing_framing_for_hour(hour)
    _wrange = _verbosity_word_range()
    return (
        "Deliver this briefing naturally in your personality. "
        "Keep it conversational — not a bullet-point list. Be warm but concise "
        f"(aim for {_wrange} of concise speech). {framing}"
        "\n\nHere is the information:\n\n{content}"
    )

# ── Module-Level State ───────────────────────────────────────────────────────

result_entity_name: dict[str, str] = {}


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
def _section_greeting(
    hour: int,
    morning_hour: int = 5,
    afternoon_hour: int = 12,
    evening_hour: int = 17,
) -> str:
    """Time-aware greeting. Raw text — the LLM will add personality."""
    if hour < morning_hour:
        return "You're up early."
    if hour < afternoon_hour:
        return "Good morning."
    if hour < evening_hour:
        return "Afternoon already."
    return "Good evening."


@pyscript_compile  # noqa: F821
def _format_weather_text(condition: str, temp: str, humidity: str) -> str:
    """Format weather into a natural sentence."""
    desc = WEATHER_MAP.get(
        condition,
        condition.replace("-", " ") if condition else "unknown",
    )
    return f"It's {temp} degrees and {desc} outside."


@pyscript_compile  # noqa: F821
def _extract_speech_from_response(resp: dict) -> str:
    """Extract speech text from conversation.process response dict."""
    if not resp or not isinstance(resp, dict):
        return ""
    response = resp.get("response")
    if not isinstance(response, dict):
        return ""
    speech = response.get("speech")
    if not isinstance(speech, dict):
        return ""
    plain = speech.get("plain")
    if not isinstance(plain, dict):
        return ""
    return plain.get("speech", "")


@pyscript_compile  # noqa: F821
def _parse_first_timed_event(
    cal_raw: str, now_hour: int, now_minute: int,
) -> tuple:
    """Parse first upcoming timed event from compact calendar string.

    Calendar format: "10:00 Dentist | 14:00 Meeting | All day: Holiday"
    Returns: (time_str, description) or (None, None).
    """
    if not cal_raw:
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
                if h * 60 + m > now_mins:
                    return (time_str, desc)
            except (ValueError, TypeError):
                continue

    return (None, None)


@pyscript_compile  # noqa: F821
def _build_mood_phrase(mood: str, context: str) -> str:
    """Build a gentle, non-creepy mood reference for the briefing.

    Input context format: "rick observed: user seems frustrated — context: why network broken"
    Output: "By the way, you seemed a bit frustrated about the network. Hope things are better."
    """
    gentle = MOOD_GENTLE_MAP.get(mood, "")
    if not gentle:
        return ""

    ctx = context.strip()
    if " — context: " in ctx:
        ctx = ctx.split(" — context: ", 1)[1]
    if ctx and ctx != "(no query)":
        return f"By the way, {gentle} when talking about {ctx}. Hope things are better today."
    return f"By the way, {gentle} yesterday. Hope today's better."


# ── Async Section Builders ───────────────────────────────────────────────────

async def _section_weather() -> str:
    """Build weather section from weather.forecast_home."""
    try:
        w_state = state.get("weather.forecast_home")  # noqa: F821
        if not w_state or w_state in ("unavailable", "unknown"):
            return ""
        w_attrs = state.getattr("weather.forecast_home")  # noqa: F821
        temp = str(w_attrs.get("temperature", "?"))
        humidity = str(w_attrs.get("humidity", "?"))
        return _format_weather_text(w_state, temp, humidity)
    except Exception as exc:
        log.warning(f"dispatcher: {exc}")  # noqa: F821
        return ""


async def _section_calendar(hour: int = 0) -> str:
    """Build calendar section from L1 helper (populated by Task 18a)."""
    try:
        cal_raw = state.get(  # noqa: F821
            "sensor.ai_calendar_today_summary",
        ) or ""
    except (NameError, Exception):
        return ""

    if not cal_raw or cal_raw in (
        "No events", "unknown", "unavailable", "none",
    ):
        return ""

    events = [e.strip() for e in cal_raw.split("|") if e.strip()]
    count = len(events)

    if count == 0:
        return ""

    # Evening: past-tense summary — don't list events as upcoming
    if hour >= _get_evening_hour():
        if count == 1:
            return f"You had 1 event today: {events[0]}."
        return f"You had {count} events today."

    now = datetime.now()
    first_time, first_desc = _parse_first_timed_event(
        cal_raw, now.hour, now.minute,
    )

    if first_time and first_desc:
        if count == 1:
            return f"You have 1 event today. {first_desc} at {first_time}."
        return (
            f"You have {count} events today. "
            f"First up: {first_desc} at {first_time}."
        )

    if count == 1:
        return f"You have 1 event today: {events[0]}."
    return f"You have {count} events today."


async def _section_email(hour: int = 0) -> str:
    """Build email section from priority count helper (Task 18b)."""
    try:
        count = int(float(
            state.get("sensor.ai_email_priority_count") or 0  # noqa: F821
        ))
    except (TypeError, ValueError, NameError):
        return ""

    if count <= 0:
        return ""

    plural = "s" if count > 1 else ""
    if hour >= _get_evening_hour():
        return f"{count} unread priority email{plural}."
    return f"{count} priority email{plural} overnight."


async def _section_schedule() -> str:
    """Build schedule advisory from today's calendar data.

    Checks next timed event and suggests prep timing if imminent.
    """
    try:
        cal_raw = state.get(  # noqa: F821
            "sensor.ai_calendar_today_summary",
        ) or ""
    except (NameError, Exception):
        return ""

    if not cal_raw or cal_raw in (
        "No events", "unknown", "unavailable", "none",
    ):
        return ""

    now = datetime.now()
    first_time, first_desc = _parse_first_timed_event(
        cal_raw, now.hour, now.minute,
    )

    if not first_time or not first_desc:
        return ""

    # Compute minutes until event
    try:
        h = int(first_time[:2])
        m = int(first_time[3:5])
        diff = (h * 60 + m) - (now.hour * 60 + now.minute)

        if diff <= 0:
            return ""
        if diff <= 60:
            return (
                f"Your {first_desc} is in about {diff} minutes. "
                "Time to start getting ready."
            )
        if diff <= 120:
            hrs = diff // 60
            mins = diff % 60
            if mins > 0:
                return (
                    f"Your {first_desc} is in about "
                    f"{hrs} hour and {mins} minutes."
                )
            return f"Your {first_desc} is in about {hrs} hour."
    except (ValueError, TypeError):
        pass

    return ""


async def _section_household(entities_override: str = "") -> str:
    """Check for unusual smart home states.

    Reads entity IDs from the blueprint's household_entities input
    (comma-separated). Reports any entity NOT in off/idle/unavailable state.
    """
    raw = (
        entities_override
        if entities_override
           and entities_override not in ("unknown", "unavailable")
        else ""
    )

    if not raw or raw in ("unknown", "unavailable"):
        return ""

    entities = [e.strip() for e in raw.split(",") if e.strip()]
    findings = []

    for entity_id in entities:
        try:
            s = state.get(entity_id)  # noqa: F821
            if s and s not in (
                "off", "idle", "unavailable", "unknown", "none", "",
            ):
                attrs = state.getattr(entity_id) or {}  # noqa: F821
                name = attrs.get(
                    "friendly_name",
                    entity_id.split(".")[-1].replace("_", " "),
                )
                findings.append(f"The {name} is {s}")
        except Exception as exc:
            log.warning(f"dispatcher: {exc}")  # noqa: F821
            continue

    if findings:
        return ". ".join(findings) + "."
    return ""


async def _section_memory() -> str:
    """Build memory highlights from whisper network mood observations (L2).

    Searches for mood entries from last 24h. Only reports negative moods
    (frustrated/stressed/tired) to provide supportive context. Happy moods
    are skipped — no need to announce "you were happy yesterday."
    Creep factor gate: phrasing is gentle and observation-based.
    """
    try:
        result = pyscript.memory_search(  # noqa: F821
            query="whisper mood",
            limit=5,
        )
        resp = await result
        if not resp or resp.get("status") != "ok":
            return ""

        results = resp.get("results", [])
        if not results:
            return ""

        now_utc = datetime.now(UTC)

        for entry in results:
            key = entry.get("key", "")
            # Normalized key starts with whisper_mood (colons stripped)
            if not key.startswith("whisper_mood"):
                continue

            value = entry.get("value", "")
            created_at = entry.get("created_at", "")

            # Freshness check: within 24h
            if created_at:
                try:
                    created = datetime.fromisoformat(created_at)
                    if created.tzinfo is None:
                        created = created.replace(tzinfo=UTC)
                    if (now_utc - created).total_seconds() > 86400:
                        continue
                except (ValueError, TypeError):
                    continue

            # Extract mood keyword from value
            mood = ""
            for m in ("frustrated", "stressed", "tired"):
                if m in value:
                    mood = m
                    break

            if mood:
                return _build_mood_phrase(mood, value)

    except Exception as exc:
        log.warning(f"dispatcher: {exc}")  # noqa: F821

    return ""


# ── 8. Projects ──────────────────────────────────────────────────────────────

async def _section_projects() -> str:
    """Build projects section from L1 helpers (populated by project_promote).

    Reads the same helpers that hot context uses — always fresh, survives
    restarts, and doesn't depend on L2 entry TTL.
    """
    _SKIP = {"", "unknown", "unavailable", "none", None}

    try:
        summary = state.get("sensor.ai_active_projects_summary")  # noqa: F821
        hot_line = state.get("sensor.ai_project_hot_context_line")  # noqa: F821
    except Exception as exc:
        log.warning(f"dispatcher: {exc}")  # noqa: F821
        return ""

    if summary in _SKIP and hot_line in _SKIP:
        return ""

    # summary format: "2 active. High: Voice Context Architecture — ..."
    # hot_line format: "Name1 (active — next action), Name2 (active)"
    # Use summary as the lead, hot_line for detail
    parts = []
    if summary not in _SKIP:
        parts.append(str(summary).rstrip(".") + ".")
    if hot_line not in _SKIP:
        parts.append("Projects: " + str(hot_line) + ".")

    return " ".join(parts)


# ── 9. Media (Radarr/Sonarr) ────────────────────────────────────────────────

async def _section_media(upcoming_days: int = 0, download_window: str = "since_midnight") -> str:
    """Build media section from Radarr/Sonarr promotion data.

    If upcoming_days > 0, calls media_promote_now directly with that window
    (allows briefing to request a different window than the tracking blueprint).
    If 0, reads from L1 helpers (whatever window the tracking blueprint configured).

    download_window controls how far back to look for recent downloads:
      - "since_midnight" (default): only today's downloads
      - "rolling_24h": original 24-hour rolling window
    """
    # Compute download_hours based on window mode
    if download_window == "rolling_24h":
        download_hours = 24
    else:  # since_midnight (default)
        _now = datetime.now()
        download_hours = max(int(_now.hour + _now.minute / 60) + 1, 1)

    if upcoming_days > 0:
        try:
            resp = pyscript.media_promote_now(  # noqa: F821
                upcoming_days=upcoming_days, download_hours=download_hours,
                write_l1=False, force=False,
            )
            result = await resp
            if not result or result.get("status") == "error":
                return ""
            # Cache-hit returns no data keys — fall through to L1 helpers
            if not result.get("skipped"):
                parts = []
                for key in ("sonarr_line", "radarr_line"):
                    val = result.get(key, "")
                    if val:
                        parts.append(val)
                rs = result.get("recent_summary", "")
                if rs:
                    parts.append(f"Recently downloaded: {rs}")
                if parts:
                    return " ".join(parts)
        except Exception as exc:
            log.warning(f"dispatcher: {exc}")  # noqa: F821
    # Fallback: read from consolidated media sensor attributes
    parts = []
    _media_attrs = state.getattr("sensor.ai_media_upcoming") or {}  # noqa: F821
    for key in ("sonarr", "radarr"):
        val = _media_attrs.get(key) or ""
        if val and val not in ("unknown", "unavailable", ""):
            parts.append(val)
    recent = _media_attrs.get("recent_downloads") or ""
    if recent and recent not in ("unknown", "unavailable", ""):
        parts.append(f"Recently downloaded: {recent}")
    return " ".join(parts)


# ── Settings Helpers ──────────────────────────────────────────────────────────

def _is_test_mode() -> bool:
    try:
        return str(
            state.get("input_boolean.ai_test_mode") or "off"  # noqa: F821
        ).lower() == "on"
    except NameError:
        return False


def _get_enabled_sections() -> set:
    """Get set of enabled section names — fallback for when no override is passed."""
    return set(ALL_SECTIONS)


@pyscript_compile
def _parse_sections_csv(raw: str) -> set:
    """Parse a CSV override string into a section set."""
    if not raw or raw in ("unknown", "unavailable"):
        return set(ALL_SECTIONS)
    parsed = {s.strip().lower() for s in raw.split(",") if s.strip()}
    return parsed if parsed else set(ALL_SECTIONS)


def _get_budget_remaining() -> int:
    """Get LLM budget remaining percentage."""
    try:
        return int(float(
            state.get("sensor.ai_llm_budget_remaining") or "100"  # noqa: F821
        ))
    except (ValueError, TypeError, NameError):
        return 100


def _increment_llm_counter(cost: int = 1) -> None:
    """Increment LLM call counter after conversation.process."""
    try:
        current = int(float(
            state.get("sensor.ai_llm_calls_today") or 0  # noqa: F821
        ))
        state.set(  # noqa: F821
            "sensor.ai_llm_calls_today",
            min(current + cost, 999),
            new_attributes={
                "icon": "mdi:counter",
                "friendly_name": "AI LLM Calls Today",
            },
        )
    except Exception as exc:
        log.warning(f"dispatcher: {exc}")  # noqa: F821


# ── Core Assembly Logic ───────────────────────────────────────────────────────

async def _assemble_briefing(
    sections_override: str = "",
    household_entities_override: str = "",
    download_window: str = "since_midnight",
) -> dict:
    """Assemble all briefing sections. Each section fails independently.

    sections_override is always passed from the blueprint. Falls back to
    ALL_SECTIONS when empty. Returns dict with: sections (per-section text),
    assembled (full text), section_count, enabled.
    """
    hour = datetime.now().hour
    enabled = (
        _parse_sections_csv(sections_override)
        if sections_override
           and sections_override not in ("unknown", "unavailable")
        else _get_enabled_sections()
    )

    sections: dict[str, str] = {}
    parts: list[str] = []

    # ── 1. Greeting ──
    if "greeting" in enabled:
        try:
            text = _section_greeting(
                    hour,
                    morning_hour=_get_morning_hour(),
                    afternoon_hour=_get_afternoon_hour(),
                    evening_hour=_get_evening_hour(),
                )
            sections["greeting"] = text
            if text:
                parts.append(text)
        except Exception as exc:
            log.warning(f"dispatcher: {exc}")  # noqa: F821
            sections["greeting"] = ""

    # ── 2. Weather ──
    if "weather" in enabled:
        try:
            text = await _section_weather()
            sections["weather"] = text
            if text:
                parts.append(text)
        except Exception as exc:
            log.warning(f"dispatcher: {exc}")  # noqa: F821
            sections["weather"] = ""

    # ── 3. Calendar ──
    if "calendar" in enabled:
        try:
            text = await _section_calendar(hour)
            sections["calendar"] = text
            if text:
                parts.append(text)
        except Exception as exc:
            log.warning(f"dispatcher: {exc}")  # noqa: F821
            sections["calendar"] = ""

    # ── 4. Email ──
    if "email" in enabled:
        try:
            text = await _section_email(hour)
            sections["email"] = text
            if text:
                parts.append(text)
        except Exception as exc:
            log.warning(f"dispatcher: {exc}")  # noqa: F821
            sections["email"] = ""

    # ── 5. Schedule advisory ──
    if "schedule" in enabled:
        try:
            text = await _section_schedule()
            sections["schedule"] = text
            if text:
                parts.append(text)
        except Exception as exc:
            log.warning(f"dispatcher: {exc}")  # noqa: F821
            sections["schedule"] = ""

    # ── 6. Household ──
    if "household" in enabled:
        try:
            text = await _section_household(household_entities_override)
            sections["household"] = text
            if text:
                parts.append(text)
        except Exception as exc:
            log.warning(f"dispatcher: {exc}")  # noqa: F821
            sections["household"] = ""

    # ── 7. Memory highlights ──
    if "memory" in enabled:
        try:
            text = await _section_memory()
            sections["memory"] = text
            if text:
                parts.append(text)
        except Exception as exc:
            log.warning(f"dispatcher: {exc}")  # noqa: F821
            sections["memory"] = ""

    # ── 8. Projects ──
    if "projects" in enabled:
        try:
            text = await _section_projects()
            sections["projects"] = text
            if text:
                parts.append(text)
        except Exception as exc:
            log.warning("briefing: _section_projects failed: %s", exc)  # noqa: F821
            sections["projects"] = ""

    # ── 9. Media (media_today/media_tomorrow/media_weekly/media) ──
    media_map = {"media_today": 1, "media_tomorrow": 2, "media_weekly": 7, "media": 0}
    for media_key, days in media_map.items():
        if media_key in enabled:
            try:
                text = await _section_media(upcoming_days=days, download_window=download_window)
                sections[media_key] = text
                if text:
                    parts.append(text)
            except Exception as exc:
                log.warning(f"dispatcher: {exc}")  # noqa: F821
                sections[media_key] = ""

    # Assemble full text
    assembled = " ".join(parts)

    # Absolute fallback: ALWAYS deliver something
    if not assembled:
        assembled = (
            "Good morning. I'm having trouble accessing your "
            "information right now."
        )
        sections["_fallback"] = True

    active_count = 0
    for v in sections.values():
        if v and v is not True:
            active_count += 1

    return {
        "sections": sections,
        "assembled": assembled,
        "section_count": active_count,
        "enabled": sorted(enabled),
    }


# ── Core Delivery Logic ──────────────────────────────────────────────────────

async def _deliver_briefing(
    test_mode: bool,
    briefing_label: str = "briefing",
    sections_override: str = "",
    household_entities_override: str = "",
    output_speaker_override: str = "",
    use_dispatcher: bool = True,
    pipeline_name: str = "",
    pipeline_id: str = "",
    tts_volume: float = 0.0,
    briefing_prompt: str = "",
    extra_context: str = "",
    download_window: str = "since_midnight",
) -> dict:
    """Full delivery pipeline.

    Label-based — no slots. The blueprint passes all config inline.
    build → dedup check → budget check → agent dispatch → LLM reformat →
    TTS playback → dedup register → summary → whisper.
    """
    t_start = time.monotonic()

    # ── Step 1: Assemble content ─────────────────────────────────────────
    briefing = await _assemble_briefing(
        sections_override=sections_override,
        household_entities_override=household_entities_override,
        download_window=download_window,
    )
    assembled = briefing["assembled"]
    sections = briefing["sections"]

    log.info(  # noqa: F821
        f"briefing: assembled {briefing['section_count']} sections "
        f"({len(assembled)} chars)"
    )

    if test_mode:
        log.info(  # noqa: F821
            f"briefing [TEST]: content: {assembled[:500]}"
        )
        for name, text in sections.items():
            if text and text is not True:
                log.info(  # noqa: F821
                    f"briefing [TEST]: section {name}: {text[:200]}"
                )

    # ── Step 2: Dedup check ──────────────────────────────────────────────
    is_duplicate = False
    try:
        dedup_call = pyscript.dedup_check(  # noqa: F821
            topic=f"{briefing_label}_briefing",
            source="proactive_briefing",
        )
        dedup_resp = await dedup_call
        if dedup_resp and dedup_resp.get("duplicate"):
            is_duplicate = True
    except Exception as exc:
        log.warning(f"dispatcher: {exc}")  # noqa: F821  — Fail-open: deliver if dedup is down

    if is_duplicate and not test_mode:
        elapsed = round((time.monotonic() - t_start) * 1000, 1)
        log.info(  # noqa: F821
            "briefing: blocked by dedup — already delivered"
        )
        return {
            "status": "ok", "op": "deliver",
            "delivered": False, "reason": "duplicate",
            "elapsed_ms": elapsed,
        }

    if test_mode and is_duplicate:
        log.info(  # noqa: F821
            "briefing [TEST]: duplicate detected but NOT blocking"
        )

    # ── Step 3: Budget check ─────────────────────────────────────────────
    budget = _get_budget_remaining()
    stripped = budget < _get_budget_stripped_threshold()

    if stripped:
        log.info(  # noqa: F821
            f"briefing: budget at {budget}% — stripped mode "
            "(no LLM reformulation, fallback TTS)"
        )

    # ── Step 4: Agent dispatch ───────────────────────────────────────────
    persona = "unknown"
    agent_entity = ""
    voice = _get_fallback_tts_voice()
    voice_id = ""
    dispatch_reason = "default"

    if not stripped:
        if use_dispatcher:
            # Dispatcher mode: let the dispatcher pick the agent
            try:
                dispatch_call = pyscript.agent_dispatch(  # noqa: F821
                    wake_word="proactive_briefing",
                    intent_text=f"{briefing_label} briefing",
                    skip_continuity=True,
                )
                dispatch_resp = await dispatch_call
                if dispatch_resp and dispatch_resp.get("persona"):
                    persona = dispatch_resp["persona"]
                    agent_entity = dispatch_resp.get("agent", "")
                    dispatch_reason = dispatch_resp.get("reason", "auto")
                    voice = dispatch_resp.get(
                        "tts_engine", _get_fallback_tts_voice(),
                    )
                    voice_id = dispatch_resp.get("tts_voice", "")
            except Exception as exc:
                log.warning(  # noqa: F821
                    f"briefing: dispatch failed ({exc}), "
                    f"using fallback voice"
                )
        elif pipeline_name or pipeline_id:
            # Direct pipeline mode: bypass dispatcher, use configured pipeline
            try:
                dispatch_kwargs = {
                    "intent_text": f"{briefing_label} briefing",
                    "skip_continuity": True,
                }
                if pipeline_name:
                    dispatch_kwargs["pipeline_name"] = pipeline_name
                else:
                    dispatch_kwargs["pipeline_id"] = pipeline_id
                dispatch_call = pyscript.agent_dispatch(  # noqa: F821
                    **dispatch_kwargs,
                )
                dispatch_resp = await dispatch_call
                if dispatch_resp and dispatch_resp.get("persona"):
                    persona = dispatch_resp["persona"]
                    agent_entity = dispatch_resp.get("agent", "")
                    dispatch_reason = "pipeline_override"
                    voice = dispatch_resp.get(
                        "tts_engine", _get_fallback_tts_voice(),
                    )
                    voice_id = dispatch_resp.get("tts_voice", "")
            except Exception as exc:
                log.warning(  # noqa: F821
                    f"briefing: pipeline dispatch failed ({exc}), "
                    f"using fallback voice"
                )

    if test_mode:
        log.info(  # noqa: F821
            f"briefing [TEST]: dispatched to {persona} "
            f"({agent_entity}) reason={dispatch_reason} "
            f"stripped={stripped} use_dispatcher={use_dispatcher}"
        )

    # ── Step 5: LLM reformulation ────────────────────────────────────────
    # Skip in stripped mode AND test mode (no LLM cost in either case)
    speech_text = assembled
    llm_used = False

    if not stripped and not test_mode:
        try:
            # Custom prompt from blueprint, or fallback to constant
            if briefing_prompt:
                prompt = (
                    briefing_prompt
                    .replace("{framing}", _briefing_framing_for_hour(datetime.now().hour))
                    .replace("{content}", assembled)
                    .replace("{context}", extra_context or "")
                )
            else:
                prompt = _briefing_prompt_for_hour(datetime.now().hour).format(content=assembled)
            # conversation.process() pyscript shorthand returns None.
            # Use hass.services.async_call with return_response=True
            # (same mechanism as YAML response_variable).
            conv_resp = await hass.services.async_call(  # noqa: F821
                "conversation", "process",
                {"agent_id": agent_entity, "text": prompt},
                blocking=True,
                return_response=True,
            )
            llm_speech = _extract_speech_from_response(conv_resp)
            if llm_speech:
                speech_text = llm_speech
                llm_used = True
                log.info(  # noqa: F821
                    f"briefing: LLM reformulation ok "
                    f"({len(llm_speech)} chars, persona={persona})"
                )
            else:
                log.warning(  # noqa: F821
                    "briefing: LLM returned empty speech, "
                    "using raw assembled content"
                )
        except Exception as exc:
            log.warning(  # noqa: F821
                f"briefing: LLM reformulation failed ({exc}), "
                "using raw assembled content"
            )

        # Increment budget counter (LLM was attempted)
        _increment_llm_counter(1)

    if test_mode and not stripped:
        log.info(  # noqa: F821
            f"briefing [TEST]: WOULD call conversation.process "
            f"(agent={agent_entity})"
        )

    # ── Step 6: TTS playback ─────────────────────────────────────────────
    tts_target_mode = "presence"
    tts_target = ""
    if (output_speaker_override
            and output_speaker_override not in ("unknown", "unavailable", "")):
        tts_target_mode = "explicit"
        tts_target = output_speaker_override

    tts_ok = False
    if not test_mode:
        tts_kwargs = {
            "text": speech_text,
            "voice": voice,
            "voice_id": voice_id,
            "priority": 3,
            "target_mode": tts_target_mode,
        }
        if tts_target:
            tts_kwargs["target"] = tts_target
        if tts_volume and float(tts_volume) > 0:
            tts_kwargs["volume_level"] = float(tts_volume)
        try:
            tts_call = pyscript.tts_queue_speak(**tts_kwargs)  # noqa: F821
            tts_resp = await tts_call
            tts_ok = (
                tts_resp is not None
                and tts_resp.get("status") == "queued"
            )
        except Exception as exc:
            log.error(f"briefing: TTS failed: {exc}")  # noqa: F821
    else:
        log.info(  # noqa: F821
            f"briefing [TEST]: WOULD play TTS via {voice} "
            f"(priority=3, target_mode={tts_target_mode}"
            f"{', target=' + tts_target if tts_target else ''})"
        )

    # ── Step 7: Dedup register ───────────────────────────────────────────
    if not test_mode and tts_ok:
        try:
            reg_call = pyscript.dedup_register(  # noqa: F821
                topic=f"{briefing_label}_briefing",
                source="proactive_briefing",
            )
            await reg_call
        except Exception as exc:
            log.warning(f"dispatcher: {exc}")  # noqa: F821

    # ── Step 8: (delivered flag handled by blueprint) ───────────────────

    # ── Step 9: Update last briefing summary ─────────────────────────────
    summary = assembled[:250]
    if not test_mode:
        try:
            state.set(  # noqa: F821
                "sensor.ai_last_briefing_summary", summary,
                new_attributes={
                    "icon": "mdi:text-box-outline",
                    "friendly_name": "AI Last Briefing Summary",
                },
            )
        except Exception as exc:
            log.warning(f"dispatcher: {exc}")  # noqa: F821

    # ── Step 10: Whisper post-interaction ────────────────────────────────
    if not test_mode and tts_ok:
        try:
            whisper_call = pyscript.agent_whisper(  # noqa: F821
                agent_name=persona,
                user_query=f"{briefing_label} briefing",
                agent_response=speech_text[:200],
                source="system",
            )
            await whisper_call
        except Exception as exc:
            log.warning(f"dispatcher: {exc}")  # noqa: F821

    elapsed = round((time.monotonic() - t_start) * 1000, 1)

    result = {
        "status": "ok",
        "op": "deliver",
        "delivered": tts_ok or test_mode,
        "persona": persona,
        "agent_entity": agent_entity,
        "voice": voice,
        "dispatch_reason": dispatch_reason,
        "stripped_mode": stripped,
        "llm_used": llm_used,
        "budget_remaining": budget,
        "section_count": briefing["section_count"],
        "assembled_length": len(assembled),
        "speech_length": len(speech_text),
        "tts_ok": tts_ok,
        "duplicate_detected": is_duplicate,
        "test_mode": test_mode,
        "elapsed_ms": elapsed,
    }

    # Include full text in test mode for inspection
    if test_mode:
        result["assembled_text"] = assembled
        result["speech_text"] = speech_text
        result["sections"] = sections

    return result


# ── Services ─────────────────────────────────────────────────────────────────

@service(supports_response="only")  # noqa: F821
async def proactive_build_briefing(
    sections_override: str = "",
    download_window: str = "since_midnight",
):
    """
    yaml
    name: Proactive Build Briefing
    description: >-
      Assemble briefing content from all available layers. Each section
      fails independently — partial briefings are fine. Returns assembled text
      and per-section breakdown for inspection. Does NOT deliver — no TTS, no
      LLM reformulation, no state changes. Use proactive_briefing_now for
      full delivery.
    fields:
      sections_override:
        name: Sections override
        description: >-
          Comma-separated enabled sections. Leave empty for all.
        default: ""
        selector:
          text: {}
      download_window:
        name: Download window
        description: >-
          since_midnight = today only, rolling_24h = 24-hour window.
        default: since_midnight
        selector:
          select:
            options:
              - since_midnight
              - rolling_24h
    """
    # Returns: {status, op, assembled, sections, section_count, enabled_sections, test_mode, elapsed_ms}
    t_start = time.monotonic()
    test_mode = _is_test_mode()

    briefing = await _assemble_briefing(
        sections_override=sections_override,
        download_window=download_window,
    )

    elapsed = round((time.monotonic() - t_start) * 1000, 1)

    result = {
        "status": "ok",
        "op": "build",
        "assembled": briefing["assembled"],
        "sections": briefing["sections"],
        "section_count": briefing["section_count"],
        "enabled_sections": briefing["enabled"],
        "test_mode": test_mode,
        "elapsed_ms": elapsed,
    }

    # Sensor attributes (exclude large text to keep sensor lean)
    sensor_state = "test" if test_mode else "ok"
    _set_result(
        sensor_state,
        op="build",
        section_count=briefing["section_count"],
        assembled_length=len(briefing["assembled"]),
        test_mode=test_mode,
        elapsed_ms=elapsed,
    )

    log.info(  # noqa: F821
        f"briefing: build complete — {briefing['section_count']} sections, "
        f"{len(briefing['assembled'])} chars, "
        f"{elapsed}ms{' [TEST]' if test_mode else ''}"
    )

    return result


@service(supports_response="only")  # noqa: F821
async def proactive_briefing_now(
    briefing_label: str = "briefing",
    sections_override: str = "",
    household_entities_override: str = "",
    output_speaker_override: str = "",
    use_dispatcher: bool = True,
    pipeline_name: str = "",
    pipeline_id: str = "",
    tts_volume: float = 0.0,
    briefing_prompt: str = "",
    extra_context: str = "",
    download_window: str = "since_midnight",
):
    """
    yaml
    name: Proactive Briefing Now
    description: >-
      Full briefing delivery pipeline. Assembles content from all layers,
      selects agent persona via dispatcher (or direct pipeline), reformulates
      via LLM conversation.process, plays via TTS queue, registers with dedup
      system, and writes whisper context. On-demand — skips all trigger
      conditions. Delivered flag is managed by the calling blueprint.
    fields:
      briefing_label:
        name: Briefing label
        description: "Free-text name for this instance (e.g. morning, afternoon recap)"
        default: briefing
        selector:
          text: {}
      sections_override:
        name: Sections override
        description: >-
          Comma-separated enabled sections. Valid: greeting, weather,
          calendar, email, schedule, household, memory, projects,
          media_today, media_tomorrow, media_weekly, media.
        default: ""
        selector:
          text: {}
      household_entities_override:
        name: Household entities override
        description: >-
          Comma-separated entity IDs for household monitoring.
        default: ""
        selector:
          text: {}
      output_speaker_override:
        name: Output speaker override
        description: >-
          Media player entity ID for TTS output. Leave empty for
          auto (follow presence).
        default: ""
        selector:
          text: {}
      use_dispatcher:
        name: Use dispatcher
        description: >-
          When true, dispatcher picks the agent. When false, uses pipeline_id.
        default: true
        selector:
          boolean: {}
      pipeline_name:
        name: Pipeline Name
        description: >-
          Pipeline display name when dispatcher is disabled (e.g. "Rick").
          Preferred over pipeline_id — survives pipeline recreation.
        default: ""
        selector:
          text: {}
      pipeline_id:
        name: Pipeline ID
        description: >-
          Assist pipeline ULID when dispatcher is disabled (legacy).
        default: ""
        selector:
          text: {}
      tts_volume:
        name: TTS volume
        description: >-
          Volume level passed to tts_queue_speak. 0 = don't set.
        default: 0.0
        selector:
          number:
            min: 0.0
            max: 1.0
            step: 0.05
      briefing_prompt:
        name: Briefing prompt
        description: >-
          Custom LLM prompt. Placeholders: {content}, {context}, {framing}.
          Leave empty for the default prompt.
        default: ""
        selector:
          text:
            multiline: true
      extra_context:
        name: Extra context
        description: >-
          Evaluated context template output injected into {context}.
        default: ""
        selector:
          text: {}
      download_window:
        name: Download window
        description: >-
          How far back to look for Radarr/Sonarr downloads.
          since_midnight = today only, rolling_24h = 24-hour window.
        default: since_midnight
        selector:
          select:
            options:
              - since_midnight
              - rolling_24h
    """
    # Normalize use_dispatcher (may arrive as string from YAML)
    if isinstance(use_dispatcher, str):
        use_dispatcher = use_dispatcher.lower() in ("true", "1", "yes", "on")

    t_start = time.monotonic()
    test_mode = _is_test_mode()

    log.info(  # noqa: F821
        f"briefing: delivery starting (label={briefing_label}, "
        f"dispatcher={use_dispatcher}, test={test_mode})"
    )

    result = await _deliver_briefing(
        test_mode,
        briefing_label=briefing_label,
        sections_override=sections_override,
        household_entities_override=household_entities_override,
        output_speaker_override=output_speaker_override,
        use_dispatcher=use_dispatcher,
        pipeline_name=pipeline_name,
        pipeline_id=pipeline_id,
        tts_volume=tts_volume,
        briefing_prompt=briefing_prompt,
        extra_context=extra_context,
        download_window=download_window,
    )

    elapsed = round((time.monotonic() - t_start) * 1000, 1)
    result["total_elapsed_ms"] = elapsed

    # Update status sensor (exclude large text fields)
    sensor_attrs = {
        k: v for k, v in result.items()
        if k not in ("sections", "assembled_text", "speech_text")
    }
    sensor_state = (
        "test" if test_mode
        else "ok" if result.get("delivered")
        else "skipped"
    )
    _set_result(sensor_state, **sensor_attrs)

    status = (
        "DELIVERED" if result.get("delivered")
        else result.get("reason", "skipped")
    )
    log.info(  # noqa: F821
        f"briefing: {status} persona={result.get('persona', '?')} "
        f"stripped={result.get('stripped_mode', False)} "
        f"sections={result.get('section_count', 0)} "
        f"{elapsed}ms{' [TEST]' if test_mode else ''}"
    )

    return result


# ── Startup ──────────────────────────────────────────────────────────────────

@time_trigger("startup")  # noqa: F821
async def _startup():
    """Initialize proactive briefing status sensor."""
    _ensure_result_entity_name(force=True)
    _set_result("idle", op="startup")
    log.info("proactive_briefing.py loaded — briefing idle")  # noqa: F821


# ── Configurable Helper Getter ────────────────────────────────────────────────

def _get_budget_stripped_threshold() -> float:
    """Read budget personality threshold from helper; fallback 20."""
    try:
        return float(state.get("input_number.ai_budget_personality_threshold"))  # noqa: F821
    except (TypeError, ValueError, NameError):
        return 20.0
