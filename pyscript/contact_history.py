"""I-47: Per-Contact Message History.

Logs per-contact messages to L2 memory after notification and email
announcements, retrieves recent history for LLM prompt injection, and
batch-summarizes raw entries into per-contact digests via LLM. Exposes
pyscript.contact_history_log, contact_history_context, and
contact_history_summarize.
"""
import json
import re
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from shared_utils import build_result_entity_name

# =============================================================================
# Contact History — I-47: Per-Contact Message History
# =============================================================================
# Provides per-contact message logging, context retrieval, and batch
# summarization for notification follow-me and email follow-me blueprints.
#
# Services:
#   pyscript.contact_history_log
#     Post-announcement: write raw message entry to L2 memory.
#     Fires contact_history_log_complete event for event-driven summarizer.
#     Zero LLM calls.
#
#   pyscript.contact_history_context
#     Pre-LLM: fetch recent history for a sender. Returns formatted context
#     block for prompt injection. Zero LLM calls.
#
#   pyscript.contact_history_summarize
#     Batch-compress raw entries into per-contact digests via LLM.
#     Budget-gated, model-configurable.
#
# L2 key schema:
#   Raw messages:  contact_msg_{name}_{unix_ts}
#     Tags: contact message {name} {channel}
#     Scope: user, Expiry: 3 days
#   Digests:       contact_digest_{name}_{unix_ts}
#     Tags: contact digest {name}
#     Scope: user, Expiry: configurable (default 7 days)
#
# Dependencies:
#   - pyscript/memory.py (L2: memory_get, memory_set, memory_search)
#   - packages/ai_context_hot.yaml (ha_text_ai for summarization)
#   - input_boolean.ai_contact_history_enabled (kill switch)
#
# Deployed: 2026-03-12
# =============================================================================

RESULT_ENTITY = "sensor.ai_contact_history_status"

# Lookback windows in hours
WINDOW_MAP = {
    "1h": 1,
    "6h": 6,
    "24h": 24,
    "3d": 72,
    "7d": 168,
}

result_entity_name: dict[str, str] = {}


def _ensure_result_entity_name(force: bool = False) -> None:
    global result_entity_name
    if force or not result_entity_name:
        result_entity_name = build_result_entity_name(RESULT_ENTITY)


def _set_result(state_value: str = "ok", **attrs: Any) -> None:
    _ensure_result_entity_name()
    attrs.update(result_entity_name)
    state.set(RESULT_ENTITY, value=state_value, new_attributes=attrs)  # noqa: F821


# ── Pure-Python Sync Helpers ─────────────────────────────────────────────────

@pyscript_compile  # noqa: F821
def _normalize_contact(name: str) -> str:
    """Normalize contact name for consistent key generation.

    Lowercase, spaces to underscores, strip special chars.
    "Mum" → "mum", "María José" → "maria_jose"
    """
    if not name:
        return "unknown"
    t = name.lower().strip()
    t = t.replace(" ", "_")
    t = re.sub(r"[^\w]", "", t)
    t = re.sub(r"_+", "_", t)
    t = t.strip("_")
    return t or "unknown"


@pyscript_compile  # noqa: F821
def _build_msg_key(contact_norm: str, unix_ts: int) -> str:
    """Build raw message L2 key."""
    return f"contact_msg_{contact_norm}_{unix_ts}"


@pyscript_compile  # noqa: F821
def _build_digest_key(contact_norm: str, unix_ts: int) -> str:
    """Build digest L2 key."""
    return f"contact_digest_{contact_norm}_{unix_ts}"


@pyscript_compile  # noqa: F821
def _build_msg_value(
    sender: str, channel: str, message: str, app_label: str,
    storage_mode: str,
) -> str:
    """Build JSON value for a raw message entry."""
    data = {
        "sender": sender,
        "channel": channel,
        "app": app_label,
        "ts": datetime.now(UTC).isoformat(),
    }
    if storage_mode in ("both", "text_only"):
        data["text"] = message[:1000]  # cap raw text storage
    if storage_mode == "summary_only":
        data["text_preview"] = message[:100]  # short preview for summarizer
    return json.dumps(data, ensure_ascii=False)


