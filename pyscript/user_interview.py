"""I-36: User Preference Interview Engine.

Provides services for agent-driven conversational onboarding — LLM agents
call save_user_preference to persist answers to L1 helpers (known keys like
wake time) or L2 memory (freeform preferences). Tracks interview progress
per user in a JSON helper and exposes status for agents to decide what to ask.
"""
import json
import time
from datetime import datetime
from typing import Any

from shared_utils import build_result_entity_name, get_person_slugs, load_entity_config

# =============================================================================
# User Preference Interview Engine — I-36
# =============================================================================
# Conversational onboarding: agents ask about user preferences and save
# responses to L1 helpers or L2 memory via tool calls.
#
# Services:
#   pyscript.user_interview_save
#     Save a user preference. Called by LLM agents via tool function during
#     interview conversations. Routes to L1 helper or L2 memory based on
#     category/key mapping.
#
#   pyscript.user_interview_status
#     Return interview progress — which categories are filled vs empty.
#     Called by agents to know what to ask next.
#
#   pyscript.user_interview_reset
#     Clear all interview data for a user (L2 preference keys + progress).
#
# Design:
#   - Agent-driven: the LLM conducts the interview naturally using its
#     system prompt + hot context guidance. No pyscript-driven loops.
#   - Tool function: agents call save_user_preference to persist data.
#   - L1 map: known helpers (wake time, bedtime, etc.) get set directly.
#   - L2 fallback: everything else → preference:{category}:{key}:{user}
#   - Progress: JSON in input_text.ai_interview_progress tracks what's done.
#   - Interview mode: input_boolean.ai_interview_mode gates hot context.
#
# Dependencies:
#   - pyscript/memory.py (L2: memory_set, memory_search)
#   - packages/ai_user_interview.yaml (helpers)
#   - packages/ai_context_hot.yaml (interview mode injection)
#
# Deployed: 2026-03-11
# =============================================================================

RESULT_ENTITY = "sensor.ai_user_interview_status"

# ── L1 Mapping ──────────────────────────────────────────────────────────────
# Preferences that map to existing HA helpers. {user} is replaced at runtime.
# Format: (category, key) → entity_id template

_L1_MAP = {
    ("identity", "name"): "input_text.ai_context_user_name_{user}",
    ("identity", "name_spoken"): "input_text.ai_context_user_name_spoken_{user}",
    ("identity", "languages"): "input_text.ai_context_user_languages_{user}",
    ("household", "members"): "input_text.ai_context_household",
    ("household", "pets"): "input_text.ai_context_pets",
    ("work", "calendar_keywords"): "input_text.ai_work_calendar_keywords",
}

# L1 entities that need input_select.select_option instead of input_text.set_value
_L1_SELECT_MAP = {
    ("identity", "preferred_language"): "input_select.ai_context_preferred_language_{user}",
}

# L1 entities that need input_datetime.set_datetime (time-only: HH:MM:SS)
_L1_DATETIME_MAP = {
    ("schedule", "wake_weekday"): "input_datetime.ai_context_wake_time_weekday_{user}",
    ("schedule", "wake_weekend"): "input_datetime.ai_context_wake_time_weekend_{user}",
    ("schedule", "bedtime"): "input_datetime.ai_context_bed_time_{user}",
}

# ── Interview Categories ────────────────────────────────────────────────────
# Ordered list of categories with their data points.
# Used by user_interview_status to report progress.

CATEGORIES = {
    "identity": [
        "name", "name_spoken", "languages", "preferred_language",
        "nickname", "birthday",
    ],
    "household": [
        "members", "pets", "guests",
    ],
    "work": [
        "location", "hybrid_schedule", "hours", "commute",
        "calendar_keywords",
    ],
    "schedule": [
        "wake_weekday", "wake_weekend", "bedtime",
        "meal_times", "nap", "exercise",
    ],
    "health": [
        "diet", "caffeine_cutoff", "medical",
    ],
    "environment": [
        "climate", "lighting", "tts_volume", "sleep_sounds",
    ],
    "media": [
        "genres", "streaming", "news", "sports",
        "audiobooks", "podcasts",
    ],
    "communication": [
        "persona", "verbosity", "humor",
        "notify_threshold", "language_context",
    ],
    "privacy": [
        "off_limits_topics", "proactive_comfort",
    ],
}

