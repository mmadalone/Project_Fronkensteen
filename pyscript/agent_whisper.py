"""Agent Whisper Network — Pattern 5 of Voice Context Architecture (Task 13).

Silent inter-agent context sharing through L2 memory. After every voice
interaction the active agent writes observations (interaction log, mood,
topic) that other agents discover before their next interaction. Zero LLM
calls — pure keyword matching and memory read/write with < 200ms latency.
"""
import json
import re
import time
from datetime import UTC, datetime
from typing import Any

from shared_utils import build_result_entity_name

# =============================================================================
# Agent Whisper Network — Pattern 5 of Voice Context Architecture (Task 13)
# =============================================================================
# Silent inter-agent context sharing through L2 memory. After every voice
# interaction, the active agent writes observations (interaction log, mood,
# topic) that other agents discover before THEIR next interaction.
#
# Services:
#   pyscript.agent_whisper
#     Post-interaction: write interaction log, mood observation, and topic
#     tracking to L2 memory. Zero LLM calls.
#
#   pyscript.agent_whisper_context
#     Pre-interaction: retrieve recent whisper entries from OTHER agents,
#     returning a concise context string for system prompt injection.
#
# Key design constraints:
#   - Zero LLM calls — pure keyword matching and memory read/write
#   - Async, non-blocking — whisper writes happen AFTER the user hears TTS
#   - < 200ms total added latency
#   - Fire-and-forget: if L2 is slow or down, don't block
#   - Mood dedup: same (agent, mood) pair skipped within 1 hour
#
# Expiration (via memory_set expiration_days):
#   - Interaction logs:  2 days (48h)
#   - Mood observations: 1 day  (24h)
#   - Topic tracking:    3 days (72h)
#
# Dependencies:
#   - pyscript/memory.py (L2: memory_set, memory_search)
#   - packages/ai_test_harness.yaml (test mode toggle)
#
# Deployed: 2026-03-01 | Pipeline-aware: 2026-03-02
# =============================================================================

RESULT_ENTITY = "sensor.ai_whisper_status"
PIPELINE_FILE = "/config/.storage/assist_pipeline.pipelines"
KNOWN_VARIANTS = {"standard", "bedtime"}

# ── Dynamic Cache ────────────────────────────────────────────────────────────
_cache: dict | None = None

# ── Mood Detection Keywords ──────────────────────────────────────────────────
MOOD_KEYWORDS: dict[str, list[str]] = {
    "frustrated": [
        "broken", "doesn't work", "doesnt work", "again", "damn", "ugh",
        "frustrated", "annoyed", "stupid", "useless", "crap", "shit",
        "hell", "dammit", "seriously", "wtf", "why won't",
    ],
    "stressed": [
        "deadline", "late", "hurry", "urgent", "worried", "anxious",
        "stress", "stressed", "pressure", "rush", "asap", "panic",
    ],
    "tired": [
        "tired", "exhausted", "sleep", "can't sleep", "cant sleep",
        "insomnia", "yawn", "sleepy", "fatigue", "wiped", "drained",
    ],
    "happy": [
        "thanks", "awesome", "great", "love it", "perfect", "amazing",
        "fantastic", "excellent", "brilliant", "wonderful", "thank you",
        "nice", "cool", "sweet",
    ],
}

# ── Stop Words for Topic Slug Generation ─────────────────────────────────────
STOP_WORDS: set[str] = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "shall", "can", "may", "might", "must",
    "what", "how", "when", "where", "who", "which", "why",
    "to", "of", "in", "for", "on", "with", "at", "by", "from", "about",
    "into", "through", "during", "before", "after", "above", "below",
    "up", "down", "out", "off", "over", "under",
    "and", "but", "or", "not", "no", "nor", "so", "yet",
    "it", "its", "i", "me", "my", "we", "our", "you", "your",
    "he", "him", "his", "she", "her", "they", "them", "their",
    "this", "that", "these", "those",
    "if", "then", "than", "just", "also", "very", "too",
    "tell", "say", "said", "know", "think", "want", "need", "like",
    "please", "hey", "hi", "hello", "ok", "okay",
    # Automation description verbs (prevent blueprint user_query pollution)
    "delivered", "announced", "proactive", "preset", "conversational",
    "autonomous", "triggered", "started", "escalation", "settling",
    "confirmed", "greeted", "spoke", "executed", "threatened",
    # Conversational prefixes (prevent near-duplicate slugs)
    "let", "set", "much", "get", "got", "put", "run", "use", "make",
    "some", "many", "more", "less", "really", "quite",
}

# ── Tuning defaults (overridden by input_number helpers in ai_whisper package) ─
_DEFAULT_INTERACTION_EXPIRY = 2
_DEFAULT_MOOD_EXPIRY = 1
_DEFAULT_TOPIC_EXPIRY = 3
_DEFAULT_MOOD_DEDUP = 3600
_DEFAULT_MAX_AUTO_KEYWORDS = 30
_DEFAULT_KEYWORD_COOLDOWN = 300


def _read_number(entity_id: str, default: int | float) -> int | float:
    """Read an input_number helper, returning default on any failure."""
    try:
        raw = state.get(entity_id)  # noqa: F821
        if raw and raw not in ("unknown", "unavailable"):
            return int(float(raw))
    except Exception:
        pass
    return default


def _get_interaction_expiry() -> int:
    return _read_number("input_number.ai_whisper_interaction_expiry_days", _DEFAULT_INTERACTION_EXPIRY)


def _get_mood_expiry() -> int:
    return _read_number("input_number.ai_whisper_mood_expiry_days", _DEFAULT_MOOD_EXPIRY)


def _get_topic_expiry() -> int:
    return _read_number("input_number.ai_whisper_topic_expiry_days", _DEFAULT_TOPIC_EXPIRY)


def _get_mood_dedup() -> int:
    return _read_number("input_number.ai_whisper_mood_dedup_seconds", _DEFAULT_MOOD_DEDUP)


def _get_max_auto_keywords() -> int:
    return _read_number("input_number.ai_whisper_max_auto_keywords", _DEFAULT_MAX_AUTO_KEYWORDS)


def _get_keyword_cooldown() -> int:
    return _read_number("input_number.ai_whisper_keyword_cooldown", _DEFAULT_KEYWORD_COOLDOWN)


