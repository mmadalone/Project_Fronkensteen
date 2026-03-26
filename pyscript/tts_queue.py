"""DC-3/DC-10/DC-11: Centralized TTS Queue Manager and Audio Pipeline.

Routes all TTS speech and media playback through a priority queue with
presence-aware speaker targeting, automatic ducking on supported speakers,
volume management, broadcast mode, and higher-priority preemption. Tracks
TTS character counts and per-agent costs for the budget system.
"""
import asyncio
import hashlib
import json
import re
import shutil
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from shared_utils import build_result_entity_name

# =============================================================================
# TTS Queue Manager — Centralized Audio Pipeline (DC-3, DC-10, DC-11)
# =============================================================================
# All TTS and audio playback routes through this module:
#   priority queue → presence-aware speaker targeting
#
# Playback:
#   TTS  — tts.speak (voice entity + media_player target)
#   Media — media_player.play_media (audio files)
#   Volume — media_player.volume_set before playback if specified
#   Broadcast — iterates ALL_SPEAKERS, calls tts.speak per speaker
#   Announce/ducking is automatic on supported speakers (Sonos, etc.)
#
# Preemption:
#   Higher-priority item → media_stop on current speaker, flag breaks sleep.
#   Preempted item is NOT re-queued (truncated, not retried).
# =============================================================================

# Log policy: log.info for user-visible events, startup, errors.
# Routine per-call tracing uses log.debug — enable via Logger integration.

CACHE_DIR = Path("/config/www/tts_cache")
HA_TTS_DIR = Path("/config/tts")
RESULT_ENTITY = "sensor.ai_tts_queue_status"
PLAYBACK_SETTLE_DELAY = 0.3      # hardware timing — keep as constant

PRIORITY_EMERGENCY = 0
PRIORITY_ALERT = 1
PRIORITY_NORMAL = 2
PRIORITY_LOW = 3
PRIORITY_AMBIENT = 4


# ── Helper-reading utilities ─────────────────────────────────────────────────

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

def _helper_str(entity_id: str, default: str) -> str:
    try:
        val = state.get(entity_id)  # noqa: F821
        if val and val not in ("unknown", "unavailable", ""):
            return str(val)
    except Exception:
        pass
    return default


# ── Dynamic constants (read from helpers, with safe defaults) ────────────────

def _get_playback_buffer(): return _helper_float("input_number.ai_tts_playback_buffer", 0.5)
def _get_poll_interval(): return _helper_float("input_number.ai_tts_poll_interval", 0.25)
def _get_max_timeout(): return _helper_float("input_number.ai_tts_max_timeout", 30.0)
def _get_post_buffer(): return _helper_float("input_number.ai_tts_post_buffer", 0.3)
def _get_max_ambient(): return _helper_int("input_number.ai_tts_max_ambient", 3)
def _get_default_duration(): return _helper_float("input_number.ai_tts_default_duration", 5.0)
def _get_generation_buffer(): return _helper_float("input_number.ai_tts_generation_buffer", 2.0)
def _get_fallback_tts_voice(): return _helper_str("input_text.ai_default_tts_voice", "tts.home_assistant_cloud")


# ── Dynamic voice/agent utilities (replace hardcoded maps) ───────────────────

def _is_elevenlabs_voice(voice: str) -> bool:
    return "elevenlabs" in (voice or "").lower()

# ── Dynamic remap: built from config entries at load time ──
# Maps old per-character TTS entities → (hacs_entity, profile_name, agent_name)
# by matching voice IDs between official entries and HACS profiles.
# Also builds UUID → profile_name reverse map for callers that pass raw voice IDs.
_TTS_ENTITY_REMAP = {}
_PROFILE_TO_AGENT = {}
_VOICE_UUID_TO_PROFILE = {}

@pyscript_executor  # noqa: F821
def _build_tts_remap_sync():
    """Read config entries to build old-entity → HACS-profile remap dynamically."""
    import json as _json
    remap = {}
    profile_to_agent = {}
    uuid_to_profile = {}
    # Load profile→agent map (shared with HACS component)
    _mood_map = {}
    try:
        with open("/config/pyscript/voice_mood_profile_map.json", "r") as f:
            _mood_map = _json.load(f)
    except Exception:
        pass
    try:
        with open("/config/.storage/core.config_entries", "r") as f:
            data = _json.load(f)
        entries = data.get("data", {}).get("entries", [])
        # Collect HACS custom TTS profiles: voice_id → profile_name
        vid_to_profile = {}
        for entry in entries:
            if entry.get("domain") == "elevenlabs_custom_tts":
                for pname, pdata in entry.get("options", {}).get("voice_profiles", {}).items():
                    vid = pdata.get("voice", "")
                    if vid:
                        vid_to_profile[vid] = pname
                        uuid_to_profile[vid] = pname
                        agent = _mood_map.get(pname.lower().strip(), pname.split(" - ")[0].split()[0].lower())
                        profile_to_agent[pname.lower()] = agent
        # Collect official ElevenLabs entries and resolve via entity registry
        entry_id_to_vid = {}
        for entry in entries:
            if entry.get("domain") != "elevenlabs":
                continue
            vid = entry.get("options", {}).get("voice") or entry.get("data", {}).get("voice", "")
            if vid and entry.get("entry_id"):
                entry_id_to_vid[entry["entry_id"]] = vid
        # Resolve entry_ids to entity_ids via entity registry
        entity_remap = {}
        try:
            with open("/config/.storage/core.entity_registry", "r") as f:
                ereg = _json.load(f)
            for ent in ereg.get("data", {}).get("entities", []):
                if ent.get("platform") != "elevenlabs":
                    continue
                if not ent.get("entity_id", "").startswith("tts."):
                    continue
                cid = ent.get("config_entry_id", "")
                vid = entry_id_to_vid.get(cid)
                if vid and vid in vid_to_profile:
                    pname = vid_to_profile[vid]
                    agent = _mood_map.get(pname.lower().strip(), pname.split(" - ")[0].split()[0].lower())
                    entity_remap[ent["entity_id"]] = ("tts.elevenlabs_custom_tts", pname, agent)
        except Exception:
            pass
        return entity_remap, profile_to_agent, uuid_to_profile
    except Exception:
        return {}, {}, {}

async def _build_tts_remap() -> tuple:
    """Async wrapper — @pyscript_executor handles threading automatically."""
    return _build_tts_remap_sync()

def _voice_to_agent(voice: str, voice_id: str = "", agent: str = "") -> str:
    """Extract agent name from explicit param, profile name, or TTS entity convention."""
    if agent:
        return agent
    # Check remap dict (old entity → agent)
    remap = _TTS_ENTITY_REMAP.get(voice)
    if remap:
        return remap[2]
    # Profile name → agent (HACS custom TTS path)
    if voice_id:
        agent_match = _PROFILE_TO_AGENT.get(voice_id.lower())
        if agent_match:
            return agent_match
    # Legacy: extract from entity naming convention
    if not voice:
        return "unknown"
    parts = voice.replace("tts.", "").split("_")
    # Convention: tts.elevenlabs_{name}_text_to_speech
    for i, p in enumerate(parts):
        if p == "text" and i > 0:
            name = parts[i-1] if parts[i-1] != "elevenlabs" else parts[0]
            if name not in ("text", "to", "speech", "tts"):
                return name
    return "unknown"

# ── Tool-narration sanitization patterns ────────────────────────────────────
# LLMs sometimes narrate their tool calls instead of executing silently.
# These regexes strip leaked function names, JSON fragments, and narration.
_TOOL_FUNC_NAMES = (
    "execute_services|stop_radio|shut_up|pause_media|web_search|"
    "memory_tool|handoff_agent|escalate_action|end_conversation|"
    "agent_interaction_log|save_user_preference|"
    "email_clear_count|focus_guard_mark_meal|focus_guard_snooze|"
    "schedule_optimal_timing|memory_related|memory_link|memory_archive_search"
)
_SANITIZE_PATTERNS = None


