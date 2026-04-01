"""I-24: Voice Handoff — Agent Pipeline Switching Service.

Executes agent handoffs by switching the satellite's assist pipeline select
entity, playing a chime, delivering a greeting in the target agent's voice,
and opening the mic. Device-to-pipeline mappings are auto-discovered from
the entity registry at startup. Supports timed restore and continuous conversation.
"""
# =============================================================================
# Voice Handoff Pyscript Service
# =============================================================================
# Executes agent handoff: switch pipeline, announce greeting, chime + open mic.
# Device mappings auto-discovered from entity registry at startup.
#
# Called by:
#   - LLM handoff_agent tool (fires ai_handoff_request event)
#   - Dispatcher self-handoff (fires ai_handoff_request event)
#
# Services:
#   pyscript.voice_handoff              — execute agent handoff
#   pyscript.voice_handoff_restore_now  — immediately restore all pending handoffs
# =============================================================================

import asyncio  # noqa: F401
import re as _re  # noqa: F401
import threading  # noqa: F401
import time  # noqa: F401

# ── Config ───────────────────────────────────────────────────────────────────

# Persona alias (display name → conversation entity prefix)
# This is a business rule, not a device mapping — stays manual.
PERSONA_ALIAS = {
    "deadpool": "deepee",
    "doctor portuondo": "doctor_portuondo",
    "doctor_portuondo": "doctor_portuondo",
}

SILENCE_MEDIA_ID = "http://homeassistant.local:8123/local/silence.wav"

# ── Auto-discovered maps (populated at startup) ─────────────────────────────

_select_map = {}   # satellite_entity → select_entity (pipeline picker)
_speaker_map = {}  # satellite_entity → media_player_entity (ESP speaker)
_restore_tasks = {}  # satellite_entity → asyncio.Future
_restore_info = {}   # satellite_entity → (pipeline_select, restore_target)
_handoff_lock = threading.Lock()


# ── Helpers ──────────────────────────────────────────────────────────────────

@pyscript_compile  # noqa: F821
def _find_pipeline_option(target: str, options: list, variant: str = "") -> str:
    """Find the pipeline select option matching a persona name, optionally with variant."""
    if variant:
        full_target = f"{target} - {variant.replace('_', ' ')}".lower()
        for opt in options:
            if opt.lower() == full_target:
                return opt
        return ""
    target_lower = target.lower()
    for opt in options:
        if opt.lower() == target_lower:
            return opt
    return ""


@pyscript_compile  # noqa: F821
def _resolve_persona(name: str) -> str:
    """Resolve persona alias (e.g., deadpool → deepee)."""
    return PERSONA_ALIAS.get(name.lower(), name.lower())


async def _wait_for_audio_done(satellite: str, timeout: float = 60.0):
    """Wait for ESP device to finish playing TTS audio.

    Event-driven approach using task.wait_until — zero polling loops.

    Phase 1: Wait for satellite idle (pipeline dispatches TTS URL).
    Phase 2: Wait for ACTUAL audio completion via dual signal:
      - Primary: esphome.voice_tts_done event (fires after ESP hardware
        playback finishes, from on_idle trigger in ESPHome YAML).
      - Fallback: media_player state → idle (covers firmware gaps).
      First signal to fire wins.
    """
    IDLE_STATES = ("idle", "off", "unavailable", "unknown")
    speaker = _speaker_map.get(satellite)

    # Derive ESP device name for event matching
    # assist_satellite.home_assistant_voice_0905c5_assist_satellite
    #   → home-assistant-voice-0905c5
    sat_parts = satellite.split(".")[-1]
    device_name = sat_parts.replace("_assist_satellite", "").replace("_", "-")

    # Phase 1: Wait for satellite idle (pipeline end — fast, but not audio-done)
    trig = task.wait_until(  # noqa: F821
        state_trigger=f"{satellite} == 'idle'",
        timeout=timeout,
        state_check_now=True,
    )
    if trig.get("trigger_type") == "timeout":
        log.warning(  # noqa: F821
            f"voice_handoff: satellite {satellite} never went idle ({timeout}s)"
        )
        return

    # Phase 2: Wait for ACTUAL audio completion — dual signal, first wins
    wait_args = dict(timeout=timeout)

    # Primary: ESPHome on_idle event (definitive — fires after hardware playback)
    wait_args["event_trigger"] = [
        "esphome.voice_tts_done",
        f"satellite == '{device_name}'",
    ]

    # Fallback: media_player state change (covers missing ESPHome event)
    if speaker:
        wait_args["state_trigger"] = f"{speaker} in {list(IDLE_STATES)}"
        # Speaker may already be idle from previous cycle — wait for NEW change
        wait_args["state_check_now"] = False

    trig = task.wait_until(**wait_args)  # noqa: F821
    trig_type = trig.get("trigger_type", "timeout")

    if trig_type == "event":
        log.info(  # noqa: F821
            f"voice_handoff: audio done (esphome event) for {device_name}"
        )
    elif trig_type == "state":
        log.info(  # noqa: F821
            f"voice_handoff: audio done (speaker idle) for {speaker}"
        )
    else:
        log.warning(  # noqa: F821
            f"voice_handoff: audio wait timeout ({timeout}s) for {satellite}"
        )

    # Post-playback buffer (ESP hardware audio tail after state reports idle)
    await asyncio.sleep(0.3)