def _is_whisper_enabled() -> bool:
    try:
        return state.get("input_boolean.ai_whisper_enabled") != "off"  # noqa: F821
    except Exception:
        return True


def _is_mood_detection_enabled() -> bool:
    try:
        return state.get("input_boolean.ai_whisper_mood_detection") != "off"  # noqa: F821
    except Exception:
        return True


# ── Summarization (I-3) ─────────────────────────────────────────────────────
SUMMARY_DEFAULT_EXPIRY_DAYS = 30
SUMMARY_MAX_INTERACTIONS = 50
SUMMARY_MAX_PER_AGENT = 20
_SUMMARY_SYSTEM_PROMPT = (
    "You are a concise interaction log compressor for a smart home system. "
    "Output ONLY the summary — no preamble, no bullet points, no labels. "
    "Write in past tense, third person. Keep it under 100 words."
)

# ── Mood Deduplication ───────────────────────────────────────────────────────
_last_mood_write: dict[tuple[str, str], float] = {}

# ── Keyword Auto-Update ─────────────────────────────────────────────────────
_last_keyword_update: dict[str, float] = {}

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
def _load_pipelines_from_file(pipeline_file: str) -> list:
    """Read the Assist Pipeline JSON file. Returns items list or []."""
    import json as _json
    try:
        with open(pipeline_file, "r") as fh:
            data = _json.load(fh)
        return data.get("data", {}).get("items", [])
    except Exception:
        return []


@pyscript_compile  # noqa: F821
def _build_from_pipelines(
    items: list,
    known_variants: set,
) -> tuple:
    """Derive personas, entity_map, wake_word_map, pipeline_map from pipeline items."""
    personas_set = set()
    entity_map = {}
    pipeline_map = {}

    for item in items:
        engine = item.get("conversation_engine", "")
        if not engine or not engine.startswith("conversation."):
            continue

        name = engine[len("conversation."):]
        if "_" in name:
            prefix, suffix = name.rsplit("_", 1)
            if suffix in known_variants:
                persona, variant = prefix, suffix
            elif suffix.isdigit() and "_" in prefix:
                # Strip HA's numeric suffix (e.g., rick_standard_2 → rick + standard)
                inner_prefix, inner_suffix = prefix.rsplit("_", 1)
                if inner_suffix in known_variants:
                    persona, variant = inner_prefix, inner_suffix
                else:
                    persona, variant = name, "standard"
            else:
                persona, variant = name, "standard"
        else:
            persona, variant = name, "standard"

        personas_set.add(persona)
        entity_map[(persona, variant)] = engine
        pipeline_map[engine] = item

    personas = tuple(sorted(personas_set))
    wake_word_map = {p: p for p in personas}

    return personas, entity_map, wake_word_map, pipeline_map


async def _ensure_cache() -> None:
    """Lazy-load the pipeline cache on first service call."""
    global _cache
    if _cache is not None:
        return

    items = _load_pipelines_from_file(PIPELINE_FILE)
    personas, entity_map, wake_word_map, pipeline_map = _build_from_pipelines(
        items, KNOWN_VARIANTS
    )

    if not personas:
        log.error(  # noqa: F821
            "agent_whisper: no conversation pipelines found in "
            f"{PIPELINE_FILE} — persona validation will reject all agents"
        )

    _cache = {
        "personas": personas,
        "entity_map": entity_map,
        "wake_word_map": wake_word_map,
        "pipeline_map": pipeline_map,
    }

    log.info(  # noqa: F821
        f"agent_whisper: loaded {len(personas)} personas from pipelines"
    )


# ── Pure-Python Sync Helpers ─────────────────────────────────────────────────

@pyscript_compile  # noqa: F821
def _detect_mood(user_query: str, agent_response: str) -> str:
    """Detect mood from user query and agent response via keyword matching.

    Priority order: frustrated > stressed > tired > happy > neutral.
    Scans both user input and agent output for keyword hits.
    """
    combined = f"{user_query} {agent_response}".lower()
    for mood in ("frustrated", "stressed", "tired", "happy"):
        for keyword in MOOD_KEYWORDS[mood]:
            if keyword in combined:
                return mood
    return "neutral"


@pyscript_compile  # noqa: F821
def _extract_topic_slug(user_query: str) -> str:
    """Extract 1-3 keyword topic slug from user query.

    Removes stop words, takes first 2-3 significant words, joins with
    underscore. "How much does a Tesla cost?" → "tesla_cost".
    """
    if not user_query:
        return "general"
    cleaned = re.sub(r"[^\w\s]", "", user_query.lower())
    words = cleaned.split()
    significant = [w for w in words if w not in STOP_WORDS and len(w) > 1]
    if not significant:
        return "general"
    slug_words = significant[:3] if len(significant) >= 3 else significant[:2]
    if not slug_words:
        slug_words = significant[:1]
    return "_".join(slug_words)


@pyscript_compile  # noqa: F821
def _summarize_query(user_query: str, max_len: int = 80) -> str:
    """Truncate user query to a brief summary for log entries."""
    if not user_query:
        return "(no query)"
    q = user_query.strip()
    if len(q) <= max_len:
        return q
    return q[: max_len - 3] + "..."


@pyscript_compile  # noqa: F821
def _check_mood_dedup(
    agent_name: str,
    mood: str,
    now_mono: float,
    last_writes: dict[tuple[str, str], float],
    dedup_seconds: float,
) -> bool:
    """Return True if this (agent, mood) pair was written within dedup window."""
    last_ts = last_writes.get((agent_name, mood), 0.0)
    return (now_mono - last_ts) < dedup_seconds


@pyscript_compile  # noqa: F821
def _is_within_lookback(
    created_at_iso: str,
    lookback_hours: int,
    now_utc_iso: str,
) -> bool:
    """Check if created_at timestamp falls within the lookback window."""
    if not created_at_iso:
        return False
    try:
        created = datetime.fromisoformat(created_at_iso)
        now = datetime.fromisoformat(now_utc_iso)
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        return (now - created).total_seconds() < (lookback_hours * 3600)
    except (ValueError, TypeError):
        return False


