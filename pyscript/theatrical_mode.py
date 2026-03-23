"""
Theatrical Mode — Pattern 4: Multi-Agent Orchestrated Debate.

pyscript/theatrical_mode.py

Services:
  pyscript.theatrical_mode_start  — Orchestrate a multi-turn debate
  pyscript.theatrical_mode_stop   — Stop a running exchange

Fixes applied (plan audit 2026-03-23):
  C1: service.call for input_boolean/datetime (not state.set)
  C2: Timeout via conversation_with_timeout
  C3: Own pipeline cache with _ensure_cache()
  H2: Satellite idle re-check before each TTS
  H3: Context via text parameter injection
  H4: Capture tts_queue_speak response
  H5: Satellite idle wait in guards
  M1: No generator expressions (AP-57)
  M2: @pyscript_executor on file I/O and regex
  M3: Dedup guard for double-fire
  M4: ask_question sequential call documentation
  M5: input_datetime update via service call

Dependencies:
  pyscript/common_utilities.py  (conversation_with_timeout)
  pyscript/tts_queue.py         (tts_queue_speak)
  pyscript/agent_dispatcher.py  (dispatcher_resolve_engine — fallback)
  /config/.storage/assist_pipeline.pipelines
  /config/pyscript/tts_speaker_config.json
"""

import asyncio
import time
import random

# ── Constants ──────────────────────────────────────────────────────────────
PIPELINE_FILE = "/config/.storage/assist_pipeline.pipelines"
SPEAKER_CONFIG = "/config/pyscript/tts_speaker_config.json"

# ── Module-level cache ─────────────────────────────────────────────────────
_cache = None
_cache_ts = 0
_SANITIZE_PATTERNS = None


# ═══════════════════════════════════════════════════════════════════════════
# Helper readers
# ═══════════════════════════════════════════════════════════════════════════

def _helper_int(entity_id, default):
    """Read an integer helper value with safe fallback."""
    try:
        val = state.get(entity_id)
        if val and val not in ("unknown", "unavailable", ""):
            return int(float(val))
    except Exception:
        pass
    return default


def _helper_float(entity_id, default):
    """Read a float helper value with safe fallback."""
    try:
        val = state.get(entity_id)
        if val and val not in ("unknown", "unavailable", ""):
            return float(val)
    except Exception:
        pass
    return default


def _helper_str(entity_id, default):
    """Read a string helper value with safe fallback."""
    try:
        val = state.get(entity_id)
        if val and val not in ("unknown", "unavailable", ""):
            return str(val)
    except Exception:
        pass
    return default


# ═══════════════════════════════════════════════════════════════════════════
# Pipeline cache — C3 fix (own cache, batch resolution)
# ═══════════════════════════════════════════════════════════════════════════

@pyscript_executor  # noqa: F821
def _load_pipelines_sync():
    """Load and parse pipeline data from assist_pipeline storage."""
    import json as _json
    try:
        with open(PIPELINE_FILE, "r") as f:
            data = _json.load(f)
        items = data.get("data", {}).get("items", [])

        personas = []
        name_to_engine = {}
        name_to_tts = {}

        for p in items:
            name = (p.get("name") or "").strip()
            if not name:
                continue
            name_lower = name.lower()
            base_name = name.split(" - ")[0].strip().lower()
            conv_engine = p.get("conversation_engine") or ""
            tts_engine = p.get("tts_engine") or ""

            personas.append(name)
            name_to_engine[name_lower] = conv_engine
            if base_name != name_lower:
                name_to_engine.setdefault(base_name, conv_engine)
            name_to_tts[name_lower] = tts_engine
            if base_name != name_lower:
                name_to_tts.setdefault(base_name, tts_engine)

        return {
            "personas": personas,
            "name_to_engine": name_to_engine,
            "name_to_tts": name_to_tts,
        }
    except Exception as e:
        return {
            "personas": [], "name_to_engine": {}, "name_to_tts": {},
            "error": str(e),
        }