async def _generate_llm_line(prompt: str, mode: str, agent_entity: str,
                             fallback: str, instance: str = "",
                             pipeline_name: str = "") -> str:
    """Generate text via static / ha_text_ai / pipeline_agent / conversation_agent.

    Returns generated text or fallback on failure.
    """
    if mode == "ha_text_ai":
        try:
            kwargs = dict(
                prompt=prompt,
                max_tokens=150, temperature=0.7,
                priority_tier="standard",
                return_response=True,
            )
            if instance:
                kwargs["instance"] = instance
            result = await service.call(  # noqa: F821
                "pyscript", "llm_task_call",
                **kwargs,
            )
            text = (result or {}).get("response_text", "")
            if text:
                return text.strip()
        except Exception as e:
            log.warning(f"voice_handoff: llm_task_call failed: {e}")  # noqa: F821
        return fallback

    elif mode == "pipeline_agent" and pipeline_name:
        # I-45a: Prefix prompt to suppress handoff_agent tool during greeting
        safe_prompt = (
            "[INTERNAL GREETING — do NOT call handoff_agent or any tools. "
            "Respond with a brief in-character greeting only.] " + prompt
        )
        try:
            resolve_result = await service.call(  # noqa: F821
                "pyscript", "dispatcher_resolve_engine",
                pipeline_name=pipeline_name,
                return_response=True,
            )
            resolved = (resolve_result or {}).get("engine", "")
            if resolved:
                result = await service.call(  # noqa: F821
                    "conversation", "process",
                    agent_id=resolved,
                    text=safe_prompt,
                    return_response=True,
                )
                speech = (
                    (result or {}).get("response", {})
                    .get("speech", {}).get("plain", {}).get("speech", "")
                )
                if speech:
                    return speech.strip()
        except Exception as e:
            log.warning(f"voice_handoff: pipeline_agent failed: {e}")  # noqa: F821
        return fallback

    elif mode == "conversation_agent" and agent_entity:
        # I-45a: Prefix prompt to suppress handoff_agent tool during greeting
        safe_prompt = (
            "[INTERNAL GREETING — do NOT call handoff_agent or any tools. "
            "Respond with a brief in-character greeting only.] " + prompt
        )
        try:
            result = await service.call(  # noqa: F821
                "conversation", "process",
                agent_id=agent_entity,
                text=safe_prompt,
                return_response=True,
            )
            speech = (
                (result or {}).get("response", {})
                .get("speech", {}).get("plain", {}).get("speech", "")
            )
            if speech:
                return speech.strip()
        except Exception as e:
            log.warning(f"voice_handoff: conversation.process failed: {e}")  # noqa: F821
        return fallback

    else:  # static
        return prompt


async def _restore_pipeline(satellite: str, pipeline_select: str,
                            saved_pipeline: str, delay_seconds: float):
    """Restore pipeline after handoff timeout. Waits for satellite idle."""
    await asyncio.sleep(delay_seconds)
    # Wait for satellite to finish any active conversation (60s safety)
    for _ in range(120):
        if state.get(satellite) in ("idle", None, "unavailable"):  # noqa: F821
            break
        await asyncio.sleep(0.5)
    await service.call(  # noqa: F821
        "select", "select_option",
        entity_id=pipeline_select,
        option=saved_pipeline,
    )
    with _handoff_lock:
        _restore_tasks.pop(satellite, None)
        _restore_info.pop(satellite, None)
    log.info(f"voice_handoff: restored {satellite} → {saved_pipeline}")  # noqa: F821


