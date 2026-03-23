"""Shared Utilities: L2 Cache, Memory PyCache, Budget Tracking, LLM Task Calls.

Provides the common infrastructure layer used by all other pyscript modules:
SQLite-backed L2 memory cache with per-key locking, memory_pycache for fast
in-process reads, I-33 per-agent budget breakdown tracking via
pyscript.budget_track_call, and the ha_text_ai LLM wrapper for tool-free
text generation.
"""
import asyncio
import json
import sqlite3
import struct
import threading
import time
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any

import aiohttp
import orjson

TTL = 300  # The Conversation ID retention period in Home Assistant is set to a fixed 5 minutes of idle time and cannot be modified.
DB_PATH = Path("/config/cache.db")

_CACHE_READY = False
_CACHE_READY_LOCK = threading.Lock()
_INDEX_LOCKS: dict[str, asyncio.Lock] = {}
_INDEX_LOCKS_COUNTS: dict[str, int] = {}
_INDEX_LOCKS_GUARD = threading.Lock()  # threading.Lock (not asyncio) is intentional:
# Guards only O(1) dict ops (no I/O, no await) — held for microseconds.
# asyncio.Lock would require all callers to be async; some aren't.
# The real async serialisation happens via the per-key asyncio.Lock in _INDEX_LOCKS.


class _IndexLockContext:
    def __init__(self, key: str):
        self.key = key
        self.lock = None

    async def __aenter__(self):
        key = self.key
        with _INDEX_LOCKS_GUARD:
            if key not in _INDEX_LOCKS:
                _INDEX_LOCKS[key] = asyncio.Lock()
                _INDEX_LOCKS_COUNTS[key] = 0
            _INDEX_LOCKS_COUNTS[key] += 1
            self.lock = _INDEX_LOCKS[key]

        await self.lock.acquire()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.lock:
            self.lock.release()

        key = self.key
        with _INDEX_LOCKS_GUARD:
            if key in _INDEX_LOCKS_COUNTS:
                _INDEX_LOCKS_COUNTS[key] -= 1
                if _INDEX_LOCKS_COUNTS[key] <= 0:
                    _INDEX_LOCKS.pop(key, None)
                    _INDEX_LOCKS_COUNTS.pop(key, None)


def _acquire_index_lock(key: str):
    return _IndexLockContext(key)


@pyscript_compile  # noqa: F821
def _get_db_connection() -> sqlite3.Connection:
    """Establish a database connection with optimized settings."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA temp_store=MEMORY;")
    conn.execute("PRAGMA busy_timeout=3000;")
    return conn


@pyscript_compile  # noqa: F821
def _ensure_cache_db() -> None:
    """Create the cache database directory, SQLite file, and schema if they do not already exist."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with closing(_get_db_connection()) as conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cache_entries
            (
                key        TEXT PRIMARY KEY,
                value      TEXT    NOT NULL,
                expires_at INTEGER NOT NULL
            )
            """
        )
        conn.commit()


@pyscript_compile  # noqa: F821
def _ensure_cache_db_once(force: bool = False) -> None:
    """Ensure the cache database exists, optionally forcing a rebuild."""
    global _CACHE_READY
    if force:
        _CACHE_READY = False
    if _CACHE_READY and DB_PATH.exists():
        return
    with _CACHE_READY_LOCK:
        if force:
            _CACHE_READY = False
        if not _CACHE_READY or not DB_PATH.exists():
            _ensure_cache_db()
            _CACHE_READY = True


@pyscript_compile  # noqa: F821
def _reset_cache_ready() -> None:
    """Mark the cache database schema as stale so it will be recreated."""
    global _CACHE_READY
    with _CACHE_READY_LOCK:
        _CACHE_READY = False


def _cache_prepare_db_sync(force: bool = False) -> bool:
    """Ensure the cache database is ready for use."""
    _ensure_cache_db_once(force=force)
    return True


@pyscript_executor  # noqa: F821
def _prune_expired_sync() -> int:
    """Prune expired entries from the cache database."""
    for attempt in range(2):
        try:
            _ensure_cache_db_once()
            now = int(time.time())
            with closing(_get_db_connection()) as conn:
                cur = conn.cursor()
                cur.execute("DELETE FROM cache_entries WHERE expires_at <= ?", (now,))
                rowcount = getattr(cur, "rowcount", -1)
                removed = rowcount if rowcount and rowcount > 0 else 0
                conn.commit()
            return removed
        except sqlite3.OperationalError:
            _reset_cache_ready()
            if attempt == 0:
                time.sleep(0.1)
                continue
            raise
    return 0


@pyscript_executor  # noqa: F821
def _cache_get_sync(key: str) -> str | None:
    """Retrieve the cached value for a key if it exists and has not expired."""
    for attempt in range(2):
        try:
            _ensure_cache_db_once(force=attempt == 1)
            now = int(time.time())
            with closing(_get_db_connection()) as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT value
                    FROM cache_entries
                    WHERE key = ?
                      AND expires_at > ?
                    """,
                    (key, now),
                )
                row = cur.fetchone()
            return row["value"] if row else None
        except sqlite3.OperationalError:
            _reset_cache_ready()
            if attempt == 0:
                time.sleep(0.1)
                continue
            raise
    return None