@pyscript_compile  # noqa: F821
def _build_sanitize_patterns():
    """Build sanitize patterns using native Python (re.compile blocked in sandbox)."""
    import re as _re
    func_names = _TOOL_FUNC_NAMES
    return [
        # "I'll call execute_services" / "using the memory_tool function now" / etc.
        _re.compile(
            r"(?:i(?:'ll| will| am going to| need to)?|let me|calling|using"
            r"(?:\s+the)?)\s+(?:call(?:ing)?|us(?:e|ing)|invok(?:e|ing)|"
            r"runn?(?:ing)?|execut(?:e|ing)|trigger(?:ing)?)"
            r"(?:\s+the)?\s+(?:" + func_names + r")\b[^.!?]*[.!?]?",
            _re.IGNORECASE,
        ),
        # "Calling handoff_agent..." / "Using web_search now..."
        _re.compile(
            r"\b(?:calling|using|invoking|running|executing|triggering)"
            r"(?:\s+the)?\s+(?:" + func_names + r")\b[^.!?]*[.!?]?",
            _re.IGNORECASE,
        ),
        # Bare function names spoken mid-sentence: "...the execute_services to..."
        _re.compile(
            r"\b(?:" + func_names + r")\s*(?:function|tool|service)?\b",
            _re.IGNORECASE,
        ),
        # JSON object fragments: {"key": "value", ...}
        _re.compile(r'\{[^{}]*"[^"]*"\s*:\s*[^{}]*\}'),
        # Stray parameter-like fragments: param_name="value"
        _re.compile(r'\b\w+_\w+\s*=\s*"[^"]*"'),
        # ── Entity ID leakage ─────────────────────────────────────────────────
        # HA entity IDs spoken aloud: "light.living_room", "input_boolean.ai_foo"
        _re.compile(
            r'\b(?:light|switch|sensor|binary_sensor|media_player|input_boolean'
            r'|input_number|input_select|input_text|input_datetime|input_button'
            r'|script|automation|climate|cover|fan|lock|vacuum|person|zone'
            r'|weather|calendar|camera|number|select|button|timer|counter'
            r'|group|scene|remote|siren|update|event|text|image|notify'
            r'|device_tracker|tts|stt|assist_satellite|conversation'
            r'|pyscript)\.[a-z][a-z0-9_]*\b',
            _re.IGNORECASE,
        ),
        # ── Parameter / schema narration ──────────────────────────────────────
        # "with target quark and reason user_request"
        _re.compile(
            r'\bwith\s+(?:target|reason|operation|action_type|agent_name'
            r'|topic|query|key|value|scope|category|user|clip)\s+'
            r'(?:"[^"]*"|[a-z_]+)\b[^.!?]*[.!?]?',
            _re.IGNORECASE,
        ),
        # "the parameters are..." / "passing parameters..."
        _re.compile(
            r'\b(?:the\s+)?(?:parameters?|arguments?|payload|schema|spec)\s+'
            r'(?:are|is|include|contain|being|were|was)\b[^.!?]*[.!?]?',
            _re.IGNORECASE,
        ),
        # "function call" / "tool call" / "service call" narration
        _re.compile(
            r'\b(?:function|tool|service)\s+(?:call(?:ed|ing|s)?|definition'
            r'|schema|spec|invocation|execution|result)\b[^.!?]*[.!?]?',
            _re.IGNORECASE,
        ),
        # "type: object" / "type: string" — YAML schema fragments
        _re.compile(
            r'\btype:\s*(?:object|string|array|integer|boolean|number)\b',
            _re.IGNORECASE,
        ),
        # ── Email / web artifact catch-all (Layer 3 sanitization) ────────────
        # URLs: http(s), ftp, mailto, bare www
        _re.compile(r'https?://[^\s<>")\]]+', _re.IGNORECASE),
        _re.compile(r'ftp://[^\s<>")\]]+', _re.IGNORECASE),
        _re.compile(r'mailto:[^\s<>")\]]+', _re.IGNORECASE),
        _re.compile(r'\bwww\.[^\s<>")\]]+', _re.IGNORECASE),
        # Tracking query parameters (?utm_source=..., &fbclid=..., etc.)
        _re.compile(r'[?&](?:utm_\w+|fbclid|gclid|mc_[a-z]+|_hsenc|_hsmi|oly_\w+|vero_\w+|s_cid|mkt_tok)=[^\s&]*', _re.IGNORECASE),
        # Email headers narrated verbatim
        _re.compile(r'\b(?:Content-Type|Content-Transfer-Encoding|Content-Disposition|MIME-Version|charset|boundary)\s*[:=][^\n.!?]*[.!?]?', _re.IGNORECASE),
        # Base64 blobs (40+ chars, stricter than Layer 1)
        _re.compile(r'[A-Za-z0-9+/=]{40,}'),
        # Hex color codes (#FFFFFF, #FFF)
        _re.compile(r'#[0-9a-fA-F]{6}\b'),
        _re.compile(r'#[0-9a-fA-F]{3}\b'),
        # CSS property:value pairs
        _re.compile(r'\b(?:font-family|font-size|line-height|color|background-color|background|display|margin|padding|border|text-align|text-decoration|vertical-align|width|height|max-width|min-width)\s*:\s*[^;}{.!?]+[;]?', _re.IGNORECASE),
        # Footer phrases
        _re.compile(r'\b(?:unsubscribe|privacy\s+policy|all\s+rights\s+reserved|view\s+in\s+(?:your\s+)?browser)\b[^.!?]*[.!?]?', _re.IGNORECASE),
        _re.compile(r'\bcopyright\s+(?:©\s*)?\d{4}[^.!?]*[.!?]?', _re.IGNORECASE),
        _re.compile(r'©\s*\d{4}[^.!?]*[.!?]?'),
        _re.compile(r'\bsent\s+from\s+my\s+(?:iphone|ipad|galaxy|android|samsung)\b[^.!?]*[.!?]?', _re.IGNORECASE),
        # Empty parentheses left from stripped URLs
        _re.compile(r'\(\s*\)'),
        # ── Whitespace / punctuation cleanup (moved from bare re.sub calls) ──
        _re.compile(r'\s{2,}'),
        _re.compile(r'^[,;.\s]+'),
    ]


@pyscript_compile  # noqa: F821
def _sanitize_tool_narration_compiled(text: str, patterns: list) -> str:
    """Apply sanitize patterns and clean up whitespace (native Python)."""
    # All patterns except the last two are content patterns
    # Last two are: multi-space collapse and leading-punctuation strip
    content_patterns = patterns[:-2]
    ws_pattern = patterns[-2]
    lead_pattern = patterns[-1]
    for pat in content_patterns:
        text = pat.sub("", text)
    text = ws_pattern.sub(" ", text).strip()
    text = lead_pattern.sub("", text).strip()
    return text or None


def _sanitize_tool_narration(text: str) -> str:
    """Strip leaked tool/function narration from LLM speech text."""
    global _SANITIZE_PATTERNS
    if _SANITIZE_PATTERNS is None:
        _SANITIZE_PATTERNS = _build_sanitize_patterns()
    return _sanitize_tool_narration_compiled(text, _SANITIZE_PATTERNS)

# ── Dynamic Speaker Cache ────────────────────────────────────────────────────
# Populated lazily from: helper JSON → fallback.
# Structure:
#   zone_speaker_map:  dict[zone_name → list[media_player entity_id]]  (ranked)
#   zone_priority:     list[zone_name]  (scan order for presence)
#   fp2_zone_entities: dict[binary_sensor entity_id → zone_name]
#   all_speakers:      list[media_player entity_id]
_speaker_cache: dict | None = None


_queue: list[dict] = []
_deferred_queue: list[dict] = []  # I-30: items deferred during phone calls
_queue_lock = threading.Lock()
_processing = False
_current_item: dict | None = None
_preempted = False
_pre_queue_playing: dict = {}  # entity_id → True if was playing before queue started
result_entity_name: dict[str, str] = {}


def _ensure_result_entity_name(force: bool = False) -> None:
    global result_entity_name
    if force or not result_entity_name:
        result_entity_name = build_result_entity_name(RESULT_ENTITY)

def _set_result(state_value: str = "ok", **attrs: Any) -> None:
    _ensure_result_entity_name()
    attrs.update(result_entity_name)
    state.set(RESULT_ENTITY, value=state_value, new_attributes=attrs)  # noqa: F821


# ── Speaker Discovery ────────────────────────────────────────────────────────

SPEAKER_CONFIG_FILE = "/config/pyscript/tts_speaker_config.json"


@pyscript_executor  # noqa: F821
def _load_speaker_config_sync(config_file: str) -> dict:
    """Load zone→speaker map from JSON config file (sync).

    File format:
      {"zone_speaker_map": {"workshop": ["media_player.sonos"], ...}}
    Values can be a single string or a ranked list. Always normalizes to lists.
    """
    import json as _json
    try:
        with open(config_file, "r") as fh:
            data = _json.loads(fh.read())
        raw = data.get("zone_speaker_map", {})
        result = {}
        for zone, speakers in raw.items():
            if isinstance(speakers, list):
                result[zone] = speakers
            else:
                result[zone] = [speakers]
        return result
    except Exception:
        return {}


async def _load_speaker_config(config_file: str) -> dict:
    """Async wrapper — @pyscript_executor handles thread dispatch."""
    return _load_speaker_config_sync(config_file)


@pyscript_executor  # noqa: F821
def _write_speaker_config_sync(config_file: str, zone_speaker_map: dict) -> bool:
    """Write zone→speaker map to JSON config file, preserving speaker_options (sync)."""
    import json as _json
    try:
        # Read existing file to preserve speaker_options
        existing_data = {}
        try:
            with open(config_file, "r") as fh:
                existing_data = _json.loads(fh.read())
        except Exception:
            pass
        data = {"zone_speaker_map": zone_speaker_map}
        if "speaker_options" in existing_data:
            data["speaker_options"] = existing_data["speaker_options"]
        with open(config_file, "w") as fh:
            fh.write(_json.dumps(data, indent=2))
        return True
    except Exception:
        return False


async def _write_speaker_config(config_file: str, zone_speaker_map: dict) -> bool:
    """Async wrapper — @pyscript_executor handles thread dispatch."""
    return _write_speaker_config_sync(config_file, zone_speaker_map)


ENTITY_REGISTRY_FILE = "/config/.storage/core.entity_registry"


@pyscript_executor  # noqa: F821
def _discover_speakers_from_registry_sync(registry_file: str) -> dict:
    """Read HA entity registry storage file for media_player speakers with area_id (sync).

    Returns dict[area_id → list[entity_id]] for speakers assigned to areas.
    """
    import json as _json
    discovered = {}
    try:
        with open(registry_file, "r") as fh:
            data = _json.loads(fh.read())
        entities = data.get("data", {}).get("entities", [])
        for entry in entities:
            if (
                entry.get("entity_id", "").startswith("media_player.")
                and entry.get("area_id")
                and not entry.get("disabled_by")
                and entry.get("original_device_class") == "speaker"
            ):
                area = entry["area_id"]
                entity = entry["entity_id"]
                if area not in discovered:
                    discovered[area] = []
                discovered[area].append(entity)
    except Exception:
        pass
    return discovered


async def _discover_speakers_from_registry(registry_file: str) -> dict:
    """Async wrapper — @pyscript_executor handles thread dispatch."""
    return _discover_speakers_from_registry_sync(registry_file)


async def _rebuild_speaker_config() -> dict:
    """Scan entity registry for area-assigned speakers, merge with
    existing config file, and write back. Returns rebuild summary.

    Discovery: queries HA entity registry API for media_player entities
    with device_class=speaker and area_id set.
    Registry speakers are inserted at the top of each zone's ranked list.
    Existing file entries for zones without a registry speaker are preserved.
    """
    global _speaker_cache

    # 1. Discover speakers from entity registry storage file
    discovered = await _discover_speakers_from_registry(ENTITY_REGISTRY_FILE)

    # 2. Load existing config file as baseline
    existing = await _load_speaker_config(SPEAKER_CONFIG_FILE)

    # 3. Merge: registry speakers go to top of list, existing preserved
    merged = dict(existing)
    for area_id, speakers in discovered.items():
        if area_id in merged:
            # Prepend registry speakers, dedup
            current = merged[area_id]
            new_list = list(speakers)
            for s in current:
                if s not in new_list:
                    new_list.append(s)
            merged[area_id] = new_list
        else:
            merged[area_id] = speakers

    # 4. If nothing at all, log error and return empty
    #    (no hardcoded fallback — config file or registry must provide data)
    if not merged:
        log.error(  # noqa: F821
            "tts_queue: rebuild produced empty config — "
            "no speakers in registry or config file"
        )
        _speaker_cache = None
        return {
            "status": "empty", "op": "rebuild_speaker_config",
            "existing_zones": 0, "discovered_zones": 0,
            "merged_zones": 0, "written": False,
        }

    # 5. Write back (only when we have real data)
    write_ok = await _write_speaker_config(SPEAKER_CONFIG_FILE, merged)

    # 6. Invalidate caches so next call picks up new config
    _speaker_cache = None

    summary = {
        "status": "ok" if write_ok else "write_failed",
        "op": "rebuild_speaker_config",
        "existing_zones": len(existing),
        "discovered_zones": len(discovered),
        "merged_zones": len(merged),
        "written": write_ok,
    }

    log.info(  # noqa: F821
        f"tts_queue: speaker config rebuilt — "
        f"{len(existing)} existing, {len(discovered)} discovered, "
        f"{len(merged)} merged, written={write_ok}"
    )

    return summary