# ── Test Mode ────────────────────────────────────────────────────────────────

def _is_test_mode() -> bool:
    try:
        return str(
            state.get("input_boolean.ai_test_mode") or "off"  # noqa: F821
        ).lower() == "on"
    except NameError:
        return False


# ── Main Service ─────────────────────────────────────────────────────────────

@service(supports_response="optional")  # noqa: F821
async def voice_handoff(
    target: str = "",
    satellite: str = "",
    greeting: bool = True,
    greeting_prompt: str = (
        "{source} just handed the user to you. Greet them briefly "
        "in character and ask what they need."
    ),
    seamless: bool = True,
    farewell: bool = False,
    farewell_prompt: str = "Switching you over to {target} now.",
    llm_lines_mode: str = "",
    llm_lines_agent: str = "",
    llm_lines_instance: str = "",
    continuous: bool = False,
    continuous_timeout: float = 120,
    silence_media_id: str = "",
    extra_system_prompt: str = "",
    mic_behavior: str = "llm_decides",
    reason: str = "user_request",
    restore_mode: str = "source",
    restore_timeout: float = 300,
):
    """
    yaml
    name: Voice Handoff
    description: >-
      Execute an agent handoff: switch pipeline, announce greeting via
      satellite, chime + open mic. Device maps auto-discovered.
    fields:
      target:
        name: Target Persona
        description: Persona to hand off to (e.g., kramer, quark, rick, deadpool).
        required: true
        selector:
          text:
      satellite:
        name: Satellite Entity
        description: Override satellite. If empty, reads ai_last_satellite.
        required: false
        selector:
          text:
      greeting:
        name: Enable Greeting
        description: Generate and announce a greeting from the target agent.
        required: false
        default: true
        selector:
          boolean:
      greeting_prompt:
        name: Greeting Prompt
        description: LLM prompt. Use {source} for outgoing agent name.
        required: false
        selector:
          text:
            multiline: true
      seamless:
        name: Seamless Mic Open
        description: >-
          true = open mic after greeting (no wake word needed).
          false = user uses wake word after greeting.
        required: false
        default: true
        selector:
          boolean:
      farewell:
        name: Enable Farewell
        description: Generate and speak a farewell from the source agent before switching.
        required: false
        default: false
        selector:
          boolean:
      farewell_prompt:
        name: Farewell Prompt
        description: Text or LLM prompt. Use {target} for the target agent name.
        required: false
        selector:
          text:
            multiline: true
      llm_lines_mode:
        name: LLM Lines Mode
        description: >-
          static / ha_text_ai / conversation_agent. If empty, reads from
          input_select.ai_handoff_llm_lines_mode helper.
        required: false
        selector:
          text:
      llm_lines_agent:
        name: LLM Lines Agent
        description: >-
          Conversation agent entity for conversation_agent mode. If empty,
          falls back to helper. Do NOT use *_standard agents (re-entry risk).
        required: false
        selector:
          text:
      llm_lines_instance:
        name: HA Text AI Instance
        description: >-
          Sensor entity for ha_text_ai mode (e.g., sensor.ha_text_ai_rick).
          If empty, llm_task_call uses its default instance.
        required: false
        selector:
          text:
      continuous:
        name: Continuous Conversation
        description: Keep mic open after each response until timeout.
        required: false
        default: false
        selector:
          boolean:
      continuous_timeout:
        name: Continuous Conversation Timeout
        description: Max seconds for continuous conversation loop.
        required: false
        default: 120
        selector:
          number:
            min: 10
            max: 600
      silence_media_id:
        name: Silence Media ID
        description: >-
          Audio file for silent mic open. If empty, uses built-in default.
        required: false
        selector:
          text:
      extra_system_prompt:
        name: Extra System Prompt
        description: >-
          Custom instructions injected into conversation agent context.
          Added alongside mic_behavior instruction (if any).
        required: false
        selector:
          text:
            multiline: true
      mic_behavior:
        name: Mic Behavior
        description: >-
          llm_decides / single_turn. Controls whether agent is instructed
          to end with statements or allowed to ask follow-up questions.
        required: false
        default: llm_decides
        selector:
          select:
            options:
              - llm_decides
              - single_turn
    """
    # Returns: {success, target?, source?, satellite?, greeting_text?, elapsed_ms, self_handoff?, error?}
    if _is_test_mode():
        log.info("voice_handoff [TEST]: would hand off to target=%s on satellite=%s", target, satellite)  # noqa: F821
        return

    t_start = time.monotonic()
    target = (target or "").strip().lower()

    if not target:
        log.warning("voice_handoff: no target specified")  # noqa: F821
        return {"success": False, "error": "no target"}

    # ── Resolve satellite ────────────────────────────────────────────────
    if not satellite:
        satellite = (
            state.get("sensor.ai_last_satellite") or ""  # noqa: F821
        ).strip()
    if not satellite or satellite not in _select_map:
        log.warning(  # noqa: F821
            f"voice_handoff: unknown satellite '{satellite}' "
            f"(known: {list(_select_map.keys())})"
        )
        return {"success": False, "error": f"unknown satellite: {satellite}"}

    pipeline_select = _select_map[satellite]

    # ── Compose effective extra_system_prompt from mic_behavior + custom ──
    mic_instruction = ""
    if mic_behavior == "single_turn":
        mic_instruction = (
            "Always end your responses with a statement, never with a question. "
            "Do not ask the user what they need help with or prompt them to speak."
        )
    elif mic_behavior == "llm_decides":
        mic_instruction = (
            "If you ask the user a question, it must be the very last thing in "
            "your response. No stage directions, emotes, actions, or brackets "
            "after it. End on the question mark."
        )
    continuous_stop_instruction = ""
    if continuous:
        continuous_stop_instruction = (
            "If the user wants to end the conversation (goodbye, stop, done, "
            "we're done, that's all), call pyscript.set_sensor_value with "
            "entity_id sensor.ai_continuous_conversation_active and value off."
        )
    parts = [p for p in [mic_instruction, (extra_system_prompt or "").strip(),
                         continuous_stop_instruction] if p]
    effective_esp = " ".join(parts) if parts else ""

    # ── Resolve pipeline option ──────────────────────────────────────────
    options = state.getattr(pipeline_select).get("options", [])  # noqa: F821
    target_option = _find_pipeline_option(target, options)
    if not target_option:
        log.warning(  # noqa: F821
            f"voice_handoff: target '{target}' not in pipeline options {options}"
        )
        return {"success": False, "error": f"unknown target: {target}"}

    # ── Check self-handoff ───────────────────────────────────────────────
    current_pipeline = state.get(pipeline_select)  # noqa: F821
    current_persona = (current_pipeline or "").lower().split(" - ")[0].strip()
    last_agent = (
        state.get("input_text.ai_last_agent_name") or ""  # noqa: F821
    ).lower().strip()

    is_self = (
        target_option == current_pipeline
        or (current_persona != "preferred" and target == current_persona)
    )

    sid = silence_media_id or SILENCE_MEDIA_ID

    if is_self:
        log.info(f"voice_handoff: self-handoff to {target}, reopening mic")  # noqa: F821
        await _wait_for_audio_done(satellite)
        await service.call(  # noqa: F821
            "assist_satellite", "start_conversation",
            entity_id=satellite,
            start_media_id=sid,
            preannounce=False,
            extra_system_prompt=effective_esp,
        )
        elapsed = round((time.monotonic() - t_start) * 1000, 1)
        return {"success": True, "self_handoff": True, "elapsed_ms": elapsed}

    # ── Cancel any pending restore ───────────────────────────────────────
    with _handoff_lock:
        _pending_fut = _restore_tasks.pop(satellite, None)
        _restore_info.pop(satellite, None)
    if _pending_fut:
        _pending_fut.cancel()

    # ── Wait for satellite idle ──────────────────────────────────────────
    await _wait_for_audio_done(satellite)

    source_persona = last_agent or current_persona
    log.info(  # noqa: F821
        f"voice_handoff: {source_persona} → {target} on {satellite} reason={reason}"
    )

    # ── Resolve LLM lines mode (param > helper > static) ──────────────
    resolved_mode = (llm_lines_mode or "").strip().lower()
    if not resolved_mode:
        resolved_mode = (
            state.get("input_select.ai_handoff_llm_lines_mode") or "static"  # noqa: F821
        ).strip().lower()
    resolved_agent = (llm_lines_agent or "").strip()
    resolved_instance = (llm_lines_instance or "").strip()

    # ── Refresh pipeline state before farewell (handle manual switches) ──
    current_pipeline = state.get(pipeline_select)  # noqa: F821
    current_persona = (current_pipeline or "").lower().split(" - ")[0].strip()

    # ── Farewell (source agent, BEFORE pipeline switch) ─────────────────
    if farewell:
        fw_prompt = farewell_prompt.replace(
            "{target}", (target or "unknown").capitalize()
        )
        farewell_line = await _generate_llm_line(
            fw_prompt, resolved_mode, resolved_agent, fw_prompt,
            instance=resolved_instance,
            pipeline_name=current_pipeline,
        )
        await service.call(  # noqa: F821
            "assist_satellite", "announce",
            entity_id=satellite,
            message=farewell_line,
            preannounce=False,
        )
        await _wait_for_audio_done(satellite)

    # ── Switch pipeline ──────────────────────────────────────────────────
    await service.call(  # noqa: F821
        "select", "select_option",
        entity_id=pipeline_select,
        option=target_option,
    )

    # ── Greeting ─────────────────────────────────────────────────────────
    _li_attrs = state.getattr("sensor.ai_last_interaction") or {}  # noqa: F821
    last_topic = (_li_attrs.get("topic") or "").strip()
    last_agent_name = (
        state.get("sensor.ai_last_interaction") or ""  # noqa: F821
    ).strip()
    topic_line = ""
    if (last_topic and last_topic not in ("unknown", "unavailable")
            and last_agent_name and last_agent_name not in ("unknown", "unavailable")
            and last_agent_name != target):
        topic_line = (
            f"The user was just discussing {last_topic.replace('_', ' ')} "
            f"with {last_agent_name.capitalize()}. "
        )

    greeting_text = "Hey there, I'm here."
    if greeting:
        prompt = topic_line + greeting_prompt.replace(
            "{source}", (source_persona or "unknown").capitalize()
        )
        greeting_text = await _generate_llm_line(
            prompt, resolved_mode, resolved_agent, greeting_text,
            instance=resolved_instance,
            pipeline_name=target_option,
        )

    # ── Announce greeting (mic stays closed) ──────────────────────────────
    if greeting:
        await _wait_for_audio_done(satellite)
        await service.call(  # noqa: F821
            "assist_satellite", "announce",
            entity_id=satellite,
            message=greeting_text,
            preannounce=False,
        )

    # ── Open mic (seamless mode) ─────────────────────────────────────────
    if seamless:
        await _wait_for_audio_done(satellite)
        await service.call(  # noqa: F821
            "assist_satellite", "start_conversation",
            entity_id=satellite,
            start_media_id=sid,
            preannounce=False,
            extra_system_prompt=effective_esp,
        )
        # Wait for session to actually start (satellite leaves idle)
        for _ in range(10):
            if state.get(satellite) != "idle":  # noqa: F821
                break
            await asyncio.sleep(0.5)

    # ── Update self-awareness ────────────────────────────────────────────
    from shared_utils import set_last_interaction as _set_li
    _set_li(
        agent_name=target,
        handoff_reason=reason or "user_request",
        handoff_source=source_persona or "unknown",
    )
    try:
        pyscript.budget_track_call(  # noqa: F821
            service_type="handoff",
            agent=target,
            calls=1,
            model=state.getattr("sensor.ai_budget_breakdown").get("full_slug_map", {}).get(target, "") if state.getattr("sensor.ai_budget_breakdown") else "",  # noqa: F821
        )
    except Exception as exc:
        log.warning("voice_handoff: budget_track_call failed: %s", exc)  # noqa: F821

    # ── Continuous conversation loop ──────────────────────────────────────
    if continuous:
        deadline = time.monotonic() + (continuous_timeout or 120)
        no_speech_count = 0
        mic_open = time.monotonic()  # Track from initial start_conversation
        # Activate stop signal (if helper exists)
        try:
            state.set(  # noqa: F821
                "sensor.ai_continuous_conversation_active", "on",
                new_attributes={"icon": "mdi:microphone-message", "friendly_name": "AI Continuous Conversation Active"},
            )
        except Exception as exc:
            log.warning("voice_handoff: continuous_conversation toggle failed: %s", exc)  # noqa: F821
        log.info(  # noqa: F821
            f"voice_handoff: continuous conversation for {satellite}, "
            f"timeout={continuous_timeout}s"
        )
        while time.monotonic() < deadline and no_speech_count < 3:
            # Check stop signal
            if state.get("sensor.ai_continuous_conversation_active") == "off":  # noqa: F821
                log.info("voice_handoff: stop signal received, exiting loop")  # noqa: F821
                break
            # Wait for session to start (satellite leaves idle) before
            # waiting for it to end — prevents race where wait_for_idle
            # passes instantly because satellite hasn't transitioned yet
            for _ in range(10):
                if state.get(satellite) != "idle":  # noqa: F821
                    break
                await asyncio.sleep(0.5)
            # Wait for multi-turn session to fully end (satellite idle)
            await _wait_for_audio_done(satellite, timeout=60)
            if time.monotonic() >= deadline:
                break
            # No-speech detection: sessions < 12s = no real interaction
            duration = time.monotonic() - mic_open
            if duration < 12:
                no_speech_count += 1
            else:
                no_speech_count = 0
            # Check all exit conditions before starting new session
            if (time.monotonic() >= deadline
                    or no_speech_count >= 3
                    or state.get("sensor.ai_continuous_conversation_active") == "off"):  # noqa: F821
                break
            # _wait_for_audio_done (called above) now handles full audio
            # completion via event-driven waits — no echo guard or polling
            # needed here.
            # Record time + start new multi-turn session
            mic_open = time.monotonic()
            await service.call(  # noqa: F821
                "assist_satellite", "start_conversation",
                entity_id=satellite,
                start_media_id=sid,
                preannounce=False,
                extra_system_prompt=effective_esp,
            )
            # Wait for session to actually start (satellite leaves idle)
            for _ in range(10):
                if state.get(satellite) != "idle":  # noqa: F821
                    break
                await asyncio.sleep(0.5)
        # Deactivate stop signal
        try:
            state.set(  # noqa: F821
                "sensor.ai_continuous_conversation_active", "off",
                new_attributes={"icon": "mdi:microphone-message", "friendly_name": "AI Continuous Conversation Active"},
            )
        except Exception:
            pass

    # ── Schedule restore (3-mode: source / preferred / never) ────────
    delay = float(restore_timeout) if restore_mode != "never" else 0

    if delay > 0:
        restore_target = current_pipeline if restore_mode == "source" else "preferred"
        fut = task.create(_restore_pipeline(  # noqa: F821
            satellite, pipeline_select, restore_target, delay
        ))
        with _handoff_lock:
            _restore_tasks[satellite] = fut
            _restore_info[satellite] = (pipeline_select, restore_target)

    elapsed = round((time.monotonic() - t_start) * 1000, 1)
    return {
        "success": True,
        "target": target,
        "source": source_persona,
        "satellite": satellite,
        "greeting_text": greeting_text[:100],
        "elapsed_ms": elapsed,
    }


