"""I-47: Radarr/Sonarr Media Promotion to L2 and L1 Hot Context.

Fetches upcoming releases and recent downloads from Radarr and Sonarr
REST APIs, promotes formatted summaries into L2 memory and L1 helpers
for agent hot context and proactive briefings. Stateless service driven
by the media_tracking.yaml blueprint.
"""
import json
import time
from aiohttp import ClientSession, ClientTimeout
from datetime import datetime, timedelta
from typing import Any

from shared_utils import build_result_entity_name

# =============================================================================
# Media Promotion Engine — Radarr/Sonarr Integration (I-47)
# =============================================================================
# Promotes Radarr/Sonarr data from L3 (APIs) to L2 (memory) and L1 (helpers)
# for agent hot context and proactive briefings.
#
# Services:
#   pyscript.media_promote_now
#     On-demand media promotion. Fetches upcoming + recent downloads from
#     Radarr/Sonarr, formats them, writes to L2 memory, updates helpers.
#     Called by media_tracking.yaml blueprint.
#
# Key design:
#   - Stateless service — no triggers, no scheduling (blueprint owns timing)
#   - API keys read from HA config entries at startup
#   - Promote cache: 5 min TTL to debounce rapid triggers
#   - L1 sensor: sensor.ai_media_upcoming (state=summary, attrs: sonarr, radarr, recent_downloads)
#   - L2 keys: media_upcoming:summary, media_downloads:recent
#   - Stale flag: input_boolean.ai_media_data_stale
#
# Data sources:
#   - sensor.sonarr_upcoming attributes — daily upcoming TV
#   - Sonarr REST /api/v3/calendar — weekly upcoming TV
#   - calendar.radarr — upcoming movies
#   - Radarr REST /api/v3/history — recently downloaded movies
#   - Sonarr REST /api/v3/history — recently downloaded TV
#   - sensor.sonarr_queue, sensor.radarr_queue — queue counts
#
# Dependencies:
#   - pyscript/memory.py (L2: memory_set)
#   - packages/ai_media_tracking.yaml (helpers)
#
# Deployed: 2026-03-10
# =============================================================================

RESULT_ENTITY = "sensor.ai_media_promotion_status"
PROMOTE_CACHE_TTL = 300  # 5 min — debounce rapid triggers
_API_TIMEOUT = 10  # seconds

# ── Module-Level State ───────────────────────────────────────────────────────

_config: dict[str, str] = {}
_promote_cache: dict[str, Any] = {}
_last_downloads: set[str] = set()  # track seen titles for new-download detection
result_entity_name: dict[str, str] = {}
_consecutive_failures: int = 0
_FAILURE_NOTIFY_THRESHOLD: int = 3


# ── Startup — Read API Keys from Config Entries ─────────────────────────────

@time_trigger("startup")  # noqa: F821
async def _startup():
    """Load Radarr/Sonarr API keys from HA config entries."""
    global _config
    _config = {}
    try:
        for entry in hass.config_entries.async_entries("radarr"):  # noqa: F821
            _config["radarr_url"] = (entry.data.get("url", "").rstrip("/"))
            _config["radarr_key"] = entry.data.get("api_key", "")
            break
        for entry in hass.config_entries.async_entries("sonarr"):  # noqa: F821
            _config["sonarr_url"] = (entry.data.get("url", "").rstrip("/"))
            _config["sonarr_key"] = entry.data.get("api_key", "")
            break
        log.info(  # noqa: F821
            "media_promote: startup — radarr=%s sonarr=%s",
            "ok" if _config.get("radarr_key") else "MISSING",
            "ok" if _config.get("sonarr_key") else "MISSING",
        )
    except Exception as exc:
        log.warning("media_promote: startup config read failed: %s", exc)  # noqa: F821
    # Initialize consolidated media sensor (refreshed every 30 min)
    try:
        state.set(  # noqa: F821
            "sensor.ai_media_upcoming", value="",
            new_attributes={
                "sonarr": "", "radarr": "", "recent_downloads": "",
                "friendly_name": "AI Media Upcoming",
                "icon": "mdi:television-classic",
            },
        )
    except Exception:
        pass