@pyscript_executor  # noqa: F821
def _cache_set_sync(key: str, value: str, ttl_seconds: int) -> bool:
    """Persist a cache entry with the provided TTL."""
    for attempt in range(2):
        try:
            _ensure_cache_db_once(force=attempt == 1)
            now = int(time.time())
            expires_at = now + ttl_seconds
            with closing(_get_db_connection()) as conn:
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO cache_entries (key, value, expires_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET value      = excluded.value,
                                                   expires_at = excluded.expires_at
                    """,
                    (key, value, expires_at),
                )
                conn.commit()
            return True
        except sqlite3.OperationalError:
            _reset_cache_ready()
            if attempt == 0:
                time.sleep(0.1)
                continue
            raise
    return False


@pyscript_executor  # noqa: F821
def _cache_delete_sync(key: str) -> int:
    """Remove the cache entry identified by key if it exists."""
    for attempt in range(2):
        try:
            _ensure_cache_db_once(force=attempt == 1)
            with closing(_get_db_connection()) as conn:
                cur = conn.cursor()
                cur.execute("DELETE FROM cache_entries WHERE key = ?", (key,))
                deleted = cur.rowcount if cur.rowcount is not None else 0
                conn.commit()
            return max(deleted, 0)
        except sqlite3.OperationalError:
            _reset_cache_ready()
            if attempt == 0:
                time.sleep(0.1)
                continue
            raise
    return 0


async def _cache_prepare_db(force: bool = False) -> bool:
    """Ensure the cache database is ready for use."""
    return await asyncio.to_thread(_cache_prepare_db_sync, force)


async def _cache_get(key: str) -> str | None:
    """Retrieve the cached value for a key if it exists and has not expired."""
    return _cache_get_sync(key)


async def _cache_set(key: str, value: str, ttl_seconds: int) -> bool:
    """Persist a cache entry with the provided TTL."""
    return _cache_set_sync(key, value, ttl_seconds)


async def _cache_delete(key: str) -> int:
    """Remove the cache entry identified by key if it exists."""
    return _cache_delete_sync(key)


async def _prune_expired() -> int:
    """Async wrapper for pruning expired entries."""
    return _prune_expired_sync()


@time_trigger("startup")  # noqa: F821
async def initialize_cache_db() -> None:
    """Run once at startup to create the cache database and schema before services execute."""
    await _cache_prepare_db(force=True)
    await _prune_expired()


@time_trigger("cron(0 * * * *)")  # noqa: F821
async def prune_cache_db() -> None:
    """Regularly prune expired entries from the cache database."""
    await _prune_expired()


_TIMEOUT_ERROR_RESPONSE = {
    "response": {
        "response_type": "error",
        "speech": {"plain": {"speech": ""}},
    }
}


# ── Test Mode ────────────────────────────────────────────────────────────────

def _is_test_mode() -> bool:
    try:
        return str(
            state.get("input_boolean.ai_test_mode") or "off"  # noqa: F821
        ).lower() == "on"
    except NameError:
        return False


@service(supports_response="only")  # noqa: F821
async def conversation_with_timeout(
    agent_id: str,
    text: str,
    timeout_secs: int = 60,
) -> dict[str, Any]:
    """
    yaml
    name: Conversation With Timeout
    description: >-
      Wrapper around conversation.process that enforces a timeout.
      Returns the same structure as conversation.process on success.
      On timeout or error, returns a response with response_type 'error'
      so callers fall through to their template fallback.
    fields:
      agent_id:
        name: Agent ID
        description: Conversation agent entity ID.
        required: true
        selector:
          text:
      text:
        name: Text
        description: Prompt text to send to the conversation agent.
        required: true
        selector:
          text:
            multiline: true
      timeout_secs:
        name: Timeout (seconds)
        description: Maximum seconds to wait for a response.
        default: 60
        selector:
          number:
            min: 5
            max: 300
            mode: box
    """
    if _is_test_mode():
        log.info("common_utilities [TEST]: would call conversation with timeout agent=%s", agent_id)  # noqa: F821
        return {"status": "test_mode_skip"}

    def _call_sync():
        return service.call(  # noqa: F821
            "conversation",
            "process",
            agent_id=agent_id,
            text=text,
            return_response=True,
        )

    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(_call_sync),
            timeout=timeout_secs,
        )
        if isinstance(result, dict):
            return result if "response" in result else {"response": result}
        return _TIMEOUT_ERROR_RESPONSE
    except asyncio.TimeoutError:
        log.warning(  # noqa: F821
            "conversation_with_timeout: timed out after %ss for %s",
            timeout_secs,
            agent_id,
        )
        return _TIMEOUT_ERROR_RESPONSE
    except Exception as exc:
        log.error(  # noqa: F821
            "conversation_with_timeout: %s: %s (agent=%s)",
            type(exc).__name__,
            exc,
            agent_id,
        )
        return _TIMEOUT_ERROR_RESPONSE


@service(supports_response="only")  # noqa: F821
async def memory_cache_get(key: str) -> dict[str, Any]:
    """
    yaml
    name: Memory Cache Get
    description: Fetch a cached value for a given key.
    fields:
      key:
        name: Key
        description: Identifier for the cached entry.
        required: true
        selector:
          text:
    """
    if _is_test_mode():
        log.info("common_utilities [TEST]: would get cache key=%s", key)  # noqa: F821
        return {"status": "test_mode_skip"}

    if not key:
        return {
            "status": "error",
            "op": "get",
            "error": "Missing a required argument: key",
        }
    try:
        raw_value = await _cache_get(key)
        if raw_value is not None:
            value = orjson.loads(raw_value)
            return {
                "status": "ok",
                "op": "get",
                "key": key,
                "value": value,
            }
        return {
            "status": "error",
            "op": "get",
            "key": key,
            "error": "not_found",
        }
    except Exception as error:
        return {
            "status": "error",
            "op": "get",
            "key": key,
            "error": f"An unexpected error occurred during processing: {error}",
        }


@service(supports_response="only")  # noqa: F821
async def memory_cache_forget(key: str) -> dict[str, Any]:
    """
    yaml
    name: Memory Cache Forget
    description: Remove a cached entry if it exists.
    fields:
      key:
        name: Key
        description: Identifier for the cached entry.
        required: true
        selector:
          text:
    """
    if _is_test_mode():
        log.info("common_utilities [TEST]: would forget cache key=%s", key)  # noqa: F821
        return {"status": "test_mode_skip"}

    if not key:
        return {
            "status": "error",
            "op": "forget",
            "error": "Missing a required argument: key",
        }
    try:
        async with _acquire_index_lock(key):
            deleted = await _cache_delete(key)
        return {
            "status": "ok",
            "op": "forget",
            "key": key,
            "deleted": deleted,
        }
    except Exception as error:
        return {
            "status": "error",
            "op": "forget",
            "key": key,
            "error": f"An unexpected error occurred during processing: {error}",
        }


@service(supports_response="only")  # noqa: F821
async def memory_cache_set(
    key: str,
    value: Any,
    ttl_seconds: int | None = None,
) -> dict[str, Any]:
    """
    yaml
    name: Memory Cache Set
    description: Store a value in cache for a given key.
    fields:
      key:
        name: Key
        description: Identifier for the cached entry.
        required: true
        selector:
          text:
      value:
        name: Value
        description: JSON-serializable value to cache for the provided key (string, number, list, dict, etc.).
        required: true
        selector:
          object:
      ttl_seconds:
        name: TTL Seconds
        description: Optional override for the entry's time to live (defaults to TTL constant).
        selector:
          number:
            min: 1
            max: 2592000
            mode: box
    """
    if _is_test_mode():
        log.info("common_utilities [TEST]: would set cache key=%s", key)  # noqa: F821
        return {"status": "test_mode_skip"}

    ttl = ttl_seconds if ttl_seconds is not None and ttl_seconds > 0 else TTL
    stored_value = orjson.dumps(value).decode("utf-8")
    try:
        async with _acquire_index_lock(key):
            success = await _cache_set(key, stored_value, ttl)
        if not success:
            return {
                "status": "error",
                "op": "set",
                "key": key,
                "value": value,
                "error": "cache_set returned False",
            }
        return {
            "status": "ok",
            "op": "set",
            "key": key,
            "value": value,
            "ttl": ttl,
        }
    except Exception as error:
        return {
            "status": "error",
            "op": "set",
            "key": key,
            "error": f"An unexpected error occurred during processing: {error}",
        }


@service(supports_response="only")  # noqa: F821
async def memory_cache_index_update(
    index_key: str,
    add: Any | None = None,
    remove: Any | None = None,
    replace: Any | None = None,
    ttl_seconds: int | None = None,
) -> dict[str, Any]:
    """
    yaml
    name: Memory Cache Index Update
    description: Atomically update a list index in cache by adding and/or removing identifiers.
    fields:
      index_key:
        name: Index key
        description: Cache key that stores the index list.
        required: true
        selector:
          text:
      add:
        name: IDs to add
        description: Optional list of identifiers to append when absent.
        selector:
          object:
      remove:
        name: IDs to remove
        description: Optional list of identifiers to remove from the index.
        selector:
          object:
      replace:
        name: Replace index
        description: Optional list that replaces the entire index before add/remove adjustments.
        selector:
          object:
      ttl_seconds:
        name: TTL Seconds
        description: Optional override for the index time to live (defaults to 30 days).
        selector:
          number:
            min: 1
            max: 2592000
            mode: box
    """
    if _is_test_mode():
        log.info("common_utilities [TEST]: would update cache index key=%s", index_key)  # noqa: F821
        return {"status": "test_mode_skip"}

    cleaned_key = (index_key or "").strip()
    if not cleaned_key:
        return {
            "status": "error",
            "op": "index_update",
            "error": "Missing a required argument: index_key",
        }

    def _normalize(_value: Any) -> list[str]:
        if _value is None:
            return []
        if isinstance(_value, (str, int, float, bool)):
            seq = [_value]
        elif isinstance(_value, list):
            seq = _value
        elif isinstance(_value, (tuple, set)):
            seq = list(_value)
        else:
            return []
        result: list[str] = []
        for _item in seq:
            normalized = str(_item).strip()
            if normalized:
                result.append(normalized)
        return result

    replace_list = _normalize(replace) if replace is not None else None
    add_list = _normalize(add)
    remove_list = _normalize(remove)

    if replace_list is None and not add_list and not remove_list:
        return {
            "status": "error",
            "op": "index_update",
            "key": cleaned_key,
            "error": "Nothing to add or remove",
        }

    ttl = ttl_seconds if ttl_seconds is not None and ttl_seconds > 0 else 2592000

    async with _acquire_index_lock(cleaned_key):
        try:
            entries: list[str] = []
            seen: set[str] = set()
            changed = False

            if replace_list is not None:
                for value in replace_list:
                    if value not in seen:
                        entries.append(value)
                        seen.add(value)
                changed = True
            else:
                existing_raw = await _cache_get(cleaned_key)
                if existing_raw:
                    try:
                        parsed = orjson.loads(existing_raw)
                        if isinstance(parsed, list):
                            for item in parsed:
                                value = str(item).strip()
                                if value and value not in seen:
                                    entries.append(value)
                                    seen.add(value)
                    except orjson.JSONDecodeError:
                        entries = []

            for value in add_list:
                if value not in seen:
                    entries.append(value)
                    seen.add(value)
                    changed = True

            if remove_list:
                remove_set = set(remove_list)
                filtered = [entry for entry in entries if entry not in remove_set]
                if len(filtered) != len(entries):
                    entries = filtered
                    changed = True

            stored_value = orjson.dumps(entries).decode("utf-8")
            success = await _cache_set(cleaned_key, stored_value, ttl)

            if not success:
                return {
                    "status": "error",
                    "op": "index_update",
                    "key": cleaned_key,
                    "error": "cache_set returned False",
                }

            return {
                "status": "ok",
                "op": "index_update",
                "key": cleaned_key,
                "ids": entries,
                "ttl": ttl,
                "changed": changed,
            }
        except Exception as error:
            return {
                "status": "error",
                "op": "index_update",
                "key": cleaned_key,
                "error": f"An unexpected error occurred during processing: {error}",
            }


# ── I-33 Phase 2: Per-Agent Budget Breakdown ────────────────────────────────

_budget_breakdown: dict = {"llm": {}, "tts": {}, "stt": {}, "search": {}}

# ── Dynamic model resolution from HA config entries ──────────────────────────

_CONFIG_ENTRIES_PATH = Path("/config/.storage/core.config_entries")
_ENTITY_REGISTRY_PATH = Path("/config/.storage/core.entity_registry")

# Agent name extraction: conversation.rick_standard_2 → rick
# Mirrors the Jinja in ai_llm_budget.yaml:
#   regex_replace('_(standard|bedtime|extended|music).*$', '') | regex_replace('_\\d+$', '')
import re as _re  # noqa: E402
_STRIP_VARIANT_RE = _re.compile(r"_(standard|bedtime|extended|music).*$")
_STRIP_TRAILING_NUM_RE = _re.compile(r"_\d+$")

# Static TTS/STT maps — these don't change with model swaps
_AGENT_TTS_MAP = {
    "rick": "elevenlabs", "quark": "elevenlabs", "kramer": "elevenlabs",
    "deadpool": "elevenlabs", "portuondo": "elevenlabs", "custom": "elevenlabs",
}
_AGENT_STT_MAP = {
    "rick": "elevenlabs", "quark": "elevenlabs", "kramer": "elevenlabs",
    "deadpool": "elevenlabs", "portuondo": "ha_cloud",
}

# Well-known OpenRouter prefix → provider mapping
_PREFIX_PROVIDER = {
    "google": "google", "anthropic": "anthropic", "meta-llama": "meta",
    "openai": "openai", "deepseek": "deepseek", "mistralai": "mistral",
    "cohere": "cohere", "perplexity": "perplexity", "qwen": "qwen",
}
# Static provider entries that never come from config entries
_STATIC_PROVIDER_MAP = {"elevenlabs": "elevenlabs", "ha_cloud": "ha_cloud"}

# Cached maps — populated on first use or by budget_reload_model_map
_AGENT_MODEL_MAP: dict = {"llm": {}, "tts": _AGENT_TTS_MAP, "stt": _AGENT_STT_MAP}
_AGENT_FULL_SLUG_MAP: dict = {}  # C5: agent → full "provider/model" slug (for pricing lookup)
_MODEL_PROVIDER_MAP: dict = dict(_STATIC_PROVIDER_MAP)
_MODEL_PRICING: dict = {}  # C5: model_slug → {input_per_1m, output_per_1m, source}
_model_map_loaded: bool = False
_pricing_loaded: bool = False
_PRICING_JSON_PATH = Path("/config/pyscript/model_pricing.json")


@pyscript_compile  # noqa: F821
def _extract_agent_name(entity_id: str) -> str | None:
    """Derive budget agent key from a conversation entity ID."""
    if not entity_id.startswith("conversation."):
        return None
    raw = entity_id.removeprefix("conversation.")
    raw = _STRIP_VARIANT_RE.sub("", raw)
    raw = _STRIP_TRAILING_NUM_RE.sub("", raw)
    # Normalize: doctor_portuondo → portuondo (matches existing budget keys)
    if raw == "doctor_portuondo":
        return "portuondo"
    # extended_openai_conversation is the default entity for the first subentry
    if raw in ("extended_openai_conversation", ""):
        return None
    return raw


@pyscript_compile  # noqa: F821
def _strip_provider_prefix(model_slug: str) -> tuple[str, str | None]:
    """Split 'google/gemini-2.5-flash' → ('gemini-2.5-flash', 'google').
    Returns (display_name, provider_or_None)."""
    if "/" in model_slug:
        prefix, name = model_slug.split("/", 1)
        provider = _PREFIX_PROVIDER.get(prefix, prefix)
        return name, provider
    return model_slug, None


@pyscript_compile  # noqa: F821
def _infer_provider(display_model: str) -> str:
    """Best-effort provider inference from a display model name."""
    lower = display_model.lower()
    if "gemini" in lower or "palm" in lower:
        return "google"
    if "claude" in lower:
        return "anthropic"
    if "gpt" in lower or lower.startswith("o1") or lower.startswith("o3"):
        return "openai"
    if "llama" in lower or "maverick" in lower:
        return "meta"
    if "deepseek" in lower:
        return "deepseek"
    if "mistral" in lower or "mixtral" in lower:
        return "mistral"
    return "unknown"


@pyscript_executor  # noqa: F821
def _load_agent_model_map_sync() -> tuple[dict, dict, dict]:
    """Read config entries + entity registry to build agent→model, model→provider,
    and agent→full_slug maps. Runs in executor thread — file I/O only, no HA API calls."""
    llm_map: dict[str, str] = {}
    full_slug_map: dict[str, str] = {}  # C5: agent → full "provider/model" slug
    provider_map: dict[str, str] = dict(_STATIC_PROVIDER_MAP)

    try:
        with open(_CONFIG_ENTRIES_PATH) as f:
            config_data = orjson.loads(f.read())
        with open(_ENTITY_REGISTRY_PATH) as f:
            entity_data = orjson.loads(f.read())
    except Exception as exc:
        # Can't read storage — return empty, caller will fall back
        return llm_map, provider_map, full_slug_map

    # Build subentry_id → (chat_model, title) lookup from all EOC + anthropic entries
    subentry_info: dict[str, tuple[str, str]] = {}  # sid → (model, title)
    for entry in config_data.get("data", {}).get("entries", []):
        domain = entry.get("domain", "")
        if domain not in ("extended_openai_conversation", "anthropic"):
            continue
        for sub in entry.get("subentries", []):
            sid = sub.get("subentry_id", "")
            sd = sub.get("data", {})
            model = sd.get("chat_model", "") or sd.get("model", "")
            title = sub.get("title", "")
            if sid and model:
                subentry_info[sid] = (model, title)

    # Walk entity registry: map entity_id → subentry → model, pick Standard variant
    # Track seen agents to prefer Standard over Bedtime
    agent_variants: dict[str, list[tuple[str, str]]] = {}  # agent → [(variant, model)]
    for ent in entity_data.get("data", {}).get("entities", []):
        eid = ent.get("entity_id", "")
        if not eid.startswith("conversation."):
            continue
        if ent.get("disabled_by"):
            continue
        sub_id = ent.get("config_subentry_id", "")
        info = subentry_info.get(sub_id)
        if not info:
            continue
        model_slug, sub_title = info
        agent = _extract_agent_name(eid)
        # Fallback: if entity_id is generic (e.g. conversation.extended_openai_conversation),
        # derive agent from subentry title ("Deadpool - Standard" → deadpool)
        if not agent and sub_title:
            title_lower = sub_title.lower().split(" - ")[0].strip()
            # Map known title names to budget agent keys
            title_agent = {
                "deadpool": "deadpool", "rick": "rick", "quark": "quark",
                "kramer": "kramer", "doctor portuondo": "portuondo",
                "dr. portuondo": "portuondo", "deepee": "deadpool",
                "claude": "claude_conversation",
            }.get(title_lower)
            if title_agent:
                agent = title_agent
        if not agent:
            continue

        # Determine variant type from entity ID or subentry title
        variant_src = eid + " " + sub_title.lower()
        variant = "standard" if "standard" in variant_src else (
            "bedtime" if "bedtime" in variant_src else "other"
        )
        agent_variants.setdefault(agent, []).append((variant, model_slug))

    # Pick Standard model for each agent (budget tracks the primary/standard pipeline)
    for agent, variants in agent_variants.items():
        # Prefer standard, then other, then bedtime
        chosen = None
        for pref in ("standard", "other", "bedtime"):
            for v, m in variants:
                if v == pref:
                    chosen = m
                    break
            if chosen:
                break
        if not chosen:
            chosen = variants[0][1]

        full_slug_map[agent] = chosen  # C5: preserve full slug for pricing lookup
        display, prefix_provider = _strip_provider_prefix(chosen)
        llm_map[agent] = display
        if display not in provider_map:
            provider_map[display] = prefix_provider or _infer_provider(display)

    return llm_map, provider_map, full_slug_map


async def _load_and_cache_model_map() -> None:
    """Load model map from config entries and cache in module globals."""
    global _AGENT_MODEL_MAP, _AGENT_FULL_SLUG_MAP, _MODEL_PROVIDER_MAP, _model_map_loaded
    try:
        llm_map, provider_map, full_slug_map = _load_agent_model_map_sync()
        _AGENT_MODEL_MAP = {"llm": llm_map, "tts": _AGENT_TTS_MAP, "stt": _AGENT_STT_MAP}
        _AGENT_FULL_SLUG_MAP = full_slug_map
        _MODEL_PROVIDER_MAP = provider_map
        _model_map_loaded = True
        log.info(  # noqa: F821
            "budget: model map loaded — %d agents, %d models, %d full slugs",
            len(llm_map), len(provider_map), len(full_slug_map),
        )
    except Exception as exc:
        log.warning("budget: model map load failed: %s", exc)  # noqa: F821


def _ensure_model_map() -> None:
    """Synchronous guard — schedules async load if map not yet populated."""
    global _model_map_loaded
    if not _model_map_loaded:
        # Schedule the async load; first call will populate before next sensor update
        task.create(_load_and_cache_model_map)  # noqa: F821
        _model_map_loaded = True  # Prevent repeated scheduling


@time_trigger("startup")  # noqa: F821
async def _initialize_model_map() -> None:
    """Load agent→model map from config entries on pyscript startup."""
    await _load_and_cache_model_map()


@service  # noqa: F821
async def budget_reload_model_map() -> None:
    """
    yaml
    name: Budget Reload Model Map
    description: >-
      Force-refresh the agent→model mapping from HA config entries.
      Call after changing a conversation agent's model in the UI.
    """
    if _is_test_mode():
        log.info("common_utilities [TEST]: would reload budget model map")  # noqa: F821
        return

    global _model_map_loaded
    _model_map_loaded = False
    await _load_and_cache_model_map()
    log.info("budget: model map reloaded — llm=%s", _AGENT_MODEL_MAP.get("llm", {}))  # noqa: F821
    # C5: Refresh pricing when model map changes (may have new models)
    await _refresh_model_pricing()


# ── C5: Dynamic Per-Model Pricing ─────────────────────────────────────────────


@pyscript_executor  # noqa: F821
def _fetch_openrouter_pricing_sync(active_slug_values: list = None) -> dict:
    """Fetch per-model pricing from OpenRouter /api/v1/models API.
    active_slug_values: list of full slugs to filter (passed from caller to avoid
    reading mutable global inside executor). Empty/None = fetch all models.
    Returns {model_slug: {input_per_1m, output_per_1m}} for active models."""
    import requests as _requests

    # Read API key from secrets (same key used by the REST sensor)
    api_key = ""
    try:
        with open("/config/secrets.yaml") as f:
            for line in f:
                if line.strip().startswith("openrouter_api_key:"):
                    api_key = line.split(":", 1)[1].strip().strip("'\"")
                    break
    except Exception:
        pass

    if not api_key:
        return {}

    resp = _requests.get(
        "https://openrouter.ai/api/v1/models",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()

    # Filter to active models if slug list provided
    active_slugs = set(active_slug_values) if active_slug_values else set()

    pricing = {}
    for model in data.get("data", []):
        model_id = model.get("id", "")
        if not model_id:
            continue
        # Only cache models we actually use (or all if slug set empty — first run)
        if active_slugs and model_id not in active_slugs:
            continue
        p = model.get("pricing", {})
        try:
            input_per_token = float(p.get("prompt", "0"))
            output_per_token = float(p.get("completion", "0"))
        except (TypeError, ValueError):
            continue
        pricing[model_id] = {
            "input_per_1m": round(input_per_token * 1_000_000, 4),
            "output_per_1m": round(output_per_token * 1_000_000, 4),
            "source": "api",
        }

    return pricing


@pyscript_executor  # noqa: F821
def _load_pricing_cache_sync() -> dict:
    """Load model_pricing.json from disk. Returns full JSON structure or empty dict."""
    import json as _json
    try:
        with open(_PRICING_JSON_PATH) as f:
            return _json.load(f)
    except (FileNotFoundError, _json.JSONDecodeError):
        return {}


@pyscript_executor  # noqa: F821
def _write_pricing_cache_sync(api_data: dict, overrides: dict, defaults: dict) -> None:
    """Merge API data with overrides and write to model_pricing.json."""
    import json as _json
    from datetime import datetime as _dt, timedelta as _td
    merged_models = {}
    for slug, info in api_data.items():
        merged_models[slug] = info
    # Overrides always win
    for slug, info in overrides.items():
        merged_models[slug] = {**info, "source": "override"}

    cache = {
        "_meta": {
            "currency": "USD",
            "last_refreshed": _dt.now().isoformat(),
            "source": "openrouter_api",
            "models_fetched": len(api_data),
            "next_refresh": (_dt.now() + _td(hours=24)).isoformat(),
        },
        "models": merged_models,
        "overrides": overrides,
        "defaults": defaults,
    }
    with open(_PRICING_JSON_PATH, "w") as f:
        _json.dump(cache, f, indent=2)


async def _refresh_model_pricing() -> None:
    """Orchestrate pricing refresh: API → merge with overrides → cache → update globals."""
    global _MODEL_PRICING, _pricing_loaded

    # Load existing cache for overrides + defaults
    existing = _load_pricing_cache_sync()
    if not isinstance(existing, dict):
        existing = {}
    overrides = existing.get("overrides", {})
    defaults = existing.get("defaults", {"input_per_1m": 1.00, "output_per_1m": 5.00})

    source = "api"
    try:
        # Pass slug values from the mutable global (safe here — this is a regular async func)
        slug_values = list(_AGENT_FULL_SLUG_MAP.values()) if _AGENT_FULL_SLUG_MAP else []
        api_data = _fetch_openrouter_pricing_sync(active_slug_values=slug_values)
        if api_data:
            _write_pricing_cache_sync(api_data, overrides, defaults)
            # Merge: API data + overrides (overrides win)
            merged = dict(api_data)
            for slug, info in overrides.items():
                merged[slug] = {**info, "source": "override"}
            _MODEL_PRICING = {"models": merged, "defaults": defaults}
            _pricing_loaded = True
            log.info(  # noqa: F821
                "budget: pricing refreshed from API — %d models (+ %d overrides)",
                len(api_data), len(overrides),
            )
        else:
            raise ValueError("API returned no pricing data")
    except Exception as exc:
        log.warning("budget: API pricing fetch failed: %s — trying cache", exc)  # noqa: F821
        source = "cache"
        # Fall back to cached JSON
        cached = existing.get("models", {})
        if cached:
            _MODEL_PRICING = {"models": cached, "defaults": defaults}
            _pricing_loaded = True
            log.info("budget: pricing loaded from cache — %d models", len(cached))  # noqa: F821
        else:
            source = "defaults_only"
            _MODEL_PRICING = {"models": {}, "defaults": defaults}
            _pricing_loaded = True
            log.error("budget: no pricing available — using defaults only")  # noqa: F821

    # Update status sensor
    models_in_pricing = len(_MODEL_PRICING.get("models", {}))
    meta = existing.get("_meta", {})
    last_refreshed = meta.get("last_refreshed", "never") if source != "api" else datetime.now().isoformat()

    # Determine staleness
    status = source
    if source == "api":
        status = "ok"
    elif source == "cache":
        try:
            lr = datetime.fromisoformat(meta.get("last_refreshed", ""))
            if (datetime.now() - lr).total_seconds() > 48 * 3600:
                status = "stale"
            else:
                status = "cache_only"
        except (ValueError, TypeError):
            status = "stale"

    state.set(  # noqa: F821
        "sensor.ai_model_pricing_status",
        status,
        {
            "friendly_name": "AI Model Pricing Status",
            "icon": "mdi:check-circle" if status == "ok" else (
                "mdi:clock-alert" if status == "stale" else "mdi:alert-circle"
            ),
            "last_refreshed": last_refreshed,
            "models_tracked": models_in_pricing,
            "source": source,
        },
    )


@pyscript_compile  # noqa: F821
def _calculate_model_cost(model_slug: str, input_tokens: int, output_tokens: int) -> float:
    """Calculate cost in USD for a given model and token counts.
    Lookup order: exact slug → prefix-stripped scan → defaults → flat-rate helper."""
    models = _MODEL_PRICING.get("models", {})
    defaults = _MODEL_PRICING.get("defaults", {"input_per_1m": 1.00, "output_per_1m": 5.00})

    info = models.get(model_slug)

    # Try prefix-stripped match (e.g., "llama-4-maverick" → scan for "*/llama-4-maverick")
    if not info and "/" not in model_slug:
        for key, val in models.items():
            if key.endswith("/" + model_slug):
                info = val
                break

    if info:
        input_rate = float(info.get("input_per_1m", defaults.get("input_per_1m", 1.0)))
        output_rate = float(info.get("output_per_1m", defaults.get("output_per_1m", 5.0)))
    elif defaults:
        input_rate = float(defaults.get("input_per_1m", 1.0))
        output_rate = float(defaults.get("output_per_1m", 5.0))
    else:
        # Ultimate fallback: flat-rate helper
        return 0.0  # Caller should use flat-rate helper directly

    cost_usd = (input_tokens / 1_000_000 * input_rate) + (output_tokens / 1_000_000 * output_rate)
    return round(cost_usd, 6)


@service  # noqa: F821
async def budget_refresh_pricing() -> None:
    """
    yaml
    name: Budget Refresh Pricing
    description: >-
      Force-refresh per-model pricing from the OpenRouter API and write
      to model_pricing.json cache. Use after pricing changes or adding new models.
    """
    if _is_test_mode():
        log.info("common_utilities [TEST]: would refresh model pricing")  # noqa: F821
        return
    await _refresh_model_pricing()


@time_trigger("startup")  # noqa: F821
async def _initialize_pricing() -> None:
    """Load pricing from cache on startup, then schedule API refresh."""
    global _MODEL_PRICING, _pricing_loaded
    # Quick load from cache (no API wait)
    cached = _load_pricing_cache_sync()
    if isinstance(cached, dict) and cached.get("models"):
        defaults = cached.get("defaults", {"input_per_1m": 1.00, "output_per_1m": 5.00})
        _MODEL_PRICING = {"models": cached["models"], "defaults": defaults}
        _pricing_loaded = True
        log.info("budget: pricing warm-loaded from cache — %d models", len(cached["models"]))  # noqa: F821
    # Schedule API refresh (non-blocking)
    task.create(_refresh_model_pricing)  # noqa: F821


@time_trigger("cron(0 4 * * *)")  # noqa: F821
async def _daily_pricing_refresh() -> None:
    """Daily pricing refresh at 04:00 — pricing rarely changes intra-day."""
    await _refresh_model_pricing()


@state_trigger("input_button.ai_budget_refresh_pricing")  # noqa: F821
async def _manual_pricing_refresh(**kwargs) -> None:
    """Trigger pricing refresh from dashboard button."""
    await _refresh_model_pricing()


def _update_breakdown_sensor() -> None:
    """Push current breakdown dict to sensor.ai_budget_breakdown."""
    _ensure_model_map()
    try:
        total_calls = 0
        for agent_data in _budget_breakdown.values():
            for v in agent_data.values():
                total_calls += v.get("calls", 0)
        state.set(  # noqa: F821
            "sensor.ai_budget_breakdown",
            value=str(total_calls),
            new_attributes={
                "breakdown": _budget_breakdown,
                "model_map": _AGENT_MODEL_MAP,
                "full_slug_map": _AGENT_FULL_SLUG_MAP,
                "provider_map": _MODEL_PROVIDER_MAP,
                "last_updated": datetime.now().isoformat(),
            },
        )
    except Exception as exc:
        log.warning("budget_breakdown: sensor update failed: %s", exc)  # noqa: F821


@service  # noqa: F821
def budget_track_call(
    service_type: str,
    agent: str,
    calls: int = 1,
    tokens: int = 0,
    chars: int = 0,
    reset: bool = False,
    model: str = "",
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> None:
    """
    yaml
    name: Budget Track Call
    description: >-
      Track a call in the per-agent breakdown. Pass reset=true to clear all data.
      C5: model + input_tokens/output_tokens enable per-model cost calculation.
    fields:
      service_type:
        name: Service Type
        description: "llm, tts, stt, search, handoff, music, music_api, music_local"
        required: true
        selector:
          select:
            options: [llm, tts, stt, search, handoff, music, music_api, music_local]
      agent:
        name: Agent
        description: Agent key (rick, quark, deadpool, kramer, portuondo, task_gpt4o_mini, etc.)
        required: true
        selector:
          text:
      calls:
        name: Calls
        description: Number of calls to add.
        default: 1
        selector:
          number:
            min: 0
            max: 1000
      tokens:
        name: Tokens
        description: Token count to add (LLM only — legacy total).
        default: 0
        selector:
          number:
            min: 0
            max: 999999
      chars:
        name: Characters
        description: Character count to add (TTS only).
        default: 0
        selector:
          number:
            min: 0
            max: 999999
      reset:
        name: Reset
        description: Clear all breakdown data.
        default: false
        selector:
          boolean:
      model:
        name: Model
        description: "Full OpenRouter model slug (e.g. meta-llama/llama-4-maverick) for per-model costing."
        default: ""
        selector:
          text:
      input_tokens:
        name: Input Tokens
        description: Prompt/input token count (C5 per-model costing).
        default: 0
        selector:
          number:
            min: 0
            max: 999999
      output_tokens:
        name: Output Tokens
        description: Completion/output token count (C5 per-model costing).
        default: 0
        selector:
          number:
            min: 0
            max: 999999
    """
    if _is_test_mode():
        log.info("common_utilities [TEST]: would track budget call type=%s agent=%s", service_type, agent)  # noqa: F821
        return

    # Returns: None (void — updates sensor side-effect only)
    global _budget_breakdown

    if reset:
        _budget_breakdown = {
            "llm": {}, "tts": {}, "stt": {}, "search": {},
            "handoff": {}, "music": {}, "music_api": {}, "music_local": {},
        }
        _update_breakdown_sensor()
        return

    bucket = _budget_breakdown.setdefault(service_type, {})
    entry = bucket.setdefault(agent, {
        "calls": 0, "tokens": 0, "chars": 0,
        "input_tokens": 0, "output_tokens": 0, "model_cost_eur": 0.0, "model": "",
    })
    entry["calls"] += calls
    entry["tokens"] += tokens
    entry["chars"] += chars
    entry["input_tokens"] += input_tokens
    entry["output_tokens"] += output_tokens
    if model:
        entry["model"] = model

    # C5: Per-model cost calculation when model + tokens are provided
    if model and (input_tokens > 0 or output_tokens > 0) and _pricing_loaded:
        cost_usd = _calculate_model_cost(model, input_tokens, output_tokens)
        if cost_usd > 0:
            try:
                rate = float(state.get("sensor.usd_eur_exchange_rate") or 0.92)  # noqa: F821
            except (TypeError, ValueError):
                rate = 0.92
            cost_eur = round(cost_usd * rate, 6)
            entry["model_cost_eur"] += cost_eur
            # Accumulate into helper for template sensor access
            try:
                cur = float(state.get("input_number.ai_model_cost_today") or 0)  # noqa: F821
                service.call(  # noqa: F821
                    "input_number", "set_value",
                    entity_id="input_number.ai_model_cost_today",
                    value=min(round(cur + cost_eur, 4), 100),
                )
            except Exception:
                pass

    _update_breakdown_sensor()


@service  # noqa: F821
def budget_breakdown_restore(data: dict = None) -> None:
    """
    yaml
    name: Budget Breakdown Restore
    description: >-
      Restore breakdown from persisted L2 data dict.
    fields:
      data:
        name: Data
        description: Breakdown dict with llm/tts/stt keys.
        required: true
        selector:
          object:
    """
    if _is_test_mode():
        log.info("common_utilities [TEST]: would restore budget breakdown")  # noqa: F821
        return

    global _budget_breakdown
    if isinstance(data, dict) and all(k in data for k in ("llm", "tts", "stt")):
        _budget_breakdown = data
        _update_breakdown_sensor()


# ── LLM Wrappers (I-41 absorbed into ha_text_ai + thin pyscript layer) ──────


_BUDGET_THRESHOLDS = {"essential": 0, "standard": 30, "luxury": 60}
_EMBED_TIMEOUT = aiohttp.ClientTimeout(total=30)


def _read_budget_remaining() -> int:
    """Read current budget remaining percentage from the template sensor."""
    try:
        val = state.get("sensor.ai_llm_budget_remaining")  # noqa: F821
        return int(float(val)) if val not in (None, "unknown", "unavailable") else 100
    except (TypeError, ValueError):
        return 100


def _increment_budget_counters(calls: int = 1, tokens: int = 0, stt: int = 0,
                                agent: str = "task_llm",
                                model: str = "", input_tokens: int = 0,
                                output_tokens: int = 0) -> None:
    """Increment LLM budget counters after a successful call.
    C5: model + input_tokens/output_tokens enable per-model cost tracking."""
    try:
        if calls > 0:
            cur_calls = int(float(state.get("input_number.ai_llm_calls_today") or 0))  # noqa: F821
            service.call(  # noqa: F821
                "input_number", "set_value",
                entity_id="input_number.ai_llm_calls_today",
                value=min(cur_calls + calls, 999),
            )
        if tokens > 0:
            cur_tokens = int(float(state.get("input_number.ai_llm_tokens_today") or 0))  # noqa: F821
            service.call(  # noqa: F821
                "input_number", "set_value",
                entity_id="input_number.ai_llm_tokens_today",
                value=min(cur_tokens + tokens, 999999),
            )
        if stt > 0:
            cur_stt = int(float(state.get("input_number.ai_stt_calls_today") or 0))  # noqa: F821
            service.call(  # noqa: F821
                "input_number", "set_value",
                entity_id="input_number.ai_stt_calls_today",
                value=min(cur_stt + stt, 99999),
            )
        # C5: Resolve model from full slug map if not provided
        resolved_model = model
        if not resolved_model and agent:
            # Strip "task_" prefix for slug map lookup
            lookup_key = agent.removeprefix("task_") if agent.startswith("task_") else agent
            resolved_model = _AGENT_FULL_SLUG_MAP.get(lookup_key, "")
        # I-33 Phase 2 + C5: Track per-agent breakdown with model + split tokens
        budget_track_call(
            "llm", agent, calls=calls, tokens=tokens,
            model=resolved_model, input_tokens=input_tokens, output_tokens=output_tokens,
        )
    except Exception as exc:
        log.warning("llm budget increment failed: %s", exc)  # noqa: F821


@service(supports_response="only")  # noqa: F821
async def llm_task_call(
    prompt: str,
    system: str | None = None,
    model: str | None = None,
    max_tokens: int = 500,
    temperature: float = 0.3,
    priority_tier: str = "standard",
) -> dict[str, Any]:
    """
    yaml
    name: LLM Task Call
    description: >-
      Budget-aware LLM wrapper using ha_text_ai.ask_question.
      Returns response text or None on budget exhaustion / failure.
    fields:
      prompt:
        name: Prompt
        description: The prompt to send to the LLM.
        required: true
        selector:
          text:
            multiline: true
      system:
        name: System Prompt
        description: Optional system prompt override.
        selector:
          text:
            multiline: true
      model:
        name: Model
        description: Model override (reads from ha_text_ai instance if omitted).
        selector:
          text:
      max_tokens:
        name: Max Tokens
        description: Maximum response tokens.
        default: 500
        selector:
          number:
            min: 50
            max: 4000
            mode: box
      temperature:
        name: Temperature
        description: Sampling temperature.
        default: 0.3
        selector:
          number:
            min: 0
            max: 1
            step: 0.1
            mode: slider
      priority_tier:
        name: Priority Tier
        description: Budget tier (essential/standard/luxury).
        default: standard
        selector:
          select:
            options:
              - essential
              - standard
              - luxury
    """
    # Returns: {status, response_text, tokens_used?, model_used?, error?, budget_remaining?}
    if _is_test_mode():
        log.info("common_utilities [TEST]: would call LLM prompt=%s", prompt[:50] if prompt else "")  # noqa: F821
        return {"status": "test_mode_skip"}

    if not prompt:
        return {"status": "error", "error": "prompt_missing", "response_text": None}

    # Budget gate
    budget_pct = _read_budget_remaining()
    threshold = _BUDGET_THRESHOLDS.get(priority_tier, 30)
    if priority_tier != "essential" and budget_pct <= threshold:
        log.warning(  # noqa: F821
            "llm_task_call: budget exhausted (%s%%, tier=%s, threshold=%s%%)",
            budget_pct, priority_tier, threshold,
        )
        return {"status": "budget_exhausted", "budget_remaining": budget_pct, "response_text": None}

    # Read ha_text_ai instance entity
    try:
        instance_entity = state.get("input_text.ai_task_instance") or ""  # noqa: F821
        instance_entity = instance_entity.strip()
    except (TypeError, AttributeError):
        instance_entity = ""
    if not instance_entity:
        instance_entity = "sensor.ha_text_ai_deepseek_chat"

    # Build service data
    svc_data = {"question": prompt, "instance": instance_entity}
    if system:
        svc_data["system_prompt"] = system
    if model:
        svc_data["model"] = model
    if max_tokens:
        svc_data["max_tokens"] = int(max_tokens)
    if temperature is not None:
        svc_data["temperature"] = float(temperature)

    def _call_sync():
        return service.call(  # noqa: F821
            "ha_text_ai", "ask_question",
            return_response=True,
            **svc_data,
        )

    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(_call_sync),
            timeout=60,
        )
    except asyncio.TimeoutError:
        log.warning("llm_task_call: timed out after 60s")  # noqa: F821
        return {"status": "error", "error": "timeout", "response_text": None}
    except Exception as exc:
        log.warning("llm_task_call: %s: %s", type(exc).__name__, exc)  # noqa: F821
        return {"status": "error", "error": str(exc), "response_text": None}

    if not isinstance(result, dict):
        return {"status": "error", "error": "unexpected_response_type", "response_text": None}

    # ha_text_ai returns nested dict: result key contains the actual response
    # Try common response structures
    response_text = None
    tokens_used = 0
    for key in ("response_text", "response"):
        if key in result and isinstance(result[key], str):
            response_text = result[key]
            break
    if response_text is None:
        # Try nested structure
        for top_key in result:
            val = result[top_key]
            if isinstance(val, dict):
                for key in ("response_text", "response"):
                    if key in val and isinstance(val[key], str):
                        response_text = val[key]
                        break
            if response_text is not None:
                break

    # Extract token counts (total + C5 split if available)
    for key in ("tokens_used", "total_tokens"):
        if key in result:
            try:
                tokens_used = int(result[key])
            except (TypeError, ValueError):
                pass
            break
    # C5: Try to extract split token counts from ha_text_ai response
    prompt_tokens = 0
    completion_tokens = 0
    for pk in ("prompt_tokens", "input_tokens"):
        if pk in result:
            try:
                prompt_tokens = int(result[pk])
            except (TypeError, ValueError):
                pass
            break
    for ck in ("completion_tokens", "output_tokens"):
        if ck in result:
            try:
                completion_tokens = int(result[ck])
            except (TypeError, ValueError):
                pass
            break
    # Fallback: if no split but total available, attribute all to output (conservative)
    if tokens_used > 0 and prompt_tokens == 0 and completion_tokens == 0:
        completion_tokens = tokens_used

    # Derive agent name from model used or instance entity
    model_used = result.get("model_used", "") or model or ""
    agent_label = f"task_{model_used.replace('-', '_').replace('.', '_')}" if model_used else f"task_{instance_entity.split('.')[-1]}"

    # C5: Increment budget with model + split tokens for per-model costing
    _increment_budget_counters(
        calls=1, tokens=tokens_used, agent=agent_label,
        model=model_used, input_tokens=prompt_tokens, output_tokens=completion_tokens,
    )

    return {
        "status": "ok",
        "response_text": response_text,
        "tokens_used": tokens_used,
        "model_used": model_used,
    }


@service(supports_response="only")  # noqa: F821
async def llm_direct_embed(
    text: str,
    model: str | None = None,
    dimensions: int | None = None,
    priority_tier: str = "standard",
) -> dict[str, Any]:
    """
    yaml
    name: LLM Direct Embed
    description: >-
      Generate an embedding vector via OpenAI-compatible API. Budget-gated.
      Reads base URL from input_text.ai_embedding_api_url (default: OpenAI).
      Returns list of floats or None on failure.
    fields:
      text:
        name: Text
        description: Text to embed.
        required: true
        selector:
          text:
            multiline: true
      model:
        name: Model
        description: Embedding model (reads from helper if omitted).
        selector:
          text:
      dimensions:
        name: Dimensions
        description: Vector dimensions (reads from helper if omitted).
        selector:
          number:
            min: 128
            max: 1536
            mode: box
      priority_tier:
        name: Priority Tier
        description: Budget tier for gate check.
        default: standard
        selector:
          select:
            options:
              - essential
              - standard
              - luxury
    """
    if _is_test_mode():
        log.info("common_utilities [TEST]: would generate embedding for text=%s", text[:50] if text else "")  # noqa: F821
        return {"status": "test_mode_skip"}

    if not text:
        return {"status": "error", "error": "text_missing", "embedding": None}

    # Budget gate
    budget_pct = _read_budget_remaining()
    threshold = _BUDGET_THRESHOLDS.get(priority_tier, 30)
    if priority_tier != "essential" and budget_pct <= threshold:
        log.warning(  # noqa: F821
            "llm_direct_embed: budget exhausted (%s%%, tier=%s)",
            budget_pct, priority_tier,
        )
        return {"status": "budget_exhausted", "budget_remaining": budget_pct, "embedding": None}

    # Read settings from helpers
    if not model:
        try:
            model = state.get("input_text.ai_embedding_model") or "text-embedding-3-small"  # noqa: F821
        except (TypeError, AttributeError):
            model = "text-embedding-3-small"
    if not dimensions:
        try:
            dimensions = int(float(state.get("input_number.ai_embedding_dimensions") or 512))  # noqa: F821
        except (TypeError, ValueError):
            dimensions = 512

    try:
        api_key = state.get("input_text.ai_embedding_api_key") or ""  # noqa: F821
        api_key = api_key.strip()
    except (TypeError, AttributeError):
        api_key = ""
    if not api_key:
        return {"status": "error", "error": "api_key_missing", "embedding": None}

    # Read API base URL from helper, fall back to OpenAI
    try:
        api_base = (state.get("input_text.ai_embedding_api_url") or "").strip()  # noqa: F821
    except (TypeError, AttributeError):
        api_base = ""
    if not api_base:
        api_base = "https://api.openai.com/v1"
    embed_url = f"{api_base.rstrip('/')}/embeddings"

    payload = {
        "input": text,
        "model": model,
        "dimensions": dimensions,
        "encoding_format": "float",
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    # ── T24-2a: Exponential backoff (3 attempts: 1s, 3s, 9s) ──
    _EMBED_RETRIES = 3
    _EMBED_BACKOFF = [1, 3, 9]
    last_error = None
    data = None
    for attempt in range(_EMBED_RETRIES):
        try:
            async with aiohttp.ClientSession(timeout=_EMBED_TIMEOUT) as session:
                async with session.post(
                    embed_url,
                    json=payload,
                    headers=headers,
                ) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        last_error = f"http_{resp.status}"
                        if resp.status < 500:
                            # Client error — don't retry
                            log.warning("llm_direct_embed: HTTP %s: %s", resp.status, body[:200])  # noqa: F821
                            return {"status": "error", "error": last_error, "embedding": None}
                        log.warning(  # noqa: F821
                            "llm_direct_embed: HTTP %s (attempt %d/%d): %s",
                            resp.status, attempt + 1, _EMBED_RETRIES, body[:200],
                        )
                    else:
                        data = await resp.json()
                        break
        except asyncio.TimeoutError:
            last_error = "timeout"
            log.warning(  # noqa: F821
                "llm_direct_embed: timeout (attempt %d/%d)",
                attempt + 1, _EMBED_RETRIES,
            )
        except Exception as exc:
            last_error = str(exc)
            log.warning(  # noqa: F821
                "llm_direct_embed: %s (attempt %d/%d): %s",
                type(exc).__name__, attempt + 1, _EMBED_RETRIES, exc,
            )
        if attempt < _EMBED_RETRIES - 1:
            await asyncio.sleep(_EMBED_BACKOFF[attempt])

    if data is None:
        return {"status": "error", "error": last_error or "unknown", "embedding": None}

    # Extract embedding vector
    try:
        embedding = data["data"][0]["embedding"]
    except (KeyError, IndexError, TypeError) as exc:
        log.warning("llm_direct_embed: bad response structure: %s", exc)  # noqa: F821
        return {"status": "error", "error": "bad_response", "embedding": None}

    # Extract token count and increment budget
    tokens = 0
    try:
        tokens = int(data.get("usage", {}).get("total_tokens", 0))
    except (TypeError, ValueError):
        pass
    _increment_budget_counters(calls=1, tokens=tokens,
                               agent=f"task_{model.replace('-', '_').replace('.', '_')}")

    return {
        "status": "ok",
        "embedding": embedding,
        "dimensions": len(embedding),
        "tokens_used": tokens,
        "model": model,
    }


def _serialize_f32_vec(vec: list[float]) -> bytes:
    """Serialize a float list to little-endian f32 bytes for sqlite-vec."""
    return struct.pack(f"<{len(vec)}f", *vec)


def _deserialize_f32_vec(raw: bytes) -> list[float]:
    """Deserialize little-endian f32 bytes back to a float list."""
    n = len(raw) // 4
    return list(struct.unpack(f"<{n}f", raw))