@pyscript_compile  # noqa: F821
def _build_context_summary(entries: list[dict[str, Any]]) -> str:
    """Build a concise context string from filtered whisper entries.

    Groups entries into interaction/topic observations and mood notes,
    then formats into a short paragraph for system prompt injection.
    """
    if not entries:
        return ""

    observations = []
    mood_notes = []

    for entry in entries:
        value = entry.get("value", "")
        key = entry.get("key", "")
        tags = entry.get("tags", "")

        # Mood entries have keys like whisper_mood_123 (normalized from
        # whisper:mood:123). Check key prefix to avoid false positives
        # from interaction tags that contain "mood_frustrated" etc.
        if key.startswith("whisper_mood"):
            mood_notes.append(value)
        else:
            observations.append(value)

    parts = []
    if observations:
        parts.append(
            "Recent observations: " + " | ".join(observations[:3]) + "."
        )
    if mood_notes:
        parts.append("Mood notes: " + " | ".join(mood_notes[:2]) + ".")
    return " ".join(parts)


# ── Async L2 Memory Helpers ──────────────────────────────────────────────────

async def _write_to_l2(
    key: str,
    value: str,
    tags: str,
    scope: str = "user",
    expiration_days: int = 2,
    force_new: bool = True,
) -> bool:
    """Write a whisper entry to L2 memory. Swallows errors for resilience."""
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
            f"agent_whisper: L2 write status={resp.get('status', '?')} "
            f"key={key}"
        )
        return False
    except Exception as exc:
        log.warning(  # noqa: F821
            f"agent_whisper: L2 write failed key={key}: {exc}"
        )
        return False


