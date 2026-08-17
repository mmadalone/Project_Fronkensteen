"""On-demand inbox reader — the PULL counterpart to email_promote/email_follow_me.

WHY THIS EXISTS
  email_follow_me announces mail as it ARRIVES (imap_content event). Nothing
  could answer a spoken question ABOUT mail, because Home Assistant's `imap`
  integration cannot enumerate a mailbox:
    - ImapSensor.native_value is a bare int count with no extra_state_attributes
    - every imap service (fetch/fetch_part/seen/move/delete) needs a message id
      you can only learn from the arrival event; nothing lists them
  and nothing in this project persists an inbox — email_promote.py stores
  counters and depth-1 snapshots only.

  So this module opens its own READ-ONLY IMAP session with the stdlib and the
  credentials already in the imap config entry. No new dependencies.

THE UID TRAP (read before touching anything that addresses a message)
  HA's imap_content event publishes a field called `uid` that is actually a
  mailbox SEQUENCE NUMBER — aioimaplib's read path is all by_uid=False. Sequence
  numbers renumber on every expunge. Verified live: this INBOX had 13 messages
  with sequence numbers 1..13 and real UIDs 11700..12771, while the push path
  had stored "17,15,13,14,16".

  Therefore this module addresses EVERYTHING with UID SEARCH / UID FETCH, and
  never hands a number back to the caller. Messages are identified by an opaque
  handle ("h1", "h2", ...) resolved internally. Nothing is persisted: UIDVALIDITY
  would have to be persisted and invalidated alongside it.

SAFETY INVARIANTS — breaking either one is silent and severe
  1. select(folder, readonly=True) and BODY.PEEK[...] everywhere. A bare BODY[]
     sets \\Seen, and the whole push path keys on `UnSeen`, so a slip here
     silently kills email notifications forever.
  2. Never log, return, or state.set the password. It is plaintext in the config
     entry; pyscript tracebacks reach home-assistant.log, which ships in
     diagnostics and backups.

  Gmail also caps simultaneous IMAP connections (~15) and HA's own coordinator
  holds a persistent IDLE connection to the same account. If we exhaust the cap
  the coordinator raises UpdateFailed, reconnects, and a fresh coordinator resets
  _last_message_id — re-firing imap_content for the last unseen message, i.e. a
  DUPLICATE spoken announcement. Hence the single-flight lock, result cache and
  minimum inter-login interval below.

UNTRUSTED CONTENT
  Everything under "messages" is attacker-written text entering an agent that
  holds tool-calling ability. Defaults return subjects, not bodies. Text is
  stripped, instruction-neutered, secret-redacted and escaped here — at the
  boundary — so a direct Dev Tools call is exactly as safe as a voice call.
  The strip chain is a 1:1 port of the Jinja chain in
  blueprints/automation/madalone/email_follow_me.yaml:1275-1330; keep them in sync.

Services:
  pyscript.email_inbox_query   mode=summary|unread|important|search|detail|clear
  pyscript.email_inbox_health  connectivity probe, touches no message

Pyscript notes:
  - AP-55: sockets/open() are blocked in regular context -> @pyscript_executor
  - AP-71: pyscript builtins (state/log/service) cannot be called from executor
    context, so the executor takes plain values and returns a plain dict
  - AP-70: `global` declarations go at the top of the function body
  - AP-57: no generator expressions
"""

import time
from typing import Any

from shared_utils import build_result_entity_name

RESULT_ENTITY = "sensor.ai_email_reader_status"

# Caps. The service arguments are advisory; these are not.
MAX_LIMIT = 15
MAX_BODY_CHARS = 2000
MAX_PREVIEW_CHARS = 300
MAX_DAYS_BACK = 30
MAX_PAYLOAD_CHARS = 6000

# Connection discipline — see the Gmail note in the module docstring.
CACHE_TTL = 60.0
HANDLE_TTL = 900.0
MIN_LOGIN_INTERVAL = 5.0
IMAP_TIMEOUT = 15

VALID_MODES = ["summary", "unread", "important", "search", "detail", "clear"]

result_entity_name: dict = {}

# key -> {"at": float, "result": dict}
_cache: dict = {}
# handle -> {"at": float, "uid": str}
_handles: dict = {}
_handle_seq = 0
_last_login = 0.0
_inflight = False


# ── Helper reads (async context only — state.get is unavailable in executors) ──

def _helper_str(entity_id: str, default: str = "") -> str:
    """state.get() raises NameError for unregistered entities — always guard."""
    try:
        val = state.get(entity_id)  # noqa: F821
        if val and val not in ("unknown", "unavailable", ""):
            return str(val)
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


def _ensure_result_entity_name(force: bool = False) -> None:
    global result_entity_name
    if force or not result_entity_name:
        result_entity_name = build_result_entity_name(RESULT_ENTITY)


