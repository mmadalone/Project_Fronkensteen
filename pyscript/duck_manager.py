"""Duck Manager — Unified Volume Ducking Engine.

Reference-counted session-based volume ducking for media players. The first
session captures current volumes and ducks; the last session ending restores.
Multiple sources (satellite wake, TTS queue, external callers) can overlap
safely. Crash recovery via JSON snapshot file; watchdog force-restores
stale sessions.
"""
import asyncio
import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from shared_utils import build_result_entity_name, load_entity_config

# =============================================================================
# Duck Manager — Unified Volume Ducking Engine
# =============================================================================
# Reference-counted session-based ducking. First session captures + ducks.
# Last session ending restores. Multiple sources can overlap safely.
#
# Sources:
#   satellite  — @state_trigger on assist_satellite entities
#   tts_queue  — via duck_manager_duck/restore service calls
#   external   — any caller via duck_manager_duck service
#
# Duck group + announcement players + satellites + vsync zones configured
# in entity_config.yaml. Crash recovery via JSON snapshot file.
# Watchdog force-restores stale sessions.
# =============================================================================

RESULT_ENTITY = "sensor.ai_duck_manager_status"
SNAPSHOT_FILE = Path("/config/pyscript/duck_snapshot.json")

# ── State ─────────────────────────────────────────────────────────────────────
_satellite_triggers = []       # holds factory-created trigger references (keep alive)
_sessions: dict = {}           # session_id → {source, detail, created_at}
_sessions_lock = asyncio.Lock()
_volume_snapshot: dict = {}    # entity_id → original_volume
_was_playing: dict = {}        # I-39: entity_id → True (media paused during duck)
_user_adjusted_during_duck: set = set()  # I-22: entities user adjusted while ducked
_lock = threading.Lock()
_sat_sessions: dict = {}       # satellite_entity → session_id
_last_duck_event: dict = {}    # {source, detail, duck_time, restore_time, duration_s, sessions}
result_entity_name: dict = {}


def _ensure_result_entity_name(force: bool = False) -> None:
    global result_entity_name
    if force or not result_entity_name:
        result_entity_name = build_result_entity_name(RESULT_ENTITY)


def _set_result(state_value: str = "ok", **attrs: Any) -> None:
    _ensure_result_entity_name()
    attrs.update(result_entity_name)
    # Include last duck event attributes when idle
    if state_value == "idle" and _last_duck_event:
        attrs["last_duck_source"] = _last_duck_event.get("source", "")
        attrs["last_duck_detail"] = _last_duck_event.get("detail", "")
        attrs["last_duck_time"] = _last_duck_event.get("duck_time_iso", "")
        attrs["last_duck_duration_s"] = _last_duck_event.get("duration_s", 0)
        attrs["last_duck_sessions"] = _last_duck_event.get("sessions", 0)
    try:
        state.set(RESULT_ENTITY, value=state_value, new_attributes=attrs)  # noqa: F821
    except Exception as exc:
        log.warning(f"duck_manager: state.set failed: {exc}")  # noqa: F821


# ── Typed Helper Readers ──────────────────────────────────────────────────────

def _helper_float(entity_id: str, default: float) -> float:
    try:
        val = state.get(entity_id)  # noqa: F821
        if val and val not in ("unknown", "unavailable", ""):
            return float(val)
    except Exception:
        pass
    return default


def _helper_int(entity_id: str, default: int) -> int:
    try:
        val = state.get(entity_id)  # noqa: F821
        if val and val not in ("unknown", "unavailable", ""):
            return int(float(val))
    except Exception:
        pass
    return default


# ── Helper Getters ────────────────────────────────────────────────────────────

def _is_enabled() -> bool:
    try:
        return state.get("input_boolean.ai_duck_manager_enabled") != "off"  # noqa: F821
    except Exception:
        return True


def _get_duck_group() -> list:
    cfg = load_entity_config()
    speakers = cfg.get("duck", {}).get("group", [])
    if not speakers:
        log.error("duck_manager: duck group config is empty")  # noqa: F821
    return speakers


def _get_announcement_players() -> list:
    cfg = load_entity_config()
    speakers = cfg.get("duck", {}).get("announcement_players", [])
    if not speakers:
        log.error("duck_manager: announcement players config is empty")  # noqa: F821
    return speakers


def _get_duck_satellites() -> list:
    cfg = load_entity_config()
    satellites = cfg.get("duck", {}).get("satellites", [])
    if not satellites:
        log.error("duck_manager: duck satellites config is empty")  # noqa: F821
    return satellites


def _get_duck_volume() -> float:
    return _helper_float("input_number.ai_duck_volume", 0.1)


def _get_announcement_volume() -> float:
    return _helper_float("input_number.ai_duck_announce_volume", 0.5)


def _get_watchdog_timeout() -> float:
    return float(_helper_int("input_number.ai_duck_watchdog_timeout", 120))


