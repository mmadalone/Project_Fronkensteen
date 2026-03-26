"""Agent Dispatcher — DC-7 of Voice Context Architecture (Task 11).

Pipeline-aware persona routing: discovers available agents from HA Assist
Pipelines, resolves TTS/STT from pipeline config, and routes requests based
on wake word, topic affinity, conversation continuity, time of day, and
LLM budget. Exposes pyscript.agent_dispatch and Priority 0 regex matching
for programmatic handoff requests.
"""
import asyncio
import json
import random
import re
import time
from datetime import datetime
from typing import Any

from shared_utils import build_result_entity_name

# =============================================================================
# Agent Dispatcher — DC-7 of Voice Context Architecture (Task 11)
# =============================================================================
# Pipeline-aware persona routing: discovers available agents from HA Assist
# Pipelines, resolves TTS/STT from pipeline config, routes based on wake word,
# topic affinity (from memory), time of day (from UI helpers), conversation
# continuity, user preference, and LLM budget.
#
# Service: pyscript.agent_dispatch
#   Input:  intent_text, source_satellite, wake_word, verbosity
#   Output: {agent, persona, verbosity, variant, reason,
#            tts_engine, tts_voice, stt_engine, pipeline_id}
#
# Persona discovery:
#   Personas and entity mappings are derived from Assist Pipeline config.
#   Convention: conversation.{persona}_{variant}
#   Known variants: standard, bedtime. "verbose" falls back to standard entity.
#
# Routing priority (auto mode):
#   0. User handoff request        →  "pass me to X" detected in intent
#   1. Explicit name in wake word  →  bypass all logic
#   2. Conversation continuity     →  same agent if < N min
#   3. Topic affinity              →  keyword match from memory
#   4. Time of day                 →  era-based default from UI helpers
#   5. User preference (L2)        →  memory search (graceful fallback)
#   6. Fallback                    →  random selection
#
# Dependencies:
#   - /config/.storage/assist_pipeline.pipelines (persona + TTS discovery)
#   - input_select.ai_dispatcher_era_{late_night,morning,afternoon,evening}
#   - pyscript/memory.py (topic keywords + L2 preferences)
#   - packages/ai_dispatcher.yaml (mode/enabled/test helpers)
#   - packages/ai_self_awareness.yaml (last-agent state)
#   - packages/ai_context_hot.yaml (bedtime booleans)
#   - packages/ai_llm_budget.yaml (budget sensor)
#   - packages/ai_test_harness.yaml (test mode)
#
# Keyword seeding (one-time, via Developer Tools → Services):
#   service: pyscript.memory_set
#   data:
#     key: "dispatch_keywords:rick"
#     value: "tech,science,code,computer,network,fix,broken,debug,..."
#     scope: "household"
#     expiration_days: 0
#     tags: "dispatch keywords rick"
#
# Deployed: 2026-03-01
# =============================================================================

# Log policy: log.info for user-visible events, startup, errors.
# Routine per-call tracing uses log.debug — enable via Logger integration.

RESULT_ENTITY = "sensor.ai_dispatcher_status"
PIPELINE_FILE = "/config/.storage/assist_pipeline.pipelines"
ENTITY_REGISTRY_FILE = "/config/.storage/core.entity_registry"
# Variants are auto-discovered from pipeline display names.
# Any pipeline named "<Persona> - <Variant>" registers as variant
# <variant> (lowercased, spaces→underscores). No allowlist needed.
KEYWORD_DISPLAY_ENTITY = "sensor.ai_keyword_display"
KEYWORD_AGENT_SELECT = "input_select.ai_keyword_agent_select"

# ── Time-of-Day Era Helpers ──────────────────────────────────────────────────
_ERA_NAMES = ("late_night", "morning", "afternoon", "evening")


def _get_era_helper(era):
    return f"input_select.ai_dispatcher_era_{era}"


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


def _get_cache_ttl():
    return _helper_int("input_number.ai_dispatcher_cache_ttl", 300)

# ── Dynamic Cache ────────────────────────────────────────────────────────────
# Populated on first dispatch from pipeline file + memory.
# Structure:
#   personas:        tuple[str, ...]                        sorted persona names
#   entity_map:      dict[(persona, variant) → entity_id]   pipeline-derived
#   wake_word_map:   dict[persona_name → persona_name]      trivially derived
#   pipeline_map:    dict[entity_id → pipeline_record]      for TTS/STT lookup
#   pipeline_id_map: dict[pipeline_id → pipeline_record]    reverse lookup by ID
#   name_to_engine:  dict[display_name_lower → entity_id]   pipeline name → conversation_engine
#   topic_keywords:  dict[persona → list[str]]              from memory
#   satellite_select_map:  dict[sat → select_entity]        for pipeline switching
#   satellite_speaker_map: dict[sat → media_player_entity]  for TTS routing
_cache: dict | None = None
_cache_ts: float = 0.0
_CACHE_EMPTY_RETRY: int = 30  # seconds — fast retry when pipelines were empty
_round_robin_index = 0

result_entity_name: dict[str, str] = {}


def _ensure_result_entity_name(force: bool = False) -> None:
    global result_entity_name
    if force or not result_entity_name:
        result_entity_name = build_result_entity_name(RESULT_ENTITY)


def _set_result(state_value: str = "ok", **attrs: Any) -> None:
    _ensure_result_entity_name()
    attrs.update(result_entity_name)
    state.set(RESULT_ENTITY, value=state_value, new_attributes=attrs)  # noqa: F821


# ── Pipeline Discovery ───────────────────────────────────────────────────────

@pyscript_executor  # noqa: F821
def _load_pipelines_from_file_sync(pipeline_file: str) -> list:
    """Read the Assist Pipeline JSON file (sync). Returns items list or []."""
    import json as _json
    try:
        with open(pipeline_file, "r") as fh:
            data = _json.load(fh)
        return data.get("data", {}).get("items", [])
    except Exception as exc:
        print(f"dispatcher: {exc}")
        return []


async def _load_pipelines_from_file(pipeline_file: str) -> list:
    """Async wrapper — @pyscript_executor handles threading automatically."""
    return _load_pipelines_from_file_sync(pipeline_file)


# ── Satellite Device Discovery ──────────────────────────────────────────────

