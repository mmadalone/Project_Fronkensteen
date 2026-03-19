"""Email Priority Filter — Task 18b of Voice Context Architecture.

Filters incoming IMAP emails and promotes only priority messages to L2
memory. Matches sender against known contacts and subject against priority
keywords; urgent matches also trigger TTS announcements via dedup_announce.
Exposes pyscript.email_promote_process and pyscript.email_clear_count.
"""
import re
import time
from typing import Any

from shared_utils import (
    build_result_entity_name,
    get_person_config,
    get_person_slugs,
    load_entity_config,
)

# =============================================================================
# Email Priority Filter — Task 18b of Voice Context Architecture
# =============================================================================
# Filters incoming IMAP emails and promotes only priority messages to L2 memory.
# High-volume inbox filtering: only known contacts and keyword matches get
# through. Everything else is filtered OUT — never promoted.
#
# Services:
#   pyscript.email_promote_process
#     Process an incoming email through priority filter. Called by automation
#     on imap_content event. Checks sender against known contacts, subject
#     against priority keywords. Priority emails → L2 memory + counter.
#     Urgent emails → L2 + TTS announcement via dedup_announce.
#
#   pyscript.email_clear_count
#     Reset priority email counter to zero. Called when user says "I've read
#     my emails" or by morning briefing after reading the count.
#
# Key design:
#   - Aggressive filtering: only known contacts + keyword matches promoted
#   - Privacy: sender + subject only — NEVER store email body in L2
#   - User-scoped: all L2 keys include ":miquel:" (per-user)
#   - Identity gate: suppressed entirely when confidence < 70%
#   - Configurable: contacts and keywords in input_text helpers
#   - Test mode: log filter decisions, no L2 writes or TTS
#   - Urgent TTS via dedup_announce: prevents duplicate announcements
#   - Urgent TTS routed through persona LLM for in-character delivery
#
# Dependencies:
#   - pyscript/memory.py (L2: memory_set, memory_get)
#   - pyscript/notification_dedup.py (dedup_announce for urgent TTS)
#   - pyscript/agent_dispatcher.py (agent_dispatch for persona routing)
#   - packages/ai_email_promotion.yaml (helpers + automation trigger)
#   - packages/ai_test_harness.yaml (test mode toggle)
#   - packages/ai_identity.yaml (identity confidence sensors)
#   - packages/ai_llm_budget.yaml (LLM budget gate)
#   - IMAP integration (sensor.gmail_messages)
#
# Deployed: 2026-03-02 | Pipeline-aware: 2026-03-02
# =============================================================================

RESULT_ENTITY = "sensor.ai_email_promotion_status"

# Built-in fallback priority keywords (always checked alongside user-defined)
_FALLBACK_PRIORITY_KEYWORDS = [
    "shipping", "delivery", "appointment", "urgent", "invoice",
    "confirmation", "password reset", "security alert", "payment", "receipt",
]

# Fallback urgent keywords (subset of priority — trigger TTS announcement)
_FALLBACK_URGENT_KEYWORDS = [
    "urgent", "security alert", "password reset", "immediate",
]

EMAIL_ANNOUNCE_PROMPT = (
    "Announce this urgent email notification in one or two sentences, "
    "in your personality. Be brief — this is a quick heads-up, not a "
    "conversation. Here is the info: {text}"
)

result_entity_name: dict[str, str] = {}


# ── Helper Utilities ─────────────────────────────────────────────────────────

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


def _get_priority_keywords():
    csv = _helper_str("input_text.ai_email_priority_keywords", "")
    if csv:
        return [k.strip() for k in csv.split(",") if k.strip()]
    return _FALLBACK_PRIORITY_KEYWORDS


def _get_urgent_keywords():
    csv = _helper_str("input_text.ai_email_urgent_keywords", "")
    if csv:
        return [k.strip() for k in csv.split(",") if k.strip()]
    return _FALLBACK_URGENT_KEYWORDS


