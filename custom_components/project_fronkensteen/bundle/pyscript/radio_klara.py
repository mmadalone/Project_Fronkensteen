"""Radio Klara — Now-Playing Awareness for Conversation Agents.

Reads a cached weekly schedule (JSON) and exposes a "now playing" sensor that
tells conversation agents what show is currently airing on Radio Klara
(Valencian community radio station based in Valencia, Spain — broadcasting
in Valencian and Spanish, libertarian/anarchist editorial line).
Optionally re-fetches the schedule from the station's PDF tríptic on a
configurable interval.

Sensors:
  sensor.ai_radio_klara_status      — module status: idle, loaded, refreshing,
                                       refresh_failed, stale
  sensor.ai_radio_klara_now_playing — current show title (or off_air);
                                       attributes: description, language,
                                       start_time, end_time, day_of_week,
                                       next_show, source

Services:
  pyscript.radio_klara_refresh_schedule(force=False)
    Re-fetch the schedule PDF, parse via llm_task_call, write JSON cache.
    No-op if last refresh < refresh_hours ago and force=False.

Triggers:
  startup            → load cache, seed sensors
  cron(*/15 * * * *) → recompute now-playing, check refresh due
  state_trigger      → MA media_title change → recompute now-playing

Config (entity_config.yaml radio_stations: section):
  Per-station match patterns + schedule source descriptor. Currently only
  Radio Klara is implemented but the module is structured for multi-station
  expansion.

Helpers (packages/ai_radio_klara.yaml):
  input_boolean.ai_radio_klara_enabled       — kill switch
  input_number.ai_radio_klara_refresh_hours  — refresh cadence
  input_datetime.ai_radio_klara_last_refresh — last successful refresh stamp
  input_boolean.ai_radio_klara_data_stale    — set when cache > 2× interval

Dependencies:
  - pyscript.llm_task_call (common_utilities.py) — for Phase 2 PDF→JSON
  - pypdf (declared in configuration.yaml pyscript: requirements:) — Phase 2

Deployed: 2026-04-09
"""
import time
from datetime import datetime, timedelta
from typing import Any

from shared_utils import load_entity_config

# =============================================================================
# Constants
# =============================================================================

CACHE_DIR = "/config/data"
CACHE_FILE = "/config/data/radio_klara_schedule.json"
RESULT_ENTITY = "sensor.ai_radio_klara_status"
NOW_PLAYING_ENTITY = "sensor.ai_radio_klara_now_playing"

STATION_SLUG = "radio_klara"
HTTP_TIMEOUT = 15  # seconds
STALE_MULTIPLIER = 2  # cache stale if older than 2× refresh interval
FAILURE_NOTIFY_THRESHOLD = 3

DAY_NAMES = [
    "monday", "tuesday", "wednesday", "thursday",
    "friday", "saturday", "sunday",
]

# =============================================================================
# Module-level state
# =============================================================================

_schedule_cache: dict = {}
_last_refresh_ts: float = 0.0
_consecutive_failures: int = 0
_station_config: dict = {}


# =============================================================================
# File I/O — @pyscript_executor (sandbox restriction)
# =============================================================================

@pyscript_executor  # noqa: F821
def _load_cache_file(path: str):
    """Read JSON cache from disk. Returns dict or None."""
    import json as _json
    try:
        with open(path, "r") as f:
            data = _json.load(f)
        if not isinstance(data, dict):
            return None
        if not isinstance(data.get("weekly_schedule"), list):
            return None
        return data
    except (FileNotFoundError, ValueError, OSError):
        return None