@pyscript_executor  # noqa: F821
def _discover_satellite_devices_sync(registry_file: str) -> tuple:
    """Read entity registry, group by device_id, build satellite maps.

    For each device with an assist_satellite entity, find:
      - select.*_assistant  (pipeline picker, excludes _assistant_2)
      - media_player.* with platform=esphome + device_class=speaker
    """
    import json as _json
    select_map = {}
    speaker_map = {}
    try:
        with open(registry_file, "r") as fh:
            data = _json.loads(fh.read())
        entities = data.get("data", {}).get("entities", [])

        by_device = {}
        for e in entities:
            did = e.get("device_id")
            if did and not e.get("disabled_by"):
                by_device.setdefault(did, []).append(e)

        for did, ents in by_device.items():
            sat = None
            sel = None
            spk = None
            for e in ents:
                eid = e.get("entity_id", "")
                if eid.startswith("assist_satellite."):
                    sat = eid
                elif (eid.startswith("select.")
                      and eid.endswith("_assistant")
                      and not eid.endswith("_assistant_2")):
                    sel = eid
                elif (eid.startswith("media_player.")
                      and e.get("platform") == "esphome"
                      and e.get("original_device_class") == "speaker"):
                    spk = eid
            if sat and sel:
                select_map[sat] = sel
            if sat and spk:
                speaker_map[sat] = spk
    except Exception:
        pass
    return select_map, speaker_map


@pyscript_compile  # noqa: F821
def _build_from_pipelines(
    items: list,
) -> tuple:
    """Derive personas from pipeline display names (not entity IDs).

    Parses 'Rick - Bedtime' → persona='rick', variant='bedtime'.
    Returns (personas, entity_map, wake_word_map, pipeline_map,
             pipeline_id_map, display_map, persona_pipeline_map).
    """
    personas_set = set()
    entity_map = {}
    pipeline_map = {}
    pipeline_id_map = {}
    display_map = {}           # persona_key → "Display Name"
    persona_pipeline_map = {}  # (persona, variant) → pipeline record

    for item in items:
        engine = item.get("conversation_engine", "")
        pid = item.get("id", "")
        pname = (item.get("name") or "").strip()

        # Build pipeline_id_map for ALL pipelines (including non-conversation ones)
        if pid:
            pipeline_id_map[pid] = item

        if not engine or not engine.startswith("conversation."):
            continue

        if not pname:
            continue

        # Derive persona and variant from the pipeline display name
        if " - " in pname:
            parts = pname.split(" - ", 1)
            display_persona = parts[0].strip()
            variant_str = parts[1].strip().lower().replace(" ", "_")
            variant = variant_str if variant_str else "standard"
        else:
            display_persona = pname
            variant = "standard"

        persona = display_persona.lower().replace(" ", "_")

        personas_set.add(persona)
        entity_map[(persona, variant)] = engine
        pipeline_map[engine] = item
        display_map[persona] = display_persona
        persona_pipeline_map[(persona, variant)] = item

    personas = tuple(sorted(personas_set))
    wake_word_map = {p: p for p in personas}

    return (personas, entity_map, wake_word_map, pipeline_map,
            pipeline_id_map, display_map, persona_pipeline_map)


async def _load_topic_keywords(personas: tuple) -> dict:
    """Load per-persona topic keywords from memory. Graceful on failure.

    Expects memory entries with key 'dispatch_keywords:{persona}' and
    comma-separated keyword values. Use memory_set to seed:
      key: dispatch_keywords:rick
      value: tech,science,code,computer,...
      scope: household
      expiration_days: 0
      tags: dispatch keywords rick
    """
    keywords = {}
    for persona in personas:
        try:
            result = pyscript.memory_get(  # noqa: F821
                key=f"dispatch_keywords:{persona}",
            )
            resp = await result
            if resp and resp.get("status") == "ok":
                val = resp.get("value", "")
                kw_list = [k.strip().lower() for k in val.split(",") if k.strip()]
                if kw_list:
                    keywords[persona] = kw_list
        except Exception as exc:
            log.warning(f"dispatcher: {exc}")  # noqa: F821
    if keywords:
        log.info(  # noqa: F821
            f"agent_dispatch: loaded keywords for {list(keywords.keys())}"
        )
    return keywords


async def _update_era_helper_options(personas: tuple) -> None:
    """Update the time-of-day era helper dropdowns with discovered personas."""
    options = ["none"] + list(personas) + ["rotate"]
    for helper_entity in [_get_era_helper(e) for e in _ERA_NAMES]:
        try:
            saved = state.get(helper_entity)  # noqa: F821
        except Exception as exc:
            log.warning(f"dispatcher: {exc}")  # noqa: F821
            saved = None
        try:
            await service.call(  # noqa: F821
                "input_select", "set_options",
                entity_id=helper_entity,
                options=options,
            )
        except Exception as exc:
            log.warning(  # noqa: F821
                f"agent_dispatch: failed to update {helper_entity}: {exc}"
            )
            continue
        # Restore previous selection if still valid
        if saved and saved in options:
            try:
                await service.call(  # noqa: F821
                    "input_select", "select_option",
                    entity_id=helper_entity,
                    option=saved,
                )
            except Exception as exc:
                log.warning(f"dispatcher: {exc}")  # noqa: F821
    # Also update keyword agent select
    try:
        await service.call(  # noqa: F821
            "input_select", "set_options",
            entity_id=KEYWORD_AGENT_SELECT,
            options=list(personas) + ["none"],
        )
    except Exception as exc:
        log.warning(  # noqa: F821
            f"agent_dispatch: failed to update keyword agent select: {exc}"
        )


# ── User-Initiated Handoff Detection (Priority 0) ────────────────────────────

@pyscript_compile  # noqa: F821
def _parse_aliases(raw: str) -> dict:
    """Parse comma-separated alias=persona pairs into a dict."""
    aliases = {}
    if not raw:
        return aliases
    for pair in raw.split(","):
        pair = pair.strip()
        if "=" not in pair:
            continue
        parts = pair.split("=", 1)
        alias = parts[0].strip().lower()
        persona = parts[1].strip().lower()
        if alias and persona:
            aliases[alias] = persona
    return aliases


@pyscript_compile  # noqa: F821
def _build_user_handoff_patterns(personas: tuple, aliases: dict) -> list:
    """Build regex patterns to detect user-initiated handoff requests.

    Matches: 'pass me to X', 'switch to X', 'hand me over to X',
    'get me X', 'put X on', 'I want to talk to X', 'can I speak to X', etc.
    The alternation includes both persona names AND alias keys.
    """
    import re as _re
    if not personas:
        return []
    # Combine persona names + alias keys, sorted longest-first for greedy match
    all_names = sorted(
        set(list(personas) + list(aliases.keys())),
        key=len, reverse=True,
    )
    alt = "|".join(_re.escape(n) for n in all_names)
    return [
        _re.compile(
            rf"\b(?:pass|hand)\s+(?:me\s+)?(?:over\s+)?to\s+({alt})\b",
            _re.IGNORECASE,
        ),
        _re.compile(
            rf"\b(?:switch|transfer)\s+(?:me\s+)?(?:over\s+)?to\s+({alt})\b",
            _re.IGNORECASE,
        ),
        _re.compile(
            rf"\bget\s+(?:me\s+)?({alt})\b",
            _re.IGNORECASE,
        ),
        _re.compile(
            rf"\bput\s+({alt})\s+on\b",
            _re.IGNORECASE,
        ),
        _re.compile(
            rf"\b(?:i\s+)?(?:want|need)\s+to\s+(?:talk|speak)\s+(?:to|with)\s+({alt})\b",
            _re.IGNORECASE,
        ),
        _re.compile(
            rf"\b(?:can|could)\s+i\s+(?:talk|speak)\s+(?:to|with)\s+({alt})\b",
            _re.IGNORECASE,
        ),
        _re.compile(
            rf"\blet\s+me\s+(?:talk|speak)\s+(?:to|with)\s+({alt})\b",
            _re.IGNORECASE,
        ),
    ]