# All category names in interview order
CATEGORY_ORDER = [
    "identity", "household", "work", "schedule", "health",
    "environment", "media", "communication", "privacy",
]

# ── Module-Level State ───────────────────────────────────────────────────────

def _get_first_person() -> str:
    """Return first person slug from discover_persons() (Task 22)."""
    slugs = get_person_slugs()
    return slugs[0] if slugs else "miquel"


result_entity_name: dict[str, str] = {}


# ── Entity Name Helpers (standard pattern) ───────────────────────────────────

def _ensure_result_entity_name(force: bool = False) -> None:
    global result_entity_name
    if force or not result_entity_name:
        result_entity_name = build_result_entity_name(RESULT_ENTITY)


def _set_result(state_value: str = "ok", **attrs: Any) -> None:
    _ensure_result_entity_name()
    attrs.update(result_entity_name)
    state.set(RESULT_ENTITY, value=state_value, new_attributes=attrs)  # noqa: F821


# ── L1 Value Detection ─────────────────────────────────────────────────────

_EMPTY_STATES = {"unknown", "unavailable", "", "None"}


def _l1_has_value(entity_id: str, domain_hint: str = "text") -> bool:
    """Check if an L1 helper has a meaningful (non-empty) value."""
    val = state.get(entity_id)  # noqa: F821
    if val is None or str(val) in _EMPTY_STATES:
        return False
    if domain_hint == "datetime" and str(val) == "00:00:00":
        return False
    if domain_hint == "text" and str(val).strip() == "":
        return False
    return True


# ── Progress Tracking ────────────────────────────────────────────────────────

def _load_progress(user: str) -> dict:
    """Load interview progress from helper. Returns {category: [keys_done]}."""
    try:
        raw = state.get("input_text.ai_interview_progress") or "{}"  # noqa: F821
        if raw in ("unknown", "unavailable", ""):
            return {}
        all_progress = json.loads(raw)
        user_progress = all_progress.get(user, {})
        # Expand compacted "*" wildcards back to full key lists
        for cat, val in list(user_progress.items()):
            if val == "*":
                user_progress[cat] = list(CATEGORIES.get(cat, []))
        return user_progress
    except (json.JSONDecodeError, Exception):
        return {}


def _save_progress(user: str, progress: dict) -> None:
    """Save interview progress to helper."""
    try:
        raw = state.get("input_text.ai_interview_progress") or "{}"  # noqa: F821
        if raw in ("unknown", "unavailable", ""):
            all_progress = {}
        else:
            all_progress = json.loads(raw)
    except (json.JSONDecodeError, Exception):
        all_progress = {}

    # Compact fully-complete categories to "*" to stay under 255 chars
    compacted = {}
    for cat, keys in progress.items():
        if isinstance(keys, list) and set(keys) >= set(CATEGORIES.get(cat, [])):
            compacted[cat] = "*"
        else:
            compacted[cat] = keys
    all_progress[user] = compacted

    try:
        service.call(  # noqa: F821
            "input_text", "set_value",
            entity_id="input_text.ai_interview_progress",
            value=json.dumps(all_progress, separators=(",", ":"))[:255],
        )
    except Exception as exc:
        log.warning(f"user_interview: progress save failed: {exc}")  # noqa: F821


def _mark_done(user: str, category: str, key: str) -> None:
    """Mark a specific key as completed in progress tracking."""
    progress = _load_progress(user)
    if category not in progress:
        progress[category] = []
    if key not in progress[category]:
        progress[category].append(key)
    _save_progress(user, progress)


# ── L2 Memory Helper ────────────────────────────────────────────────────────

async def _l2_set(
    key: str, value: str, tags: str,
    scope: str = "user", expiration_days: int = 365,
) -> bool:
    """Write preference to L2. Long expiry — preferences are semi-permanent."""
    try:
        result = pyscript.memory_set(  # noqa: F821
            key=key, value=value, scope=scope,
            expiration_days=expiration_days,
            tags=tags, force_new=True,
        )
        resp = await result
        return resp is not None and resp.get("status") == "ok"
    except Exception as exc:
        log.warning(f"user_interview: L2 set failed key={key}: {exc}")  # noqa: F821
        return False