@pyscript_compile  # noqa: F821
def _format_history_block(entries: list) -> str:
    """Format history entries into a context block for LLM prompt injection."""
    if not entries:
        return ""
    lines = []
    now = datetime.now(UTC)
    for entry in entries:
        key = entry.get("key", "")
        value_str = entry.get("value", "")
        created = entry.get("created_at", "")

        # Compute relative time
        age_label = ""
        if created:
            try:
                ts = datetime.fromisoformat(created)
                if ts.tzinfo is None:
                    from datetime import timezone
                    ts = ts.replace(tzinfo=timezone.utc)
                delta = now - ts
                mins = int(delta.total_seconds() / 60)
                if mins < 60:
                    age_label = f"{mins}m ago"
                elif mins < 1440:
                    age_label = f"{mins // 60}h ago"
                else:
                    age_label = f"{mins // 1440}d ago"
            except (ValueError, TypeError):
                age_label = "?"

        # Parse value JSON
        try:
            data = json.loads(value_str)
        except (json.JSONDecodeError, TypeError):
            data = {"text": value_str}

        is_digest = "contact_digest_" in key
        if is_digest:
            lines.append(f"[{age_label}] Digest: {data.get('summary', value_str)}")
        else:
            text = data.get("text", data.get("text_preview", ""))
            channel = data.get("channel", data.get("app", ""))
            if text:
                lines.append(f"[{age_label}] {channel}: \"{text}\"")
            else:
                lines.append(f"[{age_label}] {channel}: (media/no text)")

    return "\n".join(lines)


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
        log.warning(f"contact_history: L2 set failed key={key}: {exc}")  # noqa: F821
        return False


async def _l2_search(query: str, limit: int = 30) -> list[dict[str, Any]]:
    """Search L2 via memory_search. Returns empty list on failure."""
    try:
        result = pyscript.memory_search(query=query, limit=limit)  # noqa: F821
        resp = await result
        if resp and resp.get("status") == "ok":
            return resp.get("results", [])
    except Exception as exc:
        log.warning(f"contact_history: L2 search failed query={query}: {exc}")  # noqa: F821
    return []


async def _l2_forget(key: str) -> bool:
    """Delete entry from L2 via memory_forget."""
    try:
        result = pyscript.memory_forget(key=key)  # noqa: F821
        resp = await result
        return resp is not None and resp.get("status") == "ok"
    except Exception as exc:
        log.warning(f"contact_history: L2 forget failed key={key}: {exc}")  # noqa: F821
        return False


# ── Test Mode ────────────────────────────────────────────────────────────────

def _is_test_mode() -> bool:
    try:
        return str(
            state.get("input_boolean.ai_test_mode") or "off"  # noqa: F821
        ).lower() == "on"
    except NameError:
        return False


# ── Services ─────────────────────────────────────────────────────────────────