@pyscript_compile  # noqa: F821
def _detect_user_handoff(intent_text: str, patterns: list, aliases: dict) -> str | None:
    """Scan user intent text for handoff request. Returns resolved persona or None."""
    if not intent_text or not patterns:
        return None
    for pat in patterns:
        m = pat.search(intent_text)
        if m:
            matched = m.group(1).lower()
            # Resolve alias → persona, or return matched if it's already a persona
            return aliases.get(matched, matched)
    return None


@pyscript_compile  # noqa: F821
def _strip_handoff_command(intent_text: str, patterns: list) -> str:
    """Remove the handoff command from intent text, leaving any attached query."""
    if not intent_text or not patterns:
        return intent_text or ""
    result = intent_text
    for pat in patterns:
        result = pat.sub("", result)
    return result.strip(" ,.-")


async def _ensure_cache() -> None:
    """Lazy-load the full cache on first dispatch. Auto-expires after configurable TTL."""
    global _cache, _cache_ts
    if _cache is not None:
        ttl = _CACHE_EMPTY_RETRY if not _cache["personas"] else _get_cache_ttl()
        if (time.monotonic() - _cache_ts) < ttl:
            return
        log.info("agent_dispatch: cache TTL expired, reloading")  # noqa: F821
    _cache = None

    items = await _load_pipelines_from_file(PIPELINE_FILE)
    (personas, entity_map, wake_word_map, pipeline_map,
     pipeline_id_map, display_map, persona_pipeline_map) = (
        _build_from_pipelines(items)
    )

    if not personas:
        log.error(  # noqa: F821
            "agent_dispatch: no conversation pipelines found in "
            f"{PIPELINE_FILE} — dispatch will return empty results"
        )

    topic_keywords = await _load_topic_keywords(personas)

    # Load persona aliases from helper (deadpool=deepee, etc.)
    raw_aliases = ""
    try:
        raw_aliases = state.get("input_text.ai_handoff_persona_aliases") or ""  # noqa: F821
    except Exception as exc:
        log.warning(f"dispatcher: {exc}")  # noqa: F821
    handoff_aliases = _parse_aliases(raw_aliases)
    user_handoff_patterns = _build_user_handoff_patterns(personas, handoff_aliases)

    # Build pipeline display name → conversation_engine map
    name_to_engine = {}
    for item in items:
        pname = (item.get("name") or "").strip()
        engine = item.get("conversation_engine", "")
        if pname and engine:
            name_to_engine[pname.lower()] = engine

    # Discover satellite device mappings from entity registry
    sat_sel, sat_spk = _discover_satellite_devices_sync(ENTITY_REGISTRY_FILE)

    _cache = {
        "personas": personas,
        "entity_map": entity_map,
        "wake_word_map": wake_word_map,
        "pipeline_map": pipeline_map,
        "pipeline_id_map": pipeline_id_map,
        "name_to_engine": name_to_engine,
        "topic_keywords": topic_keywords,
        "user_handoff_patterns": user_handoff_patterns,
        "handoff_aliases": handoff_aliases,
        "display_map": display_map,
        "persona_pipeline_map": persona_pipeline_map,
        "satellite_select_map": sat_sel,
        "satellite_speaker_map": sat_spk,
    }
    _cache_ts = time.monotonic()

    log.info(  # noqa: F821
        f"agent_dispatch: loaded {len(personas)} personas, "
        f"{len(pipeline_map)} pipelines, "
        f"{len(pipeline_id_map)} pipeline IDs, "
        f"{len(name_to_engine)} name→engine mappings, "
        f"{len(topic_keywords)} keyword sets, "
        f"{len(user_handoff_patterns)} handoff patterns, "
        f"{len(sat_sel)} satellites"
    )

    if personas:
        await _update_era_helper_options(personas)


def _reload_cache() -> None:
    """Invalidate cache so it reloads on next dispatch."""
    global _cache, _cache_ts
    _cache = None
    _cache_ts = 0.0


# ── Test Mode ────────────────────────────────────────────────────────────────

def _is_test_mode() -> bool:
    try:
        return str(
            state.get("input_boolean.ai_test_mode") or "off"  # noqa: F821
        ).lower() == "on"
    except NameError:
        return False


@service(supports_response="optional")  # noqa: F821
async def dispatcher_reload_cache():
    """Invalidate and rebuild the dispatcher cache.

    yaml
    name: Dispatcher Reload Cache
    description: >-
      Invalidates the in-memory cache and reloads pipelines, personas,
      keywords, and handoff patterns. Call after config changes
      (e.g., from the Dispatcher Profile blueprint).
    """
    if _is_test_mode():
        log.info("agent_dispatcher [TEST]: would reload dispatcher cache")  # noqa: F821
        return

    _reload_cache()
    await _ensure_cache()
    personas = _cache["personas"] if _cache else ()
    display = _cache.get("display_map", {}) if _cache else {}
    log.info(  # noqa: F821
        f"dispatcher_reload_cache: reloaded {len(personas)} personas"
    )
    return {"status": "ok", "personas": list(personas), "display_map": display}


@service(supports_response="optional")  # noqa: F821
async def dispatcher_resolve_engine(pipeline_name: str = ""):
    """Resolve pipeline display name to its conversation_engine entity ID."""
    if _is_test_mode():
        log.info("agent_dispatcher [TEST]: would resolve engine for pipeline=%s", pipeline_name)  # noqa: F821
        return

    # Returns: {engine, tts_voice, tts_engine}
    await _ensure_cache()
    if not pipeline_name or _cache is None:
        return {"engine": "", "tts_voice": "", "tts_engine": ""}
    name_lower = pipeline_name.strip().lower()
    name_map = _cache.get("name_to_engine", {})
    engine = name_map.get(name_lower, "")
    # Resolve TTS voice/engine from pipeline record
    tts_voice = ""
    tts_engine = ""
    for item in _cache.get("pipeline_id_map", {}).values():
        if (item.get("name") or "").strip().lower() == name_lower:
            tts_voice = item.get("tts_voice", "")
            tts_engine = item.get("tts_engine", "")
            break
    return {"engine": engine, "tts_voice": tts_voice, "tts_engine": tts_engine}