async def _search_l2(query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Search L2 memory for whisper entries. Returns empty list on failure."""
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
            f"agent_whisper: L2 search failed query={query}: {exc}"
        )
    return []


async def _get_l2(key: str) -> str | None:
    """Get a single value from L2 memory by key. Returns value or None."""
    try:
        result = pyscript.memory_get(key=key)  # noqa: F821
        resp = await result
        if resp and resp.get("status") == "ok":
            return resp.get("value")
    except Exception as exc:
        log.warning(  # noqa: F821
            f"agent_whisper: L2 get failed key={key}: {exc}"
        )
    return None


# ── Keyword Auto-Update ─────────────────────────────────────────────────────

async def _auto_update_keywords(agent: str, topic_slug: str, source: str = "user") -> None:
    """Auto-update dispatch keywords for a persona from recent whisper topics.

    - Only considers user-sourced topics (automation/system topics are excluded)
    - Searches L2 for recent topics by this agent
    - Extracts topic slugs and converts to keywords
    - Merges with existing keywords, preserving !-prefixed manual keywords
    - Caps auto keywords at max_auto_keywords config value (oldest drop off)
    - Rate-limited by keyword_update_cooldown config value per agent
    """
    global _last_keyword_update

    try:
        # Rate limit: skip if updated too recently
        now_mono = time.monotonic()
        last_update = _last_keyword_update.get(agent, 0.0)
        if (now_mono - last_update) < _get_keyword_cooldown():
            return

        # Search L2 for recent topics by this agent
        results = await _search_l2(f"whisper topic {agent}", limit=20)

        # Extract topic slugs from matching keys — ONLY user-sourced topics
        topic_slugs = []
        for entry in results:
            key = entry.get("key", "")
            tags = entry.get("tags", "")
            # Skip automation/system-sourced topics — they pollute keywords
            # with automation descriptions like "delivered wake-up alarm"
            if "source_automation" in tags or "source_system" in tags:
                continue
            # Keys are stored as whisper:topic:{slug} but memory_search
            # normalizes colons to underscores in returned keys
            for prefix in ("whisper:topic:", "whisper_topic_"):
                if key.startswith(prefix):
                    slug = key[len(prefix):]
                    if slug and slug != "general":
                        topic_slugs.append(slug)
                    break

        # Add the current topic if not already present (user-sourced only)
        if (topic_slug and topic_slug != "general"
                and topic_slug not in topic_slugs and source == "user"):
            topic_slugs.insert(0, topic_slug)

        if not topic_slugs:
            return

        # Convert slugs to keywords: "tesla_cost" → "tesla cost"
        auto_keywords = []
        seen = set()
        for slug in topic_slugs:
            kw = slug.replace("_", " ")
            if kw not in seen:
                seen.add(kw)
                auto_keywords.append(kw)

        # Deduplicate: collapse "let quantum computing" into "quantum computing"
        # Sort by length ascending so shorter (more general) keywords are kept
        auto_keywords.sort(key=len)
        deduped = []
        deduped_word_sets = []
        for kw in auto_keywords:
            kw_words = set(kw.split())
            # Skip if all words of an existing shorter keyword are in this one
            if any(existing.issubset(kw_words) and existing != kw_words
                   for existing in deduped_word_sets):
                continue
            deduped.append(kw)
            deduped_word_sets.append(kw_words)
        auto_keywords = deduped

        # Load current dispatch_keywords for this agent
        current_raw = await _get_l2(f"dispatch_keywords:{agent}")
        manual_keywords = []
        existing_auto = []

        if current_raw:
            for kw in current_raw.split(","):
                kw = kw.strip()
                if not kw:
                    continue
                if kw.startswith("!"):
                    manual_keywords.append(kw)
                else:
                    existing_auto.append(kw)

        # Merge: new auto keywords first (newest), then existing auto
        # that aren't already in the new list, capped at _get_max_auto_keywords()
        merged_auto = list(auto_keywords)
        for kw in existing_auto:
            if kw not in seen:
                seen.add(kw)
                merged_auto.append(kw)
        merged_auto = merged_auto[:_get_max_auto_keywords()]

        # Combine: manual (!-prefixed) + auto
        merged = manual_keywords + merged_auto
        merged_csv = ",".join(merged)

        # Write back (force_new=True because tag overlap with other entries
        # is expected — "dispatch", "keywords", "rick" are common tags)
        await _write_to_l2(
            key=f"dispatch_keywords:{agent}",
            value=merged_csv,
            tags=f"dispatch keywords {agent}",
            scope="household",
            expiration_days=0,
            force_new=True,
        )

        _last_keyword_update[agent] = now_mono
        log.info(  # noqa: F821
            f"agent_whisper: updated keywords for {agent}: "
            f"{len(manual_keywords)} manual + {len(merged_auto)} auto"
        )
    except Exception as exc:
        log.warning(  # noqa: F821
            f"agent_whisper: keyword auto-update failed for {agent}: {exc}"
        )


# ── Test Mode ────────────────────────────────────────────────────────────────

def _is_test_mode() -> bool:
    try:
        return str(
            state.get("input_boolean.ai_test_mode") or "off"  # noqa: F821
        ).lower() == "on"
    except NameError:
        return False


# ── Main Whisper Service (Post-Interaction) ──────────────────────────────────

@service(supports_response="optional")  # noqa: F821
async def agent_whisper(
    agent_name: str = "",
    user_query: str = "",
    agent_response: str = "",
    interaction_mood: str = "",
    source: str = "user",
):
    """
    yaml
    name: Agent Whisper
    description: >-
      Post-interaction whisper: writes interaction log, mood observation,
      and topic tracking to L2 memory for other agents to discover.
      Zero LLM calls — pure keyword matching and memory write.
      Called AFTER every voice interaction completes.
    fields:
      agent_name:
        name: Agent Name
        description: Which persona just spoke (rick, quark, deepee, kramer).
        required: true
        example: "rick"
        selector:
          text:
      user_query:
        name: User Query
        description: What the user asked.
        required: true
        example: "why isn't the network working again"
        selector:
          text:
      agent_response:
        name: Agent Response
        description: What the agent said back.
        required: false
        default: ""
        selector:
          text:
            multiline: true
      interaction_mood:
        name: Interaction Mood
        description: >-
          Override mood detection. If empty, mood is auto-detected from
          keywords in user_query and agent_response.
          Valid values: neutral, frustrated, stressed, tired, happy.
        required: false
        default: ""
        example: "frustrated"
        selector:
          select:
            options:
              - neutral
              - frustrated
              - stressed
              - tired
              - happy
      source:
        name: Source
        description: >-
          Origin of the interaction. "user" for real voice conversations,
          "automation" for blueprint-initiated actions. Automated entries
          are still logged to L2 but excluded from conversation-facing
          surfaces (hot context, handoff context, last-topic helper).
        required: false
        default: "user"
        example: "automation"
        selector:
          select:
            options:
              - user
              - automation
    """
    if _is_test_mode():
        log.info("agent_whisper [TEST]: would write whisper for agent=%s", agent_name)  # noqa: F821
        return

    if not _is_whisper_enabled():
        return

    global _last_mood_write
    t_start = time.monotonic()

    await _ensure_cache()
    personas = _cache["personas"]

    agent = (agent_name or "").lower().strip()
    if agent not in personas:
        result = {
            "status": "error",
            "op": "agent_whisper",
            "error": f"unknown agent: {agent!r}",
        }
        _set_result("error", **result)
        return result

    query = (user_query or "").strip()
    response = (agent_response or "").strip()

    # ── Test mode ──
    test_mode = state.get("input_boolean.ai_test_mode") == "on"  # noqa: F821

    # ── Mood detection ──
    mood = (interaction_mood or "").lower().strip()
    if mood not in ("neutral", "frustrated", "stressed", "tired", "happy"):
        mood = _detect_mood(query, response) if _is_mood_detection_enabled() else "neutral"

    # ── Source normalization ──
    source = (source or "user").lower().strip()
    if source not in ("user", "automation", "system"):
        source = "user"

    # ── Topic slug ──
    topic_slug = _extract_topic_slug(query)

    # ── Timestamps ──
    now = datetime.now(UTC)
    ts = int(now.timestamp())
    time_str = now.strftime("%H:%M")
    query_summary = _summarize_query(query)

    writes = []
    skipped = []

    # ── 1. INTERACTION LOG (always) ──────────────────────────────────────
    interaction_key = f"whisper:interaction:{ts}"
    interaction_value = f"{agent} responded to '{query_summary}'"
    interaction_tags = f"whisper interaction {agent} mood_{mood} source_{source}"

    if test_mode:
        log.info(  # noqa: F821
            f"agent_whisper [TEST]: WOULD WRITE interaction "
            f"key={interaction_key} value={interaction_value}"
        )
        writes.append({
            "type": "interaction",
            "key": interaction_key,
            "written": False,
            "test_skip": True,
        })
    else:
        ok = await _write_to_l2(
            key=interaction_key,
            value=interaction_value,
            tags=interaction_tags,
            expiration_days=_get_interaction_expiry(),
        )
        writes.append({
            "type": "interaction",
            "key": interaction_key,
            "written": ok,
        })

    # ── 2. MOOD OBSERVATION (when mood != neutral, user interactions only) ─
    if mood != "neutral" and source == "user":
        now_mono = time.monotonic()
        is_dedup = _check_mood_dedup(
            agent, mood, now_mono, _last_mood_write, _get_mood_dedup(),
        )
        if is_dedup:
            skipped.append({"type": "mood", "reason": "dedup_within_1h"})
            if test_mode:
                log.info(  # noqa: F821
                    f"agent_whisper [TEST]: WOULD SKIP mood={mood} "
                    f"from {agent} (dedup within 1h)"
                )
        else:
            mood_key = f"whisper:mood:{ts}"
            mood_value = (
                f"{agent} observed: user seems {mood} — "
                f"context: {query_summary}"
            )
            mood_tags = f"whisper mood {mood} {agent}"

            if test_mode:
                log.info(  # noqa: F821
                    f"agent_whisper [TEST]: WOULD WRITE mood "
                    f"key={mood_key} value={mood_value}"
                )
                writes.append({
                    "type": "mood",
                    "key": mood_key,
                    "written": False,
                    "test_skip": True,
                })
            else:
                ok = await _write_to_l2(
                    key=mood_key,
                    value=mood_value,
                    tags=mood_tags,
                    expiration_days=_get_mood_expiry(),
                )
                if ok:
                    _last_mood_write[(agent, mood)] = now_mono
                writes.append({
                    "type": "mood",
                    "key": mood_key,
                    "written": ok,
                })
    else:
        skipped.append({"type": "mood", "reason": "neutral"})

    # ── 3. TOPIC TRACKING (always) ───────────────────────────────────────
    topic_key = f"whisper:topic:{topic_slug}"
    if source == "user":
        topic_value = (
            f"User discussed {topic_slug.replace('_', ' ')} "
            f"with {agent} at {time_str}"
        )
    else:
        topic_value = (
            f"{agent} ran {topic_slug.replace('_', ' ')} at {time_str}"
        )
    topic_tags = f"whisper topic {topic_slug} {agent} source_{source}"

    if test_mode:
        log.info(  # noqa: F821
            f"agent_whisper [TEST]: WOULD WRITE topic "
            f"key={topic_key} value={topic_value}"
        )
        writes.append({
            "type": "topic",
            "key": topic_key,
            "written": False,
            "test_skip": True,
        })
    else:
        ok = await _write_to_l2(
            key=topic_key,
            value=topic_value,
            tags=topic_tags,
            expiration_days=_get_topic_expiry(),
        )
        writes.append({
            "type": "topic",
            "key": topic_key,
            "written": ok,
        })

    # ── 4. KEYWORD AUTO-UPDATE (non-blocking, after successful writes) ──
    topic_written = False
    for w in writes:
        if w.get("type") == "topic" and w.get("written"):
            topic_written = True
            break
    if not test_mode and topic_written and source == "user":
        try:
            await _auto_update_keywords(agent, topic_slug, source=source)
        except Exception as exc:
            log.warning(f"agent_whisper: keyword update error (non-fatal): {exc}")  # noqa: F821

    # ── 5. UPDATE SELF-AWARENESS HELPERS (fire-and-forget) ──
    if not test_mode and topic_slug and source == "user":
        try:
            service.call(  # noqa: F821
                "input_text", "set_value",
                entity_id="input_text.ai_last_interaction_topic",
                value=topic_slug[:200],
            )
        except Exception:
            pass
    if not test_mode and source == "user":
        try:
            service.call(  # noqa: F821
                "input_text", "set_value",
                entity_id="input_text.ai_last_agent_name",
                value=agent,
            )
            service.call(  # noqa: F821
                "input_datetime", "set_datetime",
                entity_id="input_datetime.ai_last_interaction_time",
                datetime=datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S"),
            )
        except Exception:
            pass

    # ── Banter candidate event (Pattern 1 foundation) ──
    # Only fires for user-sourced interactions with a non-empty response.
    # Ignored if no automation listens. Also serves Patterns 2 + 4.
    if source == "user" and response and not test_mode:
        event.fire(  # noqa: F821
            "ai_banter_candidate",
            agent_name=agent,
            user_query=query,
            agent_response=response,
            mood=mood,
            topic=topic_slug,
        )

    elapsed = round((time.monotonic() - t_start) * 1000, 1)

    result = {
        "status": "ok",
        "op": "agent_whisper",
        "agent": agent,
        "mood": mood,
        "topic": topic_slug,
        "writes": writes,
        "skipped": skipped,
        "test_mode": test_mode,
        "elapsed_ms": elapsed,
    }

    sensor_state = "test" if test_mode else "ok"
    _set_result(sensor_state, **result)
    log.info(  # noqa: F821
        f"agent_whisper: agent={agent} mood={mood} topic={topic_slug} "
        f"writes={len(writes)} skipped={len(skipped)} {elapsed}ms"
        f"{' [TEST]' if test_mode else ''}"
    )
    return result


# ── Whisper Context Retrieval (Pre-Interaction) ─────────────────────────────

@service(supports_response="optional")  # noqa: F821
async def agent_whisper_context(
    agent_name: str = "",
    max_entries: int = 5,
    lookback_hours: int = 24,
):
    """
    yaml
    name: Agent Whisper Context
    description: >-
      Pre-interaction context retrieval. Searches L2 for recent whisper
      entries from OTHER agents, excluding the requesting agent's own
      entries. Returns a concise context string suitable for system
      prompt injection. Zero LLM calls.
    fields:
      agent_name:
        name: Agent Name
        description: Which persona is about to speak (their entries are excluded).
        required: true
        example: "quark"
        selector:
          text:
      max_entries:
        name: Max Entries
        description: Maximum whisper entries to include in context.
        required: false
        default: 5
        example: 5
        selector:
          number:
            min: 1
            max: 20
      lookback_hours:
        name: Lookback Hours
        description: How far back to search for whisper entries.
        required: false
        default: 24
        example: 24
        selector:
          number:
            min: 1
            max: 168
    """
    if _is_test_mode():
        log.info("agent_whisper [TEST]: would retrieve whisper context for agent=%s", agent_name)  # noqa: F821
        return

    t_start = time.monotonic()

    await _ensure_cache()
    personas = _cache["personas"]

    agent = (agent_name or "").lower().strip()
    if agent not in personas:
        result = {
            "status": "error",
            "op": "agent_whisper_context",
            "error": f"unknown agent: {agent!r}",
        }
        _set_result("error", **result)
        return result

    test_mode = state.get("input_boolean.ai_test_mode") == "on"  # noqa: F821

    try:
        max_e = int(max_entries)
    except (TypeError, ValueError):
        max_e = 5
    max_e = max(1, min(max_e, 20))

    try:
        lookback = int(lookback_hours)
    except (TypeError, ValueError):
        lookback = 24
    lookback = max(1, min(lookback, 168))

    # Over-fetch to allow for filtering by agent and freshness
    raw_results = await _search_l2("whisper", limit=max_e * 3)

    # Filter: within lookback window AND not written by requesting agent
    now_utc_iso = datetime.now(UTC).isoformat()
    filtered = []
    for entry in raw_results:
        created_at = entry.get("created_at", "")
        if not _is_within_lookback(created_at, lookback, now_utc_iso):
            continue
        tags = entry.get("tags", "")
        tag_list = tags.split() if tags else []
        if agent in tag_list:
            continue
        if "source_automation" in tag_list:
            continue
        filtered.append(entry)
        if len(filtered) >= max_e:
            break

    context_str = _build_context_summary(filtered)

    elapsed = round((time.monotonic() - t_start) * 1000, 1)

    result = {
        "status": "ok",
        "op": "agent_whisper_context",
        "agent": agent,
        "context": context_str,
        "entry_count": len(filtered),
        "entries": filtered,
        "lookback_hours": lookback,
        "test_mode": test_mode,
        "elapsed_ms": elapsed,
    }

    if test_mode:
        log.info(  # noqa: F821
            f"agent_whisper_context [TEST]: agent={agent} "
            f"entries={len(filtered)} context_len={len(context_str)} "
            f"{elapsed}ms"
        )
        if context_str:
            log.info(  # noqa: F821
                f"agent_whisper_context [TEST]: context: "
                f"{context_str[:300]}"
            )

    sensor_state = "test" if test_mode else "ok"
    _set_result(sensor_state, **result)
    log.info(  # noqa: F821
        f"agent_whisper_context: agent={agent} "
        f"entries={len(filtered)} context_len={len(context_str)} "
        f"{elapsed}ms{' [TEST]' if test_mode else ''}"
    )
    return result


# ── Interaction Summarization (I-3) ──────────────────────────────────────────


@pyscript_compile  # noqa: F821
def _extract_agent_from_tags(tags: str) -> str:
    """Extract agent name from whisper interaction tags.

    Tags format: 'whisper interaction {agent} mood_{mood}'
    """
    if not tags:
        return ""
    skip = {"whisper", "interaction"}
    for part in tags.split():
        if part in skip or part.startswith("mood_"):
            continue
        return part
    return ""


@pyscript_compile  # noqa: F821
def _build_summary_prompt(agent: str, entries: list[dict]) -> str:
    """Build the LLM compression prompt for a batch of interaction entries."""
    lines = []
    for entry in entries:
        value = entry.get("value", "")
        created = entry.get("created_at", "")
        time_str = ""
        if created:
            try:
                dt = datetime.fromisoformat(created)
                time_str = dt.strftime("%H:%M")
            except (ValueError, TypeError):
                pass
        prefix = f"[{time_str}] " if time_str else ""
        source_label = "[AUTO]" if "source_automation" in entry.get("tags", "") else "[USER]"
        lines.append(f"- {prefix}{source_label} {value}")
    interaction_block = "\n".join(lines)
    return (
        f"Compress these {len(entries)} interactions involving the "
        f"'{agent}' assistant into a 2-3 sentence summary. "
        f"Entries marked [AUTO] are automated system actions (briefings, announcements, "
        f"alarms) — the user did NOT initiate these. Entries marked [USER] are real "
        f"voice conversations. Frame accordingly: 'the system delivered' vs 'the user asked'. "
        f"Preserve: any mood shifts (user entries only), recurring topics. "
        f"Drop: timestamps, filler, exact phrasing.\n\n"
        f"Interactions:\n{interaction_block}"
    )


async def _forget_l2(key: str) -> bool:
    """Delete a single L2 entry by key. Swallows errors for resilience."""
    try:
        result = pyscript.memory_forget(key=key)  # noqa: F821
        resp = await result
        return bool(resp and resp.get("status") == "ok")
    except Exception as exc:
        log.warning(f"agent_whisper: L2 forget failed key={key}: {exc}")  # noqa: F821
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
        log.warning(f"agent_whisper: tag update failed key={key}: {exc}")  # noqa: F821
        return False


@service(supports_response="optional")  # noqa: F821
async def summarize_interactions(
    lookback_hours: int = 36,
    min_interactions: int = 3,
    max_interactions: int = 50,
    retention_mode: str = "summary_and_tag",
    summary_expiry_days: int = 30,
    priority_tier: str = "standard",
):
    """
    yaml
    name: Summarize Interactions
    description: >-
      Batch-compress whisper interaction logs into per-agent summaries
      using a cheap LLM call. Stores summaries as new L2 entries with
      long TTL. Called by the interaction_summarizer blueprint.
    fields:
      lookback_hours:
        name: Lookback Hours
        description: Only summarize interactions older than this (hours).
        default: 36
        selector:
          number:
            min: 12
            max: 47
            mode: slider
      min_interactions:
        name: Min Interactions per Agent
        description: Skip agents with fewer unsummarized interactions.
        default: 3
        selector:
          number:
            min: 1
            max: 20
            mode: box
      max_interactions:
        name: Max Interactions per Batch
        description: Total cap on interactions processed in one run.
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
          summary_only: delete sources immediately.
          both: tag as archived, extend TTL.
        default: summary_and_tag
        selector:
          select:
            options:
              - summary_and_tag
              - summary_only
              - both
      summary_expiry_days:
        name: Summary Expiry (days)
        description: How long summaries persist in L2.
        default: 30
        selector:
          number:
            min: 7
            max: 365
            mode: box
      priority_tier:
        name: Priority Tier
        description: LLM budget tier.
        default: standard
        selector:
          select:
            options:
              - essential
              - standard
              - luxury
    """
    if _is_test_mode():
        log.info("agent_whisper [TEST]: would summarize interactions")  # noqa: F821
        return

    t_start = time.monotonic()
    test_mode = state.get("input_boolean.ai_test_mode") == "on"  # noqa: F821

    # ── Validate params ──
    valid_modes = {"summary_and_tag", "summary_only", "both"}
    ret_mode = retention_mode if retention_mode in valid_modes else "summary_and_tag"
    try:
        lookback = max(12, min(int(lookback_hours), 47))
    except (TypeError, ValueError):
        lookback = 36
    try:
        min_int = max(1, min(int(min_interactions), 20))
    except (TypeError, ValueError):
        min_int = 3
    try:
        max_int = max(10, min(int(max_interactions), SUMMARY_MAX_INTERACTIONS))
    except (TypeError, ValueError):
        max_int = 50
    try:
        expiry = max(7, min(int(summary_expiry_days), 365))
    except (TypeError, ValueError):
        expiry = SUMMARY_DEFAULT_EXPIRY_DAYS

    # ── Search L2 for interaction entries ──
    raw = await _search_l2("whisper interaction", limit=max_int * 2)
    if not raw:
        result = {
            "status": "ok", "op": "summarize_interactions",
            "summaries_created": 0, "entries_processed": 0,
            "message": "no_interaction_entries_found", "test_mode": test_mode,
            "elapsed_ms": round((time.monotonic() - t_start) * 1000, 1),
        }
        _set_result("test" if test_mode else "ok", **result)
        return result

    # ── Filter: older than lookback, not already tagged ──
    now_utc = datetime.now(UTC)
    now_utc_iso = now_utc.isoformat()
    candidates = []
    for entry in raw:
        created_at = entry.get("created_at", "")
        tags = entry.get("tags", "")
        tag_set = set(tags.split()) if tags else set()
        if "summarized" in tag_set or "archived" in tag_set:
            continue
        # _is_within_lookback returns True if NEWER than lookback — we want older
        if _is_within_lookback(created_at, lookback, now_utc_iso):
            continue
        candidates.append(entry)
        if len(candidates) >= max_int:
            break

    if not candidates:
        result = {
            "status": "ok", "op": "summarize_interactions",
            "summaries_created": 0, "entries_processed": 0,
            "message": "no_eligible_entries", "test_mode": test_mode,
            "elapsed_ms": round((time.monotonic() - t_start) * 1000, 1),
        }
        _set_result("test" if test_mode else "ok", **result)
        return result

    # ── Group by agent ──
    agent_groups: dict[str, list[dict[str, Any]]] = {}
    for entry in candidates:
        agent = _extract_agent_from_tags(entry.get("tags", ""))
        if agent:
            agent_groups.setdefault(agent, []).append(entry)

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
        if len(entries) < min_int:
            agents_skipped.append(agent)
            entries_skipped += len(entries)
            continue

        batch = entries[:SUMMARY_MAX_PER_AGENT]
        prompt = _build_summary_prompt(agent, batch)

        if test_mode:
            log.info(  # noqa: F821
                f"summarize_interactions [TEST]: {agent} ({len(batch)} entries)"
            )
            agents_summarized.append(agent)
            entries_processed += len(batch)
            continue

        # ── LLM call ──
        try:
            llm_result = pyscript.llm_task_call(  # noqa: F821
                prompt=prompt,
                system=_SUMMARY_SYSTEM_PROMPT,
                max_tokens=300,
                temperature=0.3,
                priority_tier=priority_tier,
            )
            resp = await llm_result
        except Exception as exc:
            log.warning(f"summarize_interactions: LLM call failed for {agent}: {exc}")  # noqa: F821
            continue
        llm_calls += 1

        if not resp or resp.get("status") != "ok" or not resp.get("response_text"):
            if resp and resp.get("status") == "budget_exhausted":
                budget_exhausted = True
                break
            log.warning(  # noqa: F821
                f"summarize_interactions: LLM failed for {agent}: "
                f"{resp.get('status', '?') if resp else 'no_response'}"
            )
            continue

        summary_text = resp["response_text"].strip()
        total_tokens += resp.get("tokens_used", 0)

        # ── Store summary ──
        ts = int(now_utc.timestamp())
        summary_key = f"whisper:summary:{agent}:{ts}"
        summary_tags = f"whisper summary {agent}"

        ok = await _write_to_l2(
            key=summary_key,
            value=summary_text,
            tags=summary_tags,
            scope="user",
            expiration_days=expiry,
        )
        if not ok:
            log.warning(f"summarize_interactions: L2 write failed for {agent}")  # noqa: F821
            continue

        summaries_created += 1
        agents_summarized.append(agent)

        # ── Post-process source entries ──
        for entry in batch:
            entry_key = entry.get("key", "")
            if not entry_key:
                continue
            if ret_mode == "summary_only":
                await _forget_l2(entry_key)
            elif ret_mode == "summary_and_tag":
                await _tag_entry(entry_key, entry, "summarized")
            elif ret_mode == "both":
                await _tag_entry(entry_key, entry, "archived", extend_days=expiry)
        entries_processed += len(batch)

    elapsed = round((time.monotonic() - t_start) * 1000, 1)
    result = {
        "status": "ok", "op": "summarize_interactions",
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
        f"summarize_interactions: created={summaries_created} "
        f"processed={entries_processed} skipped={entries_skipped} "
        f"llm_calls={llm_calls} tokens={total_tokens} {elapsed}ms"
        f"{' [TEST]' if test_mode else ''}"
    )
    return result


# ── Agent Self-Report Tool (Fix 4 — Gap 3) ───────────────────────────────────

INTERACTION_LOG_KEY_PREFIX = "whisper_selflog"


@service(supports_response="optional")  # noqa: F821
async def agent_interaction_log(
    agent_name: str = "",
    topic: str = "",
    user_intent: str = "",
    source: str = "user",
):
    """
    yaml
    name: Agent Interaction Log
    description: >-
      Self-report tool for agents: log what was just discussed.
      Called by Extended OpenAI agents via tool function after each response.
      Writes whisper entry to L2 + updates self-awareness helpers.
      Zero LLM cost — the agent already has the context.
    fields:
      agent_name:
        name: Agent Name
        description: Which agent is reporting.
        required: true
        example: "rick"
        selector:
          text:
      topic:
        name: Topic
        description: 2-5 word summary of what was discussed.
        required: true
        example: "workshop lights"
        selector:
          text:
      user_intent:
        name: User Intent
        description: Brief description of what the user wanted.
        required: false
        example: "turn on lights"
        selector:
          text:
      source:
        name: Source
        description: >-
          Whether this interaction was user-initiated or automated.
          Automation entries are excluded from mood detection and
          labeled differently in summaries.
        required: false
        default: "user"
        example: "automation"
        selector:
          select:
            options:
              - user
              - automation
    """
    if _is_test_mode():
        log.info("agent_whisper [TEST]: would log interaction for agent=%s topic=%s", agent_name, topic)  # noqa: F821
        return

    if not _is_whisper_enabled():
        return

    t_start = time.monotonic()

    await _ensure_cache()
    personas = _cache["personas"]

    agent = (agent_name or "").lower().strip()
    if agent not in personas:
        result = {
            "status": "error",
            "op": "agent_interaction_log",
            "error": f"unknown agent: {agent!r}",
        }
        _set_result("error", **result)
        return result

    topic_str = (topic or "").strip()
    if not topic_str:
        result = {
            "status": "error",
            "op": "agent_interaction_log",
            "error": "topic is required",
        }
        _set_result("error", **result)
        return result

    intent_str = (user_intent or "").strip()
    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    entry_key = f"{INTERACTION_LOG_KEY_PREFIX}_{agent}_{ts}"

    value_parts = [f"[{agent}] topic: {topic_str}"]
    if intent_str:
        value_parts.append(f"intent: {intent_str}")
    entry_value = " | ".join(value_parts)

    src = (source or "user").lower().strip()
    if src not in ("user", "automation"):
        src = "user"
    tags = f"whisper interaction {agent} selflog source_{src}"

    ok = await _write_to_l2(
        key=entry_key,
        value=entry_value,
        tags=tags,
        expiration_days=_get_interaction_expiry(),
    )

    # Update self-awareness helpers (user interactions only)
    if src == "user":
        try:
            service.call(  # noqa: F821
                "input_text", "set_value",
                entity_id="input_text.ai_last_interaction_topic",
                value=topic_str[:200],
            )
            service.call(  # noqa: F821
                "input_text", "set_value",
                entity_id="input_text.ai_last_agent_name",
                value=agent,
            )
            service.call(  # noqa: F821
                "input_datetime", "set_datetime",
                entity_id="input_datetime.ai_last_interaction_time",
                datetime=datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S"),
            )
        except Exception:
            pass

    elapsed = round((time.monotonic() - t_start) * 1000, 1)

    result = {
        "status": "ok" if ok else "partial",
        "op": "agent_interaction_log",
        "agent": agent,
        "topic": topic_str,
        "written": ok,
        "elapsed_ms": elapsed,
    }
    _set_result("ok" if ok else "warn", **result)
    log.info(  # noqa: F821
        f"agent_interaction_log: agent={agent} topic={topic_str!r} "
        f"written={ok} {elapsed}ms"
    )
    return result


# ── Handoff Context Entity (Fix 1 — var.ai_handoff_context) ──────────────────

HANDOFF_CONTEXT_ENTITY = "var.ai_handoff_context"
HANDOFF_CONTEXT_L2_KEY = "handoff_context_persist"


async def _save_handoff_context(context_str: str):
    """Save handoff context to var entity + L2 for restart persistence."""
    state.set(  # noqa: F821
        HANDOFF_CONTEXT_ENTITY,
        value=context_str or "",
        new_attributes={
            "friendly_name": "AI Handoff Context",
            "icon": "mdi:swap-horizontal",
        },
    )
    # Persist to L2 for restart recovery
    await _write_to_l2(
        key=HANDOFF_CONTEXT_L2_KEY,
        value=context_str or "",
        tags="whisper handoff_context",
        expiration_days=1,
        force_new=True,
    )


@service(supports_response="optional")  # noqa: F821
async def save_handoff_context(context: str = ""):
    """Save cross-agent handoff context to var entity + L2 for persistence."""
    if _is_test_mode():
        log.info("agent_whisper [TEST]: would save handoff context")  # noqa: F821
        return

    await _save_handoff_context(context or "")
    return {"status": "ok", "op": "save_handoff_context"}


# ── Startup ──────────────────────────────────────────────────────────────────

@time_trigger("startup")  # noqa: F821
async def agent_whisper_startup():
    """Initialize whisper network sensor on HA startup."""
    _ensure_result_entity_name(force=True)
    _set_result("idle", op="startup")
    # Restore handoff context from L2
    try:
        persisted = await _get_l2(HANDOFF_CONTEXT_L2_KEY)
        state.set(  # noqa: F821
            HANDOFF_CONTEXT_ENTITY,
            value=persisted or "",
            new_attributes={
                "friendly_name": "AI Handoff Context",
                "icon": "mdi:swap-horizontal",
            },
        )
    except Exception:
        pass
    log.info("agent_whisper.py loaded — whisper network idle")  # noqa: F821


# ── One-Shot: Re-tag stale automation entries ──────────────────────────────

# Known automation patterns (from script blueprint whisper calls).
# Matched against the entry value (case-insensitive substring).
_AUTOMATION_PATTERNS = (
    "goodnight negotiator",
    "announce music follow me",
    "music follow me announcement",
    "rick wake-up yell",
    "randomizer selected agent",
    "replayed",
    "notification from",
    "goodnight routine music assistant",
    "bedtime interaction",
)


@service(supports_response="only")  # noqa: F821
async def whisper_retag_automation(
    dry_run=None,
):
    """
    yaml
    name: Whisper Re-tag Automation Entries
    description: >-
      One-shot cleanup: find existing whisper interaction entries whose values
      match known automation patterns but lack the source_automation tag,
      and re-tag them. Run with dry_run=true first to preview.
    fields:
    """
    if _is_test_mode():
        log.info("agent_whisper [TEST]: would retag automation entries")  # noqa: F821
        return {"status": "test_mode_skip"}

    try:
        if dry_run is None:
            dry_run = True
        dry_run = bool(dry_run)
        t_start = time.monotonic()
        raw = await _search_l2("whisper interaction", limit=200)

        matched = []
        skipped = 0
        already_tagged = 0

        for entry in raw:
            tags = entry.get("tags", "")
            if "source_automation" in tags:
                already_tagged += 1
                continue
            value_lower = (entry.get("value", "") or "").lower()
            hit = False
            for pat in _AUTOMATION_PATTERNS:
                if pat in value_lower:
                    hit = True
                    break
            if not hit:
                skipped += 1
                continue
            matched.append(entry)

        retagged = 0
        failed = 0
        if not dry_run:
            for entry in matched:
                ok = await _tag_entry(
                    key=entry.get("key", ""),
                    entry=entry,
                    new_tag="source_automation",
                )
                if ok:
                    retagged += 1
                else:
                    failed += 1

        elapsed = round((time.monotonic() - t_start) * 1000, 1)
        result = {
            "status": "ok",
            "op": "whisper_retag_automation",
            "dry_run": dry_run,
            "scanned": len(raw),
            "already_tagged": already_tagged,
            "matched": len(matched),
            "retagged": retagged,
            "failed": failed,
            "skipped": skipped,
            "elapsed_ms": elapsed,
        }
        if dry_run and matched:
            result["preview"] = [
                {"key": e.get("key", ""), "value": (e.get("value", "") or "")[:120]}
                for e in matched[:20]
            ]
        log.info(  # noqa: F821
            f"whisper_retag_automation: scanned={len(raw)} matched={len(matched)} "
            f"retagged={retagged} failed={failed} already={already_tagged} "
            f"skipped={skipped} dry_run={dry_run} {elapsed}ms"
        )
        return result
    except Exception as exc:
        log.error(f"whisper_retag_automation failed: {exc}")  # noqa: F821
        return {"status": "error", "op": "whisper_retag_automation", "error": str(exc)}
