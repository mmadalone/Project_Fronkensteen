"""Spotify Connect follow-me transfer.

WHY THIS EXISTS
  Moving an Alexa-driven Spotify session between Sonos speakers cannot be done
  with `spotifyplus.player_transfer_playback`: on a Sonos it wakes the device
  and resumes that device's OWN local queue, so you get whatever was last
  played in that room rather than what you were listening to. Observed live:
  walking into the bathroom started a track from hours earlier.

  `spotifyplus.player_media_play_context` is the documented alternative but
  fails when the context is the Liked Songs pseudo-URI
  (`spotify:user:<id>:collection`), which Spotify's play endpoint rejects.

  So this service does what actually works, proven empirically:
    1. wake the SpotifyPlus entity (a transfer while it is 'off' returns
       HTTP 200 and silently does nothing)
    2. read the live track + position + upcoming queue from the Web API
    3. spotifyplus.player_media_play_tracks -> target device, seeded with the
       current track AND the upcoming queue so playback continues past one song
    4. pause the source speaker, making it a move rather than a duplicate

Service:
  pyscript.spotify_follow_me_transfer
    spotifyplus_entity  media_player.spotifyplus_*      (required)
    target_device_id    40-char Spotify Connect id      (required)
    source_player       media_player.* to pause afterwards (optional)
    queue_depth         how many upcoming tracks to carry (default 20)

Pyscript notes:
  - AP-55: open()/urllib are blocked in regular context -> @pyscript_executor
  - AP-71: pyscript builtins cannot be called from executor context, so the
    executor returns plain data and the async caller does all state/service work
  - AP-57: no generator expressions
"""

RESULT_ENTITY = "sensor.ai_spotify_follow_me_status"
CONFIG_ENTRIES = "/config/.storage/core.config_entries"


@pyscript_executor  # noqa: F821
def _resolve_device_by_name(token, name):
    """Look up a Spotify Connect device id by display name.

    Device ids are NOT stable — Spotify regenerates them — so anything that
    targets the phone must resolve by name at runtime rather than store an id.
    Returns "" when the device is not currently listed.
    """
    import json as _json
    import urllib.error as _err
    import urllib.request as _req

    try:
        resp = _req.urlopen(_req.Request(
            "https://api.spotify.com/v1/me/player/devices",
            headers={"Authorization": "Bearer " + token}), timeout=20)
        devices = _json.loads(resp.read().decode()).get("devices") or []
    except (_err.HTTPError, _err.URLError, ValueError, OSError):
        return ""
    wanted = str(name).strip().lower()
    for d in devices:
        if str(d.get("name") or "").strip().lower() == wanted:
            return str(d.get("id") or "")
    return ""


@pyscript_executor  # noqa: F821
def _read_spotify_token(path):
    """Pull the SpotifyPlus OAuth access token out of core.config_entries."""
    import json as _json

    try:
        with open(path, "r") as fh:
            data = _json.load(fh)
    except (FileNotFoundError, ValueError, OSError):
        return ""
    for entry in data.get("data", {}).get("entries", []):
        if not str(entry.get("domain", "")).startswith("spotifyplus"):
            continue
        tok = (entry.get("data") or {}).get("token") or {}
        access = tok.get("access_token")
        if access:
            return access
    return ""


@pyscript_executor  # noqa: F821
def _fetch_playback(token, queue_depth):
    """Read current playback + upcoming queue. Returns a plain dict."""
    import json as _json
    import urllib.request as _req
    import urllib.error as _err

    hdr = {"Authorization": "Bearer " + token}

    def _get(url):
        try:
            resp = _req.urlopen(_req.Request(url, headers=hdr), timeout=20)
            body = resp.read().decode()
            return _json.loads(body) if body.strip() else {}
        except (_err.HTTPError, _err.URLError, ValueError, OSError):
            return {}

    now = _get("https://api.spotify.com/v1/me/player")
    if not now:
        return {"ok": False, "reason": "no_playback"}

    item = now.get("item") or {}
    uri = item.get("uri")
    if not uri:
        return {"ok": False, "reason": "no_track"}

    uris = [uri]
    queue = _get("https://api.spotify.com/v1/me/player/queue")
    for track in (queue.get("queue") or [])[:queue_depth]:
        turi = track.get("uri")
        if turi and turi.startswith("spotify:track:"):
            uris.append(turi)

    return {
        "ok": True,
        "uris": uris,
        "position_ms": int(now.get("progress_ms") or 0),
        "track_name": item.get("name") or "",
        "device": (now.get("device") or {}).get("name") or "",
    }


