"""Kodi Watch History Tracker — Playback Logging to L2 Memory.

Tracks what is watched on Kodi media players, classifies content
(PVR/movie/series/addon/streaming), measures watch duration, and logs
to L2 memory. Uses template sensors for pre-classified metadata plus
Kodi JSON-RPC for definitive source detection (plugin:// file path).

Blueprint-driven: watch_history.yaml owns triggers and config knobs;
this module provides stateless services for start/pause/stop events.
"""
import time
from aiohttp import ClientSession, ClientTimeout
from datetime import datetime
from typing import Any

from shared_utils import build_result_entity_name

# =============================================================================
# Watch History Tracker
# =============================================================================
#
# Services:
#   pyscript.watch_history_start   — begin tracking a playback session
#   pyscript.watch_history_stop    — end session, compute duration, log to L2
#   pyscript.watch_history_pause   — mark session as paused (no log)
#
# Key design:
#   - Stateless services — blueprint owns triggers
#   - Metadata from template sensors + JSON-RPC source detection
#   - Duration tracked via timestamps in module-level session dict
#   - Minimum duration thresholds filter channel surfing / accidental plays
#   - Daily summary written to L2 for hot context
#
# Data sources:
#   sensor.madteevee_now_playing — pre-classified (live_tv/series/movie/video)
#     with PVR channel, season/episode, cleaned titles
#   Kodi JSON-RPC Player.GetItem — file property for plugin:// source detection
#
# L2 keys:
#   watch:{date}:{index}       — individual watch entry (30d default)
#   watch:summary:{date}       — daily summary (2d default)
#
# Dependencies:
#   - pyscript/memory.py (L2: memory_set)
#   - pyscript/entity_config.yaml (kodi_devices section)
#   - packages/ai_watch_history.yaml (helpers)
#   - template.yaml (sensor.madteevee_now_playing)
# =============================================================================

_KODI_API_TIMEOUT = 5  # seconds

RESULT_ENTITY = "sensor.ai_watch_history_status"

# ── Module-Level State ───────────────────────────────────────────────────────

_active_sessions: dict[str, dict] = {}
_daily_entries: list[dict] = []
_daily_channel_flips: int = 0
_daily_flip_details: list[dict] = []  # [{channel, programme, duration_s}]
_last_summary_date: str = ""
_daily_index: int = 0
result_entity_name: dict[str, str] = {}
_kodi_devices: dict[str, dict] = {}  # entity_id → {"url": str, "auth": str|None}


@pyscript_compile  # noqa: F821
def _b64_encode(text: str) -> str:
    """Base64-encode a string (needs native Python for base64 module)."""
    import base64 as _b64
    return _b64.b64encode(text.encode()).decode()


def _load_kodi_config() -> dict:
    """Read Kodi config entries from HA and build device map."""
    devices = {}
    for entry in hass.config_entries.async_entries("kodi"):  # noqa: F821
        host = entry.data.get("host", "")
        port = entry.data.get("port", 8080)
        ssl = entry.data.get("ssl", False)
        username = entry.data.get("username", "")
        password = entry.data.get("password", "")
        if not host:
            continue
        scheme = "https" if ssl else "http"
        url = f"{scheme}://{host}:{port}/jsonrpc"
        auth = None
        if username and password:
            creds = _b64_encode(f"{username}:{password}")
            auth = f"Basic {creds}"
        device = {"url": url, "auth": auth}
        # Map by name slug (e.g., "madteevee" → media_player.madteevee)
        name = entry.data.get("name", "").lower().replace(" ", "_").replace("-", "_")
        if name:
            devices[f"media_player.{name}"] = device
        # Also map by entry_id as fallback
        devices[entry.entry_id] = device
    return devices

