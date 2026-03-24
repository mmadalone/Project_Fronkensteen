"""Task 14: Notification Deduplication Across Briefing, Calendar, and Follow-Me.

Prevents duplicate TTS announcements when multiple delivery systems
(proactive briefing, calendar push, notification follow-me) try to
announce the same information. Uses L2 hash-key lookups with TTL-based
expiry and a fail-open policy to ensure announcements are never missed.
"""
import re
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from shared_utils import build_result_entity_name

# =============================================================================
# Notification Deduplication — DC-9 Voice Context Architecture (Task 14)
# =============================================================================
# Prevents duplicate announcements when multiple systems (proactive briefing,
# calendar push, notification follow-me, predictions) try to deliver the same
# information. Example: "You have a meeting at 9 AM" from morning briefing
# AND calendar push — only the first one should play.
#
# Services:
#   pyscript.dedup_check
#     Pre-announcement: check if topic was already announced recently.
#     Uses exact-key L2 lookup (memory_get) for O(1) speed — target <100ms.
#
#   pyscript.dedup_register
#     Post-announcement: record that a topic was announced.
#     Stores hash key in L2 memory with TTL-based expiration.
#
#   pyscript.dedup_announce
#     Combined check + TTS + register. Blueprints call this instead of
#     managing check/register separately.
#
# Key design:
#   - Hash key: "announced:{topic_slug}_{YYYYMMDD}" — exact key, no FTS scan
#   - Cross-midnight: checks today AND yesterday keys for TTL spanning midnight
#   - Fail-open: if L2 is down, allow announcement (better repeat than miss)
#   - Kill switch: input_boolean.ai_dedup_enabled
#   - Test mode: detect + log duplicates but NEVER suppress announcements
#   - skip_dedup: caller can bypass dedup entirely (e.g., queue/barge_in modes)
#
# Dependencies:
#   - pyscript/memory.py (L2: memory_get, memory_set, memory_forget, memory_search)
#   - pyscript/tts_queue.py (pyscript.tts_queue_speak)
#   - packages/ai_notification_dedup.yaml (helpers)
#   - packages/ai_test_harness.yaml (test mode toggle)
#
# Deployed: 2026-03-01
# =============================================================================

RESULT_ENTITY = "sensor.ai_dedup_status"

result_entity_name: dict[str, str] = {}


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
def _normalize_topic(topic: str) -> str:
    """Normalize topic string for consistent hash key generation.

    Lowercase, spaces to underscores, strip special characters.
    "Meeting at 9 AM" → "meeting_at_9_am"
    """
    if not topic:
        return "unknown"
    t = topic.lower().strip()
    t = t.replace(" ", "_")
    t = re.sub(r"[^\w]", "", t)
    t = re.sub(r"_+", "_", t)
    t = t.strip("_")
    return t or "unknown"


@pyscript_compile  # noqa: F821
def _build_hash_key(topic_normalized: str, date_str: str) -> str:
    """Build dedup hash key: announced:{topic}_{YYYYMMDD}."""
    return f"announced:{topic_normalized}_{date_str}"


@pyscript_compile  # noqa: F821
def _parse_dedup_value(value: str) -> tuple[str, str]:
    """Parse stored dedup value → (source, timestamp).

    Format: "delivered via {source} at {ISO timestamp}"
    """
    if not value:
        return ("unknown", "")
    parts = value.rsplit(" at ", 1)
    if len(parts) == 2:
        src = parts[0].replace("delivered via ", "").strip()
        ts = parts[1].strip()
        return (src, ts)
    return ("unknown", "")


@pyscript_compile  # noqa: F821
def _is_within_ttl(
    created_at_iso: str,
    ttl_hours: float,
    now_utc_iso: str,
) -> bool:
    """Check if created_at is within TTL window from now."""
    if not created_at_iso:
        return False
    try:
        created = datetime.fromisoformat(created_at_iso)
        now = datetime.fromisoformat(now_utc_iso)
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        return (now - created).total_seconds() < (ttl_hours * 3600)
    except (ValueError, TypeError):
        return False