@service(supports_response="only")  # noqa: F821
async def dispatcher_get_satellite_maps():
    """Return satellite device maps from dispatcher cache.

    yaml
    name: Dispatcher Get Satellite Maps
    description: >-
      Returns satellite_select_map and satellite_speaker_map from the
      dispatcher cache. Used by voice_handoff and voice_session to avoid
      duplicating entity registry discovery.
    """
    await _ensure_cache()
    if _cache is None:
        return {"satellite_select_map": {}, "satellite_speaker_map": {}}
    return {
        "satellite_select_map": _cache.get("satellite_select_map", {}),
        "satellite_speaker_map": _cache.get("satellite_speaker_map", {}),
    }


def _get_pipeline_info(persona: str, variant: str) -> dict:
    """Return TTS/STT info for a persona+variant from cache.

    Uses persona_pipeline_map for exact lookup (handles shared engines
    like conversation.extended_openai_conversation correctly).
    Falls back to engine-keyed pipeline_map if persona key not found.
    """
    if _cache is None:
        return {}
    record = _cache.get("persona_pipeline_map", {}).get((persona, variant))
    if not record:
        # Fallback: try engine-keyed map via entity_map
        entity = _cache.get("entity_map", {}).get((persona, variant))
        if entity:
            record = _cache["pipeline_map"].get(entity)
    if not record:
        return {}
    info = {}
    if record.get("name"):
        info["pipeline_name"] = record["name"]
    if record.get("tts_engine"):
        info["tts_engine"] = record["tts_engine"]
    if record.get("tts_voice"):
        info["tts_voice"] = record["tts_voice"]
    if record.get("stt_engine"):
        info["stt_engine"] = record["stt_engine"]
    if record.get("id"):
        info["pipeline_id"] = record["id"]
    return info


@pyscript_compile  # noqa: F821
def _resolve_pipeline_by_id(
    pipeline_id: str, pipeline_id_map: dict,
) -> dict:
    """Resolve a pipeline ID to agent/TTS/persona info. Returns empty dict on miss."""
    record = pipeline_id_map.get(pipeline_id)
    # Fallback: if pipeline_id looks like a conversation entity, reverse-lookup
    if not record and pipeline_id.startswith("conversation."):
        for pid, item in pipeline_id_map.items():
            if item.get("conversation_engine") == pipeline_id:
                record = item
                pipeline_id = pid
                break
    if not record:
        return {}
    engine = record.get("conversation_engine", "")
    result = {"agent": engine}
    if record.get("name"):
        result["pipeline_name"] = record["name"]
    if record.get("tts_engine"):
        result["tts_engine"] = record["tts_engine"]
    if record.get("tts_voice"):
        result["tts_voice"] = record["tts_voice"]
    if record.get("stt_engine"):
        result["stt_engine"] = record["stt_engine"]
    result["pipeline_id"] = pipeline_id
    # Derive persona from pipeline display name (not entity ID)
    pname = (record.get("name") or "").strip()
    if pname:
        if " - " in pname:
            parts = pname.split(" - ", 1)
            display_persona = parts[0].strip()
            variant_str = parts[1].strip().lower().replace(" ", "_")
            result["variant"] = variant_str if variant_str else "standard"
        else:
            display_persona = pname
            result["variant"] = "standard"
        result["persona"] = display_persona.lower().replace(" ", "_")
    return result


# ── Pure-Python Sync Helpers ─────────────────────────────────────────────────

@pyscript_compile  # noqa: F821
def _extract_persona_from_wake_word(
    wake_word: str, wake_word_map: dict,
) -> str | None:
    """Extract explicit persona name from wake word. Returns None if generic."""
    ww = wake_word.lower().replace("-", "_").replace(" ", "_")
    for keyword, persona in wake_word_map.items():
        if keyword in ww:
            return persona
    return None


@pyscript_compile  # noqa: F821
def _match_topic_affinity(
    intent_text: str, topic_keywords: dict, personas: tuple,
) -> str | None:
    """Match intent text against keyword lists from memory. Returns persona or None."""
    text_lower = intent_text.lower()
    for persona in personas:
        keywords = topic_keywords.get(persona, [])
        for kw in keywords:
            if kw in text_lower:
                return persona
    return None


@pyscript_compile  # noqa: F821
def _get_time_era(hour: int) -> str:
    """Classify current hour into time era."""
    if 0 <= hour <= 5:
        return "late_night"
    if 6 <= hour <= 11:
        return "morning"
    if 12 <= hour <= 17:
        return "afternoon"
    return "evening"


@pyscript_compile  # noqa: F821
def _next_round_robin(current_index: int, personas: tuple) -> tuple:
    """Return next persona in round-robin order + updated index."""
    if not personas:
        return ("unknown", 0)
    idx = (current_index + 1) % len(personas)
    return (personas[idx], idx)


@pyscript_compile  # noqa: F821
def _resolve_entity(
    persona: str, verbosity: str, is_bedtime: bool, entity_map: dict,
) -> str:
    """Map persona + verbosity + bedtime to conversation entity ID.

    Fallback chain: (persona, variant) → (persona, 'standard') → convention.
    """
    variant = "bedtime" if is_bedtime else verbosity
    key = (persona, variant)
    return entity_map.get(key, entity_map.get(
        (persona, "standard"), f"conversation.{persona}_standard"
    ))


@pyscript_compile  # noqa: F821
def _derive_verbosity(wake_word: str, explicit_verbosity: str) -> str:
    """Determine verbosity from wake word prefix or explicit parameter."""
    if explicit_verbosity and explicit_verbosity in ("standard", "verbose"):
        return explicit_verbosity
    ww = wake_word.lower().replace("-", "_").replace(" ", "_")
    if ww.startswith("yo"):
        return "verbose"
    return "standard"


# ── Async Dispatch Logic ─────────────────────────────────────────────────────

async def _check_continuity(
    window_minutes: float, personas: tuple,
) -> str | None:
    """Check if we should continue with the last agent (within time window)."""
    last_name = state.get("input_text.ai_last_agent_name")  # noqa: F821
    if not last_name or last_name in ("none", "unknown", "unavailable", ""):
        return None

    last_ts_raw = state.getattr("input_datetime.ai_last_interaction_time")  # noqa: F821
    if not last_ts_raw:
        return None
    ts = last_ts_raw.get("timestamp", 0)
    if not ts or ts <= 0:
        return None

    elapsed_min = (time.time() - float(ts)) / 60.0
    if elapsed_min <= window_minutes:
        persona = last_name.lower().strip()
        if persona in personas:
            return persona
    return None


async def _check_user_preference(personas: tuple) -> str | None:
    """Search L2 memory for user agent preference. Graceful on failure."""
    try:
        result = pyscript.memory_search(  # noqa: F821
            query="preference agent",
            limit=1,
        )
        resp = await result
        if resp and resp.get("status") == "ok":
            results = resp.get("results", [])
            if results:
                val = results[0].get("value", "").lower()
                for p in personas:
                    if p in val:
                        return p
    except Exception as exc:
        log.warning("agent_dispatch: memory preference lookup failed: %s", exc)  # noqa: F821
    return None