# file path patterns → human-readable source name
# Checked in order: plugin:// prefixes first, then URL keywords
_SOURCE_PREFIX_MAP = [
    ("plugin://plugin.video.youtube", "YouTube"),
    ("plugin://plugin.video.netflix", "Netflix"),
    ("plugin://plugin.video.amazon", "Prime Video"),
    ("plugin://plugin.video.movistarplus", "Movistar+"),
    ("plugin://plugin.video.movistar", "Movistar+"),
    ("plugin://plugin.video.disney", "Disney+"),
    ("plugin://plugin.video.hbomax", "HBO Max"),
    ("pvr://", "PVR"),
]
# Fallback keyword detection for non-plugin:// URLs (e.g., YouTube via inputstream)
_SOURCE_KEYWORD_MAP = [
    ("youtube", "YouTube"),
    ("netflix", "Netflix"),
    ("amazon", "Prime Video"),
    ("movistar", "Movistar+"),
    ("disney", "Disney+"),
]


# ── Kodi JSON-RPC ────────────────────────────────────────────────────────────

async def _kodi_jsonrpc(device: dict, method: str, params: dict = None) -> dict | None:
    """Call Kodi JSON-RPC method via HTTP POST. Returns result or None.

    Args:
        device: {"url": "http://host:port/jsonrpc", "auth": "Basic xxx" or None}
    """
    url = device.get("url", "")
    if not url:
        return None
    try:
        timeout = ClientTimeout(total=_KODI_API_TIMEOUT)
        session = ClientSession(timeout=timeout)
        try:
            payload = {
                "jsonrpc": "2.0",
                "method": method,
                "params": params or {},
                "id": 1,
            }
            headers = {"Content-Type": "application/json"}
            auth_header = device.get("auth")
            if auth_header:
                headers["Authorization"] = auth_header
            resp = await session.post(url, json=payload, headers=headers)
            if resp.status != 200:
                log.warning("watch_history: kodi HTTP %s from %s", resp.status, method)  # noqa: F821
                return None
            data = await resp.json()
            if "error" in data:
                log.warning("watch_history: kodi %s error: %s", method, data["error"].get("message", ""))  # noqa: F821
                return None
            return data.get("result")
        finally:
            await session.close()
    except Exception as exc:
        log.warning("watch_history: kodi %s failed: %s", method, exc)  # noqa: F821
        return None


async def _fetch_kodi_metadata(entity_id: str) -> dict:
    """Fetch rich metadata from Kodi JSON-RPC: source, EPG season/episode.

    Returns dict with:
      media_source: str (YouTube, Netflix, PVR, Library, etc.)
      epg_season: int|None
      epg_episode: int|None
      epg_episode_name: str
      epg_show_title: str
    """
    empty = {
        "media_source": "", "epg_season": None, "epg_episode": None,
        "epg_episode_name": "", "epg_show_title": "",
        "jsonrpc_channel": "", "jsonrpc_channel_number": None,
    }
    device = _kodi_devices.get(entity_id)
    # Fallback: if entity_id not matched, use first available device
    if not device and _kodi_devices:
        device = next(iter(_kodi_devices.values()))
    if not device:
        return empty

    # Get active video player
    players = await _kodi_jsonrpc(device, "Player.GetActivePlayers")
    if not players:
        return empty

    player_id = None
    for p in players:
        if p.get("type") == "video":
            player_id = p.get("playerid")
            break
    if player_id is None:
        return empty

    # Get item with file + channel info
    item_result = await _kodi_jsonrpc(device, "Player.GetItem", {
        "playerid": player_id,
        "properties": ["file", "channel", "channeltype", "channelnumber"],
    })
    if not item_result:
        return empty

    item = item_result.get("item", {})
    file_path = item.get("file", "")
    item_type = item.get("type", "")
    channel_id = item.get("id")

    # ── Detect source from file path ──
    media_source = ""
    if file_path:
        file_lower = file_path.lower()
        # 1. Known plugin:// prefixes
        for prefix, source_name in _SOURCE_PREFIX_MAP:
            if file_lower.startswith(prefix):
                media_source = source_name
                break
        # 2. Generic plugin
        if not media_source and file_lower.startswith("plugin://"):
            parts = file_path.split("/")
            plugin_part = parts[2] if len(parts) > 2 else ""
            plugin_name = plugin_part.replace("plugin.video.", "").replace("plugin.", "").title()
            media_source = plugin_name if plugin_name else "Addon"
        # 3. Keyword fallback (YouTube via inputstream)
        if not media_source:
            for keyword, source_name in _SOURCE_KEYWORD_MAP:
                if keyword in file_lower:
                    media_source = source_name
                    break
        # 4. Local file = library
        if not media_source and item_type in ("movie", "episode"):
            media_source = "Library"

    # PVR channels have no file path — detect from item type
    if not media_source and item_type == "channel":
        media_source = "PVR"

    result = dict(empty)
    result["media_source"] = media_source

    # ── Enrich PVR channels with JSON-RPC channel name + EPG data ──
    if item_type == "channel":
        result["jsonrpc_channel"] = item.get("channel", "")
        result["jsonrpc_channel_number"] = item.get("channelnumber")
        if channel_id:
            epg_data = await _fetch_active_epg(device, channel_id)
            if epg_data:
                result["epg_season"] = epg_data.get("seasonnum")
                result["epg_episode"] = epg_data.get("episodenum")
                result["epg_episode_name"] = epg_data.get("episodename", "")
                result["epg_show_title"] = epg_data.get("title", "")

    return result


