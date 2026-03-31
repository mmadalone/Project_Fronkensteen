"""conversation_sensor.py — Event-driven conversation response capture + L2 history.

Listens to extended_openai_conversation.conversation.finished events, writes
sensor.ai_last_conversation_response for reactive banter, stores raw responses
in L2 memory, and provides a summarization service for batch compression.

Package: ai_conversation_sensor.yaml
Blueprint: conversation_summarizer.yaml
"""
import time as _time
from typing import Any

from shared_utils import build_result_entity_name

# =============================================================================
# Conversation Sensor — Event-driven response capture + L2 history
# =============================================================================
# Listens to conversation.finished events from extended_openai_conversation,
# captures agent responses for banter sensor, optionally stores in L2 memory,
# and provides batch summarization via LLM.
#
# Services:
#   pyscript.summarize_conversations
#     Batch-compress raw conversation entries into per-agent summaries
#     using a cheap LLM call. Stores summaries as new L2 entries.
#
# Sensors:
#   sensor.ai_last_conversation_response — latest agent response for banter
#   sensor.ai_conversation_sensor_status — module status / counters
#
# Dependencies:
#   - pyscript/memory.py (L2: memory_set, memory_search, memory_forget)
#   - pyscript/common_utilities.py (llm_task_call)
#   - packages/ai_conversation_sensor.yaml (helpers)
# =============================================================================

_MODULE = "conversation_sensor"
_RESULT_ENTITY = f"sensor.ai_{_MODULE}_status"
_BANTER_SENSOR = "sensor.ai_last_conversation_response"
_L2_PREFIX = "convsensor"

# ── Summarization Constants ──────────────────────────────────────────────────
_SUMMARY_DEFAULT_EXPIRY_DAYS = 30
_SUMMARY_MAX_CONVERSATIONS = 50
_SUMMARY_MAX_PER_AGENT = 20
_SUMMARY_SYSTEM_PROMPT = (
    "You are a concise conversation log compressor for a smart home system. "
    "Output ONLY the summary — no preamble, no bullet points, no labels. "
    "Write in past tense, third person. Keep it under 100 words. "
    "Focus on what the user asked and what the assistant did or said."
)

# ── Result Entity Name Cache ─────────────────────────────────────────────────
result_entity_name: dict[str, str] = {}


def _ensure_result_entity_name(force: bool = False) -> None:
    global result_entity_name
    if force or not result_entity_name:
        result_entity_name = build_result_entity_name(_RESULT_ENTITY)


def _set_result(state_value: str = "ok", **attrs: Any) -> None:
    _ensure_result_entity_name()
    attrs.update(result_entity_name)
    state.set(_RESULT_ENTITY, value=state_value, new_attributes=attrs)  # noqa: F821


# ── Test Mode ────────────────────────────────────────────────────────────────

def _is_test_mode() -> bool:
    try:
        return str(
            state.get("input_boolean.ai_test_mode") or "off"  # noqa: F821
        ).lower() == "on"
    except NameError:
        return False


# ── Bare Tool Call Detection ─────────────────────────────────────────────────

def _is_bare_tool_call(text):
    """Check if text is a bare function call like 'execute_service(...)'."""
    stripped = (text or "").strip().rstrip(".")
    if not stripped.endswith(")") or "(" not in stripped:
        return False
    before = stripped[:stripped.index("(")]
    if len(before) == 0:
        return False
    valid = [c.isalnum() or c == "_" for c in before]
    return all(valid)


# ── Async L2 Memory Helpers ─────────────────────────────────────────────────

async def _write_to_l2(
    key: str,
    value: str,
    tags: str,
    scope: str = "household",
    expiration_days: int = 2,
    force_new: bool = True,
) -> bool:
    """Write an entry to L2 memory. Swallows errors for resilience."""
    try:
        result = pyscript.memory_set(  # noqa: F821
            key=key,
            value=value,
            scope=scope,
            expiration_days=expiration_days,
            tags=tags,
            force_new=force_new,
        )
        resp = await result
        if resp and resp.get("status") == "ok":
            return True
        log.warning(  # noqa: F821
            f"{_MODULE}: L2 write status={resp.get('status', '?')} "
            f"key={key}"
        )
        return False
    except Exception as exc:
        log.warning(  # noqa: F821
            f"{_MODULE}: L2 write failed key={key}: {exc}"
        )
        return False