def _get_restore_mode() -> str:
    try:
        val = state.get("input_select.ai_tts_restore_mode")  # noqa: F821
        if val in ("fixed", "dynamic"):
            return val
    except Exception:
        pass
    return "dynamic"


def _get_restore_fixed_delay() -> float:
    return _helper_float("input_number.ai_duck_restore_delay", 0.5)


def _get_restore_timeout() -> float:
    return _helper_float("input_number.ai_duck_restore_timeout", 25.0)


def _get_restore_post_buffer() -> float:
    """Post-playback buffer: HA entity goes idle before ESP finishes audio."""
    return _helper_float("input_number.ai_duck_post_buffer", 5.0)


def _get_duck_behavior() -> str:
    """I-39: Get duck behavior mode — volume, pause, or both."""
    try:
        val = state.get("input_select.ai_duck_behavior")  # noqa: F821
        if val in ("volume", "pause", "both"):
            return val
    except Exception:
        pass
    return "volume"


def _get_pre_delay_ms() -> int:
    """I-21: Get pre-delay in ms before first duck."""
    try:
        val = int(float(state.get("input_number.ai_duck_pre_delay_ms") or 0))  # noqa: F821
        if 0 <= val <= 2000:
            return val
    except Exception:
        pass
    return 0


def _get_allow_manual_override() -> bool:
    """I-22: Whether manual volume changes during duck are respected."""
    try:
        return state.get("input_boolean.ai_duck_allow_manual_override") != "off"  # noqa: F821
    except Exception as exc:
        log.warning("duck_manager: _ducking_active check failed: %s", exc)  # noqa: F821
        return True


# ── Volume Buddy Fallback ────────────────────────────────────────────────────


def _get_volume_buddies() -> dict:
    """Derive buddy map from vsync_zones in entity_config.yaml.

    For each vsync group, Alexa devices are unreliable reporters.
    Their buddy is the first non-Alexa member in the same group.
    """
    cfg = load_entity_config()
    vsync = cfg.get("vsync_zones", {})
    buddies = {}
    for group_name, zone_cfg in vsync.items():
        players = zone_cfg.get("players", [])
        alexa_list = zone_cfg.get("alexa", [])
        if not players:
            log.error(  # noqa: F821
                f"duck_manager: vsync zone {group_name} players config is empty"
            )
            continue
        alexa_set = set(alexa_list)
        # First non-Alexa player is the buddy for all Alexa devices in this group
        buddy = None
        for p in players:
            if p not in alexa_set:
                buddy = p
                break
        if buddy:
            for a in alexa_set:
                buddies[a] = buddy
    if buddies:
        log.info(f"duck_manager: volume buddies resolved: {buddies}")  # noqa: F821
    else:
        log.warning("duck_manager: no volume buddies resolved from vsync config")  # noqa: F821
    return buddies


def _get_default_volume() -> float:
    try:
        val = float(state.get("input_number.ai_duck_default_volume") or 0.5)  # noqa: F821
        if 0 <= val <= 1:
            return val
    except Exception:
        pass
    return 0.5


# ── Volume Helpers ────────────────────────────────────────────────────────────

def _capture_volume(entity_id: str, guard_ducked: bool = True):
    """Read current volume_level. Returns float or None.

    If guard_ducked is True and the captured volume is at or below the
    configured duck level, return the default fallback volume instead —
    the speaker is almost certainly already ducked from a prior cycle.
    """
    try:
        attrs = state.getattr(entity_id)  # noqa: F821
        if attrs and "volume_level" in attrs:
            vol = float(attrs["volume_level"])
            if guard_ducked and vol <= _get_duck_volume():
                default = _get_default_volume()
                log.info(  # noqa: F821
                    f"duck_manager: {entity_id} volume {vol:.2f} "
                    f"<= duck level {_get_duck_volume():.2f} — "
                    f"using default {default:.2f} (likely already ducked)"
                )
                return default
            return vol
    except Exception:
        pass
    return None


def _is_playing(entity_id: str) -> bool:
    try:
        return state.get(entity_id) == "playing"  # noqa: F821
    except Exception:
        return False


def _get_satellite_name(entity_id: str) -> str:
    """Derive a short name from satellite entity for logging."""
    try:
        attrs = state.getattr(entity_id)  # noqa: F821
        name = (attrs or {}).get("friendly_name", "")
        if name:
            name_lower = name.lower()
            for persona in ["rick", "quark", "deepee", "kramer"]:
                if persona in name_lower:
                    return persona
    except Exception:
        pass
    return entity_id.split(".")[-1][:20]


# ── Snapshot Persistence (file-based) ─────────────────────────────────────────

@pyscript_executor  # noqa: F821
def _save_snapshot_sync(snapshot: dict, path: str) -> bool:
    import json as _json
    try:
        with open(path, "w") as f:
            f.write(_json.dumps(snapshot))
        return True
    except Exception:
        return False