async def _ensure_cache():
    """Lazy-load pipeline cache with configurable TTL."""
    global _cache, _cache_ts
    ttl = _helper_float("input_number.ai_dispatcher_cache_ttl", 300)
    if _cache and _cache.get("personas") and (time.monotonic() - _cache_ts) < ttl:
        return _cache
    log.info("theatrical: loading pipeline cache")
    _cache = await _load_pipelines_sync()
    _cache_ts = time.monotonic()
    if _cache.get("error"):
        log.warning("theatrical: cache load error: %s", _cache["error"])
    else:
        log.info("theatrical: cached %d pipelines", len(_cache.get("personas", [])))
    return _cache


# ═══════════════════════════════════════════════════════════════════════════
# Speaker resolution — M2 fix (@pyscript_executor for file I/O)
# ═══════════════════════════════════════════════════════════════════════════

@pyscript_executor  # noqa: F821
def _resolve_speakers_sync(zone):
    """Resolve zone speakers from tts_speaker_config.json."""
    import json as _json
    try:
        with open(SPEAKER_CONFIG, "r") as f:
            config = _json.load(f)
        zone_map = config.get("zone_speaker_map", {})
        speakers = zone_map.get(zone, [])
        if not speakers:
            # Fall back to first zone with speakers
            for z_speakers in zone_map.values():
                if z_speakers:
                    speakers = z_speakers
                    break
        return {"explicit": False, "speakers": speakers}
    except Exception:
        return {"explicit": False, "speakers": []}


# ═══════════════════════════════════════════════════════════════════════════
# Response sanitization — M2 fix (@pyscript_executor for regex)
# ═══════════════════════════════════════════════════════════════════════════

@pyscript_executor  # noqa: F821
def _build_sanitize_patterns_sync():
    """Build regex patterns for stripping tool narration from LLM output."""
    import re as _re
    return [
        # Tool narration: "I'll call execute_service..." etc.
        _re.compile(
            r"(?:i(?:'ll| will| am going to)?|let me|calling|using)"
            r"\s+(?:call|use|invoke|run|execute|trigger)"
            r"\s+(?:the\s+)?(?:execute_service|handoff_agent|escalate_action|"
            r"start_debate|memory_\w+|calendar_\w+)\b[^.!?]*[.!?]?",
            _re.IGNORECASE,
        ),
        # Entity IDs: "light.kitchen", "input_boolean.ai_foo"
        _re.compile(
            r"\b(?:light|switch|sensor|input_boolean|input_number|"
            r"input_select|media_player|climate|cover|fan|lock|"
            r"binary_sensor|automation|script|scene)\.[a-z_0-9]+\b"
        ),
        # JSON fragments: {"key": "value"}
        _re.compile(r'\{["\']?\w+["\']?\s*:\s*["\']?[^}]+\}'),
        # Multi-space cleanup
        _re.compile(r"\s{2,}"),
        # Leading punctuation cleanup
        _re.compile(r"^[\s,;.!?\u2014\u2013-]+"),
    ]


@pyscript_executor  # noqa: F821
def _apply_sanitize_sync(text, patterns):
    """Apply sanitization patterns (native Python for regex ops)."""
    if not text or not patterns:
        return text
    content_pats = patterns[:-2]
    ws_pat = patterns[-2]
    lead_pat = patterns[-1]
    for pat in content_pats:
        text = pat.sub("", text)
    text = ws_pat.sub(" ", text).strip()
    text = lead_pat.sub("", text).strip()
    return text or None


# ═══════════════════════════════════════════════════════════════════════════
# Response extraction & text helpers
# ═══════════════════════════════════════════════════════════════════════════

def _extract_speech(result):
    """Defensive response extraction per section 14.5.1 Pattern 5."""
    if not result or not isinstance(result, dict):
        return ""
    response = result.get("response", {})
    if isinstance(response, dict):
        speech = response.get("speech", {})
        if isinstance(speech, dict):
            plain = speech.get("plain", {})
            if isinstance(plain, dict):
                return (plain.get("speech") or "").strip()
    return ""