# ── Entity Name Helpers ─────────────────────────────────────────────────────

def _ensure_result_entity_name(force: bool = False) -> None:
    global result_entity_name
    if force or not result_entity_name:
        result_entity_name = build_result_entity_name(RESULT_ENTITY)


def _set_result(state_value: str = "ok", **attrs: Any) -> None:
    _ensure_result_entity_name()
    attrs.update(result_entity_name)
    state.set(RESULT_ENTITY, value=state_value, new_attributes=attrs)  # noqa: F821


# ── Pure-Python Formatters ──────────────────────────────────────────────────

@pyscript_compile  # noqa: F821
def _format_sonarr_line(tv: list, tv_queue: int, upcoming_days: int) -> str:
    """Format TV upcoming L1 line.

    Example: "TV: Last Week Tonight S13E04, Late Night S13E74 today."
    """
    if not tv and tv_queue <= 0:
        return ""

    parts = []
    if tv:
        tv_names = [item.get("label", item.get("title", "?")) for item in tv[:4]]
        suffix = f" +{len(tv) - 4} more" if len(tv) > 4 else ""
        window = "today" if upcoming_days <= 1 else (
            "today/tomorrow" if upcoming_days <= 2 else "this week"
        )
        parts.append(f"{', '.join(tv_names)}{suffix} {window}")

    if tv_queue > 0:
        parts.append(f"{tv_queue} in queue")

    return "TV: " + ". ".join(parts) + "."


@pyscript_compile  # noqa: F821
def _format_radarr_line(movies: list, movie_queue: int, upcoming_days: int) -> str:
    """Format Movies upcoming L1 line.

    Example: "Movies: The Matrix (Mar 15) today."
    """
    if not movies and movie_queue <= 0:
        return ""

    parts = []
    if movies:
        movie_names = []
        for m in movies[:3]:
            name = m.get("title", "?")
            date = m.get("date", "")
            if date:
                movie_names.append(f"{name} ({date})")
            else:
                movie_names.append(name)
        suffix = f" +{len(movies) - 3} more" if len(movies) > 3 else ""
        window = "today" if upcoming_days <= 1 else (
            "today/tomorrow" if upcoming_days <= 2 else "this week"
        )
        parts.append(f"{', '.join(movie_names)}{suffix} {window}")

    if movie_queue > 0:
        parts.append(f"{movie_queue} in queue")

    return "Movies: " + ". ".join(parts) + "."


@pyscript_compile  # noqa: F821
def _format_upcoming_line(
    tv: list, movies: list, tv_queue: int, movie_queue: int,
) -> str:
    """Format combined L1 one-liner (max 255 chars). Backward compat."""
    parts = []
    if tv:
        tv_names = [item.get("label", item.get("title", "?")) for item in tv[:4]]
        suffix = f" +{len(tv) - 4} more" if len(tv) > 4 else ""
        parts.append(f"TV: {', '.join(tv_names)}{suffix}")
    if movies:
        movie_names = []
        for m in movies[:3]:
            name = m.get("title", "?")
            date = m.get("date", "")
            movie_names.append(f"{name} ({date})" if date else name)
        suffix = f" +{len(movies) - 3} more" if len(movies) > 3 else ""
        parts.append(f"Movies: {', '.join(movie_names)}{suffix}")
    if tv_queue > 0 or movie_queue > 0:
        q_parts = []
        if tv_queue > 0:
            q_parts.append(f"{tv_queue} TV")
        if movie_queue > 0:
            q_parts.append(f"{movie_queue} movie")
        parts.append(f"Queue: {', '.join(q_parts)}")
    if not parts:
        return ""
    line = ". ".join(parts) + "."
    if len(line) > 255:
        line = line[:252] + "..."
    return line