@pyscript_executor  # noqa: F821
def _load_snapshot_sync(path: str) -> dict:
    import json as _json
    try:
        with open(path, "r") as f:
            return _json.loads(f.read())
    except Exception:
        return {}


@pyscript_executor  # noqa: F821
def _clear_snapshot_sync(path: str) -> None:
    import os
    try:
        os.remove(path)
    except Exception:
        pass


async def _save_snapshot():
    data = {"volumes": dict(_volume_snapshot), "was_playing": dict(_was_playing)}
    _save_snapshot_sync(data, str(SNAPSHOT_FILE))


async def _load_snapshot():
    return _load_snapshot_sync(str(SNAPSHOT_FILE))


async def _clear_snapshot():
    _clear_snapshot_sync(str(SNAPSHOT_FILE))


# ── Core Duck / Restore ───────────────────────────────────────────────────────

async def _capture_and_duck(skip_duck_entity: str = "") -> None:
    """Capture volumes and duck all players. Called on first session only.

    I-39: Also pauses playing media if duck_behavior is 'pause' or 'both'.
    skip_duck_entity: entity to exclude from ducking (e.g. TTS target speaker
    that supports native announce ducking — still captured for restore).
    """
    global _volume_snapshot, _last_duck_event, _was_playing

    duck_group = _get_duck_group()
    announce_players = _get_announcement_players()
    duck_vol = _get_duck_volume()
    announce_vol = _get_announcement_volume()
    behavior = _get_duck_behavior()

    if not duck_group and not announce_players:
        log.warning("duck_manager: no duck group or announcement players configured")  # noqa: F821
        return

    # Set ducking flag FIRST — blocks volume_sync before any volume changes
    try:
        state.set("sensor.ai_ducking_flag", "on",  # noqa: F821
                  new_attributes={"icon": "mdi:duck", "friendly_name": "AI Ducking Flag"})
    except Exception:
        pass

    # Clear I-22 user adjustment tracking for new duck session
    _user_adjusted_during_duck.clear()

    announce_set = set(announce_players)

    # Capture current volumes (first capture wins — don't overwrite)
    all_players = list(duck_group)
    for p in announce_players:
        if p not in all_players:
            all_players.append(p)

    # ── Pass 1: Primary capture ──
    # Capture volumes outside lock, batch-write under lock
    pass1_captures = {}
    for entity_id in all_players:
        if entity_id not in _volume_snapshot:
            vol = _capture_volume(entity_id)
            if vol is not None:
                pass1_captures[entity_id] = vol
    with _lock:
        for entity_id, vol in pass1_captures.items():
            if entity_id not in _volume_snapshot:
                _volume_snapshot[entity_id] = vol

    # ── Pass 2: Buddy/default fallback for uncaptured devices ──
    buddies = _get_volume_buddies()
    default_vol = _get_default_volume()
    pass2_captures = {}
    pass2_log = []  # (level, msg) — log outside lock
    for entity_id in all_players:
        with _lock:
            already_captured = entity_id in _volume_snapshot
        if already_captured:
            continue
        # Try buddy's already-captured volume
        buddy_id = buddies.get(entity_id)
        if buddy_id:
            with _lock:
                buddy_vol_from_snapshot = _volume_snapshot.get(buddy_id)
            if buddy_vol_from_snapshot is not None:
                pass2_captures[entity_id] = buddy_vol_from_snapshot
                pass2_log.append(("info",
                    f"duck_manager: {entity_id} — using buddy volume "
                    f"{buddy_vol_from_snapshot:.2f} from {buddy_id}"
                ))
                continue
        # Try capturing buddy directly (buddy may not be in duck group)
        if buddy_id:
            buddy_vol = _capture_volume(buddy_id)
            if buddy_vol is not None:
                pass2_captures[entity_id] = buddy_vol
                pass2_log.append(("info",
                    f"duck_manager: {entity_id} — using buddy volume "
                    f"{buddy_vol:.2f} from {buddy_id}"
                ))
                continue
        # Last resort: default volume
        pass2_captures[entity_id] = default_vol
        pass2_log.append(("warning",
            f"duck_manager: {entity_id} — no volume captured, "
            f"no buddy available — using default {default_vol:.2f}"
        ))
    with _lock:
        _volume_snapshot.update(pass2_captures)
    for level, msg in pass2_log:
        if level == "info":
            log.info(msg)  # noqa: F821
        else:
            log.warning(msg)  # noqa: F821

    # Diagnostic: log full snapshot after capture
    with _lock:
        snap_copy = dict(_volume_snapshot)
    log.warning(  # noqa: F821
        f"duck_manager: capture complete — skip={skip_duck_entity or 'none'}, "
        f"snapshot={snap_copy}"
    )

    # ── I-39: Pause playing media if behavior is 'pause' or 'both' ──
    paused_count = 0
    if behavior in ("pause", "both"):
        for entity_id in duck_group:
            if entity_id in announce_set:
                continue
            if _is_playing(entity_id):
                try:
                    await service.call("media_player", "media_pause",  # noqa: F821
                                       entity_id=entity_id)
                    _was_playing[entity_id] = True
                    paused_count += 1
                except Exception as exc:
                    log.warning(f"duck_manager: pause {entity_id} failed: {exc}")  # noqa: F821

    # Duck: set all duck group players (except announcement) to duck volume
    # Guard: skip players whose volume capture failed (no snapshot = no restore)
    # I-39: skip volume duck if behavior is 'pause' only
    # Skip TTS target speaker — it handles ducking natively via announce mode
    ducked_count = 0
    if behavior in ("volume", "both"):
        for entity_id in duck_group:
            if entity_id in announce_set:
                continue
            if skip_duck_entity and entity_id == skip_duck_entity:
                log.info(  # noqa: F821
                    f"duck_manager: skipping duck for {entity_id} — "
                    f"TTS target with native announce"
                )
                continue
            if entity_id not in _volume_snapshot:
                log.warning(f"duck_manager: skipping duck for {entity_id} — no volume captured")  # noqa: F821
                continue
            try:
                await service.call("media_player", "volume_set",  # noqa: F821
                                   entity_id=entity_id, volume_level=duck_vol)
                ducked_count += 1
            except Exception as exc:
                log.warning(f"duck_manager: duck {entity_id} failed: {exc}")  # noqa: F821

    # Boost announcement players (same guard)
    boosted_count = 0
    for entity_id in announce_players:
        if entity_id not in _volume_snapshot:
            log.warning(f"duck_manager: skipping announce boost for {entity_id} — no volume captured")  # noqa: F821
            continue
        try:
            await service.call("media_player", "volume_set",  # noqa: F821
                               entity_id=entity_id, volume_level=announce_vol)
            boosted_count += 1
        except Exception as exc:
            log.warning(f"duck_manager: announce boost {entity_id} failed: {exc}")  # noqa: F821

    # Record duck event start
    now = time.time()
    with _lock:
        first_session = next(iter(_sessions.values()), {})
        _last_duck_event = {
            "source": first_session.get("source", "unknown"),
            "detail": first_session.get("detail", ""),
            "duck_time": now,
            "duck_time_iso": datetime.fromtimestamp(now, tz=timezone.utc).isoformat(timespec="seconds"),
            "restore_time": None,
            "restore_time_iso": "",
            "duration_s": 0,
            "sessions": 0,
        }

    log.info(  # noqa: F821
        f"duck_manager: ducked {ducked_count} players, "
        f"paused {paused_count}, boosted {boosted_count} announcement players, "
        f"snapshot={len(_volume_snapshot)} entries (behavior={behavior})"
    )


