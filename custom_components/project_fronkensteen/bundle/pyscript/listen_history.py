"""Music Listen History — tracks listening sessions with duration.

Logs what gets played on Music Assistant / Spotify players, tracks session
duration, classifies source (track, radio, podcast, audiobook), and writes
completed sessions to L2 memory.  Provides sensor.ai_listen_history_status
for hot-context injection.

Companion blueprint: listen_history.yaml (owns triggers, calls services).
Separate from music_taste.py (taste aggregation, no duration tracking).
"""

import time
from datetime import datetime
from typing import Any

from shared_utils import build_result_entity_name, load_entity_config

# ── Constants ────────────────────────────────────────────────────────────────

RESULT_ENTITY = "sensor.ai_listen_history_status"
KILL_SWITCH = "input_boolean.ai_listen_history_enabled"

# ── Module-Level State ───────────────────────────────────────────────────────

_active_sessions: dict[str, dict] = {}   # entity_id → session dict
_daily_entries: list[dict] = []           # today's logged entries
_daily_index: int = 0                     # session counter for L2 keys
_last_summary_date: str = ""              # date of last rollover
result_entity_name: dict[str, str] = {}   # cached friendly name


# ── Startup ──────────────────────────────────────────────────────────────────

@time_trigger("startup")  # noqa: F821
async def _startup():
    """Clear stale sessions and seed sensor on startup."""
    global _active_sessions, _daily_entries, _last_summary_date, _daily_index
    _active_sessions = {}
    _daily_entries = []
    _last_summary_date = datetime.now().strftime("%Y-%m-%d")
    _daily_index = 0
    _ensure_result_entity_name(force=True)
    _update_sensor("idle")
    log.info("listen_history: startup — ready")  # noqa: F821


# ── Helper Utilities ─────────────────────────────────────────────────────────

def _ensure_result_entity_name(force: bool = False) -> None:
    global result_entity_name
    if force or not result_entity_name:
        result_entity_name = build_result_entity_name(RESULT_ENTITY)


