"""I-56: Shared Voice Session Service — Mic Control Infrastructure.

Extracts reusable mic control patterns from voice_handoff.py into shared
services. Consumers: music composer (prelisten), handoff (future), interview
(future).

Services:
  pyscript.voice_session_wait_audio     — wait for speaker to finish playing
  pyscript.voice_session_open_mic       — single mic open via start_conversation
  pyscript.voice_session_continuous     — full continuous conversation loop
  pyscript.voice_session_request        — write pending flag for post-pipeline mic
  pyscript.voice_session_rediscover     — re-scan entity registry
"""
# =============================================================================
# Voice Session Pyscript Service
# =============================================================================
# Shared mic control infrastructure for post-pipeline actions.
# Ported from voice_handoff.py (I-24) to avoid code duplication.
#
# Consumers:
#   - voice_session_mic.yaml (automation) — post-pipeline playback + mic
#   - voice_compose_music.yaml (script) — queues music feedback sessions
#
# Future consumers:
#   - voice_handoff.py — migrate inline mic control (Phase 3)
#   - user_interview.yaml — session-based interviews (Phase 2)
# =============================================================================

import asyncio  # noqa: F401
import json as _json  # noqa: F401
import time  # noqa: F401

# ── Config ───────────────────────────────────────────────────────────────────

SILENCE_MEDIA_ID = "http://homeassistant.local:8123/local/silence.wav"

# ── Auto-discovered maps (populated at startup) ─────────────────────────────

_speaker_map = {}   # satellite_entity → media_player_entity (ESP speaker)
_select_map = {}    # satellite_entity → select_entity (pipeline picker)


# ── Wait for Audio ──────────────────────────────────────────────────────────

@service(supports_response="optional")  # noqa: F821
async def voice_session_wait_audio(
    satellite: str = "",
    speaker: str = "",
    timeout: float = 60.0,
):
    """Wait for ESP device to finish playing TTS/media audio.

    Event-driven approach using task.wait_until — zero polling loops.

    Phase 1: Wait for satellite idle (pipeline dispatches TTS URL).
    Phase 2: Wait for ACTUAL audio completion via dual signal:
      - Primary: esphome.voice_tts_done event (fires after ESP hardware
        playback finishes, from on_idle trigger in ESPHome YAML).
      - Fallback: media_player state → idle (covers firmware gaps).
      First signal to fire wins.

    yaml
    name: Voice Session — Wait Audio
    description: >-
      Wait for satellite/speaker to finish playing audio. Dual-signal:
      ESPHome voice_tts_done event + speaker state fallback.
    fields:
      satellite:
        name: Satellite Entity
        description: If empty, reads input_text.ai_last_satellite.
        required: false
        selector:
          entity:
            domain: assist_satellite
      speaker:
        name: Speaker Entity
        description: If empty, auto-discovered from satellite.
        required: false
        selector:
          entity:
            domain: media_player
      timeout:
        name: Timeout (seconds)
        required: false
        default: 60
        selector:
          number:
            min: 5
            max: 300
    """
    if not satellite:
        satellite = (
            state.get("sensor.ai_last_satellite") or ""  # noqa: F821
        ).strip()
    if not satellite:
        log.warning("voice_session: wait_audio — no satellite")  # noqa: F821
        return {"status": "error", "error": "no satellite"}

    if not speaker:
        speaker = _speaker_map.get(satellite, "")

    IDLE_STATES = ("idle", "off", "unavailable", "unknown")

    # Derive ESP device name for event matching
    sat_parts = satellite.split(".")[-1]
    device_name = sat_parts.replace("_assist_satellite", "").replace("_", "-")

    # Phase 1: Wait for satellite idle (pipeline end)
    trig = task.wait_until(  # noqa: F821
        state_trigger=f"{satellite} == 'idle'",
        timeout=timeout,
        state_check_now=True,
    )
    if trig.get("trigger_type") == "timeout":
        log.warning(  # noqa: F821
            f"voice_session: satellite {satellite} never went idle ({timeout}s)"
        )
        return {"status": "timeout", "phase": "satellite_idle"}

    # Phase 2: Wait for ACTUAL audio completion — dual signal, first wins
    wait_args = dict(timeout=timeout)

    # Primary: ESPHome on_idle event (definitive)
    wait_args["event_trigger"] = [
        "esphome.voice_tts_done",
        f"satellite == '{device_name}'",
    ]

    # Fallback: media_player state change
    if speaker:
        wait_args["state_trigger"] = f"{speaker} in {list(IDLE_STATES)}"
        # Do NOT use state_check_now=True here — ESP speaker entity stays
        # 'idle' during internal TTS playback (not tracked by media_player).
        # Checking current state would return immediately while TTS is still
        # playing. Wait for a NEW transition or the voice_tts_done event.
        wait_args["state_check_now"] = False

    trig = task.wait_until(**wait_args)  # noqa: F821
    trig_type = trig.get("trigger_type", "timeout")

    if trig_type == "event":
        log.info(  # noqa: F821
            f"voice_session: audio done (esphome event) for {device_name}"
        )
    elif trig_type == "state":
        log.info(  # noqa: F821
            f"voice_session: audio done (speaker idle) for {speaker}"
        )
    else:
        log.warning(  # noqa: F821
            f"voice_session: audio wait timeout ({timeout}s) for {satellite}"
        )
        return {"status": "timeout", "phase": "audio_done"}

    # Post-playback buffer
    await asyncio.sleep(0.3)
    return {"status": "ok"}