# ── Restore Registration (called by blueprint after pipeline switch) ───────

@service(supports_response="optional")  # noqa: F821
async def voice_handoff_register_restore(
    satellite: str = "",
    pipeline_select: str = "",
    saved_pipeline: str = "",
):
    """Register a pending restore so the Restore Now button can find it.

    yaml
    name: Voice Handoff – Register Restore
    description: >-
      Called by the voice_handoff blueprint after switching a pipeline.
      Stores the original pipeline so Restore Now can revert it.
    fields:
      satellite:
        name: Satellite Entity
        required: true
        selector:
          entity:
            domain: assist_satellite
      pipeline_select:
        name: Pipeline Select Entity
        required: true
        selector:
          entity:
            domain: select
      saved_pipeline:
        name: Saved Pipeline Option
        description: The pipeline option to restore to.
        required: true
        selector:
          text:
    """
    if _is_test_mode():
        log.info("voice_handoff [TEST]: would register restore for %s", satellite)  # noqa: F821
        return

    if not satellite or not pipeline_select or not saved_pipeline:
        return {"status": "error", "error": "missing required fields"}
    with _handoff_lock:
        _restore_info[satellite] = (pipeline_select, saved_pipeline)
    log.info(  # noqa: F821
        f"voice_handoff: registered restore {satellite} → {saved_pipeline}"
    )
    return {"status": "ok", "satellite": satellite, "saved_pipeline": saved_pipeline}