# ── L1 Save Helpers ──────────────────────────────────────────────────────────

def _save_to_l1_text(entity_id: str, value: str) -> bool:
    """Save to an input_text helper."""
    try:
        service.call(  # noqa: F821
            "input_text", "set_value",
            entity_id=entity_id, value=str(value)[:255],
        )
        return True
    except Exception as exc:
        log.warning(f"user_interview: L1 text save failed {entity_id}: {exc}")  # noqa: F821
        return False


def _save_to_l1_select(entity_id: str, value: str) -> bool:
    """Save to an input_select helper."""
    try:
        service.call(  # noqa: F821
            "input_select", "select_option",
            entity_id=entity_id, option=value,
        )
        return True
    except Exception as exc:
        log.warning(f"user_interview: L1 select save failed {entity_id}: {exc}")  # noqa: F821
        return False


def _save_to_l1_datetime(entity_id: str, value: str) -> bool:
    """Save to an input_datetime helper. Expects HH:MM or HH:MM:SS."""
    try:
        # Normalize to HH:MM:SS
        parts = value.strip().split(":")
        if len(parts) == 2:
            value = f"{parts[0]}:{parts[1]}:00"
        service.call(  # noqa: F821
            "input_datetime", "set_datetime",
            entity_id=entity_id, time=value,
        )
        return True
    except Exception as exc:
        log.warning(f"user_interview: L1 datetime save failed {entity_id}: {exc}")  # noqa: F821
        return False


# ── Core Save Logic ──────────────────────────────────────────────────────────

async def _save_preference(
    user: str, category: str, key: str, value: str,
) -> dict:
    """Route a preference to the right storage (L1 or L2).

    Returns dict with status, target, and whether it was L1 or L2.
    """
    user_lower = user.lower().strip()
    cat_lower = category.lower().strip()
    key_lower = key.lower().strip()
    lookup = (cat_lower, key_lower)

    # ── Try L1 text map ──
    if lookup in _L1_MAP:
        entity_tpl = _L1_MAP[lookup]
        entity_id = entity_tpl.replace("{user}", user_lower)
        ok = _save_to_l1_text(entity_id, value)
        if ok:
            _mark_done(user_lower, cat_lower, key_lower)
        return {
            "status": "ok" if ok else "error",
            "target": "l1_text",
            "entity_id": entity_id,
            "saved": ok,
        }

    # ── Try L1 select map ──
    if lookup in _L1_SELECT_MAP:
        entity_tpl = _L1_SELECT_MAP[lookup]
        entity_id = entity_tpl.replace("{user}", user_lower)
        ok = _save_to_l1_select(entity_id, value)
        if ok:
            _mark_done(user_lower, cat_lower, key_lower)
        return {
            "status": "ok" if ok else "error",
            "target": "l1_select",
            "entity_id": entity_id,
            "saved": ok,
        }

    # ── Try L1 datetime map ──
    if lookup in _L1_DATETIME_MAP:
        entity_tpl = _L1_DATETIME_MAP[lookup]
        entity_id = entity_tpl.replace("{user}", user_lower)
        ok = _save_to_l1_datetime(entity_id, value)
        if ok:
            _mark_done(user_lower, cat_lower, key_lower)
        return {
            "status": "ok" if ok else "error",
            "target": "l1_datetime",
            "entity_id": entity_id,
            "saved": ok,
        }

    # ── Fallback: L2 memory ──
    l2_key = f"preference:{cat_lower}:{key_lower}:{user_lower}"
    l2_tags = f"preference {cat_lower} {user_lower}"
    ok = await _l2_set(l2_key, value, l2_tags)
    if ok:
        _mark_done(user_lower, cat_lower, key_lower)
    return {
        "status": "ok" if ok else "error",
        "target": "l2",
        "l2_key": l2_key,
        "saved": ok,
    }


# ── Test Mode ────────────────────────────────────────────────────────────────

def _is_test_mode() -> bool:
    try:
        return str(
            state.get("input_boolean.ai_test_mode") or "off"  # noqa: F821
        ).lower() == "on"
    except NameError:
        return False


# ── Services ─────────────────────────────────────────────────────────────────