async def _set_status(status, detail="", carried=None):
    """Publish status, and carry the queue forward for the next hop.

    Once playback moves via player_media_play_tracks it lives in the target's
    Sonos LOCAL queue, which the Spotify Web API cannot see — a second hop
    reads back "no_playback". So the URI list is stashed here and re-sliced
    from the current track on the next transfer.
    """
    import datetime

    attrs = {
        "icon": "mdi:spotify",
        "friendly_name": "AI Spotify Follow-Me Status",
        "detail": detail,
        "updated": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    # new_attributes REPLACES the whole attribute dict, so an error write would
    # otherwise wipe the carried queue and break the next hop. Preserve it.
    attrs["carried_uris"] = carried if carried is not None else _carried_uris()
    state.set(RESULT_ENTITY, status, new_attributes=attrs)  # noqa: F821


def _carried_uris():
    """Previously carried queue, if any."""
    try:
        val = state.getattr(RESULT_ENTITY)  # noqa: F821
    except (NameError, AttributeError):
        return []
    if not val:
        return []
    got = val.get("carried_uris") or []
    return list(got) if isinstance(got, list) else []


def _slice_from(uris, current_uri):
    """Return uris starting at current_uri (inclusive). [] if not present."""
    if not current_uri or not uris:
        return []
    out = []
    found = False
    for u in uris:
        if u == current_uri:
            found = True
        if found:
            out.append(u)
    return out


@time_trigger("startup")  # noqa: F821
def spotify_follow_me_startup():
    """Seed the status sensor at boot.

    state.set() sensors do not survive a restart, and unlike the token monitor
    this one is otherwise created only when a transfer runs — leaving it
    missing after every reboot. carried_uris starts empty, which is correct:
    the first hop after a restart reads the Web API anyway.
    """
    task.create(_seed_status)  # noqa: F821


async def _seed_status():
    try:
        current = state.get(RESULT_ENTITY)  # noqa: F821
    except NameError:
        current = None
    if current in (None, "", "unknown", "unavailable"):
        await _set_status("idle", "seeded at startup", carried=[])


@service  # noqa: F821
async def spotify_follow_me_transfer(
    spotifyplus_entity="",
    target_device_id="",
    source_player="",
    source_ma_player="",
    source_device_id="",
    target_player="",
    target_device_name="",
    queue_depth=20,
    ma_seek=False,
    autoplay=True,
):
    """yaml
    name: Spotify Follow-Me Transfer
    description: >-
      Move the live Spotify session to a Spotify Connect device, carrying the
      current track, playback position and upcoming queue, then pause the
      source speaker. Works with Alexa-driven Sonos sessions, which
      spotifyplus.player_transfer_playback cannot move correctly.
    fields:
      spotifyplus_entity:
        description: The SpotifyPlus media_player entity.
        required: true
        example: media_player.spotifyplus_username
        selector:
          entity:
            domain: media_player
      target_device_id:
        description: >-
          40-character Spotify Connect device ID of the target speaker (Sonos).
          Leave empty for a Music Assistant target, in which case target_player
          is used and MA streams the tracks itself.
        required: false
        example: 4fbbc98a2dc8a070fcd028bba50cf48e5fc386ee
        selector:
          text:
      source_player:
        description: Speaker to pause after the move. Leave empty to duplicate instead.
        required: false
        example: media_player.workshop_sonos
        selector:
          entity:
            domain: media_player
      source_device_id:
        description: >-
          Spotify Connect device ID of the SOURCE, used to pause it when the
          source is not an HA entity — the arrival case, where music is playing
          on a phone. Ignored when source_player is set.
        required: false
        example: 31d19297-972b-492a-909f-24516b98b58f
        selector:
          text:
      source_ma_player:
        description: >-
          The source room's Music Assistant player. Used as the fallback source
          of truth for track and position when the Spotify Web API cannot see
          the session — which is the case after the first hop, because playback
          then lives in the target's Sonos local queue.
        required: false
        example: media_player.workshop_ma
        selector:
          entity:
            domain: media_player
      target_player:
        description: >-
          The target room's Music Assistant player, used to VERIFY playback
          actually started before pausing the source. Without it a failed
          transfer silences every room.
        required: false
        example: media_player.bathroom_ma
        selector:
          entity:
            domain: media_player
      target_device_name:
        description: >-
          Spotify Connect device NAME to target, resolved at runtime. Use this
          instead of target_device_id when the id is not stable — notably a
          phone, whose device id Spotify regenerates.
        required: false
        example: Madaphone
        selector:
          text:
      ma_seek:
        description: >-
          Seek to the original position on Music Assistant targets. Off by
          default: MA serves Spotify as a duration-less stream and logs that
          seeking is not possible, and a Voice PE crashed shortly after one
          such seek (unproven as the cause). Leaving it off means MA targets
          restart the track.
        required: false
        default: false
        selector:
          boolean:
      autoplay:
        description: >-
          Start playing on the target. Set false to hand over PAUSED — used by
          the reverse transfer so music does not start in your pocket.
        required: false
        default: true
        selector:
          boolean:
      queue_depth:
        description: How many upcoming tracks to carry across (0-50).
        required: false
        example: 20
        selector:
          number:
            min: 0
            max: 50
    """
    sp = str(spotifyplus_entity or "").strip()
    dev = str(target_device_id or "").strip()
    src = str(source_player or "").strip()
    ma_source = str(source_ma_player or "").strip()
    src_dev = str(source_device_id or "").strip()
    tgt = str(target_player or "").strip()
    tgt_name = str(target_device_name or "").strip()
    try:
        depth = int(queue_depth)
    except (TypeError, ValueError):
        depth = 20
    depth = max(0, min(50, depth))

    # Two target shapes: a Spotify Connect device (Sonos) addressed by 40-char
    # device id, or a Music Assistant player (e.g. ESPHome Voice PE) which is
    # not a Connect endpoint and must be streamed by MA itself.
    if not sp:
        await _set_status("error", "spotifyplus_entity is required")
        return {"ok": False, "reason": "missing_args"}
    if not dev and not tgt and not tgt_name:
        await _set_status(
            "error",
            "need target_device_id / target_device_name (Connect) or target_player (MA)",
        )
        return {"ok": False, "reason": "missing_args"}

    # 1. Wake SpotifyPlus. While its entity is 'off' the transfer/play services
    #    return HTTP 200 and silently do nothing.
    try:
        if state.get(sp) == "off":  # noqa: F821
            service.call("media_player", "turn_on", entity_id=sp)  # noqa: F821
            await task.sleep(6)  # noqa: F821
    except NameError:
        pass

    token = await _read_spotify_token(CONFIG_ENTRIES)
    if not token:
        await _set_status("error", "no Spotify token in core.config_entries")
        return {"ok": False, "reason": "no_token"}

    # Resolve a Connect target by NAME when no id was given (the reverse
    # transfer targets a phone, whose device id Spotify regenerates).
    if not dev and tgt_name:
        dev = await _resolve_device_by_name(token, tgt_name)
        if not dev:
            await _set_status("error", f"device '{tgt_name}' not in Spotify's device list")
            return {"ok": False, "reason": "target_device_not_found"}

    info = await _fetch_playback(token, depth)

    # Fall back to the source Music Assistant player when the Web API cannot
    # see the session — which is always true after the first hop, because the
    # content is then playing from the target's Sonos local queue.
    if not info.get("ok"):
        ma_uri, ma_pos, ma_name = "", 0, ""
        if ma_source:
            try:
                attrs = state.getattr(ma_source) or {}  # noqa: F821
                ma_uri = str(attrs.get("media_content_id") or "")
                ma_pos = float(attrs.get("media_position") or 0)
                ma_name = str(attrs.get("media_title") or "")
                # media_position is a SNAPSHOT taken at media_position_updated_at,
                # not a live counter — without this correction the track restarts
                # several seconds behind where it actually is.
                upd = attrs.get("media_position_updated_at")
                if upd is not None:
                    import datetime

                    if not isinstance(upd, datetime.datetime):
                        upd = datetime.datetime.fromisoformat(
                            str(upd).replace("Z", "+00:00")
                        )
                    drift = (
                        datetime.datetime.now(datetime.timezone.utc) - upd
                    ).total_seconds()
                    if 0 < drift < 3600:
                        ma_pos = ma_pos + drift
                ma_pos = int(ma_pos)
            except (NameError, AttributeError, TypeError, ValueError):
                ma_uri, ma_pos, ma_name = "", 0, ""

        carried = _slice_from(_carried_uris(), ma_uri)
        if not ma_uri.startswith("spotify:track:") or not carried:
            reason = info.get("reason") or "no_playback"
            await _set_status("error", f"playback read failed: {reason}")
            return {"ok": False, "reason": reason}

        info = {
            "ok": True,
            "uris": carried[: depth + 1],
            "position_ms": ma_pos * 1000,
            "track_name": ma_name,
            "device": ma_source,
            "source": "ma_fallback",
        }

    uris = info["uris"]
    log.info(  # noqa: F821
        f"spotify_follow_me: moving '{info['track_name']}' "
        f"(+{len(uris) - 1} queued, via {info.get('source', 'web_api')}) "
        f"from {info['device'] or '?'} to device {dev[:12]}… "
        f"at {info['position_ms']}ms"
    )

    # 2. Seed the target with the real content at the real position.
    #    Wrapped: SpotifyPlus can raise while reading Sonos state back
    #    (GetPlayerPlaybackStateSonos -> GetTrack) if any queued URI will not
    #    resolve. Playback itself usually still starts, so verify rather than
    #    assume either way.
    play_error = ""
    if dev:
        # ── Spotify Connect target (Sonos): hand the tracks to the device ──
        try:
            service.call(  # noqa: F821
                "spotifyplus",
                "player_media_play_tracks",
                entity_id=sp,
                uris=",".join(uris),
                position_ms=info["position_ms"],
                device_id=dev,
            )
        except Exception as exc:  # noqa: BLE001 - surface, never swallow
            play_error = str(exc)[:160]
            log.warning(f"spotify_follow_me: play_tracks raised: {play_error}")  # noqa: F821
    else:
        # ── Music Assistant target (e.g. an ESPHome Voice PE) ──
        # Not a Spotify Connect endpoint, so MA must stream it itself. This
        # only became possible with MA 2.9.13 (#5601 "Fix Spotify playback
        # authorization"); before that librespot failed INVALID_CREDENTIALS.
        # music_assistant.transfer_queue is NOT usable here — it moves an MA
        # queue between MA players, and a source that is merely MIRRORING an
        # Alexa session has no queue to move (returns HTTP 500).
        try:
            service.call(  # noqa: F821
                "music_assistant",
                "play_media",
                entity_id=tgt,
                media_id=uris,
                media_type="track",
            )
            # play_media always starts at 0, so a seek is needed to preserve
            # position. OPT-IN (ma_seek), default off: MA serves Spotify as a
            # duration-less queue-flow stream and logs "seeking is not possible
            # on duration-less streams!", and a Voice PE crashed (esp32 panic)
            # shortly after one such seek. That was never proven to be the
            # cause — a later seek did not crash — so this is exposed as a
            # setting rather than removed. Cost of leaving it off: MA targets
            # restart the track from the beginning.
            if ma_seek and info["position_ms"] > 2000:
                await task.sleep(6)  # noqa: F821
                service.call(  # noqa: F821
                    "media_player",
                    "media_seek",
                    entity_id=tgt,
                    seek_position=int(info["position_ms"] / 1000),
                )
        except Exception as exc:  # noqa: BLE001
            play_error = str(exc)[:160]
            log.warning(f"spotify_follow_me: ma play_media raised: {play_error}")  # noqa: F821

    # 3. VERIFY the target actually started before touching the source.
    #    Pausing the source unconditionally is how a failed transfer turns into
    #    silence in every room — observed in the field.
    started = False
    if tgt:
        for _ in range(6):
            await task.sleep(3)  # noqa: F821
            try:
                if state.get(tgt) in ("playing", "buffering"):  # noqa: F821
                    started = True
                    break
            except NameError:
                break
    else:
        # No target entity given to verify with — assume the call worked only
        # if it did not raise, and never pause blind.
        started = not play_error

    if not started:
        await _set_status(
            "error",
            f"target did not start; source left playing. {play_error}".strip(),
            carried=uris,
        )
        log.warning(  # noqa: F821
            "spotify_follow_me: target did not start — leaving the source "
            "playing rather than silencing every room"
        )
        return {"ok": False, "reason": "target_did_not_start"}

    # 3b. Hand over paused when asked. Used by the reverse transfer: music
    #     suddenly starting in your pocket as you leave the house is worse than
    #     having to press play. Pause the TARGET, not the source — the source is
    #     stopped below either way.
    if not autoplay:
        try:
            if dev:
                service.call(  # noqa: F821
                    "spotifyplus", "player_media_pause",
                    entity_id=sp, device_id=dev,
                )
            elif tgt:
                service.call("media_player", "media_pause", entity_id=tgt)  # noqa: F821
        except Exception as exc:  # noqa: BLE001
            log.warning(  # noqa: F821
                f"spotify_follow_me: handover-paused failed: {str(exc)[:120]}"
            )

    # 4. Only now make it a move rather than a duplicate.
    if src:
        service.call("media_player", "media_pause", entity_id=src)  # noqa: F821
    elif src_dev:
        # Arrival case: the source is a phone, which is NOT an HA media_player,
        # so there is nothing to media_pause. Pause it by Spotify Connect
        # device id instead.
        try:
            service.call(  # noqa: F821
                "spotifyplus", "player_media_pause",
                entity_id=sp, device_id=src_dev,
            )
        except Exception as exc:  # noqa: BLE001
            # Not fatal: Spotify allows only one active stream, so the phone
            # stops on its own once the target takes over.
            log.warning(  # noqa: F821
                f"spotify_follow_me: could not pause source device {src_dev[:12]}…: "
                f"{str(exc)[:120]}"
            )

    await _set_status(
        "ok",
        f"{info['track_name']} -> {dev[:12]}… (+{len(uris) - 1} queued)",
        carried=uris,
    )
    return {"ok": True, "tracks": len(uris), "position_ms": info["position_ms"]}