def _normalize_speaker(s: str) -> str:
    """Ensure speaker entity_id has media_player. prefix."""
    if s and "." not in s:
        return f"media_player.{s}"
    return s


async def _ensure_speaker_cache() -> None:
    """Lazy-load speaker/zone mappings.

    Priority: JSON config file → entity registry discovery.
    Zone priority from helper CSV → derived from zone_speaker_map keys.
    FP2 zones auto-discovered from zone_speaker_map keys.
    """
    global _speaker_cache
    if _speaker_cache is not None:
        return

    try:
        # 1. Load zone→speaker from JSON config file
        zone_speaker_map = await _load_speaker_config(SPEAKER_CONFIG_FILE)

        # 2. If still empty, log error — no hardcoded fallback
        if not zone_speaker_map:
            log.error(  # noqa: F821
                "tts_queue: no speaker mappings found in config file — "
                "run tts_rebuild_speaker_config or populate "
                "tts_speaker_config.json"
            )

        # 3. Load zone priority order from helper CSV
        priority_raw = state.get(  # noqa: F821
            "input_text.ai_tts_zone_priority"
        ) or ""
        if priority_raw and priority_raw not in ("unknown", "unavailable", ""):
            zone_priority = [
                z.strip() for z in priority_raw.split(",") if z.strip()
            ]
        else:
            # Derive from zone_speaker_map keys if no helper
            zone_priority = list(zone_speaker_map.keys()) if zone_speaker_map else []

        # 4. Build FP2 zone entities from map keys
        fp2_zones = {
            f"binary_sensor.fp2_presence_sensor_{z}": z
            for z in zone_speaker_map
        }

        # 5. Derive ALL_SPEAKERS from unique speakers across all zones
        seen = {}
        for speakers in zone_speaker_map.values():
            for s in speakers:
                if s not in seen:
                    seen[s] = True
        all_speakers = list(seen.keys())
        if not all_speakers:
            log.error(  # noqa: F821
                "tts_queue: no speakers discovered — "
                "all_speakers is empty"
            )

        _speaker_cache = {
            "zone_speaker_map": zone_speaker_map,
            "zone_priority": zone_priority,
            "fp2_zone_entities": fp2_zones,
            "all_speakers": all_speakers,
        }

        log.info(  # noqa: F821
            f"tts_queue: loaded {len(zone_speaker_map)} zone→speaker mappings, "
            f"{len(zone_priority)} priority zones, "
            f"{len(all_speakers)} speakers"
        )
    except Exception as exc:
        log.error(  # noqa: F821
            f"tts_queue: speaker cache load failed: {exc}"
        )
        _speaker_cache = {
            "zone_speaker_map": {},
            "zone_priority": [],
            "fp2_zone_entities": {},
            "all_speakers": [],
        }


# ── Cache Functions ───────────────────────────────────────────────────────────

@pyscript_executor  # noqa: F821
def _cache_key_sync(text: str, voice: str) -> str:
    return hashlib.sha256(f"{voice}:{text}".encode("utf-8")).hexdigest()[:16]

@pyscript_executor  # noqa: F821
def _cache_check_sync(key: str) -> dict | None:
    mp3 = CACHE_DIR / f"{key}.mp3"
    meta = CACHE_DIR / f"{key}.json"
    if not mp3.exists() or not meta.exists():
        return None
    try:
        with open(meta, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

@pyscript_compile  # noqa: F821
def _cache_save_sync(key: str, source_path: str, duration: float, hint: str) -> bool:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, str(CACHE_DIR / f"{key}.mp3"))
        with open(CACHE_DIR / f"{key}.json", "w") as f:
            json.dump({"duration": duration, "hint": hint, "created": datetime.now().isoformat()}, f)
        return True
    except OSError:
        return False

@pyscript_executor  # noqa: F821
def _cache_cleanup_daily_sync() -> int:
    removed = 0
    today = datetime.now().date()
    if not CACHE_DIR.exists():
        return 0
    for meta_path in CACHE_DIR.glob("*.json"):
        try:
            with open(meta_path, "r") as f:
                data = json.load(f)
            if data.get("hint") != "daily":
                continue
            if datetime.fromisoformat(data["created"]).date() < today:
                meta_path.with_suffix(".mp3").unlink(missing_ok=True)
                meta_path.unlink(missing_ok=True)
                removed += 1
        except (json.JSONDecodeError, OSError, KeyError, ValueError):
            continue
    return removed

@pyscript_executor  # noqa: F821
def _cache_cleanup_expired_sync(max_age_days: int = 30, static_max_age_days: int = 90) -> int:
    removed = 0
    now = datetime.now()
    if not CACHE_DIR.exists():
        return 0
    for meta_path in CACHE_DIR.glob("*.json"):
        try:
            with open(meta_path, "r") as f:
                data = json.load(f)
            hint = data.get("hint", "none")
            if hint == "static":
                cutoff = now - timedelta(days=static_max_age_days)
            elif hint == "session":
                cutoff = now - timedelta(hours=4)
            else:
                cutoff = now - timedelta(days=max_age_days)
            created = datetime.fromisoformat(data["created"])
            if created < cutoff:
                meta_path.with_suffix(".mp3").unlink(missing_ok=True)
                meta_path.unlink(missing_ok=True)
                removed += 1
        except (json.JSONDecodeError, OSError, KeyError, ValueError):
            continue
    return removed

@pyscript_executor  # noqa: F821
def _cache_evict_by_size_sync(max_size_mb: int = 500, protect_age_hours: float = 1.0) -> int:
    """LRU eviction: remove oldest cache entries when total size exceeds cap."""
    if not CACHE_DIR.exists():
        return 0
    now = datetime.now()
    protect_cutoff = now - timedelta(hours=protect_age_hours)
    entries = []
    total_size = 0
    for meta_path in CACHE_DIR.glob("*.json"):
        try:
            mp3_path = meta_path.with_suffix(".mp3")
            if not mp3_path.exists():
                continue
            with open(meta_path, "r") as f:
                data = json.load(f)
            mp3_size = mp3_path.stat().st_size
            total_size += mp3_size
            entries.append({
                "meta": meta_path,
                "mp3": mp3_path,
                "size": mp3_size,
                "created": datetime.fromisoformat(data["created"]),
            })
        except (json.JSONDecodeError, OSError, KeyError, ValueError):
            continue
    max_bytes = max_size_mb * 1024 * 1024
    if total_size <= max_bytes:
        return 0
    # Sort oldest first for LRU eviction
    entries.sort(key=lambda e: e["created"])
    evicted = 0
    for entry in entries:
        if total_size <= max_bytes:
            break
        # Skip entries younger than protection window
        if entry["created"] >= protect_cutoff:
            continue
        try:
            entry["mp3"].unlink(missing_ok=True)
            entry["meta"].unlink(missing_ok=True)
            total_size -= entry["size"]
            evicted += 1
        except OSError:
            continue
    return evicted

@pyscript_executor  # noqa: F821
def _ha_tts_cleanup_sync(max_age_days: int = 30, protect_age_hours: float = 1.0) -> int:
    """Age-based cleanup of HA's native TTS cache (/config/tts/).
    No metadata files — uses file mtime for age determination."""
    if not HA_TTS_DIR.exists():
        return 0
    now = datetime.now()
    cutoff = now - timedelta(days=max_age_days)
    protect_cutoff = now - timedelta(hours=protect_age_hours)
    removed = 0
    for f in HA_TTS_DIR.iterdir():
        if not f.is_file():
            continue
        try:
            mtime = datetime.fromtimestamp(f.stat().st_mtime)
            if mtime < cutoff and mtime < protect_cutoff:
                f.unlink(missing_ok=True)
                removed += 1
        except OSError:
            continue
    return removed

@pyscript_executor  # noqa: F821
def _try_populate_cache_sync(text: str, voice: str, key: str, hint: str) -> bool:
    """Find TTS output in HA's cache (/config/tts/) and copy to our cache."""
    import hashlib as _hl
    from pathlib import Path as _P

    ha_hash = _hl.sha1(text.encode()).hexdigest()
    ha_tts_dir = _P("/config/tts")

    # HA filename: {sha1}_{lang}_{options_hash}_{engine}.{ext}
    matches = sorted(ha_tts_dir.glob(f"{ha_hash}_*"),
                     key=lambda p: p.stat().st_mtime, reverse=True)
    if not matches:
        return False

    source = str(matches[0])
    # Estimate duration from file size (~10KB/sec for MP3)
    size = matches[0].stat().st_size
    duration = max(1.0, size / 10000)

    return _cache_save_sync(key, source, duration, hint)

async def _cache_key(text, voice):
    return _cache_key_sync(text, voice)
async def _cache_check(key):
    return _cache_check_sync(key)
async def _cache_save(key, source_path, duration, hint):
    return await asyncio.to_thread(_cache_save_sync, key, source_path, duration, hint)
async def _try_populate_cache(text, voice, key, hint):
    return _try_populate_cache_sync(text, voice, key, hint)
async def _cache_cleanup_daily():
    return _cache_cleanup_daily_sync()
async def _cache_cleanup_expired(max_age_days=30, static_max_age_days=90):
    return _cache_cleanup_expired_sync(max_age_days, static_max_age_days)
async def _cache_evict_by_size(max_size_mb=500, protect_age_hours=1.0):
    return _cache_evict_by_size_sync(max_size_mb, protect_age_hours)
async def _ha_tts_cleanup(max_age_days=30, protect_age_hours=1.0):
    return _ha_tts_cleanup_sync(max_age_days, protect_age_hours)


# ── Speaker Resolution ────────────────────────────────────────────────────────

def _get_default_speaker() -> str:
    """Return the configured default speaker, or first from config."""
    try:
        default = state.get("input_text.ai_default_speaker")  # noqa: F821
        if default and default not in ("unknown", "unavailable", ""):
            return _normalize_speaker(default)
    except Exception:
        pass
    if _speaker_cache and _speaker_cache["all_speakers"]:
        return _speaker_cache["all_speakers"][0]
    log.error(  # noqa: F821
        "tts_queue: no default speaker available — "
        "speaker cache empty and input_text.ai_default_speaker not set"
    )
    return "media_player.unknown"