# ── Entity Name Helpers (standard pattern) ───────────────────────────────────

def _ensure_result_entity_name(force: bool = False) -> None:
    global result_entity_name
    if force or not result_entity_name:
        result_entity_name = build_result_entity_name(RESULT_ENTITY)


def _set_result(state_value: str = "ok", **attrs: Any) -> None:
    _ensure_result_entity_name()
    attrs.update(result_entity_name)
    state.set(RESULT_ENTITY, value=state_value, new_attributes=attrs)  # noqa: F821


def _check_test_mode() -> bool:
    try:
        return str(state.get("input_boolean.ai_test_mode") or "off").lower() == "on"  # noqa: F821
    except NameError:
        return False


# ── Pure-Python Sync Helpers ─────────────────────────────────────────────────

@pyscript_compile  # noqa: F821
def _extract_sender_parts(sender_raw: str) -> tuple:
    """Extract name and email from sender field.

    "John Doe <john@example.com>" → ("John Doe", "john@example.com")
    "<john@example.com>" → ("john", "john@example.com")
    "john@example.com" → ("john", "john@example.com")
    """
    if not sender_raw:
        return ("unknown", "unknown@unknown")

    sender_raw = sender_raw.strip()

    # Pattern: "Name <email>" or "Name" <email>
    match = re.match(r'^"?([^"<]*)"?\s*<([^>]+)>', sender_raw)
    if match:
        name = match.group(1).strip().strip('"')
        email = match.group(2).strip().lower()
        if not name:
            name = email.split("@")[0]
        return (name, email)

    # Pattern: <email>
    match = re.match(r"^<([^>]+)>", sender_raw)
    if match:
        email = match.group(1).strip().lower()
        return (email.split("@")[0], email)

    # Pattern: bare email
    if "@" in sender_raw:
        email = sender_raw.strip().lower()
        return (email.split("@")[0], email)

    return (sender_raw, "unknown@unknown")


@pyscript_compile  # noqa: F821
def _extract_domain(email: str) -> str:
    """Extract domain from email address."""
    if "@" in email:
        return email.split("@", 1)[1].lower()
    return ""


@pyscript_compile  # noqa: F821
def _check_contacts(
    sender_email: str, sender_domain: str, contacts_csv: str,
) -> bool:
    """Check if sender email or domain matches known contacts list.

    contacts_csv is comma-separated. Can contain full emails or domains:
    "mom@gmail.com, amazon.com, boss@work.com"
    """
    if not contacts_csv or not contacts_csv.strip():
        return False

    sender_email_lower = sender_email.lower()
    sender_domain_lower = sender_domain.lower()

    contacts = [c.strip().lower() for c in contacts_csv.split(",") if c.strip()]

    for contact in contacts:
        # Exact email match
        if contact == sender_email_lower:
            return True
        # Domain match (contact is just a domain like "amazon.com")
        if "@" not in contact and contact == sender_domain_lower:
            return True
        # Domain suffix match ("amazon.com" matches "email.amazon.com")
        if "@" not in contact and sender_domain_lower.endswith("." + contact):
            return True

    return False


@pyscript_compile  # noqa: F821
def _check_keywords(
    subject: str, default_kw: list, custom_csv: str,
) -> tuple:
    """Check subject against priority keywords.

    Returns (is_match, matched_keyword).
    Checks built-in defaults + user-defined custom keywords.
    """
    if not subject:
        return (False, "")

    subject_lower = subject.lower()

    # Check built-in keywords
    for kw in default_kw:
        if kw in subject_lower:
            return (True, kw)

    # Check custom keywords from helper
    if custom_csv and custom_csv.strip():
        customs = [c.strip().lower() for c in custom_csv.split(",") if c.strip()]
        for kw in customs:
            if kw in subject_lower:
                return (True, kw)

    return (False, "")