async def _wait_for_announcements_done() -> None:
    """Wait for announcement players to finish using configured restore mode."""
    mode = _get_restore_mode()
    announce_players = _get_announcement_players()

    if not announce_players:
        await asyncio.sleep(0.3)
        return

    if mode == "fixed":
        delay = _get_restore_fixed_delay()
        await asyncio.sleep(delay)
        return

    # Dynamic mode — pre-check: if nothing is playing right now, skip wait
    any_playing_now = False
    for p in announce_players:
        if _is_playing(p):
            any_playing_now = True
            break

    if not any_playing_now:
        # TTS already done (or never started). Brief buffer then return.
        await asyncio.sleep(0.3)
        # Post-buffer: ESP audio continues after HA entity goes idle
        post_buffer = _get_restore_post_buffer()
        if post_buffer > 0:
            await asyncio.sleep(post_buffer)
        return

    # Something IS playing — wait for it to finish (Phase 2 only)
    timeout = _get_restore_timeout()
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        any_playing = False
        for p in announce_players:
            if _is_playing(p):
                any_playing = True
                break
        if not any_playing:
            break
        await asyncio.sleep(0.25)  # I-21: tighter polling for faster restore

    # Post-buffer: ESP hardware continues playing decoded audio after HA
    # entity state flips to idle (HTTP stream done ≠ speaker done)
    post_buffer = _get_restore_post_buffer()
    if post_buffer > 0:
        await asyncio.sleep(post_buffer)


