"""Transfer a Music Assistant queue from a phone that Home Assistant cannot see.

WHY THIS EXISTS
  The Music Assistant companion app registers a player with the MA server
  (observed: "madaphone", state=playing) but the MA integration never creates a
  Home Assistant entity for it. So `music_assistant.transfer_queue` — which
  takes HA entity_ids — cannot be used: there is no entity for the source.

  MA's own API does see it, so this talks to MA directly over its websocket and
  issues `player_queues/transfer` using MA player ids.

  Mapping is exact, not heuristic: the HA entity's `unique_id` in
  core.entity_registry IS the MA player_id
  (media_player.workshop_ma -> RINCON_74CA60724CA801400).

MA PROTOCOL NOTES (both cost real debugging time — from the official client source)
  - Auth is a COMMAND, not a header: after the websocket handshake send
    {"command":"auth","args":{"token":...}} for schema >= 28. There is no
    Authorization header on connect.
  - `message_id` is a STRING (music_assistant_models.CommandMessage). Sending an
    int means replies never match and every call silently times out.

Service:
  pyscript.ma_phone_transfer
    target_player   HA entity of the MA player to move the music TO   (required)
    room_players    HA entities that are ROOM players — excluded when
                    deciding which MA player is "the phone"           (optional)
    auto_play       start playing on the target (default true)

Pyscript notes:
  - AP-55: sockets/open() are blocked in regular context -> @pyscript_executor
  - AP-71: pyscript builtins cannot be called from executor context, so the
    executor returns plain data and the async caller does all state/logging
  - AP-57: no generator expressions
"""

RESULT_ENTITY = "sensor.ai_ma_phone_transfer_status"
CONFIG_ENTRIES = "/config/.storage/core.config_entries"
ENTITY_REGISTRY = "/config/.storage/core.entity_registry"


@pyscript_executor  # noqa: F821
def _ma_call(target_uid, exclude_uids, auto_play):
    """Find the phone player on the MA server and transfer its queue.

    Runs as native Python: raw RFC6455 websocket, stdlib only. Returns a plain
    dict — no pyscript builtins may be touched from here.
    """
    import base64 as _b64
    import json as _json
    import os as _os
    import socket as _socket
    import struct as _struct

    def _load(path):
        with open(path, "r") as fh:
            return _json.load(fh)

    # ── MA connection details ──────────────────────────────────────────────
    try:
        entries = _load(CONFIG_ENTRIES)["data"]["entries"]
    except (OSError, ValueError, KeyError):
        return {"ok": False, "reason": "cannot read config_entries"}
    cfg = None
    for e in entries:
        if e.get("domain") == "music_assistant" and (e.get("data") or {}).get("token"):
            cfg = e["data"]
            break
    if not cfg:
        return {"ok": False, "reason": "no music_assistant config entry with a token"}
    netloc = str(cfg["url"]).replace("http://", "").replace("https://", "").rstrip("/")
    host = netloc.split(":")[0]
    port = int(netloc.split(":")[1]) if ":" in netloc else 80

    # ── minimal websocket client ───────────────────────────────────────────
    sock = _socket.create_connection((host, port), timeout=20)
    key = _b64.b64encode(_os.urandom(16)).decode()
    sock.sendall((
        f"GET /ws HTTP/1.1\r\nHost: {host}\r\nUpgrade: websocket\r\n"
        f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
        f"Sec-WebSocket-Version: 13\r\n\r\n"
    ).encode())
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = sock.recv(4096)
        if not chunk:
            return {"ok": False, "reason": "handshake closed"}
        buf += chunk
    if b"101" not in buf.split(b"\r\n")[0]:
        return {"ok": False, "reason": "websocket handshake refused"}
    state = {"buf": buf.split(b"\r\n\r\n", 1)[1]}

    def _send(obj):
        payload = _json.dumps(obj).encode()
        n = len(payload)
        hdr = b"\x81"
        if n < 126:
            hdr += _struct.pack("!B", n | 0x80)
        elif n < 65536:
            hdr += _struct.pack("!BH", 126 | 0x80, n)
        else:
            hdr += _struct.pack("!BQ", 127 | 0x80, n)
        mask = _os.urandom(4)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        sock.sendall(hdr + mask + masked)

    def _read(n):
        while len(state["buf"]) < n:
            chunk = sock.recv(65536)
            if not chunk:
                raise OSError("socket closed")
            state["buf"] += chunk
        out = state["buf"][:n]
        state["buf"] = state["buf"][n:]
        return out

    def _recv():
        while True:
            b1, b2 = _read(2)
            opcode = b1 & 0x0F
            ln = b2 & 0x7F
            if ln == 126:
                ln = _struct.unpack("!H", _read(2))[0]
            elif ln == 127:
                ln = _struct.unpack("!Q", _read(8))[0]
            data = _read(ln)
            if opcode == 1:
                return _json.loads(data)
            if opcode == 8:
                raise OSError("server closed")

    def _cmd(command, mid, **args):
        # message_id MUST be a string, else the reply never matches
        mid = str(mid)
        _send({"command": command, "message_id": mid, "args": args})
        for _ in range(60):
            msg = _recv()
            if str(msg.get("message_id")) == mid:
                return msg
        return None

    try:
        hello = _recv()
        if int(hello.get("schema_version") or 0) >= 28:
            auth = _cmd("auth", "0", token=cfg["token"])
            if not auth or auth.get("error"):
                return {"ok": False, "reason": "MA auth failed"}

        res = _cmd("players/all", "1")
        if not res or res.get("error"):
            return {"ok": False, "reason": "players/all failed"}

        source_id = ""
        source_name = ""
        source_title = ""
        for p in (res.get("result") or []):
            pid = str(p.get("player_id") or "")
            if not pid or pid == target_uid or pid in exclude_uids:
                continue
            if p.get("state") != "playing" or not p.get("available"):
                continue
            source_id = pid
            source_name = str(p.get("display_name") or "")
            source_title = str((p.get("current_media") or {}).get("title") or "")
            break

        if not source_id:
            return {"ok": False, "reason": "no off-HA player is playing"}

        tr = _cmd(
            "player_queues/transfer", "2",
            source_queue_id=source_id,
            target_queue_id=target_uid,
            auto_play=bool(auto_play),
        )
        if not tr or tr.get("error"):
            return {
                "ok": False,
                "reason": f"transfer failed: {(tr or {}).get('error', 'no response')}",
                "source_name": source_name,
            }
        return {
            "ok": True,
            "source_id": source_id,
            "source_name": source_name,
            "title": source_title,
        }
    except (OSError, ValueError) as exc:
        return {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}
    finally:
        try:
            sock.close()
        except OSError:
            pass