@pyscript_compile  # noqa: F821
def _check_urgent(subject: str, urgent_kw: list) -> tuple:
    """Check if subject contains urgent keywords.

    Returns (is_urgent, matched_keyword).
    """
    if not subject:
        return (False, "")

    subject_lower = subject.lower()

    for kw in urgent_kw:
        if kw in subject_lower:
            return (True, kw)

    return (False, "")


@pyscript_compile  # noqa: F821
def _check_blocked_keywords(subject: str, blocked_csv: str) -> tuple:
    """Check if subject contains any blocked keywords.

    Returns (is_blocked, matched_keyword).
    """
    if not subject or not blocked_csv or not blocked_csv.strip():
        return (False, "")

    subject_lower = subject.lower()
    blocked = [k.strip().lower() for k in blocked_csv.split(",") if k.strip()]

    for kw in blocked:
        if kw in subject_lower:
            return (True, kw)

    return (False, "")


@pyscript_compile  # noqa: F821
def _make_slug(text: str, max_len: int = 30) -> str:
    """Create a short slug for dedup topic keys."""
    if not text:
        return "unknown"
    t = text.lower().strip()
    t = re.sub(r"[^\w\s]", "", t)
    t = re.sub(r"\s+", "_", t)
    t = t.strip("_")
    if len(t) > max_len:
        t = t[:max_len].rstrip("_")
    return t or "unknown"


@pyscript_compile  # noqa: F821
def _extract_speech_from_response(resp: dict) -> str:
    """Extract speech text from conversation.process response dict."""
    if not resp or not isinstance(resp, dict):
        return ""
    response = resp.get("response")
    if not isinstance(response, dict):
        return ""
    speech = response.get("speech")
    if not isinstance(speech, dict):
        return ""
    plain = speech.get("plain")
    if not isinstance(plain, dict):
        return ""
    return plain.get("speech", "")


# ── L2 Memory Helpers ────────────────────────────────────────────────────────