def _set_result(state_value: str = "ok", **attrs: Any) -> None:
    _ensure_result_entity_name()
    attrs.update(result_entity_name)
    state.set(RESULT_ENTITY, value=state_value, new_attributes=attrs)  # noqa: F821


def _clamp(value, lo, hi, default):
    try:
        n = int(float(value))
    except (TypeError, ValueError):
        return default
    if n < lo:
        return lo
    if n > hi:
        return hi
    return n


def _imap_config(account: str = "") -> dict:
    """Read the imap config entry.

    hass.config_entries is reachable because configuration.yaml sets
    `pyscript: hass_is_global: true` — same approach as media_promote.py:73-80.
    Avoids parsing .storage by hand.

    Returns {} when no entry matches. The password is carried in the returned
    dict and must never be logged or echoed back to a caller.
    """
    wanted = str(account or "").strip().lower()
    try:
        entries = hass.config_entries.async_entries("imap")  # noqa: F821
    except Exception:
        return {}
    for entry in entries:
        title = str(getattr(entry, "title", "") or "")
        if wanted and wanted not in title.lower():
            continue
        data = dict(entry.data or {})
        if not data.get("server"):
            continue
        data["_title"] = title
        return data
    return {}


def _next_handles(uids: list) -> dict:
    """Mint opaque handles for this result set.

    The agent never sees a UID or a sequence number, so it can never pass one to
    an `imap.*` service (which would address by SEQUENCE NUMBER and act on the
    wrong message).
    """
    global _handle_seq, _handles

    now = time.time()
    stale = []
    for key in _handles:
        if now - _handles[key]["at"] > HANDLE_TTL:
            stale.append(key)
    for key in stale:
        del _handles[key]

    out = {}
    for uid in uids:
        _handle_seq += 1
        handle = "h%d" % _handle_seq
        _handles[handle] = {"at": now, "uid": str(uid)}
        out[str(uid)] = handle
    return out


def _resolve_handle(handle: str) -> str:
    now = time.time()
    rec = _handles.get(str(handle or "").strip())
    if not rec:
        return ""
    if now - rec["at"] > HANDLE_TTL:
        return ""
    return rec["uid"]


# ── IMAP + scrubbing (executor context: plain Python only, no pyscript builtins) ──