async def _resolve_speaker(target_mode: str, target: str | None) -> str | list[str]:
    try:
        await _ensure_speaker_cache()
        zone_speaker_map = _speaker_cache["zone_speaker_map"]
        zone_priority = _speaker_cache["zone_priority"]
        all_speakers = _speaker_cache["all_speakers"]

        if target_mode == "explicit":
            return _normalize_speaker(target) if target else _get_default_speaker()
        if target_mode == "source_room":
            return _normalize_speaker(target) if target else _get_default_speaker()
        if target_mode == "broadcast":
            return all_speakers

        # Scan zones in priority order; pick first available speaker in winning zone
        for zone in zone_priority:
            fp2_entity = f"binary_sensor.fp2_presence_sensor_{zone}"
            try:
                if state.get(fp2_entity) != "on":  # noqa: F821
                    continue
            except Exception:
                continue
            speakers = zone_speaker_map.get(zone, [])
            for speaker in speakers:
                try:
                    spk_state = state.get(speaker)  # noqa: F821
                    if spk_state not in ("unavailable", None):
                        return speaker
                except Exception:
                    continue
            # All speakers in this zone unavailable — try next zone

        return _get_default_speaker()
    except Exception as exc:
        log.error(  # noqa: F821
            f"tts_queue: speaker resolution failed: {exc}"
        )
        return _get_default_speaker()


# ── Queue Management ──────────────────────────────────────────────────────────

@pyscript_compile  # noqa: F821
def _queue_add_sync(item: dict) -> int:
    with _queue_lock:
        _queue.append(item)
        _queue.sort(key=lambda x: (x["priority"], x["added_at"]))
        return len(_queue)

@pyscript_compile  # noqa: F821
def _queue_pop_sync() -> dict | None:
    with _queue_lock:
        return _queue.pop(0) if _queue else None

@pyscript_compile  # noqa: F821
def _queue_length_sync() -> int:
    with _queue_lock:
        return len(_queue)

@pyscript_compile  # noqa: F821
def _queue_count_by_priority_sync(priority: int) -> int:
    with _queue_lock:
        return sum(1 for item in _queue if item["priority"] == priority)


# ── Playback ──────────────────────────────────────────────────────────────────

async def _play_tts(
    speaker: str | list[str],
    text: str,
    voice: str,
    volume_level: float | None = None,
    voice_id: str = "",
) -> None:
    """Play TTS via tts.speak. Announce/ducking is automatic on supported speakers."""
    # Guard: reject text that's only whitespace, emojis, or speaker tags —
    # ElevenLabs strips these and returns 400 "input_text_empty".
    stripped = re.sub(r'[\s\U00010000-\U0010ffff\u200d\u2600-\u27bf\ufe0f]', '', text or '')
    if not stripped:
        log.warning(f"tts_queue: skipping empty-after-strip text: {text!r}")  # noqa: F821
        return
    # ── Transparent remap: old per-character entities → HACS custom TTS ──
    remap = _TTS_ENTITY_REMAP.get(voice)
    if remap:
        voice = remap[0]       # tts.elevenlabs_custom_tts
        voice_id = remap[1]    # profile name (e.g., "Quark - Kwork v0.6")
    elif voice == "tts.elevenlabs_custom_tts" and voice_id:
        # Already targeting HACS entity — resolve UUID → profile name if needed
        profile = _VOICE_UUID_TO_PROFILE.get(voice_id)
        if profile:
            voice_id = profile
    targets = speaker if isinstance(speaker, list) else [speaker]
    if volume_level is not None and volume_level > 0:
        for s in targets:
            try:
                service.call("media_player", "volume_set",  # noqa: F821
                             entity_id=s, volume_level=volume_level)
            except Exception:
                pass
    # ── Voice mood modulation (v3): stability + tag prefix ──
    _mood_opts = {}
    _mood_tags = ""
    if state.get("input_boolean.ai_voice_mood_enabled") == "on":  # noqa: F821
        _agent = _voice_to_agent(voice, voice_id=voice_id)
        if _agent and _agent != "unknown":
            # Stability — the one VoiceSettings param v3 respects
            _sv = state.get(f"input_number.ai_voice_mood_{_agent}_stability")  # noqa: F821
            if _sv not in (None, "unknown", "unavailable"):
                _mood_opts["stability"] = float(_sv)
            # Tag prefix for non-tagged text
            _tv = state.get(f"input_text.ai_voice_mood_{_agent}_tags")  # noqa: F821
            if _tv not in (None, "unknown", "unavailable", ""):
                _mood_tags = _tv.strip()
    # Inject mood tags for non-tagged messages (notifications, announcements).
    # Messages from agents already contain tags — "[" check avoids double-tagging.
    if _mood_tags and "[" not in text:
        text = f"{_mood_tags} {text}"

    for s in targets:
        try:
            kwargs = dict(
                entity_id=voice,
                media_player_entity_id=s,
                message=text,
            )
            if voice_id:
                kwargs["options"] = {"voice": voice_id}
            # Merge mood modulation values into options
            if _mood_opts:
                opts = kwargs.get("options", {})
                opts.update(_mood_opts)
                kwargs["options"] = opts
            service.call("tts", "speak", **kwargs)  # noqa: F821
        except Exception as e:
            # ── T24-1a: ElevenLabs outage fallback → HA Cloud ──
            if _is_elevenlabs_voice(voice):
                fallback_voice = _get_fallback_tts_voice()
                log.warning(  # noqa: F821
                    f"tts_queue: ElevenLabs failed for {s} ({e}), "
                    f"retrying with {fallback_voice}"
                )
                try:
                    # Strip stage directions for HA Cloud (can't process them)
                    fallback_text = re.sub(r'\[.*?\]', '', text).strip() or text
                    service.call("tts", "speak",  # noqa: F821
                                 entity_id=fallback_voice,
                                 media_player_entity_id=s,
                                 message=fallback_text)
                except Exception as e2:
                    log.error(f"tts_queue: HA Cloud fallback also failed for {s}: {e2}")  # noqa: F821
            else:
                log.error(f"tts_queue: tts.speak failed for {s}: {e}")  # noqa: F821

async def _play_media(
    speaker: str | list[str],
    media_path: str,
    volume_level: float | None = None,
    announce: bool = False,
) -> None:
    """Play a media file via media_player.play_media."""
    targets = speaker if isinstance(speaker, list) else [speaker]
    if volume_level is not None and volume_level > 0:
        for s in targets:
            try:
                service.call("media_player", "volume_set",  # noqa: F821
                             entity_id=s, volume_level=volume_level)
            except Exception:
                pass
    for s in targets:
        try:
            kwargs = {
                "entity_id": s,
                "media_content_id": media_path,
                "media_content_type": "music",
            }
            if announce:
                kwargs["announce"] = True
            service.call("media_player", "play_media", **kwargs)  # noqa: F821
        except Exception as e:
            log.error(f"tts_queue: play_media failed for {s}: {e}")  # noqa: F821

async def _stop_playback(speaker: str | list[str]) -> None:
    targets = speaker if isinstance(speaker, list) else [speaker]
    for s in targets:
        try:
            service.call("media_player", "media_stop", entity_id=s)  # noqa: F821
        except Exception as exc:
            log.warning("tts_queue: media_stop failed for %s: %s", s, exc)  # noqa: F821

def _is_speaker_playing(entity_id: str) -> bool:
    """Check if a media_player entity is currently playing."""
    try:
        return state.get(entity_id) == "playing"  # noqa: F821
    except Exception:
        return False


def _get_playback_timeout() -> float:
    """Return playback timeout from helper (default 30s)."""
    return _get_max_timeout()


async def _wait_for_playback_done(speaker) -> None:
    """Wait for speaker(s) to finish playing. Three-phase poll pattern."""
    global _preempted
    targets = speaker if isinstance(speaker, list) else [speaker]

    # Phase 1: Settle — wait for speaker to enter 'playing' state
    settle_deadline = asyncio.get_event_loop().time() + PLAYBACK_SETTLE_DELAY
    while asyncio.get_event_loop().time() < settle_deadline:
        if _preempted:
            return
        for t in targets:
            if _is_speaker_playing(t):
                break
        else:
            await asyncio.sleep(0.05)
            continue
        break  # at least one speaker is playing
    else:
        # Speaker never entered 'playing' — post-buffer and return
        if not _preempted:
            await asyncio.sleep(_get_post_buffer())
        return

    # Phase 2: Poll — wait for speaker(s) to leave 'playing' state
    timeout = _get_playback_timeout()
    poll_deadline = asyncio.get_event_loop().time() + timeout
    timed_out = True
    while asyncio.get_event_loop().time() < poll_deadline:
        if _preempted:
            return
        any_playing = False
        for t in targets:
            if _is_speaker_playing(t):
                any_playing = True
                break
        if not any_playing:
            timed_out = False
            break
        await asyncio.sleep(_get_poll_interval())

    if timed_out:
        log.warning(  # noqa: F821
            f"tts_queue: playback timeout ({timeout}s) waiting for "
            f"{targets[0] if len(targets) == 1 else targets}"
        )

    # Phase 3: Post-buffer — hardware audio lag after entity goes idle
    if not _preempted:
        await asyncio.sleep(_get_post_buffer())


def _increment_counter(entity_id: str) -> None:
    global _budget_save_counter
    try:
        current = float(state.get(entity_id) or 0)  # noqa: F821
        service.call("input_number", "set_value",  # noqa: F821
                     entity_id=entity_id, value=current + 1)
    except Exception:
        pass
    # I-33: Trigger budget save every 10 TTS calls
    _budget_save_counter += 1
    if _budget_save_counter >= 10:
        _budget_save_counter = 0
        try:
            task.create(_budget_save_to_l2())  # noqa: F821
        except Exception:
            pass

def _increment_counter_by(entity_id: str, amount: int) -> None:
    """Increment a counter by a specific amount (I-33: TTS char counting)."""
    try:
        current = float(state.get(entity_id) or 0)  # noqa: F821
        service.call("input_number", "set_value",  # noqa: F821
                     entity_id=entity_id, value=min(current + amount, 999999))
    except Exception:
        pass


# ── Preemption ────────────────────────────────────────────────────────────────