async def _l2_set(
    key: str, value: str, tags: str,
    scope: str = "user", expiration_days: int = 3,
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
        log.warning(f"email_promote: L2 set failed key={key}: {exc}")  # noqa: F821
        return False


# ── Counter + Helper Updates ─────────────────────────────────────────────────

def _get_email_count() -> int:
    """Read current priority email count from helper."""
    try:
        return int(float(
            state.get("input_number.ai_email_priority_count") or 0  # noqa: F821
        ))
    except (TypeError, ValueError, NameError):
        return 0


def _set_email_count(count: int) -> None:
    """Set priority email count on helper."""
    try:
        service.call(  # noqa: F821
            "input_number", "set_value",
            entity_id="input_number.ai_email_priority_count",
            value=max(0, min(999, count)),
        )
    except Exception as exc:
        log.warning(f"email_promote: counter update failed: {exc}")  # noqa: F821


def _update_last_priority(subject: str) -> None:
    """Update last priority email subject helper."""
    try:
        service.call(  # noqa: F821
            "input_text", "set_value",
            entity_id="input_text.ai_email_last_priority",
            value=str(subject)[:255],
        )
    except Exception as exc:
        log.warning(f"email_promote: last priority update failed: {exc}")  # noqa: F821


def _set_email_stale(stale_val: bool) -> None:
    """Set or clear the email stale flag (Gap 2)."""
    try:
        svc = "turn_on" if stale_val else "turn_off"
        service.call(  # noqa: F821
            "input_boolean", svc,
            entity_id="input_boolean.ai_email_stale",
        )
    except Exception as exc:
        log.warning(f"email_promote: stale flag update failed: {exc}")  # noqa: F821


# ── LLM Budget Helpers ───────────────────────────────────────────────────────

def _get_budget_remaining() -> int:
    """Get LLM budget remaining percentage."""
    try:
        return int(float(
            state.get("sensor.ai_llm_budget_remaining") or "100"  # noqa: F821
        ))
    except (ValueError, TypeError, NameError):
        return 100


def _increment_llm_counter(cost: int = 1) -> None:
    """Increment LLM call counter after conversation.process."""
    try:
        current = int(float(
            state.get("input_number.ai_llm_calls_today") or 0  # noqa: F821
        ))
        service.call(  # noqa: F821
            "input_number", "set_value",
            entity_id="input_number.ai_llm_calls_today",
            value=min(current + cost, 999),
        )
    except Exception:
        pass


# ── Identity Check ───────────────────────────────────────────────────────────

def _resolve_person_from_imap(sensor_entity: str = "") -> str:
    """Resolve which person owns an IMAP sensor (Task 22).

    Checks get_person_config(slug, "imap_sensor") for each person.
    Falls back to first person if no match found.
    """
    if sensor_entity:
        for slug in get_person_slugs():
            if get_person_config(slug, "imap_sensor") == sensor_entity:
                return slug
    # Fallback: first person slug
    slugs = get_person_slugs()
    return slugs[0] if slugs else "miquel"


def _check_identity_confidence(person: str = "miquel") -> int:
    """Get identity confidence score for a person."""
    try:
        return int(float(
            state.get(f"sensor.identity_confidence_{person}") or 0  # noqa: F821
        ))
    except (TypeError, ValueError, NameError):
        return 0


# ── Core Processing Logic ───────────────────────────────────────────────────

async def _process_email(
    sender: str, subject: str, test_mode: bool, suppress_tts: str = "false",
    person: str = "miquel",
) -> dict[str, Any]:
    """Core email processing logic.

    1. Check identity confidence (privacy gate)
    2. Extract sender parts
    3. Check against known contacts
    4. Check against priority keywords
    5. If priority: write to L2, increment counter
    6. If urgent: also announce via TTS dedup (routed through persona LLM)
    """

    # ── Identity gate ──
    confidence = _check_identity_confidence(person)
    id_min = _helper_int("input_number.ai_identity_confidence_min", 70)
    if confidence < id_min:
        reason = f"low_confidence ({confidence}%)"
        if test_mode:
            log.info(  # noqa: F821
                f"email_promote [TEST]: SUPPRESSED {reason} "
                f"sender={sender} subject={subject}"
            )
        return {
            "status": "ok", "promoted": False,
            "reason": reason, "filter_result": "suppressed",
        }

    # ── Extract sender parts ──
    sender_name, sender_email = _extract_sender_parts(sender)
    sender_domain = _extract_domain(sender_email)

    # ── Get filter configuration from helpers ──
    try:
        filter_mode = str(
            state.get("input_select.ai_email_filter_mode") or "whitelist"  # noqa: F821
        ).lower()
    except NameError:
        filter_mode = "whitelist"

    try:
        contacts_csv = str(
            state.get("input_text.ai_email_known_contacts") or ""  # noqa: F821
        )
    except NameError:
        contacts_csv = ""

    try:
        custom_kw_csv = str(
            state.get("input_text.ai_email_priority_keywords") or ""  # noqa: F821
        )
    except NameError:
        custom_kw_csv = ""

    try:
        blocked_csv = str(
            state.get("input_text.ai_email_blocked_senders") or ""  # noqa: F821
        )
    except NameError:
        blocked_csv = ""

    try:
        blocked_kw_csv = str(
            state.get("input_text.ai_email_blocked_keywords") or ""  # noqa: F821
        )
    except NameError:
        blocked_kw_csv = ""

    # ── Priority check (mode-dependent) ──
    is_priority = False
    match_reason = "no_match"

    if filter_mode == "blacklist":
        # Blacklist: everything promoted EXCEPT blocked senders/keywords
        is_blocked = _check_contacts(
            sender_email, sender_domain, blocked_csv,
        )
        is_blocked_kw, blocked_kw_match = _check_blocked_keywords(
            subject, blocked_kw_csv,
        )
        if is_blocked:
            match_reason = f"blocked_sender ({sender_email})"
        elif is_blocked_kw:
            match_reason = f"blocked_keyword ({blocked_kw_match})"
        else:
            is_priority = True
            # Check contacts/keywords for reason labeling
            is_contact = _check_contacts(
                sender_email, sender_domain, contacts_csv,
            )
            is_keyword, matched_keyword = _check_keywords(
                subject, _get_priority_keywords(), custom_kw_csv,
            )
            if is_contact:
                match_reason = f"known_contact ({sender_email})"
            elif is_keyword:
                match_reason = f"keyword ({matched_keyword})"
            else:
                match_reason = "not_blocked (open filter)"
    elif filter_mode == "hybrid":
        # Hybrid: blocked senders/keywords filtered first, then only
        # contacts + keywords promoted. Unknown senders are filtered out.
        is_blocked = _check_contacts(
            sender_email, sender_domain, blocked_csv,
        )
        is_blocked_kw, blocked_kw_match = _check_blocked_keywords(
            subject, blocked_kw_csv,
        )
        if is_blocked:
            match_reason = f"blocked_sender ({sender_email})"
        elif is_blocked_kw:
            match_reason = f"blocked_keyword ({blocked_kw_match})"
        else:
            # Not blocked — check contacts + keywords (whitelist pass)
            is_contact = _check_contacts(
                sender_email, sender_domain, contacts_csv,
            )
            is_keyword, matched_keyword = _check_keywords(
                subject, _get_priority_keywords(), custom_kw_csv,
            )
            is_priority = is_contact or is_keyword
            if is_contact:
                match_reason = f"known_contact ({sender_email})"
            elif is_keyword:
                match_reason = f"keyword ({matched_keyword})"
            else:
                match_reason = "unknown_sender (hybrid filter)"
    else:
        # Whitelist: only contacts + keywords get through
        is_contact = _check_contacts(
            sender_email, sender_domain, contacts_csv,
        )
        is_keyword, matched_keyword = _check_keywords(
            subject, _get_priority_keywords(), custom_kw_csv,
        )
        is_priority = is_contact or is_keyword
        if is_contact:
            match_reason = f"known_contact ({sender_email})"
        elif is_keyword:
            match_reason = f"keyword ({matched_keyword})"

    # ── Urgent check (applies in both modes) ──
    is_urgent, urgent_keyword = _check_urgent(subject, _get_urgent_keywords())

    # ── Not priority → filtered out ──
    if not is_priority:
        if test_mode:
            log.info(  # noqa: F821
                f"email_promote [TEST]: FILTERED "
                f"sender={sender_email} subject={subject} "
                f"reason={match_reason}"
            )
        return {
            "status": "ok", "promoted": False,
            "reason": match_reason, "filter_result": "filtered",
            "sender": sender_email, "subject": subject,
        }

    # ── Priority match — promote to L2 ──
    timestamp = int(time.time())
    l2_key = f"email_priority:{person}:{timestamp}"
    l2_value = f"{sender_name}: {subject}"
    l2_tags = f"email {person} priority"
    filter_result = "urgent" if is_urgent else "priority"

    if test_mode:
        log.info(  # noqa: F821
            f"email_promote [TEST]: {filter_result.upper()} "
            f"sender={sender_email} subject={subject} "
            f"reason={match_reason}"
            + (f" urgent_keyword={urgent_keyword}" if is_urgent else "")
        )
        return {
            "status": "ok", "promoted": False,
            "reason": match_reason, "filter_result": filter_result,
            "sender": sender_email, "subject": subject,
            "test_skip": True,
        }

    # Write individual email to L2
    l2_ok = await _l2_set(
        key=l2_key, value=l2_value, tags=l2_tags,
        scope="user", expiration_days=3,
    )

    # Increment counter
    new_count = _get_email_count() + 1
    _set_email_count(new_count)

    # Mirror rolling count to L2 (for agent access via memory_get)
    await _l2_set(
        key=f"email_priority_count:{person}", value=str(new_count),
        tags=f"email {person} count", scope="user", expiration_days=1,
    )

    # Update last priority subject
    _update_last_priority(subject)
    _set_email_stale(False)  # Gap 2: clear stale on successful email processing

    # ── Urgent → TTS announcement via dedup ──
    tts_announced = False
    llm_used = False
    _suppress = str(suppress_tts).lower() in ("true", "1", "yes", "on")
    if is_urgent and not _suppress:
        sender_slug = _make_slug(sender_email.split("@")[0])
        subject_slug = _make_slug(subject[:30])

        # Get TTS voice + agent entity from dispatcher (pipeline-aware)
        announce_voice = _helper_str("input_text.ai_default_tts_voice", "tts.home_assistant_cloud")
        agent_entity = ""
        dispatch_resp = None
        try:
            dispatch_call = pyscript.agent_dispatch(  # noqa: F821
                wake_word="email_alert",
                intent_text="urgent email notification",
                skip_continuity=True,
            )
            dispatch_resp = await dispatch_call
            if dispatch_resp and dispatch_resp.get("tts_engine"):
                announce_voice = dispatch_resp["tts_engine"]
            if dispatch_resp:
                agent_entity = dispatch_resp.get("agent", "")
        except Exception:
            pass  # Fallback voice is fine

        # Build raw announcement text
        raw_text = (
            f"Priority email from {sender_name}. "
            f"Subject: {subject}."
        )
        speech_text = raw_text

        # LLM persona reformulation (budget-gated)
        budget = _get_budget_remaining()
        budget_threshold = _helper_int("input_number.ai_budget_personality_threshold", 20)
        if agent_entity and budget >= budget_threshold:
            try:
                prompt = EMAIL_ANNOUNCE_PROMPT.format(text=raw_text)
                conv_resp = await hass.services.async_call(  # noqa: F821
                    "conversation", "process",
                    {"agent_id": agent_entity, "text": prompt},
                    blocking=True,
                    return_response=True,
                )
                llm_speech = _extract_speech_from_response(conv_resp)
                if llm_speech:
                    speech_text = llm_speech
                    llm_used = True
                    log.info(  # noqa: F821
                        f"email_promote: LLM reformulation ok "
                        f"({len(llm_speech)} chars)"
                    )
            except Exception as exc:
                log.warning(  # noqa: F821
                    f"email_promote: LLM reformulation failed "
                    f"({exc}), using raw text"
                )
            _increment_llm_counter(1)
        elif not agent_entity:
            log.info(  # noqa: F821
                "email_promote: no agent_entity from dispatch, "
                "skipping LLM reformulation"
            )
        else:
            log.info(  # noqa: F821
                f"email_promote: budget at {budget}%, "
                "skipping LLM reformulation"
            )

        try:
            tts_call = pyscript.dedup_announce(  # noqa: F821
                topic=f"email_{sender_slug}_{subject_slug}",
                source="email_follow_me",
                text=speech_text,
                voice=announce_voice,
                priority=3,
                target_mode="presence",
            )
            tts_resp = await tts_call
            tts_announced = (
                tts_resp is not None
                and tts_resp.get("status") == "ok"
                and tts_resp.get("announced", False)
            )
        except Exception as exc:
            log.warning(  # noqa: F821
                f"email_promote: dedup_announce failed: {exc}"
            )

    return {
        "status": "ok",
        "promoted": l2_ok,
        "filter_result": filter_result,
        "reason": match_reason,
        "sender": sender_email,
        "subject": subject,
        "l2_key": l2_key,
        "count": new_count,
        "tts_announced": tts_announced,
        "llm_used": llm_used,
    }


# ── Services ─────────────────────────────────────────────────────────────────

@service(supports_response="only")  # noqa: F821
async def email_promote_process(
    sender: str = "",
    subject: str = "",
    suppress_tts: str = "false",
):
    """
    yaml
    name: Email Promote Process
    description: >-
      Process an incoming email through the priority filter. Checks sender
      against known contacts and subject against priority keywords. Priority
      emails are written to L2 memory. Urgent emails also get TTS announcement
      via dedup_announce with persona LLM reformulation. Called by the
      imap_content automation.
    fields:
      sender:
        name: Sender
        description: >-
          Email sender field (e.g., "John Doe <john@example.com>").
        required: true
        example: "Amazon <ship-confirm@amazon.com>"
        selector:
          text:
      subject:
        name: Subject
        description: Email subject line.
        required: true
        example: "Your package has shipped!"
        selector:
          text:
      suppress_tts:
        name: Suppress TTS
        description: >-
          When "true", urgent emails are still promoted to L2 but the
          TTS announcement is skipped. Used when email_follow_me
          instances already handle announcements.
        required: false
        example: "true"
        selector:
          text:
    """
    t_start = time.monotonic()

    # Kill switch
    try:
        enabled = str(
            state.get("input_boolean.ai_email_promotion_enabled") or "on"  # noqa: F821
        ).lower()
    except NameError:
        enabled = "on"

    if enabled == "off":
        result = {
            "status": "ok", "op": "email_promote",
            "promoted": False, "reason": "disabled",
            "elapsed_ms": 0,
        }
        _set_result("ok", **result)
        return result

    test_mode = _check_test_mode()

    # Resolve person from IMAP sensor (Task 22)
    imap_sensor = _get_imap_sensor()
    person = _resolve_person_from_imap(imap_sensor)
    process_result = await _process_email(sender, subject, test_mode, suppress_tts, person=person)

    elapsed = round((time.monotonic() - t_start) * 1000, 1)
    process_result["op"] = "email_promote"
    process_result["elapsed_ms"] = elapsed
    process_result["test_mode"] = test_mode

    sensor_state = "test" if test_mode else process_result.get("status", "ok")
    _set_result(sensor_state, **process_result)

    log.info(  # noqa: F821
        f"email_promote: {process_result.get('filter_result', 'unknown')} "
        f"sender={process_result.get('sender', '?')} "
        f"reason={process_result.get('reason', '?')} "
        f"{elapsed}ms{' [TEST]' if test_mode else ''}"
    )

    return process_result


@service(supports_response="only")  # noqa: F821
async def email_clear_count():
    """
    yaml
    name: Email Clear Count
    description: >-
      Reset the priority email counter to zero. Call when user says "I've read
      my emails" or from morning briefing after reading the count. Also clears
      the rolling count in L2 memory.
    """
    t_start = time.monotonic()

    _set_email_count(0)

    # Clear L2 rolling count for all persons (Task 22)
    for person in get_person_slugs():
        await _l2_set(
            key=f"email_priority_count:{person}", value="0",
            tags=f"email {person} count", scope="user", expiration_days=1,
        )

    elapsed = round((time.monotonic() - t_start) * 1000, 1)

    result = {
        "status": "ok", "op": "email_clear_count",
        "count": 0, "elapsed_ms": elapsed,
    }

    _set_result("ok", **result)
    log.info(f"email_promote: counter cleared {elapsed}ms")  # noqa: F821

    return result


# ── T24-3b: IMAP Health Check ─────────────────────────────────────────────────

def _get_imap_sensor() -> str:
    """Read IMAP sensor entity from config file."""
    cfg = load_entity_config()
    return cfg.get("imap_sensor") or "sensor.gmail_messages"


def _check_imap_health() -> None:
    """Check IMAP sensor availability and notify on failure."""
    try:
        imap_sensor = _get_imap_sensor()
        imap_state = state.get(imap_sensor)  # noqa: F821
        if imap_state in (None, "unavailable", "unknown"):
            log.warning(  # noqa: F821
                f"email_promote: IMAP sensor {imap_sensor} is "
                f"{imap_state or 'missing'} — email processing may fail"
            )
            _set_email_stale(True)
            service.call(  # noqa: F821
                "persistent_notification", "create",
                title="Email Integration: IMAP Unavailable",
                message=(
                    f"IMAP sensor ({imap_sensor}) is {imap_state or 'missing'}. "
                    f"Check IMAP credentials and integration in "
                    f"Settings → Integrations."
                ),
                notification_id="ai_imap_failure",
            )
        else:
            # IMAP healthy — dismiss any lingering alert
            _set_email_stale(False)
            service.call(  # noqa: F821
                "persistent_notification", "dismiss",
                notification_id="ai_imap_failure",
            )
    except Exception:
        pass


# ── Startup ──────────────────────────────────────────────────────────────────

@time_trigger("startup")  # noqa: F821
async def email_promote_startup():
    """Initialize email promotion status sensor."""
    _ensure_result_entity_name(force=True)
    _set_result("idle", op="startup")
    # Delay to let IMAP sensor load
    await task.sleep(30)  # noqa: F821
    _check_imap_health()

    # Gap 4: Reload IMAP config entry to re-fire events for unread messages.
    # Fixes startup race condition where IMAP events fire before automations are ready.
    # blocking=False prevents hanging on IMAP reconnect/IDLE setup.
    try:
        imap_sensor = _get_imap_sensor()
        log.info(f"email_promote: requesting IMAP reload for {imap_sensor}")  # noqa: F821
        service.call(  # noqa: F821
            "homeassistant", "reload_config_entry",
            entity_id=imap_sensor,
            blocking=False,
        )
        log.info("email_promote: IMAP config entry reload dispatched — catch-up events will fire")  # noqa: F821
    except Exception as exc:
        log.warning(f"email_promote: IMAP reload failed (non-fatal): {exc}")  # noqa: F821

    log.info("email_promote.py loaded — email priority filter idle")  # noqa: F821


# ── Midnight Reset ───────────────────────────────────────────────────────────

@time_trigger("cron(2 0 * * *)")  # noqa: F821
async def email_promote_midnight():
    """Reset email count at midnight — stale count from yesterday."""
    _set_email_count(0)

    # Midnight reset for all persons (Task 22)
    for person in get_person_slugs():
        await _l2_set(
            key=f"email_priority_count:{person}", value="0",
            tags=f"email {person} count", scope="user", expiration_days=1,
        )

    _check_imap_health()
    log.info("email_promote: midnight reset — counter cleared")  # noqa: F821


# ── Periodic Stale Check (Gap 2) ─────────────────────────────────────────────

@time_trigger("cron(*/30 * * * *)")  # noqa: F821
async def email_check_stale():
    """Flag email as stale if IMAP sensor hasn't changed in N minutes."""
    try:
        imap_sensor = _get_imap_sensor()
        imap_state = state.get(imap_sensor)  # noqa: F821
        if imap_state in (None, "unavailable", "unknown"):
            _set_email_stale(True)
            return

        try:
            raw_timeout = state.get("input_number.ai_email_stale_timeout")  # noqa: F821
            timeout_min = int(float(raw_timeout)) if raw_timeout not in (None, "unknown", "unavailable") else 120
        except (TypeError, ValueError):
            timeout_min = 120

        last_changed = state.get(imap_sensor + ".last_changed")  # noqa: F821
        if last_changed:
            from datetime import datetime, timezone
            changed_dt = datetime.fromisoformat(str(last_changed))
            age_min = (datetime.now(timezone.utc) - changed_dt).total_seconds() / 60
            if age_min > timeout_min:
                _set_email_stale(True)
            else:
                _set_email_stale(False)
        else:
            _set_email_stale(False)
    except Exception as exc:
        log.warning(f"email_promote: stale check failed: {exc}")  # noqa: F821