@service(supports_response="only")  # noqa: F821
async def user_interview_save(
    user: str = "",
    category: str = "",
    key: str = "",
    value: str = "",
):
    """
    yaml
    name: User Interview Save
    description: >-
      Save a user preference during an interview conversation. Routes to the
      appropriate L1 helper or L2 memory based on category and key. Called by
      LLM agents via the save_user_preference tool function.
    fields:
      user:
        name: User
        description: "Username (e.g., miquel, jessica)"
        default: miquel
        selector:
          text: {}
      category:
        name: Category
        description: >-
          Preference category: identity, household, work, schedule, health,
          environment, media, communication, privacy
        selector:
          text: {}
      key:
        name: Key
        description: >-
          Preference key within the category (e.g., name, wake_weekday,
          diet, genres, persona). Use snake_case.
        selector:
          text: {}
      value:
        name: Value
        description: "The preference value to save"
        selector:
          text:
            multiline: true
    """
    if not user:
        user = _get_first_person()

    if _is_test_mode():
        log.info("user_interview [TEST]: would save preference %s.%s for %s", category, key, user)  # noqa: F821
        return {"status": "test_mode_skip"}

    if not category or not key or not value:
        return {"status": "error", "reason": "missing_fields"}

    t_start = time.monotonic()

    result = await _save_preference(user, category, key, value)

    elapsed = round((time.monotonic() - t_start) * 1000, 1)
    result["elapsed_ms"] = elapsed
    result["user"] = user
    result["category"] = category
    result["key"] = key

    log.info(  # noqa: F821
        f"user_interview: saved {category}.{key} for {user} "
        f"→ {result.get('target')} "
        f"({'ok' if result.get('saved') else 'FAILED'}) "
        f"{elapsed}ms"
    )

    return result


@service(supports_response="only")  # noqa: F821
async def user_interview_status(user: str = ""):
    """
    yaml
    name: User Interview Status
    description: >-
      Return interview progress for a user. Shows which categories and keys
      have been filled vs are still empty. Use this to know what to ask next.
    fields:
      user:
        name: User
        description: "Username (e.g., miquel, jessica)"
        default: miquel
        selector:
          text: {}
    """
    if not user:
        user = _get_first_person()

    if _is_test_mode():
        log.info("user_interview [TEST]: would return interview status for %s", user)  # noqa: F821
        return {"status": "test_mode_skip"}

    user_lower = user.lower().strip()
    progress = _load_progress(user_lower)

    categories_status = {}
    total_keys = 0
    filled_keys = 0
    next_category = None
    next_keys = []

    for cat in CATEGORY_ORDER:
        keys = CATEGORIES.get(cat, [])
        done = progress.get(cat, [])
        remaining = [k for k in keys if k not in done]

        total_keys += len(keys)
        filled_keys += len(done)

        categories_status[cat] = {
            "total": len(keys),
            "done": len(done),
            "remaining": remaining,
            "complete": len(remaining) == 0,
        }

        # Track first incomplete category
        if remaining and next_category is None:
            next_category = cat
            next_keys = remaining

    completion_pct = round(filled_keys / total_keys * 100) if total_keys else 0

    result = {
        "status": "ok",
        "user": user_lower,
        "completion_pct": completion_pct,
        "filled": filled_keys,
        "total": total_keys,
        "next_category": next_category,
        "next_keys": next_keys,
        "categories": categories_status,
    }

    _set_result("ok", **{
        k: v for k, v in result.items() if k != "categories"
    })

    return result


@service(supports_response="only")  # noqa: F821
async def user_interview_reset(user: str = ""):
    """
    yaml
    name: User Interview Reset
    description: >-
      Reset interview progress for a user. Clears the progress tracker
      but does NOT delete saved preferences from L1/L2. Use this to
      re-interview a user.
    fields:
      user:
        name: User
        description: "Username (e.g., miquel, jessica)"
        default: miquel
        selector:
          text: {}
    """
    if not user:
        user = _get_first_person()

    if _is_test_mode():
        log.info("user_interview [TEST]: would reset interview progress for %s", user)  # noqa: F821
        return {"status": "test_mode_skip"}

    user_lower = user.lower().strip()
    _save_progress(user_lower, {})

    log.info(f"user_interview: reset progress for {user_lower}")  # noqa: F821

    return {
        "status": "ok",
        "user": user_lower,
        "action": "reset",
    }