@service(supports_response="optional")  # noqa: F821
async def contact_history_log(
    sender: str = "",
    channel: str = "",
    message: str = "",
    app_label: str = "",
    storage_mode: str = "both",
):
    """
    yaml
    name: Contact History Log
    description: >-
      Write a raw message entry to L2 memory for per-contact history tracking.
      Fires contact_history_log_complete event after write for event-driven
      summarizer triggering. Zero LLM calls.
    fields:
      sender:
        name: Sender
        description: Contact name (e.g., "Mum", "María").
        required: true
        selector:
          text:
      channel:
        name: Channel
        description: Message source (e.g., "WhatsApp", "Signal", "SMS").
        required: true
        selector:
          text:
      message:
        name: Message
        description: The message text to log.
        required: true
        selector:
          text:
            multiline: true
      app_label:
        name: App Label
        description: Display label for the app (e.g., "WhatsApp").
        default: ""
        selector:
          text:
      storage_mode:
        name: Storage Mode
        description: "What to persist: both (text + summary), summary_only, text_only."
        default: "both"
        selector:
          select:
            options: [both, summary_only, text_only]
    """
    # Returns: {status, op, logged?, key?, contact?, elapsed_ms?, reason?, error?}
    if _is_test_mode():
        log.info("contact_history [TEST]: would log message from sender=%s channel=%s", sender, channel)  # noqa: F821
        return

    t_start = time.monotonic()

    try:
        # Kill switch
        if state.get("input_boolean.ai_contact_history_enabled") == "off":  # noqa: F821
            result = {
                "status": "ok", "op": "contact_history_log",
                "logged": False, "reason": "disabled",
            }
            _set_result("ok", **result)
            return result

        if not sender:
            result = {
                "status": "error", "op": "contact_history_log",
                "error": "sender_required",
            }
            _set_result("error", **result)
            return result

        contact_norm = _normalize_contact(sender)
        unix_ts = int(datetime.now(UTC).timestamp())
        key = _build_msg_key(contact_norm, unix_ts)
        value = _build_msg_value(
            sender=sender,
            channel=channel or app_label or "unknown",
            message=message or "",
            app_label=app_label or channel or "unknown",
            storage_mode=storage_mode,
        )
        tags = f"contact message {contact_norm} {(channel or app_label or 'unknown').lower()}"

        ok = await _l2_set(key=key, value=value, tags=tags, scope="user", expiration_days=3)

        elapsed = round((time.monotonic() - t_start) * 1000, 1)

        if ok:
            log.info(  # noqa: F821
                f"contact_history_log: logged {key} sender={sender} "
                f"channel={channel} {elapsed}ms"
            )
            # Fire event for event-driven summarizer
            event.fire(  # noqa: F821
                "contact_history_log_complete",
                contact=contact_norm,
                sender=sender,
                channel=channel or app_label or "unknown",
            )
        else:
            log.warning(  # noqa: F821
                f"contact_history_log: L2 write failed for {key}"
            )

        result = {
            "status": "ok", "op": "contact_history_log",
            "logged": ok, "key": key, "contact": contact_norm,
            "elapsed_ms": elapsed,
        }
        _set_result("ok", **result)
        return result

    except Exception as exc:
        log.error("contact_history_log failed: %s: %s", type(exc).__name__, exc)  # noqa: F821
        _set_result("error", op="contact_history_log", error=str(exc))
        return {"status": "error", "op": "contact_history_log", "error": str(exc)}


@service(supports_response="only")  # noqa: F821
async def contact_history_context(
    sender: str = "",
    window: str = "24h",
    max_entries: int = 15,
):
    """
    yaml
    name: Contact History Context
    description: >-
      Fetch recent message history for a sender from L2 memory. Returns a
      formatted context block for LLM prompt injection. Combines raw messages
      and digests, sorted by time. Zero LLM calls.
    fields:
      sender:
        name: Sender
        description: Contact name to look up.
        required: true
        selector:
          text:
      window:
        name: Context Window
        description: "Lookback period: 1h, 6h, 24h, 3d, 7d."
        default: "24h"
        selector:
          select:
            options: [1h, 6h, 24h, 3d, 7d]
      max_entries:
        name: Max Entries
        description: Maximum entries to return.
        default: 15
        selector:
          number:
            min: 1
            max: 50
    """
    # Returns: {status, op, has_history, context_block, entry_count, contact?, window?, elapsed_ms?, reason?, error?}
    if _is_test_mode():
        log.info("contact_history [TEST]: would fetch context for sender=%s window=%s", sender, window)  # noqa: F821
        return {"status": "test_mode_skip"}

    t_start = time.monotonic()

    try:
        # Kill switch
        if state.get("input_boolean.ai_contact_history_enabled") == "off":  # noqa: F821
            return {
                "status": "ok", "op": "contact_history_context",
                "has_history": False, "reason": "disabled",
                "context_block": "", "entry_count": 0,
            }

        if not sender:
            return {
                "status": "error", "op": "contact_history_context",
                "error": "sender_required",
            }

        contact_norm = _normalize_contact(sender)
        window_hours = WINDOW_MAP.get(window, 24)
        now = datetime.now(UTC)
        cutoff = now - timedelta(hours=window_hours)
        cutoff_iso = cutoff.isoformat()

        # Search for both raw messages and digests for this contact
        raw_entries = await _l2_search(
            f"contact message {contact_norm}", limit=30,
        )
        digest_entries = await _l2_search(
            f"contact digest {contact_norm}", limit=10,
        )

        # Filter by time window and combine
        all_entries = []
        for entry in raw_entries + digest_entries:
            created = entry.get("created_at", "")
            if not created:
                continue
            if created >= cutoff_iso:
                all_entries.append(entry)

        # Sort by created_at ascending (oldest first)
        all_entries.sort(key=lambda e: e.get("created_at", ""))

        # Cap entries
        if len(all_entries) > max_entries:
            all_entries = all_entries[-max_entries:]

        context_block = _format_history_block(all_entries)

        elapsed = round((time.monotonic() - t_start) * 1000, 1)

        result = {
            "status": "ok",
            "op": "contact_history_context",
            "has_history": len(all_entries) > 0,
            "context_block": context_block,
            "entry_count": len(all_entries),
            "contact": contact_norm,
            "window": window,
            "elapsed_ms": elapsed,
        }
        _set_result("ok", **result)

        log.info(  # noqa: F821
            f"contact_history_context: contact={contact_norm} "
            f"entries={len(all_entries)} window={window} {elapsed}ms"
        )

        return result

    except Exception as exc:
        log.error(f"contact_history_context failed: {exc}")  # noqa: F821
        return {
            "status": "error", "op": "contact_history_context",
            "error": str(exc), "has_history": False,
            "context_block": "", "entry_count": 0,
        }