async def _search_l2(query: str, limit: int = 50) -> list[dict[str, Any]]:
    """Search L2 memory for entries. Returns empty list on failure."""
    try:
        result = pyscript.memory_search(  # noqa: F821
            query=query,
            limit=limit,
        )
        resp = await result
        if resp and resp.get("status") == "ok":
            return resp.get("results", [])
    except Exception as exc:
        log.warning(  # noqa: F821
            f"{_MODULE}: L2 search failed query={query}: {exc}"
        )
    return []


async def _forget_l2(key: str) -> bool:
    """Delete a single L2 entry by key. Swallows errors for resilience."""
    try:
        result = pyscript.memory_forget(key=key)  # noqa: F821
        resp = await result
        return bool(resp and resp.get("status") == "ok")
    except Exception as exc:
        log.warning(f"{_MODULE}: L2 forget failed key={key}: {exc}")  # noqa: F821
        return False


async def _tag_entry(key: str, entry: dict, new_tag: str, extend_days: int = 0) -> bool:
    """Add a tag to an existing L2 entry by re-writing with updated tags."""
    try:
        existing_tags = entry.get("tags", "")
        updated_tags = f"{existing_tags} {new_tag}".strip()
        kwargs: dict[str, Any] = {
            "key": key,
            "value": entry.get("value", ""),
            "scope": entry.get("scope", "user"),
            "tags": updated_tags,
            "force_new": True,
        }
        if extend_days > 0:
            kwargs["expiration_days"] = extend_days
        result = pyscript.memory_set(**kwargs)  # noqa: F821
        resp = await result
        return bool(resp and resp.get("status") == "ok")
    except Exception as exc:
        log.warning(f"{_MODULE}: tag update failed key={key}: {exc}")  # noqa: F821
        return False


# ── Startup ──────────────────────────────────────────────────────────────────

@time_trigger("startup")  # noqa: F821
def conversation_sensor_startup():
    """Initialize sensors on HA restart."""
    # Initialize banter sensor (moved from agent_whisper.py)
    state.set(  # noqa: F821
        _BANTER_SENSOR,
        "",
        new_attributes={
            "agent": "",
            "full_response": "",
            "friendly_name": "AI Last Conversation Response",
        },
    )
    # Initialize result entity
    _ensure_result_entity_name(force=True)
    _set_result(
        "idle",
        last_event="",
        events_captured=0,
        l2_writes=0,
    )
    log.info(f"[{_MODULE}] Initialized — listening for conversation events")  # noqa: F821


# ── Event Listener ───────────────────────────────────────────────────────────