async def _maybe_preempt(new_priority: int) -> bool:
    global _preempted
    if _current_item is None:
        return False
    if new_priority < _current_item["priority"]:
        speaker = _current_item.get("resolved_speaker")
        if speaker:
            await _stop_playback(speaker)
        _preempted = True
        return True
    return False


# ── Queue Processor ───────────────────────────────────────────────────────────



async def _process_queue() -> None:
    global _processing, _current_item, _preempted, _pre_queue_playing
    _set_result("processing", op="queue_drain")
    try:
        while True:
            item = _queue_pop_sync()
            if item is None:
                break
            with _queue_lock:
                _current_item = item
                _preempted = False

            # Track pre-queue playing state for announce-native speakers
            # so we can resume music after queue drains if preemption
            # interrupted the announce context (media_stop kills both
            # the TTS and the underlying stream on Sonos).
            if item.get("announce_native"):
                speaker = item.get("resolved_speaker")
                if speaker and speaker not in _pre_queue_playing:
                    if _is_speaker_playing(speaker):
                        _pre_queue_playing[speaker] = True

            # Snapshot speaker state before playback — used by the
            # was-playing fallback in the completion detection below.
            _pre_speaker = item.get("resolved_speaker")
            if _pre_speaker and isinstance(_pre_speaker, str):
                item["_was_playing_before"] = _is_speaker_playing(_pre_speaker)

            try:
                await _play_item(item)
                with _queue_lock:
                    was_preempted = _preempted
                if not was_preempted and not item.get("test_mode"):
                    speaker = item.get("resolved_speaker")
                    if speaker:
                        # Announce-capable speakers (Sonos/ESP) don't change
                        # entity state reliably during announce — use a
                        # text-length estimate instead of state polling.
                        if item.get("announce_native"):
                            text_len = len(item.get("text") or "")
                            gen_buf = _get_generation_buffer()
                            est_secs = max(2.0, text_len / 11.0) + gen_buf
                            log.info(  # noqa: F821
                                f"tts_queue: announce-native wait "
                                f"{est_secs:.1f}s for {text_len} chars "
                                f"(gen_buf={gen_buf:.1f})"
                            )
                            await asyncio.sleep(est_secs)
                        else:
                            # If speaker was already playing (e.g. radio/music),
                            # state polling won't work — it never leaves 'playing'.
                            # Fall back to text-length time estimate.
                            if item.get("_was_playing_before"):
                                text_len = len(item.get("text") or "")
                                gen_buf = _get_generation_buffer()
                                est_secs = max(2.0, text_len / 11.0) + gen_buf
                                log.info(  # noqa: F821
                                    f"tts_queue: was-playing fallback wait "
                                    f"{est_secs:.1f}s for {text_len} chars "
                                    f"on {speaker} (gen_buf={gen_buf:.1f})"
                                )
                                await asyncio.sleep(est_secs)
                            else:
                                await _wait_for_playback_done(speaker)
                    else:
                        await asyncio.sleep(_get_playback_buffer())

                # ── Fire completion event for downstream coordination ──
                # Re-read preemption flag (may have changed during wait)
                if not item.get("test_mode"):
                    with _queue_lock:
                        _final_preempted = _preempted
                    _meta = dict(item.get("metadata") or {})
                    # Strip reserved keys to prevent overwrites
                    for _rk in ("completed", "priority", "speaker"):
                        _meta.pop(_rk, None)
                    event.fire(  # noqa: F821
                        "tts_queue_item_completed",
                        completed=not _final_preempted,
                        priority=item.get("priority", 3),
                        speaker=str(item.get("resolved_speaker") or ""),
                        **_meta,
                    )
            except Exception as e:
                log.error(f"tts_queue playback error: {e}")  # noqa: F821
    finally:
        # Resume announce-native speakers that were playing before the
        # queue started but got stopped by preemption (media_stop).
        for spk in list(_pre_queue_playing):
            try:
                spk_state = state.get(spk)  # noqa: F821
                if spk_state in ("paused", "idle"):
                    service.call("media_player", "media_play",  # noqa: F821
                                 entity_id=spk)
                    log.info(  # noqa: F821
                        f"tts_queue: resumed {spk} after queue drain "
                        f"(was playing before TTS)"
                    )
            except Exception as exc:
                log.warning(f"tts_queue: resume {spk} failed: {exc}")  # noqa: F821
        _pre_queue_playing = {}

        with _queue_lock:
            _current_item = None
            _processing = False
        _set_result("idle", op="queue_idle", queue_length=0)

async def _play_item(item: dict) -> None:
    """Play a single queue item via tts.speak or media_player.play_media."""
    text = item.get("text")
    voice = item.get("voice")
    # Strip LLM stage directions like [thoughtful pause], [sigh], [pause]
    # Preserve for ElevenLabs eleven_v3 (processes [tags] as performative cues)
    if text:
        try:
            strip_dirs = state.get("input_boolean.ai_tts_strip_stage_directions") != "off"
        except Exception:
            strip_dirs = True
        if strip_dirs and not _is_elevenlabs_voice(voice):
            text = re.sub(r'\[.*?\]', '', text).strip() or None
    # Strip leaked tool/function narration from LLM responses
    if text:
        text = _sanitize_tool_narration(text)
    speaker = item.get("resolved_speaker")
    volume_level = item.get("volume_level")
    announce = item.get("announce", True)
    media_file = item.get("media_file")
    voice_id = item.get("voice_id", "")
    test_mode = item.get("test_mode", False)
    cache_hint = item.get("cache", "none")

    # ── I-30: Defer during phone calls (P0 emergency always plays) ──
    if (
        item.get("priority", 3) > PRIORITY_EMERGENCY
        and state.get("input_boolean.ai_phone_call_active") == "on"  # noqa: F821
        and state.get("input_boolean.ai_phone_call_defer_tts") == "on"  # noqa: F821
    ):
        with _queue_lock:
            _deferred_queue.append(item)
        log.debug(  # noqa: F821
            f"tts_queue: deferred during phone call "
            f"(priority={item['priority']}, deferred={len(_deferred_queue)})"
        )
        return

    # ── I-38: Conflict mode check (skip/wait/override) ──
    if speaker and not isinstance(speaker, list):
        try:
            conflict_mode = state.get("input_select.ai_tts_conflict_mode") or "override"  # noqa: F821
            if conflict_mode == "skip" and state.get(speaker) == "playing":  # noqa: F821
                log.debug(f"tts_queue: skipped — {speaker} already playing (conflict=skip)")  # noqa: F821
                return
            elif conflict_mode == "wait" and state.get(speaker) == "playing":  # noqa: F821
                log.debug(f"tts_queue: waiting — {speaker} playing (conflict=wait)")  # noqa: F821
                await asyncio.sleep(1.5)
        except Exception:
            pass

    # ── I-46: ElevenLabs credit gate + budget fallback + test session TTS swap ──
    if voice and _is_elevenlabs_voice(voice):
        try:
            tts_test = state.get("input_boolean.ai_tts_test_mode") == "on"  # noqa: F821
            fallback_on = state.get("input_boolean.ai_budget_fallback_active") == "on"  # noqa: F821
            credits_low = False
            if not tts_test and not fallback_on:
                credits = int(float(
                    state.get("sensor.elevenlabs_credits_remaining") or "999999"  # noqa: F821
                ))
                floor = int(float(
                    state.get("input_number.ai_elevenlabs_credit_floor") or "5000"  # noqa: F821
                ))
                credits_low = credits <= floor
            if tts_test or fallback_on or credits_low:
                original_voice = voice
                voice = _get_fallback_tts_voice()
                item["voice"] = voice
                item["voice_id"] = ""
                voice_id = ""
                reason = "test_session" if tts_test else ("fallback" if fallback_on else "credits_low")
                log.info(  # noqa: F821
                    f"tts_queue: TTS swap {original_voice} → {voice} ({reason})"
                )
                # Strip ElevenLabs stage direction tags — HA Cloud speaks them literally
                if text:
                    text = re.sub(r'\[.*?\]', '', text).strip() or text
        except Exception:
            pass  # fail-open: play with original voice

    _increment_counter("input_number.ai_tts_calls_today")

    # I-33: Count TTS characters (ElevenLabs billing unit)
    if text:
        _increment_counter_by("input_number.ai_tts_chars_today", len(text))

    # I-33 Phase 2: Per-agent TTS tracking
    try:
        tts_agent = _voice_to_agent(voice, voice_id=voice_id, agent=item.get("agent", ""))
        service.call(  # noqa: F821
            "pyscript", "budget_track_call",
            service_type="tts",
            agent=tts_agent,
            calls=1,
            chars=len(text) if text else 0,
        )
    except Exception:
        pass

    if test_mode:
        log.info(  # noqa: F821
            f"tts_queue [TEST] priority={item['priority']} "
            f"speaker={speaker} text={text!r} voice={voice}"
        )
        return

    # ── Volume save (for restore_volume callers) ──
    original_volume = None
    restore_vol = item.get("restore_volume", False)
    restore_delay_sec = item.get("volume_restore_delay", 8)
    speaker_single = speaker if isinstance(speaker, str) else (speaker[0] if speaker else None)

    if restore_vol and volume_level and float(volume_level) > 0 and speaker_single:
        try:
            original_volume = float(state.get(speaker_single + ".volume_level") or 0)  # noqa: F821
            if original_volume <= 0:
                original_volume = None  # no valid volume to restore
        except Exception as exc:
            log.warning(f"tts_queue: volume save failed for {speaker_single}: {exc}")  # noqa: F821

    # ── Duck background media via duck_manager ──
    # Skip ducking entirely for announce-native speakers — they handle
    # ducking locally via announce mode, no need to duck other rooms.
    session_id = None
    if item.get("duck", True) and not item.get("announce_native"):
        try:
            speaker_detail = speaker if isinstance(speaker, str) else speaker[0]
            result = await hass.services.async_call(  # noqa: F821
                "pyscript", "duck_manager_duck",
                {"source": "tts_queue", "detail": speaker_detail},
                blocking=True, return_response=True,
            )
            if result:
                session_id = result.get("session_id", "")
        except Exception as exc:
            log.warning(f"tts_queue: duck_manager_duck failed: {exc}")  # noqa: F821

    try:
        # ── I-10: Pre-speech chime/jingle (activated from "reserved") ──
        chime = item.get("chime_path")
        if chime:
            await _play_media(speaker=speaker, media_path=chime,
                              volume_level=volume_level, announce=announce)
            chime_dur = item.get("chime_duration_ms", 0)
            if chime_dur > 0:
                post_buf = _get_post_buffer()
                wait_s = (chime_dur / 1000.0) + post_buf
                log.debug("tts_queue: chime wait %.2fs (duration=%dms + buffer=%.1fs)",  # noqa: F821
                          wait_s, chime_dur, post_buf)
                await asyncio.sleep(wait_s)
            else:
                await asyncio.sleep(_get_post_buffer())

        if media_file:
            await _play_media(speaker=speaker, media_path=media_file,
                              volume_level=volume_level)
            return

        if text and voice:
            # ── Cache HIT path ──
            if cache_hint != "none":
                key = await _cache_key(text, voice)
                hit = await _cache_check(key)
                if hit:
                    _increment_counter("input_number.ai_tts_cache_hits_today")
                    await _play_media(
                        speaker=speaker,
                        media_path=f"/local/tts_cache/{key}.mp3",
                        volume_level=volume_level,
                        announce=announce,
                    )
                    return

            # ── Cache MISS / uncacheable path ──
            await _play_tts(speaker=speaker, text=text, voice=voice,
                            volume_level=volume_level, voice_id=voice_id)

            # Opportunistic cache save (non-blocking, fail-silent)
            if cache_hint != "none":
                try:
                    saved = await _try_populate_cache(text, voice, key, cache_hint)
                    if saved:
                        log.debug(f"tts_queue: cached {key} (hint={cache_hint})")  # noqa: F821
                except Exception:
                    pass

            return

        log.warning("tts_queue: _play_item called with no text/voice and no media_file")  # noqa: F821
    finally:
        # ── Restore background media via duck_manager ──
        if session_id:
            with _queue_lock:
                was_preempted = _preempted
            try:
                await hass.services.async_call(  # noqa: F821
                    "pyscript", "duck_manager_restore",
                    {"session_id": session_id,
                     "wait_for_playback": not was_preempted},
                    blocking=True, return_response=True,
                )
            except Exception as exc:
                log.warning(  # noqa: F821
                    f"tts_queue: duck_manager_restore failed: {exc}"
                )

        # ── Restore original TTS speaker volume ──
        if original_volume is not None:
            if not session_id:
                # No duck session (announce-native) → wait for TTS to finish
                await asyncio.sleep(restore_delay_sec)
            try:
                service.call("media_player", "volume_set",  # noqa: F821
                             entity_id=speaker_single, volume_level=original_volume)
            except Exception as exc:
                log.warning(f"tts_queue: volume restore failed for {speaker_single}: {exc}")  # noqa: F821
            # Duck guard snapshot sync
            try:
                if state.get("input_boolean.ai_duck_guard_enabled") == "on":  # noqa: F821
                    await hass.services.async_call(  # noqa: F821
                        "pyscript", "duck_manager_update_snapshot",
                        {"entity_id": speaker_single, "volume_level": original_volume},
                        blocking=True, return_response=True,
                    )
            except Exception:
                pass


