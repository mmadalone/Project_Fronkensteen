"""I-34: Music Taste Extraction from Music Assistant / Spotify.

Logs what gets played (MA state triggers), pulls Spotify taste analytics
(SpotifyPlus daily), merges both into a unified taste profile on
sensor.ai_music_taste_status, and stores everything in L2 memory.
"""

import asyncio
import hashlib
import json
import time
import unicodedata
from datetime import UTC, datetime
from typing import Any

from shared_utils import build_result_entity_name, load_entity_config, reload_entity_config

# ── Constants ────────────────────────────────────────────────────────────────

RESULT_ENTITY = "sensor.ai_music_taste_status"
KILL_SWITCH = "input_boolean.ai_music_taste_enabled"

L2_SPOTIFY_EXPIRY = 30  # days
L2_PROFILE_EXPIRY = 30  # days
PROFILE_KEY = "music_taste:profile"


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


def _get_ma_players() -> list:
    cfg = load_entity_config()
    return cfg.get("music_players") or []


def _get_spotifyplus_entity() -> str:
    cfg = load_entity_config()
    return cfg.get("spotifyplus_entity") or ""


# ── Module State ─────────────────────────────────────────────────────────────

_recent_plays: dict[str, float] = {}  # "artist:title" → timestamp
_recent_plays_lock = asyncio.Lock()
_media_triggers = []           # factory-created trigger references (keep alive)
result_entity_name: dict[str, str] = {}


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

def _normalize(text: str) -> str:
    """Lowercase + strip accents for dedup keys."""
    nfkd = unicodedata.normalize("NFKD", text.lower().strip())
    chars = []
    for c in nfkd:
        if not unicodedata.combining(c):
            chars.append(c)
    return "".join(chars)


def _title_hash(title: str) -> str:
    return hashlib.md5(title.encode()).hexdigest()[:8]  # noqa: S324


def _is_enabled() -> bool:
    try:
        val = state.get(KILL_SWITCH)  # noqa: F821
    except NameError:
        return False
    return val == "on"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


# ── L2 Memory Helpers ────────────────────────────────────────────────────────