@event_trigger("extended_openai_conversation.conversation.finished")  # noqa: F821
def _on_conversation_finished(**kwargs):
    """Capture conversation responses and optionally store in L2."""
    user_input = kwargs.get("user_input")
    messages = kwargs.get("messages", [])

    if not user_input or not messages:
        return

    # Extract text — handle both object and dict
    user_text = getattr(user_input, "text", None) or (
        user_input.get("text", "") if isinstance(user_input, dict) else ""
    )
    agent_entity_id = getattr(user_input, "agent_id", None) or (
        user_input.get("agent_id", "") if isinstance(user_input, dict) else ""
    )

    # Guard: skip automation-driven conversation calls (prevent banter/L2 pollution)
    if user_text.startswith((
        "[BANTER", "[INTERNAL", "[NOTIFICATION", "[MUSIC ANNOUNCE",
        "[BEDTIME", "[ALARM", "[GREETING", "[REMINDER",
        "[HANDOFF", "[ESCALATION",
    )):
        return

    # Extract optional [SOURCE:tag] prefix — pass as event field, strip from user_text
    _source_tag = ""
    if user_text.startswith("[SOURCE:"):
        _end = user_text.find("]")
        if _end > 8:
            _source_tag = user_text[8:_end].strip()
            user_text = user_text[_end + 1:].lstrip()

    # Extract response from last message
    last_msg = messages[-1] if messages else {}
    response_text = last_msg.get("content", "") if isinstance(last_msg, dict) else ""

    # Guard: skip empty/None responses
    if not response_text:
        return

    # Guard: skip bare tool calls
    if _is_bare_tool_call(response_text):
        return

    # Resolve agent name
    agent_display_name = ""
    if agent_entity_id:
        attrs = state.getattr(agent_entity_id) or {}  # noqa: F821
        agent_display_name = attrs.get("friendly_name", agent_entity_id.split(".", 1)[-1])
    agent_slug = agent_entity_id.split(".", 1)[-1] if agent_entity_id else "unknown"

    # --- Always write banter sensor ---
    state.set(  # noqa: F821
        _BANTER_SENSOR,
        response_text[:200] if response_text else "",
        new_attributes={
            "agent": agent_display_name,
            "full_response": response_text[:500] if response_text else "",
            "friendly_name": "AI Last Conversation Response",
        },
    )

    # --- Fire event for reactive banter (replaces state triggers) ---
    _topic = (
        (state.getattr("sensor.ai_last_interaction") or {}).get("topic") or "general"  # noqa: F821
    ).strip()
    _event_kwargs = dict(
        agent_name=agent_display_name,
        agent_slug=agent_slug,
        agent_short=(
            agent_display_name.split(" - ")[0].strip().lower().replace(" ", "_")
            if agent_display_name else (agent_slug.split("_")[0] if agent_slug else "unknown")
        ),
        response_text=response_text[:500] if response_text else "",
        user_text=user_text,
        topic=_topic,
    )
    if _source_tag:
        _event_kwargs["source"] = _source_tag
    event.fire("ai_conversation_response_ready", **_event_kwargs)  # noqa: F821

    # Update counters
    current_attrs = state.getattr(_RESULT_ENTITY) or {}  # noqa: F821
    events_captured = int(current_attrs.get("events_captured", 0)) + 1

    # --- L2 write (if enabled) ---
    l2_writes = int(current_attrs.get("l2_writes", 0))
    if state.get("input_boolean.ai_conversation_sensor_enabled") == "on":  # noqa: F821
        ts = int(_time.time())
        # Derive short agent name from friendly_name (slug unreliable for generic entities)
        agent_short = (
            agent_display_name.split(" - ")[0].strip().lower().replace(" ", "_")
            if agent_display_name else (agent_slug.split("_")[0] if agent_slug else "unknown")
        )
        key = f"{_L2_PREFIX}:response:{agent_slug}:{ts}"
        value = f'[{agent_display_name}] User: "{user_text}" -> "{response_text[:500]}"'
        tags = f"conversation response {agent_short}"

        retention_days = int(
            float(state.get("input_number.ai_conversation_history_retention_days") or 7)  # noqa: F821
        )
        await _write_to_l2(key, value, tags, expiration_days=retention_days, force_new=True)
        l2_writes += 1

    _set_result(
        "active",
        last_event=agent_display_name,
        events_captured=events_captured,
        l2_writes=l2_writes,
    )


# ── Summarization Helpers ────────────────────────────────────────────────────

@pyscript_compile  # noqa: F821
def _build_conversation_summary_prompt(entries):
    """Build a prompt from conversation entries for LLM summarization."""
    lines = []
    for entry in entries:
        lines.append(entry.get("value", ""))
    return (
        f"Compress these {len(entries)} conversation exchanges into a 2-3 "
        f"sentence summary. Preserve: recurring topics, any mood shifts. "
        f"Drop: timestamps, filler, exact phrasing.\n\n"
        f"Exchanges:\n" + "\n".join(lines)
    )


def _extract_agent_from_conversation_tags(tags: str) -> str:
    """Extract agent name from conversation tags.

    Tags format: 'conversation response {agent_short}'
    """
    if not tags:
        return ""
    skip = {"conversation", "response", "summary", "summarized", "archived"}
    for part in tags.split():
        if part in skip:
            continue
        return part
    return ""


# ── Summarize Conversations Service ──────────────────────────────────────────