@pyscript_compile  # noqa: F821
def _is_older_than_hours(
    created_at_iso: str,
    hours: float,
    now_utc_iso: str,
) -> bool:
    """Check if created_at is older than the specified hours."""
    if not created_at_iso:
        return True
    try:
        created = datetime.fromisoformat(created_at_iso)
        now = datetime.fromisoformat(now_utc_iso)
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        return (now - created).total_seconds() > (hours * 3600)
    except (ValueError, TypeError):
        return True


# ── L2 Memory Helpers ────────────────────────────────────────────────────────

async def _l2_get(key: str) -> dict | None:
    """Exact-key lookup in L2 via memory_get. Returns response dict or None."""
    try:
        result = pyscript.memory_get(key=key)  # noqa: F821
        return await result
    except Exception as exc:
        log.warning(f"dedup: L2 get failed key={key}: {exc}")  # noqa: F821
        return None


async def _l2_set(
    key: str, value: str, tags: str,
    scope: str = "household", expiration_days: int = 1,
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
        log.warning(f"dedup: L2 set failed key={key}: {exc}")  # noqa: F821
        return False


async def _l2_forget(key: str) -> bool:
    """Delete entry from L2 via memory_forget."""
    try:
        result = pyscript.memory_forget(key=key)  # noqa: F821
        resp = await result
        return resp is not None and resp.get("status") == "ok"
    except Exception as exc:
        log.warning(f"dedup: L2 forget failed key={key}: {exc}")  # noqa: F821
        return False


async def _l2_search(query: str, limit: int = 20) -> list[dict[str, Any]]:
    """Search L2 via memory_search. Returns empty list on failure."""
    try:
        result = pyscript.memory_search(query=query, limit=limit)  # noqa: F821
        resp = await result
        if resp and resp.get("status") == "ok":
            return resp.get("results", [])
    except Exception as exc:
        log.warning(f"dedup: L2 search failed query={query}: {exc}")  # noqa: F821
    return []


# ── Counter Helper ───────────────────────────────────────────────────────────

def _increment_blocked_counter() -> None:
    """Increment the daily blocked-duplicates counter."""
    try:
        current = float(state.get("input_number.ai_dedup_blocked_count") or 0)  # noqa: F821
        service.call("input_number", "set_value",  # noqa: F821
                     entity_id="input_number.ai_dedup_blocked_count",
                     value=min(current + 1, 999))
    except Exception:
        pass


# ── Resolve Default TTL ─────────────────────────────────────────────────────

def _resolve_ttl(ttl_hours: float) -> float:
    """Resolve TTL: use provided value or fall back to helper entity.

    Service callers pass ttl_hours directly (in hours).
    The helper (input_number.ai_dedup_default_ttl) stores minutes — convert
    to hours for internal use (all TTL logic uses hours).
    """
    if ttl_hours > 0:
        return max(0.01, min(24.0, ttl_hours))
    try:
        default_minutes = float(
            state.get("input_number.ai_dedup_default_ttl") or 240  # noqa: F821
        )
        default_hours = default_minutes / 60.0
        return max(1.0 / 60.0, min(12.0, default_hours))
    except (TypeError, ValueError):
        return 4.0


# ── Core Internal Functions ──────────────────────────────────────────────────

async def _dedup_check_internal(
    topic: str, source: str, ttl_hours: float, test_mode: bool,
) -> dict[str, Any]:
    """Core dedup check logic.

    Checks today's AND yesterday's hash key for cross-midnight TTL support.
    Two sequential exact-key lookups — still well under 100ms target.
    """
    topic_norm = _normalize_topic(topic)
    now = datetime.now(UTC)
    now_iso = now.isoformat()

    today_key = _build_hash_key(topic_norm, now.strftime("%Y%m%d"))
    yesterday_key = _build_hash_key(
        topic_norm, (now - timedelta(days=1)).strftime("%Y%m%d")
    )

    l2_failures = 0

    for hash_key in (today_key, yesterday_key):
        resp = await _l2_get(hash_key)

        if resp is None:
            l2_failures += 1
            continue

        resp_status = resp.get("status", "")

        # Not found or ambiguous → try next key
        if resp_status == "error":
            continue

        # L2 expired → definitely past our TTL too → try next key
        if resp_status == "expired":
            continue

        # Found and valid in L2 → check our TTL window
        if resp_status == "ok":
            created_at = resp.get("created_at", "")
            if _is_within_ttl(created_at, ttl_hours, now_iso):
                # DUPLICATE found
                value = resp.get("value", "")
                original_source, original_time = _parse_dedup_value(value)

                if test_mode:
                    log.info(  # noqa: F821
                        f"dedup_check [TEST]: DUPLICATE topic={topic_norm} "
                        f"original_source={original_source} "
                        f"original_time={original_time}"
                    )

                return {
                    "duplicate": True, "reason": "within_ttl",
                    "original_source": original_source,
                    "original_time": original_time,
                    "hash_key": hash_key, "topic": topic_norm,
                }

    # No duplicate found across either key
    if l2_failures == 2:
        log.warning(  # noqa: F821
            f"dedup_check: L2 unreachable for all keys, "
            f"fail-open topic={topic_norm}"
        )
        return {
            "duplicate": False, "reason": "l2_unavailable",
            "hash_key": today_key, "topic": topic_norm,
        }

    return {
        "duplicate": False, "reason": "not_found",
        "hash_key": today_key, "topic": topic_norm,
    }


async def _dedup_register_internal(
    topic: str, source: str, ttl_hours: float, test_mode: bool,
) -> dict[str, Any]:
    """Core register logic. Writes announcement hash to L2."""
    topic_norm = _normalize_topic(topic)
    source_norm = (source or "unknown").lower().strip()
    now = datetime.now(UTC)
    date_str = now.strftime("%Y%m%d")
    hash_key = _build_hash_key(topic_norm, date_str)

    value = f"delivered via {source_norm} at {now.isoformat()}"
    tags = f"dedup announcement {source_norm} {topic_norm}"
    # L2 expiration: TTL rounded up to days + 1 day buffer
    expiration_days = max(1, int(ttl_hours / 24) + 1)

    if test_mode:
        log.info(  # noqa: F821
            f"dedup_register [TEST]: WOULD REGISTER key={hash_key} "
            f"value={value}"
        )
        return {
            "registered": False, "hash_key": hash_key,
            "topic": topic_norm, "source": source_norm,
            "test_skip": True,
        }

    ok = await _l2_set(
        key=hash_key, value=value, tags=tags,
        scope="household", expiration_days=expiration_days,
    )

    if ok:
        log.info(  # noqa: F821
            f"dedup_register: registered {hash_key} source={source_norm}"
        )
    else:
        log.warning(  # noqa: F821
            f"dedup_register: L2 write failed for {hash_key}"
        )

    return {
        "registered": ok, "hash_key": hash_key,
        "topic": topic_norm, "source": source_norm,
    }


# ── Test Mode ────────────────────────────────────────────────────────────────

def _is_test_mode() -> bool:
    try:
        return str(
            state.get("input_boolean.ai_test_mode") or "off"  # noqa: F821
        ).lower() == "on"
    except NameError:
        return False


# ── Services ─────────────────────────────────────────────────────────────────

@service(supports_response="only")  # noqa: F821
async def dedup_check(
    topic: str = "",
    source: str = "",
    ttl_hours: float = 0,
):
    """
    yaml
    name: Dedup Check
    description: >-
      Check if a topic has already been announced recently. Returns duplicate
      status with original source and time. Uses exact-key L2 lookup for
      speed (target <100ms). Fails open if L2 is unavailable.
    fields:
      topic:
        name: Topic
        description: What is being announced (e.g., "meeting_9am", "weather_alert").
        required: true
        example: "meeting_9am"
        selector:
          text:
      source:
        name: Source
        description: Which system is announcing (e.g., "proactive_briefing", "calendar_push").
        required: true
        example: "proactive_briefing"
        selector:
          text:
      ttl_hours:
        name: TTL Hours
        description: How long to suppress duplicates. 0 = use default from helper.
        default: 0
        selector:
          number:
            min: 0
            max: 24
            step: 0.5
    """
    # Returns: {status, op, duplicate, reason, hash_key?, topic?, original_source?, original_time?, test_mode, elapsed_ms}  # noqa: E501
    if _is_test_mode():
        log.info("notification_dedup [TEST]: would check dedup for topic=%s source=%s", topic, source)  # noqa: F821
        return {"status": "test_mode_skip", "op": "dedup_check", "duplicate": False, "reason": "test_mode"}

    t_start = time.monotonic()

    # Kill switch
    if state.get("input_boolean.ai_dedup_enabled") == "off":  # noqa: F821
        result = {
            "status": "ok", "op": "dedup_check", "duplicate": False,
            "reason": "dedup_disabled", "elapsed_ms": 0,
        }
        _set_result("ok", **result)
        return result

    test_mode = state.get("input_boolean.ai_test_mode") == "on"  # noqa: F821
    ttl = _resolve_ttl(ttl_hours)

    check = await _dedup_check_internal(topic, source, ttl, test_mode)

    elapsed = round((time.monotonic() - t_start) * 1000, 1)

    result = {
        "status": "ok",
        "op": "dedup_check",
        "duplicate": check["duplicate"],
        "reason": check.get("reason", ""),
        "hash_key": check.get("hash_key", ""),
        "topic": check.get("topic", ""),
        "original_source": check.get("original_source", ""),
        "original_time": check.get("original_time", ""),
        "test_mode": test_mode,
        "elapsed_ms": elapsed,
    }

    sensor_state = "test" if test_mode else "ok"
    _set_result(sensor_state, **result)

    log.info(  # noqa: F821
        f"dedup_check: topic={check.get('topic', '')} "
        f"duplicate={check['duplicate']} "
        f"reason={check.get('reason', '')} "
        f"{elapsed}ms{' [TEST]' if test_mode else ''}"
    )

    return result


@service(supports_response="only")  # noqa: F821
async def dedup_register(
    topic: str = "",
    source: str = "",
    ttl_hours: float = 0,
):
    """
    yaml
    name: Dedup Register
    description: >-
      Register a successful announcement in L2 memory. Called AFTER TTS
      playback is queued. Stores hash key with source, timestamp, and tags.
      Idempotent — calling twice with same topic just updates the entry.
    fields:
      topic:
        name: Topic
        description: What was announced.
        required: true
        example: "meeting_9am"
        selector:
          text:
      source:
        name: Source
        description: Which system announced it.
        required: true
        example: "proactive_briefing"
        selector:
          text:
      ttl_hours:
        name: TTL Hours
        description: How long to suppress future duplicates. 0 = use default.
        default: 0
        selector:
          number:
            min: 0
            max: 24
            step: 0.5
    """
    # Returns: {status, op, registered, hash_key?, topic?, source?, test_mode, test_skip?, elapsed_ms, reason?}
    if _is_test_mode():
        log.info("notification_dedup [TEST]: would register dedup for topic=%s source=%s", topic, source)  # noqa: F821
        return {"status": "test_mode_skip"}

    t_start = time.monotonic()

    if state.get("input_boolean.ai_dedup_enabled") == "off":  # noqa: F821
        result = {
            "status": "ok", "op": "dedup_register", "registered": False,
            "reason": "dedup_disabled", "elapsed_ms": 0,
        }
        _set_result("ok", **result)
        return result

    test_mode = state.get("input_boolean.ai_test_mode") == "on"  # noqa: F821
    ttl = _resolve_ttl(ttl_hours)

    reg = await _dedup_register_internal(topic, source, ttl, test_mode)

    elapsed = round((time.monotonic() - t_start) * 1000, 1)

    result = {
        "status": "ok",
        "op": "dedup_register",
        "registered": reg["registered"],
        "hash_key": reg.get("hash_key", ""),
        "topic": reg.get("topic", ""),
        "source": reg.get("source", ""),
        "test_mode": test_mode,
        "test_skip": reg.get("test_skip", False),
        "elapsed_ms": elapsed,
    }

    sensor_state = "test" if test_mode else "ok"
    _set_result(sensor_state, **result)

    log.info(  # noqa: F821
        f"dedup_register: topic={reg.get('topic', '')} "
        f"registered={reg['registered']} "
        f"{elapsed}ms{' [TEST]' if test_mode else ''}"
    )

    return result


@service(supports_response="only")  # noqa: F821
async def dedup_announce(
    topic: str = "",
    source: str = "",
    ttl_hours: float = 0,
    text: str = "",
    voice: str = "",
    voice_id: str = "",
    priority: int = 3,
    target_mode: str = "presence",
    volume_level: float = None,
    skip_dedup: bool = False,
    chime_path: str = "",
    restore_volume: bool = False,
    volume_restore_delay: int = 8,
    metadata=None,
):
    """
    yaml
    name: Dedup Announce
    description: >-
      Combined check + announce + register. Blueprints call this instead of
      managing check/register separately. Checks for duplicates, plays TTS
      via tts_queue_speak if new, then registers the announcement in L2.
      In test mode, duplicates are detected and logged but never suppressed.
      When skip_dedup is true, bypasses dedup check and registration entirely
      (used by queue/barge_in collision modes).
    fields:
      topic:
        name: Topic
        description: What is being announced.
        required: true
        example: "meeting_9am"
        selector:
          text:
      source:
        name: Source
        description: Which system is announcing.
        required: true
        example: "proactive_briefing"
        selector:
          text:
      ttl_hours:
        name: TTL Hours
        description: Duplicate suppression window. 0 = use default.
        default: 0
        selector:
          number:
            min: 0
            max: 24
            step: 0.5
      text:
        name: Text
        description: The announcement text to speak.
        required: true
        selector:
          text:
            multiline: true
      voice:
        name: Voice
        description: TTS entity (e.g., tts.elevenlabs_custom_tts).
        required: true
        selector:
          text:
      voice_id:
        name: Voice ID
        description: >-
          Voice profile name for unified HACS TTS entity
          (e.g., "Kramer - That Neighbor v0.0.10"). Passed through to
          tts_queue_speak. Empty = use entity default.
        default: ""
        selector:
          text:
      priority:
        name: Priority
        description: "TTS queue priority: 0=emergency, 1=alert, 2=normal, 3=low, 4=ambient"
        default: 3
        selector:
          number:
            min: 0
            max: 4
      target_mode:
        name: Target Mode
        description: "Speaker targeting: presence, explicit, broadcast, source_room"
        default: presence
        selector:
          select:
            options: [presence, explicit, broadcast, source_room]
      volume_level:
        name: Volume Level
        description: "Speaker volume (0.0–1.0) to set before TTS. None = leave unchanged."
        selector:
          number:
            min: 0.0
            max: 1.0
            step: 0.05
      chime_path:
        name: Chime Path
        description: >-
          I-10: Optional pre-TTS chime/stinger file path. Passed through to
          tts_queue_speak chime_path parameter. Empty = no chime.
        default: ""
        selector:
          text:
      restore_volume:
        name: Restore Volume
        description: >-
          Save the speaker's current volume before TTS and restore it after
          playback. Passed through to tts_queue_speak. Only applies when
          volume_level is set > 0.
        default: false
        selector:
          boolean:
      volume_restore_delay:
        name: Volume Restore Delay
        description: >-
          Seconds to wait after TTS before restoring volume. Passed through
          to tts_queue_speak.
        default: 8
        selector:
          number:
            min: 1
            max: 30
      metadata:
        name: Metadata
        description: >-
          Caller metadata dict passed through to tts_queue_speak and emitted
          in the tts_queue_item_completed event after playback.
        required: false
        selector:
          object:
    """
    if _is_test_mode():
        log.info("notification_dedup [TEST]: would dedup-announce topic=%s source=%s", topic, source)  # noqa: F821
        return {"status": "test_mode_skip"}

    t_start = time.monotonic()

    if not text:
        result = {
            "status": "error", "op": "dedup_announce",
            "error": "text_required",
        }
        _set_result("error", **result)
        return result
    if not voice:
        result = {
            "status": "error", "op": "dedup_announce",
            "error": "voice_required",
        }
        _set_result("error", **result)
        return result

    # Skip dedup entirely if caller requests it (e.g., queue/barge_in collision mode)
    if skip_dedup:
        tts_ok = False
        try:
            tts_kwargs = dict(
                text=text,
                voice=voice,
                priority=int(max(0, min(4, priority))),
                target_mode=target_mode,
                volume_level=volume_level,
                restore_volume=restore_volume,
                volume_restore_delay=volume_restore_delay,
            )
            if voice_id:
                tts_kwargs["voice_id"] = voice_id
            if chime_path:
                tts_kwargs["chime_path"] = chime_path
            if metadata and isinstance(metadata, dict):
                tts_kwargs["metadata"] = metadata
            tts_call = pyscript.tts_queue_speak(**tts_kwargs)  # noqa: F821
            tts_resp = await tts_call
            tts_ok = tts_resp is not None and tts_resp.get("status") == "queued"
        except Exception as exc:
            log.error(f"dedup_announce: tts_queue_speak failed (skip_dedup): {exc}")  # noqa: F821

        elapsed = round((time.monotonic() - t_start) * 1000, 1)
        result = {
            "status": "ok", "op": "dedup_announce",
            "announced": tts_ok, "topic": _normalize_topic(topic),
            "source": (source or "unknown").lower().strip(),
            "duplicate_detected": False, "test_mode": False,
            "skip_dedup": True, "elapsed_ms": elapsed,
        }
        _set_result("ok", **result)
        log.info(  # noqa: F821
            f"dedup_announce: {'ANNOUNCED' if tts_ok else 'TTS_FAILED'} "
            f"topic={result['topic']} skip_dedup=true {elapsed}ms"
        )
        return result

    test_mode = state.get("input_boolean.ai_test_mode") == "on"  # noqa: F821
    dedup_enabled = state.get("input_boolean.ai_dedup_enabled") != "off"  # noqa: F821
    ttl = _resolve_ttl(ttl_hours)

    is_duplicate = False
    check_result = {}

    if dedup_enabled:
        check_result = await _dedup_check_internal(
            topic, source, ttl, test_mode,
        )
        is_duplicate = check_result.get("duplicate", False)

    # In test mode: detect duplicates but NEVER suppress
    suppress = is_duplicate and not test_mode

    if suppress:
        # Duplicate + not test mode → block announcement
        _increment_blocked_counter()
        elapsed = round((time.monotonic() - t_start) * 1000, 1)

        result = {
            "status": "ok",
            "op": "dedup_announce",
            "announced": False,
            "reason": "duplicate",
            "topic": check_result.get("topic", ""),
            "original_source": check_result.get("original_source", ""),
            "original_time": check_result.get("original_time", ""),
            "test_mode": False,
            "elapsed_ms": elapsed,
        }

        _set_result("ok", **result)
        log.info(  # noqa: F821
            f"dedup_announce: BLOCKED duplicate "
            f"topic={check_result.get('topic', '')} "
            f"original_source={check_result.get('original_source', '')} "
            f"{elapsed}ms"
        )
        return result

    # Not a duplicate (or test mode / dedup disabled) → play TTS
    if test_mode and is_duplicate:
        log.info(  # noqa: F821
            f"dedup_announce [TEST]: duplicate detected but NOT suppressing "
            f"topic={check_result.get('topic', '')}"
        )

    tts_ok = False
    try:
        tts_kwargs = dict(
            text=text,
            voice=voice,
            priority=int(max(0, min(4, priority))),
            target_mode=target_mode,
            volume_level=volume_level,
            restore_volume=restore_volume,
            volume_restore_delay=volume_restore_delay,
        )
        if voice_id:
            tts_kwargs["voice_id"] = voice_id
        if chime_path:
            tts_kwargs["chime_path"] = chime_path
        if metadata and isinstance(metadata, dict):
            tts_kwargs["metadata"] = metadata
        tts_call = pyscript.tts_queue_speak(**tts_kwargs)  # noqa: F821
        tts_resp = await tts_call
        tts_ok = tts_resp is not None and tts_resp.get("status") == "queued"
    except Exception as exc:
        log.error(f"dedup_announce: tts_queue_speak failed: {exc}")  # noqa: F821

    # Only register if TTS was actually queued (don't register on TTS failure)
    if dedup_enabled and tts_ok:
        await _dedup_register_internal(topic, source, ttl, test_mode)

    elapsed = round((time.monotonic() - t_start) * 1000, 1)
    topic_norm = _normalize_topic(topic)
    source_norm = (source or "unknown").lower().strip()

    result = {
        "status": "ok",
        "op": "dedup_announce",
        "announced": tts_ok,
        "topic": topic_norm,
        "source": source_norm,
        "duplicate_detected": is_duplicate,
        "test_mode": test_mode,
        "elapsed_ms": elapsed,
    }

    sensor_state = "test" if test_mode else "ok"
    _set_result(sensor_state, **result)

    log.info(  # noqa: F821
        f"dedup_announce: {'ANNOUNCED' if tts_ok else 'TTS_FAILED'} "
        f"topic={topic_norm} source={source_norm} "
        f"dup_detected={is_duplicate} "
        f"{elapsed}ms{' [TEST]' if test_mode else ''}"
    )

    return result


# ── Startup ──────────────────────────────────────────────────────────────────

@time_trigger("startup")  # noqa: F821
async def dedup_startup():
    """Initialize dedup sensor on HA startup."""
    _ensure_result_entity_name(force=True)
    _set_result("idle", op="startup")
    log.info("notification_dedup.py loaded — dedup idle")  # noqa: F821


# ── Daily Housekeeping ───────────────────────────────────────────────────────

@time_trigger("cron(5 0 * * *)")  # noqa: F821
async def dedup_daily_housekeeping():
    """Reset blocked counter and purge stale dedup entries from L2.

    L2's own expiration handles most cleanup — this cron is a safety net
    for entries that somehow survived past their L2 expiration_days.
    """
    # Reset daily blocked counter
    try:
        service.call("input_number", "set_value",  # noqa: F821
                     entity_id="input_number.ai_dedup_blocked_count", value=0)
    except Exception as exc:
        log.error(f"dedup housekeeping: counter reset failed: {exc}")  # noqa: F821

    # Purge stale dedup entries (older than cleanup_hours — max TTL is 24h + buffer)
    cleanup_max_age = _helper_int("input_number.ai_dedup_cleanup_hours", 48)
    entries = await _l2_search("dedup announcement", limit=50)
    deleted = 0
    now_iso = datetime.now(UTC).isoformat()

    for entry in entries:
        key = entry.get("key", "")
        # Normalized keys start with "announced_" (colon stripped by memory.py)
        if not key.startswith("announced_"):
            continue
        created_at = entry.get("created_at", "")
        if _is_older_than_hours(created_at, cleanup_max_age, now_iso):
            if await _l2_forget(key):
                deleted += 1

    log.info(  # noqa: F821
        f"dedup housekeeping: reset blocked counter, "
        f"purged {deleted} stale entries"
    )
