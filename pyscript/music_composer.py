"""I-10: Agent Music Composition — Option C Hybrid (ElevenLabs + FluidSynth).

Each voice agent has a musical identity. Two generation paths:
  - ElevenLabs Music API (/v1/music/compose) + SFX API (/v1/sound-generation)
    → production-quality, 10-60s latency, credits per generation
  - FluidSynth local MIDI → MP3 rendering
    → MIDI quality, 0.5-2s, free (RPi5 CPU)

Services exposed:
  pyscript.music_compose         — ElevenLabs generation (Music or SFX API)
  pyscript.music_compose_local   — FluidSynth local MIDI → MP3
  pyscript.music_compose_batch   — Batch-generate all static compositions
  pyscript.music_compose_status  — Cache inventory + stats
  pyscript.music_compose_approve — Move staging → production
  pyscript.music_compose_get     — Resolve agent + content_type → cached file path
  pyscript.music_soundfont_list  — SoundFont catalogue with metadata
  pyscript.music_library_list    — Browse cached compositions with filters
  pyscript.music_library_play    — Play a cached composition on a speaker
  pyscript.music_library_delete  — Delete a composition from the library
  pyscript.music_library_action  — Single router for LLM tool (list/play/delete/list_soundfonts)
"""

import asyncio
import hashlib
import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

import aiohttp
import yaml

from shared_utils import build_result_entity_name

# ── Constants ────────────────────────────────────────────────────────────────

RESULT_ENTITY = "sensor.ai_music_composer_status"
CACHE_STATS_ENTITY = "sensor.ai_music_cache_stats"
BUDGET_ENTITY = "sensor.ai_music_generation_budget"
KILL_SWITCH = "input_boolean.ai_music_composer_enabled"

CACHE_DIR = Path("/config/www/music_cache")
STAGING_DIR = CACHE_DIR / "staging"
PRODUCTION_DIR = CACHE_DIR / "production"
SOUNDFONT_DIR = Path("/config/soundfonts")
DEFAULT_SOUNDFONT = "FluidR3_GM2-2.SF2"
SECRETS_PATH = Path("/config/secrets.yaml")

SOUNDFONT_CATALOGUE_PATH = Path("/config/soundfonts/soundfont_catalogue.yaml")
SOUNDFONT_CATALOGUE_ENTITY = "sensor.ai_music_soundfont_catalogue"

ELEVENLABS_MUSIC_URL = "https://api.elevenlabs.io/v1/music/compose"
ELEVENLABS_SFX_URL = "https://api.elevenlabs.io/v1/sound-generation"
ELEVENLABS_MUSIC_MODEL = "music_v1"

_API_TIMEOUT = aiohttp.ClientTimeout(total=120)  # music generation can take 60s+
_API_RETRIES = 3

# ── Module State ─────────────────────────────────────────────────────────────

result_entity_name: dict[str, str] = {}
_api_key_cache: str | None = None
_fluidsynth_available: bool | None = None  # lazy-checked on first local call
_soundfont_catalogue: list[dict] = []


# ── Agent Musical Identity ───────────────────────────────────────────────────

_AGENT_MUSIC_IDENTITY: dict[str, dict[str, Any]] = {
    "rick": {
        "style": "Chaotic sci-fi synth, dissonant",
        "instruments": "Distorted synth, theremin, electric guitar",
        "tempo_range": (130, 160),
        "mood": "Manic, unpredictable",
        "elevenlabs_keywords": "distorted synth, theremin, electric guitar, manic, sci-fi, chaotic, dissonant",
        "midi_profile": {
            "instruments": [81, 32, 27],  # Lead Synth, Acoustic Bass, Electric Guitar
            "key": "C",
            "scale": "chromatic",
            "velocity_range": (90, 127),
        },
    },
    "quark": {
        "style": "Smooth lounge jazz, Ferengi bar ambiance",
        "instruments": "Saxophone, upright bass, piano",
        "tempo_range": (80, 110),
        "mood": "Suave, calculating",
        "elevenlabs_keywords": "smooth jazz, saxophone, upright bass, piano, lounge, suave, sophisticated",
        "midi_profile": {
            "instruments": [66, 33, 1],  # Alto Sax, Acoustic Bass, Grand Piano
            "key": "Bb",
            "scale": "mixolydian",
            "velocity_range": (60, 100),
        },
    },
    "deadpool": {
        "style": "Inappropriately upbeat pop, 4th-wall-breaking",
        "instruments": "Pop synths, chiptune, ironic orchestral",
        "tempo_range": (120, 140),
        "mood": "Chaotic good",
        "elevenlabs_keywords": "upbeat pop, chiptune, synth pop, ironic, playful, orchestral stab, 8-bit",
        "midi_profile": {
            "instruments": [81, 13, 49],  # Lead Synth, Marimba, String Ensemble
            "key": "C",
            "scale": "major",
            "velocity_range": (80, 120),
        },
    },
    "kramer": {
        "style": "Eccentric improv, unexpected genre shifts",
        "instruments": "Slap bass, bongos, random brass",
        "tempo_range": (90, 160),
        "mood": "Unpredictable, physical",
        "elevenlabs_keywords": "slap bass, bongos, brass section, eccentric, improv, unpredictable, funk",
        "midi_profile": {
            "instruments": [37, 117, 62],  # Slap Bass, Melodic Tom, Brass Section
            "key": "E",
            "scale": "blues",
            "velocity_range": (70, 127),
        },
    },
    "portuondo": {
        "style": "Cuban bolero, Buena Vista Social Club warmth",
        "instruments": "Piano, trumpet, upright bass, congas",
        "tempo_range": (70, 100),
        "mood": "Warm, nostalgic, soulful",
        "elevenlabs_keywords": "cuban bolero, piano, trumpet, upright bass, congas, warm, nostalgic, latin, soulful",
        "midi_profile": {
            "instruments": [1, 57, 33],  # Grand Piano, Trumpet, Acoustic Bass
            "key": "F",
            "scale": "dorian",
            "velocity_range": (50, 90),
        },
    },
}

# ── Content-Type Defaults ────────────────────────────────────────────────────

_CONTENT_DEFAULTS: dict[str, dict[str, Any]] = {
    "theme": {
        "duration_ms": 5000,
        "api": "music",
        "cache_hint": "static",
        "description": "agent theme jingle, audio identity",
    },
    "chime": {
        "duration_ms": 3000,
        "api": "sfx",
        "cache_hint": "static",
        "description": "notification chime sound",
    },
    "thinking": {
        "duration_ms": 10000,
        "api": "music",
        "cache_hint": "static",
        "description": "thinking/deliberation loop",
    },
    "stinger": {
        "duration_ms": 3000,
        "api": "sfx",
        "cache_hint": "static",
        "description": "transition stinger between agents",
    },
    "handoff": {
        "duration_ms": 2000,
        "api": "sfx",
        "cache_hint": "static",
        "description": "short handoff chime when user requests agent switch",
    },
    "expertise": {
        "duration_ms": 2000,
        "api": "sfx",
        "cache_hint": "static",
        "description": "soft advisory chime for expertise-based agent routing",
    },
    "wake_melody": {
        "duration_ms": 45000,
        "api": "music",
        "cache_hint": "daily",
        "description": "personalized alarm tone",
    },
    "bedtime": {
        "duration_ms": 180000,
        "api": "music",
        "cache_hint": "session",
        "description": "ambient bedtime wind-down piece",
    },
    "ambient": {
        "duration_ms": 300000,
        "api": "local",
        "cache_hint": "none",
        "description": "mood-reactive background ambient",
    },
    "variation": {
        "duration_ms": 5000,
        "api": "local",
        "cache_hint": "session",
        "description": "local variation on a base composition",
    },
}

# ── Scale Definitions (for MIDI generation) ──────────────────────────────────

_SCALES: dict[str, list[int]] = {
    "chromatic": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11],
    "major": [0, 2, 4, 5, 7, 9, 11],
    "minor": [0, 2, 3, 5, 7, 8, 10],
    "mixolydian": [0, 2, 4, 5, 7, 9, 10],
    "dorian": [0, 2, 3, 5, 7, 9, 10],
    "blues": [0, 3, 5, 6, 7, 10],
    "pentatonic": [0, 2, 4, 7, 9],
}

_KEY_OFFSETS: dict[str, int] = {
    "C": 0, "C#": 1, "Db": 1, "D": 2, "Eb": 3, "E": 4, "F": 5,
    "F#": 6, "Gb": 6, "G": 7, "Ab": 8, "A": 9, "Bb": 10, "B": 11,
}


# ── Result Entity Helpers ────────────────────────────────────────────────────