def _get_era_persona(era: str, personas: tuple) -> str | None:
    """Read the time-of-day persona from UI helper. Returns None for 'rotate'."""
    if era not in _ERA_NAMES:
        return None
    helper = _get_era_helper(era)
    val = state.get(helper)  # noqa: F821
    if not val or val in ("rotate", "unknown", "unavailable", "none", ""):
        return None
    val = val.lower().strip()
    if val in personas:
        return val
    return None


async def _check_bedtime() -> bool:
    """Check if bedtime mode is active."""
    bedtime = state.get("input_boolean.ai_bedtime_active")  # noqa: F821
    if bedtime == "on":
        return True
    bedtime_lock = state.get("input_boolean.ai_bedtime_global_lock")  # noqa: F821
    if bedtime_lock == "on":
        return True
    return False


async def _check_budget() -> tuple:
    """Check LLM budget. Returns (budget_ok, remaining_pct)."""
    try:
        remaining = int(float(
            state.get("sensor.ai_llm_budget_remaining") or "100"  # noqa: F821
        ))
    except (ValueError, TypeError):
        remaining = 100
    return remaining > 0, remaining


async def _update_self_awareness(persona: str, entity: str) -> None:
    """Update self-awareness helpers after dispatch decision."""
    try:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        service.call(  # noqa: F821
            "input_text", "set_value",
            entity_id="input_text.ai_last_agent_name",
            value=persona,
        )
        service.call(  # noqa: F821
            "input_text", "set_value",
            entity_id="input_text.ai_last_agent_entity",
            value=entity,
        )
        service.call(  # noqa: F821
            "input_datetime", "set_datetime",
            entity_id="input_datetime.ai_last_interaction_time",
            datetime=now_str,
        )
    except Exception as exc:
        log.warning(f"agent_dispatch: self-awareness update failed: {exc}")  # noqa: F821


# ── Main Dispatch Service ────────────────────────────────────────────────────