async def _l2_set(
    key: str, value: str, tags: str,
    scope: str = "user", expiration_days: int = 180,
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
        log.warning(f"music_taste: L2 set failed key={key}: {exc}")  # noqa: F821
        return False


async def _l2_get(key: str) -> dict | None:
    """Exact-key lookup in L2."""
    try:
        result = pyscript.memory_get(key=key)  # noqa: F821
        return await result
    except Exception as exc:
        log.warning(f"music_taste: L2 get failed key={key}: {exc}")  # noqa: F821
        return None


async def _l2_search(query: str, limit: int = 50) -> list[dict[str, Any]]:
    """Search L2. Returns empty list on failure."""
    try:
        result = pyscript.memory_search(query=query, limit=limit)  # noqa: F821
        resp = await result
        if resp and resp.get("status") == "ok":
            return resp.get("results", [])
    except Exception as exc:
        log.warning(f"music_taste: L2 search failed query={query}: {exc}")  # noqa: F821
    return []


# ── 2A: Real-Time Play Logging ──────────────────────────────────────────────

async def _log_play(entity_id: str, artist: str, title: str) -> bool:
    """Shared play-logging: dedup → L2 write → log. Returns True if logged."""
    artist_norm = _normalize(artist)
    title_norm = _normalize(title)
    dedup_key = f"{artist_norm}:{title_norm}"
    now = time.monotonic()
    dedup_cooldown = _helper_int("input_number.ai_music_dedup_cooldown", 180)

    # Dedup: same artist:title within cooldown window
    async with _recent_plays_lock:
        if dedup_key in _recent_plays and (now - _recent_plays[dedup_key]) < dedup_cooldown:
            return False
        _recent_plays[dedup_key] = now

        # Clean old dedup entries (older than 2× cooldown)
        stale = [k for k, v in _recent_plays.items() if (now - v) > dedup_cooldown * 2]
        for k in stale:
            del _recent_plays[k]

    # Determine room from entity
    room = entity_id.replace("media_player.", "").replace("_ma", "").replace("_", " ").title()

    # L2 key
    thash = _title_hash(title_norm)
    l2_key = f"music_play:{artist_norm}:{thash}"

    # Check existing entry
    existing = await _l2_get(l2_key)
    if existing and existing.get("status") == "ok" and existing.get("value"):
        try:
            data = json.loads(existing["value"])
            data["plays"] = data.get("plays", 0) + 1
            data["last_played"] = _now_iso()
            rooms = data.get("rooms", [])
            if room not in rooms:
                rooms.append(room)
            data["rooms"] = rooms
        except (json.JSONDecodeError, TypeError):
            data = {
                "artist": artist,
                "title": title,
                "plays": 1,
                "last_played": _now_iso(),
                "source": "music_assistant",
                "rooms": [room],
            }
    else:
        data = {
            "artist": artist,
            "title": title,
            "plays": 1,
            "last_played": _now_iso(),
            "source": "music_assistant",
            "rooms": [room],
        }

    play_expiry = _helper_int("input_number.ai_music_play_expiry_days", 365)
    ok = await _l2_set(
        key=l2_key,
        value=json.dumps(data),
        tags="music_taste",
        scope="music",
        expiration_days=play_expiry,
    )
    if ok:
        log.info(f"music_taste: logged {artist} — {title} (plays={data['plays']}, room={room})")  # noqa: F821
    return ok


def _media_trigger_factory(player_id):
    """Create @state_trigger for a single media player (state + media_title)."""
    @state_trigger(  # noqa: F821
        f"{player_id} == 'playing'",
        f"{player_id}.media_title",
    )
    async def _trig(**kwargs):
        await _on_media_playing(**kwargs)
    return _trig


async def _on_media_playing(**kwargs):
    """Log tracks as they start playing on MA players."""
    var_name = kwargs.get("var_name", "")
    log.info(f"music_taste: trigger fired — var_name={var_name}")  # noqa: F821

    if not _is_enabled():
        return

    # Extract entity_id: take first two dot-separated segments
    parts = var_name.split(".")
    entity_id = f"{parts[0]}.{parts[1]}" if len(parts) >= 2 else var_name

    # Must be in playing state
    cur_state = state.get(entity_id)  # noqa: F821
    if cur_state != "playing":
        return

    attrs = state.getattr(entity_id)  # noqa: F821
    artist = attrs.get("media_artist", "") if attrs else ""
    title = attrs.get("media_title", "") if attrs else ""
    content_id = attrs.get("media_content_id", "") if attrs else ""

    # Filter: skip radio streams and TTS (no artist)
    if not artist or not artist.strip():
        return
    if content_id and content_id.startswith("library://radio/"):
        return

    await _log_play(entity_id, artist.strip(), title.strip())


# ── 2A-poll: Polling Fallback ───────────────────────────────────────────────

@time_trigger("period(0, 30)")  # noqa: F821
async def _poll_playing_media():
    """Fallback: catch tracks on players not covered by @state_trigger."""
    if not _is_enabled():
        return

    ma_players = _get_ma_players()
    for entity_id in state.names(domain="media_player"):  # noqa: F821
        if entity_id in ma_players:
            continue  # already covered by @state_trigger
        cur_state = state.get(entity_id)  # noqa: F821
        if cur_state != "playing":
            continue
        attrs = state.getattr(entity_id)  # noqa: F821
        if not attrs:
            continue
        # Content filter: only log music (skip TTS, announcements, etc.)
        content_type = attrs.get("media_content_type", "")
        if content_type != "music":
            continue
        content_id = attrs.get("media_content_id", "")
        if content_id and content_id.startswith("library://radio/"):
            continue
        artist = attrs.get("media_artist", "")
        title = attrs.get("media_title", "")
        if not artist or not artist.strip():
            continue
        await _log_play(entity_id, artist.strip(), title.strip() if title else "")


# ── 2B: Spotify Taste Pull ──────────────────────────────────────────────────

@time_trigger("cron(0 4 * * *)")  # noqa: F821  # helper: input_number.ai_music_top_limit
async def _spotify_daily_pull():
    """Pull Spotify taste analytics via SpotifyPlus once daily at 04:00."""
    if not _is_enabled():
        log.info("music_taste: Spotify pull skipped (disabled)")  # noqa: F821
        return

    # Check SpotifyPlus entity exists
    sp_entity = _get_spotifyplus_entity()
    sp_state = state.get(sp_entity)  # noqa: F821
    if sp_state in (None, "unavailable", "unknown"):
        log.warning("music_taste: SpotifyPlus entity unavailable — skipping Spotify pull")  # noqa: F821
        return

    spotify_top_limit = _helper_int("input_number.ai_music_top_limit", 15)

    # Top artists (medium_term = ~6 months)
    try:
        resp = spotifyplus.get_users_top_artists(  # noqa: F821
            entity_id=sp_entity,
            time_range="medium_term",
            limit=spotify_top_limit,
        )
        if resp and isinstance(resp, dict):
            items = resp.get("items", [])
            artist_names = [item.get("name", "") for item in items if item.get("name")]
            await _l2_set(
                key="music_spotify:top_artists",
                value=json.dumps(artist_names[:spotify_top_limit]),
                tags="music_taste,spotify",
                scope="music",
                expiration_days=L2_SPOTIFY_EXPIRY,
            )
            log.info(f"music_taste: stored {len(artist_names)} Spotify top artists")  # noqa: F821
    except asyncio.TimeoutError:
        log.warning("music_taste: Spotify top artists timed out after 30s")  # noqa: F821
    except Exception as exc:
        log.warning(f"music_taste: Spotify top artists failed: {exc}")  # noqa: F821

    # Top tracks (medium_term)
    try:
        resp = spotifyplus.get_users_top_tracks(  # noqa: F821
            entity_id=sp_entity,
            time_range="medium_term",
            limit=spotify_top_limit,
        )
        if resp and isinstance(resp, dict):
            items = resp.get("items", [])
            tracks = []
            for item in items:
                track_name = item.get("name", "")
                artists = item.get("artists", [])
                artist_name = artists[0].get("name", "") if artists else ""
                if track_name and artist_name:
                    tracks.append({"artist": artist_name, "title": track_name})
            await _l2_set(
                key="music_spotify:top_tracks",
                value=json.dumps(tracks[:spotify_top_limit]),
                tags="music_taste,spotify",
                scope="music",
                expiration_days=L2_SPOTIFY_EXPIRY,
            )
            log.info(f"music_taste: stored {len(tracks)} Spotify top tracks")  # noqa: F821
    except asyncio.TimeoutError:
        log.warning("music_taste: Spotify top tracks timed out after 30s")  # noqa: F821
    except Exception as exc:
        log.warning(f"music_taste: Spotify top tracks failed: {exc}")  # noqa: F821

    # Recently played (last 50)
    try:
        resp = spotifyplus.get_player_recently_played(  # noqa: F821
            entity_id=sp_entity,
            limit=50,
        )
        if resp and isinstance(resp, dict):
            items = resp.get("items", [])
            log.info(f"music_taste: Spotify recently played — {len(items)} items (logged for profile merge)")  # noqa: F821
    except asyncio.TimeoutError:
        log.warning("music_taste: Spotify recently played timed out after 30s")  # noqa: F821
    except Exception as exc:
        log.warning(f"music_taste: Spotify recently played failed: {exc}")  # noqa: F821


# ── 2C: Profile Aggregation ─────────────────────────────────────────────────

async def _aggregate_profile() -> dict[str, Any]:
    """Merge MA play logs + Spotify data into a unified taste profile."""
    # 1. Gather MA play entries from L2
    ma_results = await _l2_search("music_taste", limit=50)
    artist_plays: dict[str, int] = {}
    track_plays: list[dict[str, Any]] = []
    total_plays = 0

    for entry in ma_results:
        key = entry.get("key", "")
        if not key.startswith("music_play_"):
            continue
        try:
            data = json.loads(entry.get("value", "{}"))
        except (json.JSONDecodeError, TypeError):
            continue
        artist = data.get("artist", "")
        title = data.get("title", "")
        plays = data.get("plays", 1)
        if artist:
            artist_plays[artist] = artist_plays.get(artist, 0) + plays
            total_plays += plays
        if artist and title:
            track_plays.append({
                "artist": artist,
                "title": title,
                "plays": plays,
                "source": "music_assistant",
            })

    # 2. Read Spotify data from L2
    sp_artists_raw = await _l2_get("music_spotify:top_artists")
    sp_tracks_raw = await _l2_get("music_spotify:top_tracks")
    sp_artists: list[str] = []
    sp_tracks: list[dict[str, str]] = []

    if sp_artists_raw and sp_artists_raw.get("status") == "ok":
        try:
            sp_artists = json.loads(sp_artists_raw.get("value", "[]"))
        except (json.JSONDecodeError, TypeError):
            pass

    if sp_tracks_raw and sp_tracks_raw.get("status") == "ok":
        try:
            sp_tracks = json.loads(sp_tracks_raw.get("value", "[]"))
        except (json.JSONDecodeError, TypeError):
            pass

    # 3. Weighted artist ranking: MA plays (weight 2) + Spotify position (weight 1)
    artist_scores: dict[str, float] = {}
    for artist, plays in artist_plays.items():
        artist_scores[artist] = plays * 2.0

    spotify_top_limit = _helper_int("input_number.ai_music_top_limit", 15)
    for idx, sp_artist in enumerate(sp_artists):
        # Spotify rank bonus: top artist = N pts, descending
        bonus = max(1, spotify_top_limit - idx)
        # Try to match with existing MA artist (case-insensitive)
        matched = False
        for existing in list(artist_scores.keys()):
            if _normalize(existing) == _normalize(sp_artist):
                artist_scores[existing] += bonus
                matched = True
                break
        if not matched:
            artist_scores[sp_artist] = bonus

    # Sort artists by score descending, take top 15
    artist_score_pairs = []
    for a_name in artist_scores:
        artist_score_pairs.append((artist_scores[a_name], a_name))
    artist_score_pairs.sort(reverse=True)
    top_artists = []
    for _score, a_name in artist_score_pairs[:15]:
        top_artists.append(a_name)

    # 4. Top tracks: MA by play count, enriched with Spotify
    # Sort by plays descending using decorated sort
    decorated = []
    for idx, t in enumerate(track_plays):
        decorated.append((t.get("plays", 0), idx, t))
    decorated.sort(reverse=True)
    track_plays_sorted = []
    for _plays, _idx, t in decorated:
        track_plays_sorted.append(t)
    top_tracks_list = []
    for t in track_plays_sorted[:10]:
        top_tracks_list.append({"artist": t["artist"], "title": t["title"]})
    # Add Spotify tracks not already in list
    existing_keys = set()
    for t in top_tracks_list:
        existing_keys.add(_normalize(f"{t['artist']}:{t['title']}"))
    for sp_t in sp_tracks:
        sp_key = _normalize(f"{sp_t.get('artist', '')}:{sp_t.get('title', '')}")
        if sp_key not in existing_keys and len(top_tracks_list) < 15:
            top_tracks_list.append({"artist": sp_t["artist"], "title": sp_t["title"]})
            existing_keys.add(sp_key)

    # 5. Build summary string
    summary_parts = []
    if top_artists:
        summary_parts.append(f"Top artists: {', '.join(top_artists[:8])}")
    if top_tracks_list:
        track_strs = []
        for t in top_tracks_list[:5]:
            track_strs.append(f"{t['artist']} — {t['title']}")
        summary_parts.append(f"Top tracks: {', '.join(track_strs)}")
    if total_plays:
        summary_parts.append(f"{total_plays} plays logged")
    if sp_artists:
        summary_parts.append("Spotify data included")

    summary = ". ".join(summary_parts) + "." if summary_parts else ""

    profile = {
        "summary": summary,
        "top_artists": top_artists,
        "top_tracks": top_tracks_list,
        "total_plays": total_plays,
        "has_spotify": bool(sp_artists or sp_tracks),
        "last_updated": _now_iso(),
    }

    # 6. Store profile in L2
    await _l2_set(
        key=PROFILE_KEY,
        value=json.dumps(profile),
        tags="music_taste,profile",
        scope="system",
        expiration_days=L2_PROFILE_EXPIRY,
    )

    return profile


@time_trigger("cron(30 4 * * *)")  # noqa: F821
async def _daily_aggregate():
    """Daily profile aggregation at 04:30 (after Spotify pull at 04:00)."""
    if not _is_enabled():
        log.info("music_taste: daily aggregation skipped (disabled)")  # noqa: F821
        return

    profile = await _aggregate_profile()
    raw_summary = profile.get("summary", "")

    # Try LLM genre summary using configured task instance
    genre_summary = ""
    task_instance = state.get("input_text.ai_task_instance")  # noqa: F821
    if task_instance and raw_summary:
        genre_summary = await _generate_genre_summary(raw_summary, task_instance, 100, "")
        # C5: Track the LLM call that _generate_genre_summary makes via llm_task_call
        # (llm_task_call already increments counters, but this was previously a blind spot
        # if called via a different path — now explicitly documented as tracked)

    _set_result(
        "ok",
        op="aggregate",
        summary=raw_summary,
        genre_summary=genre_summary if genre_summary else raw_summary,
        top_artists=json.dumps(profile.get("top_artists", [])),
        top_tracks=json.dumps(profile.get("top_tracks", [])),
        total_plays=profile.get("total_plays", 0),
        has_spotify=profile.get("has_spotify", False),
        last_updated=profile.get("last_updated", ""),
    )
    log.info(  # noqa: F821
        f"music_taste: profile updated — {len(profile.get('top_artists', []))} artists, "
        f"{profile.get('total_plays', 0)} plays (genre_summary={bool(genre_summary)})"
    )


# ── 2D: Startup + Services ──────────────────────────────────────────────────

@time_trigger("startup")  # noqa: F821
async def _startup():
    """Restore taste profile from L2 on startup."""
    task.sleep(10)  # noqa: F821
    await asyncio.to_thread(reload_entity_config)

    _ensure_result_entity_name(force=True)
    _set_result("idle", op="startup", message="initializing")

    # Register media player triggers dynamically from config
    global _media_triggers
    players = _get_ma_players()
    _media_triggers = [_media_trigger_factory(p) for p in players]
    log.info(f"music_taste: registered {len(_media_triggers)} media player triggers")  # noqa: F821

    log.info("music_taste.py loaded — restoring profile from L2")  # noqa: F821

    resp = await _l2_get(PROFILE_KEY)
    if resp and resp.get("status") == "ok" and resp.get("value"):
        try:
            profile = json.loads(resp["value"])
            _set_result(
                "ok",
                op="startup",
                summary=profile.get("summary", ""),
                top_artists=json.dumps(profile.get("top_artists", [])),
                top_tracks=json.dumps(profile.get("top_tracks", [])),
                total_plays=profile.get("total_plays", 0),
                has_spotify=profile.get("has_spotify", False),
                last_updated=profile.get("last_updated", ""),
            )
            log.info(  # noqa: F821
                f"music_taste: restored profile — "
                f"{len(profile.get('top_artists', []))} artists, "
                f"{profile.get('total_plays', 0)} plays"
            )
            return
        except (json.JSONDecodeError, TypeError) as exc:
            log.warning(f"music_taste: failed to parse L2 profile: {exc}")  # noqa: F821

    _set_result("ok", op="startup", message="no_profile_yet")
    log.info("music_taste: no L2 profile found — will populate on first aggregation")  # noqa: F821


DEFAULT_GENRE_PROMPT = (
    "Given this music profile, write a concise genre/style summary in plain text. "
    "No artist or track names. No markdown, no bold, no char counts, no alternatives. "
    "Just one short phrase, max {max_chars} characters.\n\n"
    "Profile: {profile}"
)


async def _generate_genre_summary(
    raw_summary: str, llm_instance: str, max_chars: int, llm_prompt: str = ""
) -> str:
    """Call LLM to produce a concise genre/style summary from raw profile text."""
    template = llm_prompt.strip() if llm_prompt else DEFAULT_GENRE_PROMPT
    prompt = template.replace("{max_chars}", str(max_chars)).replace("{profile}", raw_summary)
    try:
        # Set the task instance for llm_task_call
        old_instance = state.get("input_text.ai_task_instance")  # noqa: F821
        state_val = llm_instance if llm_instance else old_instance  # noqa: F821
        if state_val and state_val != old_instance:
            input_text.set_value(  # noqa: F821
                entity_id="input_text.ai_task_instance", value=state_val
            )
        resp = pyscript.llm_task_call(  # noqa: F821
            prompt=prompt, max_tokens=100, temperature=0.3
        )
        result = await resp
        if state_val and state_val != old_instance and old_instance:
            input_text.set_value(  # noqa: F821
                entity_id="input_text.ai_task_instance", value=old_instance
            )
        text = result.get("response_text", "") if isinstance(result, dict) else ""
        if text:
            text = text.replace("**", "").strip()
            # Drop anything after first newline (alternatives, notes)
            text = text.split("\n")[0].strip()
            return text[:max_chars]
    except Exception as exc:
        log.warning(f"music_taste: genre summary LLM failed: {exc}")  # noqa: F821
    return ""


# ── Test Mode ────────────────────────────────────────────────────────────────

def _is_test_mode() -> bool:
    try:
        return str(
            state.get("input_boolean.ai_test_mode") or "off"  # noqa: F821
        ).lower() == "on"
    except NameError:
        return False


@service(supports_response="optional")  # noqa: F821
async def music_taste_rebuild(
    llm_instance: str = "", summary_max_chars: int = 100, llm_prompt: str = ""
):
    """
    yaml
    name: Music Taste Rebuild
    description: >-
      Force a full profile aggregation now. Optionally generates an LLM
      genre summary if llm_instance is provided.
    fields:
      llm_instance:
        name: LLM Instance
        description: "ha_text_ai sensor entity for genre summary (optional)."
        selector:
          entity:
            domain: sensor
      summary_max_chars:
        name: Summary Max Chars
        description: "Maximum characters for the genre summary."
        default: 100
        selector:
          number:
            min: 40
            max: 200
      llm_prompt:
        name: LLM Prompt
        description: "Custom prompt template. Use {profile} and {max_chars} placeholders."
        selector:
          text:
            multiline: true
    """
    if _is_test_mode():
        log.info("music_taste [TEST]: would rebuild taste profile")  # noqa: F821
        return

    if not _is_enabled():
        return {"status": "skipped", "op": "rebuild", "reason": "disabled"}

    profile = await _aggregate_profile()
    raw_summary = profile.get("summary", "")

    genre_summary = ""
    if llm_instance and raw_summary:
        genre_summary = await _generate_genre_summary(
            raw_summary, llm_instance, int(summary_max_chars), llm_prompt
        )

    _set_result(
        "ok",
        op="rebuild",
        summary=raw_summary,
        genre_summary=genre_summary if genre_summary else raw_summary,
        top_artists=json.dumps(profile.get("top_artists", [])),
        top_tracks=json.dumps(profile.get("top_tracks", [])),
        total_plays=profile.get("total_plays", 0),
        has_spotify=profile.get("has_spotify", False),
        last_updated=profile.get("last_updated", ""),
    )
    log.info("music_taste: manual rebuild complete (genre_summary=%s)", bool(genre_summary))  # noqa: F821
    return {
        "status": "ok",
        "op": "rebuild",
        "top_artists": profile.get("top_artists", []),
        "total_plays": profile.get("total_plays", 0),
        "genre_summary": genre_summary,
    }


@service(supports_response="optional")  # noqa: F821
async def music_taste_stats():
    """
    yaml
    name: Music Taste Stats
    description: Return current taste profile (debugging/dashboard).
    """
    if _is_test_mode():
        log.info("music_taste [TEST]: would return taste stats")  # noqa: F821
        return

    resp = await _l2_get(PROFILE_KEY)
    if resp and resp.get("status") == "ok" and resp.get("value"):
        try:
            profile = json.loads(resp["value"])
            return {"status": "ok", "op": "stats", **profile}
        except (json.JSONDecodeError, TypeError):
            pass
    return {"status": "empty", "op": "stats", "message": "no_profile"}