@pyscript_executor  # noqa: F821
def _entity_to_ma_id(entity_ids):
    """Map HA entity_ids -> MA player ids via the registry unique_id."""
    import json as _json

    try:
        with open(ENTITY_REGISTRY, "r") as fh:
            reg = _json.load(fh)
    except (OSError, ValueError):
        return {}
    out = {}
    for e in reg.get("data", {}).get("entities", []):
        if e.get("platform") != "music_assistant":
            continue
        if e.get("entity_id") in entity_ids:
            out[e["entity_id"]] = e.get("unique_id") or ""
    return out


async def _publish(status, detail=""):
    import datetime

    state.set(  # noqa: F821
        RESULT_ENTITY,
        status,
        new_attributes={
            "icon": "mdi:cellphone-arrow-down",
            "friendly_name": "AI MA Phone Transfer Status",
            "detail": detail,
            "updated": datetime.datetime.now().isoformat(timespec="seconds"),
        },
    )


@time_trigger("startup")  # noqa: F821
def ma_phone_transfer_startup():
    """Seed the status sensor — state.set() sensors do not survive a restart."""
    task.create(_seed)  # noqa: F821


async def _seed():
    try:
        cur = state.get(RESULT_ENTITY)  # noqa: F821
    except NameError:
        cur = None
    if cur in (None, "", "unknown", "unavailable"):
        await _publish("idle", "seeded at startup")


@service  # noqa: F821
async def ma_phone_transfer(target_player="", room_players="", auto_play=True):
    """yaml
    name: MA Phone Transfer
    description: >-
      Move a Music Assistant queue from a phone (or any MA player that Home
      Assistant has no entity for) onto a target MA player. Talks to the Music
      Assistant server directly, because music_assistant.transfer_queue needs
      HA entity_ids and the phone has none.
    fields:
      target_player:
        description: HA entity of the Music Assistant player to move the music TO.
        required: true
        example: media_player.workshop_ma
        selector:
          entity:
            domain: media_player
      room_players:
        description: >-
          Room MA players, excluded when deciding which MA player is "the
          phone". Normally the same list as the follow-me target players.
        required: false
        example: media_player.workshop_ma, media_player.bathroom_ma
        selector:
          entity:
            domain: media_player
            multiple: true
      auto_play:
        description: Start playing on the target immediately.
        required: false
        default: true
        selector:
          boolean:
    """
    tgt = str(target_player or "").strip()
    if not tgt:
        await _publish("error", "target_player is required")
        return {"ok": False, "reason": "missing target_player"}

    if isinstance(room_players, str):
        rooms = [r.strip() for r in room_players.split(",") if r.strip()]
    else:
        rooms = [str(r).strip() for r in (room_players or []) if str(r).strip()]

    wanted = [tgt] + rooms
    mapping = await _entity_to_ma_id(wanted)
    target_uid = mapping.get(tgt, "")
    if not target_uid:
        await _publish("error", f"{tgt} is not a Music Assistant player")
        return {"ok": False, "reason": "target not an MA player"}

    exclude = []
    for r in rooms:
        uid = mapping.get(r)
        if uid:
            exclude.append(uid)

    res = await _ma_call(target_uid, exclude, bool(auto_play))

    if res.get("ok"):
        detail = f"{res.get('source_name')} -> {tgt.split('.')[-1]}"
        if res.get("title"):
            detail += f" ({res['title']})"
        log.info(f"ma_phone_transfer: {detail}")  # noqa: F821
        await _publish("ok", detail)
    elif res.get("reason") == "no off-HA player is playing":
        # Not a fault: the arrival branch calls this speculatively, so "nothing
        # was playing on the phone" is the normal quiet outcome.
        log.info("ma_phone_transfer: nothing playing off-HA, nothing to move")  # noqa: F821
        await _publish("idle", "nothing playing on an off-HA player")
    else:
        log.warning(f"ma_phone_transfer: {res.get('reason')}")  # noqa: F821
        await _publish("error", str(res.get("reason"))[:120])
    return res