@pyscript_compile  # noqa: F821
def _format_recent_line(tv_recent: list, movie_recent: list) -> str:
    """Format recent downloads for briefing helper.

    Example: "Breaking Bad S01E01, The Matrix"
    """
    titles = []
    for item in tv_recent[:5]:
        titles.append(item.get("label", item.get("title", "?")))
    for item in movie_recent[:5]:
        titles.append(item.get("title", "?"))

    if not titles:
        return ""

    return ", ".join(titles)


@pyscript_compile  # noqa: F821
def _parse_sonarr_upcoming_attrs(attrs: dict) -> list:
    """Parse sensor.sonarr_upcoming attributes into normalized list.

    Supports two formats:
      - Structured: attrs["data"] or attrs["episodes"] = list of dicts
      - Flat: attrs = {"Show Name": "S01E02", ...} (HA Sonarr integration)
    """
    if not attrs:
        return []

    # ── Try structured format first (legacy / Sonarr add-on) ──
    data = attrs.get("data") or attrs.get("episodes") or []
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except (json.JSONDecodeError, TypeError):
            data = []

    if data and isinstance(data, list) and isinstance(data[0], dict):
        results = []
        for item in data:
            series = item.get("series", {}) or {}
            title = series.get("title", item.get("title", "Unknown"))
            ep_num = item.get("episodeNumber", "")
            season = item.get("seasonNumber", "")
            label = title
            if season and ep_num:
                label = f"{title} season {int(season)}, episode {int(ep_num)}"
            air_date = item.get("airDateUtc", item.get("airDate", ""))
            results.append({
                "title": title,
                "label": label,
                "date": air_date[:10] if air_date else "",
            })
        return results

    # ── Flat format: {"Show Name": "S01E02", "unit_of_measurement": ...} ──
    skip_keys = {
        "unit_of_measurement", "friendly_name", "icon",
        "device_class", "state_class", "attribution",
    }
    results = []
    for key, val in attrs.items():
        if key in skip_keys:
            continue
        title = key
        ep_code = str(val) if val else ""
        if ep_code:
            # Convert S13E07 → season 13, episode 7
            import re as _re
            ep_friendly = _re.sub(
                r'S(\d{1,2})E(\d{1,3})',
                lambda x: f"season {int(x.group(1))}, episode {int(x.group(2))}",
                ep_code, flags=_re.IGNORECASE,
            )
            label = f"{title} {ep_friendly}"
        else:
            label = title
        results.append({"title": title, "label": label, "date": ""})
    return results


@pyscript_compile  # noqa: F821
def _parse_sonarr_calendar_api(data: list) -> list:
    """Parse Sonarr /api/v3/calendar response into normalized list."""
    if not data:
        return []

    results = []
    for item in data:
        series = item.get("series", {}) or {}
        title = series.get("title", item.get("title", "Unknown"))
        ep_num = item.get("episodeNumber", "")
        season = item.get("seasonNumber", "")
        label = title
        if season and ep_num:
            label = f"{title} season {int(season)}, episode {int(ep_num)}"
        air_date = item.get("airDateUtc", item.get("airDate", ""))
        results.append({
            "title": title,
            "label": label,
            "date": air_date[:10] if air_date else "",
        })
    return results


@pyscript_compile  # noqa: F821
def _parse_radarr_calendar(events: list) -> list:
    """Parse calendar.radarr events into normalized list.

    Filters out multi-day events whose start date is before today
    (e.g. "in cinemas" events that span weeks). Only shows movies
    whose start date is today or later.
    """
    if not events:
        return []

    today = datetime.now().date()
    results = []
    for ev in events:
        summary = ev.get("summary", ev.get("title", "Unknown"))
        start = ev.get("start", "")
        date_str = ""
        if start:
            try:
                dt = datetime.fromisoformat(str(start))
                # Skip stale multi-day events (start before today)
                if dt.date() < today:
                    continue
                date_str = dt.strftime("%b %d")
            except (ValueError, TypeError):
                date_str = str(start)[:10]
        results.append({"title": summary, "date": date_str})
    return results