async def _restore_and_verify() -> None:
    """Restore all captured volumes, then verify and retry if needed.

    I-39: Also resumes media that was paused during duck.
    I-22: Skips restore for entities the user manually adjusted.
    """
    global _volume_snapshot, _last_duck_event, _was_playing

    # Take snapshot copy and clear immediately (prevent double-restore)
    saved_snapshot = dict(_volume_snapshot)
    _volume_snapshot = {}
    paused_players = dict(_was_playing)
    _was_playing = {}
    user_adjusted = set(_user_adjusted_during_duck)
    _user_adjusted_during_duck.clear()

    log.warning(  # noqa: F821
        f"duck_manager: restore starting — "
        f"snapshot={saved_snapshot}, "
        f"paused={list(paused_players.keys())}, "
        f"user_adjusted={list(user_adjusted)}"
    )

    if not saved_snapshot and not paused_players:
        log.warning("duck_manager: nothing to restore (empty snapshot)")  # noqa: F821
        try:
            await service.call("input_boolean", "turn_off",  # noqa: F821
                               entity_id="sensor.ai_ducking_flag")
        except Exception:
            pass
        return

    # Pass 1: restore all volumes (skip user-adjusted entities)
    skipped_user = []
    for entity_id, vol in saved_snapshot.items():
        if entity_id in user_adjusted:
            skipped_user.append(entity_id)
            continue
        try:
            await service.call("media_player", "volume_set",  # noqa: F821
                               entity_id=entity_id, volume_level=vol)
        except Exception as exc:
            log.warning(f"duck_manager: restore {entity_id} failed: {exc}")  # noqa: F821

    # I-39: Resume paused media players
    resumed_count = 0
    for entity_id in paused_players:
        try:
            await service.call("media_player", "media_play",  # noqa: F821
                               entity_id=entity_id)
            resumed_count += 1
        except Exception as exc:
            log.warning(f"duck_manager: resume {entity_id} failed: {exc}")  # noqa: F821

    # Wait for players to process
    await asyncio.sleep(1.5)

    # Pass 2: verify and retry (skip user-adjusted)
    retried = []
    for entity_id, target_vol in saved_snapshot.items():
        if entity_id in user_adjusted:
            continue
        current = _capture_volume(entity_id, guard_ducked=False)
        if current is None:
            log.warning(f"duck_manager: {entity_id} volume unreadable, skipping retry")  # noqa: F821
            continue
        if abs(current - target_vol) > 0.05:
            try:
                await service.call("media_player", "volume_set",  # noqa: F821
                                   entity_id=entity_id, volume_level=target_vol)
                retried.append(entity_id)
            except Exception as exc:
                log.warning(f"duck_manager: retry restore {entity_id} failed: {exc}")  # noqa: F821

    # Clear ducking flag
    try:
        state.set("sensor.ai_ducking_flag", "off",  # noqa: F821
                  new_attributes={"icon": "mdi:duck", "friendly_name": "AI Ducking Flag"})
    except Exception:
        pass

    # Update last duck event with restore info
    now = time.time()
    with _lock:
        session_count = len(_sessions)
        if _last_duck_event:
            _last_duck_event["restore_time"] = now
            _last_duck_event["restore_time_iso"] = datetime.fromtimestamp(now, tz=timezone.utc).isoformat(timespec="seconds")
            duck_t = _last_duck_event.get("duck_time", now)
            _last_duck_event["duration_s"] = round(now - duck_t)
            _last_duck_event["sessions"] = session_count + 1

    log.info(  # noqa: F821
        f"duck_manager: restored {len(saved_snapshot)} volumes "
        f"(retried={retried}, skipped_user={skipped_user}, "
        f"resumed={resumed_count})"
    )


# ── Session Management ────────────────────────────────────────────────────────

async def _add_session(source: str, detail: str = "") -> str:
    """Add a ducking session. Capture+duck if first. Returns session_id.

    I-21: On first session, apply pre-delay before capture+duck.
    """
    ts = int(time.time() * 1000)
    session_id = f"{source}_{detail}_{ts}" if detail else f"{source}_{ts}"

    async with _sessions_lock:
        is_first = len(_sessions) == 0
        _sessions[session_id] = {
            "source": source,
            "detail": detail,
            "created_at": time.time(),
        }

    if is_first:
        # I-21: Pre-delay before first duck
        pre_delay_ms = _get_pre_delay_ms()
        if pre_delay_ms > 0:
            await asyncio.sleep(pre_delay_ms / 1000)
        # Skip ducking the TTS target speaker — it uses native announce ducking
        skip = detail if source == "tts_queue" else ""
        await _capture_and_duck(skip_duck_entity=skip)

    await _update_status()
    return session_id


async def _remove_session(session_id: str) -> bool:
    """Remove a session. Returns True if this was the last session."""
    async with _sessions_lock:
        _sessions.pop(session_id, None)
        return len(_sessions) == 0


async def _clear_all_sessions() -> None:
    global _sessions
    async with _sessions_lock:
        _sessions = {}


async def _update_status() -> None:
    async with _sessions_lock:
        count = len(_sessions)
        sources = list(set([s["source"] for s in _sessions.values()]))
    _set_result(
        "ducking" if count > 0 else "idle",
        op="status",
        active_sessions=count,
        sources=sources,
        snapshot_entries=len(_volume_snapshot),
    )


# ── Satellite Trigger (dynamic via state_trigger_factory) ─────────────────────
# Triggers are registered at startup from entity_config.yaml duck.satellites.
# To add/remove satellites: update entity_config.yaml → pyscript.reload or HA restart.
# Pattern: https://hacs-pyscript.readthedocs.io/en/stable/reference (factory)