async def _fetch_active_epg(device: dict, channel_id: int) -> dict | None:
    """Fetch the currently active EPG broadcast for a PVR channel.

    Returns the active broadcast dict or None.
    Linear scan in batches of 30 — typically finds the active entry in 1-3 requests.
    """
    _EPG_PROPS = [
        "title", "episodename", "episodenum", "seasonnum",
        "isseries", "isactive", "starttime", "endtime",
    ]
    # Get total count
    count_result = await _kodi_jsonrpc(device, "PVR.GetBroadcasts", {
        "channelid": channel_id,
        "properties": ["isactive"],
        "limits": {"start": 0, "end": 1},
    })
    if not count_result:
        return None
    total = count_result.get("limits", {}).get("total", 0)
    if total == 0:
        return None

    # Scan in batches of 30
    batch_size = 30
    for start in range(0, total, batch_size):
        end = min(start + batch_size, total)
        batch = await _kodi_jsonrpc(device, "PVR.GetBroadcasts", {
            "channelid": channel_id,
            "properties": _EPG_PROPS,
            "limits": {"start": start, "end": end},
        })
        if not batch:
            return None
        for b in batch.get("broadcasts", []):
            if b.get("isactive"):
                return b

    return None


# ── Startup ──────────────────────────────────────────────────────────────────

@time_trigger("startup")  # noqa: F821
async def _startup():
    """Clear stale sessions, load config, and seed sensor on startup."""
    global _active_sessions, _daily_entries, _daily_channel_flips, _daily_flip_details, _last_summary_date, _daily_index, _kodi_devices
    _active_sessions = {}
    _daily_entries = []
    _daily_channel_flips = 0
    _daily_flip_details = []
    _last_summary_date = datetime.now().strftime("%Y-%m-%d")
    _daily_index = 0

    # Load Kodi JSON-RPC config from HA config entries (same pattern as media_promote.py)
    _kodi_devices = {}
    try:
        _kodi_devices = _load_kodi_config()
        log.info(  # noqa: F821
            "watch_history: loaded %d kodi device(s): %s",
            len(_kodi_devices),
            ", ".join([k for k in _kodi_devices if k.startswith("media_player.")]),
        )
    except Exception as exc:
        log.warning("watch_history: kodi config load failed: %s", exc)  # noqa: F821

    _ensure_result_entity_name(force=True)
    _update_sensor("idle")
    log.info("watch_history: startup — ready")  # noqa: F821


# ── Helper Utilities ─────────────────────────────────────────────────────────

def _ensure_result_entity_name(force: bool = False) -> None:
    global result_entity_name
    if force or not result_entity_name:
        result_entity_name = build_result_entity_name(RESULT_ENTITY)


def _is_enabled() -> bool:
    try:
        return str(
            state.get("input_boolean.ai_watch_history_enabled") or "off"  # noqa: F821
        ).lower() == "on"
    except NameError:
        return False


def _is_test_mode() -> bool:
    try:
        return str(
            state.get("input_boolean.ai_test_mode") or "off"  # noqa: F821
        ).lower() == "on"
    except NameError:
        return False