@service(supports_response="only")  # noqa: F821
async def agent_dispatch(
    intent_text: str = "",
    source_satellite: str = "",
    wake_word: str = "",
    verbosity: str = "",
    skip_continuity: bool = False,
    pipeline_id: str = "",
    pipeline_name: str = "",
):
    """
    yaml
    name: Agent Dispatch
    description: >-
      Pipeline-aware persona routing. When pipeline_id is provided, resolves
      that specific pipeline to agent/TTS/persona (no dynamic selection).
      Otherwise, discovers agents from Assist Pipelines, evaluates wake word,
      topic affinity (from memory), time of day (from UI helpers), continuity,
      and user preference to select the best conversation agent. Returns agent,
      persona, verbosity, variant, reason, and pipeline-derived fields
      (tts_engine, tts_voice, stt_engine, pipeline_id).
    fields:
      intent_text:
        name: Intent Text
        description: User's spoken text from STT.
        required: false
        default: ""
        example: "how much does a Tesla cost"
        selector:
          text:
      source_satellite:
        name: Source Satellite
        description: Entity ID of the Voice PE satellite.
        required: false
        default: ""
        example: "assist_satellite.workshop_rick"
        selector:
          text:
      wake_word:
        name: Wake Word
        description: Which wake word triggered (hey_rick, yo_quark, hey_jarvis, etc).
        required: false
        default: ""
        example: "hey_rick"
        selector:
          text:
      verbosity:
        name: Verbosity
        description: Override verbosity (standard or verbose). Derived from wake word if empty.
        required: false
        default: ""
        example: "standard"
        selector:
          select:
            options:
              - standard
              - verbose
      skip_continuity:
        name: Skip Continuity
        description: >-
          Skip conversation continuity check. Use for automated system
          dispatches (email alerts, briefings) so they respect the
          time-of-day era setting instead of inheriting the last
          conversational agent.
        required: false
        default: false
        selector:
          boolean:
      pipeline_id:
        name: Pipeline ID
        description: >-
          Resolve a specific Assist Pipeline by its ID (ULID). When provided,
          skips all dynamic routing and returns the pipeline's agent, TTS
          engine, TTS voice, and derived persona. Used by blueprints when
          dispatcher is OFF and the user's Voice Assistant selection applies.
        required: false
        default: ""
        example: "01kayrss2ypkzzsae1r2ex7nad"
        selector:
          text:
      pipeline_name:
        name: Pipeline Name
        description: >-
          Resolve a pipeline by its display name (e.g., "Rick", "Rick - Bedtime").
          Case-insensitive. When provided, skips all dynamic routing. Preferred
          over pipeline_id as display names survive pipeline recreation.
        required: false
        default: ""
        example: "Rick"
        selector:
          text:
    """
    if _is_test_mode():
        log.info("agent_dispatcher [TEST]: would dispatch intent_text=%s wake_word=%s", intent_text[:50] if intent_text else "", wake_word)  # noqa: F821
        return {"status": "test_mode_skip", "agent": "homeassistant", "reason": "test_mode"}

    global _round_robin_index
    t_start = time.monotonic()

    try:
        # Returns: {agent, persona, verbosity?, variant?, reason, elapsed_ms, tts_engine?, tts_voice?, stt_engine?, pipeline_id?, pipeline_name?, fallback?, budget_remaining?, handoff_detected?, handoff_source?, handoff_target?, remaining_query?, self_handoff?, test_mode?, error?}  # noqa: E501

        # ── Ensure cache is loaded ──
        await _ensure_cache()

        # ── I-46: Budget fallback gate — bypass all routing ──
        if state.get("input_boolean.ai_budget_fallback_active") == "on":  # noqa: F821
            fallback_agent = (
                state.get("input_text.ai_budget_fallback_agent") or "homeassistant"  # noqa: F821
            ).strip()
            result = {
                "agent": fallback_agent,
                "persona": "fallback",
                "verbosity": "standard",
                "variant": "standard",
                "reason": "budget_fallback",
                "fallback": True,
                "tts_engine": "tts.home_assistant_cloud",
                "tts_voice": "",
                "stt_engine": "stt.home_assistant_cloud",
                "elapsed_ms": round((time.monotonic() - t_start) * 1000, 1),
            }
            _set_result("fallback", **result)
            return result

        # ── Pipeline name resolution (dynamic by display name) ──
        if pipeline_name:
            pipeline_name_lower = pipeline_name.strip().lower()
            for pid, item in _cache["pipeline_id_map"].items():
                if (item.get("name") or "").strip().lower() == pipeline_name_lower:
                    resolved = _resolve_pipeline_by_id(
                        pid, _cache["pipeline_id_map"]
                    )
                    if resolved:
                        resolved["reason"] = "pipeline_name_resolve"
                        resolved["elapsed_ms"] = round(
                            (time.monotonic() - t_start) * 1000, 1
                        )
                        _set_result("ok", **resolved)
                        log.debug(  # noqa: F821
                            f"agent_dispatch: pipeline name '{pipeline_name}' → {resolved}"
                        )
                        return resolved
            # Name not found
            result = {
                "agent": "", "persona": "",
                "reason": "pipeline_name_not_found",
                "pipeline_name": pipeline_name,
                "elapsed_ms": round(
                    (time.monotonic() - t_start) * 1000, 1
                ),
            }
            _set_result("error", **result)
            log.warning(  # noqa: F821
                f"agent_dispatch: pipeline_name '{pipeline_name}' not found"
            )
            return result

        # ── Pipeline ID resolution (bypass all dynamic routing) ──
        if pipeline_id:
            resolved = _resolve_pipeline_by_id(
                pipeline_id, _cache["pipeline_id_map"]
            )
            if resolved:
                resolved["reason"] = "pipeline_id_resolve"
                resolved["elapsed_ms"] = round(
                    (time.monotonic() - t_start) * 1000, 1
                )
                _set_result("ok", **resolved)
                log.debug(f"agent_dispatch: pipeline resolve → {resolved}")  # noqa: F821
                return resolved
            else:
                result = {
                    "agent": "",
                    "persona": "",
                    "reason": "pipeline_id_not_found",
                    "pipeline_id": pipeline_id,
                    "elapsed_ms": round(
                        (time.monotonic() - t_start) * 1000, 1
                    ),
                }
                _set_result("error", **result)
                log.warning(  # noqa: F821
                    f"agent_dispatch: pipeline_id '{pipeline_id}' not found"
                )
                return result

        personas = _cache["personas"]
        entity_map = _cache["entity_map"]
        wake_word_map = _cache["wake_word_map"]
        topic_keywords = _cache["topic_keywords"]

        # ── Resolve verbosity from wake word if not explicit ──
        resolved_verbosity = _derive_verbosity(wake_word or "", verbosity or "")

        # ── No personas guard ──
        if not personas:
            result = {
                "agent": "",
                "persona": "",
                "reason": "no_pipelines",
                "elapsed_ms": round((time.monotonic() - t_start) * 1000, 1),
            }
            _set_result("error", **result)
            return result

        # ── Priority 0: User-initiated handoff ("pass me to X") ──
        if intent_text and state.get("input_boolean.ai_voice_handoff_enabled") != "off":  # noqa: F821
            handoff_target = _detect_user_handoff(
                intent_text, _cache["user_handoff_patterns"],
                _cache["handoff_aliases"],
            )
            if handoff_target and handoff_target in personas:
                is_bedtime = await _check_bedtime()
                entity = _resolve_entity(
                    handoff_target, resolved_verbosity, is_bedtime, entity_map
                )
                variant = "bedtime" if is_bedtime else resolved_verbosity
                # Determine handoff source (who the user was addressing)
                handoff_source = ""
                if wake_word:
                    handoff_source = _extract_persona_from_wake_word(
                        wake_word, wake_word_map
                    ) or ""
                if not handoff_source:
                    try:
                        handoff_source = (
                            state.get("input_text.ai_last_agent_name") or ""  # noqa: F821
                        ).lower().strip()
                    except Exception as exc:
                        log.warning(f"dispatcher: {exc}")  # noqa: F821
                # Strip the handoff command, leaving any attached query
                remaining_query = _strip_handoff_command(
                    intent_text, _cache["user_handoff_patterns"]
                )
                result = {
                    "agent": entity,
                    "persona": handoff_target,
                    "verbosity": resolved_verbosity,
                    "variant": variant,
                    "reason": "user_handoff_request",
                    "handoff_detected": True,
                    "handoff_source": handoff_source,
                    "handoff_target": handoff_target,
                    "remaining_query": remaining_query,
                    "elapsed_ms": round((time.monotonic() - t_start) * 1000, 1),
                }
                result.update(_get_pipeline_info(handoff_target, variant))
                # Fire handoff event so the blueprint can handle the switch.
                # Replaces the fragile input_text flag mechanism.
                current_agent = (
                    state.get("input_text.ai_last_agent_name") or ""  # noqa: F821
                ).lower().strip()
                is_self = handoff_target == current_agent
                if is_self:
                    result["self_handoff"] = True
                # Fire handoff event for all handoffs — belt and suspenders.
                # Voice path: LLM tool also fires event; mode:restart
                # deduplicates. Programmatic path: this is the only source.
                event.fire(  # noqa: F821
                    "ai_handoff_request",
                    target=handoff_target,
                    source=current_agent,
                    self_handoff=is_self,
                    reason="user_request",
                )
                if not (state.get("input_boolean.ai_test_mode") == "on"):  # noqa: F821
                    await _update_self_awareness(handoff_target, entity)
                _set_result("ok", **result)
                log.info(f"agent_dispatch: {result}")  # noqa: F821
                return result

        # ── Check dispatcher enabled ──
        dispatcher_enabled = state.get(  # noqa: F821
            "input_boolean.ai_dispatcher_enabled"
        )
        if dispatcher_enabled == "off":
            persona = random.choice(personas)
            is_bedtime = await _check_bedtime()
            entity = _resolve_entity(
                persona, resolved_verbosity, is_bedtime, entity_map
            )
            variant = "bedtime" if is_bedtime else resolved_verbosity
            result = {
                "agent": entity,
                "persona": persona,
                "verbosity": resolved_verbosity,
                "variant": variant,
                "reason": "dispatcher_disabled",
                "elapsed_ms": round((time.monotonic() - t_start) * 1000, 1),
            }
            result.update(_get_pipeline_info(persona, variant))
            _set_result("ok", **result)
            log.debug(f"agent_dispatch: {result}")  # noqa: F821
            return result

        # ── Check test mode ──
        test_mode = state.get("input_boolean.ai_test_mode") == "on"  # noqa: F821

        # ── Check dispatch mode ──
        dispatch_mode = (
            state.get("input_select.ai_dispatcher_mode") or "auto"  # noqa: F821
        ).lower().strip()

        # ── Check bedtime (shared by all paths) ──
        is_bedtime = await _check_bedtime()

        # ── Read agent pool (limits random/round_robin/auto-rotate) ──
        pool_raw = (
            state.get("input_text.ai_dispatcher_agent_pool") or ""  # noqa: F821
        ).strip()
        if pool_raw:
            agent_pool = tuple([
                p.strip().lower() for p in pool_raw.split(",")
                if p.strip() and p.strip().lower() in personas
            ])
        else:
            agent_pool = personas
        if not agent_pool:
            agent_pool = personas  # safety fallback

        # ── Mode: fixed ──
        if dispatch_mode == "fixed":
            fixed_agent = (
                state.get("input_text.ai_dispatcher_fixed_agent") or ""  # noqa: F821
            ).lower().strip()
            if fixed_agent not in personas:
                fixed_agent = personas[0]
            entity = _resolve_entity(
                fixed_agent, resolved_verbosity, is_bedtime, entity_map
            )
            variant = "bedtime" if is_bedtime else resolved_verbosity
            result = {
                "agent": entity,
                "persona": fixed_agent,
                "verbosity": resolved_verbosity,
                "variant": variant,
                "reason": "mode_fixed",
                "elapsed_ms": round((time.monotonic() - t_start) * 1000, 1),
            }
            result.update(_get_pipeline_info(fixed_agent, variant))
            if not test_mode:
                await _update_self_awareness(fixed_agent, entity)
            _set_result("ok", **result)
            log.debug(f"agent_dispatch: {result}")  # noqa: F821
            return result

        # ── Mode: random ──
        if dispatch_mode == "random":
            persona = random.choice(agent_pool)
            entity = _resolve_entity(
                persona, resolved_verbosity, is_bedtime, entity_map
            )
            variant = "bedtime" if is_bedtime else resolved_verbosity
            result = {
                "agent": entity,
                "persona": persona,
                "verbosity": resolved_verbosity,
                "variant": variant,
                "reason": "mode_random",
                "elapsed_ms": round((time.monotonic() - t_start) * 1000, 1),
            }
            result.update(_get_pipeline_info(persona, variant))
            if not test_mode:
                await _update_self_awareness(persona, entity)
            _set_result("ok", **result)
            log.debug(f"agent_dispatch: {result}")  # noqa: F821
            return result

        # ── Mode: round_robin ──
        if dispatch_mode == "round_robin":
            persona, _round_robin_index = _next_round_robin(
                _round_robin_index, agent_pool
            )
            entity = _resolve_entity(
                persona, resolved_verbosity, is_bedtime, entity_map
            )
            variant = "bedtime" if is_bedtime else resolved_verbosity
            result = {
                "agent": entity,
                "persona": persona,
                "verbosity": resolved_verbosity,
                "variant": variant,
                "reason": "mode_round_robin",
                "elapsed_ms": round((time.monotonic() - t_start) * 1000, 1),
            }
            result.update(_get_pipeline_info(persona, variant))
            if not test_mode:
                await _update_self_awareness(persona, entity)
            _set_result("ok", **result)
            log.debug(f"agent_dispatch: {result}")  # noqa: F821
            return result

        # ── Mode: auto (full dispatch logic) ──

        # ── Budget check (log warning if exhausted, but don't block) ──
        budget_ok, budget_remaining = await _check_budget()
        if not budget_ok:
            log.warning(  # noqa: F821
                f"agent_dispatch: LLM budget exhausted ({budget_remaining}%), "
                "allowing essential dispatch"
            )

        persona = None
        reason = "fallback_random"

        # ── Priority 1: Explicit name in wake word ──
        if wake_word:
            explicit = _extract_persona_from_wake_word(wake_word, wake_word_map)
            if explicit:
                persona = explicit
                reason = "explicit_wake_word"

        # ── Priority 2: Conversation continuity (skipped for system dispatches) ──
        if persona is None and not skip_continuity:
            try:
                window = float(
                    state.get(  # noqa: F821
                        "input_number.ai_conversation_continuity_window"
                    ) or "5"
                )
            except (ValueError, TypeError):
                window = 5.0
            cont = await _check_continuity(window, personas)
            if cont:
                persona = cont
                reason = "conversation_continuity"

        # ── Priority 3: Topic affinity (from memory keywords) ──
        if persona is None and intent_text and topic_keywords:
            topic_match = _match_topic_affinity(
                intent_text, topic_keywords, personas
            )
            if topic_match:
                persona = topic_match
                reason = "topic_affinity"

        # ── Priority 4: Time of day (from UI helpers) ──
        if persona is None:
            hour = datetime.now().hour
            era = _get_time_era(hour)
            era_persona = _get_era_persona(era, personas)
            if era_persona:
                persona = era_persona
                reason = f"time_of_day_{era}"
            else:
                persona, _round_robin_index = _next_round_robin(
                    _round_robin_index, agent_pool
                )
                reason = f"time_of_day_{era}_rotate"

        # ── Priority 5: User preference from L2 (only if still None) ──
        if persona is None:
            pref = await _check_user_preference(personas)
            if pref:
                persona = pref
                reason = "user_preference_l2"

        # ── Priority 6: Fallback random ──
        if persona is None:
            persona = random.choice(agent_pool)
            reason = "fallback_random"

        # ── Resolve final entity ──
        entity = _resolve_entity(
            persona, resolved_verbosity, is_bedtime, entity_map
        )
        variant = "bedtime" if is_bedtime else resolved_verbosity

        # ── Build result ──
        result = {
            "agent": entity,
            "persona": persona,
            "verbosity": resolved_verbosity,
            "variant": variant,
            "reason": reason,
            "budget_remaining": budget_remaining,
            "elapsed_ms": round((time.monotonic() - t_start) * 1000, 1),
        }
        result.update(_get_pipeline_info(persona, variant))

        # ── Test mode: log only, skip self-awareness update ──
        if test_mode:
            log.info(  # noqa: F821
                f"agent_dispatch [TEST MODE]: {result} | "
                f"intent='{intent_text}' wake='{wake_word}' "
                f"sat='{source_satellite}'"
            )
            result["test_mode"] = True
            _set_result("test", **result)
            return result

        # ── Production: update self-awareness ──
        await _update_self_awareness(persona, entity)

        _set_result("ok", **result)
        log.debug(f"agent_dispatch: {result}")  # noqa: F821
        return result

    except Exception as exc:
        log.error("agent_dispatch failed: %s: %s", type(exc).__name__, exc)  # noqa: F821
        _set_result("error", error=str(exc))
        return {
            "agent": "", "persona": "", "reason": "dispatch_error",
            "error": str(exc),
        }