def _ensure_result_entity_name(force: bool = False) -> None:
    global result_entity_name
    if force or not result_entity_name:
        result_entity_name = build_result_entity_name(RESULT_ENTITY)


def _set_result(state_value: str = "ok", **attrs: Any) -> None:
    _ensure_result_entity_name()
    attrs.update(result_entity_name)
    state.set(RESULT_ENTITY, value=state_value, new_attributes=attrs)  # noqa: F821


# ── Utility Helpers ──────────────────────────────────────────────────────────

def _is_enabled() -> bool:
    try:
        val = state.get(KILL_SWITCH)  # noqa: F821
    except Exception:
        return False
    return val == "on"


@pyscript_executor  # noqa: F821
def _get_api_key_sync(secrets_path: str) -> str:
    """Read ElevenLabs API key from secrets.yaml. Runs in executor thread."""
    import yaml as _yaml
    try:
        from pathlib import Path as _Path
        raw = _Path(secrets_path).read_text(encoding="utf-8")
        secrets = _yaml.safe_load(raw) or {}
        return secrets.get("elevenlabs_api_key", "")
    except Exception:
        return ""


async def _get_api_key() -> str:
    """Read ElevenLabs API key from secrets.yaml (cached after first read)."""
    global _api_key_cache
    if _api_key_cache:
        return _api_key_cache
    _api_key_cache = _get_api_key_sync(str(SECRETS_PATH))
    if not _api_key_cache:
        _api_key_cache = ""
    return _api_key_cache


def _cache_key(agent: str, content_type: str, seed: int,
               target_agent: str = "") -> str:
    """Build deterministic cache key."""
    seed_hex = f"{seed:08x}" if seed else "random"
    if content_type == "stinger" and target_agent:
        return f"{agent}_{target_agent}_stinger_{seed_hex}"
    return f"{agent}_{content_type}_{seed_hex}"


@pyscript_executor  # noqa: F821
def _ensure_dirs_sync(staging: str, production: str) -> None:
    """Create cache directories if they don't exist. Runs in executor thread."""
    from pathlib import Path as _Path
    _Path(staging).mkdir(parents=True, exist_ok=True)
    _Path(production).mkdir(parents=True, exist_ok=True)


def _ensure_dirs() -> None:
    """Create cache directories if they don't exist (sync fallback for startup)."""
    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    PRODUCTION_DIR.mkdir(parents=True, exist_ok=True)


def _get_generations_today() -> int:
    try:
        return int(float(state.get("input_number.ai_music_generations_today") or 0))  # noqa: F821
    except Exception:
        return 0


def _get_daily_limit() -> int:
    try:
        return int(float(state.get("input_number.ai_music_daily_generation_limit") or 10))  # noqa: F821
    except Exception:
        return 10


def _increment_generations() -> None:
    """Increment the daily API generation counter."""
    current = _get_generations_today()
    try:
        service.call(  # noqa: F821
            "input_number", "set_value",
            entity_id="input_number.ai_music_generations_today",
            value=current + 1,
        )
    except Exception:
        pass


def _budget_gate() -> dict | None:
    """Check budget gates. Returns None if OK, or error dict if blocked."""
    if not _is_enabled():
        return {"status": "disabled", "error": "kill switch off"}

    today = _get_generations_today()
    limit = _get_daily_limit()
    if limit > 0 and today >= limit:
        return {"status": "budget_exceeded", "error": f"daily limit reached ({today}/{limit})"}

    return None


def _build_prompt(agent: str, content_type: str, prompt_override: str = "",
                  target_agent: str = "") -> str:
    """Build ElevenLabs prompt from agent identity + content type."""
    if prompt_override:
        return prompt_override

    identity = _AGENT_MUSIC_IDENTITY.get(agent, {})
    defaults = _CONTENT_DEFAULTS.get(content_type, {})
    keywords = identity.get("elevenlabs_keywords", "")
    mood = identity.get("mood", "")
    tempo_lo, tempo_hi = identity.get("tempo_range", (120, 120))
    tempo = (tempo_lo + tempo_hi) // 2
    desc = defaults.get("description", content_type)

    if content_type == "stinger" and target_agent:
        target_id = _AGENT_MUSIC_IDENTITY.get(target_agent, {})
        target_kw = target_id.get("elevenlabs_keywords", "")
        return (
            f"A 2-3 second transition stinger from {agent} to {target_agent}. "
            f"Start with {keywords}, quickly morph into {target_kw}. "
            f"Short, punchy, {mood}."
        )

    duration_s = defaults.get("duration_ms", 5000) / 1000

    prompts = {
        "theme": (
            f"A {duration_s:.0f}-second instrumental {desc}. "
            f"Style: {keywords}. Mood: {mood}. "
            f"Tempo: {tempo} BPM. Catchy, memorable, suitable as a character introduction."
        ),
        "chime": (
            f"A short notification chime sound effect. "
            f"Style: {keywords}. Mood: {mood}. Clear and recognizable."
        ),
        "thinking": (
            f"A {duration_s:.0f}-second loopable instrumental thinking music. "
            f"Style: {keywords}. Mood: contemplative, {mood}. "
            f"Tempo: {tempo} BPM. Seamlessly loopable."
        ),
        "wake_melody": (
            f"A {duration_s:.0f}-second gentle instrumental wake-up melody. "
            f"Style: {keywords}. Start soft and gradually build. "
            f"Tempo: {tempo - 20} BPM. Warm and inviting."
        ),
        "bedtime": (
            f"A {duration_s / 60:.0f}-minute ambient instrumental wind-down piece. "
            f"Style: {keywords}. Mood: peaceful, sleepy, {mood}. "
            f"Tempo: {max(tempo - 40, 60)} BPM. Gradually fade quieter."
        ),
        "handoff": (
            f"A short 2-second handoff chime sound effect. "
            f"Style: {keywords}. Mood: {mood}. "
            f"Clear, attention-getting, signals a switch or transition."
        ),
        "expertise": (
            f"A soft 2-second advisory chime sound effect. "
            f"Style: {keywords}. Mood: gentle, informative. "
            f"Subtle, non-intrusive, signals a helpful suggestion or redirect."
        ),
    }
    return prompts.get(content_type, (
        f"A {duration_s:.0f}-second instrumental piece. "
        f"Style: {keywords}. Mood: {mood}. Tempo: {tempo} BPM."
    ))


# ── ElevenLabs API Functions ─────────────────────────────────────────────────

async def _generate_music_api(
    prompt: str, duration_ms: int, seed: int = 0,
    force_instrumental: bool = True,
) -> bytes | None:
    """Call ElevenLabs Music Compose API. Returns audio bytes or None."""
    api_key = await _get_api_key()
    if not api_key:
        log.error("music_composer: ElevenLabs API key not found in secrets.yaml")  # noqa: F821
        return None

    payload: dict[str, Any] = {
        "prompt": prompt,
        "music_length_ms": max(duration_ms, 3000),
        "force_instrumental": force_instrumental,
        "model_id": ELEVENLABS_MUSIC_MODEL,
        "output_format": "mp3_44100_128",
    }
    if seed > 0:
        payload["seed"] = seed

    headers = {"xi-api-key": api_key}

    for attempt in range(_API_RETRIES):
        try:
            async with aiohttp.ClientSession(timeout=_API_TIMEOUT) as session:
                async with session.post(
                    ELEVENLABS_MUSIC_URL, json=payload, headers=headers,
                ) as resp:
                    if resp.status == 200:
                        return await resp.read()
                    body = await resp.text()
                    log.warning(  # noqa: F821
                        "music_composer: ElevenLabs Music API %d on attempt %d: %s",
                        resp.status, attempt + 1, body[:200],
                    )
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            log.warning(  # noqa: F821
                "music_composer: ElevenLabs Music API error attempt %d: %s",
                attempt + 1, exc,
            )
        if attempt < _API_RETRIES - 1:
            await asyncio.sleep(2 ** attempt)

    return None


async def _generate_sfx_api(prompt: str, duration_s: float = 2.0) -> bytes | None:
    """Call ElevenLabs Sound Generation API. Returns audio bytes or None."""
    api_key = await _get_api_key()
    if not api_key:
        log.error("music_composer: ElevenLabs API key not found in secrets.yaml")  # noqa: F821
        return None

    payload = {
        "text": prompt,
        "duration_seconds": max(duration_s, 0.5),
        "prompt_influence": 0.5,
    }
    headers = {"xi-api-key": api_key}

    for attempt in range(_API_RETRIES):
        try:
            async with aiohttp.ClientSession(timeout=_API_TIMEOUT) as session:
                async with session.post(
                    ELEVENLABS_SFX_URL, json=payload, headers=headers,
                ) as resp:
                    if resp.status == 200:
                        return await resp.read()
                    body = await resp.text()
                    log.warning(  # noqa: F821
                        "music_composer: ElevenLabs SFX API %d on attempt %d: %s",
                        resp.status, attempt + 1, body[:200],
                    )
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            log.warning(  # noqa: F821
                "music_composer: ElevenLabs SFX API error attempt %d: %s",
                attempt + 1, exc,
            )
        if attempt < _API_RETRIES - 1:
            await asyncio.sleep(2 ** attempt)

    return None