@service(supports_response="optional")  # noqa: F821
async def contact_history_summarize(
    min_messages: int = 2,
    max_contacts: int = 20,
    summary_expiry_days: int = 7,
    llm_instance: str = "",
    target_contact: str = "",
):
    """
    yaml
    name: Contact History Summarize
    description: >-
      Batch-compress raw contact message entries into per-contact digests
      using an LLM. Groups unsummarized raw messages by contact, sends each
      group to the LLM for compression, stores the digest, and optionally
      cleans up source entries.
    fields:
      min_messages:
        name: Min Messages
        description: Min raw messages per contact before compressing.
        default: 2
        selector:
          number:
            min: 1
            max: 20
      max_contacts:
        name: Max Contacts
        description: Cap contacts processed per run.
        default: 20
        selector:
          number:
            min: 1
            max: 50
      summary_expiry_days:
        name: Summary Expiry Days
        description: How long digest entries persist in L2.
        default: 7
        selector:
          number:
            min: 1
            max: 90
      llm_instance:
        name: LLM Instance
        description: >-
          ha_text_ai sensor entity for LLM calls. Leave empty to use default.
        default: ""
        selector:
          entity:
            domain: sensor
      target_contact:
        name: Target Contact
        description: >-
          If set, only summarize this contact (normalized name).
          Used by event-driven mode. Empty = summarize all.
        default: ""
        selector:
          text:
    """
    if _is_test_mode():
        log.info("contact_history [TEST]: would summarize contact messages")  # noqa: F821
        return

    t_start = time.monotonic()

    # Kill switch
    if state.get("input_boolean.ai_contact_history_enabled") == "off":  # noqa: F821
        result = {
            "status": "ok", "op": "contact_history_summarize",
            "reason": "disabled", "contacts_processed": 0,
            "digests_created": 0,
        }
        _set_result("ok", **result)
        return result

    # Search for unsummarized raw messages
    if target_contact:
        contact_norm = _normalize_contact(target_contact)
        raw_entries = await _l2_search(
            f"contact message {contact_norm}", limit=50,
        )
    else:
        raw_entries = await _l2_search("contact message", limit=100)

    # Group by contact
    contact_groups: dict[str, list[dict]] = {}
    for entry in raw_entries:
        key = entry.get("key", "")
        tags = entry.get("tags", "")
        if "summarized" in tags:
            continue  # already processed
        if not key.startswith("contact_msg_"):
            continue
        # Extract contact name from key: contact_msg_{name}_{ts}
        parts = key.split("_")
        if len(parts) < 4:
            continue
        # Name is everything between "msg" and the last part (timestamp)
        contact = "_".join(parts[2:-1])
        if contact not in contact_groups:
            contact_groups[contact] = []
        contact_groups[contact].append(entry)

    # Filter by min_messages and cap contacts
    eligible = {
        k: v for k, v in contact_groups.items()
        if len(v) >= min_messages
    }
    contacts_to_process = list(eligible.keys())[:max_contacts]

    digests_created = 0
    entries_processed = 0
    llm_calls = 0

    # Resolve LLM instance
    llm_entity = llm_instance or ""
    if not llm_entity:
        # Try default ha_text_ai instance
        llm_entity = "sensor.ha_text_ai"

    for contact in contacts_to_process:
        entries = eligible[contact]
        # Sort by created_at
        entries.sort(key=lambda e: e.get("created_at", ""))

        # Build prompt from entries
        msg_lines = []
        source_keys = []
        for entry in entries:
            value_str = entry.get("value", "")
            try:
                data = json.loads(value_str)
            except (json.JSONDecodeError, TypeError):
                data = {"text": value_str}
            created = entry.get("created_at", "")
            channel = data.get("channel", data.get("app", ""))
            text = data.get("text", data.get("text_preview", ""))
            sender = data.get("sender", contact)
            msg_lines.append(
                f"[{created}] {channel} from {sender}: {text}"
            )
            source_keys.append(entry.get("key", ""))

        prompt = (
            "Summarize these messages from the same contact into a concise "
            "2-3 sentence digest. Focus on key topics, questions asked, and "
            "emotional tone. Do not include timestamps or channel names in "
            "the summary — just the conversational essence.\n\n"
            + "\n".join(msg_lines)
        )

        # Call LLM via ha_text_ai
        try:
            llm_result = pyscript.llm_task_call(  # noqa: F821
                prompt=prompt,
                instance=llm_entity,
            )
            resp = await llm_result
            llm_calls += 1

            summary_text = ""
            if resp and resp.get("status") == "ok":
                summary_text = resp.get("response", "")

            if not summary_text:
                log.warning(  # noqa: F821
                    f"contact_history_summarize: LLM returned empty "
                    f"for contact={contact}"
                )
                continue

        except Exception as exc:
            log.error(  # noqa: F821
                f"contact_history_summarize: LLM call failed "
                f"contact={contact}: {exc}"
            )
            continue

        # Store digest
        unix_ts = int(datetime.now(UTC).timestamp())
        digest_key = _build_digest_key(contact, unix_ts)
        digest_value = json.dumps(
            {"summary": summary_text, "source_count": len(entries)},
            ensure_ascii=False,
        )
        digest_tags = f"contact digest {contact}"

        ok = await _l2_set(
            key=digest_key, value=digest_value, tags=digest_tags,
            scope="user", expiration_days=summary_expiry_days,
        )

        if ok:
            digests_created += 1
            entries_processed += len(entries)

            # Tag source entries as summarized
            for src_key in source_keys:
                try:
                    result = pyscript.memory_set(  # noqa: F821
                        key=src_key,
                        value="",  # keep existing value
                        tags=f"contact message {contact} summarized",
                        scope="user",
                        expiration_days=3,
                    )
                    await result
                except Exception:
                    pass

            log.info(  # noqa: F821
                f"contact_history_summarize: created digest for "
                f"contact={contact} from {len(entries)} messages"
            )

    elapsed = round((time.monotonic() - t_start) * 1000, 1)

    result = {
        "status": "ok",
        "op": "contact_history_summarize",
        "contacts_processed": len(contacts_to_process),
        "digests_created": digests_created,
        "entries_processed": entries_processed,
        "llm_calls": llm_calls,
        "elapsed_ms": elapsed,
    }
    _set_result("ok", **result)

    log.info(  # noqa: F821
        f"contact_history_summarize: {digests_created} digests from "
        f"{entries_processed} messages, {llm_calls} LLM calls, "
        f"{elapsed}ms"
    )

    return result


# ── Startup ──────────────────────────────────────────────────────────────────

@time_trigger("startup")  # noqa: F821
async def contact_history_startup():
    """Initialize contact history sensor on HA startup."""
    _ensure_result_entity_name(force=True)
    _set_result("idle", op="startup")
    log.info("contact_history.py loaded — contact history idle")  # noqa: F821