# ── Event Trigger ─────────────────────────────────────────────────────────────

@event_trigger("tts_queue_item_added")  # noqa: F821
async def _on_queue_item_added(**kwargs):
    global _processing
    with _queue_lock:
        if _processing:
            return
        _processing = True
    try:
        await _process_queue()
    except Exception as exc:
        log.error(f"tts_queue: queue processor crashed: {exc}")  # noqa: F821
        with _queue_lock:
            _processing = False
        _set_result("idle", op="queue_idle", queue_length=0)


# ── I-30: Deferred Queue Flush ────────────────────────────────────────────────

# ── Test Mode ────────────────────────────────────────────────────────────────

def _is_test_mode() -> bool:
    try:
        return str(
            state.get("input_boolean.ai_test_mode") or "off"  # noqa: F821
        ).lower() == "on"
    except NameError:
        return False


@event_trigger("tts_queue_flush_deferred")  # noqa: F821
async def _on_flush_deferred(**kwargs):
    """Move deferred items back to main queue after phone call ends."""
    await tts_queue_flush_deferred()


@service(supports_response="optional")  # noqa: F821
async def tts_queue_flush_deferred():
    """
    yaml
    name: TTS Queue Flush Deferred
    description: >-
      Move items deferred during phone calls back to the main queue
      and trigger processing.
    """
    if _is_test_mode():
        log.info("tts_queue [TEST]: would flush deferred queue")  # noqa: F821
        return

    with _queue_lock:
        count = len(_deferred_queue)
        if count == 0:
            return {"status": "ok", "op": "flush_deferred", "flushed": 0}
        _queue.extend(_deferred_queue)
        _deferred_queue.clear()
        _queue.sort(key=lambda x: (x["priority"], x["added_at"]))

    log.info(f"tts_queue: flushed {count} deferred items back to queue")  # noqa: F821
    event.fire("tts_queue_item_added")  # noqa: F821
    _set_result("queued", op="flush_deferred", flushed=count,
                queue_length=_queue_length_sync())
    return {"status": "ok", "op": "flush_deferred", "flushed": count}


# ── Service ───────────────────────────────────────────────────────────────────

# ── Blueprint / Automation Callable Pattern (Follow-Me) ──────────────────────
#
# All TTS playback should route through tts_queue_speak. Two primary modes:
#
#   1. Follow-Me (default): target_mode="presence"
#      The queue scans FP2 presence sensors by zone priority and routes audio
#      to the nearest available speaker. No target parameter needed.
#
#      Example automation YAML:
#        action: pyscript.tts_queue_speak
#        data:
#          text: "You have a meeting in 30 minutes."
#          voice: "tts.elevenlabs_quark_text_to_speech"
#          priority: 3
#          target_mode: "presence"
#
#   2. Explicit Speaker: target_mode="explicit" + target="media_player.xxx"
#      Bypass zone routing — always play on the specified speaker.
#
#      Example automation YAML:
#        action: pyscript.tts_queue_speak
#        data:
#          text: "Goodnight."
#          voice: "tts.home_assistant_cloud"
#          priority: 3
#          target_mode: "explicit"
#          target: "media_player.bathroom_sonos"
#
#   Other modes: "broadcast" (all speakers), "source_room" (trigger room).
# ─────────────────────────────────────────────────────────────────────────────

@service(supports_response="only")  # noqa: F821
async def tts_queue_speak(
    text: str = "",
    voice: str = "",
    priority: int = 3,
    cache: str = "none",
    target_mode: str = "presence",
    target: str = "",
    volume_level: float = None,
    announce: bool = True,
    duck: bool = True,
    chime_path: str = "",
    chime_duration_ms: int = 0,
    media_file: str = "",
    voice_id: str = "",
    restore_volume: bool = False,
    volume_restore_delay: int = 8,
    agent: str = "",
    metadata=None,
):
    """
    yaml
    name: TTS Queue Speak
    description: >-
      Enqueue TTS or audio for prioritized playback through the centralized
      audio pipeline. Handles presence-aware speaker targeting,
      priority preemption, and broadcast.
    fields:
      text:
        name: Text
        description: TTS message to speak.
        required: false
        selector:
          text:
      voice:
        name: Voice
        description: TTS entity (e.g., tts.elevenlabs_quark_text_to_speech).
        required: false
        selector:
          text:
      priority:
        name: Priority
        description: "0=emergency, 1=alert, 2=normal, 3=low, 4=ambient"
        default: 3
        selector:
          number:
            min: 0
            max: 4
      cache:
        name: Cache
        description: "Cache strategy (reserved): static, daily, session, none"
        default: none
        selector:
          select:
            options: [static, daily, session, none]
      target_mode:
        name: Target Mode
        description: "Speaker targeting: presence, explicit, broadcast, source_room"
        default: presence
        selector:
          select:
            options: [presence, explicit, broadcast, source_room]
      target:
        name: Target
        description: Media player entity (required for explicit/source_room).
        required: false
        selector:
          entity:
            domain: media_player
      volume_level:
        name: Volume Level
        description: Volume 0.0-1.0 (optional).
        required: false
        selector:
          number:
            min: 0
            max: 1
            step: 0.05
      announce:
        name: Announce
        description: Enable ducking/announce mode.
        default: true
        selector:
          boolean:
      duck:
        name: Duck
        description: >-
          Enable duck_manager volume ducking for background media.
          When false, duck_manager is not called — useful for callers
          that manage their own ducking (e.g. banter). Announce mode
          on the speaker is unaffected.
        default: true
        selector:
          boolean:
      chime_path:
        name: Chime Path
        description: Audio file to play before the TTS speech (e.g. agent jingle).
        required: false
        selector:
          text:
      chime_duration_ms:
        name: Chime Duration (ms)
        description: Duration of the chime in milliseconds. When provided, the queue waits this long (plus buffer) before starting TTS. 0 = use default buffer only.
        required: false
        default: 0
        selector:
          number:
            min: 0
            max: 30000
      media_file:
        name: Media File
        description: Raw audio file instead of TTS (bypasses text/voice).
        required: false
        selector:
          text:
      voice_id:
        name: Voice ID
        description: ElevenLabs voice override ID (e.g., from pipeline tts_voice). Passed as options.voice to tts.speak.
        required: false
        selector:
          text:
      restore_volume:
        name: Restore Volume
        description: Save the speaker's current volume before TTS and restore it after playback. Only applies when volume_level is set > 0.
        default: false
        selector:
          boolean:
      volume_restore_delay:
        name: Volume Restore Delay
        description: Seconds to wait after TTS before restoring volume (only used when no duck session is active).
        default: 8
        selector:
          number:
            min: 1
            max: 30
      metadata:
        name: Metadata
        description: >-
          Caller metadata dict passed through to the tts_queue_item_completed
          event after playback finishes. Enables downstream coordination
          (e.g. reactive banter waits for notification TTS to complete).
        required: false
        selector:
          object:
    """
    # Returns: {status, op, queue_length?, priority?, speaker?, preempted?, test_mode?, cache_hit?, cache_key?, error?, reason?}  # noqa: E501
    if _is_test_mode():
        log.info("tts_queue [TEST]: would enqueue TTS text=%s voice=%s", text[:50] if text else "", voice)  # noqa: F821
        return {"status": "test_mode_skip"}

    if state.get("input_boolean.ai_tts_queue_active") == "off":  # noqa: F821
        return {"status": "disabled", "op": "tts_queue_speak"}

    if not text and not media_file:
        return {"status": "error", "op": "tts_queue_speak",
                "error": "text or media_file required"}
    if text and not voice:
        return {"status": "error", "op": "tts_queue_speak",
                "error": "voice required when text is provided"}

    try:
        priority = max(0, min(4, int(priority)))
        if cache not in ("static", "daily", "session", "none"):
            cache = "none"
        if target_mode not in ("presence", "explicit", "broadcast", "source_room"):
            target_mode = "presence"

        if priority == PRIORITY_AMBIENT:
            ambient_count = _queue_count_by_priority_sync(PRIORITY_AMBIENT)
            if ambient_count >= _get_max_ambient():
                log.debug(f"tts_queue: ambient dropped ({ambient_count} in queue)")  # noqa: F821
                return {"status": "dropped", "op": "tts_queue_speak",
                        "reason": "ambient_queue_full"}

        test_mode = state.get("input_boolean.ai_test_mode") == "on"  # noqa: F821
        resolved_speaker = await _resolve_speaker(target_mode, target or None)

        # Detect announce-native speakers (Sonos/ESP) — these handle their
        # own ducking via announce mode, so playback detection uses a
        # time estimate instead of state polling.
        announce_native = False
        if announce and isinstance(resolved_speaker, str):
            try:
                # Use dot-notation for reliable attribute read —
                # state.getattr() may return 0 for supported_features
                # on some integrations (Sonos).
                feat = state.get(resolved_speaker + ".supported_features") or 0  # noqa: F821
                feat = int(feat)
                # Bit 9 (512) = SUPPORT_ANNOUNCE in HA media_player
                announce_native = bool(feat & 512)
                log.warning(  # noqa: F821
                    f"tts_queue: announce_native={announce_native} "
                    f"for {resolved_speaker} (features={feat})"
                )
            except Exception as exc:
                log.warning(  # noqa: F821
                    f"tts_queue: announce_native detection failed "
                    f"for {resolved_speaker}: {exc}"
                )
        elif announce and not isinstance(resolved_speaker, str):
            log.warning(  # noqa: F821
                f"tts_queue: announce_native skipped — "
                f"resolved_speaker is list: {resolved_speaker}"
            )

        _parsed_meta = metadata if isinstance(metadata, dict) else {}

        item = {
            "text": text or None, "voice": voice or None,
            "priority": priority, "cache": cache,
            "target_mode": target_mode, "resolved_speaker": resolved_speaker,
            "volume_level": volume_level, "announce": announce,
            "duck": duck, "announce_native": announce_native,
            "chime_path": chime_path or None,
            "chime_duration_ms": int(chime_duration_ms) if chime_duration_ms else 0,
            "media_file": media_file or None,
            "voice_id": voice_id or None, "agent": agent or "",
            "restore_volume": restore_volume, "volume_restore_delay": volume_restore_delay,
            "test_mode": test_mode, "added_at": time.time(),
            "metadata": _parsed_meta,
        }

        queue_len = _queue_add_sync(item)
        preempted = await _maybe_preempt(priority)
        event.fire("tts_queue_item_added")  # noqa: F821
        _set_result("queued", op="tts_queue_speak", queue_length=queue_len, priority=priority)

        speaker_display = resolved_speaker if isinstance(resolved_speaker, str) else resolved_speaker[0]
        result = {
            "status": "queued", "op": "tts_queue_speak",
            "queue_length": queue_len, "priority": priority,
            "speaker": speaker_display, "preempted": preempted,
            "test_mode": test_mode,
        }
        if cache != "none" and text and voice:
            key = await _cache_key(text, voice)
            hit = await _cache_check(key)
            result["cache_hit"] = hit is not None
            result["cache_key"] = key
        return result

    except Exception as exc:
        log.error("tts_queue_speak failed: %s: %s", type(exc).__name__, exc)  # noqa: F821
        _set_result("error", op="tts_queue_speak", error=str(exc))
        return {"status": "error", "op": "tts_queue_speak", "error": str(exc)}