# ── Pre-Seed Service ─────────────────────────────────────────────────────────

@service(supports_response="only")  # noqa: F821
async def user_interview_preseed(user: str = ""):
    """
    yaml
    name: User Interview Preseed
    description: >-
      Scan L1 helpers and L2 memory for existing answers and pre-mark them
      as done in interview progress. Call before the first interview question
      so the agent skips topics the user already answered casually.
    fields:
      user:
        name: User
        description: "Username (e.g., miquel, jessica)"
        default: miquel
        selector:
          text: {}
    """
    if not user:
        user = _get_first_person()

    if _is_test_mode():
        log.info("user_interview [TEST]: would preseed interview for %s", user)  # noqa: F821
        return {"status": "test_mode_skip"}

    user_lower = user.lower().strip()
    t_start = time.monotonic()

    progress = _load_progress(user_lower)
    seeded = []
    already_done = 0
    checked = 0

    # ── L1 scan ──
    all_l1_maps = {
        **{k: ("text", v) for k, v in _L1_MAP.items()},
        **{k: ("select", v) for k, v in _L1_SELECT_MAP.items()},
        **{k: ("datetime", v) for k, v in _L1_DATETIME_MAP.items()},
    }

    for cat in CATEGORY_ORDER:
        keys = CATEGORIES.get(cat, [])
        done_keys = progress.get(cat, [])
        for key in keys:
            checked += 1
            if key in done_keys:
                already_done += 1
                continue
            lookup = (cat, key)
            if lookup in all_l1_maps:
                domain_hint, entity_tpl = all_l1_maps[lookup]
                entity_id = entity_tpl.replace("{user}", user_lower)
                if _l1_has_value(entity_id, domain_hint):
                    _mark_done(user_lower, cat, key)
                    seeded.append({"category": cat, "key": key, "source": "l1"})

    # ── L2 batch scan ──
    # Build set of keys that are L1-mapped (already checked above)
    l1_keys = set(all_l1_maps.keys())

    try:
        result = pyscript.memory_search(  # noqa: F821
            query=f"preference {user_lower}", limit=50,
        )
        resp = await result
        l2_results = resp if isinstance(resp, list) else resp.get("results", [])
    except Exception as exc:
        log.warning(f"user_interview: preseed L2 search failed: {exc}")  # noqa: F821
        l2_results = []

    # Build a dict of L2 keys → status for fast lookup
    l2_found = {}
    for entry in l2_results:
        l2_key = entry.get("key", "")
        l2_status = entry.get("status", "")
        l2_value = entry.get("value", "")
        if l2_key and l2_value and l2_status in ("ok", "expired"):
            l2_found[l2_key] = True

    # Refresh progress (L1 seeding may have updated it)
    progress = _load_progress(user_lower)

    for cat in CATEGORY_ORDER:
        keys = CATEGORIES.get(cat, [])
        done_keys = progress.get(cat, [])
        for key in keys:
            if key in done_keys:
                continue
            if (cat, key) in l1_keys:
                continue  # Already checked via L1
            l2_key = f"preference:{cat}:{key}:{user_lower}"
            if l2_key in l2_found:
                _mark_done(user_lower, cat, key)
                seeded.append({"category": cat, "key": key, "source": "l2"})

    elapsed = round((time.monotonic() - t_start) * 1000, 1)
    seeded_count = len(seeded)

    log.info(  # noqa: F821
        f"user_interview: preseed for {user_lower} — "
        f"{seeded_count} seeded, {already_done} already done, "
        f"{checked} checked, {elapsed}ms"
    )

    return {
        "status": "ok",
        "user": user_lower,
        "seeded_count": seeded_count,
        "already_done": already_done,
        "checked": checked,
        "seeded": seeded,
        "elapsed_ms": elapsed,
    }


# ── Startup ──────────────────────────────────────────────────────────────────

@time_trigger("startup")  # noqa: F821
async def _startup():
    """Initialize user interview status sensor."""
    _ensure_result_entity_name(force=True)
    _set_result("idle", op="startup")
    log.info("user_interview.py loaded")  # noqa: F821