# ── FluidSynth / MIDI Functions ──────────────────────────────────────────────

@pyscript_executor  # noqa: F821
def _check_fluidsynth_sync() -> bool:
    """Check if FluidSynth binary + midiutil are available. BLOCKING — run in executor."""
    import subprocess
    try:
        import midiutil  # noqa: F401
        result = subprocess.run(["fluidsynth", "--version"], capture_output=True, timeout=5)
        from pathlib import Path
        sf_dir = Path("/config/soundfonts")
        sf_path = sf_dir / "FluidR3_GM2-2.SF2"
        return sf_path.exists() and result.returncode == 0
    except (ImportError, FileNotFoundError, subprocess.TimeoutExpired):
        return False


async def _check_fluidsynth() -> bool:
    """Async wrapper — runs blocking check in executor thread."""
    global _fluidsynth_available
    if _fluidsynth_available is not None:
        return _fluidsynth_available
    _fluidsynth_available = _check_fluidsynth_sync()
    return _fluidsynth_available


@pyscript_executor  # noqa: F821
def _build_midi_bytes(
    agent: str, content_type: str, duration_s: float,
    tempo_shift: float = 1.0, pitch_shift: int = 0,
    instrument_override: int = -1,
) -> bytes | None:
    """Build a MIDI file in memory from agent profile + content patterns.

    Runs in executor thread (blocking). Returns MIDI bytes.
    """
    try:
        from midiutil import MIDIFile
    except ImportError:
        return None

    identity = _AGENT_MUSIC_IDENTITY.get(agent)
    if not identity:
        return None

    profile = identity["midi_profile"]
    key_name = profile.get("key", "C")
    scale_name = profile.get("scale", "major")
    vel_lo, vel_hi = profile.get("velocity_range", (60, 100))
    instruments = profile["instruments"]
    tempo_lo, tempo_hi = identity.get("tempo_range", (120, 120))
    base_tempo = int((tempo_lo + tempo_hi) / 2 * tempo_shift)

    scale = _SCALES.get(scale_name, _SCALES["major"])
    root = _KEY_OFFSETS.get(key_name, 0) + pitch_shift

    # Use first instrument or override
    instrument = instrument_override if instrument_override >= 0 else instruments[0]

    midi = MIDIFile(1)
    track = 0
    channel = 0
    midi.addTempo(track, 0, base_tempo)
    midi.addProgramChange(track, channel, 0, instrument)

    import random
    # Seed from agent+content for reproducibility
    rng = random.Random(hashlib.md5(f"{agent}:{content_type}".encode()).hexdigest())

    beats = max(1, int(duration_s * base_tempo / 60))

    if content_type in ("chime", "stinger", "handoff", "expertise"):
        # Short, punchy: 3-5 notes with gaps
        num_notes = rng.randint(3, 5)
        note_dur = duration_s / num_notes * 0.7
        for i in range(num_notes):
            degree = rng.choice(scale)
            if content_type == "handoff":
                octave = 5
                vel = rng.randint(max(vel_lo, 90), vel_hi)  # higher velocity — urgent
            elif content_type == "expertise":
                octave = 5
                vel = rng.randint(vel_lo, min(vel_hi, 80))  # lower velocity — gentle advisory
            elif content_type == "chime":
                octave = 5
                vel = rng.randint(vel_lo, vel_hi)
            else:
                octave = 4
                vel = rng.randint(vel_lo, vel_hi)
            pitch = root + degree + 12 * octave
            pitch = max(21, min(108, pitch))
            t = i * (duration_s / num_notes)
            midi.addNote(track, channel, pitch, t, note_dur, vel)

    elif content_type == "theme":
        # Melodic motif: ascending then resolving
        num_notes = rng.randint(5, 8)
        note_dur = duration_s / num_notes * 0.8
        prev_degree_idx = 0
        for i in range(num_notes):
            if i < num_notes // 2:
                prev_degree_idx = min(prev_degree_idx + rng.randint(0, 2), len(scale) - 1)
            else:
                prev_degree_idx = max(prev_degree_idx - rng.randint(0, 2), 0)
            pitch = root + scale[prev_degree_idx] + 60
            pitch = max(21, min(108, pitch))
            vel = rng.randint(vel_lo, vel_hi)
            midi.addNote(track, channel, pitch, i * note_dur, note_dur, vel)

    elif content_type == "thinking":
        # Repeating arpeggio loop
        pattern_len = min(4, len(scale))
        pattern = [scale[i % len(scale)] for i in range(pattern_len)]
        note_dur = 60 / base_tempo * 0.8
        t = 0.0
        while t < duration_s:
            for deg in pattern:
                if t >= duration_s:
                    break
                pitch = root + deg + 60
                pitch = max(21, min(108, pitch))
                vel = rng.randint(vel_lo, vel_hi)
                midi.addNote(track, channel, pitch, t, note_dur, vel)
                t += 60 / base_tempo

    elif content_type in ("wake_melody", "bedtime", "ambient", "variation"):
        # Slow, evolving: chord tones with gentle movement
        note_dur = max(1.0, 60 / base_tempo * 2)
        t = 0.0
        degree_idx = 0
        while t < duration_s:
            pitch = root + scale[degree_idx % len(scale)] + 60
            pitch = max(21, min(108, pitch))
            # Bedtime/ambient: softer velocity, decreasing over time
            if content_type in ("bedtime", "ambient"):
                fade = max(0.3, 1.0 - t / duration_s * 0.5)
                vel = int(vel_lo + (vel_hi - vel_lo) * fade * rng.uniform(0.7, 1.0))
            else:
                vel = rng.randint(vel_lo, vel_hi)
            midi.addNote(track, channel, pitch, t, note_dur, vel)
            # Add a chord tone occasionally
            if rng.random() > 0.5 and len(scale) > 2:
                chord_deg = (degree_idx + 2) % len(scale)
                chord_pitch = root + scale[chord_deg] + 60
                chord_pitch = max(21, min(108, chord_pitch))
                midi.addNote(track, channel, chord_pitch, t, note_dur, int(vel * 0.7))
            degree_idx += rng.choice([-1, 0, 1, 1])
            degree_idx = max(0, min(len(scale) - 1, degree_idx))
            t += note_dur * rng.uniform(0.8, 1.2)
    else:
        # Fallback: simple scale run
        note_dur = duration_s / len(scale)
        for i, deg in enumerate(scale):
            pitch = root + deg + 60
            pitch = max(21, min(108, pitch))
            vel = rng.randint(vel_lo, vel_hi)
            midi.addNote(track, channel, pitch, i * note_dur, note_dur, vel)

    import io
    buf = io.BytesIO()
    midi.writeFile(buf)
    return buf.getvalue()


@pyscript_executor  # noqa: F821
def _render_midi_to_wav(midi_bytes: bytes, soundfont_path: str, output_path: str) -> bool:
    """Render MIDI bytes to WAV via FluidSynth subprocess. Runs in executor thread.

    Uses fluidsynth CLI directly — midi2audio is incompatible with FluidSynth 2.5+.
    """
    import subprocess

    midi_fd, midi_path = tempfile.mkstemp(suffix=".mid")
    try:
        with os.fdopen(midi_fd, "wb") as f:
            f.write(midi_bytes)
        cmd = [
            "fluidsynth", "-ni", "-q",
            "-F", output_path,
            "-r", "44100",
            soundfont_path,
            midi_path,
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=60)
        return Path(output_path).exists() and result.returncode == 0
    except Exception:
        return False
    finally:
        try:
            os.unlink(midi_path)
        except OSError:
            pass


# ── Cache Functions ──────────────────────────────────────────────────────────


@pyscript_executor  # noqa: F821
def _write_cache_sync(
    audio_bytes: bytes, key: str, target_dir_str: str,
    metadata_json: str, staging_str: str, production_str: str,
) -> str:
    """Write audio + metadata to cache. Runs in executor thread. Returns file path."""
    from pathlib import Path as _Path
    import json as _json
    _Path(staging_str).mkdir(parents=True, exist_ok=True)
    _Path(production_str).mkdir(parents=True, exist_ok=True)
    target_dir = _Path(target_dir_str)
    audio_path = target_dir / f"{key}.mp3"
    meta_path = target_dir / f"{key}.json"
    audio_path.write_bytes(audio_bytes)
    meta_path.write_text(_json.dumps(_json.loads(metadata_json), indent=2))
    return str(audio_path)