# ── I-38: Queue Clear / Stop Services ─────────────────────────────────────────

@service(supports_response="only")  # noqa: F821
async def tts_queue_clear(target: str = ""):
    """
    yaml
    name: TTS Queue Clear
    description: >-
      Remove pending items from the queue. If target is specified, only
      remove items targeting that speaker. Returns count of removed items.
    fields:
      target:
        name: Target
        description: "Media player entity to filter (empty = clear all)"
        required: false
        selector:
          text:
    """
    if _is_test_mode():
        log.info("tts_queue [TEST]: would clear queue target=%s", target)  # noqa: F821
        return {"status": "test_mode_skip"}

    # Returns: {status, op, cleared}
    with _queue_lock:
        if not target:
            count = len(_queue)
            _queue.clear()
        else:
            before = len(_queue)
            _queue[:] = [
                item for item in _queue
                if item.get("resolved_speaker") != target
            ]
            count = before - len(_queue)

    log.info(f"tts_queue: cleared {count} items (target={target or 'all'})")  # noqa: F821
    _set_result("idle", op="queue_clear", cleared=count)
    return {"status": "ok", "op": "tts_queue_clear", "cleared": count}


@service(supports_response="only")  # noqa: F821
async def tts_queue_stop(target: str = ""):
    """
    yaml
    name: TTS Queue Stop
    description: >-
      Stop current playback and clear the queue. If target is specified,
      only stop/clear items for that speaker.
    fields:
      target:
        name: Target
        description: "Media player entity to stop (empty = stop all)"
        required: false
        selector:
          text:
    """
    if _is_test_mode():
        log.info("tts_queue [TEST]: would stop playback target=%s", target)  # noqa: F821
        return {"status": "test_mode_skip"}

    # Returns: {status, op, cleared}
    global _preempted

    # Stop current playback if it matches target
    with _queue_lock:
        cur = _current_item
    if cur:
        current_speaker = cur.get("resolved_speaker", "")
        if not target or current_speaker == target:
            with _queue_lock:
                _preempted = True
            await _stop_playback(current_speaker)

    # Clear matching items from queue
    result = await tts_queue_clear(target=target)
    log.info(f"tts_queue: stopped (target={target or 'all'})")  # noqa: F821
    return {"status": "ok", "op": "tts_queue_stop",
            "cleared": result.get("cleared", 0)}


# ── Cache Generate Service ────────────────────────────────────────────────────

@service(supports_response="only")  # noqa: F821
async def tts_cache_generate(
    text: str = "",
    voice: str = "",
    cache: str = "static",
):
    """
    yaml
    name: TTS Cache Generate
    description: >-
      Generate TTS and save to cache without playing audibly.
      Useful for pre-warming the cache with static phrases.
    fields:
      text:
        name: Text
        description: TTS message to generate and cache.
        required: true
        selector:
          text:
      voice:
        name: Voice
        description: TTS entity (e.g., tts.elevenlabs_quark_text_to_speech).
        required: true
        selector:
          text:
      cache:
        name: Cache
        description: "Cache tier: static, daily, session"
        default: static
        selector:
          select:
            options: [static, daily, session]
    """
    if _is_test_mode():
        log.info("tts_queue [TEST]: would generate TTS cache for text=%s", text[:50] if text else "")  # noqa: F821
        return {"status": "test_mode_skip"}

    if not text or not voice:
        return {"status": "error", "op": "tts_cache_generate",
                "error": "text and voice required"}
    if cache not in ("static", "daily", "session"):
        cache = "static"

    key = await _cache_key(text, voice)
    hit = await _cache_check(key)
    if hit:
        return {"status": "already_cached", "op": "tts_cache_generate", "key": key}

    # Play to default speaker at volume 0 to trigger HA's TTS generation
    default = _get_default_speaker()
    await _play_tts(speaker=default, text=text, voice=voice, volume_level=0.0)
    await asyncio.sleep(1.0)  # Give HA time to write cache file

    saved = await _try_populate_cache(text, voice, key, cache)
    return {
        "status": "cached" if saved else "generation_failed",
        "op": "tts_cache_generate", "key": key,
    }


# ── Speaker Config Rebuild Service ────────────────────────────────────────────

@service(supports_response="only")  # noqa: F821
async def tts_rebuild_speaker_config():
    """
    yaml
    name: TTS Rebuild Speaker Config
    description: >-
      Scan media_player entities for area-assigned speakers, merge with
      existing tts_speaker_config.json, and write back. Invalidates the
      speaker cache so the next TTS call picks up the new config.
      Called automatically on startup, or manually when speaker setup changes.
    """
    if _is_test_mode():
        log.info("tts_queue [TEST]: would rebuild speaker config")  # noqa: F821
        return {"status": "test_mode_skip"}

    result = await _rebuild_speaker_config()
    _set_result("ok", **result)
    return result


# ── I-33: Budget Counter Persistence ─────────────────────────────────────────

_budget_save_counter: int = 0  # track calls since last save


async def _budget_restore_from_l2() -> bool:
    """Restore budget counters from L2 memory on startup.

    Retries with exponential backoff if memory.py isn't loaded yet.
    """
    delays = [2, 4, 8]  # seconds — 3 attempts
    today = datetime.now().strftime("%Y-%m-%d")

    for attempt, delay in enumerate(delays):
        try:
            result = await hass.services.async_call(  # noqa: F821
                "pyscript", "memory_get",
                {"key": f"budget_counters:{today}"},
                blocking=True, return_response=True,
            )
            if result and result.get("value"):
                import json as _json
                counters = _json.loads(result["value"])

                # I-33 Phase 2: Extract and restore breakdown before counter loop
                breakdown = counters.pop("_breakdown", None)
                if breakdown:
                    try:
                        service.call(  # noqa: F821
                            "pyscript", "budget_breakdown_restore",
                            data=breakdown,
                        )
                    except Exception as bex:
                        log.warning(f"tts_queue: breakdown restore failed: {bex}")  # noqa: F821

                # Restore each counter
                for entity_id, val in counters.items():
                    try:
                        service.call("input_number", "set_value",  # noqa: F821
                                     entity_id=entity_id, value=float(val))
                    except Exception:
                        pass
                log.info(  # noqa: F821
                    f"tts_queue: restored budget counters from L2 "
                    f"({len(counters)} entries)"
                )
                return True
            else:
                log.info("tts_queue: no budget counters in L2 for today")  # noqa: F821
                return True  # No data is OK — fresh day
        except NameError:
            # memory.py not loaded yet
            if attempt < len(delays) - 1:
                log.info(  # noqa: F821
                    f"tts_queue: memory.py not ready, retrying in {delay}s "
                    f"(attempt {attempt + 1}/{len(delays)})"
                )
                await asyncio.sleep(delay)
            else:
                log.warning(  # noqa: F821
                    "tts_queue: budget restore failed after 3 attempts "
                    "(memory.py not loaded) — starting with zero counters"
                )
                return False
        except Exception as exc:
            log.warning(f"tts_queue: budget restore failed: {exc}")  # noqa: F821
            return False
    return False