def _is_enabled() -> bool:
    try:
        return str(
            state.get(KILL_SWITCH) or "off"  # noqa: F821
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


# ── Source Classification ────────────────────────────────────────────────────

def _classify_source(
    entity_id: str, media_content_id: str, media_content_type: str,
) -> tuple:
    """Classify media source and content type.

    Returns (media_source, content_type) tuple.
    Priority: TTS → podcast/audiobook → Spotify URI → MA content_id → fallback.
    """
    content_id = (media_content_id or "").lower()
    ct_attr = (media_content_type or "").lower()
    cfg = load_entity_config()
    sp_entity = cfg.get("spotifyplus_entity", "")

    # ── 1. TTS detection (reject before anything else) ──
    if ct_attr == "tts":
        return ("tts", "tts")
    if "/api/tts_proxy/" in content_id or "media-source://tts/" in content_id:
        return ("tts", "tts")

    # ── 2. Podcast / audiobook via media_content_type ──
    if ct_attr in ("podcast", "episode"):
        src = "spotify" if (entity_id == sp_entity or "spotify:" in content_id) else "music_assistant"
        return (src, "podcast")
    if ct_attr == "audiobook":
        src = "spotify" if (entity_id == sp_entity or "spotify:" in content_id) else "music_assistant"
        return (src, "audiobook")

    # ── 3. Spotify URI parsing ──
    if entity_id == sp_entity or "spotify:" in content_id:
        if "spotify:episode:" in content_id or "spotify:show:" in content_id:
            return ("spotify", "podcast")
        if "spotify:audiobook:" in content_id:
            return ("spotify", "audiobook")
        return ("spotify", "track")

    # ── 4. MA content_id prefix matching ──
    if content_id.startswith("library://radio/"):
        return ("radio", "radio")
    if content_id.startswith("library://playlist/"):
        return ("music_assistant", "playlist")
    if content_id.startswith("library://album/"):
        return ("music_assistant", "album")
    if content_id.startswith("library://track/") or content_id.startswith("library://"):
        return ("music_assistant", "track")

    # ── 5. Known MA player fallback ──
    ma_players = cfg.get("music_players") or []
    if entity_id in ma_players:
        return ("music_assistant", "track")

    return ("unknown", "unknown")


def _derive_room(entity_id: str) -> str:
    """Derive human-readable room from entity_id."""
    name = entity_id.replace("media_player.", "")
    if "spotifyplus" in name:
        return "Spotify"
    name = name.replace("_ma", "").replace("_", " ").title()
    return name


# ── L2 Memory Write ─────────────────────────────────────────────────────────

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
        log.warning("listen_history: L2 set failed key=%s: %s", key, exc)  # noqa: F821
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


def _format_listen_entry(session: dict, duration_s: int) -> str:
    """Format a completed listen session into a human-readable string."""
    artist = session.get("media_artist", "Unknown")
    title = session.get("media_title", "Unknown")
    album = session.get("media_album", "")
    source = session.get("media_source", "")
    room = session.get("room", "")
    content_type = session.get("content_type", "")
    dur = _format_duration(duration_s)

    if session.get("is_radio"):
        return f"Listened to radio: {title} ({dur})"

    if content_type == "podcast":
        # artist = show name, title = episode name
        if artist and artist != "Unknown":
            return f"Listened to podcast: {artist} — {title} ({dur})"
        return f"Listened to podcast: {title} ({dur})"

    if content_type == "audiobook":
        # artist = author, title = chapter/book
        if artist and artist != "Unknown":
            return f"Listened to audiobook: {artist} — {title} ({dur})"
        return f"Listened to audiobook: {title} ({dur})"

    # Music track
    parts = [f"Listened to {artist} — {title}"]
    if album:
        parts[0] += f" [{album}]"
    if source and source not in ("unknown", ""):
        parts.append(f"via {source}")
    if room:
        parts.append(f"in {room}")
    parts.append(f"({dur})")
    return " ".join(parts)


def _format_short_entry(session: dict, duration_s: int) -> str:
    """Short format for daily summary and sensor."""
    artist = session.get("media_artist", "Unknown")
    title = session.get("media_title", "Unknown")
    content_type = session.get("content_type", "")
    dur = _format_duration_short(duration_s)

    if session.get("is_radio"):
        return f"Radio: {title} ({dur})"
    if content_type == "podcast":
        if artist and artist != "Unknown":
            return f"Podcast: {artist} — {title} ({dur})"
        return f"Podcast: {title} ({dur})"
    if content_type == "audiobook":
        if artist and artist != "Unknown":
            return f"Audiobook: {artist} — {title} ({dur})"
        return f"Audiobook: {title} ({dur})"
    return f"{artist} — {title} ({dur})"


# ── Sensor Update ────────────────────────────────────────────────────────────

def _build_display_state(state_val: str, session: dict | None) -> str:
    """Build a descriptive state value for logbook display."""
    if state_val != "listening" or not session:
        return state_val
    title = session.get("media_title", "")
    artist = session.get("media_artist", "")
    content_type = session.get("content_type", "")
    if session.get("is_radio"):
        return f"listening to {title}" if title else "listening"
    if content_type == "podcast":
        if artist:
            return f"listening to {artist} — {title}"
        return f"listening to {title}" if title else "listening"
    if content_type == "audiobook":
        if artist:
            return f"listening to {artist} — {title}"
        return f"listening to {title}" if title else "listening"
    if artist and title:
        return f"listening to {artist} — {title}"
    if title:
        return f"listening to {title}"
    return "listening"


def _update_sensor(state_val: str, **extra_attrs: Any) -> None:
    """Update sensor.ai_listen_history_status."""
    _ensure_result_entity_name()
    attrs = dict(result_entity_name)
    icon = "mdi:music" if state_val in ("listening", "paused") else "mdi:music-off"
    attrs["icon"] = icon

    if state_val in ("listening", "paused"):
        session = extra_attrs.get("session")
        if session:
            attrs["current_artist"] = session.get("media_artist", "")
            attrs["current_title"] = session.get("media_title", "")
            attrs["current_album"] = session.get("media_album", "")
            attrs["current_source"] = session.get("media_source", "")
            attrs["current_room"] = session.get("room", "")
            attrs["current_player"] = session.get("player_entity", "")
            attrs["current_content_type"] = session.get("content_type", "")
            started = session.get("start_time", 0)
            attrs["started_at"] = (
                datetime.fromtimestamp(started).isoformat() if started else ""
            )
            elapsed = int(time.time() - started) if started else 0
            attrs["duration_so_far_min"] = max(0, elapsed // 60)
    else:
        # idle — show recent history
        attrs["last_listened"] = extra_attrs.get("last_listened", "")
        attrs["last_listened_at"] = extra_attrs.get("last_listened_at", "")
        attrs["today_count"] = len(_daily_entries)
        attrs["today_total_minutes"] = sum(
            [e.get("duration_s", 0) for e in _daily_entries]
        ) // 60
        attrs["today_entries"] = [
            e.get("short", "") for e in _daily_entries
        ][:15]

    display_state = _build_display_state(state_val, extra_attrs.get("session"))
    try:
        state.set(RESULT_ENTITY, value=display_state, new_attributes=attrs)  # noqa: F821
    except Exception as exc:
        log.warning("listen_history: sensor update failed: %s", exc)  # noqa: F821


# ── Daily Rollover ───────────────────────────────────────────────────────────

async def _check_daily_rollover() -> None:
    """Reset daily entries at midnight, write yesterday's summary to L2."""
    global _daily_entries, _last_summary_date, _daily_index
    today = datetime.now().strftime("%Y-%m-%d")
    if today == _last_summary_date:
        return

    if _daily_entries:
        yesterday = _last_summary_date
        short_list = [e.get("short", "") for e in _daily_entries]
        total_s = sum([e.get("duration_s", 0) for e in _daily_entries])
        summary_val = (
            f"Listened to: {', '.join(short_list)}. "
            f"Total: {_format_duration_short(total_s)}."
        )
        await _l2_set(
            key=f"listen:summary:{yesterday}",
            value=summary_val,
            tags="media,listen_history,daily_summary,l1_promote",
            expiration_days=2,
        )

    _daily_entries = []
    _daily_index = 0
    _last_summary_date = today


# ── Close Active Session (internal) ──────────────────────────────────────────

async def _close_session(
    entity_id: str,
    min_duration: int = 60,
    retention_days: int = 30,
) -> dict:
    """Close an active session: compute duration, threshold check, L2 write.

    Returns dict with logged (bool), duration_s, reason/entry.
    """
    global _daily_index

    session = _active_sessions.pop(entity_id, None)
    if not session:
        return {"logged": False, "duration_s": 0, "reason": "no_session"}

    duration_s = int(time.time() - session.get("start_time", time.time()))

    # Threshold check
    if duration_s < min_duration:
        return {
            "logged": False,
            "duration_s": duration_s,
            "reason": f"below_threshold ({duration_s}s < {min_duration}s)",
        }

    # Format entries
    full_entry = _format_listen_entry(session, duration_s)
    short_entry = _format_short_entry(session, duration_s)
    now = datetime.now()
    time_str = now.strftime("%H:%M")
    full_with_time = f"{full_entry} at {time_str}"

    # L2 write
    await _check_daily_rollover()
    _daily_index += 1
    date_str = now.strftime("%Y-%m-%d")
    l2_key = f"listen:{date_str}:{_daily_index}"

    source = session.get("media_source", "")
    content_type = session.get("content_type", "")
    source_tag = source.lower().replace(" ", "_") if source else ""
    content_tag = content_type.lower().replace(" ", "_") if content_type else ""
    tag_parts = ["media", "listen_history"]
    if source_tag:
        tag_parts.append(source_tag)
    if content_tag and content_tag != source_tag:
        tag_parts.append(content_tag)
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
        "source": source,
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
async def listen_history_start(
    entity_id: str = "",
    media_artist: str = "",
    media_title: str = "",
    media_album: str = "",
    media_content_id: str = "",
    media_content_type: str = "",
    recovered: bool = False,
) -> dict:
    """Begin tracking a listening session.

    Called by the listen_history blueprint on play_start or track_change.
    If a session is already active (track change), the old session is closed.
    """
    if not _is_enabled():
        return {"status": "disabled"}
    if _is_test_mode():
        log.info(  # noqa: F821
            "listen_history [TEST]: start entity=%s artist=%s title=%s",
            entity_id, media_artist, media_title,
        )
        return {"status": "test_mode_skip"}
    if not entity_id:
        return {"status": "error", "error": "entity_id required"}

    # Classify source — reject TTS immediately
    media_source, content_type = _classify_source(
        entity_id, media_content_id, media_content_type,
    )
    if media_source == "tts":
        return {"status": "skipped", "reason": "tts_content"}

    # Close existing session if any (track change / playlist advance)
    if entity_id in _active_sessions:
        min_dur = _helper_int("input_number.ai_listen_min_duration", 60)
        retention = _helper_int("input_number.ai_listen_history_retention_days", 30)
        close_result = await _close_session(entity_id, min_dur, retention)
        if close_result.get("logged"):
            log.info("listen_history: auto-closed previous — %s", close_result.get("entry", ""))  # noqa: F821
        else:
            log.debug(  # noqa: F821
                "listen_history: auto-closed previous — %s",
                close_result.get("reason", "unknown"),
            )

    room = _derive_room(entity_id)
    is_radio = content_type == "radio"

    session = {
        "start_time": time.time(),
        "media_artist": _safe_str(media_artist),
        "media_title": _safe_str(media_title),
        "media_album": _safe_str(media_album),
        "media_source": media_source,
        "content_type": content_type,
        "player_entity": entity_id,
        "room": room,
        "is_radio": is_radio,
        "recovered": bool(recovered),
    }

    _active_sessions[entity_id] = session
    _update_sensor("listening", session=session)

    log.info(  # noqa: F821
        "listen_history: start — %s — %s [%s/%s] in %s%s",
        session["media_artist"] or "(no artist)",
        session["media_title"] or "(no title)",
        media_source,
        content_type,
        room,
        " (recovered)" if recovered else "",
    )

    return {
        "status": "ok",
        "op": "listen_history_start",
        "media_artist": session["media_artist"],
        "media_title": session["media_title"],
        "media_source": media_source,
        "content_type": content_type,
    }


@service(supports_response="optional")  # noqa: F821
async def listen_history_stop(
    entity_id: str = "",
    min_duration: int = 60,
    retention_days: int = 30,
    summary_retention_days: int = 2,
) -> dict:
    """End a listening session, compute duration, log to L2 if above threshold."""
    if not _is_enabled():
        return {"status": "disabled"}
    if _is_test_mode():
        log.info("listen_history [TEST]: stop entity=%s", entity_id)  # noqa: F821
        return {"status": "test_mode_skip"}
    if not entity_id:
        return {"status": "error", "error": "entity_id required"}

    result = await _close_session(
        entity_id,
        min_duration=int(min_duration),
        retention_days=int(retention_days),
    )

    # Multi-player awareness: if another session is still active, show it
    if _active_sessions:
        remaining_id = next(iter(_active_sessions))
        remaining_session = _active_sessions[remaining_id]
        _update_sensor("listening", session=remaining_session)
    else:
        last_listened = result.get("entry", "")
        last_at = datetime.now().isoformat() if result.get("logged") else ""
        _update_sensor("idle", last_listened=last_listened, last_listened_at=last_at)

    if result.get("logged"):
        log.info("listen_history: logged — %s", result.get("entry", ""))  # noqa: F821
    else:
        log.debug("listen_history: skipped — %s", result.get("reason", "unknown"))  # noqa: F821

    result["status"] = "ok"
    result["op"] = "listen_history_stop"
    return result


@service(supports_response="optional")  # noqa: F821
async def listen_history_pause(entity_id: str = "") -> dict:
    """Mark a session as paused (sensor update only, no log)."""
    if not entity_id:
        return {"status": "error", "error": "entity_id required"}
    session = _active_sessions.get(entity_id)
    if not session:
        return {"status": "ok", "op": "listen_history_pause", "note": "no_active_session"}
    _update_sensor("paused", session=session)
    return {"status": "ok", "op": "listen_history_pause"}