# ── Open Mic ─────────────────────────────────────────────────────────────────

@service(supports_response="optional")  # noqa: F821
async def voice_session_open_mic(
    satellite: str = "",
    silence_media: str = "",
    extra_system_prompt: str = "",
    echo_guard_seconds: float = 0.5,
):
    """Open mic once via assist_satellite.start_conversation.

    yaml
    name: Voice Session — Open Mic
    description: >-
      Single mic open with silence media and optional system prompt.
    fields:
      satellite:
        name: Satellite Entity
        required: false
        selector:
          entity:
            domain: assist_satellite
      silence_media:
        name: Silence Media URL
        required: false
        selector:
          text:
      extra_system_prompt:
        name: Extra System Prompt
        required: false
        selector:
          text:
            multiline: true
      echo_guard_seconds:
        name: Echo Guard (seconds)
        required: false
        default: 0.5
        selector:
          number:
            min: 0
            max: 5
    """
    if not satellite:
        satellite = (
            state.get("sensor.ai_last_satellite") or ""  # noqa: F821
        ).strip()
    if not satellite:
        log.warning("voice_session: open_mic — no satellite")  # noqa: F821
        return {"status": "error", "error": "no satellite"}

    sid = silence_media or SILENCE_MEDIA_ID

    if echo_guard_seconds > 0:
        await asyncio.sleep(echo_guard_seconds)

    service.call(  # noqa: F821
        "assist_satellite", "start_conversation",
        entity_id=satellite,
        start_media_id=sid,
        preannounce=False,
        extra_system_prompt=extra_system_prompt or "",
    )

    # Wait for session to start (satellite leaves idle)
    for _ in range(10):
        if state.get(satellite) != "idle":  # noqa: F821
            break
        await asyncio.sleep(0.5)

    return {"status": "ok", "satellite": satellite}


# ── Continuous Conversation ──────────────────────────────────────────────────