# ── Startup ──────────────────────────────────────────────────────────────────

@time_trigger("startup")  # noqa: F821
async def agent_dispatcher_startup():
    """Initialize dispatcher status sensor on HA startup."""
    _ensure_result_entity_name(force=True)
    _set_result("idle", op="startup")
    await _ensure_cache()  # populates era selects + keywords
    log.info("agent_dispatcher: loaded — idle")  # noqa: F821


# ── Keyword Manager Services (Dashboard V2.1) ────────────────────────────────

@service(supports_response="only")  # noqa: F821
async def dispatcher_load_keywords():
    """Load keywords for selected agent from L2 memory and display."""
    if _is_test_mode():
        log.info("agent_dispatcher [TEST]: would load keywords for selected agent")  # noqa: F821
        return {"status": "test_mode_skip"}

    await _ensure_cache()
    agent = (state.get(KEYWORD_AGENT_SELECT) or "").strip().lower()  # noqa: F821
    if not agent or agent == "none":
        state.set(  # noqa: F821
            KEYWORD_DISPLAY_ENTITY, value="none",
            new_attributes={
                "friendly_name": "AI Keyword Display",
                "keywords_md": "_Select an agent first._",
            },
        )
        return {"status": "error", "op": "load_keywords", "error": "no_agent"}

    try:
        result = pyscript.memory_get(key=f"dispatch_keywords:{agent}")  # noqa: F821
        resp = await result
    except Exception as exc:
        log.warning(f"dispatcher: {exc}")  # noqa: F821
        resp = {"status": "error"}

    if resp and resp.get("status") == "ok":
        raw = resp.get("value", "")
        keywords = [k.strip() for k in raw.split(",") if k.strip()]
        lines = []
        for kw in keywords:
            if kw.startswith("!"):
                lines.append(f"- **[M]** {kw[1:]}")
            else:
                lines.append(f"- [A] {kw}")
        md = "\n".join(lines) if lines else "_No keywords found._"

        # Update in-memory cache too
        if _cache is not None:
            kw_list = [k.strip().lower() for k in raw.split(",") if k.strip()]
            _cache["topic_keywords"][agent] = kw_list

        state.set(  # noqa: F821
            KEYWORD_DISPLAY_ENTITY, value=agent,
            new_attributes={
                "friendly_name": "AI Keyword Display",
                "keywords_md": md,
                "count": len(keywords),
                "agent": agent,
            },
        )
        return {"status": "ok", "op": "load_keywords", "agent": agent, "count": len(keywords)}
    else:
        state.set(  # noqa: F821
            KEYWORD_DISPLAY_ENTITY, value=agent,
            new_attributes={
                "friendly_name": "AI Keyword Display",
                "keywords_md": f"_No keywords for {agent}._",
                "count": 0,
                "agent": agent,
            },
        )
        return {"status": "ok", "op": "load_keywords", "agent": agent, "count": 0}