def _helper_int(entity_id: str, default: int) -> int:
    try:
        val = state.get(entity_id)  # noqa: F821
        if val and val not in ("unknown", "unavailable", ""):
            return int(float(val))
    except (TypeError, ValueError, NameError):
        pass
    return default


def _safe_str(val: Any) -> str:
    """Convert to string, returning '' for None/unknown/unavailable."""
    if val is None:
        return ""
    s = str(val).strip()
    if s.lower() in ("none", "unknown", "unavailable"):
        return ""
    return s


def _safe_int(val: Any) -> int | None:
    """Convert to int, returning None for empty/invalid."""
    if val is None:
        return None
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return None


# ── L2 Memory Write ──────────────────────────────────────────────────────────

async def _l2_set(
    key: str, value: str, tags: str,
    scope: str = "user", expiration_days: int = 30,
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
        log.warning("watch_history: L2 set failed key=%s: %s", key, exc)  # noqa: F821
        return False


# ── Formatting ───────────────────────────────────────────────────────────────

def _format_duration(seconds: int) -> str:
    """Format seconds into human-readable duration."""
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} min"
    hours = minutes // 60
    remaining = minutes % 60
    if remaining == 0:
        return f"{hours}h"
    return f"{hours}h {remaining}min"


def _format_duration_short(seconds: int) -> str:
    """Short duration for daily summary."""
    minutes = max(1, seconds // 60)
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    remaining = minutes % 60
    if remaining == 0:
        return f"{hours}h"
    return f"{hours}h{remaining}m"


def _format_watch_entry(session: dict, duration_s: int) -> str:
    """Format a completed watch session into a human-readable string."""
    cat = session.get("media_category", "")
    title = session.get("media_title", "Unknown")
    channel = session.get("pvr_channel", "")
    show = session.get("series_title", "")
    source = session.get("media_source", "")
    season = session.get("season")
    episode = session.get("episode")
    dur = _format_duration(duration_s)

    ep_name = session.get("epg_episode_name", "")

    if cat == "live_tv" and channel:
        # Build rich PVR entry: "Watched Cartoon Network — Family Guy S06E01 'Blue Harvest' (22 min)"
        programme = show if show else (session.get("pvr_programme", "") or title)
        ep_str = ""
        s = _safe_int(season)
        e = _safe_int(episode)
        if s is not None and e is not None:
            ep_str = f" S{s:02d}E{e:02d}"
        name_str = f" '{ep_name}'" if ep_name else ""
        return f"Watched {channel} — {programme}{ep_str}{name_str} ({dur})"
    elif cat == "series" and show:
        ep_str = ""
        s = _safe_int(season)
        e = _safe_int(episode)
        if s is not None and e is not None:
            ep_str = f" S{s:02d}E{e:02d}"
        return f"Watched {show}{ep_str} ({dur})"
    elif cat == "movie":
        src = f" on {source}" if source else ""
        return f"Watched {title}{src} ({dur})"
    elif source:
        return f"Watched {title} on {source} ({dur})"
    else:
        return f"Watched {title} ({dur})"


def _format_short_entry(session: dict, duration_s: int) -> str:
    """Short format for daily summary and sensor."""
    cat = session.get("media_category", "")
    title = session.get("media_title", "Unknown")
    channel = session.get("pvr_channel", "")
    show = session.get("series_title", "")
    source = session.get("media_source", "")
    season = session.get("season")
    episode = session.get("episode")
    dur = _format_duration_short(duration_s)

    ep_name_s = session.get("epg_episode_name", "")

    if cat == "live_tv" and channel:
        programme = show if show else title
        s = _safe_int(season)
        e = _safe_int(episode)
        if s is not None and e is not None:
            return f"{channel} — {programme} S{s:02d}E{e:02d} ({dur})"
        return f"{channel} — {programme} ({dur})"
    elif cat == "series" and show:
        s = _safe_int(season)
        e = _safe_int(episode)
        if s is not None and e is not None:
            return f"{show} S{s:02d}E{e:02d} ({dur})"
        return f"{show} ({dur})"
    elif cat == "movie":
        return f"{title} ({dur})"
    elif source:
        return f"{source}: {title} ({dur})"
    else:
        return f"{title} ({dur})"


# ── Sensor Update ────────────────────────────────────────────────────────────

def _update_sensor(state_val: str, **extra_attrs: Any) -> None:
    """Update sensor.ai_watch_history_status."""
    _ensure_result_entity_name()
    attrs = dict(result_entity_name)
    icon = "mdi:television-play" if state_val == "watching" else "mdi:television-classic"
    attrs["icon"] = icon

    if state_val in ("watching", "paused"):
        session = extra_attrs.get("session")
        if session:
            attrs["current_category"] = session.get("media_category", "")
            attrs["current_title"] = session.get("media_title", "")
            attrs["current_source"] = session.get("media_source", "")
            attrs["current_series"] = session.get("series_title", "")
            attrs["current_season"] = session.get("season", "")
            attrs["current_episode"] = session.get("episode", "")
            attrs["current_episode_name"] = session.get("epg_episode_name", "")
            attrs["current_channel"] = session.get("pvr_channel", "")
            attrs["current_show"] = session.get("series_title", "")
            started = session.get("start_time", 0)
            attrs["started_at"] = datetime.fromtimestamp(started).isoformat() if started else ""
            elapsed = int(time.time() - started) if started else 0
            attrs["duration_so_far_min"] = max(0, elapsed // 60)
    else:
        # idle / error — show recent history
        attrs["last_watched"] = extra_attrs.get("last_watched", "")
        attrs["last_watched_at"] = extra_attrs.get("last_watched_at", "")
        attrs["today_count"] = len(_daily_entries)
        attrs["today_total_minutes"] = sum(
            [e.get("duration_s", 0) for e in _daily_entries]
        ) // 60
        attrs["today_entries"] = [e.get("short", "") for e in _daily_entries][:10]
        attrs["today_channel_flips"] = _daily_channel_flips
        if _daily_flip_details:
            attrs["today_flip_channels"] = [
                f"{f.get('channel', '?')} — {f.get('programme', '?')} ({f.get('duration_s', 0)}s)"
                for f in _daily_flip_details
            ][:15]

    try:
        state.set(RESULT_ENTITY, value=state_val, new_attributes=attrs)  # noqa: F821
    except Exception as exc:
        log.warning("watch_history: sensor update failed: %s", exc)  # noqa: F821


# ── Daily Rollover ───────────────────────────────────────────────────────────

async def _check_daily_rollover() -> None:
    """Reset daily entries at midnight, write yesterday's summary to L2."""
    global _daily_entries, _last_summary_date, _daily_index
    today = datetime.now().strftime("%Y-%m-%d")
    if today == _last_summary_date:
        return

    # Write yesterday's summary if there were entries or flips
    if _daily_entries or _daily_channel_flips > 0:
        yesterday = _last_summary_date
        parts = []
        if _daily_entries:
            short_list = [e.get("short", "") for e in _daily_entries]
            total_s = sum([e.get("duration_s", 0) for e in _daily_entries])
            parts.append(
                f"Watched: {', '.join(short_list)}. "
                f"Total: {_format_duration_short(total_s)}."
            )
        if _daily_channel_flips > 0:
            flip_total_s = sum([f.get("duration_s", 0) for f in _daily_flip_details])
            flip_channels = [f.get("channel", "?") for f in _daily_flip_details]
            unique_channels = list(dict.fromkeys(flip_channels))  # dedupe, preserve order
            parts.append(
                f"Flipped through {_daily_channel_flips} channels "
                f"({_format_duration_short(flip_total_s)} total): "
                f"{', '.join(unique_channels[:8])}."
            )
        summary_val = " ".join(parts)
        await _l2_set(
            key=f"watch:summary:{yesterday}",
            value=summary_val,
            tags="media,watch_history,daily_summary,l1_promote",
            expiration_days=2,
        )

    _daily_entries = []
    _daily_channel_flips = 0
    _daily_flip_details = []
    _daily_index = 0
    _last_summary_date = today


# ── Close Active Session (internal) ─────────────────────────────────────────

async def _close_session(
    entity_id: str,
    min_duration_pvr: int = 180,
    min_duration_content: int = 120,
    retention_days: int = 30,
) -> dict:
    """Close an active session: compute duration, threshold check, L2 write.

    Returns dict with logged (bool), duration_s, reason.
    """
    global _daily_index

    session = _active_sessions.pop(entity_id, None)
    if not session:
        return {"logged": False, "duration_s": 0, "reason": "no_session"}

    duration_s = int(time.time() - session.get("start_time", time.time()))
    cat = session.get("media_category", "")

    # Threshold check
    threshold = min_duration_pvr if cat == "live_tv" else min_duration_content
    if duration_s < threshold:
        # Track channel flips for PVR
        if cat == "live_tv":
            global _daily_channel_flips, _daily_flip_details
            _daily_channel_flips += 1
            _daily_flip_details.append({
                "channel": session.get("pvr_channel", ""),
                "programme": session.get("pvr_programme", session.get("media_title", "")),
                "duration_s": duration_s,
            })
        return {
            "logged": False,
            "duration_s": duration_s,
            "reason": f"below_threshold ({duration_s}s < {threshold}s)",
            "channel_flip": cat == "live_tv",
        }

    # Format entries
    full_entry = _format_watch_entry(session, duration_s)
    short_entry = _format_short_entry(session, duration_s)
    now = datetime.now()
    time_str = now.strftime("%H:%M")
    full_with_time = f"{full_entry} at {time_str}"

    # L2 write
    await _check_daily_rollover()
    _daily_index += 1
    date_str = now.strftime("%Y-%m-%d")
    l2_key = f"watch:{date_str}:{_daily_index}"
    source = session.get("media_source", "")
    source_tag = source.lower().replace(" ", "_").replace("+", "_plus") if source else ""
    tag_parts = ["media", "watch_history"]
    if cat:
        tag_parts.append(cat)
    if source_tag:
        tag_parts.append(source_tag)
    l2_tags = ",".join(tag_parts)

    success = await _l2_set(
        key=l2_key,
        value=full_with_time,
        tags=l2_tags,
        expiration_days=retention_days,
    )

    # Track for daily summary
    _daily_entries.append({
        "short": short_entry,
        "full": full_with_time,
        "duration_s": duration_s,
        "category": cat,
    })

    return {
        "logged": True,
        "l2_success": success,
        "duration_s": duration_s,
        "duration": _format_duration(duration_s),
        "entry": full_with_time,
        "l2_key": l2_key,
    }


# ── Services ─────────────────────────────────────────────────────────────────

@service(supports_response="optional")  # noqa: F821
async def watch_history_start(
    entity_id: str = "",
    media_category: str = "",
    media_title: str = "",
    series_title: str = "",
    season: str = "",
    episode: str = "",
    pvr_channel: str = "",
    pvr_channel_number: str = "",
    pvr_programme: str = "",
    recovered: bool = False,
) -> dict:
    """Begin tracking a playback session.

    Called by the watch_history blueprint on play_start trigger.
    If a session is already active (playlist/channel change), the old
    session is closed first with threshold checks.
    """
    if not _is_enabled():
        return {"status": "disabled"}
    if _is_test_mode():
        log.info(  # noqa: F821
            "watch_history [TEST]: start entity=%s title=%s cat=%s",
            entity_id, media_title, media_category,
        )
        return {"status": "test_mode_skip"}

    if not entity_id:
        return {"status": "error", "error": "entity_id required"}

    # Close existing session if any (playlist/channel change — EC-4)
    if entity_id in _active_sessions:
        min_pvr = _helper_int("input_number.ai_watch_min_duration_pvr", 180)
        min_content = _helper_int("input_number.ai_watch_min_duration_content", 120)
        retention = _helper_int("input_number.ai_watch_history_retention_days", 30)
        close_result = await _close_session(
            entity_id, min_pvr, min_content, retention,
        )
        log.info(  # noqa: F821
            "watch_history: auto-closed previous session — %s",
            close_result.get("reason", "logged") if not close_result.get("logged") else close_result.get("entry", ""),
        )

    # Fetch rich metadata via JSON-RPC (source + EPG)
    kodi_meta = await _fetch_kodi_metadata(entity_id)
    media_source = kodi_meta.get("media_source", "")

    # Build session — EPG data enriches PVR entries with season/episode
    _season = _safe_str(season)
    _episode = _safe_str(episode)
    _series = _safe_str(series_title)
    epg_season = kodi_meta.get("epg_season")
    epg_episode = kodi_meta.get("epg_episode")
    epg_ep_name = kodi_meta.get("epg_episode_name", "")
    epg_show = kodi_meta.get("epg_show_title", "")

    # Prefer EPG data over HA attributes for PVR
    if epg_season is not None and epg_season > 0:
        _season = str(epg_season)
    if epg_episode is not None and epg_episode > 0:
        _episode = str(epg_episode)
    if epg_show:
        _series = epg_show
    epg_name = epg_ep_name

    session = {
        "start_time": time.time(),
        "media_category": _safe_str(media_category),
        "media_title": _safe_str(media_title),
        "series_title": _series,
        "season": _season,
        "episode": _episode,
        "epg_episode_name": epg_name,
        "pvr_channel": _safe_str(pvr_channel) or kodi_meta.get("jsonrpc_channel", ""),
        "pvr_channel_number": _safe_int(pvr_channel_number) or kodi_meta.get("jsonrpc_channel_number"),
        "pvr_programme": _safe_str(pvr_programme),
        "media_source": media_source,
        "recovered": bool(recovered),
    }

    _active_sessions[entity_id] = session
    _update_sensor("watching", session=session)

    log.info(  # noqa: F821
        "watch_history: start — %s %s [%s]%s%s",
        session["media_category"],
        session["media_title"],
        media_source or "unknown",
        f" S{_season}E{_episode}" if _season and _episode else "",
        " (recovered)" if recovered else "",
    )

    return {
        "status": "ok",
        "op": "watch_history_start",
        "media_category": session["media_category"],
        "media_title": session["media_title"],
    }


@service(supports_response="optional")  # noqa: F821
async def watch_history_stop(
    entity_id: str = "",
    min_duration_pvr: int = 180,
    min_duration_content: int = 120,
    retention_days: int = 30,
    summary_retention_days: int = 2,
) -> dict:
    """End a playback session, compute duration, log to L2 if above threshold.

    Called by the watch_history blueprint on play_stop trigger.
    """
    if not _is_enabled():
        return {"status": "disabled"}
    if _is_test_mode():
        log.info("watch_history [TEST]: stop entity=%s", entity_id)  # noqa: F821
        return {"status": "test_mode_skip"}

    if not entity_id:
        return {"status": "error", "error": "entity_id required"}

    result = await _close_session(
        entity_id,
        min_duration_pvr=int(min_duration_pvr),
        min_duration_content=int(min_duration_content),
        retention_days=int(retention_days),
    )

    # Update sensor to idle with recent history
    last_watched = result.get("entry", "")
    last_at = datetime.now().isoformat() if result.get("logged") else ""

    _update_sensor(
        "idle",
        last_watched=last_watched,
        last_watched_at=last_at,
    )

    if result.get("logged"):
        log.info(  # noqa: F821
            "watch_history: logged — %s", result.get("entry", ""),
        )
    else:
        log.debug(  # noqa: F821
            "watch_history: skipped — %s", result.get("reason", "unknown"),
        )

    result["status"] = "ok"
    result["op"] = "watch_history_stop"
    return result


@service(supports_response="optional")  # noqa: F821
async def watch_history_pause(entity_id: str = "") -> dict:
    """Mark a session as paused (sensor update only, no log).

    Called by the watch_history blueprint on play_pause trigger.
    Session remains active — will be logged on eventual stop.
    """
    if not entity_id:
        return {"status": "error", "error": "entity_id required"}

    session = _active_sessions.get(entity_id)
    if not session:
        return {"status": "ok", "op": "watch_history_pause", "note": "no_active_session"}

    _update_sensor("paused", session=session)
    return {"status": "ok", "op": "watch_history_pause"}