def _satellite_trigger_factory(entity_id):
    """Create a @state_trigger for a single satellite entity."""
    @state_trigger(entity_id)  # noqa: F821
    async def _sat_trigger(var_name=None, value=None, old_value=None):
        await _on_satellite_change(var_name=var_name, value=value, old_value=old_value)
    return _sat_trigger


async def _on_satellite_change(var_name=None, value=None, old_value=None):
    """Handle satellite state changes for duck/restore.

    Called by dynamically registered triggers (see _duck_manager_startup).
    The input_text.ai_duck_satellites helper controls which satellites are
    ACTIVE for ducking (removing one disables it without a code edit).
    """
    if not _is_enabled():
        return

    # Check configured satellites (allows disabling via entity_config without code edit)
    configured = _get_duck_satellites()
    if var_name not in configured:
        return

    new_val = value or ""
    old_val = old_value or ""

    # If satellite goes unavailable/unknown while we have a session, clean it up
    if new_val in ("unavailable", "unknown"):
        sid = _sat_sessions.pop(var_name, None)
        if sid:
            log.warning(  # noqa: F821
                f"duck_manager: satellite {_get_satellite_name(var_name)} went "
                f"{new_val} during duck — cleaning up session {sid}"
            )
            is_last = await _remove_session(sid)
            if is_last:
                await _restore_and_verify()
                await _clear_snapshot()
            await _update_status()
        return

    # Ignore transitions FROM unavailable/unknown (boot-up)
    if old_val in ("unavailable", "unknown"):
        return

    sat_name = _get_satellite_name(var_name)

    if old_val == "idle" and new_val != "idle":
        # Satellite woke up → duck (but only one session per satellite)
        async with _sessions_lock:
            already_active = var_name in _sat_sessions and _sat_sessions[var_name] in _sessions
        if already_active:
            log.info(  # noqa: F821
                f"duck_manager: satellite {sat_name} re-activated — "
                f"session {_sat_sessions[var_name]} still active, skipping"
            )
            return
        session_id = await _add_session("satellite", sat_name)
        _sat_sessions[var_name] = session_id
        await _save_snapshot()
        log.info(  # noqa: F821
            f"duck_manager: satellite {sat_name} active → duck "
            f"(session={session_id})"
        )

    elif new_val == "idle" and old_val != "idle":
        # Satellite went idle → maybe restore
        # I-23: Configurable idle delay — LLM-based agents need longer than
        # the 2s default because the pipeline may time out before the LLM
        # responds, causing the satellite to go idle while the agent's tool
        # call (and its mark_user_adjusted) is still pending.
        idle_delay = _helper_float("input_number.ai_duck_idle_delay", 2.0)
        log.warning(f"duck_manager: satellite idle — waiting {idle_delay}s before restore check")  # noqa: F821
        await asyncio.sleep(idle_delay)

        # Check this satellite is still idle
        try:
            current = state.get(var_name)  # noqa: F821
            if current != "idle":
                return
        except Exception:
            return

        # Check ALL configured satellites are idle
        all_idle = True
        for sat_entity in configured:
            try:
                s = state.get(sat_entity)  # noqa: F821
                if s and s not in ("idle", "unavailable", "unknown"):
                    all_idle = False
                    break
            except Exception:
                pass

        if not all_idle:
            sid = _sat_sessions.pop(var_name, None)
            if sid:
                is_last = await _remove_session(sid)
                if is_last:
                    await _restore_and_verify()
                    await _clear_snapshot()
                await _update_status()
            return

        # All satellites idle — wait for announcements to finish
        await _wait_for_announcements_done()

        # Remove all satellite sessions
        for sat_e in list(_sat_sessions):
            sid = _sat_sessions.pop(sat_e, None)
            if sid:
                await _remove_session(sid)

        # If no sessions remain, restore
        async with _sessions_lock:
            remaining = len(_sessions)
        if remaining == 0:
            await _restore_and_verify()
            await _clear_snapshot()

        await _update_status()
        log.info(  # noqa: F821
            f"duck_manager: all satellites idle → restored "
            f"(remaining={remaining})"
        )


# ── Test Mode ────────────────────────────────────────────────────────────────

def _is_test_mode() -> bool:
    try:
        return str(
            state.get("input_boolean.ai_test_mode") or "off"  # noqa: F821
        ).lower() == "on"
    except NameError:
        return False


# ── Services ──────────────────────────────────────────────────────────────────

@service(supports_response="only")  # noqa: F821
async def duck_manager_duck(source: str = "external", detail: str = ""):
    """
    yaml
    name: Duck Manager Duck
    description: Start a ducking session. Captures and ducks on first session.
    fields:
      source:
        name: Source
        description: "Who initiated: satellite, tts_queue, external"
        default: external
        selector:
          text:
      detail:
        name: Detail
        description: Extra context (e.g. speaker name)
        required: false
        selector:
          text:
    """
    # Returns: {status, op, session_id}
    if _is_test_mode():
        log.info("duck_manager [TEST]: would start ducking session source=%s detail=%s", source, detail)  # noqa: F821
        return {"status": "test_mode_skip", "op": "duck", "session_id": "test_noop"}

    if not _is_enabled():
        return {"status": "disabled", "op": "duck_manager_duck",
                "session_id": ""}

    session_id = await _add_session(source, detail)
    await _save_snapshot()
    return {
        "status": "ok",
        "op": "duck_manager_duck",
        "session_id": session_id,
    }