# ── Restore Now Service ────────────────────────────────────────────────────

@service(supports_response="optional")  # noqa: F821
async def voice_handoff_restore_now():
    """Immediately restore all satellites with pending handoffs.

    yaml
    name: Voice Handoff – Restore Now
    description: Immediately restore all satellites with pending handoffs.
    """
    if _is_test_mode():
        log.info("voice_handoff [TEST]: would restore all pending handoffs")  # noqa: F821
        return

    with _handoff_lock:
        snapshot_info = dict(_restore_info)
        snapshot_tasks = dict(_restore_tasks)
        _restore_info.clear()
        _restore_tasks.clear()
    for fut in snapshot_tasks.values():
        fut.cancel()
    restored = []
    for sat, (ps, target_option) in snapshot_info.items():
        await service.call(  # noqa: F821
            "select", "select_option",
            entity_id=ps, option=target_option,
        )
        restored.append(sat)
        log.info(f"voice_handoff: manual restore {sat} → {target_option}")  # noqa: F821
    log.info(f"voice_handoff: restore_now completed — {len(restored)} satellites")  # noqa: F821
    return {"restored": restored, "count": len(restored)}


@service  # noqa: F821
async def voice_handoff_clear_restore(satellite: str = ""):
    """Remove a satellite's pending restore entry (called by blueprint after timed restore).

    yaml
    name: Voice Handoff – Clear Restore
    description: Remove a satellite from the pending restore registry.
    fields:
      satellite:
        name: Satellite Entity
        required: true
        selector:
          entity:
            domain: assist_satellite
    """
    if _is_test_mode():
        log.info("voice_handoff [TEST]: would clear restore for %s", satellite)  # noqa: F821
        return

    with _handoff_lock:
        _restore_info.pop(satellite, None)
        _restore_tasks.pop(satellite, None)