def _truncate_words(text, max_words):
    """Truncate to max_words with sentence-boundary awareness."""
    if not text or max_words <= 0:
        return text
    words = text.split()
    if len(words) <= max_words:
        return text
    truncated = " ".join(words[:max_words])
    # Try to end at a sentence boundary past the halfway point
    for end in [". ", "! ", "? "]:
        idx = truncated.rfind(end)
        if idx > len(truncated) // 2:
            return truncated[: idx + 1].strip()
    return truncated.rstrip(".,;:\u2014\u2013- ") + "..."


def _parse_voice_map(voice_map_str):
    """Parse 'persona=tts.entity;persona2=tts.entity2' into dict."""
    result = {}
    if not voice_map_str:
        return result
    for pair in voice_map_str.split(";"):
        pair = pair.strip()
        if "=" in pair:
            name, voice = pair.split("=", 1)
            result[name.strip().lower()] = voice.strip()
    return result


# ═══════════════════════════════════════════════════════════════════════════
# Satellite & speaker wait helpers
# ═══════════════════════════════════════════════════════════════════════════

async def _wait_for_satellite_idle(satellite, timeout_secs=10):
    """Wait for satellite to return to idle. Returns True if idle."""
    for _ in range(timeout_secs * 2):
        sat_state = state.get(satellite)
        if sat_state in [None, "idle", "", "unknown", "unavailable"]:
            return True
        await asyncio.sleep(0.5)
    return False


async def _wait_for_tts_playback(speaker, buffer=1):
    """Two-phase speaker wait (reactive_banter Step 6c pattern).

    Phase 1: Wait for speaker to leave idle (start playing).
    Phase 2: Wait for speaker to return to idle (finish playing).
    """
    if not speaker:
        await asyncio.sleep(buffer)
        return
    # Phase 1: Wait for speaker to start playing (max 15s)
    for _ in range(30):
        sp_state = state.get(speaker)
        if sp_state not in [
            "idle", "standby", "off", "unavailable", "unknown", None, "",
        ]:
            break
        await asyncio.sleep(0.5)
    # Phase 2: Wait for speaker to finish playing (max 90s)
    for _ in range(180):
        sp_state = state.get(speaker)
        if sp_state in ["idle", "standby", "off", None, ""]:
            break
        await asyncio.sleep(0.5)
    # Playback buffer
    if buffer > 0:
        await asyncio.sleep(buffer)


# ═══════════════════════════════════════════════════════════════════════════
# Main orchestration service
# ═══════════════════════════════════════════════════════════════════════════