@pyscript_compile  # noqa: F821
def _parse_history_response(data: list) -> list:
    """Parse Radarr/Sonarr /api/v3/history response into title list."""
    if not data:
        return []

    records = data if isinstance(data, list) else data.get("records", [])
    results = []
    seen = set()
    for item in records:
        # Sonarr has series.title + episode info, Radarr has movie.title
        series = item.get("series", {}) or {}
        movie = item.get("movie", {}) or {}
        episode = item.get("episode", {}) or {}

        if series.get("title"):
            title = series["title"]
            ep_num = episode.get("episodeNumber", "")
            season = episode.get("seasonNumber", "")
            label = title
            if season and ep_num:
                label = f"{title} season {int(season)}, episode {int(ep_num)}"
            key = label
        elif movie.get("title"):
            title = movie["title"]
            label = title
            key = title
        else:
            # sourceTitle is a raw scene release filename — clean it
            label = _clean_source_title(item.get("sourceTitle", "Unknown"))
            title = label
            key = label

        if key not in seen:
            seen.add(key)
            results.append({"title": title, "label": label})

    return results


@pyscript_compile  # noqa: F821
def _clean_source_title(raw: str) -> str:
    """Strip scene release junk from a sourceTitle, keeping show name + episode."""
    import re as _re
    if not raw or raw == "Unknown":
        return raw
    # Replace dots/underscores with spaces
    cleaned = raw.replace(".", " ").replace("_", " ")
    # Try to extract up to SxxExx pattern
    m = _re.match(r'^(.+?\s+S\d{1,2}E\d{1,3})', cleaned, _re.IGNORECASE)
    if m:
        title_part = m.group(1).strip()
        # Convert SxxExx to TTS-friendly format
        title_part = _re.sub(
            r'S(\d{1,2})E(\d{1,3})',
            lambda x: f"season {int(x.group(1))}, episode {int(x.group(2))}",
            title_part, flags=_re.IGNORECASE,
        )
        return title_part
    # Try to extract up to a year (movie pattern: "Title 2026")
    m = _re.match(r'^(.+?\s+(?:19|20)\d{2})\b', cleaned)
    if m:
        return m.group(1).strip()
    # Last resort: cut at first resolution/codec indicator
    cutoff = _re.split(
        r'\b(?:720p|1080p|2160p|4K|WEB|HDTV|BluRay|REPACK|PROPER|AMZN|NF)\b',
        cleaned, maxsplit=1, flags=_re.IGNORECASE,
    )
    return cutoff[0].strip() if cutoff[0].strip() else raw


# ── Data Fetch Functions ────────────────────────────────────────────────────

async def _fetch_upcoming_tv(days: int) -> list | None:
    """Fetch upcoming TV shows.

    For daily (days=1): read sensor.sonarr_upcoming attributes (zero cost).
    For weekly (days=7): call Sonarr REST API /api/v3/calendar.
    Returns None on failure, [] on success-but-empty.
    """
    if days <= 1:
        # Use native sensor attributes — zero API cost
        try:
            attrs = state.getattr("sensor.sonarr_upcoming") or {}  # noqa: F821
            return _parse_sonarr_upcoming_attrs(attrs)
        except Exception as exc:
            log.warning("media_promote: sonarr sensor read failed: %s", exc)  # noqa: F821
            return None

    # Weekly — use REST API
    url = _config.get("sonarr_url")
    key = _config.get("sonarr_key")
    if not url or not key:
        log.warning("media_promote: sonarr API config missing")  # noqa: F821
        return None

    now = datetime.now()
    start = now.strftime("%Y-%m-%d")
    end = (now + timedelta(days=days)).strftime("%Y-%m-%d")

    try:
        timeout = ClientTimeout(total=_API_TIMEOUT)
        session = ClientSession(timeout=timeout)
        try:
            resp = await session.get(
                f"{url}/api/v3/calendar",
                params={"start": start, "end": end},
                headers={"X-Api-Key": key},
            )
            if resp.status != 200:
                body = await resp.text()
                log.warning(  # noqa: F821
                    "media_promote: sonarr calendar HTTP %s: %s",
                    resp.status, body[:200],
                )
                return None
            data = await resp.json()
            return _parse_sonarr_calendar_api(data)
        finally:
            await session.close()
    except Exception as exc:
        log.warning("media_promote: sonarr calendar fetch failed: %s", exc)  # noqa: F821
        return None