@pyscript_executor  # noqa: F821
def _write_meta_sync(meta_path_str: str, json_str: str) -> None:
    """Write a JSON metadata file. Runs in executor thread."""
    from pathlib import Path as _Path
    _Path(meta_path_str).write_text(json_str)


@pyscript_executor  # noqa: F821
def _read_meta_sync(meta_path_str: str) -> str:
    """Read a JSON metadata file. Runs in executor thread. Returns JSON string or empty."""
    from pathlib import Path as _Path
    p = _Path(meta_path_str)
    if p.exists():
        return p.read_text()
    return ""


@pyscript_executor  # noqa: F821
def _approve_move_sync(
    staging_str: str, production_str: str,
    approve_mode: str, agent_filter: str, content_type_filter: str,
) -> tuple:
    """Move approved compositions from staging to production. Runs in executor thread.

    Returns (moved_count, skipped_count).
    """
    from pathlib import Path as _Path
    import json as _json
    import shutil as _shutil

    staging = _Path(staging_str)
    production = _Path(production_str)
    moved = 0
    skipped = 0

    for mp3 in list(staging.glob("*.mp3")):
        meta_path = mp3.with_suffix(".json")
        meta = {}
        if meta_path.exists():
            try:
                meta = _json.loads(meta_path.read_text())
            except (ValueError, OSError):
                pass

        if approve_mode == "by_agent" and agent_filter:
            if meta.get("agent", "") != agent_filter:
                skipped += 1
                continue
        elif approve_mode == "by_content_type" and content_type_filter:
            if meta.get("content_type", "") != content_type_filter:
                skipped += 1
                continue

        dest_mp3 = production / mp3.name
        dest_meta = production / meta_path.name
        _shutil.move(str(mp3), str(dest_mp3))
        if meta_path.exists():
            meta["approved"] = True
            dest_meta.write_text(_json.dumps(meta, indent=2))
            meta_path.unlink(missing_ok=True)
        moved += 1

    return (moved, skipped)


@pyscript_executor  # noqa: F821
def _scan_library_sync(
    production_str: str, staging_str: str,
    agent: str, content_type: str, source: str,
    search: str, limit: int,
) -> list:
    """Scan library for compositions with optional filters. Runs in executor thread."""
    from pathlib import Path as _Path
    import json as _json
    from datetime import datetime, timezone

    production = _Path(production_str)
    production.mkdir(parents=True, exist_ok=True)
    results = []
    search_lower = search.lower() if search else ""

    for audio_file in sorted(
        list(production.glob("*.mp3")) + list(production.glob("*.wav")),
        key=lambda p: -p.stat().st_mtime,
    ):
        meta_path = audio_file.with_suffix(".json")
        meta = {}
        if meta_path.exists():
            try:
                meta = _json.loads(meta_path.read_text())
            except (ValueError, OSError):
                pass

        m_agent = meta.get("agent", "unknown")
        m_type = meta.get("content_type", "unknown")
        m_source = meta.get("source", "unknown")
        m_prompt = meta.get("prompt", "")

        if agent and m_agent != agent:
            continue
        if content_type and m_type != content_type:
            continue
        if source and m_source != source:
            continue
        if search_lower:
            haystack = f"{m_agent} {m_type} {m_source} {m_prompt}".lower()
            if search_lower not in haystack:
                continue

        created_ts = meta.get("created", audio_file.stat().st_mtime)
        try:
            created_iso = datetime.fromtimestamp(created_ts, tz=timezone.utc).isoformat()
        except Exception:
            created_iso = str(created_ts)

        results.append({
            "library_id": audio_file.stem,
            "agent": m_agent,
            "content_type": m_type,
            "source": m_source,
            "duration_ms": meta.get("duration_ms", 0),
            "created": created_iso,
            "file_path": str(audio_file),
            "prompt": (m_prompt[:120] + "...") if len(m_prompt) > 120 else m_prompt,
            "size_mb": round(audio_file.stat().st_size / (1024 * 1024), 2),
        })
        if len(results) >= limit:
            break

    return results


async def _write_cache(
    audio_bytes: bytes, key: str, target_dir: Path,
    metadata: dict,
) -> str:
    """Write audio + metadata to cache. Returns file path."""
    return _write_cache_sync(
        audio_bytes, key, str(target_dir),
        json.dumps(metadata), str(STAGING_DIR), str(PRODUCTION_DIR),
    )


@pyscript_executor  # noqa: F821
def _count_files_sync(dir_str: str) -> int:
    """Count .mp3 files in a directory. Runs in executor thread."""
    from pathlib import Path as _Path
    d = _Path(dir_str)
    if d.exists():
        return len(list(d.glob("*.mp3")))
    return 0


@pyscript_executor  # noqa: F821
def _library_delete_sync(file_path_str: str) -> None:
    """Delete audio file + JSON sidecar. Runs in executor thread."""
    from pathlib import Path as _Path
    p = _Path(file_path_str)
    p.unlink(missing_ok=True)
    p.with_suffix(".json").unlink(missing_ok=True)


@pyscript_executor  # noqa: F821
def _library_promote_sync(
    key: str, staging_str: str, production_str: str,
) -> dict:
    """Move a composition from staging to production. Runs in executor thread.

    Returns dict with status/action/library_id.
    """
    from pathlib import Path as _Path
    import json as _json
    import shutil as _shutil

    staging = _Path(staging_str)
    production = _Path(production_str)

    # Check production first — already saved
    for ext in (".mp3", ".wav"):
        prod = production / f"{key}{ext}"
        if prod.exists():
            return {"status": "ok", "action": "already_saved", "library_id": key}

    # Check staging — move to production
    for ext in (".mp3", ".wav"):
        stage = staging / f"{key}{ext}"
        if stage.exists():
            dest = production / stage.name
            _shutil.move(str(stage), str(dest))
            meta_src = stage.with_suffix(".json")
            if meta_src.exists():
                meta = {}
                try:
                    meta = _json.loads(meta_src.read_text())
                except (ValueError, OSError):
                    pass
                meta["approved"] = True
                dest_meta = production / meta_src.name
                dest_meta.write_text(_json.dumps(meta, indent=2))
                meta_src.unlink(missing_ok=True)
            return {"status": "ok", "action": "promoted", "library_id": key}

    return {"status": "error", "error": f"composition '{key}' not found in staging or production"}


@pyscript_executor  # noqa: F821
def _prefix_scan_sync(prefix: str, production_str: str, staging_str: str) -> dict:
    """Find first file matching prefix in production then staging. Runs in executor thread."""
    from pathlib import Path as _Path
    import json as _json

    for dir_str, status in ((production_str, "ok"), (staging_str, "staging")):
        d = _Path(dir_str)
        d.mkdir(parents=True, exist_ok=True)
        matches = sorted(
            list(d.glob(f"{prefix}*.mp3")) + list(d.glob(f"{prefix}*.wav")),
            key=lambda p: -p.stat().st_mtime,
        )
        if matches:
            f = matches[0]
            dur = 0
            meta_path = f.with_suffix(".json")
            if meta_path.exists():
                try:
                    meta = _json.loads(meta_path.read_text())
                    dur = int(meta.get("duration_ms", 0))
                except (ValueError, OSError, TypeError):
                    pass
            return {"status": status, "file_path": str(f), "cache_key": f.stem,
                    "duration_ms": dur}

    return {"status": "not_found", "file_path": "", "cache_key": "", "duration_ms": 0}


@pyscript_executor  # noqa: F821
def _find_in_cache_sync(key: str, production_str: str, staging_str: str) -> str:
    """Look up a cache key in production then staging. Runs in executor thread."""
    from pathlib import Path as _Path
    for ext in (".mp3", ".wav"):
        prod = _Path(production_str) / f"{key}{ext}"
        if prod.exists():
            return str(prod)
    for ext in (".mp3", ".wav"):
        stage = _Path(staging_str) / f"{key}{ext}"
        if stage.exists():
            return str(stage)
    return ""


async def _find_in_cache(key: str) -> str | None:
    """Look up a cache key in production (preferred) then staging. Checks .mp3 and .wav."""
    result = _find_in_cache_sync(key, str(PRODUCTION_DIR), str(STAGING_DIR))
    return result if result else None