@pyscript_executor  # noqa: F821
def _imap_run(cfg, opts):
    """Open a read-only IMAP session and return a plain dict.

    Everything happens in one connection: capability detection, SEARCH, header
    FETCH, optional single-body FETCH, classification and scrubbing. Nothing in
    here may touch state/log/service (AP-71).
    """
    import email as _email
    import imaplib as _imaplib
    import quopri as _quopri
    import re as _re
    import ssl as _ssl
    import time as _time
    from email.header import decode_header as _decode_header
    from email.header import make_header as _make_header

    # IMAP dates need the English month abbreviation regardless of locale, so
    # never use strftime("%b") here.
    _MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

    # ---- scrubbing -------------------------------------------------------
    # 1:1 port of email_follow_me.yaml:1275-1330, same order. URLs first, so a
    # tracking beacon dies before anything else runs.
    _BODY_PATTERNS = [
        (r'https?://[^\s<>")\]]+', ""),
        (r'ftp://[^\s<>")\]]+', ""),
        (r'mailto:[^\s<>")\]]+', ""),
        (r'\bwww\.[^\s<>")\]]+', ""),
        (r"Content-Type:[^\n]+", ""),
        (r"boundary=[^\s]+", ""),
        # Bare multipart delimiter lines. `boundary=` above only catches the
        # declaration in the header; the delimiter itself appears in the body as
        # e.g. "----==_mimepart_6a81fe38bce1b_be11a054644e" and survived both
        # that rule and the base64 rule (underscores and dashes are not in the
        # base64 class). Previews fetch BODY.PEEK[TEXT], which is the raw
        # multipart payload, so they hit this on every multipart message.
        (r"--[=_A-Za-z0-9.\-]{16,}", ""),
        (r"charset=[^\s;]+", ""),
        (r"MIME-Version:[^\n]+", ""),
        (r"Content-Transfer-Encoding:[^\n]+", ""),
        (r"Content-Disposition:[^\n]+", ""),
        (r"[A-Za-z0-9+/=]{30,}", ""),
        (r"(font-family|font-size|line-height|color|background-color|background"
         r"|display|margin|padding|border|text-align|text-decoration"
         r"|vertical-align|width|height|max-width|min-width)\s*:\s*[^;}{]+[;]?", ""),
        (r"#[0-9a-fA-F]{6}\b", ""),
        (r"#[0-9a-fA-F]{3}\b", ""),
        (r"\b1x1\b", ""),
        (r"\b0x0\b", ""),
        (r"^From:[^\n]+", ""),
        (r"^To:[^\n]+", ""),
        (r"^X-[A-Za-z0-9-]+:[^\n]+", ""),
        (r"^Reply-To:[^\n]+", ""),
        (r"unsubscribe[^\n.]*[.\n]?", ""),
        (r"privacy\s+policy[^\n.]*[.\n]?", ""),
        (r"©\s*\d{4}[^\n]*", ""),
        (r"copyright\s+\d{4}[^\n]*", ""),
        (r"all\s+rights\s+reserved[^\n.]*[.\n]?", ""),
        (r"sent\s+from\s+my\s+(iphone|ipad|galaxy|android|samsung)[^\n.]*[.\n]?", ""),
        (r"view\s+(this\s+)?(email\s+)?in\s+(your\s+)?browser[^\n.]*[.\n]?", ""),
        (r"if\s+you\s+no\s+longer\s+wish\s+to\s+receive[^\n.]*[.\n]?", ""),
        (r"to\s+stop\s+receiving\s+these\s+emails[^\n.]*[.\n]?", ""),
        (r"this\s+email\s+was\s+sent\s+to[^\n.]*[.\n]?", ""),
        (r"\d{1,5}\s+[A-Z][a-z]+\s+(Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd"
         r"|Drive|Dr|Lane|Ln|Suite|Ste)\b[^\n]*\d{5}(-\d{4})?", ""),
        (r"\(\s*\)", ""),
    ]
    # Subject/sender get the URL and header rules but NOT the body-artifact ones
    # (base64/CSS would mangle a legitimate subject line).
    _HEADER_PATTERNS = _BODY_PATTERNS[0:10] + _BODY_PATTERNS[16:]

    # Instruction-shaped text. The push path only ASKS the model to ignore this;
    # here it is removed. Names the specific tools worth hijacking.
    _NEUTER = [
        # Whole words only — a character-count window bites into the next word
        # and leaves debris ("...and call" -> "ll") in otherwise benign mail.
        r"ignore\s+(all\s+)?(previous|prior)(\s+\w+){0,3}",
        r"disregard(\s+\w+){0,4}\s+(instructions|above)",
        r"new\s+instructions",
        r"system\s+prompt",
        r"you\s+are\s+now",
        r"execute_service",
        r"memory_tool",
        r"save_user_preference",
        r"handoff_agent",
        r"call\s+the\s+(function|tool)",
        r"\bassistant\s*:",
    ]
    # Secrets are REMOVED, not merely "not read aloud".
    _REDACT = [
        r"(?:code|otp|pin|verification|código)\D{0,20}\b\d{4,8}\b",
        r"\b(?:\d[ -]?){13,19}\b",
        r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b",
        r"password\s*[:=]\s*\S+",
    ]
    # `[` is a control token in this codebase (assist_tts_reroute keys on a
    # leading bracket; tts_queue skips mood injection when one is present), so
    # attacker brackets must not survive.
    _ESCAPE = [("<", "‹"), (">", "›"), ("[", "⟦"), ("]", "⟧")]

    def _scrub(text, full, cap):
        if not text:
            return ""
        out = str(text)
        patterns = _BODY_PATTERNS if full else _HEADER_PATTERNS
        for pat, repl in patterns:
            out = _re.sub(pat, repl, out, flags=_re.IGNORECASE | _re.MULTILINE)
        for pat in _NEUTER:
            out = _re.sub(pat, "▮", out, flags=_re.IGNORECASE)
        for pat in _REDACT:
            out = _re.sub(pat, "▮▮▮▮", out, flags=_re.IGNORECASE)
        for src, dst in _ESCAPE:
            out = out.replace(src, dst)
        out = _re.sub(r"\s+", " ", out).strip()
        if cap and len(out) > cap:
            out = out[:cap].rstrip() + "…"
        return out

    def _decode(raw):
        if not raw:
            return ""
        try:
            return str(_make_header(_decode_header(raw)))
        except Exception:
            return str(raw)

    def _split_sender(raw):
        """'John Doe <j@x.com>' -> ('John Doe', 'j@x.com'). Mirrors
        email_promote.py:150-183 so both paths name senders identically."""
        if not raw:
            return ("unknown", "")
        raw = raw.strip()
        m = _re.match(r'^"?([^"<]*)"?\s*<([^>]+)>', raw)
        if m:
            name = m.group(1).strip().strip('"')
            addr = m.group(2).strip().lower()
            return (name or addr.split("@")[0], addr)
        m = _re.match(r"^<([^>]+)>", raw)
        if m:
            addr = m.group(1).strip().lower()
            return (addr.split("@")[0], addr)
        if "@" in raw:
            addr = raw.strip().lower()
            return (addr.split("@")[0], addr)
        return (raw, "")

    def _csv(value):
        out = []
        for item in str(value or "").split(","):
            item = item.strip().lower()
            if item:
                out.append(item)
        return out

    def _alias_map(csv_text):
        """"Key=Value" pairs, matched case-insensitively against display name or
        address. Same shape as notification_replay's sender_aliases input."""
        out = {}
        for entry in str(csv_text or "").split(","):
            if "=" not in entry:
                continue
            key, val = entry.split("=", 1)
            key = key.strip().lower()
            val = val.strip()
            if key and val:
                out[key] = val
        return out

    def _known_contact(addr, domain, contacts):
        """Same matching as email_promote.py:195-222 (exact, domain, suffix)."""
        for c in contacts:
            if c == addr:
                return True
            if "@" not in c and c and c == domain:
                return True
            if "@" not in c and c and domain.endswith("." + c):
                return True
        return False

    def _first_hit(haystack, needles):
        for n in needles:
            if n and n in haystack:
                return n
        return ""

    def _since_date(days):
        t = _time.localtime(_time.time() - (days * 86400))
        return "%02d-%s-%04d" % (t.tm_mday, _MONTHS[t.tm_mon - 1], t.tm_year)

    def _html_to_text(html):
        out = _re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
        out = _re.sub(r"(?i)<br\s*/?>", "\n", out)
        out = _re.sub(r"(?i)</p>", "\n", out)
        out = _re.sub(r"<[^>]+>", " ", out)
        out = out.replace("&nbsp;", " ").replace("&amp;", "&")
        out = out.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
        return out

    # ---- connect ---------------------------------------------------------
    mode = opts.get("mode", "summary")
    limit = opts.get("limit", 8)
    days = opts.get("days_back", 7)

    ctx = _ssl.create_default_context()
    if not cfg.get("verify_ssl", True):
        ctx.check_hostname = False
        ctx.verify_mode = _ssl.CERT_NONE

    started = _time.time()
    imap = None
    try:
        try:
            imap = _imaplib.IMAP4_SSL(
                cfg["server"], int(cfg.get("port") or 993),
                ssl_context=ctx, timeout=opts.get("timeout", 15),
            )
        except Exception as exc:
            return {"status": "error", "error": "connect failed: %s" % type(exc).__name__}

        try:
            imap.login(cfg["username"], cfg["password"])
        except Exception as exc:
            # Never surface the exception text: imaplib echoes the tagged
            # command, which contains the password.
            return {"status": "error", "error": "login failed: %s" % type(exc).__name__}

        caps = []
        for c in (imap.capabilities or ()):
            caps.append(str(c).upper())
        gmail = ("X-GM-EXT-1" in caps) and not opts.get("force_generic", False)
        flavour = "gmail" if gmail else "generic"

        folder = cfg.get("folder") or "INBOX"
        # READ-ONLY. Do not change this without re-reading the module docstring.
        typ, _ = imap.select(folder, readonly=True)
        if typ != "OK":
            return {"status": "error", "error": "cannot select folder"}

        total = 0
        unread = 0
        try:
            typ, sdata = imap.status(folder, "(MESSAGES UNSEEN)")
            if typ == "OK" and sdata:
                line = sdata[0].decode("utf-8", "replace")
                m = _re.search(r"MESSAGES\s+(\d+)", line)
                if m:
                    total = int(m.group(1))
                m = _re.search(r"UNSEEN\s+(\d+)", line)
                if m:
                    unread = int(m.group(1))
        except Exception:
            pass

        # ---- search ------------------------------------------------------
        def _uid_search(args):
            try:
                typ, data = imap.uid("SEARCH", *args)
            except Exception:
                return None
            if typ != "OK" or not data or data[0] is None:
                return None
            return data[0].split()

        def _gm(raw_query):
            return _uid_search([None, "X-GM-RAW", '"%s"' % raw_query.replace('"', "'")])

        def _run_search(window):
            """Returns (uids, description). Gmail first, generic on any failure."""
            since = _since_date(window)
            q = str(opts.get("query") or "").strip()
            if gmail:
                if mode == "unread":
                    raw = "is:unread in:inbox"
                elif mode == "important":
                    raw = ("(is:important OR is:starred OR is:unread) "
                           "newer_than:%dd" % window)
                elif mode == "search":
                    raw = "%s newer_than:%dd" % (q, window)
                else:
                    raw = ("in:inbox newer_than:%dd -category:promotions "
                           "-category:social" % window)
                found = _gm(raw)
                if found is not None:
                    return (found, 'X-GM-RAW "%s"' % raw)
                # Some proxies advertise X-GM-EXT-1 and then reject the search.

            if mode == "unread":
                crit = [[None, "UNSEEN"]]
                desc = "UNSEEN"
            elif mode == "important":
                crit = [[None, "FLAGGED"], [None, "UNSEEN", "SINCE", since]]
                desc = "FLAGGED + (UNSEEN SINCE %s)" % since
            elif mode == "search":
                crit = [[None, "SINCE", since, "FROM", '"%s"' % q],
                        [None, "SINCE", since, "SUBJECT", '"%s"' % q]]
                desc = 'SINCE %s (FROM|SUBJECT "%s")' % (since, q)
            else:
                crit = [[None, "SINCE", since]]
                desc = "SINCE %s" % since

            merged = []
            seen_uids = {}
            for args in crit:
                got = _uid_search(args)
                if not got:
                    continue
                for u in got:
                    key = u.decode() if isinstance(u, bytes) else str(u)
                    if key not in seen_uids:
                        seen_uids[key] = True
                        merged.append(u)
            return (merged, desc)

        if mode == "detail":
            uids = [opts.get("uid", "").encode()]
            search_used = "UID FETCH %s" % opts.get("uid", "")
            widened = False
            window = days
        else:
            window = days
            uids, search_used = _run_search(window)
            widened = False
            # One widening retry only. This inbox archives aggressively, so a
            # literal answer of "nothing" is usually wrong rather than useful.
            if not uids and mode != "unread":
                window = min(days * 4, opts.get("max_days", 30))
                if window > days:
                    uids, search_used = _run_search(window)
                    widened = True

        if not uids or not uids[0]:
            return {
                "status": "empty", "flavour": flavour, "folder": folder,
                "total": total, "unread": unread, "search_used": search_used,
                "window_days": window, "widened": widened, "messages": [],
                "latency_ms": int((_time.time() - started) * 1000),
            }

        # ---- fetch headers ----------------------------------------------
        # Over-fetch so client-side ranking has something to rank, then slice.
        pool = uids[-(limit * 3):]
        idset = b",".join(pool).decode()
        items = "(UID FLAGS BODYSTRUCTURE BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])"
        if gmail:
            items = ("(UID FLAGS X-GM-LABELS BODYSTRUCTURE "
                     "BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
        try:
            typ, raw = imap.uid("FETCH", idset, items)
        except Exception as exc:
            return {"status": "error", "error": "fetch failed: %s" % type(exc).__name__}
        if typ != "OK":
            return {"status": "error", "error": "fetch rejected"}

        contacts = _csv(opts.get("contacts_csv"))
        aliases = _alias_map(opts.get("aliases_csv"))
        priority_kw = _csv(opts.get("priority_csv"))
        blocked_senders = _csv(opts.get("blocked_senders_csv"))
        blocked_kw = _csv(opts.get("blocked_kw_csv"))
        preview_cap = opts.get("preview_chars", 120)

        now_ts = _time.time()
        rows = []
        for part in raw:
            if not isinstance(part, tuple) or len(part) < 2:
                continue
            prefix = part[0].decode("utf-8", "replace") if part[0] else ""
            msg = _email.message_from_bytes(part[1])

            m = _re.search(r"UID\s+(\d+)", prefix)
            uid = m.group(1) if m else ""
            m = _re.search(r"FLAGS\s+\(([^)]*)\)", prefix)
            flags = (m.group(1) if m else "").lower()
            m = _re.search(r"X-GM-LABELS\s+\(([^)]*)\)", prefix)
            labels = (m.group(1) if m else "").lower()

            raw_from = _decode(msg.get("From", ""))
            name, addr = _split_sender(raw_from)
            domain = addr.split("@", 1)[1] if "@" in addr else ""
            subject_raw = _decode(msg.get("Subject", ""))

            if addr and addr in blocked_senders:
                continue
            if domain and domain in blocked_senders:
                continue
            hit_blocked = _first_hit(subject_raw.lower(), blocked_kw)
            if hit_blocked:
                continue

            date_raw = msg.get("Date", "")
            age_hours = -1
            iso = ""
            try:
                from email.utils import parsedate_to_datetime as _pdt
                dt = _pdt(date_raw)
                iso = dt.isoformat()
                age_hours = int((now_ts - dt.timestamp()) / 3600)
            except Exception:
                iso = str(date_raw)

            is_unread = "\\seen" not in flags
            is_flagged = "\\flagged" in flags
            is_important = "important" in labels or "starred" in labels
            known = _known_contact(addr, domain, contacts)
            kw_hit = _first_hit(subject_raw.lower(), priority_kw)

            score = 0
            if is_unread:
                score += 3
            if is_flagged:
                score += 2
            if is_important:
                score += 2
            if known:
                score += 3
            if kw_hit:
                score += 2

            # A matched alias is user-configured (trusted), so it is used
            # verbatim; only an unmatched, sender-supplied name gets scrubbed.
            alias = aliases.get(name.strip().lower()) or aliases.get(addr)

            rows.append({
                "_uid": uid,
                "from_name": alias if alias else _scrub(name, False, 80),
                "from_address": _scrub(addr, False, 120),
                "subject": _scrub(subject_raw, False, 200) or "(no subject)",
                "date": iso,
                "age_hours": age_hours,
                "unread": is_unread,
                "flagged": is_flagged,
                "important": is_important,
                "has_attachments": "attachment" in prefix.lower(),
                "known_contact": known,
                "matched_keyword": kw_hit,
                "score": score,
                "preview": "",
            })

        rows.sort(key=lambda r: (r["score"], r["date"]), reverse=True)
        truncated = len(rows) > limit
        rows = rows[:limit]

        # ---- optional single body ---------------------------------------
        body_text = ""
        if mode == "detail" and opts.get("include_body") and rows:
            try:
                typ, braw = imap.uid("FETCH", rows[0]["_uid"], "(BODY.PEEK[])")
                if typ == "OK":
                    for part in braw:
                        if not isinstance(part, tuple) or len(part) < 2:
                            continue
                        full = _email.message_from_bytes(part[1])
                        chosen = ""
                        html = ""
                        if full.is_multipart():
                            for sub in full.walk():
                                ctype = sub.get_content_type()
                                if sub.get_filename():
                                    continue
                                try:
                                    payload = sub.get_payload(decode=True)
                                except Exception:
                                    continue
                                if not payload:
                                    continue
                                cs = sub.get_content_charset() or "utf-8"
                                txt = payload.decode(cs, "replace")
                                if ctype == "text/plain" and not chosen:
                                    chosen = txt
                                elif ctype == "text/html" and not html:
                                    html = txt
                        else:
                            payload = full.get_payload(decode=True) or b""
                            cs = full.get_content_charset() or "utf-8"
                            chosen = payload.decode(cs, "replace")
                        if not chosen and html:
                            chosen = _html_to_text(html)
                        body_text = _scrub(chosen, True, opts.get("body_chars", 600))
                        break
            except Exception:
                body_text = ""

        # A preview is a scrubbed slice of the same body, so it costs a fetch.
        # Only worth it for small result sets; subjects alone answer most asks.
        if preview_cap and mode != "detail" and len(rows) <= 5:
            for row in rows:
                try:
                    typ, braw = imap.uid("FETCH", row["_uid"], "(BODY.PEEK[TEXT])")
                except Exception:
                    continue
                if typ != "OK":
                    continue
                for part in braw:
                    if not isinstance(part, tuple) or len(part) < 2:
                        continue
                    # BODY.PEEK[TEXT] is the raw payload, still in its transfer
                    # encoding — unlike the detail path, which gets decoding for
                    # free from get_payload(decode=True). Without this, curly
                    # quotes and accents surface as "I=E2=80=99ll".
                    chunk_bytes = part[1][:8192]
                    if _re.search(rb"=[0-9A-Fa-f]{2}", chunk_bytes):
                        try:
                            chunk_bytes = _quopri.decodestring(chunk_bytes)
                        except Exception:
                            pass
                    chunk = chunk_bytes.decode("utf-8", "replace")
                    if "<" in chunk and ">" in chunk:
                        chunk = _html_to_text(chunk)
                    row["preview"] = _scrub(chunk, True, preview_cap)
                    break

        return {
            "status": "ok" if rows else "empty",
            "flavour": flavour,
            "folder": folder,
            "total": total,
            "unread": unread,
            "search_used": search_used,
            "window_days": window,
            "widened": widened,
            "truncated": truncated,
            "messages": rows,
            "body": body_text,
            "latency_ms": int((_time.time() - started) * 1000),
        }
    finally:
        if imap is not None:
            try:
                imap.close()
            except Exception:
                pass
            try:
                imap.logout()
            except Exception:
                pass


@pyscript_executor  # noqa: F821
def _imap_probe(cfg, timeout):
    """Connectivity probe. Selects read-only and touches no message."""
    import imaplib as _imaplib
    import re as _re
    import ssl as _ssl
    import time as _time

    ctx = _ssl.create_default_context()
    if not cfg.get("verify_ssl", True):
        ctx.check_hostname = False
        ctx.verify_mode = _ssl.CERT_NONE

    started = _time.time()
    imap = None
    try:
        imap = _imaplib.IMAP4_SSL(
            cfg["server"], int(cfg.get("port") or 993),
            ssl_context=ctx, timeout=timeout,
        )
        imap.login(cfg["username"], cfg["password"])
        caps = []
        for c in (imap.capabilities or ()):
            caps.append(str(c).upper())
        folder = cfg.get("folder") or "INBOX"
        typ, _ = imap.select(folder, readonly=True)
        if typ != "OK":
            return {"ok": False, "error": "cannot select %s" % folder}
        total = 0
        unread = 0
        typ, sdata = imap.status(folder, "(MESSAGES UNSEEN)")
        if typ == "OK" and sdata:
            line = sdata[0].decode("utf-8", "replace")
            m = _re.search(r"MESSAGES\s+(\d+)", line)
            if m:
                total = int(m.group(1))
            m = _re.search(r"UNSEEN\s+(\d+)", line)
            if m:
                unread = int(m.group(1))
        return {
            "ok": True,
            "flavour": "gmail" if "X-GM-EXT-1" in caps else "generic",
            "folder": folder,
            "total": total,
            "unread": unread,
            "latency_ms": int((_time.time() - started) * 1000),
            "error": "",
        }
    except Exception as exc:
        # Type name only — imaplib can echo the login command, password included.
        return {"ok": False, "error": type(exc).__name__,
                "latency_ms": int((_time.time() - started) * 1000)}
    finally:
        if imap is not None:
            try:
                imap.close()
            except Exception:
                pass
            try:
                imap.logout()
            except Exception:
                pass


# ── Services ─────────────────────────────────────────────────────────────────

@service(supports_response="only")  # noqa: F821
async def email_inbox_query(
    mode: str = "summary",
    query: str = "",
    handle: str = "",
    days_back: int = 7,
    limit: int = 8,
    include_body: bool = False,
    body_chars: int = 600,
    preview_chars: int = 120,
    detail_level: str = "full",
    sender_aliases: str = "",
    current_count: int = -1,
    account: str = "",
    force_generic: bool = False,
):
    """Answer a question about the inbox. Read-only; nothing is marked seen.

    mode          summary | unread | important | search | detail | clear
    query         search text (mode=search)
    handle        opaque handle from a previous result (mode=detail)
    detail_level  full | senders_only — senders_only drops subjects/previews and
                  is what the privacy gate asks for rather than going silent

    Returns a dict whose attacker-controlled strings live only under
    "messages"/"body". Never returns credentials.
    """
    global _cache, _inflight, _last_login

    started = time.time()
    mode = str(mode or "summary").strip().lower()
    if mode not in VALID_MODES:
        mode = "summary"

    if not _helper_str("input_boolean.ai_email_master_toggle", "on") == "on":
        return {"status": "disabled", "mode": mode, "messages": [],
                "hint": "email features are switched off"}

    # mode=clear folds in the old email_clear_count tool so the agents keep a
    # single email verb. The underlying service is untouched, and current_count
    # is passed straight through: email_promote uses it to detect AP-82 tool
    # pretense (an agent "clearing" a counter it never actually read).
    if mode == "clear":
        try:
            call = pyscript.email_clear_count(current_count=current_count)  # noqa: F821
            resp = await call
        except Exception:
            _set_result("error", op="clear", error="clear failed")
            return {"status": "error", "mode": "clear", "messages": [],
                    "error": "could not clear the counter"}
        before = 0
        if isinstance(resp, dict):
            before = resp.get("count_before", 0)
        _set_result("ok", op="clear", count_before=before)
        return {"status": "ok", "mode": "clear", "count_before": before,
                "messages": [], "_untrusted": False}

    limit = _clamp(limit, 1, MAX_LIMIT, 8)
    days_back = _clamp(days_back, 1, MAX_DAYS_BACK, 7)
    body_chars = _clamp(body_chars, 80, MAX_BODY_CHARS, 600)
    preview_chars = _clamp(preview_chars, 0, MAX_PREVIEW_CHARS, 120)
    senders_only = str(detail_level or "full").strip().lower() == "senders_only"
    if senders_only:
        preview_chars = 0
        include_body = False

    uid = ""
    if mode == "detail":
        try:
            uid = _resolve_handle(handle)
        except Exception as exc:
            uid = ""
            log.warning(  # noqa: F821
                f"email_reader: handle lookup failed ({type(exc).__name__}: {exc})"
            )
        if not uid:
            return {"status": "error", "mode": mode, "messages": [],
                    "error": "unknown handle",
                    "hint": "that message reference expired - ask for the inbox "
                            "again, then request the message you want"}

    cfg = _imap_config(account)
    if not cfg:
        _set_result("error", op=mode, error="no imap config entry")
        return {"status": "error", "mode": mode, "messages": [],
                "error": "no imap account configured"}

    # detail_level MUST be part of the key: without it a privacy-degraded call
    # could be served a cached full-detail result and leak subjects. Aliases
    # change the rendered sender, so they belong here too.
    cache_key = "|".join([mode, query or "", str(days_back), str(limit),
                          str(preview_chars), uid, str(force_generic),
                          "senders_only" if senders_only else "full",
                          str(sender_aliases or "")])
    now = time.time()
    cached = _cache.get(cache_key)
    if cached and (now - cached["at"]) < CACHE_TTL:
        out = dict(cached["result"])
        out["cached"] = True
        return out

    # Single-flight: a chatty agent can call twice in one turn, and stacking
    # logins risks Gmail's connection cap (which can make HA's own coordinator
    # reconnect and re-fire imap_content — a duplicate spoken announcement).
    if _inflight:
        if cached:
            out = dict(cached["result"])
            out["cached"] = True
            return out
        return {"status": "error", "mode": mode, "messages": [],
                "error": "busy", "hint": "still reading the inbox, ask again"}

    gap = now - _last_login
    if gap < MIN_LOGIN_INTERVAL:
        task.sleep(MIN_LOGIN_INTERVAL - gap)  # noqa: F821

    opts = {
        "mode": mode,
        "query": str(query or "").strip(),
        "uid": uid,
        "days_back": days_back,
        "max_days": MAX_DAYS_BACK,
        "limit": limit,
        "include_body": bool(include_body),
        "body_chars": body_chars,
        "preview_chars": preview_chars,
        "force_generic": bool(force_generic),
        "timeout": IMAP_TIMEOUT,
        "aliases_csv": str(sender_aliases or ""),
        "contacts_csv": _helper_str("input_text.ai_email_known_contacts", ""),
        "priority_csv": _helper_str("input_text.ai_email_priority_keywords", ""),
        "blocked_senders_csv": _helper_str("input_text.ai_email_blocked_senders", ""),
        "blocked_kw_csv": _helper_str("input_text.ai_email_blocked_keywords", ""),
    }

    _inflight = True
    try:
        raw = await _imap_run(cfg, opts)
    except Exception as exc:
        _set_result("error", op=mode, error=type(exc).__name__)
        return {"status": "error", "mode": mode, "messages": [],
                "error": "inbox unreachable"}
    finally:
        _inflight = False
        _last_login = time.time()

    if raw.get("status") == "error":
        _set_result("error", op=mode, error=raw.get("error", ""))
        return {"status": "error", "mode": mode, "messages": [],
                "error": raw.get("error", "inbox unreachable")}

    rows = raw.get("messages") or []
    uids = []
    for row in rows:
        uids.append(row.get("_uid", ""))
    handle_map = _next_handles(uids)

    messages = []
    payload_chars = 0
    truncated = bool(raw.get("truncated"))
    for row in rows:
        item = {
            "handle": handle_map.get(row.get("_uid", ""), ""),
            "from_name": row.get("from_name", ""),
            "from_address": row.get("from_address", ""),
            "date": row.get("date", ""),
            "age_hours": row.get("age_hours", -1),
            "unread": row.get("unread", False),
            "flagged": row.get("flagged", False),
            "important": row.get("important", False),
            "has_attachments": row.get("has_attachments", False),
            "known_contact": row.get("known_contact", False),
            "score": row.get("score", 0),
        }
        if senders_only:
            # Privacy degrade: who wrote, not what they said.
            item["subject"] = ""
            item["preview"] = ""
        else:
            item["subject"] = row.get("subject", "")
            item["preview"] = row.get("preview", "")
            item["matched_keyword"] = row.get("matched_keyword", "")
        payload_chars += len(str(item))
        if payload_chars > MAX_PAYLOAD_CHARS:
            truncated = True
            break
        messages.append(item)

    hint = ""
    if not messages:
        hint = ("nothing in the last %d days in %s; %d message(s) in the folder, "
                "%d unread — this account archives aggressively, so an empty "
                "inbox is normal" % (raw.get("window_days", days_back),
                                     raw.get("folder", "INBOX"),
                                     raw.get("total", 0), raw.get("unread", 0)))

    result = {
        "status": raw.get("status", "ok"),
        "mode": mode,
        "account": cfg.get("_title", ""),
        "server_flavour": raw.get("flavour", ""),
        "search_used": raw.get("search_used", ""),
        "window_days": raw.get("window_days", days_back),
        "widened": raw.get("widened", False),
        "total_in_folder": raw.get("total", 0),
        "unread_count": raw.get("unread", 0),
        "returned": len(messages),
        "truncated": truncated,
        "cached": False,
        "detail_level": "senders_only" if senders_only else "full",
        "_untrusted": True,
        "messages": messages,
        "body": "" if senders_only else raw.get("body", ""),
        "hint": hint,
        "error": "",
    }

    _cache[cache_key] = {"at": time.time(), "result": result}
    _set_result(
        "ok", op=mode, returned=len(messages), unread=raw.get("unread", 0),
        total=raw.get("total", 0), flavour=raw.get("flavour", ""),
        widened=raw.get("widened", False),
        latency_ms=raw.get("latency_ms", 0),
        elapsed_ms=int((time.time() - started) * 1000),
    )
    return result


@service(supports_response="only")  # noqa: F821
async def email_inbox_health(account: str = ""):
    """Probe IMAP connectivity. Marks nothing seen; returns no credentials."""
    cfg = _imap_config(account)
    if not cfg:
        _set_result("error", op="health", error="no imap config entry")
        return {"ok": False, "error": "no imap account configured"}

    try:
        out = await _imap_probe(cfg, IMAP_TIMEOUT)
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__}

    out["account"] = cfg.get("_title", "")
    _set_result("ok" if out.get("ok") else "error", op="health",
                flavour=out.get("flavour", ""), unread=out.get("unread", 0),
                total=out.get("total", 0), latency_ms=out.get("latency_ms", 0),
                error=out.get("error", ""))
    return out


@time_trigger("startup")  # noqa: F821
def email_reader_startup():
    """Seed the status sensor. Deliberately does NOT open IMAP — email_promote
    already reloads the imap config entry at startup, and a second connection
    there would add to Gmail's connection pressure at the worst moment."""
    _ensure_result_entity_name(force=True)
    _set_result("idle", op="", returned=0)