@service(supports_response="only")  # noqa: F821
async def dispatcher_add_keyword():
    """Add a keyword to the selected agent's routing keywords."""
    if _is_test_mode():
        log.info("agent_dispatcher [TEST]: would add keyword to selected agent")  # noqa: F821
        return {"status": "test_mode_skip"}

    await _ensure_cache()
    agent = (state.get(KEYWORD_AGENT_SELECT) or "").strip().lower()  # noqa: F821
    keyword = (state.get("input_text.ai_keyword_add") or "").strip().lower()  # noqa: F821
    manual = state.get("input_boolean.ai_keyword_manual") == "on"  # noqa: F821

    if not agent or agent == "none":
        return {"status": "error", "op": "add_keyword", "error": "no_agent"}
    if not keyword:
        return {"status": "error", "op": "add_keyword", "error": "no_keyword"}

    # Load existing keywords
    existing = []
    try:
        result = pyscript.memory_get(key=f"dispatch_keywords:{agent}")  # noqa: F821
        resp = await result
        if resp and resp.get("status") == "ok":
            existing = [k.strip() for k in resp.get("value", "").split(",") if k.strip()]
    except Exception as exc:
        log.warning(f"dispatcher: {exc}")  # noqa: F821

    # Check if already exists (in either form)
    existing_lower = [k.lower().lstrip("!") for k in existing]
    if keyword.lower() in existing_lower:
        return {"status": "error", "op": "add_keyword", "error": "already_exists"}

    new_kw = f"!{keyword}" if manual else keyword
    existing.append(new_kw)
    new_value = ",".join(existing)

    # Save to L2
    result = pyscript.memory_set(  # noqa: F821
        key=f"dispatch_keywords:{agent}",
        value=new_value,
        scope="household",
        expiration_days=0,
        tags=f"dispatch keywords {agent}",
    )
    await result

    # Refresh display
    await dispatcher_load_keywords()
    return {"status": "ok", "op": "add_keyword", "agent": agent, "keyword": new_kw}


@service(supports_response="only")  # noqa: F821
async def dispatcher_remove_keyword():
    """Remove a keyword from the selected agent's routing keywords."""
    if _is_test_mode():
        log.info("agent_dispatcher [TEST]: would remove keyword from selected agent")  # noqa: F821
        return {"status": "test_mode_skip"}

    await _ensure_cache()
    agent = (state.get(KEYWORD_AGENT_SELECT) or "").strip().lower()  # noqa: F821
    keyword = (state.get("input_text.ai_keyword_remove") or "").strip().lower()  # noqa: F821

    if not agent or agent == "none":
        return {"status": "error", "op": "remove_keyword", "error": "no_agent"}
    if not keyword:
        return {"status": "error", "op": "remove_keyword", "error": "no_keyword"}

    # Load existing
    try:
        result = pyscript.memory_get(key=f"dispatch_keywords:{agent}")  # noqa: F821
        resp = await result
    except Exception as exc:
        log.warning(f"dispatcher: {exc}")  # noqa: F821
        resp = {"status": "error"}

    if not resp or resp.get("status") != "ok":
        return {"status": "error", "op": "remove_keyword", "error": "no_entry"}

    existing = [k.strip() for k in resp.get("value", "").split(",") if k.strip()]
    # Remove both !keyword and keyword forms
    filtered = [k for k in existing if k.lower().lstrip("!") != keyword.lower()]

    if len(filtered) == len(existing):
        return {"status": "error", "op": "remove_keyword", "error": "not_found"}

    new_value = ",".join(filtered)
    result = pyscript.memory_set(  # noqa: F821
        key=f"dispatch_keywords:{agent}",
        value=new_value,
        scope="household",
        expiration_days=0,
        tags=f"dispatch keywords {agent}",
    )
    await result

    await dispatcher_load_keywords()
    return {"status": "ok", "op": "remove_keyword", "agent": agent, "keyword": keyword}


@service(supports_response="only")  # noqa: F821
async def dispatcher_clear_auto_keywords():
    """Clear all auto (non-manual) keywords from the selected agent."""
    if _is_test_mode():
        log.info("agent_dispatcher [TEST]: would clear auto keywords for selected agent")  # noqa: F821
        return {"status": "test_mode_skip"}

    await _ensure_cache()
    agent = (state.get(KEYWORD_AGENT_SELECT) or "").strip().lower()  # noqa: F821

    if not agent or agent == "none":
        return {"status": "error", "op": "clear_auto", "error": "no_agent"}

    try:
        result = pyscript.memory_get(key=f"dispatch_keywords:{agent}")  # noqa: F821
        resp = await result
    except Exception as exc:
        log.warning(f"dispatcher: {exc}")  # noqa: F821
        resp = {"status": "error"}

    if not resp or resp.get("status") != "ok":
        return {"status": "error", "op": "clear_auto", "error": "no_entry"}

    existing = [k.strip() for k in resp.get("value", "").split(",") if k.strip()]
    manual_only = [k for k in existing if k.startswith("!")]
    removed = len(existing) - len(manual_only)

    new_value = ",".join(manual_only)
    result = pyscript.memory_set(  # noqa: F821
        key=f"dispatch_keywords:{agent}",
        value=new_value,
        scope="household",
        expiration_days=0,
        tags=f"dispatch keywords {agent}",
    )
    await result

    await dispatcher_load_keywords()
    return {"status": "ok", "op": "clear_auto", "agent": agent, "removed": removed}