@pyscript_executor  # noqa: F821
def _read_sidecar_duration_sync(file_path: str) -> int:
    """Read duration_ms from JSON sidecar. Runs in executor thread."""
    from pathlib import Path as _Path
    import json as _json
    try:
        meta_path = _Path(file_path).with_suffix(".json")
        if meta_path.exists():
            meta = _json.loads(meta_path.read_text())
            return int(meta.get("duration_ms", 0))
    except (ValueError, OSError, TypeError):
        pass
    return 0


async def _read_sidecar_duration(file_path: str) -> int:
    """Read duration_ms from JSON sidecar. Returns 0 on failure."""
    return _read_sidecar_duration_sync(file_path)


@pyscript_executor  # noqa: F821
def _cache_inventory_sync(staging_str: str, production_str: str) -> dict:
    """Build cache inventory stats. Runs in executor thread."""
    from pathlib import Path as _Path
    import json as _json
    staging = _Path(staging_str)
    production = _Path(production_str)
    staging.mkdir(parents=True, exist_ok=True)
    production.mkdir(parents=True, exist_ok=True)
    stats = {"total_files": 0, "total_size_mb": 0.0, "by_agent": {}, "by_source": {}}
    for d in (staging, production):
        for mp3 in list(d.glob("*.mp3")) + list(d.glob("*.wav")):
            stats["total_files"] += 1
            stats["total_size_mb"] += mp3.stat().st_size / (1024 * 1024)
            meta_path = mp3.with_suffix(".json")
            if meta_path.exists():
                try:
                    meta = _json.loads(meta_path.read_text())
                    agent = meta.get("agent", "unknown")
                    source = meta.get("source", "unknown")
                    stats["by_agent"][agent] = stats["by_agent"].get(agent, 0) + 1
                    stats["by_source"][source] = stats["by_source"].get(source, 0) + 1
                except (_json.JSONDecodeError, OSError):
                    pass
    stats["total_size_mb"] = round(stats["total_size_mb"], 2)
    return stats


async def _cache_inventory() -> dict:
    """Build cache inventory stats."""
    return _cache_inventory_sync(str(STAGING_DIR), str(PRODUCTION_DIR))


@pyscript_executor  # noqa: F821
def _evict_cache_sync(production_str: str, max_mb: float) -> int:
    """LRU eviction if cache exceeds size limit. Runs in executor thread."""
    from pathlib import Path as _Path
    import time as _time

    production = _Path(production_str)
    all_files = sorted(
        list(production.glob("*.mp3")) + list(production.glob("*.wav")),
        key=lambda p: p.stat().st_mtime,
    )
    total = sum([f.stat().st_size for f in all_files]) / (1024 * 1024)
    removed = 0
    protect_age = 3600  # protect files < 1 hour old

    while total > max_mb and all_files:
        oldest = all_files.pop(0)
        if _time.time() - oldest.stat().st_mtime < protect_age:
            continue
        size_mb = oldest.stat().st_size / (1024 * 1024)
        oldest.unlink(missing_ok=True)
        oldest.with_suffix(".json").unlink(missing_ok=True)
        total -= size_mb
        removed += 1

    return removed


async def _evict_cache() -> int:
    """LRU eviction if cache exceeds size limit. Returns files removed."""
    try:
        max_mb = float(state.get("input_number.ai_music_cache_size_mb") or 200)  # noqa: F821
    except (TypeError, ValueError):
        max_mb = 200
    return _evict_cache_sync(str(PRODUCTION_DIR), max_mb)


# ── Sensor Update ────────────────────────────────────────────────────────────

async def _update_cache_sensor() -> None:
    """Push cache stats to sensor."""
    stats = await _cache_inventory()
    state.set(  # noqa: F821
        CACHE_STATS_ENTITY,
        value=str(stats["total_files"]),
        new_attributes={
            "friendly_name": "AI Music Cache Stats",
            "total_files": stats["total_files"],
            "total_size_mb": stats["total_size_mb"],
            "by_agent": stats["by_agent"],
            "by_source": stats["by_source"],
        },
    )


def _update_budget_sensor() -> None:
    """Push generation budget to sensor."""
    today = _get_generations_today()
    limit = _get_daily_limit()
    remaining = max(0, limit - today)
    state.set(  # noqa: F821
        BUDGET_ENTITY,
        value=str(remaining),
        new_attributes={
            "friendly_name": "AI Music Generation Budget",
            "used_today": today,
            "daily_limit": limit,
            "remaining": remaining,
        },
    )


# ── SoundFont Catalogue (Phase 1) ────────────────────────────────────────────

@pyscript_executor  # noqa: F821
def _scan_soundfonts_sync(
    soundfont_dir: str, catalogue_path: str,
) -> tuple:
    """Scan soundfonts and catalogue. Runs in executor thread.

    Returns (catalogue_list, error_msg_or_none).
    """
    from pathlib import Path as _Path
    import yaml as _yaml

    sf_dir = _Path(soundfont_dir)
    cat_path = _Path(catalogue_path)

    # Load optional metadata overlay
    overlay = {}
    error_msg = None
    if cat_path.exists():
        try:
            raw = cat_path.read_text(encoding="utf-8")
            entries = _yaml.safe_load(raw) or []
            for entry in entries:
                fname = entry.get("filename", "")
                if fname:
                    overlay[fname] = entry
        except Exception as exc:
            error_msg = str(exc)

    catalogue = []
    if sf_dir.exists():
        for sf in sorted(sf_dir.glob("*.sf2")):
            size_mb = round(sf.stat().st_size / (1024 * 1024), 1)
            meta = overlay.get(sf.name, {})
            if "tier" not in meta:
                if size_mb < 10:
                    auto_tier = "quick"
                elif size_mb < 100:
                    auto_tier = "standard"
                else:
                    auto_tier = "premium"
            else:
                auto_tier = meta["tier"]

            catalogue.append({
                "filename": sf.name,
                "name": meta.get("name", sf.stem),
                "tier": auto_tier,
                "size_mb": size_mb,
                "character": meta.get("character", ""),
                "best_for": meta.get("best_for", ""),
                "default_agents": meta.get("default_agents", []),
            })

    return (catalogue, error_msg)


async def _scan_soundfonts() -> list[dict]:
    """Scan /config/soundfonts/*.sf2, merge with catalogue YAML overlay."""
    global _soundfont_catalogue
    catalogue, error_msg = _scan_soundfonts_sync(
        str(SOUNDFONT_DIR), str(SOUNDFONT_CATALOGUE_PATH),
    )
    if error_msg:
        log.warning("music_composer: failed to load soundfont catalogue: %s", error_msg)  # noqa: F821
    _soundfont_catalogue = catalogue
    return catalogue


async def _update_soundfont_sensor() -> None:
    """Push SoundFont catalogue to sensor entity."""
    cat = _soundfont_catalogue or await _scan_soundfonts()
    tier_counts = {}
    total_size = 0.0
    for entry in cat:
        tier_counts[entry["tier"]] = tier_counts.get(entry["tier"], 0) + 1
        total_size += entry["size_mb"]
    state.set(  # noqa: F821
        SOUNDFONT_CATALOGUE_ENTITY,
        value=str(len(cat)),
        new_attributes={
            "friendly_name": "AI Music SoundFont Catalogue",
            "catalogue": cat,
            "tier_counts": tier_counts,
            "total_size_mb": round(total_size, 1),
        },
    )


# ── Music Taste Integration (Phase 3) ───────────────────────────────────────

def _enrich_prompt_with_taste(prompt: str) -> str:
    """Append music taste data to prompt if available."""
    try:
        taste_status = state.get("sensor.ai_music_taste_status")  # noqa: F821
        if not taste_status or taste_status in ("unknown", "unavailable"):
            return prompt
        attrs = state.getattr("sensor.ai_music_taste_status") or {}  # noqa: F821
        summary = attrs.get("summary", "")
        top_artists = attrs.get("top_artists", [])
        if not summary and not top_artists:
            return prompt
        taste_parts = []
        if summary:
            taste_parts.append(f"The listener enjoys: {summary}.")
        if top_artists:
            artists_str = ", ".join([str(a) for a in top_artists[:5]])
            taste_parts.append(f"Top artists: {artists_str}.")
        return prompt + " " + " ".join(taste_parts)
    except Exception:
        return prompt


# ── Library Management (Phase 2) ────────────────────────────────────────────

async def _scan_library(
    agent: str = "", content_type: str = "", source: str = "",
    search: str = "", limit: int = 50,
) -> list[dict]:
    """Scan production dir for compositions with optional filters."""
    return _scan_library_sync(
        str(PRODUCTION_DIR), str(STAGING_DIR),
        agent, content_type, source, search, limit,
    )


# ── Services ─────────────────────────────────────────────────────────────────