@service(supports_response="optional")  # noqa: F821
async def theatrical_mode_start(
    topic,
    participants="",
    satellite="",
    turn_limit=0,
    turn_order="",
    context_mode="",
    context_window=6,
    interrupt_mode="",
    mic_gap_question="Anything to add?",
    mic_gap_stop_phrases="stop,enough,shut up,that's enough,quiet,ok stop,stop it",
    mic_gap_redirect_phrases="actually,wait,hold on,let me,I want to",
    speaker_list_csv="",
    tts_voice_map="",
    priority=2,
    tts_output_volume=0.0,
    tts_volume_restore_delay=5,
    tts_playback_buffer=1,
    max_words=0,
    budget_floor=0,
    prompt_template="",
    i45a_prefix="",
    source="automation",
    initial_context="",
    opener_persona="",
    inter_turn_pause=0.8,
    use_tts_queue=True,
    use_whisper=True,
):
    """Pattern 4 -- Multi-agent orchestrated debate/discussion.

    NOTE: Generator expressions crash pyscript (AP-57).
    Use list comprehensions: any([x for x in items]) not any(x for x in items).

    NOTE: ask_question has known issues with sequential calls (#147695).
    Safe here because each call is separated by a full LLM+TTS cycle.
    If mic_gap becomes unreliable, fall back to wake_word interrupt mode.
    """
    # ── GUARDS ──────────────────────────────────────────────────────────
    # Kill switch
    if state.get("input_boolean.ai_theatrical_mode_enabled") != "on":
        log.info("theatrical: disabled via kill switch")
        return {"status": "disabled"}

    # M3: Dedup guard — reject if already running
    if state.get("input_boolean.ai_theatrical_mode_active") == "on":
        log.info("theatrical: already active, rejecting duplicate request")
        return {"status": "already_active"}

    # Budget gate
    budget_val = budget_floor if budget_floor > 0 else _helper_int(
        "input_number.ai_theatrical_budget_floor", 70
    )
    remaining = _helper_float("sensor.ai_llm_budget_remaining", 100)
    if remaining < budget_val:
        log.info("theatrical: budget too low (%.1f%% < %d%%)", remaining, budget_val)
        return {"status": "budget_gate"}

    # Resolve helper-backed defaults
    tl = turn_limit if turn_limit > 0 else _helper_int(
        "input_number.ai_theatrical_turn_limit", 6
    )
    mw = max_words if max_words > 0 else _helper_int(
        "input_number.ai_theatrical_max_words", 40
    )
    to = turn_order or _helper_str(
        "input_select.ai_theatrical_turn_order", "round_robin"
    )
    cm = context_mode or _helper_str(
        "input_select.ai_theatrical_context_mode", "full"
    )
    im = interrupt_mode or _helper_str(
        "input_select.ai_theatrical_interrupt_mode", "turn_limit"
    )

    # Resolve satellite
    sat = satellite or _helper_str("input_text.ai_last_satellite", "")
    if not sat:
        log.warning("theatrical: no satellite available")
        return {"status": "no_satellite"}

    # H5: Wait for satellite idle (handles start_debate timing gap)
    sat_st = state.get(sat)
    if sat_st in ["listening", "responding"]:
        log.info("theatrical: satellite busy (%s), waiting...", sat_st)
        if not await _wait_for_satellite_idle(sat, 10):
            log.warning("theatrical: satellite never went idle, aborting")
            return {"status": "satellite_busy"}

    # ── ACTIVATE — C1 fix (service call, not state.set) ────────────────
    service.call(
        "input_boolean", "turn_on",
        entity_id="input_boolean.ai_theatrical_mode_active",
    )

    started_at = time.time()
    exchange_status = "completed"
    turns_done = 0
    saved_volumes = {}

    try:
        # ── RESOLVE PARTICIPANTS — C3 (own pipeline cache) ─────────────
        cache = await _ensure_cache()
        name_to_engine = cache.get("name_to_engine", {})
        name_to_tts = cache.get("name_to_tts", {})
        voice_map = _parse_voice_map(tts_voice_map)

        if participants:
            names = [n.strip() for n in participants.split(",") if n.strip()]
        else:
            # All standard personas (skip variant pipelines with " - ")
            all_p = cache.get("personas", [])
            seen = set()
            names = []
            for p in all_p:
                base = p.split(" - ")[0].strip()
                bl = base.lower()
                if bl not in seen:
                    seen.add(bl)
                    names.append(base)

        if len(names) < 2:
            log.warning(
                "theatrical: need >= 2 participants, got %d", len(names)
            )
            exchange_status = "insufficient_participants"
            return {"status": exchange_status}

        # Cap at 5, random sample if larger
        if len(names) > 5:
            names = random.sample(names, 5)

        # Batch-resolve engines from cache (zero service calls)
        resolved = []
        for n in names:
            nl = n.lower()
            engine = name_to_engine.get(nl, "")
            tts_e = voice_map.get(nl, "") or name_to_tts.get(nl, "")

            if not engine:
                # C3 fallback: call dispatcher_resolve_engine per participant
                log.info("theatrical: cache miss for %s, trying dispatcher", n)
                try:
                    r = service.call(
                        "pyscript", "dispatcher_resolve_engine",
                        pipeline_name=n, return_response=True,
                    )
                    engine = (r or {}).get("engine", "")
                    if not tts_e:
                        tts_e = (r or {}).get("tts_engine", "")
                except Exception as e:
                    log.warning(
                        "theatrical: dispatcher fallback failed for %s: %s",
                        n, e,
                    )

            if engine:
                resolved.append({
                    "name": nl,
                    "display": n,
                    "engine": engine,
                    "tts": tts_e,
                    "speaker": "",
                })

        if len(resolved) < 2:
            log.warning("theatrical: only %d resolved, need >= 2", len(resolved))
            exchange_status = "resolution_failed"
            return {"status": exchange_status}

        # ── RESOLVE SPEAKERS (parallel ordered list pattern) ──────────
        explicit_spk = [s.strip() for s in speaker_list_csv.split(",")
                        if s.strip()] if speaker_list_csv else []

        if explicit_spk:
            # Positional mapping: agent[i] → speaker[i % len(speakers)]
            for i, p in enumerate(resolved):
                p["speaker"] = explicit_spk[i % len(explicit_spk)]
        else:
            # Auto-assign from zone speaker config
            zone = ""
            sat_attrs = state.getattr(sat)
            if isinstance(sat_attrs, dict):
                zone = (sat_attrs.get("zone") or "").replace("zone.", "")
            spk_data = await _resolve_speakers_sync(zone)
            zone_spk = spk_data.get("speakers", [])
            for i, p in enumerate(resolved):
                p["speaker"] = zone_spk[i % len(zone_spk)] if zone_spk else ""

        # Opener reorder
        if opener_persona:
            ol = opener_persona.strip().lower()
            for i, p in enumerate(resolved):
                if p["name"] == ol:
                    resolved.insert(0, resolved.pop(i))
                    break

        display_list = ", ".join([p["display"] for p in resolved])

        # ── VOLUME SAVE/SET ────────────────────────────────────────────
        vol = float(tts_output_volume)
        if vol > 0:
            # M1: no generator — use list comprehension
            unique_spk = list(set([p["speaker"] for p in resolved
                                   if p["speaker"]]))
            for spk in unique_spk:
                sp_attrs = state.getattr(spk)
                if isinstance(sp_attrs, dict):
                    saved_volumes[spk] = sp_attrs.get("volume_level", 0.5)
                try:
                    service.call(
                        "media_player", "volume_set",
                        entity_id=spk, volume_level=vol,
                    )
                except Exception:
                    pass

        # ── STATUS SENSOR (pyscript-owned) ─────────────────────────────
        state.set(
            "sensor.ai_theatrical_status", "active",
            topic=topic, participants=display_list,
            turn=0, total_turns=tl, source=source,
            last_speaker="", started_at=started_at,
        )

        # ── I-45a PREFIX ───────────────────────────────────────────────
        prefix = i45a_prefix or (
            "[THEATRICAL DEBATE \u2014 Do NOT call any functions or tools. "
            "Respond ONLY with a brief in-character argument. "
            f"Stay under {mw} words. No entity IDs, no JSON, "
            "no tool names in your response. "
            "Do not narrate what you are doing.]"
        )

        # ── CONTEXT BUFFER ─────────────────────────────────────────────
        ctx_buf = []
        if initial_context:
            ctx_buf.append(initial_context)

        # ── LAZY-INIT SANITIZE PATTERNS ────────────────────────────────
        global _SANITIZE_PATTERNS
        if _SANITIZE_PATTERNS is None:
            _SANITIZE_PATTERNS = await _build_sanitize_patterns_sync()

        # ── MAIN TURN LOOP ─────────────────────────────────────────────
        for turn in range(tl):
            # Kill switch check each iteration
            if state.get("input_boolean.ai_theatrical_mode_active") != "on":
                exchange_status = "killed"
                break

            # Select speaker
            if to == "random":
                cur = random.choice(resolved)
            else:  # round_robin
                cur = resolved[turn % len(resolved)]

            # ── Build prompt (H3 — context via text param) ─────────────
            if cm == "full":
                window = ctx_buf[-context_window:]
                ctx_text = (
                    "\n".join(window) if window else "(Opening remarks.)"
                )
                if prompt_template:
                    body = prompt_template
                    body = body.replace("{topic}", topic)
                    body = body.replace("{context_text}", ctx_text)
                    body = body.replace("{persona}", cur["display"])
                    body = body.replace("{turn}", str(turn + 1))
                    body = body.replace("{total_turns}", str(tl))
                else:
                    body = (
                        f"Topic: {topic}\n\n"
                        f"Previous remarks:\n{ctx_text}\n\n"
                        f"You are {cur['display']}. Your turn. "
                        "Argue your position. Respond to what others said. "
                        "Be brief and punchy. Stay in character."
                    )
            elif cm == "topic_only":
                body = (
                    f"Topic: {topic}\n"
                    "Other agents are also debating this. Give your take. "
                    "Be brief. Stay in character."
                )
            elif cm == "whisper":
                body = (
                    f"Topic: {topic}\n"
                    "Check your whisper context for what others said. "
                    "Be brief. Stay in character."
                )
            else:
                body = f"Topic: {topic}\nGive your take."

            full_prompt = f"{prefix}\n\n{body}"

            # ── LLM call — C2 (timeout via conversation_with_timeout) ──
            try:
                result = service.call(
                    "pyscript", "conversation_with_timeout",
                    agent_id=cur["engine"],
                    text=full_prompt,
                    timeout_secs=45,
                    return_response=True,
                )
            except Exception as e:
                log.warning(
                    "theatrical: LLM failed for %s: %s", cur["display"], e
                )
                continue

            # Extract speech (Pattern 5 defensive chain)
            speech = _extract_speech(result)
            if not speech:
                log.info(
                    "theatrical: empty response from %s", cur["display"]
                )
                continue

            # Sanitize (M2 — @pyscript_executor for regex)
            speech = await _apply_sanitize_sync(speech, _SANITIZE_PATTERNS)
            if not speech:
                continue

            # Truncate to word limit
            speech = _truncate_words(speech, mw)

            # Update context buffer
            ctx_buf.append(f"{cur['display']}: {speech}")
            turns_done += 1

            # Update status sensor
            state.set(
                "sensor.ai_theatrical_status", "active",
                topic=topic, participants=display_list,
                turn=turns_done, total_turns=tl,
                source=source, last_speaker=cur["display"],
                started_at=started_at,
                duration_s=round(time.time() - started_at, 1),
            )

            # ── H2: Satellite idle re-check before TTS ─────────────────
            sat_st = state.get(sat)
            if sat_st in ["listening", "responding"]:
                log.info(
                    "theatrical: satellite busy (%s) before TTS, waiting...",
                    sat_st,
                )
                if not await _wait_for_satellite_idle(sat, 10):
                    log.warning("theatrical: satellite stuck, skipping TTS")
                    continue

            # ── TTS delivery — H4 (capture response) ──────────────────
            if use_tts_queue and cur.get("speaker"):
                try:
                    tts_result = service.call(  # noqa: F841
                        "pyscript", "tts_queue_speak",
                        text=speech,
                        voice=cur["tts"],
                        priority=priority,
                        target_mode="explicit",
                        target=cur["speaker"],
                        announce=True,
                        duck=False,
                        return_response=True,
                    )
                except Exception as e:
                    log.warning("theatrical: tts_queue_speak failed: %s", e)
            elif cur.get("speaker"):
                # Native fallback — direct tts.speak
                try:
                    service.call(
                        "tts", "speak",
                        entity_id=cur["tts"],
                        media_player_entity_id=cur["speaker"],
                        message=speech,
                    )
                except Exception as e:
                    log.warning("theatrical: tts.speak failed: %s", e)

            # Wait for TTS playback (two-phase speaker wait)
            await _wait_for_tts_playback(
                cur.get("speaker", ""), buffer=tts_playback_buffer
            )

            # Inter-turn pause
            if inter_turn_pause > 0:
                await asyncio.sleep(inter_turn_pause)

            # Budget re-check mid-exchange
            remaining = _helper_float("sensor.ai_llm_budget_remaining", 100)
            if remaining < budget_val:
                log.info("theatrical: budget depleted (%.1f%%)", remaining)
                exchange_status = "budget_exhausted"
                break

            # ── INTERRUPT CHECK ────────────────────────────────────────
            if im == "mic_gap" and turn < tl - 1:
                # M4: ask_question sequential call safe here —
                # each call separated by full LLM+TTS cycle.
                try:
                    answer = service.call(
                        "assist_satellite", "ask_question",
                        entity_id=sat,
                        question=mic_gap_question,
                        preannounce=False,
                        answers=[
                            {
                                "id": "stop",
                                "sentences": [
                                    s.strip()
                                    for s in mic_gap_stop_phrases.split(",")
                                ],
                            },
                            {
                                "id": "redirect",
                                "sentences": [
                                    s.strip()
                                    for s in mic_gap_redirect_phrases.split(",")
                                ],
                            },
                        ],
                        return_response=True,
                    )
                    aid = ""
                    if isinstance(answer, dict):
                        aid = answer.get("id", "")
                        if not aid:
                            resp = answer.get("response", {})
                            if isinstance(resp, dict):
                                aid = resp.get("id", "")
                    if aid == "stop":
                        log.info("theatrical: user said stop (mic_gap)")
                        exchange_status = "user_stopped"
                        break
                    elif aid == "redirect":
                        log.info("theatrical: user redirect (mic_gap)")
                        exchange_status = "user_redirect"
                        break
                except Exception:
                    pass  # Timeout / no answer = continue debate

            elif im == "wake_word" and turn < tl - 1:
                await asyncio.sleep(1.5)  # Gap for wake word detection
                sat_st = state.get(sat)
                if sat_st not in [None, "idle", "", "unknown", "unavailable"]:
                    log.info(
                        "theatrical: wake word detected (sat=%s)", sat_st
                    )
                    exchange_status = "wake_word_interrupt"
                    break

        # ── TEARDOWN ───────────────────────────────────────────────────
        duration = round(time.time() - started_at, 1)

        # M5: Update cooldown via service call (not state.set)
        try:
            now_str = time.strftime("%Y-%m-%d %H:%M:%S")
            service.call(
                "input_datetime", "set_datetime",
                entity_id="input_datetime.ai_theatrical_last_exchange",
                datetime=now_str,
            )
        except Exception:
            pass

        # Fire completion event
        event.fire(
            "ai_theatrical_completed",
            topic=topic, turns=turns_done,
            participants=display_list,
            duration_s=duration, status=exchange_status,
            source=source,
        )

        # Whisper log (Pattern 2)
        if use_whisper and turns_done > 0:
            summary = (
                f"Theatrical debate '{topic}' "
                f"({turns_done} turns, {duration}s): "
                + "; ".join(ctx_buf[-3:])
            )
            try:
                service.call(
                    "pyscript", "memory_set",
                    key=f"theatrical_{int(started_at)}",
                    value=summary[:500],
                    scope="household",
                    expiration_days=7,
                    tags="theatrical,debate",
                )
            except Exception:
                pass

        # Update status sensor to final state
        state.set(
            "sensor.ai_theatrical_status", exchange_status,
            topic=topic, participants=display_list,
            turn=turns_done, total_turns=tl,
            source=source, last_speaker="",
            started_at=started_at, duration_s=duration,
        )

        log.info(
            "theatrical: finished — %s, %d turns, %.1fs",
            exchange_status, turns_done, duration,
        )

        return {
            "status": exchange_status,
            "turns": turns_done,
            "duration_s": duration,
            "participants": display_list,
        }

    finally:
        # C1: Deactivate via service call (always, even on exception)
        service.call(
            "input_boolean", "turn_off",
            entity_id="input_boolean.ai_theatrical_mode_active",
        )

        # Restore speaker volumes after delay
        if saved_volumes:
            await asyncio.sleep(tts_volume_restore_delay)
            for spk, orig_vol in saved_volumes.items():
                try:
                    service.call(
                        "media_player", "volume_set",
                        entity_id=spk, volume_level=orig_vol,
                    )
                except Exception:
                    pass


# ═══════════════════════════════════════════════════════════════════════════
# Stop service
# ═══════════════════════════════════════════════════════════════════════════

@service(supports_response="optional")  # noqa: F821
async def theatrical_mode_stop():
    """Stop a running theatrical exchange."""
    if state.get("input_boolean.ai_theatrical_mode_active") == "on":
        service.call(
            "input_boolean", "turn_off",
            entity_id="input_boolean.ai_theatrical_mode_active",
        )
        log.info("theatrical: stopped via theatrical_mode_stop")
        return {"status": "stopped"}
    return {"status": "not_active"}