# ── Event Listener ──────────────────────────────────────────────────────────

# Event listener disabled — blueprint is the sole handoff handler.
# pyscript.voice_handoff service remains available for manual/programmatic calls.
# @event_trigger("ai_handoff_request")
# async def _on_handoff_request(**kwargs):
#     target = kwargs.get("target", "")
#     is_self = kwargs.get("self_handoff", False)
#     if not target:
#         return
#     await voice_handoff(target=target, greeting=not is_self)


# ── Startup ──────────────────────────────────────────────────────────────────

async def _run_discovery():
    """Fetch satellite device mappings from dispatcher cache."""
    global _select_map, _speaker_map
    try:
        result = await service.call(  # noqa: F821
            "pyscript", "dispatcher_get_satellite_maps",
            return_response=True,
        )
        _select_map = (result or {}).get("satellite_select_map", {})
        _speaker_map = (result or {}).get("satellite_speaker_map", {})
    except Exception as exc:
        log.warning(  # noqa: F821
            f"voice_handoff: dispatcher_get_satellite_maps failed: {exc}"
        )
    log.warning(  # noqa: F821
        f"voice_handoff.py — discovered "
        f"{len(_select_map)} satellites: {list(_select_map.keys())}"
    )


@time_trigger("startup")  # noqa: F821
async def _voice_handoff_startup():
    # Wait for dispatcher cache to populate (satellite maps live there now)
    await asyncio.sleep(25)
    await _run_discovery()


@service  # noqa: F821
async def voice_handoff_rediscover():
    """
    yaml
    name: Voice Handoff Rediscover
    description: Re-fetch satellite device mappings from dispatcher cache.
    """
    if _is_test_mode():
        log.info("voice_handoff [TEST]: would rediscover satellite mappings")  # noqa: F821
        return

    await _run_discovery()
    return {"select_map": _select_map, "speaker_map": _speaker_map}