@service(supports_response="only")  # noqa: F821
async def music_compose(
    agent: str = "rick",
    content_type: str = "theme",
    prompt_override: str = "",
    duration_ms: int = 0,
    seed: int = 0,
    target_agent: str = "",
    force_instrumental: bool = True,
    use_sfx_api: bool = False,
    staging: bool = True,
    reference_taste: bool = False,
) -> dict:
    """
    yaml
    name: Music Compose
    description: >-
      Generate a composition via ElevenLabs Music or SFX API.
    fields:
      agent:
        name: Agent
        description: Agent persona (rick/quark/deadpool/kramer/portuondo).
        required: true
        selector:
          select:
            options: [rick, quark, deadpool, kramer, portuondo]
      content_type:
        name: Content Type
        description: Type of composition.
        required: true
        selector:
          select:
            options: [theme, chime, thinking, stinger, handoff, expertise, wake_melody, bedtime, ambient]
      prompt_override:
        name: Prompt Override
        description: Custom prompt (overrides identity table).
        required: false
        selector:
          text:
            multiline: true
      duration_ms:
        name: Duration (ms)
        description: Override duration (0 = use default for content type).
        required: false
        default: 0
        selector:
          number:
            min: 0
            max: 600000
      seed:
        name: Seed
        description: Reproducibility seed (0 = random).
        required: false
        default: 0
        selector:
          number:
            min: 0
            max: 2147483647
      target_agent:
        name: Target Agent
        description: For stingers — the target persona.
        required: false
        selector:
          text: {}
      force_instrumental:
        name: Force Instrumental
        description: Ensure no vocals.
        required: false
        default: true
        selector:
          boolean: {}
      use_sfx_api:
        name: Use SFX API
        description: Use Sound Effects API instead of Music API.
        required: false
        default: false
        selector:
          boolean: {}
      staging:
        name: Staging
        description: Write to staging (true) or production (false).
        required: false
        default: true
        selector:
          boolean: {}
      reference_taste:
        name: Reference Taste
        description: Enrich prompt with user's music taste profile.
        required: false
        default: false
        selector:
          boolean: {}
    """
    gate = _budget_gate()
    if gate:
        return gate

    if agent not in _AGENT_MUSIC_IDENTITY:
        return {"status": "error", "error": f"unknown agent: {agent}"}

    defaults = _CONTENT_DEFAULTS.get(content_type, _CONTENT_DEFAULTS["theme"])
    actual_duration = duration_ms if duration_ms > 0 else defaults["duration_ms"]

    # Determine API to use
    api = "sfx" if use_sfx_api else defaults.get("api", "music")
    if api == "local":
        api = "music"  # local-primary types can still be forced to API

    key = _cache_key(agent, content_type, seed, target_agent)

    # Check cache first
    cached = await _find_in_cache(key)
    if cached:
        return {"status": "cached", "file_path": cached, "cache_key": key}

    prompt = _build_prompt(agent, content_type, prompt_override, target_agent)
    if reference_taste:
        prompt = _enrich_prompt_with_taste(prompt)
    start = time.time()

    if api == "sfx":
        audio = await _generate_sfx_api(prompt, actual_duration / 1000)
    else:
        audio = await _generate_music_api(
            prompt, actual_duration, seed, force_instrumental,
        )

    gen_time = round(time.time() - start, 1)

    if not audio:
        _set_result("error", last_error=f"API returned no audio for {agent}/{content_type}")
        return {"status": "error", "error": "API returned no audio", "generation_time_s": gen_time}

    target_dir = STAGING_DIR if staging else PRODUCTION_DIR
    metadata = {
        "agent": agent,
        "content_type": content_type,
        "seed": seed,
        "duration_ms": actual_duration,
        "prompt": prompt[:500],
        "created": time.time(),
        "approved": not staging,
        "api_used": api,
        "source": "elevenlabs",
        "generation_time_s": gen_time,
    }
    if target_agent:
        metadata["target_agent"] = target_agent

    file_path = await _write_cache(audio, key, target_dir, metadata)

    # Track budget
    _increment_generations()
    try:
        pyscript.budget_track_call(  # noqa: F821
            service_type="music", agent=agent, calls=1,
        )
    except Exception:
        pass

    await _evict_cache()
    await _update_cache_sensor()
    _update_budget_sensor()
    _set_result("ok", last_generation=f"{agent}/{content_type}", generation_time_s=gen_time)

    return {
        "status": "ok",
        "file_path": file_path,
        "cache_key": key,
        "duration_ms": actual_duration,
        "seed_used": seed,
        "generation_time_s": gen_time,
        "api_used": api,
        "source": "elevenlabs",
    }


@service(supports_response="only")  # noqa: F821
async def music_compose_local(
    agent: str = "rick",
    content_type: str = "variation",
    base_key: str = "",
    tempo_shift: float = 1.0,
    pitch_shift: int = 0,
    instrument_override: int = -1,
    duration_s: float = 5.0,
    soundfont: str = "",
    prompt_hint: str = "",
) -> dict:
    """
    yaml
    name: Music Compose Local
    description: >-
      Generate a composition locally via FluidSynth MIDI rendering.
    fields:
      agent:
        name: Agent
        description: Agent persona.
        required: true
        selector:
          select:
            options: [rick, quark, deadpool, kramer, portuondo]
      content_type:
        name: Content Type
        description: Type of composition.
        required: true
        selector:
          select:
            options: [theme, chime, thinking, stinger, handoff, expertise, wake_melody, bedtime, ambient, variation]
      base_key:
        name: Base Key
        description: Cache key of base composition to derive from.
        required: false
        selector:
          text: {}
      tempo_shift:
        name: Tempo Shift
        description: Tempo multiplier (0.5–2.0).
        required: false
        default: 1.0
        selector:
          number:
            min: 0.5
            max: 2.0
            step: 0.1
      pitch_shift:
        name: Pitch Shift
        description: Semitones (-12 to +12).
        required: false
        default: 0
        selector:
          number:
            min: -12
            max: 12
      instrument_override:
        name: Instrument Override
        description: GM instrument number (-1 = use identity default).
        required: false
        default: -1
        selector:
          number:
            min: -1
            max: 127
      duration_s:
        name: Duration (seconds)
        description: Output duration.
        required: false
        default: 5.0
        selector:
          number:
            min: 0.5
            max: 600
            step: 0.5
      soundfont:
        name: SoundFont
        description: SoundFont filename (in /config/soundfonts/).
        required: false
        selector:
          text: {}
      prompt_hint:
        name: Prompt Hint
        description: >-
          User's creative prompt (for documentation only — FluidSynth
          renders from the agent's musical identity, not the prompt).
        required: false
        selector:
          text:
            multiline: true
    """
    if not _is_enabled():
        return {"status": "disabled", "error": "kill switch off"}

    if agent not in _AGENT_MUSIC_IDENTITY:
        return {"status": "error", "error": f"unknown agent: {agent}"}

    if not await _check_fluidsynth():
        return {"status": "error", "error": "FluidSynth not available (install midiutil + midi2audio + fluidsynth)"}

    sf_name = soundfont or DEFAULT_SOUNDFONT
    sf_path = str(SOUNDFONT_DIR / sf_name)
    if not Path(sf_path).exists():
        return {"status": "error", "error": f"SoundFont not found: {sf_path}"}

    # Build a unique key for this local generation
    key_data = f"{agent}:{content_type}:{tempo_shift}:{pitch_shift}:{instrument_override}:{duration_s}"
    seed = int(hashlib.md5(key_data.encode()).hexdigest()[:8], 16)
    key = _cache_key(agent, content_type, seed)

    # Check cache
    cached = await _find_in_cache(key)
    if cached:
        return {"status": "cached", "file_path": cached, "cache_key": key}

    start = time.time()

    # Build MIDI in executor thread
    midi_bytes = _build_midi_bytes(
        agent, content_type, duration_s,
        tempo_shift, pitch_shift, instrument_override,
    )
    if not midi_bytes:
        return {"status": "error", "error": "MIDI generation failed"}

    # Render to WAV in executor thread (fluidsynth CLI, not midi2audio)
    _ensure_dirs_sync(str(STAGING_DIR), str(PRODUCTION_DIR))
    output_path = str(PRODUCTION_DIR / f"{key}.wav")
    success = _render_midi_to_wav(midi_bytes, sf_path, output_path)
    if not success:
        return {"status": "error", "error": "FluidSynth rendering failed"}

    render_time = round((time.time() - start) * 1000)

    metadata = {
        "agent": agent,
        "content_type": content_type,
        "seed": seed,
        "duration_ms": int(duration_s * 1000),
        "tempo_shift": tempo_shift,
        "pitch_shift": pitch_shift,
        "instrument_override": instrument_override,
        "created": time.time(),
        "approved": True,
        "source": "fluidsynth",
        "render_time_ms": render_time,
        "prompt_hint": prompt_hint,
    }
    _write_meta_sync(str(PRODUCTION_DIR / f"{key}.json"), json.dumps(metadata, indent=2))

    # Track calls (no cost for local)
    try:
        pyscript.budget_track_call(  # noqa: F821
            service_type="music", agent=agent, calls=1,
        )
    except Exception:
        pass

    await _update_cache_sensor()
    _set_result("ok", last_generation=f"{agent}/{content_type} (local)", render_time_ms=render_time)

    result = {
        "status": "ok",
        "file_path": output_path,
        "cache_key": key,
        "duration_ms": int(duration_s * 1000),
        "render_time_ms": render_time,
        "source": "fluidsynth",
        "source_note": "FluidSynth renders from the agent's musical identity, not the prompt.",
    }
    if prompt_hint:
        result["prompt_hint"] = prompt_hint
    return result