@service(supports_response="only")  # noqa: F821
async def duck_manager_restore(session_id: str = "",
                               wait_for_playback: bool = True):
    """
    yaml
    name: Duck Manager Restore
    description: End a ducking session. Restores volumes when last session ends.
    fields:
      session_id:
        name: Session ID
        description: Session ID returned by duck_manager_duck
        required: true
        selector:
          text:
      wait_for_playback:
        name: Wait for Playback
        description: Wait for announcement players to finish before restoring
        default: true
        selector:
          boolean:
    """
    # Returns: {status, op, restored?, remaining_sessions?, error?}
    if _is_test_mode():
        log.info("duck_manager [TEST]: would restore ducking session=%s", session_id)  # noqa: F821
        return {"status": "test_mode_skip"}

    if not session_id:
        return {"status": "error", "op": "duck_manager_restore",
                "error": "session_id required"}

    is_last = await _remove_session(session_id)

    if is_last:
        if wait_for_playback:
            await _wait_for_announcements_done()
        await _restore_and_verify()
        await _clear_snapshot()

    await _update_status()
    return {
        "status": "ok",
        "op": "duck_manager_restore",
        "restored": is_last,
        "remaining_sessions": len(_sessions),
    }


@service(supports_response="only")  # noqa: F821
async def duck_manager_force_restore():
    """
    yaml
    name: Duck Manager Force Restore
    description: Emergency — clear all sessions and restore volumes immediately.
    """
    if _is_test_mode():
        log.info("duck_manager [TEST]: would force-restore all sessions")  # noqa: F821
        return {"status": "test_mode_skip"}

    await _clear_all_sessions()
    _sat_sessions.clear()
    await _restore_and_verify()
    await _clear_snapshot()
    await _update_status()
    log.warning("duck_manager: FORCE RESTORE — all sessions cleared")  # noqa: F821
    return {"status": "ok", "op": "duck_manager_force_restore"}


@service(supports_response="only")  # noqa: F821
async def duck_manager_status():
    """
    yaml
    name: Duck Manager Status
    description: Debug — active sessions, snapshot, and flag state.
    """
    if _is_test_mode():
        log.info("duck_manager [TEST]: would return status info")  # noqa: F821
        return {"status": "test_mode_skip"}

    async with _sessions_lock:
        sessions_copy = dict(_sessions)

    flag = "unknown"
    try:
        flag = state.get("sensor.ai_ducking_flag") or "unknown"  # noqa: F821
    except Exception:
        pass

    return {
        "status": "ok",
        "op": "duck_manager_status",
        "active_sessions": len(sessions_copy),
        "sessions": {
            k: {
                "source": v["source"],
                "detail": v["detail"],
                "age_s": round(time.time() - v["created_at"]),
            }
            for k, v in sessions_copy.items()
        },
        "snapshot_entries": len(_volume_snapshot),
        "snapshot": dict(_volume_snapshot),
        "ducking_flag": flag,
        "last_duck_event": dict(_last_duck_event) if _last_duck_event else {},
    }


# ── I-22: User Adjustment Marker ──────────────────────────────────────────────

@service(supports_response="only")  # noqa: F821
async def duck_manager_mark_user_adjusted(entity_id: str = ""):
    """
    yaml
    name: Duck Manager Mark User Adjusted
    description: >-
      Mark a media player as user-adjusted during ducking.
      On restore, its volume will not be reset to the pre-duck level.
    fields:
      entity_id:
        name: Entity ID
        description: Media player entity that the user manually adjusted.
        required: true
        selector:
          entity:
            domain: media_player
    """
    if _is_test_mode():
        log.info("duck_manager [TEST]: would mark %s as user-adjusted", entity_id)  # noqa: F821
        return {"status": "test_mode_skip"}

    if not entity_id:
        return {"status": "error", "op": "mark_user_adjusted",
                "error": "entity_id required"}

    _user_adjusted_during_duck.add(entity_id)
    log.info(  # noqa: F821
        f"duck_manager: marked {entity_id} as user-adjusted "
        f"(total={len(_user_adjusted_during_duck)})"
    )
    return {"status": "ok", "op": "mark_user_adjusted",
            "entity_id": entity_id}


# ── Duck Guard: Blueprint Snapshot Update ─────────────────────────────────────