async def _budget_save_to_l2() -> None:
    """Save current budget counters + breakdown to L2 for persistence."""
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        counters = {
            "input_number.ai_llm_calls_today": float(
                state.get("input_number.ai_llm_calls_today") or 0  # noqa: F821
            ),
            "input_number.ai_tts_calls_today": float(
                state.get("input_number.ai_tts_calls_today") or 0  # noqa: F821
            ),
            "input_number.ai_llm_tokens_today": float(
                state.get("input_number.ai_llm_tokens_today") or 0  # noqa: F821
            ),
            "input_number.ai_tts_chars_today": float(
                state.get("input_number.ai_tts_chars_today") or 0  # noqa: F821
            ),
            "input_number.ai_stt_calls_today": float(
                state.get("input_number.ai_stt_calls_today") or 0  # noqa: F821
            ),
        }
        import json as _json

        # I-33 Phase 2: Include per-agent breakdown
        breakdown_raw = state.getattr("sensor.ai_budget_breakdown") or {}  # noqa: F821
        breakdown = breakdown_raw.get("breakdown", {})
        counters["_breakdown"] = breakdown

        await hass.services.async_call(  # noqa: F821
            "pyscript", "memory_set",
            {
                "key": f"budget_counters:{today}",
                "value": _json.dumps(counters),
                "scope": "system",
                "tags": "budget,counters,daily",
            },
            blocking=True, return_response=True,
        )
    except Exception as exc:
        log.warning(f"tts_queue: budget save to L2 failed: {exc}")  # noqa: F821


# ── TTS Test Mode: Pipeline Swap (ElevenLabs ↔ HA Cloud) ─────────────────────
# When ai_tts_test_mode toggles ON, all ElevenLabs pipelines swap to HA Cloud
# via HA internal API (async_update_pipeline). Original configs backed up to
# pipeline_tts_backup.json. Toggle OFF restores originals.

_PIPELINE_BACKUP = Path("/config/pyscript/pipeline_tts_backup.json")
_HA_CLOUD_ENGINE = "tts.home_assistant_cloud"
_HA_CLOUD_VOICE = "DavisNeural"
_HA_CLOUD_LANG = "en-US"


@pyscript_executor  # noqa: F821
def _save_pipeline_backup(data):
    import json as _json
    with open("/config/pyscript/pipeline_tts_backup.json", "w") as f:
        _json.dump(data, f, indent=2)


@pyscript_executor  # noqa: F821
def _load_pipeline_backup():
    import json as _json
    try:
        with open("/config/pyscript/pipeline_tts_backup.json", "r") as f:
            return _json.load(f)
    except FileNotFoundError:
        return None


@pyscript_executor  # noqa: F821
def _delete_pipeline_backup():
    import os as _os
    try:
        _os.remove("/config/pyscript/pipeline_tts_backup.json")
    except OSError:
        pass


@state_trigger("input_boolean.ai_tts_test_mode")  # noqa: F821
async def _on_tts_test_mode_changed(**kwargs):
    new_state = kwargs.get("value", "")
    enable = new_state == "on"
    log.info(  # noqa: F821
        "tts_queue: TTS test mode %s — swapping pipelines",
        "ENABLED" if enable else "DISABLED",
    )
    try:
        from homeassistant.components.assist_pipeline.pipeline import (
            async_get_pipelines,
            async_update_pipeline,
        )

        pipelines = async_get_pipelines(hass)  # noqa: F821

        if enable:
            # Collect originals FIRST — backup must exist before any swap
            backup = {}
            to_swap = []
            for p in pipelines:
                if "elevenlabs" not in (p.tts_engine or "").lower():
                    continue
                backup[p.id] = {
                    "name": p.name,
                    "tts_engine": p.tts_engine,
                    "tts_voice": p.tts_voice or "",
                    "tts_language": p.tts_language or "",
                }
                to_swap.append(p)

            if not to_swap:
                log.info("tts_queue: no ElevenLabs pipelines to swap")  # noqa: F821
                return

            # Write backup BEFORE modifying any pipeline
            _save_pipeline_backup(backup)

            updated = []
            for p in to_swap:
                await async_update_pipeline(
                    hass,  # noqa: F821
                    p,
                    tts_engine=_HA_CLOUD_ENGINE,
                    tts_voice=_HA_CLOUD_VOICE,
                    tts_language=_HA_CLOUD_LANG,
                )
                updated.append(p.name)

            log.info(  # noqa: F821
                "tts_queue: pipelines swapped to HA Cloud: %d (%s)",
                len(updated), ", ".join(updated),
            )
        else:
            backup = _load_pipeline_backup()
            if not backup:
                log.warning("tts_queue: no backup file — nothing to restore")  # noqa: F821
                return

            pipe_map = {p.id: p for p in pipelines}
            restored = []
            for pid, cfg in backup.items():
                p = pipe_map.get(pid)
                if not p:
                    continue
                await async_update_pipeline(
                    hass,  # noqa: F821
                    p,
                    tts_engine=cfg["tts_engine"],
                    tts_voice=cfg["tts_voice"],
                    tts_language=cfg.get("tts_language", "en"),
                )
                restored.append(cfg["name"])

            _delete_pipeline_backup()
            log.info(  # noqa: F821
                "tts_queue: pipelines restored to ElevenLabs: %d (%s)",
                len(restored), ", ".join(restored),
            )
    except Exception as e:
        log.error("tts_queue: pipeline swap error: %s", e)  # noqa: F821


# ── Startup ───────────────────────────────────────────────────────────────────

@time_trigger("startup")  # noqa: F821
async def tts_queue_startup():
    _ensure_result_entity_name(force=True)
    # Load TTS entity remap (deferred from module level to avoid blocking event loop)
    global _TTS_ENTITY_REMAP, _PROFILE_TO_AGENT, _VOICE_UUID_TO_PROFILE
    try:
        _TTS_ENTITY_REMAP, _PROFILE_TO_AGENT, _VOICE_UUID_TO_PROFILE = await _build_tts_remap()
        if _TTS_ENTITY_REMAP:
            log.info(  # noqa: F821
                f"tts_queue: dynamic remap loaded — {len(_TTS_ENTITY_REMAP)} entities: "
                f"{list(_TTS_ENTITY_REMAP.keys())}"
            )
    except Exception as e:
        log.warning(f"tts_queue: remap init failed ({e}) — old entities pass through unchanged")  # noqa: F821
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        log.error(f"tts_queue: failed to create cache dir: {e}")  # noqa: F821

    # Rebuild speaker config from registry + existing file
    await _rebuild_speaker_config()

    # I-33: Restore budget counters from L2 (with retry backoff)
    await _budget_restore_from_l2()

    _set_result("idle", op="startup", cache_dir=str(CACHE_DIR))

    # TTS Test Mode: auto-restore pipelines if backup exists but toggle is OFF
    # Handles crash/restart during an active test session.
    try:
        test_on = state.get("input_boolean.ai_tts_test_mode") == "on"  # noqa: F821
        backup = _load_pipeline_backup()
        if backup and not test_on:
            log.info(  # noqa: F821
                "tts_queue: orphaned TTS test backup found — auto-restoring %d pipelines",
                len(backup),
            )
            from homeassistant.components.assist_pipeline.pipeline import (
                async_get_pipelines as _agp,
                async_update_pipeline as _aup,
            )
            pipe_map = {p.id: p for p in _agp(hass)}  # noqa: F821
            restored = []
            for pid, cfg in backup.items():
                p = pipe_map.get(pid)
                if not p:
                    continue
                await _aup(
                    hass, p,  # noqa: F821
                    tts_engine=cfg["tts_engine"],
                    tts_voice=cfg["tts_voice"],
                    tts_language=cfg.get("tts_language", "en"),
                )
                restored.append(cfg["name"])
            _delete_pipeline_backup()
            log.info(  # noqa: F821
                "tts_queue: auto-restored %d pipelines to ElevenLabs (%s)",
                len(restored), ", ".join(restored),
            )
        elif backup and test_on:
            log.info(  # noqa: F821
                "tts_queue: TTS test mode still ON after restart — "
                "backup retained (%d pipelines), toggle OFF to restore",
                len(backup),
            )
    except Exception as e:
        log.error("tts_queue: TTS test mode startup check failed: %s", e)  # noqa: F821

    log.info("tts_queue.py loaded — queue idle")  # noqa: F821


# ── I-33: Periodic Budget Save (every 30 min) ───────────────────────────────

@time_trigger("cron(*/30 * * * *)")  # noqa: F821
async def _budget_periodic_save():
    """Save budget counters to L2 every 30 minutes."""
    await _budget_save_to_l2()


# ── Daily Housekeeping ────────────────────────────────────────────────────────

@time_trigger("cron(0 0 * * *)")  # noqa: F821
async def tts_queue_daily_housekeeping():
    try:
        # Read cache eviction helpers with safe defaults
        try:
            static_days = int(float(state.get("input_number.ai_tts_cache_static_max_days") or 90))  # noqa: F821
        except (ValueError, TypeError):
            static_days = 90
        try:
            max_mb = int(float(state.get("input_number.ai_tts_cache_max_size_mb") or 500))  # noqa: F821
        except (ValueError, TypeError):
            max_mb = 500
        try:
            protect_hrs = float(state.get("input_number.ai_tts_cache_protect_hours") or 1.0)  # noqa: F821
        except (ValueError, TypeError):
            protect_hrs = 1.0
        d = await _cache_cleanup_daily()
        e = await _cache_cleanup_expired(static_max_age_days=static_days)
        s = await _cache_evict_by_size(max_size_mb=max_mb, protect_age_hours=protect_hrs)
        h = await _ha_tts_cleanup(max_age_days=static_days, protect_age_hours=protect_hrs)
        log.info(f"tts_queue housekeeping: daily={d}, expired={e}, size_evicted={s}, ha_tts={h}")  # noqa: F821
    except Exception as ex:
        log.error(f"tts_queue housekeeping cache cleanup failed: {ex}")  # noqa: F821
    try:
        service.call("input_number", "set_value",  # noqa: F821
                     entity_id="input_number.ai_tts_cache_hits_today", value=0)
        service.call("input_number", "set_value",  # noqa: F821
                     entity_id="input_number.ai_tts_calls_today", value=0)
    except Exception as ex:
        log.error(f"tts_queue housekeeping counter reset failed: {ex}")  # noqa: F821