@service(supports_response="optional")  # noqa: F821
async def music_compose_batch(
    agents: list = None,
    content_types: list = None,
    auto_approve: bool = False,
) -> dict:
    """
    yaml
    name: Music Compose Batch
    description: >-
      Batch-generate all static compositions for specified agents.
    fields:
      agents:
        name: Agents
        description: List of agents (empty = all).
        required: false
        selector:
          object: {}
      content_types:
        name: Content Types
        description: List of types (empty = all static types).
        required: false
        selector:
          object: {}
      auto_approve:
        name: Auto Approve
        description: Skip staging, write directly to production.
        required: false
        default: false
        selector:
          boolean: {}
    """
    gate = _budget_gate()
    if gate:
        return gate

    target_agents = agents or list(_AGENT_MUSIC_IDENTITY.keys())
    static_types = ["theme", "chime", "thinking"]
    target_types = content_types or static_types

    results = {"generated": 0, "cached": 0, "errors": 0, "details": []}

    # Generate per-agent compositions
    for ag in target_agents:
        for ct in target_types:
            if ct == "stinger":
                continue  # stingers handled separately below
            result = await music_compose(
                agent=ag, content_type=ct, staging=not auto_approve,
            )
            status = result.get("status", "error")
            results["details"].append({"agent": ag, "type": ct, "status": status})
            if status == "ok":
                results["generated"] += 1
            elif status == "cached":
                results["cached"] += 1
            else:
                results["errors"] += 1

    # Generate stingers (if requested)
    if "stinger" in target_types:
        for source in target_agents:
            for target in target_agents:
                if source == target:
                    continue
                result = await music_compose(
                    agent=source, content_type="stinger",
                    target_agent=target, staging=not auto_approve,
                )
                status = result.get("status", "error")
                results["details"].append(
                    {"agent": f"{source}→{target}", "type": "stinger", "status": status},
                )
                if status == "ok":
                    results["generated"] += 1
                elif status == "cached":
                    results["cached"] += 1
                else:
                    results["errors"] += 1

    # Send persistent notification
    try:
        service.call(  # noqa: F821
            "persistent_notification", "create",
            title="Music Composition Batch Complete",
            message=(
                f"Generated: {results['generated']}, "
                f"Cached: {results['cached']}, "
                f"Errors: {results['errors']}"
            ),
            notification_id="music_compose_batch",
        )
    except Exception:
        pass

    _set_result(
        "batch_complete",
        generated=results["generated"],
        cached=results["cached"],
        errors=results["errors"],
    )
    return results


@service(supports_response="optional")  # noqa: F821
async def music_compose_status() -> dict:
    """
    yaml
    name: Music Compose Status
    description: Return cache inventory and generation stats.
    """
    stats = await _cache_inventory()
    budget = {
        "used_today": _get_generations_today(),
        "daily_limit": _get_daily_limit(),
        "remaining": max(0, _get_daily_limit() - _get_generations_today()),
    }
    fluidsynth = await _check_fluidsynth()

    stats = await _cache_inventory()
    staging_count = 0
    production_count = 0
    try:
        staging_count = _count_files_sync(str(STAGING_DIR))
        production_count = _count_files_sync(str(PRODUCTION_DIR))
    except Exception:
        pass

    result = {
        "status": "ok",
        "cache": stats,
        "budget": budget,
        "fluidsynth_available": fluidsynth,
        "staging_count": staging_count,
        "production_count": production_count,
        "enabled": _is_enabled(),
    }

    await _update_cache_sensor()
    _update_budget_sensor()
    return result


@service(supports_response="optional")  # noqa: F821
async def music_compose_approve(
    approve_mode: str = "all",
    agent_filter: str = "",
    content_type_filter: str = "",
) -> dict:
    """
    yaml
    name: Music Compose Approve
    description: >-
      Move compositions from staging to production.
    fields:
      approve_mode:
        name: Approve Mode
        description: "all / by_agent / by_content_type / single"
        required: false
        default: all
        selector:
          select:
            options: [all, by_agent, by_content_type]
      agent_filter:
        name: Agent Filter
        description: Filter to specific agent (for by_agent mode).
        required: false
        selector:
          text: {}
      content_type_filter:
        name: Content Type Filter
        description: Filter to specific type (for by_content_type mode).
        required: false
        selector:
          text: {}
    """
    _ensure_dirs_sync(str(STAGING_DIR), str(PRODUCTION_DIR))
    moved, skipped = _approve_move_sync(
        str(STAGING_DIR), str(PRODUCTION_DIR),
        approve_mode, agent_filter, content_type_filter,
    )

    await _update_cache_sensor()
    return {"status": "ok", "moved": moved, "skipped": skipped}


@service(supports_response="only")  # noqa: F821
async def music_compose_get(
    agent: str = "rick",
    content_type: str = "theme",
    target_agent: str = "",
    seed: int = 0,
    library_id: str = "",
) -> dict:
    """
    yaml
    name: Music Compose Get
    description: >-
      Resolve agent + content_type to a cached file path (production first).
    fields:
      agent:
        name: Agent
        description: Agent persona.
        required: true
        selector:
          select:
            options: [rick, quark, deadpool, kramer, portuondo]
      content_type:
        name: Content Type
        description: Type of composition.
        required: true
        selector:
          select:
            options: [theme, chime, thinking, stinger, handoff, expertise, wake_melody, bedtime, ambient, variation]
      target_agent:
        name: Target Agent
        description: For stingers — the target persona.
        required: false
        selector:
          text: {}
      seed:
        name: Seed
        description: Specific seed to look up (0 = any matching file).
        required: false
        default: 0
        selector:
          number:
            min: 0
            max: 2147483647
      library_id:
        name: Library ID
        description: Direct cache key lookup (bypasses agent/content_type resolution).
        required: false
        selector:
          text: {}
    """
    # Direct library_id lookup (bypasses agent/content_type)
    if library_id:
        found = await _find_in_cache(library_id)
        if found:
            dur = await _read_sidecar_duration(found)
            return {"status": "ok", "file_path": found, "cache_key": library_id,
                    "duration_ms": dur}
        return {"status": "not_found", "file_path": "", "cache_key": library_id,
                "duration_ms": 0}

    # If seed specified, look for exact key
    if seed > 0:
        key = _cache_key(agent, content_type, seed, target_agent)
        found = await _find_in_cache(key)
        if found:
            dur = await _read_sidecar_duration(found)
            return {"status": "ok", "file_path": found, "cache_key": key,
                    "duration_ms": dur}
        return {"status": "not_found", "file_path": "", "cache_key": key,
                "duration_ms": 0}

    # Otherwise, find any matching file in production/staging via executor
    prefix = f"{agent}_{content_type}_"
    if content_type == "stinger" and target_agent:
        prefix = f"{agent}_{target_agent}_stinger_"
    result = _prefix_scan_sync(prefix, str(PRODUCTION_DIR), str(STAGING_DIR))
    return result


# ── SoundFont Catalogue Service (Phase 1) ────────────────────────────────────

@service(supports_response="only")  # noqa: F821
async def music_soundfont_list() -> dict:
    """
    yaml
    name: Music SoundFont List
    description: >-
      Return the SoundFont catalogue with metadata for each installed font.
    """
    cat = _soundfont_catalogue or await _scan_soundfonts()
    return {"status": "ok", "soundfonts": cat, "count": len(cat)}


# ── Library Services (Phase 2) ──────────────────────────────────────────────