async def _fetch_upcoming_movies(days: int) -> list | None:
    """Fetch upcoming movies from calendar.radarr entity."""
    try:
        now = datetime.now()
        start_str = now.isoformat(timespec="seconds")
        end_str = (now + timedelta(days=days)).isoformat(timespec="seconds")

        result = calendar.get_events(  # noqa: F821
            entity_id="calendar.radarr",
            start_date_time=start_str,
            end_date_time=end_str,
        )
        resp = await result

        events = []
        if isinstance(resp, dict):
            for key in resp:
                val = resp[key]
                if isinstance(val, dict) and "events" in val:
                    events = val["events"]
                    break
            if not events and "events" in resp:
                events = resp["events"]
        elif isinstance(resp, list):
            events = resp

        return _parse_radarr_calendar(events)
    except Exception as exc:
        log.warning("media_promote: radarr calendar fetch failed: %s", exc)  # noqa: F821
        return None


async def _fetch_recent_downloads(
    base_url: str, api_key: str, hours: int,
) -> list | None:
    """Fetch recently downloaded items from Radarr/Sonarr history API."""
    if not base_url or not api_key:
        return None

    try:
        timeout = ClientTimeout(total=_API_TIMEOUT)
        session = ClientSession(timeout=timeout)
        try:
            resp = await session.get(
                f"{base_url}/api/v3/history",
                params={
                    "eventType": "3",  # downloadFolderImported
                    "pageSize": "10",
                    "sortKey": "date",
                    "sortDirection": "descending",
                },
                headers={"X-Api-Key": api_key},
            )
            if resp.status != 200:
                body = await resp.text()
                log.warning(  # noqa: F821
                    "media_promote: history HTTP %s from %s: %s",
                    resp.status, base_url, body[:200],
                )
                return None
            data = await resp.json()
        finally:
            await session.close()

        # Filter by timestamp
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        records = data.get("records", data) if isinstance(data, dict) else data
        filtered = []
        for item in (records if isinstance(records, list) else []):
            date_str = item.get("date", "")
            if date_str:
                try:
                    item_date = datetime.fromisoformat(
                        date_str.replace("Z", "+00:00")
                    )
                    # Compare naive (strip tz for simplicity)
                    if item_date.replace(tzinfo=None) < cutoff:
                        continue
                except (ValueError, TypeError):
                    pass
            filtered.append(item)

        return _parse_history_response(filtered)
    except Exception as exc:
        log.warning(  # noqa: F821
            "media_promote: history fetch failed from %s: %s",
            base_url, exc,
        )
        return None


# ── L2 Memory Helper ────────────────────────────────────────────────────────