@service(supports_response="optional")  # noqa: F821
async def summarize_conversations(
    lookback_hours: int = 36,
    min_conversations: int = 3,
    max_conversations: int = 50,
    retention_mode: str = "summary_and_tag",
    summary_expiry_days: int = 30,
    llm_instance: str = "",
    budget_floor: int = 30,
):
    """
    yaml
    name: Summarize Conversations
    description: >-
      Batch-compress raw conversation entries from L2 memory into per-agent
      summaries using a cheap LLM call. Stores summaries as new L2 entries
      with long TTL. Called by the conversation_summarizer blueprint.
    fields:
      lookback_hours:
        name: Lookback Hours
        description: Only summarize conversations older than this (hours).
        default: 36
        selector:
          number:
            min: 12
            max: 47
            mode: slider
      min_conversations:
        name: Min Conversations per Agent
        description: Skip agents with fewer unsummarized conversations.
        default: 3
        selector:
          number:
            min: 1
            max: 20
            mode: box
      max_conversations:
        name: Max Conversations per Batch
        description: Total cap on conversations processed in one run.
        default: 50
        selector:
          number:
            min: 10
            max: 200
            mode: box
      retention_mode:
        name: Retention Mode
        description: >-
          summary_and_tag: tag sources, let TTL expire.
          summary_and_delete: delete sources immediately.
          summary_only: leave sources untouched.
        default: summary_and_tag
        selector:
          select:
            options:
              - summary_and_tag
              - summary_and_delete
              - summary_only
      summary_expiry_days:
        name: Summary Expiry (days)
        description: How long summaries persist in L2.
        default: 30
        selector:
          number:
            min: 7
            max: 365
            mode: box
      llm_instance:
        name: LLM Instance
        description: ha_text_ai sensor entity for LLM calls. Leave empty to use default.
        selector:
          entity:
            domain: sensor
      budget_floor:
        name: Budget Floor (%)
        description: Skip when remaining budget is at or below this percentage. 0 = always run.
        default: 30
        selector:
          number:
            min: 0
            max: 100
            step: 5
            mode: slider
    """
    if _is_test_mode():
        log.info(f"[{_MODULE}] [TEST]: would summarize conversations")  # noqa: F821
        return {"status": "test_mode_skip"}

    t_start = _time.monotonic()
    test_mode = state.get("input_boolean.ai_test_mode") == "on"  # noqa: F821

    # ── Validate params ──
    valid_modes = {"summary_and_tag", "summary_and_delete", "summary_only"}
    ret_mode = retention_mode if retention_mode in valid_modes else "summary_and_tag"
    try:
        lookback = max(12, min(int(lookback_hours), 47))
    except (TypeError, ValueError):
        lookback = 36
    try:
        min_conv = max(1, min(int(min_conversations), 20))
    except (TypeError, ValueError):
        min_conv = 3
    try:
        max_conv = max(10, min(int(max_conversations), _SUMMARY_MAX_CONVERSATIONS))
    except (TypeError, ValueError):
        max_conv = 50
    try:
        expiry = max(7, min(int(summary_expiry_days), 365))
    except (TypeError, ValueError):
        expiry = _SUMMARY_DEFAULT_EXPIRY_DAYS

    _set_result("summarizing")

    # ── Search L2 for conversation response entries ──
    raw = await _search_l2("conversation response", limit=max_conv * 2)
    if not raw:
        result = {
            "status": "ok", "op": "summarize_conversations",
            "summaries_created": 0, "entries_processed": 0,
            "message": "no_conversation_entries_found",
            "test_mode": test_mode,
            "elapsed_ms": round((_time.monotonic() - t_start) * 1000, 1),
        }
        _set_result("test" if test_mode else "ok", **result)
        return result

    # ── Filter: not already tagged ──
    candidates = []
    for entry in raw:
        tags = entry.get("tags", "")
        tag_set = set(tags.split()) if tags else set()
        if "summarized" in tag_set or "archived" in tag_set:
            continue
        candidates.append(entry)
        if len(candidates) >= max_conv:
            break

    if not candidates:
        result = {
            "status": "ok", "op": "summarize_conversations",
            "summaries_created": 0, "entries_processed": 0,
            "message": "no_eligible_entries",
            "test_mode": test_mode,
            "elapsed_ms": round((_time.monotonic() - t_start) * 1000, 1),
        }
        _set_result("test" if test_mode else "ok", **result)
        return result

    # ── Group by agent ──
    agent_groups: dict[str, list[dict[str, Any]]] = {}
    for entry in candidates:
        agent = _extract_agent_from_conversation_tags(entry.get("tags", ""))
        if agent:
            agent_groups.setdefault(agent, []).append(entry)

    # ── Budget pre-check ──
    try:
        floor = max(0, min(int(budget_floor), 100))
    except (TypeError, ValueError):
        floor = 30
    if floor > 0:
        try:
            bval = state.get("sensor.ai_llm_budget_remaining")  # noqa: F821
            budget_pct = int(float(bval)) if bval not in (None, "unknown", "unavailable") else 100
        except (TypeError, ValueError):
            budget_pct = 100
        if budget_pct <= floor:
            result = {
                "status": "ok", "op": "summarize_conversations",
                "summaries_created": 0, "entries_processed": 0,
                "message": f"budget_below_floor ({budget_pct}% <= {floor}%)",
                "test_mode": test_mode,
                "elapsed_ms": round((_time.monotonic() - t_start) * 1000, 1),
            }
            _set_result("test" if test_mode else "ok", **result)
            return result

    # ── Process each agent group ──
    summaries_created = 0
    entries_processed = 0
    entries_skipped = 0
    agents_summarized: list[str] = []
    agents_skipped: list[str] = []
    llm_calls = 0
    total_tokens = 0
    budget_exhausted = False

    for agent, entries in sorted(agent_groups.items()):
        if len(entries) < min_conv:
            agents_skipped.append(agent)
            entries_skipped += len(entries)
            continue

        batch = entries[:_SUMMARY_MAX_PER_AGENT]
        prompt = _build_conversation_summary_prompt(batch)

        if test_mode:
            log.info(  # noqa: F821
                f"[{_MODULE}] [TEST]: {agent} ({len(batch)} entries)"
            )
            agents_summarized.append(agent)
            entries_processed += len(batch)
            continue

        # ── LLM call ──
        try:
            llm_entity = llm_instance or "sensor.ha_text_ai"
            llm_result = pyscript.llm_task_call(  # noqa: F821
                prompt=prompt,
                system=_SUMMARY_SYSTEM_PROMPT,
                instance=llm_entity,
                max_tokens=300,
                temperature=0.3,
                priority_tier="essential",  # budget gated by budget_floor above
            )
            resp = await llm_result
        except Exception as exc:
            log.warning(  # noqa: F821
                f"[{_MODULE}] LLM call failed for {agent}: {exc}"
            )
            continue
        llm_calls += 1

        if not resp or resp.get("status") != "ok" or not resp.get("response_text"):
            if resp and resp.get("status") == "budget_exhausted":
                budget_exhausted = True
                break
            log.warning(  # noqa: F821
                f"[{_MODULE}] LLM failed for {agent}: "
                f"{resp.get('status', '?') if resp else 'no_response'}"
            )
            continue

        summary_text = resp["response_text"].strip()
        total_tokens += resp.get("tokens_used", 0)

        # ── Store summary ──
        ts = int(_time.time())
        summary_key = f"{_L2_PREFIX}:summary:{agent}:{ts}"
        summary_tags = f"conversation summary {agent}"

        ok = await _write_to_l2(
            key=summary_key,
            value=summary_text,
            tags=summary_tags,
            scope="household",
            expiration_days=expiry,
        )
        if not ok:
            log.warning(f"[{_MODULE}] L2 write failed for {agent}")  # noqa: F821
            continue

        summaries_created += 1
        agents_summarized.append(agent)

        # ── Post-process source entries ──
        for entry in batch:
            entry_key = entry.get("key", "")
            if not entry_key:
                continue
            if ret_mode == "summary_and_delete":
                await _forget_l2(entry_key)
            elif ret_mode == "summary_and_tag":
                await _tag_entry(entry_key, entry, "summarized")
            # summary_only: leave entries untouched
        entries_processed += len(batch)

    elapsed = round((_time.monotonic() - t_start) * 1000, 1)
    result = {
        "status": "ok", "op": "summarize_conversations",
        "summaries_created": summaries_created,
        "entries_processed": entries_processed,
        "entries_skipped": entries_skipped,
        "agents_summarized": agents_summarized,
        "agents_skipped": agents_skipped,
        "llm_calls": llm_calls,
        "total_tokens": total_tokens,
        "retention_mode": ret_mode,
        "budget_exhausted": budget_exhausted,
        "test_mode": test_mode,
        "elapsed_ms": elapsed,
    }
    _set_result("test" if test_mode else "ok", **result)
    log.info(  # noqa: F821
        f"[{_MODULE}] summarize: created={summaries_created} "
        f"processed={entries_processed} skipped={entries_skipped} "
        f"llm_calls={llm_calls} tokens={total_tokens} {elapsed}ms"
        f"{' [TEST]' if test_mode else ''}"
    )
    return result