@service(supports_response="optional")  # noqa: F821
async def voice_session_continuous(
    satellite: str = "",
    speaker: str = "",
    silence_media: str = "",
    extra_system_prompt: str = "",
    timeout: float = 120,
    no_speech_limit: int = 3,
    start_media_override: str = "",
    feedback_question: str = "",
    feedback_context: str = "",
):
    """Continuous conversation with dynamic hot-context agent awareness.

    For music feedback sessions, context is injected into a hot-context
    helper (input_text.ai_music_feedback_context) so the agent sees it on
    EVERY pipeline turn — even after duplicate_wake_up recovery or
    satellite auto-restart. No extra_system_prompt needed for music.

    Two-phase approach:
      Phase A — announce media: Play composition via assist_satellite.announce
        (no mic, no pipeline). Waits for satellite to return to idle.
      Phase B — open mic once: Single start_conversation call. Satellite
        handles continuous conversation natively. Pyscript monitors for
        timeout, stop signal, pending requests, or idle timeout.
        ESPHome handles duplicate_wake_up recovery on-device.

    yaml
    name: Voice Session — Continuous Loop
    description: >-
      Two-phase: announce media, then open mic once with hot-context.
      Satellite handles continuous conversation. ESPHome self-heals
      duplicate_wake_up on-device.
    fields:
      satellite:
        name: Satellite Entity
        required: false
        selector:
          entity:
            domain: assist_satellite
      speaker:
        name: Speaker Entity
        required: false
        selector:
          entity:
            domain: media_player
      silence_media:
        name: Silence Media URL
        required: false
        selector:
          text:
      extra_system_prompt:
        name: Extra System Prompt
        description: For non-music callers. Music sessions use hot context.
        required: false
        selector:
          text:
            multiline: true
      timeout:
        name: Timeout (seconds)
        required: false
        default: 120
        selector:
          number:
            min: 10
            max: 600
      no_speech_limit:
        name: No-Speech Limit
        description: Kept for API compat; not used in simplified monitor.
        required: false
        default: 3
        selector:
          number:
            min: 1
            max: 10
      start_media_override:
        name: Start Media Override
        description: >-
          Media URL to announce before opening mic (e.g. composition).
          Played via assist_satellite.announce (no mic, no pipeline).
        required: false
        selector:
          text:
      feedback_question:
        name: Feedback Question
        description: Kept for API compat; agent asks naturally via hot context.
        required: false
        selector:
          text:
      feedback_context:
        name: Feedback Context
        description: >-
          "filename|cache_key" for hot context. Sets
          input_text.ai_music_feedback_context so agent sees composition
          info on every pipeline turn automatically.
        required: false
        selector:
          text:
    """
    if not satellite:
        satellite = (
            state.get("sensor.ai_last_satellite") or ""  # noqa: F821
        ).strip()
    if not satellite:
        log.warning("voice_session: continuous — no satellite")  # noqa: F821
        return {"status": "error", "error": "no satellite"}

    if not speaker:
        speaker = _speaker_map.get(satellite, "")

    sid = silence_media or SILENCE_MEDIA_ID
    deadline = time.monotonic() + (timeout or 120)
    first_media = (start_media_override or "").strip()

    # Activate stop signal
    try:
        service.call(  # noqa: F821
            "input_boolean", "turn_on",
            entity_id="input_boolean.ai_continuous_conversation_active",
        )
    except Exception as exc:
        log.warning("voice_session: continuous toggle failed: %s", exc)  # noqa: F821

    log.info(  # noqa: F821
        f"voice_session: continuous for {satellite}, timeout={timeout}s"
        f", announce={'yes' if first_media else 'no'}"
        f", feedback_ctx={'yes' if feedback_context else 'no'}"
    )

    # ── 1. Set hot context (agent sees it on every turn) ──────────
    if feedback_context:
        service.call(  # noqa: F821
            "input_text", "set_value",
            entity_id="input_text.ai_music_feedback_context",
            value=feedback_context[:255],
        )

    # ── Phase A: Announce composition (no mic, no pipeline) ──────────
    if first_media:
        log.info(  # noqa: F821
            f"voice_session: Phase A — announcing media via {satellite}"
        )
        service.call(  # noqa: F821
            "assist_satellite", "announce",
            entity_id=satellite,
            media_id=first_media,
            preannounce=False,
        )
        # Wait for satellite to leave idle (announcement started)
        for _ in range(10):
            if state.get(satellite) != "idle":  # noqa: F821
                break
            await asyncio.sleep(0.5)
        # Wait for satellite to return to idle (announcement finished)
        trig = task.wait_until(  # noqa: F821
            state_trigger=f"{satellite} == 'idle'",
            timeout=90,
            state_check_now=False,
        )
        if trig.get("trigger_type") == "timeout":
            log.warning(  # noqa: F821
                f"voice_session: Phase A media announce timeout for {satellite}"
            )
        else:
            await asyncio.sleep(0.5)  # Brief buffer after playback

    # ── Phase B: Open mic ONCE — satellite handles continuous ─────
    # If feedback_question is set, use start_message so the agent gets
    # an initial prompt and responds using hot context. Without this,
    # mic opens silently and the user has no cue to speak.
    if feedback_question:
        log.info(  # noqa: F821
            f"voice_session: Phase B — start_message on {satellite}"
        )
        service.call(  # noqa: F821
            "assist_satellite", "start_conversation",
            entity_id=satellite,
            start_message=feedback_question,
            preannounce=False,
            extra_system_prompt=extra_system_prompt or "",
        )
    else:
        log.info(  # noqa: F821
            f"voice_session: Phase B — opening mic on {satellite}"
        )
        service.call(  # noqa: F821
            "assist_satellite", "start_conversation",
            entity_id=satellite,
            start_media_id=sid,
            preannounce=False,
            extra_system_prompt=extra_system_prompt or "",
        )

    # ── Phase C: Monitor — wait for conversation to truly end ─────
    # Don't fight the satellite. Just watch for:
    #   - timeout deadline
    #   - stop signal (helper OFF)
    #   - new pending request (re-compose)
    #   - satellite idle for >5s (conversation truly ended)
    # ESPHome handles duplicate_wake_up recovery on-device.
    while time.monotonic() < deadline:
        if state.get("input_boolean.ai_continuous_conversation_active") == "off":  # noqa: F821
            log.info("voice_session: stop signal received")  # noqa: F821
            break

        pending = (
            state.get("input_text.ai_voice_session_pending") or ""  # noqa: F821
        ).strip()
        if pending:
            log.info("voice_session: new session request, exiting loop")  # noqa: F821
            break

        trig = task.wait_until(  # noqa: F821
            state_trigger=f"{satellite} == 'idle'",
            timeout=10,
            state_check_now=False,
        )
        if trig.get("trigger_type") != "timeout":
            # Satellite went idle — wait to confirm it stays idle.
            # (Satellite may auto-restart for continuous conversation.)
            await asyncio.sleep(5)
            if state.get(satellite) == "idle":  # noqa: F821
                log.info(  # noqa: F821
                    "voice_session: satellite idle 5s — conversation ended"
                )
                break  # Conversation truly ended

    # ── Cleanup ───────────────────────────────────────────────────
    if feedback_context:
        try:
            service.call(  # noqa: F821
                "input_text", "set_value",
                entity_id="input_text.ai_music_feedback_context",
                value="",
            )
        except Exception:
            pass

    try:
        service.call(  # noqa: F821
            "input_boolean", "turn_off",
            entity_id="input_boolean.ai_continuous_conversation_active",
        )
    except Exception:
        pass

    log.info(  # noqa: F821
        f"voice_session: continuous loop ended for {satellite}"
    )
    return {"status": "ok"}