async def _l2_set(
    key: str, value: str, tags: str,
    scope: str = "system", expiration_days: int = 1,
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
        log.warning("media_promote: L2 set failed key=%s: %s", key, exc)  # noqa: F821
        return False




def _set_stale_flag(stale: bool) -> None:
    """Set or clear the media data stale flag."""
    try:
        state.set(  # noqa: F821
            "sensor.ai_media_data_stale", "on" if stale else "off",
            new_attributes={
                "icon": "mdi:alert-circle-outline",
                "friendly_name": "AI Media Data Stale",
            },
        )
    except Exception as exc:
        log.warning("media_promote: stale flag failed: %s", exc)  # noqa: F821


def _get_queue_count(entity_id: str) -> int:
    """Read queue count from a native sensor."""
    try:
        val = state.get(entity_id)  # noqa: F821
        if val in (None, "unknown", "unavailable"):
            return 0
        return int(float(val))
    except (ValueError, TypeError, NameError):
        return 0


# ── Core Promotion Logic ───────────────────────────────────────────────────

async def _promote_internal(
    upcoming_days: int = 1,
    download_hours: int = 24,
    write_l1: bool = True,
    force: bool = False,
) -> dict:
    """Core promotion logic. Fetches data, formats, writes L2 + L1."""
    global _promote_cache, _consecutive_failures, _last_downloads

    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")

    # ── Cache check (debounce rapid triggers) ──
    if (not force
            and _promote_cache.get("date") == today_str
            and (time.time() - _promote_cache.get("fetched_at", 0))
                < PROMOTE_CACHE_TTL):
        return {
            "status": "ok", "op": "media_promote",
            "skipped": True, "reason": "cache_valid",
        }

    # ── Kill switch ──
    try:
        enabled = str(
            state.get("input_boolean.ai_media_tracking_enabled")  # noqa: F821
            or "on"
        ).lower()
    except NameError:
        enabled = "on"

    if enabled == "off" and not force:
        return {
            "status": "ok", "op": "media_promote",
            "skipped": True, "reason": "disabled",
        }

    # ── Fetch all data ──
    api_failed = False

    upcoming_tv = await _fetch_upcoming_tv(upcoming_days)
    upcoming_movies = await _fetch_upcoming_movies(upcoming_days)

    recent_tv = await _fetch_recent_downloads(
        _config.get("sonarr_url", ""),
        _config.get("sonarr_key", ""),
        download_hours,
    )
    recent_movies = await _fetch_recent_downloads(
        _config.get("radarr_url", ""),
        _config.get("radarr_key", ""),
        download_hours,
    )

    # Track API failures
    if upcoming_tv is None and upcoming_movies is None:
        api_failed = True
    if upcoming_tv is None:
        upcoming_tv = []
    if upcoming_movies is None:
        upcoming_movies = []
    if recent_tv is None:
        recent_tv = []
    if recent_movies is None:
        recent_movies = []

    # ── Handle API failure ──
    if api_failed:
        _consecutive_failures += 1
        _set_stale_flag(True)
        log.warning(  # noqa: F821
            "media_promote: API failures — stale flag set (failures=%d)",
            _consecutive_failures,
        )
        if _consecutive_failures >= _FAILURE_NOTIFY_THRESHOLD:
            try:
                await service.call(  # noqa: F821
                    "persistent_notification", "create",
                    title="Media Tracking: Repeated API Failures",
                    message=(
                        f"Radarr/Sonarr APIs have failed {_consecutive_failures} "
                        f"consecutive times. Check connectivity to madteevee.local."
                    ),
                    notification_id="ai_media_api_failure",
                )
            except Exception:
                pass
        return {
            "status": "error", "op": "media_promote",
            "api_failed": True, "stale": True,
            "consecutive_failures": _consecutive_failures,
        }

    # ── Reset failure counter on success ──
    if _consecutive_failures > 0:
        _consecutive_failures = 0
        try:
            await service.call(  # noqa: F821
                "persistent_notification", "dismiss",
                notification_id="ai_media_api_failure",
            )
        except Exception:
            pass

    _set_stale_flag(False)

    # ── Queue counts ──
    tv_queue = _get_queue_count("sensor.sonarr_queue")
    movie_queue = _get_queue_count("sensor.radarr_queue")

    # ── Format output ──
    sonarr_line = _format_sonarr_line(upcoming_tv, tv_queue, upcoming_days)
    radarr_line = _format_radarr_line(upcoming_movies, movie_queue, upcoming_days)
    upcoming_summary = _format_upcoming_line(
        upcoming_tv, upcoming_movies, tv_queue, movie_queue,
    )
    recent_summary = _format_recent_line(recent_tv, recent_movies)

    # ── Detect new downloads since last run ──
    current_titles = set()
    for item in recent_tv:
        current_titles.add(item.get("label", item.get("title", "")))
    for item in recent_movies:
        current_titles.add(item.get("title", ""))
    current_titles.discard("")

    new_count = 0
    if _last_downloads:
        new_titles = current_titles - _last_downloads
        new_count = len(new_titles)
    _last_downloads = current_titles

    # ── Write consolidated sensor ──
    if write_l1:
        try:
            state.set(  # noqa: F821
                "sensor.ai_media_upcoming",
                value=str(upcoming_summary)[:255],
                new_attributes={
                    "sonarr": str(sonarr_line),
                    "radarr": str(radarr_line),
                    "recent_downloads": str(recent_summary),
                    "friendly_name": "AI Media Upcoming",
                    "icon": "mdi:television-classic",
                },
            )
        except Exception as exc:
            log.warning("media_promote: sensor update failed: %s", exc)  # noqa: F821

    # ── Write L2 memory ──
    if upcoming_summary:
        await _l2_set(
            key="media_upcoming:summary",
            value=upcoming_summary,
            tags="media,upcoming,l1_promote",
            expiration_days=1,
        )
    if recent_summary:
        await _l2_set(
            key="media_downloads:recent",
            value=recent_summary,
            tags="media,downloads,l1_promote",
            expiration_days=2,
        )

    # ── Update cache ──
    _promote_cache = {
        "date": today_str,
        "fetched_at": time.time(),
    }

    result = {
        "status": "ok",
        "op": "media_promote",
        "upcoming_tv": upcoming_tv,
        "upcoming_movies": upcoming_movies,
        "recent_tv": recent_tv,
        "recent_movies": recent_movies,
        "upcoming_summary": upcoming_summary,
        "sonarr_line": sonarr_line,
        "radarr_line": radarr_line,
        "recent_summary": recent_summary,
        "new_downloads_since_last": new_count,
        "tv_queue": tv_queue,
        "movie_queue": movie_queue,
    }

    _set_result("ok", **{
        "last_run": now.isoformat(timespec="seconds"),
        "upcoming_tv_count": len(upcoming_tv),
        "upcoming_movie_count": len(upcoming_movies),
        "recent_tv_count": len(recent_tv),
        "recent_movie_count": len(recent_movies),
        "tv_queue": tv_queue,
        "movie_queue": movie_queue,
    })

    log.info(  # noqa: F821
        "media_promote: ok — tv=%d movies=%d recent_tv=%d recent_movies=%d "
        "queue=%d+%d new=%d",
        len(upcoming_tv), len(upcoming_movies),
        len(recent_tv), len(recent_movies),
        tv_queue, movie_queue, new_count,
    )

    return result


# ── Test Mode ────────────────────────────────────────────────────────────────

def _is_test_mode() -> bool:
    try:
        return str(
            state.get("input_boolean.ai_test_mode") or "off"  # noqa: F821
        ).lower() == "on"
    except NameError:
        return False


# ── Public Service ──────────────────────────────────────────────────────────

@service(supports_response="only")  # noqa: F821
async def media_promote_now(
    upcoming_days: int = 1,
    download_hours: int = 24,
    write_l1: bool = True,
    force: bool = False,
) -> dict:
    """Promote Radarr/Sonarr data to L2 memory and L1 hot context helpers.

    Parameters:
        upcoming_days: 1 (daily) or 7 (weekly) — upcoming window
        download_hours: 24 (daily) or 168 (weekly) — recent download window
        write_l1: whether to update input_text helpers for hot context
        force: bypass cache TTL
    """
    if _is_test_mode():
        log.info("media_promote [TEST]: would promote Radarr/Sonarr data")  # noqa: F821
        return {"status": "test_mode_skip"}

    try:
        return await _promote_internal(
            upcoming_days=int(upcoming_days),
            download_hours=int(download_hours),
            write_l1=bool(write_l1),
            force=bool(force),
        )
    except Exception as exc:
        log.error("media_promote_now: unhandled: %s", exc)  # noqa: F821
        _set_result("error", error=str(exc))
        return {"status": "error", "error": str(exc)}