@service(supports_response="only")  # noqa: F821
async def music_library_list(
    agent: str = "", content_type: str = "", source: str = "",
    search: str = "", limit: int = 50,
) -> dict:
    """
    yaml
    name: Music Library List
    description: >-
      Browse cached compositions with optional filters.
    fields:
      agent:
        name: Agent
        description: Filter by agent name.
        required: false
        selector:
          text: {}
      content_type:
        name: Content Type
        description: Filter by content type.
        required: false
        selector:
          text: {}
      source:
        name: Source
        description: Filter by source (elevenlabs/fluidsynth).
        required: false
        selector:
          text: {}
      search:
        name: Search
        description: Substring search against prompt/agent/type.
        required: false
        selector:
          text: {}
      limit:
        name: Limit
        description: Max results to return.
        required: false
        default: 50
        selector:
          number:
            min: 1
            max: 200
    """
    items = await _scan_library(agent=agent, content_type=content_type,
                                source=source, search=search, limit=limit)
    return {"status": "ok", "compositions": items, "count": len(items)}


@service(supports_response="only")  # noqa: F821
async def music_library_play(
    library_id: str = "", search: str = "",
    player: str = "", volume: float = 0,
) -> dict:
    """
    yaml
    name: Music Library Play
    description: >-
      Play a cached composition by library_id or search string.
    fields:
      library_id:
        name: Library ID
        description: Exact file stem to play.
        required: false
        selector:
          text: {}
      search:
        name: Search
        description: Substring search — plays first match.
        required: false
        selector:
          text: {}
      player:
        name: Player
        description: Media player entity to play on.
        required: true
        selector:
          entity:
            domain: media_player
      volume:
        name: Volume
        description: "Volume level (0.0–1.0). 0 = keep current."
        required: false
        default: 0
        selector:
          number:
            min: 0.0
            max: 1.0
            step: 0.05
    """
    if not player:
        return {"status": "error", "error": "player is required"}

    # Resolve file
    target_file = None
    if library_id:
        found = await _find_in_cache(library_id)
        if found:
            target_file = Path(found)
    if not target_file and search:
        items = await _scan_library(search=search, limit=1)
        if items:
            target_file = Path(items[0]["file_path"])

    if not target_file:
        return {"status": "not_found", "error": "no matching composition found"}

    # Load metadata sidecar for enriched return
    file_meta = {}
    meta_json = _read_meta_sync(str(target_file.with_suffix(".json")))
    if meta_json:
        try:
            file_meta = json.loads(meta_json)
        except (json.JSONDecodeError, OSError):
            pass

    # Set volume if requested (>0 = set explicitly, ≤0 = keep current)
    saved_volume = None
    if volume > 0:
        try:
            saved_volume = float(
                state.getattr(player).get("volume_level", 0)  # noqa: F821
            )
        except Exception:
            pass
        try:
            service.call(  # noqa: F821
                "media_player", "volume_set",
                entity_id=player, volume_level=volume,
            )
        except Exception:
            pass

    # Play via media_player.play_media with local URL
    # /config/www/music_cache/production/X.mp3 → /local/music_cache/production/X.mp3
    media_url = f"/local/music_cache/production/{target_file.name}"
    try:
        service.call(  # noqa: F821
            "media_player", "play_media",
            entity_id=player,
            media_content_id=media_url,
            media_content_type="music",
            announce=True,
        )
    except Exception as exc:
        return {"status": "error", "error": f"playback failed: {exc}"}

    # Restore volume if we changed it
    if saved_volume is not None:
        try:
            await asyncio.sleep(0.5)
            service.call(  # noqa: F821
                "media_player", "volume_set",
                entity_id=player, volume_level=saved_volume,
            )
        except Exception:
            pass

    m_prompt = file_meta.get("prompt", "")
    return {
        "status": "ok",
        "played": target_file.stem,
        "player": player,
        "file_path": str(target_file),
        "agent": file_meta.get("agent", "unknown"),
        "content_type": file_meta.get("content_type", "unknown"),
        "duration_ms": file_meta.get("duration_ms", 0),
        "source": file_meta.get("source", "unknown"),
        "prompt": (m_prompt[:120] + "...") if len(m_prompt) > 120 else m_prompt,
    }


@service(supports_response="only")  # noqa: F821
async def music_library_delete(
    library_id: str = "", search: str = "",
) -> dict:
    """
    yaml
    name: Music Library Delete
    description: >-
      Delete a composition (audio + JSON sidecar) from the library.
    fields:
      library_id:
        name: Library ID
        description: Exact file stem to delete.
        required: false
        selector:
          text: {}
      search:
        name: Search
        description: Substring search — deletes first match.
        required: false
        selector:
          text: {}
    """
    target_file = None
    if library_id:
        found = await _find_in_cache(library_id)
        if found:
            target_file = Path(found)
    if not target_file and search:
        items = await _scan_library(search=search, limit=1)
        if items:
            target_file = Path(items[0]["file_path"])

    if not target_file:
        return {"status": "not_found", "error": "no matching composition found"}

    deleted_id = target_file.stem
    _library_delete_sync(str(target_file))
    await _update_cache_sensor()

    return {"status": "ok", "deleted": deleted_id}


async def _music_library_promote(library_id: str = "", search: str = "") -> dict:
    """Promote (keep/save) a composition — move staging → production.

    If already in production, returns success (idempotent).
    Accepts library_id (cache_key / file stem) or search string.
    """
    _ensure_dirs_sync(str(STAGING_DIR), str(PRODUCTION_DIR))
    key = (library_id or "").strip()

    # Resolve via search if no direct ID
    if not key and search:
        result = await music_library_list(search=search, limit=1)
        items = result.get("items", [])
        if items:
            key = items[0].get("id", "")

    if not key:
        return {"status": "error", "error": "no library_id or search provided"}

    result = _library_promote_sync(key, str(STAGING_DIR), str(PRODUCTION_DIR))
    if result.get("action") == "promoted":
        await _update_cache_sensor()
        log.info(f"music_library: promote — moved {key} to production")  # noqa: F821
    elif result.get("action") == "already_saved":
        log.info(f"music_library: promote — {key} already in production")  # noqa: F821
    return result


@service(supports_response="only")  # noqa: F821
async def music_library_action(
    action: str = "list", agent: str = "", content_type: str = "",
    source: str = "", search: str = "", library_id: str = "",
    player: str = "", volume: float = -1, limit: int = 20,
) -> dict:
    """
    yaml
    name: Music Library Action
    description: >-
      Single router for LLM music library tool. Actions: list, play, delete, list_soundfonts.
    fields:
      action:
        name: Action
        description: "list / play / delete / list_soundfonts"
        required: true
        selector:
          select:
            options: [list, play, delete, list_soundfonts]
      agent:
        name: Agent
        description: Filter by agent (for list).
        required: false
        selector:
          text: {}
      content_type:
        name: Content Type
        description: Filter by type (for list).
        required: false
        selector:
          text: {}
      source:
        name: Source
        description: Filter by source (for list).
        required: false
        selector:
          text: {}
      search:
        name: Search
        description: Search string.
        required: false
        selector:
          text: {}
      library_id:
        name: Library ID
        description: Exact file stem (for play/delete).
        required: false
        selector:
          text: {}
      player:
        name: Player
        description: Media player entity (for play).
        required: false
        selector:
          entity:
            domain: media_player
      volume:
        name: Volume
        description: Volume (for play). -1 = keep current.
        required: false
        default: -1
        selector:
          number:
            min: -1
            max: 1.0
            step: 0.05
      limit:
        name: Limit
        description: Max results (for list).
        required: false
        default: 20
        selector:
          number:
            min: 1
            max: 200
    """
    if action == "list":
        return await music_library_list(
            agent=agent, content_type=content_type,
            source=source, search=search, limit=limit,
        )
    elif action == "play":
        return await music_library_play(
            library_id=library_id, search=search,
            player=player, volume=volume,
        )
    elif action == "delete":
        return await music_library_delete(
            library_id=library_id, search=search,
        )
    elif action == "promote":
        return await _music_library_promote(library_id=library_id, search=search)
    elif action == "list_soundfonts":
        return await music_soundfont_list()
    else:
        return {"status": "error", "error": f"unknown action: {action}"}


# ── Startup ──────────────────────────────────────────────────────────────────

@time_trigger("startup")  # noqa: F821
async def _music_composer_startup():
    """Initialize cache directories, sensors, and SoundFont catalogue on startup."""
    _ensure_dirs_sync(str(STAGING_DIR), str(PRODUCTION_DIR))
    _ensure_result_entity_name(force=True)
    _set_result("idle", message="Music composer ready")
    await _update_cache_sensor()
    _update_budget_sensor()
    await _scan_soundfonts()
    await _update_soundfont_sensor()
    fs_ok = await _check_fluidsynth()
    log.info(  # noqa: F821
        "music_composer: startup complete, fluidsynth=%s, soundfonts=%d",
        fs_ok, len(_soundfont_catalogue),
    )