# ── Request (Flag Writer) ───────────────────────────────────────────────────

@service(supports_response="optional")  # noqa: F821
async def voice_session_request(
    session_type: str = "music_feedback",
    file_path: str = "",
    player: str = "",
    agent: str = "",
    volume: float = 0.5,
    continuous: bool = True,
    continuous_timeout: float = 120,
):
    """Write JSON to ai_voice_session_pending to trigger post-pipeline automation.

    yaml
    name: Voice Session — Request
    description: >-
      Queue a voice session request. Triggers voice_session_mic automation
      after the current pipeline ends.
    fields:
      session_type:
        name: Session Type
        description: "music_feedback, interview, or custom."
        required: true
        selector:
          text:
      file_path:
        name: File Path
        description: Media file path (for music_feedback).
        required: false
        selector:
          text:
      player:
        name: Player Entity
        required: false
        selector:
          entity:
            domain: media_player
      agent:
        name: Agent Name
        required: false
        selector:
          text:
      volume:
        name: Volume
        required: false
        default: 0.5
        selector:
          number:
            min: 0
            max: 1
            step: 0.05
      continuous:
        name: Continuous
        required: false
        default: true
        selector:
          boolean:
      continuous_timeout:
        name: Continuous Timeout
        required: false
        default: 120
        selector:
          number:
            min: 10
            max: 600
    """
    payload = {
        "type": session_type,
        "file": file_path,
        "player": player,
        "agent": agent,
        "volume": volume,
        "continuous": continuous,
        "continuous_timeout": continuous_timeout,
    }

    json_str = _json.dumps(payload)

    if len(json_str) > 255:
        log.warning(  # noqa: F821
            f"voice_session: payload too long ({len(json_str)}), truncating"
        )
        payload["file"] = payload["file"][-80:] if payload["file"] else ""
        json_str = _json.dumps(payload)

    service.call(  # noqa: F821
        "input_text", "set_value",
        entity_id="input_text.ai_voice_session_pending",
        value=json_str,
    )

    log.info(  # noqa: F821
        f"voice_session: request queued — type={session_type} player={player}"
    )
    return {"status": "ok", "payload": payload}


# ── Startup ──────────────────────────────────────────────────────────────────

async def _run_discovery():
    """Fetch satellite device mappings from dispatcher cache."""
    global _select_map, _speaker_map
    try:
        result = service.call(  # noqa: F821
            "pyscript", "dispatcher_get_satellite_maps",
            return_response=True,
        )
        _select_map = (result or {}).get("satellite_select_map", {})
        _speaker_map = (result or {}).get("satellite_speaker_map", {})
    except Exception as exc:
        log.warning(  # noqa: F821
            f"voice_session: dispatcher_get_satellite_maps failed: {exc}"
        )
    log.warning(  # noqa: F821
        f"voice_session.py — discovered "
        f"{len(_speaker_map)} speakers, {len(_select_map)} satellites: "
        f"{list(_speaker_map.keys())}"
    )


@time_trigger("startup")  # noqa: F821
async def _voice_session_startup():
    # Wait for dispatcher cache to populate (satellite maps live there now)
    await asyncio.sleep(25)
    await _run_discovery()


@service  # noqa: F821
async def voice_session_rediscover():
    """
    yaml
    name: Voice Session — Rediscover
    description: Re-fetch satellite device mappings from dispatcher cache.
    """
    await _run_discovery()
    return {"speaker_map": _speaker_map, "select_map": _select_map}