@pyscript_executor  # noqa: F821
def _write_cache_file(path: str, data_json: str) -> bool:
    """Atomic write: write to .tmp then os.replace."""
    import os as _os
    try:
        _os.makedirs(_os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            f.write(data_json)
        _os.replace(tmp, path)
        return True
    except OSError:
        return False


@pyscript_executor  # noqa: F821
def _pdf_to_text(pdf_bytes):
    """Extract plain text from PDF bytes. Returns text or None.

    Requires pypdf to be installed (declared in configuration.yaml
    pyscript.requirements). Returns None gracefully if not available.
    """
    try:
        import pypdf  # type: ignore
    except ImportError:
        return None
    try:
        from io import BytesIO
        reader = pypdf.PdfReader(BytesIO(pdf_bytes))
        out = []
        for page in reader.pages:
            out.append(page.extract_text() or "")
        return "\n".join(out)
    except Exception:
        return None


# =============================================================================
# Pure logic — @pyscript_compile
# =============================================================================

@pyscript_compile  # noqa: F821
def _hhmm_to_minutes(s):
    """Parse 'HH:MM' to minutes since midnight. '24:00' → 1440."""
    if not s or ":" not in s:
        return None
    try:
        h, m = s.split(":", 1)
        h = int(h)
        m = int(m)
        if h < 0 or h > 24 or m < 0 or m > 59:
            return None
        return h * 60 + m
    except ValueError:
        return None


@pyscript_compile  # noqa: F821
def _now_playing_from_schedule(schedule_list, weekday_idx, current_minutes):
    """Pure lookup — no HA dependencies.

    schedule_list: list of show dicts
    weekday_idx: 0=Monday .. 6=Sunday
    current_minutes: minutes since midnight (0..1439)

    Returns dict with keys (title, start_time, end_time, day_of_week,
    description, language, next_show) or None if no match.
    """
    day_names = ["monday", "tuesday", "wednesday", "thursday",
                 "friday", "saturday", "sunday"]
    today = day_names[weekday_idx]

    # Build today's shows sorted by start time
    today_shows = []
    for show in schedule_list:
        if show.get("day_of_week") != today:
            continue
        start = _hhmm_to_minutes(show.get("start_time", ""))
        end = _hhmm_to_minutes(show.get("end_time", ""))
        if start is None or end is None:
            continue
        # 24:00 means end-of-day
        if end == 0:
            end = 1440
        today_shows.append((start, end, show))

    today_shows.sort(key=lambda t: t[0])

    # Find current show
    current_show = None
    next_show_obj = None
    for i, (start, end, show) in enumerate(today_shows):
        if start <= current_minutes < end:
            current_show = show
            if i + 1 < len(today_shows):
                next_show_obj = today_shows[i + 1][2]
            break

    if current_show is None:
        return None

    # Build next-show description (cross-day if needed)
    next_label = ""
    if next_show_obj:
        next_label = f"{next_show_obj.get('start_time', '')} {next_show_obj.get('title', '')}"
    else:
        # Look at tomorrow's first show
        tomorrow = day_names[(weekday_idx + 1) % 7]
        tomorrow_first = None
        tomorrow_min = 9999
        for show in schedule_list:
            if show.get("day_of_week") != tomorrow:
                continue
            start = _hhmm_to_minutes(show.get("start_time", ""))
            if start is not None and start < tomorrow_min:
                tomorrow_min = start
                tomorrow_first = show
        if tomorrow_first:
            next_label = (
                f"{tomorrow_first.get('start_time', '')} "
                f"{tomorrow_first.get('title', '')} (tomorrow)"
            )

    return {
        "title": current_show.get("title", ""),
        "start_time": current_show.get("start_time", ""),
        "end_time": current_show.get("end_time", ""),
        "day_of_week": today,
        "description": current_show.get("description", ""),
        "language": current_show.get("language", ""),
        "next_show": next_label,
    }


@pyscript_compile  # noqa: F821
def _extract_pdf_link(html, base_url):
    """Find latest .pdf link in schedule page HTML via regex."""
    import re as _re
    if not html:
        return None
    # Look for tríptic-style PDFs first
    match = _re.search(
        r'href=["\']([^"\']+triptic[^"\']*\.pdf)["\']',
        html, _re.IGNORECASE,
    )
    if not match:
        # Fall back to any PDF reference on the page
        match = _re.search(
            r'href=["\']([^"\']+\.pdf)["\']',
            html, _re.IGNORECASE,
        )
    if not match:
        return None
    href = match.group(1)
    if href.startswith("http://") or href.startswith("https://"):
        return href
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/"):
        # Reconstruct origin from base_url
        try:
            scheme_end = base_url.index("://") + 3
            host_end = base_url.index("/", scheme_end)
            origin = base_url[:host_end]
        except ValueError:
            return None
        return origin + href
    # Relative path
    if "/" in base_url:
        return base_url.rsplit("/", 1)[0] + "/" + href
    return None


# =============================================================================
# HTTP fetch — async (aiohttp via main pyscript loop)
# =============================================================================

async def _fetch_url(url, timeout=HTTP_TIMEOUT):
    """GET a URL and return body bytes. Returns None on failure."""
    try:
        from aiohttp import ClientSession, ClientTimeout
        ct = ClientTimeout(total=timeout)
        session = ClientSession(timeout=ct)
        try:
            resp = await session.get(url)
            if resp.status != 200:
                log.warning(  # noqa: F821
                    f"radio_klara: HTTP {resp.status} from {url}"
                )
                return None
            return await resp.read()
        finally:
            await session.close()
    except Exception as exc:
        log.warning(f"radio_klara: fetch failed {url}: {exc}")  # noqa: F821
        return None


# =============================================================================
# LLM extraction — Phase 2
# =============================================================================

async def _llm_extract_schedule(text):
    """Send PDF text to llm_task_call for structured extraction.

    Returns dict {weekly_schedule: [...]} or None on failure.
    """
    if not text or len(text) < 100:
        return None

    # Truncate to avoid context overflow
    if len(text) > 12000:
        text = text[:12000]

    system_prompt = (
        "You extract Radio Klara weekly programming schedules from PDF text. "
        "Output STRICTLY valid JSON with no markdown fences and no commentary. "
        "Schema: {\"weekly_schedule\": [{\"day_of_week\": \"monday\", "
        "\"start_time\": \"HH:MM\", \"end_time\": \"HH:MM\", \"title\": \"...\", "
        "\"language\": \"catalan|spanish|other\", \"description\": \"short EN description\"}]}. "
        "Cover ALL 7 days. Use 24-hour times. "
        "End-of-day slots use end_time \"24:00\"."
    )
    user_prompt = (
        "Extract the complete weekly schedule from this Radio Klara PDF text. "
        "Be exhaustive — every time slot for all 7 days.\n\n"
        f"PDF TEXT:\n{text}"
    )

    try:
        result = pyscript.llm_task_call(  # noqa: F821
            prompt=user_prompt,
            system=system_prompt,
            max_tokens=4000,
            temperature=0.1,
            priority_tier="standard",
        )
        resp = await result
        if not resp or not isinstance(resp, dict):
            return None
        text_out = resp.get("text") or resp.get("response") or ""
        if not text_out:
            return None
        # Strip potential markdown fences
        text_out = text_out.strip()
        if text_out.startswith("```"):
            lines = text_out.split("\n")
            text_out = "\n".join(lines[1:-1] if lines[-1].strip().startswith("```") else lines[1:])
        import json as _json
        parsed = _json.loads(text_out)
        if not isinstance(parsed, dict):
            return None
        if not isinstance(parsed.get("weekly_schedule"), list):
            return None
        if len(parsed["weekly_schedule"]) < 5:
            log.warning(  # noqa: F821
                "radio_klara: LLM extraction returned suspiciously few shows"
            )
            return None
        return parsed
    except Exception as exc:
        log.warning(f"radio_klara: LLM extraction failed: {exc}")  # noqa: F821
        return None


# =============================================================================
# Sensor writers
# =============================================================================

def _set_status(state_value, **attrs):
    """Update the result/status sensor."""
    base_attrs = {
        "icon": "mdi:radio",
        "friendly_name": "AI Radio Klara Status",
    }
    base_attrs.update(attrs)
    state.set(RESULT_ENTITY, value=state_value, new_attributes=base_attrs)  # noqa: F821


def _update_now_playing_sensor():
    """Compute current show from cached schedule and write the sensor."""
    station_name = (_station_config or {}).get("name") or "Radio Klara"
    schedule_list = _schedule_cache.get("weekly_schedule") if _schedule_cache else None
    if not schedule_list:
        state.set(  # noqa: F821
            NOW_PLAYING_ENTITY,
            value="idle",
            new_attributes={
                "icon": "mdi:radio-tower",
                "friendly_name": "AI Radio Klara Now Playing",
                "station_name": station_name,
                "description": "",
                "language": "",
                "start_time": "",
                "end_time": "",
                "day_of_week": "",
                "next_show": "",
                "source": "no_schedule",
            },
        )
        return

    now = datetime.now()  # noqa: F821
    weekday_idx = now.weekday()
    current_minutes = now.hour * 60 + now.minute
    show = _now_playing_from_schedule(schedule_list, weekday_idx, current_minutes)

    if show is None:
        state.set(  # noqa: F821
            NOW_PLAYING_ENTITY,
            value="off_air",
            new_attributes={
                "icon": "mdi:radio-off",
                "friendly_name": "AI Radio Klara Now Playing",
                "station_name": station_name,
                "description": "",
                "language": "",
                "start_time": "",
                "end_time": "",
                "day_of_week": DAY_NAMES[weekday_idx],
                "next_show": "",
                "source": "schedule_gap",
            },
        )
        return

    state.set(  # noqa: F821
        NOW_PLAYING_ENTITY,
        value=show["title"],
        new_attributes={
            "icon": "mdi:radio-tower",
            "friendly_name": "AI Radio Klara Now Playing",
            "station_name": station_name,
            "description": show["description"],
            "language": show["language"],
            "start_time": show["start_time"],
            "end_time": show["end_time"],
            "day_of_week": show["day_of_week"],
            "next_show": show["next_show"],
            "source": "schedule",
        },
    )


# =============================================================================
# Helpers — read interval helper, stale check, etc.
# =============================================================================

def _get_refresh_hours() -> int:
    """Read configured refresh interval. Defaults to 168 (weekly)."""
    try:
        v = state.get("input_number.ai_radio_klara_refresh_hours")  # noqa: F821
        if v not in (None, "", "unknown", "unavailable"):
            return max(1, int(float(v)))
    except Exception:
        pass
    return 168


def _is_enabled() -> bool:
    try:
        return str(state.get("input_boolean.ai_radio_klara_enabled") or "off").lower() == "on"  # noqa: F821
    except Exception:
        return True  # default-on if helper missing


def _set_stale(stale: bool):
    try:
        if stale:
            service.call("input_boolean", "turn_on",  # noqa: F821
                         entity_id="input_boolean.ai_radio_klara_data_stale")
        else:
            service.call("input_boolean", "turn_off",  # noqa: F821
                         entity_id="input_boolean.ai_radio_klara_data_stale")
    except Exception:
        pass


def _stamp_last_refresh():
    try:
        service.call(  # noqa: F821
            "input_datetime", "set_datetime",
            entity_id="input_datetime.ai_radio_klara_last_refresh",
            datetime=datetime.now().isoformat(),  # noqa: F821
        )
    except Exception:
        pass


def _check_stale():
    """If cache is older than 2× refresh interval, set stale flag."""
    global _last_refresh_ts
    if _last_refresh_ts <= 0:
        return
    refresh_hours = _get_refresh_hours()
    age_hours = (time.time() - _last_refresh_ts) / 3600.0
    if age_hours > (refresh_hours * STALE_MULTIPLIER):
        _set_stale(True)
    else:
        _set_stale(False)


# =============================================================================
# Refresh pipeline — Phase 2
# =============================================================================

def _set_status_loaded_from_cache():
    """Restore status sensor to 'loaded' from current in-memory cache."""
    if _schedule_cache and isinstance(_schedule_cache.get("weekly_schedule"), list):
        _set_status(
            "loaded",
            show_count=len(_schedule_cache["weekly_schedule"]),
            fetched_at=_schedule_cache.get("fetched_at", ""),
            source_url=_schedule_cache.get("source_url", ""),
        )
    else:
        _set_status("no_cache")


def _refresh_failure(reason: str) -> str:
    """Common failure path: increment counter, notify, restore status, return reason."""
    global _consecutive_failures
    _consecutive_failures += 1
    _maybe_notify_failure()
    # Status reflects failure but cache (if any) remains usable
    if _schedule_cache and isinstance(_schedule_cache.get("weekly_schedule"), list):
        _set_status(
            "refresh_failed",
            reason=reason,
            consecutive_failures=_consecutive_failures,
            show_count=len(_schedule_cache["weekly_schedule"]),
            fetched_at=_schedule_cache.get("fetched_at", ""),
            source_url=_schedule_cache.get("source_url", ""),
        )
    else:
        _set_status(
            "refresh_failed",
            reason=reason,
            consecutive_failures=_consecutive_failures,
        )
    return reason


async def _do_refresh():
    """Run the full refresh pipeline. Returns status string."""
    global _schedule_cache, _last_refresh_ts, _consecutive_failures

    cfg = _station_config or {}
    src = cfg.get("schedule_source") or {}
    page_url = src.get("page_url")
    if not page_url:
        return _refresh_failure("no_page_url")

    _set_status("refreshing")

    # Step 1: fetch page
    page_bytes = await _fetch_url(page_url)
    if not page_bytes:
        return _refresh_failure("page_fetch_failed")

    try:
        page_html = page_bytes.decode("utf-8", errors="replace")
    except Exception:
        return _refresh_failure("page_decode_failed")

    # Step 2: extract PDF link
    pdf_url = _extract_pdf_link(page_html, page_url)
    if not pdf_url:
        return _refresh_failure("pdf_link_not_found")

    log.info(f"radio_klara: discovered PDF URL: {pdf_url}")  # noqa: F821

    # Step 3: download PDF
    pdf_bytes = await _fetch_url(pdf_url)
    if not pdf_bytes:
        return _refresh_failure("pdf_download_failed")

    # Step 4: extract text
    text = _pdf_to_text(pdf_bytes)
    if not text:
        log.error(  # noqa: F821
            "radio_klara: PDF→text failed. Verify pypdf is installed: "
            "configuration.yaml → pyscript: requirements: - pypdf, then restart HA."
        )
        return _refresh_failure("pdf_text_extract_failed")

    # Step 5: LLM structured extraction
    parsed = await _llm_extract_schedule(text)
    if not parsed:
        return _refresh_failure("llm_extract_failed")

    # Step 6: validate + assemble cache
    new_cache = {
        "station_slug": STATION_SLUG,
        "station_name": cfg.get("name", "Radio Klara"),
        "fetched_at": datetime.now().isoformat(),  # noqa: F821
        "source_url": pdf_url,
        "schedule_version_hint": datetime.now().strftime("%Y-%m"),  # noqa: F821
        "weekly_schedule": parsed["weekly_schedule"],
    }

    # Step 7: atomic write
    import json as _json
    ok = _write_cache_file(CACHE_FILE, _json.dumps(new_cache, indent=2))
    if not ok:
        return _refresh_failure("cache_write_failed")

    # Step 8: success — update in-memory + sensor + helpers
    _schedule_cache = new_cache
    _last_refresh_ts = time.time()
    _consecutive_failures = 0
    _stamp_last_refresh()
    _set_stale(False)
    _update_now_playing_sensor()
    _set_status("loaded", show_count=len(new_cache["weekly_schedule"]),
                source_url=pdf_url)
    return "ok"


def _maybe_notify_failure():
    """Fire persistent_notification if failure threshold exceeded."""
    if _consecutive_failures < FAILURE_NOTIFY_THRESHOLD:
        return
    try:
        service.call(  # noqa: F821
            "persistent_notification", "create",
            title="Radio Klara schedule refresh failing",
            message=(
                f"radio_klara: {_consecutive_failures} consecutive refresh "
                "failures. Cache is preserved but may go stale. Check logs."
            ),
            notification_id="radio_klara_refresh_failing",
        )
    except Exception:
        pass


# =============================================================================
# Public services
# =============================================================================

@service(supports_response="optional")  # noqa: F821
async def radio_klara_refresh_schedule(force: bool = False):
    """yaml
    name: Radio Klara — refresh schedule
    description: >
      Re-fetch the Radio Klara weekly schedule from the station's website,
      parse the PDF tríptic, and update the local cache. Honors the
      ai_radio_klara_refresh_hours interval unless force=true.
    fields:
      force:
        name: Force refresh
        description: Skip the interval check and refresh immediately.
        default: false
        selector:
          boolean:
    """
    if not _is_enabled() and not force:
        return {"status": "disabled"}

    if not force:
        refresh_hours = _get_refresh_hours()
        if _last_refresh_ts > 0:
            age_hours = (time.time() - _last_refresh_ts) / 3600.0
            if age_hours < refresh_hours:
                return {
                    "status": "skipped",
                    "reason": "interval_not_elapsed",
                    "age_hours": round(age_hours, 2),
                    "refresh_hours": refresh_hours,
                }

    status = await _do_refresh()
    return {"status": status, "consecutive_failures": _consecutive_failures}


@service(supports_response="only")  # noqa: F821
def radio_klara_now_playing():
    """yaml
    name: Radio Klara — now playing
    description: >
      Returns the show currently airing on Radio Klara as a dict.
      Useful for blueprint variables and ad-hoc queries.
    """
    schedule_list = _schedule_cache.get("weekly_schedule") if _schedule_cache else None
    if not schedule_list:
        return {"status": "no_schedule"}

    now = datetime.now()  # noqa: F821
    show = _now_playing_from_schedule(
        schedule_list, now.weekday(), now.hour * 60 + now.minute,
    )
    if show is None:
        return {"status": "off_air", "day_of_week": DAY_NAMES[now.weekday()]}
    return {"status": "ok", **show}


# =============================================================================
# Triggers
# =============================================================================

@time_trigger("startup")  # noqa: F821
def radio_klara_startup():
    """Load cache from disk, seed sensors, schedule refresh check."""
    global _schedule_cache, _last_refresh_ts, _station_config

    # Load station config
    cfg = load_entity_config()
    stations = (cfg or {}).get("radio_stations") or {}
    _station_config = stations.get(STATION_SLUG) or {}
    if not _station_config.get("enabled", True):
        log.info("radio_klara: station disabled in entity_config.yaml")  # noqa: F821
        _set_status("disabled")
        return

    # Load cached schedule
    cached = _load_cache_file(CACHE_FILE)
    if cached and isinstance(cached.get("weekly_schedule"), list):
        _schedule_cache = cached
        # Approximate last refresh from fetched_at if present
        try:
            ts_iso = cached.get("fetched_at", "")
            if ts_iso:
                _last_refresh_ts = datetime.fromisoformat(ts_iso).timestamp()  # noqa: F821
        except Exception:
            _last_refresh_ts = 0.0
        _set_status(
            "loaded",
            show_count=len(cached["weekly_schedule"]),
            fetched_at=cached.get("fetched_at", ""),
            source_url=cached.get("source_url", ""),
        )
        log.info(  # noqa: F821
            f"radio_klara: loaded {len(cached['weekly_schedule'])} shows "
            f"from cache (fetched {cached.get('fetched_at', 'unknown')})"
        )
    else:
        _set_status("no_cache")
        log.warning(  # noqa: F821
            "radio_klara: no cache at %s — call "
            "pyscript.radio_klara_refresh_schedule(force=true) to bootstrap"
            % CACHE_FILE
        )

    _update_now_playing_sensor()
    _check_stale()


@time_trigger("cron(*/15 * * * *)")  # noqa: F821
async def radio_klara_periodic():
    """Every 15 min: refresh sensor + check refresh due."""
    _update_now_playing_sensor()
    _check_stale()

    # Check if a refresh is due
    if not _is_enabled():
        return
    refresh_hours = _get_refresh_hours()
    if _last_refresh_ts <= 0:
        # Never refreshed — try once
        log.info("radio_klara: bootstrap refresh attempt")  # noqa: F821
        await _do_refresh()
        return
    age_hours = (time.time() - _last_refresh_ts) / 3600.0
    if age_hours >= refresh_hours:
        log.info(  # noqa: F821
            f"radio_klara: refresh interval elapsed ({age_hours:.1f}h "
            f">= {refresh_hours}h), refreshing"
        )
        await _do_refresh()


@state_trigger(  # noqa: F821
    "media_player.workshop_ma.media_title",
    "media_player.bathroom_ma.media_title",
    "media_player.ha_voice_pe_living_room_quark_esp.media_title",
)
def radio_klara_on_media_change(**kwargs):
    """Recompute now-playing whenever an MA player's media_title changes.

    The sensor itself is schedule-based, not playback-based, but this trigger
    ensures the line is fresh exactly when blueprints will read it.
    """
    _update_now_playing_sensor()