@service(supports_response="only")  # noqa: F821
async def duck_manager_update_snapshot(entity_id: str = "",
                                       volume_level: float = -1.0):
    """
    yaml
    name: Duck Manager Update Snapshot
    description: >-
      Update the duck snapshot for a media player so that when ducking
      restores, it restores to this volume instead of the stale pre-duck
      level.  Called by blueprints after media_player.volume_set when
      ducking is active.  Returns noop if not ducking or entity not in
      the current snapshot (not in duck group).
    fields:
      entity_id:
        name: Entity ID
        description: Media player whose snapshot volume to update.
        required: true
        selector:
          entity:
            domain: media_player
      volume_level:
        name: Volume Level
        description: New volume to store in the snapshot (0.0–1.0).
        required: true
        selector:
          number:
            min: 0
            max: 1
            step: 0.01
    """
    # Returns: {status, op, entity_id?, old_volume?, new_volume?, reason?, error?}
    if _is_test_mode():
        log.info("duck_manager [TEST]: would update snapshot for %s vol=%.2f", entity_id, volume_level)  # noqa: F821
        return {"status": "test_mode_skip"}

    if not entity_id or volume_level < 0:
        return {"status": "error", "op": "update_snapshot",
                "error": "entity_id and volume_level required"}

    # Not currently ducking — nothing to update
    async with _sessions_lock:
        active = len(_sessions) > 0

    if not active:
        return {"status": "noop", "op": "update_snapshot",
                "reason": "not_ducking"}

    # Entity not in snapshot — not part of duck group, nothing to update
    with _lock:
        if entity_id not in _volume_snapshot:
            return {"status": "noop", "op": "update_snapshot",
                    "reason": "entity_not_in_snapshot",
                    "entity_id": entity_id}
        old_vol = _volume_snapshot[entity_id]
        _volume_snapshot[entity_id] = float(volume_level)
    await _save_snapshot()

    log.info(  # noqa: F821
        f"duck_manager: duck guard updated snapshot for {entity_id} "
        f"({old_vol:.2f} → {float(volume_level):.2f})"
    )
    return {"status": "ok", "op": "update_snapshot",
            "entity_id": entity_id,
            "old_volume": old_vol,
            "new_volume": float(volume_level)}


# ── Watchdog ──────────────────────────────────────────────────────────────────

@time_trigger("cron(* * * * *)")  # noqa: F821
async def _duck_watchdog():
    """Check for stale sessions and force-restore if needed."""
    timeout = _get_watchdog_timeout()
    now = time.time()
    stale = []

    async with _sessions_lock:
        for sid, info in _sessions.items():
            age = now - info["created_at"]
            if age > timeout:
                stale.append((sid, info["source"], info["detail"], age))

    if not stale:
        return

    log.warning(  # noqa: F821
        f"duck_manager: watchdog found {len(stale)} stale sessions, "
        f"force-restoring"
    )

    await _clear_all_sessions()
    _sat_sessions.clear()
    await _restore_and_verify()
    await _clear_snapshot()
    await _update_status()

    try:
        detail_str = ", ".join(
            f"{s[1]}:{s[2]} ({s[3]:.0f}s)" for s in stale
        )
        await service.call(  # noqa: F821
            "persistent_notification", "create",
            title="Duck Manager Watchdog",
            message=f"Force-restored {len(stale)} stale session(s): {detail_str}",
            notification_id="duck_manager_watchdog",
        )
    except Exception:
        pass


# ── Startup ───────────────────────────────────────────────────────────────────

@time_trigger("startup")  # noqa: F821
async def _duck_manager_startup():
    """Initialize duck manager. Crash recovery from snapshot file."""
    global _volume_snapshot

    _ensure_result_entity_name(force=True)

    # Crash recovery: restore from snapshot if present
    snapshot = await _load_snapshot()
    if snapshot:
        # Handle both old format (flat dict) and new format (nested dict)
        if "volumes" in snapshot:
            _volume_snapshot = snapshot.get("volumes", {})
            _was_playing = snapshot.get("was_playing", {})
        else:
            _volume_snapshot = snapshot  # backward compat with old format
        log.warning(  # noqa: F821
            f"duck_manager: crash recovery — restoring "
            f"{len(_volume_snapshot)} volumes"
        )
        await _restore_and_verify()

    # Clear stale state
    await _clear_all_sessions()
    _sat_sessions.clear()
    await _clear_snapshot()

    try:
        state.set("sensor.ai_ducking_flag", "off",  # noqa: F821
                  new_attributes={"icon": "mdi:duck", "friendly_name": "AI Ducking Flag"})
    except Exception:
        pass

    # Register satellite triggers dynamically from config
    global _satellite_triggers
    satellites = _get_duck_satellites()
    _satellite_triggers = [_satellite_trigger_factory(sat) for sat in satellites]
    log.warning(  # noqa: F821
        f"duck_manager: registered {len(_satellite_triggers)} satellite "
        f"triggers: {satellites}"
    )

    _set_result("idle", op="startup", sessions=0, snapshot_entries=0)
    log.info("duck_manager.py loaded — idle")  # noqa: F821
