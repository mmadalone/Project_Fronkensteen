"""Core L2 Memory Engine: CRUD, Semantic Search, Linking, and Expiry.

Manages the persistent SQLite-backed memory layer (memory.db) with
key-value CRUD, tag-based and full-text search, optional vec0 semantic
embeddings, cross-key linking, TTL-based expiry, and automatic
housekeeping. Exposes services for set, get, forget, search, link,
reindex, and archive operations used by every other pyscript module.
"""
import asyncio
import re
import sqlite3
import struct
import threading
import time
import unicodedata
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from shared_utils import (
    build_result_entity_name,
    get_person_slugs,
    load_entity_config,
    resolve_memory_owner,
    resolve_memory_owner_with_confidence,
)

DB_PATH = Path("/config/memory.db")
VEC0_PATH = "/config/vec0"
RESULT_ENTITY = "sensor.memory_result"
EXPIRATION_MAX_DAYS = 3650
SEARCH_LIMIT_MAX = 50
NEAR_DISTANCE = 5
CANDIDATE_CHECK_LIMIT = 5
DUPLICATE_MIN_SCORE = 0.75  # Tag-overlap floor for duplicate_tags guard
HOUSEKEEPING_GRACE_DAYS = 10
HOUSEKEEPING_GRACE_MAX_DAYS = 365
VALUE_PREVIEW_CHARS = 120
BM25_WEIGHT = 0.5
MIN_REL_WEIGHT = 0.05
SEARCH_ENRICH_TOP_N = 3  # Enrich top-N search results with related entries
SEARCH_ENRICH_MAX_RELATED = 3  # Max related entries appended per search
SEARCH_ENRICH_MIN_WEIGHT = 0.15  # Min rel weight for search enrichment

_VEC_AVAILABLE = False
_VEC_DIMENSIONS = 512

EXTRA_CHAR_REPLACEMENTS = {
    "đ": "d",
    "Đ": "d",
    "ı": "i",  # noqa: RUF001
    "İ": "i",
    "ñ": "n",
    "Ñ": "n",
    "ç": "c",
    "Ç": "c",
    "ğ": "g",
    "Ğ": "g",
    "ş": "s",
    "Ş": "s",
    "ø": "o",
    "Ø": "o",
    "ł": "l",
    "Ł": "l",
    "ß": "ss",
    "Æ": "AE",
    "æ": "ae",
    "Œ": "OE",
    "œ": "oe",
    "Þ": "th",
    "þ": "th",
    "Ð": "d",
    "ð": "d",
    "Å": "a",
    "å": "a",
    "Ä": "a",
    "ä": "a",
    "Ö": "o",
    "ö": "o",
    "Ü": "u",
    "ü": "u",
}

_DB_READY = False
_DB_READY_LOCK = threading.Lock()

# ── Degradation: read-only mode on repeated write failures ──
_db_mode: str = "normal"  # normal | read_only | unavailable
_db_write_fail_count: int = 0
_DB_WRITE_FAIL_THRESHOLD: int = 3
_db_mode_lock = threading.Lock()


# ── QS-5: access control ─────────────────────────────────────────────────

def _check_access(row_owner: str, row_scope: str, requesting_user: str) -> str:
    """Return 'full' or 'restricted' (Tier B).

    full:       caller can see key + value.
    restricted: caller can see key/scope/tags, but value is redacted.
    """
    if row_scope in ("household", "session", "couple"):
        return "full"
    if not row_owner:  # legacy unassigned → full access
        return "full"
    if row_owner == requesting_user:
        return "full"
    return "restricted"

result_entity_name: dict[str, str] = {}


def _ensure_result_entity_name(force: bool = False) -> None:
    """Ensure result_entity_name is populated, optionally forcing a refresh."""
    global result_entity_name
    if force or not result_entity_name:
        result_entity_name = build_result_entity_name(RESULT_ENTITY)


@pyscript_executor  # noqa: F821
def _read_entity_config_sync(path: str) -> str:
    """Read entity_config.yaml content. Runs in executor thread. Returns raw string or empty."""
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except (OSError, IOError):
        return ""


@pyscript_compile  # noqa: F821
def _utcnow_iso() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(UTC).isoformat()


@pyscript_compile  # noqa: F821
def _dt_from_iso(s: str) -> datetime | None:
    """Parse an ISO string into datetime; return None if invalid."""
    try:
        return datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return None


@pyscript_compile  # noqa: F821
def _get_db_connection() -> sqlite3.Connection:
    """Create a properly configured database connection."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA temp_store=MEMORY;")
    conn.execute("PRAGMA busy_timeout=3000;")
    return conn


@pyscript_compile  # noqa: F821
def _ensure_db() -> None:
    """Ensure database exists and tables/indices are created.

    Uses a short-lived connection to avoid leaving an idle connection open
    at import time.
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with closing(_get_db_connection()) as conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS mem
            (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                key          TEXT UNIQUE NOT NULL,
                value        TEXT        NOT NULL,
                scope        TEXT        NOT NULL,
                tags         TEXT        NOT NULL,
                tags_search  TEXT        NOT NULL,
                created_at   TEXT        NOT NULL,
                last_used_at TEXT        NOT NULL,
                expires_at   TEXT
            );
            """
        )
        conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS mem_fts USING fts5(
                key, value, tags,
                content='mem',
                content_rowid='id',
                tokenize = 'unicode61 remove_diacritics 2'
            );
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_scope ON mem(scope);")
        conn.executescript(
            """
            CREATE TRIGGER IF NOT EXISTS mem_ai
                AFTER INSERT
                ON mem
            BEGIN
                INSERT INTO mem_fts(rowid, key, value, tags)
                VALUES (new.id,
                        new.key,
                        new.value,
                        new.tags_search);
            END;

            CREATE TRIGGER IF NOT EXISTS mem_ad
                AFTER DELETE
                ON mem
            BEGIN
                INSERT INTO mem_fts(mem_fts, rowid, key, value, tags)
                VALUES ('delete', old.id, old.key, old.value, old.tags_search);
            END;

            CREATE TRIGGER IF NOT EXISTS mem_au
                AFTER UPDATE OF key, value, tags_search
                ON mem
                WHEN (old.key IS NOT new.key)
                    OR (old.value IS NOT new.value)
                    OR (old.tags_search IS NOT new.tags_search)
            BEGIN
                INSERT INTO mem_fts(mem_fts, rowid, key, value, tags)
                VALUES ('delete', old.id, old.key, old.value, old.tags_search);
                INSERT INTO mem_fts(rowid, key, value, tags)
                VALUES (new.id,
                        new.key,
                        new.value,
                        new.tags_search);
            END;
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS mem_rel
            (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                from_key    TEXT NOT NULL,
                to_key      TEXT NOT NULL,
                weight      REAL NOT NULL DEFAULT 0.0,
                rel_type    TEXT NOT NULL DEFAULT 'tag_overlap',
                created_at  TEXT NOT NULL,
                UNIQUE(from_key, to_key, rel_type)
            );
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_memrel_from ON mem_rel(from_key);"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_memrel_to ON mem_rel(to_key);"
        )
        # ── budget_history: daily usage snapshots for rolling aggregation ──
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS budget_history (
                date          TEXT PRIMARY KEY,
                usage_usd     REAL NOT NULL,
                usage_eur     REAL NOT NULL,
                exchange_rate  REAL NOT NULL,
                llm_calls     INTEGER DEFAULT 0,
                llm_tokens    INTEGER DEFAULT 0,
                tts_chars     INTEGER DEFAULT 0,
                stt_calls     INTEGER DEFAULT 0
            );
            """
        )
        # ── Serper credits column migration ──
        try:
            conn.execute("ALTER TABLE budget_history ADD COLUMN serper_credits INTEGER DEFAULT 0")
        except Exception:
            pass
        # ── C5: Per-model cost + breakdown columns ──
        try:
            conn.execute("ALTER TABLE budget_history ADD COLUMN model_cost_eur REAL DEFAULT 0")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE budget_history ADD COLUMN model_breakdown TEXT DEFAULT '{}'")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE budget_history ADD COLUMN music_generations INTEGER DEFAULT 0")
        except Exception:
            pass
        # ── QS-5: owner column for per-user memory isolation ──
        try:
            conn.execute("ALTER TABLE mem ADD COLUMN owner TEXT NOT NULL DEFAULT ''")
        except Exception:
            pass  # Column already exists
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_owner ON mem(owner);")
        # ── QS-5: backfill owner from existing key naming convention ──
        _qs5_row = conn.execute(
            "SELECT 1 FROM mem WHERE key='_schema:qs5_backfill'"
        ).fetchone()
        if _qs5_row is None:
            _now_bf = datetime.now(UTC).isoformat()
            for _slug in get_person_slugs():
                conn.execute("""
                    UPDATE mem SET owner=?
                    WHERE owner='' AND scope='user'
                      AND (key LIKE ? OR key LIKE ?)
                """, (_slug, f'%:{_slug}', f'%:{_slug}:%'))
            conn.execute("""
                INSERT OR IGNORE INTO mem(
                    key, value, scope, tags, tags_search,
                    created_at, last_used_at, owner
                ) VALUES(
                    '_schema:qs5_backfill', '1', 'system',
                    'schema migration', 'schema migration',
                    ?, ?, 'system'
                )
            """, (_now_bf, _now_bf))
            conn.commit()
        # ── mem_archive: cold storage for archived L2 entries (I-42 Phase 2) ──
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS mem_archive (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                original_id  INTEGER,
                key          TEXT UNIQUE NOT NULL,
                value        TEXT NOT NULL,
                scope        TEXT NOT NULL,
                tags         TEXT NOT NULL,
                tags_search  TEXT NOT NULL,
                created_at   TEXT NOT NULL,
                last_used_at TEXT NOT NULL,
                expires_at   TEXT,
                archived_at  TEXT NOT NULL
            );
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_mem_archive_key ON mem_archive(key);"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_mem_archive_archived_at ON mem_archive(archived_at);"
        )
        # ── QS-5: owner column on mem_archive ──
        try:
            conn.execute(
                "ALTER TABLE mem_archive ADD COLUMN owner TEXT NOT NULL DEFAULT ''"
            )
        except Exception:
            pass
        # ── toggle_audit: kill switch audit trail ──
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS toggle_audit (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_id     TEXT    NOT NULL,
                old_state     TEXT    NOT NULL,
                new_state     TEXT    NOT NULL,
                source        TEXT    NOT NULL DEFAULT 'unknown',
                source_detail TEXT    NOT NULL DEFAULT '',
                timestamp     TEXT    NOT NULL,
                context_id    TEXT    NOT NULL DEFAULT '',
                user_id       TEXT    NOT NULL DEFAULT '',
                parent_id     TEXT    NOT NULL DEFAULT ''
            );
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_toggle_audit_entity "
            "ON toggle_audit(entity_id);"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_toggle_audit_ts "
            "ON toggle_audit(timestamp);"
        )
        # ── sqlite-vec: load extension and create vector table ──
        _init_vec0(conn, _VEC_DIMENSIONS)
        conn.execute("PRAGMA optimize;")
        conn.commit()


@pyscript_compile  # noqa: F821
def _init_vec0(conn: sqlite3.Connection, dims: int = 512) -> bool:
    """Load sqlite-vec extension and create mem_vec table. Returns True on success."""
    vec_so = Path(f"{VEC0_PATH}.so")
    if not vec_so.exists():
        return False
    try:
        conn.enable_load_extension(True)
        conn.load_extension(VEC0_PATH)
        conn.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS mem_vec USING vec0("
            f"    key TEXT PRIMARY KEY,"
            f"    embedding float[{dims}]"
            f");"
        )
        return True
    except Exception:
        return False


@pyscript_executor  # noqa: F821
def _check_vec0_sync() -> bool:
    """Check if vec0.so can be loaded. Called from async context to set _VEC_AVAILABLE."""
    vec_so = Path(f"{VEC0_PATH}.so")
    if not vec_so.exists():
        return False
    try:
        with closing(sqlite3.connect(":memory:")) as conn:
            conn.enable_load_extension(True)
            conn.load_extension(VEC0_PATH)
        return True
    except Exception:
        return False


@pyscript_compile  # noqa: F821
def _ensure_db_once(force: bool = False) -> None:
    """Ensure the database schema exists once per runtime."""
    global _DB_READY
    if force:
        _DB_READY = False
    if _DB_READY and DB_PATH.exists():
        return
    with _DB_READY_LOCK:
        if force:
            _DB_READY = False
        if not _DB_READY or not DB_PATH.exists():
            _ensure_db()
            _DB_READY = True


async def _call_llm_direct_embed(text: str) -> dict:
    """Call pyscript.llm_direct_embed via service.call (cross-module)."""
    def _call_sync():
        return service.call(  # noqa: F821
            "pyscript", "llm_direct_embed",
            text=text,
            return_response=True,
        )
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(_call_sync),
            timeout=30,
        )
        return result if isinstance(result, dict) else {"status": "error", "error": "bad_response_type"}
    except asyncio.TimeoutError:
        return {"status": "error", "error": "timeout"}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


@pyscript_compile  # noqa: F821
def _normalize_value(s: str) -> str:
    """Normalize a text value for storage (NFC)."""
    if s is None:
        return ""
    return unicodedata.normalize("NFC", str(s))


@pyscript_compile  # noqa: F821
def _strip_diacritics(value: str) -> str:
    """Remove diacritics and normalize locale-specific letters (Vietnamese, Turkish, Spanish, Germanic, Nordic)."""
    if value is None:
        return ""
    decomposed = unicodedata.normalize("NFKD", value)
    filtered: list[str] = []
    for ch in decomposed:
        replacement = EXTRA_CHAR_REPLACEMENTS.get(ch)
        if replacement is not None:
            if replacement:
                filtered.extend(replacement)
            continue
        if unicodedata.category(ch) == "Mn":
            continue
        filtered.append(ch)
    return "".join(filtered)


@pyscript_compile  # noqa: F821
def _normalize_search_text(value: str | None) -> str:
    """Lowercase, strip diacritics, and collapse whitespace for search usage."""
    if value is None:
        return ""
    lowered = str(value).lower()
    stripped = _strip_diacritics(lowered)
    cleaned = re.sub(r"[,/_]+", " ", stripped)
    cleaned = re.sub(r"[^a-z0-9]+", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


@pyscript_compile  # noqa: F821
def _normalize_tags(s: str) -> str:
    """Normalize tags similarly to keys but retain space-separated words."""
    return _normalize_search_text(s)


@pyscript_compile  # noqa: F821
def _normalize_key(s: str) -> str:
    """Normalize a key to [a-z0-9_], lowercase, no accents."""
    if s is None:
        return ""
    s = str(s).strip().lower()
    s = _strip_diacritics(s)
    s = re.sub(r"[^a-z0-9_]", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s


def _condense_candidate_for_selection(
    entry: dict[str, Any], *, score: float | None = None
) -> dict[str, Any]:
    """Prepare a candidate dict with trimmed value and optional score."""
    value = entry.get("value")
    if isinstance(value, str) and len(value) > VALUE_PREVIEW_CHARS:
        value = value[: VALUE_PREVIEW_CHARS - 3] + "..."
    data = {
        "key": entry.get("key"),
        "value": value,
        "scope": entry.get("scope"),
        "tags": entry.get("tags"),
        "created_at": entry.get("created_at"),
        "last_used_at": entry.get("last_used_at"),
        "expires_at": entry.get("expires_at"),
    }
    if score is not None:
        data["match_score"] = score
    return data


@pyscript_compile  # noqa: F821
def _calculate_match_score(
    source_tokens: set[str], candidate_tokens: set[str], bm25_raw: float | None
) -> float:
    """Blend Jaccard overlap with BM25 to estimate relevance."""
    if not source_tokens or not candidate_tokens:
        jaccard_score = 0.0
    else:
        intersection = source_tokens.intersection(candidate_tokens)
        if not intersection:
            return 0.0
        union = source_tokens.union(candidate_tokens)
        union_size = len(union) or 1
        jaccard_score = len(intersection) / union_size
    if isinstance(bm25_raw, (int, float)):
        bm25_score = 1 / (1 + max(bm25_raw, 0))
        jaccard_weight = 1 - BM25_WEIGHT
        return BM25_WEIGHT * bm25_score + jaccard_weight * jaccard_score
    return jaccard_score


async def _search_tag_candidates(
    source: str,
    *,
    exclude_keys: set[str] | None = None,
    limit: int | None = None,
    log_context: str = "tag lookup",
) -> list[tuple[dict[str, Any], float]]:
    """Return (entry, score) tuples for memories sharing normalized tags."""
    tags_search = _normalize_tags(source or "")
    if not tags_search:
        return []
    tag_tokens = {token for token in tags_search.split() if token}
    if not tag_tokens:
        return []
    limit_value = (
        limit if limit is not None else min(CANDIDATE_CHECK_LIMIT, SEARCH_LIMIT_MAX)
    )
    limit_value = max(1, min(limit_value, SEARCH_LIMIT_MAX))
    try:
        raw_matches = await _memory_search_db(tags_search, limit=limit_value)
    except Exception as lookup_err:
        log.error(f"memory {log_context} failed for '{tags_search}': {lookup_err}")  # noqa: F821
        return []
    if not raw_matches:
        return []
    exclude_norm = (
        {_normalize_key(item) for item in exclude_keys if item}
        if exclude_keys
        else set()
    )
    dedup: dict[str, tuple[dict[str, Any], float]] = {}
    for item in raw_matches:
        existing_key = _normalize_key(item.get("key"))
        if not existing_key or existing_key in exclude_norm or existing_key in dedup:
            continue
        score_raw = item.get("match_score")
        score_val: float | None
        if isinstance(score_raw, (int, float)):
            score_val = float(score_raw)
        else:
            try:
                score_val = float(score_raw)
            except (TypeError, ValueError):
                existing_tags_norm = _normalize_tags(item.get("tags"))
                candidate_tokens = {
                    token for token in existing_tags_norm.split() if token
                }
                score_val = _calculate_match_score(tag_tokens, candidate_tokens, None)
        if score_val is None or score_val <= 0:
            continue
        dedup[existing_key] = (item, score_val)
    if not dedup:
        return []
    sorted_candidates = sorted(dedup.values(), key=lambda pair: pair[1], reverse=True)
    return sorted_candidates[:limit_value]


async def _find_tag_matches_for_query(
    source: str,
    *,
    exclude_keys: set[str] | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Search for potential key matches based on normalized tags."""
    candidates = await _search_tag_candidates(
        source,
        exclude_keys=exclude_keys,
        limit=limit,
        log_context="tag lookup",
    )
    if not candidates:
        return []
    return [
        _condense_candidate_for_selection(entry, score=score)
        for entry, score in candidates
    ]


@pyscript_compile  # noqa: F821
def _tokenize_query(q: str) -> list[str]:
    """Tokenize a free-text query into normalized word tokens for FTS."""
    normalized = _normalize_search_text(q)
    if not normalized:
        return []
    return normalized.split()


@pyscript_compile  # noqa: F821
def _near_distance_for_tokens(n: int) -> int:
    """Compute dynamic NEAR distance based on token count."""
    if n <= 1:
        return 0
    val = 2 * n - 1
    if val < 3:
        val = 3
    if val > NEAR_DISTANCE:
        val = NEAR_DISTANCE
    return val


@pyscript_compile  # noqa: F821
def _build_fts_queries(raw_query: str) -> list[str]:
    """Build a list of FTS5 MATCH query variants to improve recall.

    Strategy (ordered by priority):
    - PHRASE: exact phrase (highest precision when user typed a phrase)
    - NEAR: tokens appear within proximity (high relevance, dynamic distance)
    - AND: all tokens must appear (relevant but looser than NEAR)
    - OR*: any token with prefix match (broad recall)
    - RAW: the original raw query as a last option
    """
    normalized_query = _normalize_search_text(raw_query)
    tokens = normalized_query.split() if normalized_query else []
    variants = []

    if tokens:
        # 1) PHRASE exact order (if 2+ tokens)
        if len(tokens) >= 2:
            phrase = " ".join(tokens)
            variants.append(f'"{phrase}"')

        # 2) NEAR across all tokens (if 2+ tokens)
        if len(tokens) >= 2:
            near_inner = " ".join(tokens)
            near_dist = _near_distance_for_tokens(len(tokens))
            variants.append(f"NEAR({near_inner}, {near_dist})")

        # 3) AND of all tokens (or single token)
        if len(tokens) == 1:
            variants.append(tokens[0])
        else:
            variants.append(" AND ".join(tokens))

        # 4) OR with prefix match to broaden recall
        or_tokens = [f"{t}*" for t in tokens]
        variants.append(" OR ".join(or_tokens))

    # 5) RAW as very last resort if provided
    if normalized_query:
        variants.append(normalized_query)
    rq = (raw_query or "").strip()
    if rq:
        variants.append(rq)

    # Deduplicate while preserving order
    seen = set()
    out = []
    for v in variants:
        if v not in seen:
            out.append(v)
            seen.add(v)
    return out


@pyscript_compile  # noqa: F821
def _fetch_with_expiry(
    cur: sqlite3.Cursor, key: str
) -> tuple[bool, sqlite3.Row | None]:
    """Fetch the row and report whether it is expired; never deletes the row."""
    row = cur.execute(
        """
        SELECT key,
               value,
               scope,
               tags,
               created_at,
               last_used_at,
               expires_at,
               owner
        FROM mem
        WHERE key = ?;
        """,
        (key,),
    ).fetchone()
    if not row:
        return False, None
    expires_at = row["expires_at"]
    if expires_at:
        dt = _dt_from_iso(expires_at)
        if dt and datetime.now(UTC) > dt:
            return True, row
    return False, row


def _set_result(state_value: str = "ok", **attrs: Any) -> None:
    """Set result sensor state and attributes."""
    _ensure_result_entity_name()
    attrs.update(result_entity_name)
    state.set(RESULT_ENTITY, value=state_value, new_attributes=attrs)  # noqa: F821


@pyscript_compile  # noqa: F821
def _reset_db_ready() -> None:
    """Mark the cached DB-ready flag as stale so the next call rebuilds."""
    global _DB_READY
    with _DB_READY_LOCK:
        _DB_READY = False


@pyscript_compile  # noqa: F821
def _track_write_failure() -> str | None:
    """Increment write failure count; transition to read_only if threshold exceeded.

    Returns "read_only" if mode just transitioned, else None.
    Safe to call from @pyscript_executor context (no pyscript builtins used).
    """
    global _db_write_fail_count, _db_mode
    with _db_mode_lock:
        _db_write_fail_count += 1
        if _db_write_fail_count >= _DB_WRITE_FAIL_THRESHOLD and _db_mode == "normal":
            _db_mode = "read_only"
            return "read_only"
    return None


@pyscript_compile  # noqa: F821
def _track_write_success() -> str | None:
    """Reset failure count; promote from read_only to normal if recovered.

    Returns "normal" if mode just transitioned, else None.
    Safe to call from @pyscript_executor context (no pyscript builtins used).
    """
    global _db_write_fail_count, _db_mode
    with _db_mode_lock:
        _db_write_fail_count = 0
        if _db_mode == "read_only":
            _db_mode = "normal"
            return "normal"
    return None


@pyscript_compile  # noqa: F821
def _is_write_allowed() -> bool:
    """Return True if the DB is in normal (writable) mode.

    Safe to call from @pyscript_executor context (no pyscript builtins used).
    """
    return _db_mode == "normal"


@pyscript_executor  # noqa: F821
def _memory_set_db_sync(
    key_norm: str,
    value_norm: str,
    scope_norm: str,
    tags_raw: str,
    tags_search: str,
    now_iso: str,
    expires_at: str | None,
    owner_norm: str = "",
) -> bool:
    """Persist a memory record, retrying once if schema objects are missing."""
    if not _is_write_allowed():
        return False
    for attempt in range(2):
        try:
            _ensure_db_once(force=attempt == 1)
            with closing(_get_db_connection()) as conn:
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO mem(key, value, scope, tags, tags_search,
                                    created_at, last_used_at, expires_at, owner)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET value=excluded.value,
                                                   scope=excluded.scope,
                                                   tags=excluded.tags,
                                                   tags_search=excluded.tags_search,
                                                   last_used_at=excluded.last_used_at,
                                                   expires_at=excluded.expires_at,
                                                   owner=excluded.owner
                    """,
                    (
                        key_norm,
                        value_norm,
                        scope_norm,
                        tags_raw,
                        tags_search,
                        now_iso,
                        now_iso,
                        expires_at,
                        owner_norm,
                    ),
                )
                conn.commit()
            _track_write_success()
            return True
        except sqlite3.OperationalError:
            _reset_db_ready()
            _track_write_failure()
            if attempt == 0:
                time.sleep(0.1)
                continue
            raise
    return False


@pyscript_executor  # noqa: F821
def _memory_key_exists_db_sync(key_norm: str) -> bool:
    """Return True if a memory row already exists for key."""
    for attempt in range(2):
        try:
            _ensure_db_once(force=attempt == 1)
            with closing(_get_db_connection()) as conn:
                cur = conn.cursor()
                row = cur.execute(
                    "SELECT 1 FROM mem WHERE key = ? LIMIT 1",
                    (key_norm,),
                ).fetchone()
                return row is not None
        except sqlite3.OperationalError:
            _reset_db_ready()
            if attempt == 0:
                time.sleep(0.1)
                continue
            raise
    return False


@pyscript_executor  # noqa: F821
def _memory_get_db_sync(key_norm: str) -> tuple[str, dict[str, Any] | None]:
    """Fetch a memory by key, updating access time and handling expiry."""
    for attempt in range(2):
        try:
            _ensure_db_once(force=attempt == 1)
            with closing(_get_db_connection()) as conn:
                cur = conn.cursor()
                expired, row = _fetch_with_expiry(cur, key_norm)
                if row is None:
                    return "not_found", None
                row_data = {
                    "key": row["key"],
                    "value": row["value"],
                    "scope": row["scope"],
                    "tags": row["tags"],
                    "created_at": row["created_at"],
                    "last_used_at": row["last_used_at"],
                    "expires_at": row["expires_at"],
                    "owner": row["owner"] if "owner" in row.keys() else "",
                }
                if expired:
                    return "expired", row_data
                last_used_iso = _utcnow_iso()
                cur.execute(
                    "UPDATE mem SET last_used_at=? WHERE key=?",
                    (last_used_iso, key_norm),
                )
                conn.commit()
            row_data["last_used_at"] = last_used_iso
            return "ok", row_data
        except sqlite3.OperationalError:
            _reset_db_ready()
            if attempt == 0:
                time.sleep(0.1)
                continue
            raise
    return "error", None


@pyscript_compile  # noqa: F821
def _vec_knn_search_sync(
    conn: sqlite3.Connection, query_vec: list[float], limit: int, threshold: float
) -> dict[str, float]:
    """Run KNN search on mem_vec, return {key: similarity_score}."""
    if not _VEC_AVAILABLE or not query_vec:
        return {}
    try:
        vec_bytes = struct.pack(f"<{len(query_vec)}f", *query_vec)
        rows = conn.execute(
            """
            SELECT v.key, v.distance
            FROM mem_vec AS v
            WHERE v.embedding MATCH ?
              AND k = ?
            ORDER BY v.distance
            """,
            (vec_bytes, limit * 2),
        ).fetchall()
        results: dict[str, float] = {}
        for row in rows:
            # sqlite-vec distance is L2; convert to similarity: 1 / (1 + distance)
            dist = float(row["distance"]) if row["distance"] is not None else 999.0
            similarity = 1.0 / (1.0 + dist)
            if similarity >= threshold:
                results[row["key"]] = similarity
        return results
    except Exception:
        return {}


@pyscript_executor  # noqa: F821
def _memory_search_db_sync(
    query: str, limit: int, query_vec: list[float] | None = None
) -> list[dict[str, Any]]:
    """Run the primary search query, returning matching memory rows.

    If query_vec is provided and vec0 is loaded, blends FTS5 scores with
    semantic similarity based on the ai_semantic_blend_weight helper.
    """
    normalized_query = _normalize_search_text(query)
    query_tokens = set(normalized_query.split()) if normalized_query else set()

    # Read blend weight (0=FTS5 only, 100=semantic only)
    blend_w = 0
    if _VEC_AVAILABLE and query_vec:
        try:
            raw = state.get("input_number.ai_semantic_blend_weight")  # noqa: F821
            blend_w = int(float(raw)) if raw not in (None, "unknown", "unavailable") else 50
        except (TypeError, ValueError, NameError):
            blend_w = 50
    sem_weight = max(0, min(blend_w, 100)) / 100.0

    # Read similarity threshold
    sim_threshold = 0.7
    if sem_weight > 0:
        try:
            raw = state.get("input_number.ai_semantic_similarity_threshold")  # noqa: F821
            sim_threshold = float(raw) if raw not in (None, "unknown", "unavailable") else 0.7
        except (TypeError, ValueError, NameError):
            sim_threshold = 0.7

    for attempt in range(2):
        try:
            _ensure_db_once(force=attempt == 1)
            with closing(_get_db_connection()) as conn:
                # ── Load vec0 extension for this connection if available ──
                if _VEC_AVAILABLE:
                    try:
                        conn.enable_load_extension(True)
                        conn.load_extension(VEC0_PATH)
                    except Exception:
                        pass

                cur = conn.cursor()
                found_by_key: dict[str, sqlite3.Row] = {}
                total_rows: list[sqlite3.Row] = []
                match_variants = _build_fts_queries(query)

                for mv in match_variants:
                    if len(found_by_key) >= limit:
                        break
                    try:
                        fetched = cur.execute(
                            """
                            SELECT DISTINCT m.key,
                                            m.value,
                                            m.scope,
                                            m.tags,
                                            m.tags_search,
                                            m.created_at,
                                            m.last_used_at,
                                            m.expires_at,
                                            m.owner,
                                            mem_fts.rank AS rank
                            FROM mem_fts
                                     JOIN mem AS m
                                          ON m.id = mem_fts.rowid
                            WHERE mem_fts MATCH ?
                            ORDER BY rank, m.last_used_at DESC
                            LIMIT ?;
                            """,
                            (mv, limit),
                        ).fetchall()
                    except sqlite3.Error as error:
                        log.warning(f"FTS variant failed: {error}")  # noqa: F821
                        continue
                    for row in fetched:
                        key = row["key"]
                        if key not in found_by_key:
                            found_by_key[key] = row
                            total_rows.append(row)
                        if len(found_by_key) >= limit:
                            break
                if not total_rows:
                    # Fallback to LIKE using normalized query to match normalized columns (key, tags)
                    # We prioritize normalized matching because key/tags are the primary search vectors.
                    like_q = f"%{normalized_query}%"
                    total_rows = cur.execute(
                        """
                        SELECT DISTINCT m.key,
                                        m.value,
                                        m.scope,
                                        m.tags,
                                        m.tags_search,
                                        m.created_at,
                                        m.last_used_at,
                                        m.expires_at,
                                        m.owner,
                                        NULL AS rank
                        FROM mem AS m
                        WHERE m.value LIKE ?
                           OR m.tags LIKE ?
                           OR m.tags_search LIKE ?
                           OR m.key LIKE ?
                        ORDER BY m.last_used_at DESC
                        LIMIT ?;
                        """,
                        (like_q, like_q, like_q, like_q, limit),
                    ).fetchall()

                # ── Semantic KNN search (if vec0 available + blend > 0) ──
                sem_scores: dict[str, float] = {}
                if sem_weight > 0 and query_vec:
                    sem_scores = _vec_knn_search_sync(conn, query_vec, limit, sim_threshold)

            # ── Score FTS5 results ──
            fts_results: dict[str, dict[str, Any]] = {}
            for row in total_rows:
                candidate_source = row["tags_search"] or _normalize_tags(row["tags"])
                candidate_tokens = {
                    token for token in candidate_source.split() if token
                }
                fts_score = _calculate_match_score(
                    query_tokens, candidate_tokens, row["rank"]
                )
                fts_results[row["key"]] = {
                    "key": row["key"],
                    "value": row["value"],
                    "scope": row["scope"],
                    "tags": row["tags"],
                    "created_at": row["created_at"],
                    "last_used_at": row["last_used_at"],
                    "expires_at": row["expires_at"],
                    "owner": row["owner"] if "owner" in row.keys() else "",
                    "fts_score": fts_score,
                }

            # ── Blend scores if semantic results exist ──
            if sem_scores and sem_weight > 0:
                all_keys = set(fts_results.keys()) | set(sem_scores.keys())
                # Fetch full rows for semantic-only results not in FTS set
                sem_only_keys = set(sem_scores.keys()) - set(fts_results.keys())
                if sem_only_keys:
                    try:
                        with closing(_get_db_connection()) as conn2:
                            placeholders = ",".join("?" for _ in sem_only_keys)
                            rows = conn2.execute(
                                f"""
                                SELECT key, value, scope, tags, tags_search,
                                       created_at, last_used_at, expires_at, owner
                                FROM mem WHERE key IN ({placeholders})
                                """,
                                list(sem_only_keys),
                            ).fetchall()
                            for row in rows:
                                fts_results[row["key"]] = {
                                    "key": row["key"],
                                    "value": row["value"],
                                    "scope": row["scope"],
                                    "tags": row["tags"],
                                    "created_at": row["created_at"],
                                    "last_used_at": row["last_used_at"],
                                    "expires_at": row["expires_at"],
                                    "owner": row["owner"] if "owner" in row.keys() else "",
                                    "fts_score": 0.0,
                                }
                    except Exception:
                        pass

                # Compute blended scores
                blended: list[tuple[str, float]] = []
                for key in all_keys:
                    if key not in fts_results:
                        continue
                    fts_s = fts_results[key].get("fts_score", 0.0)
                    sem_s = sem_scores.get(key, 0.0)
                    combined = (1.0 - sem_weight) * fts_s + sem_weight * sem_s
                    blended.append((key, combined))
                blended.sort(key=lambda x: x[1], reverse=True)

                results: list[dict[str, Any]] = []
                for key, score in blended[:limit]:
                    entry = fts_results[key]
                    entry["match_score"] = round(score, 4)
                    results.append(entry)
                return results

            # ── FTS-only results (no blending) ──
            results = []
            for entry in fts_results.values():
                entry["match_score"] = entry.pop("fts_score", 0.0)
                results.append(entry)
            return results
        except sqlite3.OperationalError:
            _reset_db_ready()
            if attempt == 0:
                time.sleep(0.1)
                continue
            raise
    return []


@pyscript_executor  # noqa: F821
def _memory_forget_db_sync(key_norm: str) -> int:
    """Delete a memory row by key and return the number of rows removed."""
    for attempt in range(2):
        try:
            _ensure_db_once(force=attempt == 1)
            with closing(_get_db_connection()) as conn:
                cur = conn.cursor()
                cur.execute("DELETE FROM mem WHERE key=?", (key_norm,))
                rowcount = getattr(cur, "rowcount", -1)
                cur.execute(
                    "DELETE FROM mem_rel WHERE from_key = ? OR to_key = ?",
                    (key_norm, key_norm),
                )
                # ── I-42 Phase 2: clean vec orphans (best-effort, vec0 may not be loaded) ──
                try:
                    cur.execute("DELETE FROM mem_vec WHERE key = ?", (key_norm,))
                except sqlite3.OperationalError:
                    pass
                deleted = rowcount if rowcount and rowcount > 0 else 0
                conn.commit()
            return deleted
        except sqlite3.OperationalError:
            _reset_db_ready()
            if attempt == 0:
                time.sleep(0.1)
                continue
            raise
    return 0


@pyscript_executor  # noqa: F821
def _memory_purge_expired_db_sync(grace_days: int = 0) -> int:
    """Remove expired rows older than the grace period and report how many were purged."""
    grace = max(int(grace_days), 0)
    cutoff_dt = datetime.now(UTC) - timedelta(days=grace)
    cutoff_iso = cutoff_dt.isoformat()
    for attempt in range(2):
        try:
            _ensure_db_once(force=attempt == 1)
            with closing(_get_db_connection()) as conn:
                cur = conn.cursor()
                # ── I-42 Phase 2: collect keys before delete for vec cleanup ──
                cur.execute(
                    "SELECT key FROM mem WHERE expires_at IS NOT NULL AND expires_at < ?",
                    (cutoff_iso,),
                )
                expired_keys = [r[0] for r in cur.fetchall()]
                cur.execute(
                    "DELETE FROM mem WHERE expires_at IS NOT NULL AND expires_at < ?",
                    (cutoff_iso,),
                )
                rowcount = getattr(cur, "rowcount", -1)
                removed = rowcount if rowcount and rowcount > 0 else 0
                # ── Clean vec orphans for purged keys (best-effort, vec0 may not be loaded) ──
                if expired_keys:
                    try:
                        placeholders = ",".join("?" * len(expired_keys))
                        cur.execute(
                            f"DELETE FROM mem_vec WHERE key IN ({placeholders})",
                            expired_keys,
                        )
                    except sqlite3.OperationalError:
                        pass
                conn.commit()
            return removed
        except sqlite3.OperationalError:
            _reset_db_ready()
            if attempt == 0:
                time.sleep(0.1)
                continue
            raise
    return 0


@pyscript_executor  # noqa: F821
def _memory_reindex_fts_db_sync() -> tuple[int, int]:
    """Rebuild the FTS index, returning counts before and after the rebuild."""
    for attempt in range(2):
        try:
            _ensure_db_once(force=attempt == 1)
            with closing(_get_db_connection()) as conn:
                cur = conn.cursor()
                cur.execute("BEGIN IMMEDIATE")
                try:
                    cur.execute("SELECT COUNT(*) FROM mem_fts")
                    before = cur.fetchone()[0]
                except sqlite3.Error:
                    before = 0

                cur.execute("DROP TABLE IF EXISTS mem_fts")
                cur.execute(
                    """
                    CREATE VIRTUAL TABLE mem_fts USING fts5(
                        key, value, tags,
                        content='mem',
                        content_rowid='id',
                        tokenize = 'unicode61 remove_diacritics 2'
                    );
                    """
                )

                cur.executescript(
                    """
                    CREATE TRIGGER IF NOT EXISTS mem_ai
                        AFTER INSERT
                        ON mem
                    BEGIN
                        INSERT INTO mem_fts(rowid, key, value, tags)
                        VALUES (new.id,
                                new.key,
                                new.value,
                                new.tags_search);
                    END;

                    CREATE TRIGGER IF NOT EXISTS mem_ad
                        AFTER DELETE
                        ON mem
                    BEGIN
                        INSERT INTO mem_fts(mem_fts, rowid, key, value, tags)
                        VALUES ('delete', old.id, old.key, old.value, old.tags_search);
                    END;

                    CREATE TRIGGER IF NOT EXISTS mem_au
                        AFTER UPDATE OF key, value, tags_search
                        ON mem
                        WHEN (old.key IS NOT new.key)
                            OR (old.value IS NOT new.value)
                            OR (old.tags_search IS NOT new.tags_search)
                    BEGIN
                        INSERT INTO mem_fts(mem_fts, rowid, key, value, tags)
                        VALUES ('delete', old.id, old.key, old.value, old.tags_search);
                        INSERT INTO mem_fts(rowid, key, value, tags)
                        VALUES (new.id,
                                new.key,
                                new.value,
                                new.tags_search);
                    END;
                    """
                )

                cur.execute("INSERT INTO mem_fts(mem_fts) VALUES('rebuild')")
                cur.execute("SELECT COUNT(*) FROM mem_fts")
                after = cur.fetchone()[0]
                conn.commit()
            return before, after
        except sqlite3.OperationalError:
            _reset_db_ready()
            if attempt == 0:
                time.sleep(0.1)
                continue
            raise
    return 0, 0


@pyscript_executor  # noqa: F821
def _memory_health_check_db_sync() -> tuple[int, int, int, int, int, int]:
    """Return basic health counts (total, expired, FTS rows, rel rows, db size bytes, archived) for diagnostics."""
    import os

    for attempt in range(2):
        try:
            _ensure_db_once(force=attempt == 1)
            with closing(_get_db_connection()) as conn:
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) FROM mem")
                rows = cur.fetchone()[0]
                now_iso = _utcnow_iso()
                cur.execute(
                    "SELECT COUNT(*) FROM mem WHERE expires_at IS NOT NULL AND expires_at < ?",
                    (now_iso,),
                )
                expired = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM mem_fts")
                fts_rows = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM mem_rel")
                rel_count = cur.fetchone()[0]
                # ── I-42 Phase 2: archived count ──
                cur.execute("SELECT COUNT(*) FROM mem_archive")
                archived_count = cur.fetchone()[0]
            try:
                db_size_bytes = os.path.getsize(str(DB_PATH))
            except OSError:
                db_size_bytes = 0
            return rows, expired, fts_rows, rel_count, db_size_bytes, archived_count
        except sqlite3.OperationalError:
            _reset_db_ready()
            if attempt == 0:
                time.sleep(0.1)
                continue
            raise
    return 0, 0, 0, 0, 0, 0


@pyscript_executor  # noqa: F821
def _memory_auto_link_db_sync(
    source_key: str,
    candidates: list[tuple[str, float]],
    now_iso: str,
    min_weight: float = MIN_REL_WEIGHT,
) -> int:
    """Persist bidirectional relationships for tag/content overlap."""
    for attempt in range(2):
        try:
            _ensure_db_once(force=attempt == 1)
            linked = 0
            with closing(_get_db_connection()) as conn:
                cur = conn.cursor()
                for target_key, weight in candidates:
                    if weight < min_weight or target_key == source_key:
                        continue
                    cur.execute(
                        """INSERT OR REPLACE INTO mem_rel
                           (from_key, to_key, weight, rel_type, created_at)
                           VALUES (?, ?, ?, 'tag_overlap', ?)""",
                        (source_key, target_key, weight, now_iso),
                    )
                    cur.execute(
                        """INSERT OR REPLACE INTO mem_rel
                           (from_key, to_key, weight, rel_type, created_at)
                           VALUES (?, ?, ?, 'tag_overlap', ?)""",
                        (target_key, source_key, weight, now_iso),
                    )
                    linked += 1
                conn.commit()
            return linked
        except sqlite3.OperationalError:
            _reset_db_ready()
            if attempt == 0:
                time.sleep(0.1)
                continue
            raise
    return 0


@pyscript_executor  # noqa: F821
def _memory_related_db_sync(
    key_norm: str, limit: int, depth: int
) -> list[dict[str, Any]]:
    """Fetch related memories via the relationship graph."""
    for attempt in range(2):
        try:
            _ensure_db_once(force=attempt == 1)
            with closing(_get_db_connection()) as conn:
                cur = conn.cursor()
                visited = {key_norm}
                current_keys = {key_norm}
                all_results = []

                for d in range(depth):
                    if not current_keys:
                        break
                    placeholders = ",".join("?" for _ in current_keys)
                    visited_ph = ",".join("?" for _ in visited)
                    rows = cur.execute(
                        f"""SELECT r.to_key, r.weight, r.rel_type, r.created_at,
                                   m.value, m.scope, m.tags, m.created_at AS mem_created,
                                   m.last_used_at, m.expires_at, m.owner
                            FROM mem_rel r
                            JOIN mem m ON m.key = r.to_key
                            WHERE r.from_key IN ({placeholders})
                              AND r.to_key NOT IN ({visited_ph})
                            ORDER BY r.weight DESC
                            LIMIT ?""",
                        (*current_keys, *visited, limit),
                    ).fetchall()

                    next_keys = set()
                    for row in rows:
                        to_key = row["to_key"]
                        if to_key in visited:
                            continue
                        visited.add(to_key)
                        next_keys.add(to_key)
                        all_results.append({
                            "key": to_key,
                            "value": row["value"],
                            "scope": row["scope"],
                            "tags": row["tags"],
                            "owner": row["owner"] if "owner" in row.keys() else "",
                            "weight": row["weight"],
                            "rel_type": row["rel_type"],
                            "rel_created_at": row["created_at"],
                            "created_at": row["mem_created"],
                            "last_used_at": row["last_used_at"],
                            "expires_at": row["expires_at"],
                            "depth": d + 1,
                        })
                    current_keys = next_keys

                all_results.sort(key=lambda x: x["weight"], reverse=True)
                return all_results[:limit]
        except sqlite3.OperationalError:
            _reset_db_ready()
            if attempt == 0:
                time.sleep(0.1)
                continue
            raise
    return []


@pyscript_executor  # noqa: F821
def _memory_search_enrich_db_sync(
    source_keys: list[str],
    exclude_keys: set[str],
    max_results: int,
    min_weight: float,
) -> list[dict[str, Any]]:
    """Fetch depth-1 related memories for a batch of source keys.

    Returns related entries ordered by weight descending, excluding
    any key in exclude_keys (the direct search hits).
    """
    if not source_keys:
        return []
    for attempt in range(2):
        try:
            _ensure_db_once(force=attempt == 1)
            with closing(_get_db_connection()) as conn:
                cur = conn.cursor()
                key_ph = ",".join("?" for _ in source_keys)
                params: list[Any] = list(source_keys) + [min_weight]
                excl_clause = ""
                if exclude_keys:
                    excl_ph = ",".join("?" for _ in exclude_keys)
                    excl_clause = f" AND r.to_key NOT IN ({excl_ph})"
                    params.extend(exclude_keys)
                params.append(max_results)

                rows = cur.execute(
                    f"""SELECT r.from_key AS related_to,
                               r.to_key,
                               r.weight,
                               r.rel_type,
                               m.key,
                               m.value,
                               m.scope,
                               m.tags,
                               m.created_at,
                               m.last_used_at,
                               m.expires_at,
                               m.owner
                        FROM mem_rel r
                        JOIN mem m ON m.key = r.to_key
                        WHERE r.from_key IN ({key_ph})
                          AND r.weight >= ?
                          {excl_clause}
                        ORDER BY r.weight DESC
                        LIMIT ?""",
                    params,
                ).fetchall()

                seen: set[str] = set()
                results: list[dict[str, Any]] = []
                for row in rows:
                    to_key = row["to_key"]
                    if to_key in seen:
                        continue
                    seen.add(to_key)
                    results.append({
                        "key": row["key"],
                        "value": row["value"],
                        "scope": row["scope"],
                        "tags": row["tags"],
                        "owner": row["owner"] if "owner" in row.keys() else "",
                        "created_at": row["created_at"],
                        "last_used_at": row["last_used_at"],
                        "expires_at": row["expires_at"],
                        "match_score": 0.0,
                        "related": True,
                        "related_to": row["related_to"],
                        "rel_weight": row["weight"],
                        "rel_type": row["rel_type"],
                    })
                return results
        except sqlite3.OperationalError:
            _reset_db_ready()
            if attempt == 0:
                time.sleep(0.1)
                continue
            raise
    return []


@pyscript_executor  # noqa: F821
def _memory_semantic_autolink_db_sync(
    batch_limit: int,
    threshold: float,
) -> dict[str, int]:
    """Create content_match relationships via vec0 KNN for unlinked embeddings."""
    if not _VEC_AVAILABLE:
        return {"linked": 0, "keys_processed": 0}
    for attempt in range(2):
        try:
            _ensure_db_once(force=attempt == 1)
            with closing(_get_db_connection()) as conn:
                conn.enable_load_extension(True)
                conn.load_extension(VEC0_PATH)
                cur = conn.cursor()

                # Find keys with embeddings but no content_match edges
                rows = cur.execute(
                    """SELECT v.key, v.embedding
                       FROM mem_vec v
                       WHERE NOT EXISTS (
                           SELECT 1 FROM mem_rel r
                           WHERE r.from_key = v.key
                             AND r.rel_type = 'content_match'
                       )
                       LIMIT ?""",
                    (batch_limit,),
                ).fetchall()

                keys_processed = len(rows)
                linked = 0
                now_iso = datetime.now(UTC).isoformat()

                for row in rows:
                    source_key = row["key"]
                    embedding_bytes = row["embedding"]
                    if not embedding_bytes:
                        continue

                    # Decode embedding from blob to float list
                    n_floats = len(embedding_bytes) // 4
                    query_vec = list(struct.unpack(f"<{n_floats}f", embedding_bytes))

                    # Find KNN neighbors (reuse existing function logic)
                    neighbors = _vec_knn_search_sync(
                        conn, query_vec, limit=5, threshold=threshold,
                    )
                    for neighbor_key, similarity in neighbors.items():
                        if neighbor_key == source_key:
                            continue
                        # Insert bidirectional content_match edges
                        cur.execute(
                            """INSERT OR REPLACE INTO mem_rel
                               (from_key, to_key, weight, rel_type, created_at)
                               VALUES (?, ?, ?, 'content_match', ?)""",
                            (source_key, neighbor_key, similarity, now_iso),
                        )
                        cur.execute(
                            """INSERT OR REPLACE INTO mem_rel
                               (from_key, to_key, weight, rel_type, created_at)
                               VALUES (?, ?, ?, 'content_match', ?)""",
                            (neighbor_key, source_key, similarity, now_iso),
                        )
                        linked += 1
                conn.commit()
                return {"linked": linked, "keys_processed": keys_processed}
        except sqlite3.OperationalError:
            _reset_db_ready()
            if attempt == 0:
                time.sleep(0.1)
                continue
            raise
    return {"linked": 0, "keys_processed": 0}


@pyscript_executor  # noqa: F821
def _memory_link_db_sync(
    from_key: str,
    to_key: str,
    rel_type: str,
    now_iso: str,
) -> bool:
    """Insert a bidirectional manual relationship between two memories."""
    for attempt in range(2):
        try:
            _ensure_db_once(force=attempt == 1)
            with closing(_get_db_connection()) as conn:
                cur = conn.cursor()
                cur.execute(
                    """INSERT OR REPLACE INTO mem_rel
                       (from_key, to_key, weight, rel_type, created_at)
                       VALUES (?, ?, 1.0, ?, ?)""",
                    (from_key, to_key, rel_type, now_iso),
                )
                cur.execute(
                    """INSERT OR REPLACE INTO mem_rel
                       (from_key, to_key, weight, rel_type, created_at)
                       VALUES (?, ?, 1.0, ?, ?)""",
                    (to_key, from_key, rel_type, now_iso),
                )
                conn.commit()
            return True
        except sqlite3.OperationalError:
            _reset_db_ready()
            if attempt == 0:
                time.sleep(0.1)
                continue
            raise
    return False


@pyscript_executor  # noqa: F821
def _memory_prune_orphan_rels_db_sync() -> int:
    """Remove relationships where either key no longer exists in mem."""
    for attempt in range(2):
        try:
            _ensure_db_once(force=attempt == 1)
            with closing(_get_db_connection()) as conn:
                cur = conn.cursor()
                cur.execute(
                    """DELETE FROM mem_rel
                       WHERE from_key NOT IN (SELECT key FROM mem)
                          OR to_key NOT IN (SELECT key FROM mem)"""
                )
                rowcount = getattr(cur, "rowcount", -1)
                pruned = rowcount if rowcount and rowcount > 0 else 0
                conn.commit()
            return pruned
        except sqlite3.OperationalError:
            _reset_db_ready()
            if attempt == 0:
                time.sleep(0.1)
                continue
            raise
    return 0


async def _memory_set_db(
    key_norm: str,
    value_norm: str,
    scope_norm: str,
    tags_raw: str,
    tags_search: str,
    now_iso: str,
    expires_at: str | None,
    owner_norm: str = "",
) -> bool:
    """Async wrapper around _memory_set_db_sync to keep writes off the event loop."""
    return _memory_set_db_sync(
        key_norm,
        value_norm,
        scope_norm,
        tags_raw,
        tags_search,
        now_iso,
        expires_at,
        owner_norm,
    )


async def _memory_key_exists_db(key_norm: str) -> bool:
    """Async wrapper that checks key existence via _memory_key_exists_db_sync."""
    return _memory_key_exists_db_sync(key_norm)


async def _memory_get_db(key_norm: str) -> tuple[str, dict[str, Any] | None]:
    """Async wrapper for _memory_get_db_sync handling DB access in a thread."""
    return _memory_get_db_sync(key_norm)


async def _memory_search_db(
    query: str, limit: int, query_vec: list[float] | None = None
) -> list[dict[str, Any]]:
    """Async wrapper that runs _memory_search_db_sync without blocking."""
    return _memory_search_db_sync(query, limit, query_vec)


async def _memory_forget_db(key_norm: str) -> int:
    """Async wrapper for _memory_forget_db_sync."""
    return _memory_forget_db_sync(key_norm)


async def _memory_purge_expired_db(grace_days: int = 0) -> int:
    """Async wrapper for the purge helper supporting a grace window."""
    return _memory_purge_expired_db_sync(grace_days)


async def _memory_reindex_fts_db() -> tuple[int, int]:
    """Async wrapper rebuilding the FTS index via _memory_reindex_fts_db_sync."""
    return _memory_reindex_fts_db_sync()


async def _memory_health_check_db() -> tuple[int, int, int, int, int, int]:
    """Async wrapper running the health-check query in a thread."""
    return _memory_health_check_db_sync()


async def _memory_auto_link_db(
    source_key: str,
    candidates: list[tuple[str, float]],
    now_iso: str,
    min_weight: float = MIN_REL_WEIGHT,
) -> int:
    """Async wrapper for _memory_auto_link_db_sync."""
    return _memory_auto_link_db_sync(source_key, candidates, now_iso, min_weight)


async def _memory_auto_link(
    source_key: str,
    tags_search: str,
    exclude_keys: set[str] | None = None,
) -> int:
    """Find related memories by tag overlap and persist relationships."""
    candidates = await _search_tag_candidates(
        tags_search,
        exclude_keys=exclude_keys or {source_key},
        limit=CANDIDATE_CHECK_LIMIT,
        log_context="auto_link",
    )
    if not candidates:
        return 0
    pairs = [
        (_normalize_key(entry.get("key", "")), score)
        for entry, score in candidates
    ]
    return await _memory_auto_link_db(source_key, pairs, _utcnow_iso())


async def _memory_related_db(
    key_norm: str, limit: int, depth: int
) -> list[dict[str, Any]]:
    """Async wrapper for _memory_related_db_sync."""
    return _memory_related_db_sync(key_norm, limit, depth)


async def _memory_search_enrich_db(
    source_keys: list[str],
    exclude_keys: set[str],
    max_results: int,
    min_weight: float,
) -> list[dict[str, Any]]:
    """Async wrapper for _memory_search_enrich_db_sync."""
    return _memory_search_enrich_db_sync(source_keys, exclude_keys, max_results, min_weight)


async def _memory_semantic_autolink_db(
    batch_limit: int,
    threshold: float,
) -> dict[str, int]:
    """Async wrapper for _memory_semantic_autolink_db_sync."""
    return _memory_semantic_autolink_db_sync(batch_limit, threshold)


async def _memory_link_db(
    from_key: str, to_key: str, rel_type: str, now_iso: str
) -> bool:
    """Async wrapper for _memory_link_db_sync."""
    return _memory_link_db_sync(from_key, to_key, rel_type, now_iso)


async def _memory_prune_orphan_rels_db() -> int:
    """Async wrapper for _memory_prune_orphan_rels_db_sync."""
    return _memory_prune_orphan_rels_db_sync()


# ── Test Mode ────────────────────────────────────────────────────────────────

def _is_test_mode() -> bool:
    try:
        return str(
            state.get("input_boolean.ai_test_mode") or "off"  # noqa: F821
        ).lower() == "on"
    except NameError:
        return False


@service(supports_response="only")  # noqa: F821
async def memory_set(
    key: str,
    value: str,
    scope: str = "user",
    expiration_days: int = 180,
    tags: str = "",
    force_new: bool = False,
    owner: str = "",
):
    """
    yaml
    name: Memory Set
    description: Create or update a memory entry with optional expiration and tags. When creating a brand-new key, tag overlaps trigger a duplicate_tags error; successful responses include key_exists to clarify whether the entry was updated or newly inserted.
    fields:
      key:
        name: Key
        description: Unique key of the entry.
        required: true
        example: "car_parking_slot"
        selector:
          text:
      value:
        name: Value
        description: Value to store (string or JSON-encoded structure).
        required: true
        example: "Column B2E9"
        selector:
          text:
      scope:
        name: Scope
        description: >-
          Grouping label. "user" = private (QS-5 owner isolation),
          "household" = shared, "session" = temporary,
          "couple" = shared between both partners (visible to both).
        default: user
        example: user
        selector:
          select:
            options:
              - user
              - household
              - session
              - couple
      expiration_days:
        name: Expiration (days)
        description: Days until expiration; 0 keeps forever.
        default: 180
        example: 30
        selector:
          number:
            min: 0
            max: 3650
            mode: box
      tags:
        name: Tags
        description: Optional space-separated tags for improved search.
        example: "car parking slot"
        selector:
          text:
      force_new:
        name: Force New
        description: Proceed even when tags overlap with other entries.
        example: false
        selector:
          boolean:
      owner:
        name: Owner
        description: >-
          Person slug who owns this memory (QS-5 isolation).
          Auto-resolved from identity confidence when empty.
        default: ""
        example: "your_name"
        selector:
          text:
    """
    # Returns: {status, op, key, value?, scope?, tags?, expires_at?, key_exists?, force_new_applied?, duplicate_matches?, error?, matches?, owner?}  # noqa: E501
    if _is_test_mode():
        log.info("memory [TEST]: would set key=%s", key)  # noqa: F821
        return {"status": "test_mode_skip"}

    key_norm = _normalize_key(key)
    if not key_norm or value is None:
        _set_result(
            "error",
            op="set",
            key=key_norm or "",
            error="key_or_value_missing",
        )
        log.error("memory_set: missing key or value")  # noqa: F821
        return {
            "status": "error",
            "op": "set",
            "key": key_norm or "",
            "error": "key_or_value_missing",
        }

    try:
        expiration_days_i = int(expiration_days)
    except (TypeError, ValueError):
        expiration_days_i = 0
    if expiration_days_i < 0:
        expiration_days_i = 0
    if expiration_days_i > EXPIRATION_MAX_DAYS:
        expiration_days_i = EXPIRATION_MAX_DAYS

    if isinstance(force_new, str):
        force_new_bool = force_new.strip().lower() in {"1", "true", "yes", "y", "on"}
    else:
        force_new_bool = bool(force_new)
    forced_duplicate_override = False

    try:
        scope_norm = ("" if scope is None else str(scope).strip()).lower() or "user"

        # ── QS-5: resolve owner with dual-mode safety ──
        owner_slug, certain = resolve_memory_owner_with_confidence(owner, scope_norm)
        if not certain and scope_norm == "user":
            return {
                "status": "identity_uncertain",
                "op": "set",
                "key": _normalize_key(key),
                "candidates": list(get_person_slugs()),
                "message": "Cannot determine who is speaking. "
                "Please confirm your identity.",
            }
        owner_norm = owner_slug

        value_norm = _normalize_value(value)
        tags_raw = _normalize_value(tags) if tags else _normalize_value(key)
        tags_search = _normalize_tags(tags_raw)

        now = datetime.now(UTC)
        now_iso = now.isoformat()
        expires_at = (
            (now + timedelta(days=expiration_days_i)).isoformat()
            if expiration_days_i
            else None
        )

        key_exists = await _memory_key_exists_db(key_norm)

        duplicate_matches: list[tuple[dict[str, Any], float]] = []
        if not key_exists and tags_search:
            duplicate_matches = await _search_tag_candidates(
                tags_search,
                exclude_keys={key_norm},
                limit=CANDIDATE_CHECK_LIMIT,
                log_context="set: duplicate lookup",
            )

        duplicate_options: list[dict[str, Any]] = []
        if duplicate_matches:
            duplicate_options = [
                _condense_candidate_for_selection(match, score=score)
                for match, score in duplicate_matches
                if score >= DUPLICATE_MIN_SCORE
            ]

        if duplicate_options and not key_exists:
            if not force_new_bool:
                _set_result(
                    "error",
                    op="set",
                    key=key_norm,
                    tags=tags_raw,
                    error="duplicate_tags",
                    matches=duplicate_options,
                )
                log.error("memory_set: duplicate tags detected, refusing to overwrite")  # noqa: F821
                return {
                    "status": "error",
                    "op": "set",
                    "key": key_norm,
                    "tags": tags_raw,
                    "error": "duplicate_tags",
                    "matches": duplicate_options,
                }
            forced_duplicate_override = True
            log.warning("memory_set: duplicate tags override forced by force_new")  # noqa: F821

        ok_db = await _memory_set_db(
            key_norm=key_norm,
            value_norm=value_norm,
            scope_norm=scope_norm,
            tags_raw=tags_raw,
            tags_search=tags_search,
            now_iso=now_iso,
            expires_at=expires_at,
            owner_norm=owner_norm,
        )

        if not ok_db:
            return {
                "status": "error",
                "op": "set",
                "key": key_norm,
                "error": "memory_set_db returned False",
            }

        # Auto-link: persist relationships from tag overlap
        if tags_search:
            try:
                await _memory_auto_link(
                    source_key=key_norm,
                    tags_search=tags_search,
                    exclude_keys={key_norm},
                )
            except Exception as link_err:
                log.warning(f"memory_set auto_link failed (non-fatal): {link_err}")  # noqa: F821

        result_details: dict[str, Any] = {
            "value": value_norm,
            "scope": scope_norm,
            "tags": tags_raw,
            "expires_at": expires_at,
            "key_exists": key_exists,
            "force_new_applied": forced_duplicate_override,
            "owner": owner_norm,
        }
        if forced_duplicate_override:
            result_details["duplicate_matches"] = duplicate_options

        _set_result("ok", op="set", key=key_norm, **result_details)

        response: dict[str, Any] = {
            "status": "ok",
            "op": "set",
            "key": key_norm,
            "value": value_norm,
            "scope": scope_norm,
            "tags": tags_raw,
            "expires_at": expires_at,
            "key_exists": key_exists,
            "force_new_applied": forced_duplicate_override,
            "owner": owner_norm,
        }
        if forced_duplicate_override:
            response["duplicate_matches"] = duplicate_options
        return response
    except Exception as e:
        log.error(f"memory_set failed: {e}")  # noqa: F821
        _set_result("error", op="set", key=key_norm, error=str(e))
        return {"status": "error", "op": "set", "key": key_norm, "error": str(e)}


@service(supports_response="only")  # noqa: F821
async def memory_get(key: str, owner: str = ""):
    """
    yaml
    name: Memory Get
    description: Get a memory entry by key, updating last_used_at; returns `ambiguous` when similar suggestions exist and `status=expired` with the stored payload so callers can reuse it when the record has expired. Returns `restricted` if the entry belongs to another user.
    fields:
      key:
        name: Key
        description: Key to fetch.
        required: true
        example: "car_parking_slot"
        selector:
          text:
      owner:
        name: Owner
        description: >-
          Requesting user slug (QS-5). Auto-resolved when empty.
        default: ""
        selector:
          text:
    """
    # Returns: {status, op, key, value?, scope?, tags?, created_at?, last_used_at?, expires_at?, owner?, error?, expired?, matches?, restricted?}  # noqa: E501
    if _is_test_mode():
        log.info("memory [TEST]: would get key=%s", key)  # noqa: F821
        return {"status": "test_mode_skip", "op": "get", "value": "{}"}

    key_norm = _normalize_key(key)
    if not key_norm:
        _set_result("error", op="get", key=key or "", error="key_missing")
        return {
            "status": "error",
            "op": "get",
            "key": key or "",
            "error": "key_missing",
        }

    try:
        status, payload = await _memory_get_db(key_norm)
    except Exception as e:
        log.error(f"memory_get failed: {e}")  # noqa: F821
        _set_result("error", op="get", key=key_norm, error=str(e))
        return {"status": "error", "op": "get", "key": key_norm, "error": str(e)}

    if status == "expired":
        payload = payload or {"key": key_norm}
        attrs: dict[str, Any] = {**payload, "expired": True}
        if "error" not in attrs:
            attrs["error"] = "expired"
        _set_result("expired", op="get", **attrs)
        return {"status": "expired", "op": "get", **attrs}

    if status == "not_found":
        matches = await _find_tag_matches_for_query(
            key or key_norm, exclude_keys={key_norm}
        )
        error_code = "ambiguous" if matches else "not_found"
        _set_result(
            "error",
            op="get",
            key=key_norm,
            error=error_code,
            matches=matches,
        )
        return {
            "status": "error",
            "op": "get",
            "key": key_norm,
            "error": error_code,
            "matches": matches,
        }

    res = payload or {}

    # ── QS-5: Tier B access check ──
    row_owner = res.get("owner", "")
    row_scope = res.get("scope", "")
    requesting_user = resolve_memory_owner(owner, row_scope)
    access = _check_access(row_owner, row_scope, requesting_user)
    if access == "restricted":
        restricted_res = {
            "status": "restricted",
            "op": "get",
            "key": res.get("key", key_norm),
            "scope": row_scope,
            "tags": res.get("tags", ""),
            "owner": row_owner,
            "restricted": True,
        }
        _set_result("restricted", op="get", **restricted_res)
        return restricted_res

    _set_result("ok", op="get", **res)
    return {"status": "ok", "op": "get", **res}


@service(supports_response="only")  # noqa: F821
async def memory_search(
    query: str, limit: int = 5, include_related: bool = True, owner: str = ""
):
    """
    yaml
    name: Memory Search
    description: Search entries across key/value/tags using FTS; falls back to LIKE if MATCH fails. Optionally appends graph-connected related entries. Other-user entries are returned with value redacted (Tier B).
    fields:
      query:
        name: Query
        description: FTS search query.
        required: true
        example: "parking slot"
        selector:
          text:
      limit:
        name: Limit
        description: Maximum number of results to return.
        default: 5
        example: 5
        selector:
          number:
            min: 1
            max: 50
      include_related:
        name: Include Related
        description: Append graph-connected entries to search results (search-time enrichment).
        default: true
        selector:
          boolean:
      owner:
        name: Owner
        description: >-
          Requesting user slug (QS-5). Auto-resolved when empty.
        default: ""
        selector:
          text:
    """
    # Returns: {status, op, query, count?, related_count?, results?, blended?, error?}
    if _is_test_mode():
        log.info("memory [TEST]: would search query=%s", query)  # noqa: F821
        return {"status": "test_mode_skip"}

    if not query:
        _set_result("error", op="search", query=query or "", error="query_missing")
        return {
            "status": "error",
            "op": "search",
            "query": query or "",
            "error": "query_missing",
        }

    try:
        lim = int(limit)
    except (TypeError, ValueError):
        lim = 5
    if lim < 1:
        lim = 1
    if lim > SEARCH_LIMIT_MAX:
        lim = SEARCH_LIMIT_MAX

    # Generate query embedding for blended search if vec0 is available
    query_vec = None
    if _VEC_AVAILABLE:
        try:
            raw_w = state.get("input_number.ai_semantic_blend_weight")  # noqa: F821
            blend_w = int(float(raw_w)) if raw_w not in (None, "unknown", "unavailable") else 50
        except (TypeError, ValueError):
            blend_w = 50
        if blend_w > 0:
            try:
                embed_result = await _call_llm_direct_embed(query)
                if isinstance(embed_result, dict) and embed_result.get("status") == "ok":
                    query_vec = embed_result["embedding"]
            except Exception:
                pass  # Non-blocking: fall back to FTS5-only

    try:
        results = await _memory_search_db(query, lim, query_vec=query_vec)
    except Exception as e:
        log.error(f"memory_search failed: {e}")  # noqa: F821
        _set_result("error", op="search", query=query, error=str(e))
        return {"status": "error", "op": "search", "query": query, "error": str(e)}

    # ── Search-time enrichment: append depth-1 related entries ────────────
    related_entries: list[dict[str, Any]] = []
    if include_related and results:
        try:
            enrich_enabled = True
            try:
                raw_en = state.get("input_boolean.ai_memory_search_enrich")  # noqa: F821
                enrich_enabled = str(raw_en).lower() not in ("off", "false", "0")
            except (NameError, AttributeError):
                pass

            if enrich_enabled:
                try:
                    raw_max = state.get("input_number.ai_memory_search_enrich_max")  # noqa: F821
                    max_related = int(float(raw_max)) if raw_max not in (None, "unknown", "unavailable") else SEARCH_ENRICH_MAX_RELATED
                except (TypeError, ValueError, NameError):
                    max_related = SEARCH_ENRICH_MAX_RELATED
                max_related = max(0, min(max_related, 10))

                try:
                    raw_mw = state.get("input_number.ai_memory_search_enrich_min_weight")  # noqa: F821
                    enrich_min_weight = float(raw_mw) if raw_mw not in (None, "unknown", "unavailable") else SEARCH_ENRICH_MIN_WEIGHT
                except (TypeError, ValueError, NameError):
                    enrich_min_weight = SEARCH_ENRICH_MIN_WEIGHT

                if max_related > 0:
                    top_n = min(SEARCH_ENRICH_TOP_N, len(results))
                    source_keys = [r["key"] for r in results[:top_n]]
                    seen_keys = {r["key"] for r in results}

                    related_entries = await _memory_search_enrich_db(
                        source_keys=source_keys,
                        exclude_keys=seen_keys,
                        max_results=max_related,
                        min_weight=enrich_min_weight,
                    )
        except Exception as enrich_err:
            log.warning(f"memory_search enrichment failed (non-fatal): {enrich_err}")  # noqa: F821

    # Combine for response
    all_results = results + related_entries

    # ── QS-5: Tier B post-filter ──
    requesting_user = resolve_memory_owner(owner, "user")
    filtered: list[dict[str, Any]] = []
    for r in all_results:
        row_owner = r.get("owner", "")
        row_scope = r.get("scope", "")
        access = _check_access(row_owner, row_scope, requesting_user)
        if access == "restricted":
            filtered.append({
                "key": r.get("key", ""),
                "value": "[restricted]",
                "scope": row_scope,
                "tags": r.get("tags", ""),
                "owner": row_owner,
                "restricted": True,
                "match_score": r.get("match_score", 0),
            })
        else:
            filtered.append(r)

    # Sensor attrs get only summary (full results in service response).
    # This avoids the 16 KB recorder limit and 32 KB event-size cap.
    _set_result(
        "ok",
        op="search",
        query=query,
        count=len(results),
        related_count=len(related_entries),
        result_keys=[r.get("key", "") for r in filtered],
    )
    return {
        "status": "ok",
        "op": "search",
        "query": query,
        "count": len(results),
        "related_count": len(related_entries),
        "results": filtered,
        "blended": query_vec is not None,
    }


@service(supports_response="only")  # noqa: F821
async def memory_forget(key: str, owner: str = ""):
    """
    yaml
    name: Memory Forget
    description: Delete a memory entry by key and remove it from the FTS index; returns `ambiguous` when nothing is removed but suggestions exist. Refuses to delete entries owned by another user.
    fields:
      key:
        name: Key
        description: Key to delete.
        required: true
        example: "car_parking_slot"
        selector:
          text:
      owner:
        name: Owner
        description: >-
          Requesting user slug (QS-5). Auto-resolved when empty.
        default: ""
        selector:
          text:
    """
    # Returns: {status, op, key, deleted?, error?, matches?}
    if _is_test_mode():
        log.info("memory [TEST]: would forget key=%s", key)  # noqa: F821
        return {"status": "test_mode_skip"}

    key_norm = _normalize_key(key)
    if not key_norm:
        _set_result("error", op="forget", key=key or "", error="key_missing")
        return {
            "status": "error",
            "op": "forget",
            "key": key or "",
            "error": "key_missing",
        }

    # ── QS-5: ownership check before delete ──
    try:
        _, existing = await _memory_get_db(key_norm)
    except Exception:
        existing = None
    if existing:
        row_owner = existing.get("owner", "")
        row_scope = existing.get("scope", "")
        requesting_user = resolve_memory_owner(owner, row_scope)
        if row_owner and row_owner != requesting_user:
            _set_result(
                "error", op="forget", key=key_norm, error="not_owner"
            )
            return {
                "status": "error",
                "op": "forget",
                "key": key_norm,
                "error": "not_owner",
                "owner": row_owner,
            }

    try:
        deleted = await _memory_forget_db(key_norm)
    except Exception as e:
        log.error(f"memory_forget failed: {e}")  # noqa: F821
        _set_result("error", op="forget", key=key_norm, error=str(e))
        return {"status": "error", "op": "forget", "key": key_norm, "error": str(e)}

    if deleted == 0:
        matches = await _find_tag_matches_for_query(
            key or key_norm, exclude_keys={key_norm}
        )
        error_code = "ambiguous" if matches else "not_found"
        _set_result(
            "error",
            op="forget",
            key=key_norm,
            error=error_code,
            matches=matches,
        )
        return {
            "status": "error",
            "op": "forget",
            "key": key_norm,
            "error": error_code,
            "matches": matches,
        }

    _set_result("ok", op="forget", key=key_norm, deleted=deleted)
    return {"status": "ok", "op": "forget", "key": key_norm, "deleted": deleted}


@service(supports_response="only")  # noqa: F821
async def memory_related(key: str, limit: int = 10, depth: int = 1, owner: str = ""):
    """
    yaml
    name: Memory Related
    description: Get memories related to a given key via the relationship graph. Other-user entries are returned with value redacted (Tier B).
    fields:
      key:
        name: Key
        description: Key to find relationships for.
        required: true
        selector:
          text:
      limit:
        name: Limit
        description: Maximum related memories to return.
        default: 10
        selector:
          number:
            min: 1
            max: 50
      depth:
        name: Depth
        description: Traversal depth (1=direct, 2=friends-of-friends, 3=max).
        default: 1
        selector:
          number:
            min: 1
            max: 3
      owner:
        name: Owner
        description: >-
          Requesting user slug (QS-5). Auto-resolved when empty.
        default: ""
        selector:
          text:
    """
    if _is_test_mode():
        log.info("memory [TEST]: would get related for key=%s", key)  # noqa: F821
        return {"status": "test_mode_skip"}

    key_norm = _normalize_key(key)
    if not key_norm:
        _set_result("error", op="related", key=key or "", error="key_missing")
        return {
            "status": "error",
            "op": "related",
            "key": key or "",
            "error": "key_missing",
        }

    lim = max(1, min(int(limit or 10), SEARCH_LIMIT_MAX))
    dep = max(1, min(int(depth or 1), 3))

    try:
        results = await _memory_related_db(key_norm, lim, dep)

        # ── QS-5: Tier B post-filter ──
        requesting_user = resolve_memory_owner(owner, "user")
        filtered: list[dict[str, Any]] = []
        for r in results:
            row_owner = r.get("owner", "")
            row_scope = r.get("scope", "")
            access = _check_access(row_owner, row_scope, requesting_user)
            if access == "restricted":
                filtered.append({
                    "key": r.get("key", ""),
                    "value": "[restricted]",
                    "scope": row_scope,
                    "tags": r.get("tags", ""),
                    "owner": row_owner,
                    "restricted": True,
                    "rel_type": r.get("rel_type", ""),
                    "weight": r.get("weight", 0),
                    "depth": r.get("depth", 1),
                })
            else:
                filtered.append(r)

        _set_result(
            "ok",
            op="related",
            key=key_norm,
            count=len(filtered),
            result_keys=[r.get("key", "") for r in filtered],
        )
        return {
            "status": "ok",
            "op": "related",
            "key": key_norm,
            "count": len(filtered),
            "results": filtered,
        }
    except Exception as e:
        log.error(f"memory_related failed: {e}")  # noqa: F821
        _set_result("error", op="related", key=key_norm, error=str(e))
        return {"status": "error", "op": "related", "key": key_norm, "error": str(e)}


@service(supports_response="only")  # noqa: F821
async def memory_semantic_autolink(batch_size: int = 50, threshold: float = 0.7):
    """
    yaml
    name: Memory Semantic Autolink
    description: >-
      Create content_match relationships between semantically similar memories
      via vec0 KNN. Processes embeddings that have no content_match edges yet.
    fields:
      batch_size:
        name: Batch Size
        description: Max keys to process per run.
        default: 50
        selector:
          number:
            min: 10
            max: 200
            mode: box
      threshold:
        name: Similarity Threshold
        description: Minimum cosine similarity for content_match edges (0.0-1.0).
        default: 0.7
        selector:
          number:
            min: 0.5
            max: 1.0
            step: 0.05
            mode: slider
    """
    if _is_test_mode():
        log.info("memory [TEST]: would run semantic autolink")  # noqa: F821
        return {"status": "test_mode_skip"}

    if not _VEC_AVAILABLE:
        return {"status": "error", "op": "semantic_autolink", "error": "vec0_not_available"}

    # Read config from helpers with fallback to params
    try:
        raw_th = state.get("input_number.ai_memory_semantic_autolink_threshold")  # noqa: F821
        th = float(raw_th) if raw_th not in (None, "unknown", "unavailable") else threshold
    except (TypeError, ValueError, NameError):
        th = threshold
    th = max(0.5, min(th, 1.0))

    try:
        raw_bs = state.get("input_number.ai_memory_semantic_autolink_batch")  # noqa: F821
        bs = int(float(raw_bs)) if raw_bs not in (None, "unknown", "unavailable") else batch_size
    except (TypeError, ValueError, NameError):
        bs = batch_size
    bs = max(10, min(bs, 200))

    try:
        result = await _memory_semantic_autolink_db(batch_limit=bs, threshold=th)
        linked = result.get("linked", 0)
        keys_processed = result.get("keys_processed", 0)
        if linked:
            log.info(  # noqa: F821
                "memory_semantic_autolink: linked=%d from %d keys (threshold=%.2f)",
                linked, keys_processed, th,
            )
        _set_result(
            "ok",
            op="semantic_autolink",
            linked=linked,
            keys_processed=keys_processed,
        )
        return {
            "status": "ok",
            "op": "semantic_autolink",
            "linked": linked,
            "keys_processed": keys_processed,
        }
    except Exception as e:
        log.error(f"memory_semantic_autolink failed: {e}")  # noqa: F821
        _set_result("error", op="semantic_autolink", error=str(e))
        return {"status": "error", "op": "semantic_autolink", "error": str(e)}


@service(supports_response="only")  # noqa: F821
async def memory_link(from_key: str, to_key: str, rel_type: str = "manual"):
    """
    yaml
    name: Memory Link
    description: Manually link two memories with a specified relationship type.
    fields:
      from_key:
        name: From Key
        description: Source memory key.
        required: true
        selector:
          text:
      to_key:
        name: To Key
        description: Target memory key.
        required: true
        selector:
          text:
      rel_type:
        name: Relationship Type
        description: Type of relationship.
        default: manual
        selector:
          select:
            options:
              - manual
              - tag_overlap
              - content_match
    """
    if _is_test_mode():
        log.info("memory [TEST]: would link %s → %s", from_key, to_key)  # noqa: F821
        return {"status": "test_mode_skip"}

    from_norm = _normalize_key(from_key)
    to_norm = _normalize_key(to_key)
    if not from_norm or not to_norm:
        _set_result("error", op="link", error="key_missing")
        return {"status": "error", "op": "link", "error": "key_missing"}

    if from_norm == to_norm:
        _set_result("error", op="link", error="self_link")
        return {"status": "error", "op": "link", "error": "self_link"}

    rel_type_norm = str(rel_type or "manual").strip().lower()
    if rel_type_norm not in {"manual", "tag_overlap", "content_match"}:
        rel_type_norm = "manual"

    try:
        from_exists = await _memory_key_exists_db(from_norm)
        if not from_exists:
            _set_result(
                "error", op="link", from_key=from_norm, error="from_key_not_found"
            )
            return {
                "status": "error",
                "op": "link",
                "from_key": from_norm,
                "error": "from_key_not_found",
            }

        to_exists = await _memory_key_exists_db(to_norm)
        if not to_exists:
            _set_result(
                "error", op="link", to_key=to_norm, error="to_key_not_found"
            )
            return {
                "status": "error",
                "op": "link",
                "to_key": to_norm,
                "error": "to_key_not_found",
            }

        ok = await _memory_link_db(from_norm, to_norm, rel_type_norm, _utcnow_iso())
        if not ok:
            _set_result(
                "error",
                op="link",
                from_key=from_norm,
                to_key=to_norm,
                error="link_failed",
            )
            return {
                "status": "error",
                "op": "link",
                "from_key": from_norm,
                "to_key": to_norm,
                "error": "link_failed",
            }

        _set_result(
            "ok", op="link", from_key=from_norm, to_key=to_norm, rel_type=rel_type_norm
        )
        return {
            "status": "ok",
            "op": "link",
            "from_key": from_norm,
            "to_key": to_norm,
            "rel_type": rel_type_norm,
        }
    except Exception as e:
        log.error(f"memory_link failed: {e}")  # noqa: F821
        _set_result("error", op="link", error=str(e))
        return {"status": "error", "op": "link", "error": str(e)}


@service(supports_response="only")  # noqa: F821
async def memory_purge_expired(grace_days: int | None = None):
    """
    yaml
    name: Memory Purge Expired
    description: Remove expired rows older than the provided grace period; manual calls default to 0 days while daily housekeeping uses HOUSEKEEPING_GRACE_DAYS.
    fields:
      grace_days:
        name: Grace Days
        description: Extra days to keep expired entries before deletion (clamped to HOUSEKEEPING_GRACE_MAX_DAYS).
        default: 0
        example: 10
        selector:
          number:
            min: 0
            max: 365
    """
    if _is_test_mode():
        log.info("memory [TEST]: would purge expired entries")  # noqa: F821
        return {"status": "test_mode_skip"}

    if grace_days is None:
        grace = 0
    else:
        try:
            grace = int(grace_days)
        except (TypeError, ValueError):
            grace = 0
    if grace < 0:
        grace = 0
    if grace > HOUSEKEEPING_GRACE_MAX_DAYS:
        grace = HOUSEKEEPING_GRACE_MAX_DAYS

    try:
        removed = await _memory_purge_expired_db(grace)
    except Exception as e:
        log.error(f"memory_purge_expired failed: {e}")  # noqa: F821
        _set_result("error", op="purge_expired", grace_days=grace, error=str(e))
        return {
            "status": "error",
            "op": "purge_expired",
            "grace_days": grace,
            "error": str(e),
        }

    _set_result("ok", op="purge_expired", grace_days=grace, removed=removed)
    return {
        "status": "ok",
        "op": "purge_expired",
        "grace_days": grace,
        "removed": removed,
    }


@service(supports_response="only")  # noqa: F821
async def memory_reindex_fts():
    """
    yaml
    name: Memory Reindex FTS
    description: Rebuild the FTS index from the main table. Useful when mem_fts is empty or out of sync.
    """
    if _is_test_mode():
        log.info("memory [TEST]: would reindex FTS")  # noqa: F821
        return {"status": "test_mode_skip"}

    try:
        before, after = await _memory_reindex_fts_db()
    except Exception as e:
        log.error(f"memory_reindex_fts failed: {e}")  # noqa: F821
        _set_result("error", op="reindex_fts", error=str(e))
        return {"status": "error", "op": "reindex_fts", "error": str(e)}

    _set_result("ok", op="reindex_fts", removed=before, inserted=after)
    return {
        "status": "ok",
        "op": "reindex_fts",
        "removed": before,
        "inserted": after,
    }


@time_trigger("startup")  # noqa: F821
@service(supports_response="only")  # noqa: F821
async def memory_health_check():
    """
    yaml
    name: Memory Health Check
    description: >-
      Run a health check (counts, expired, FTS rows, DB size), compare against
      thresholds, and fire ai_memory_threshold_exceeded event if limits are breached.
      Update sensor.memory_result with all metrics.
    """
    if _is_test_mode():
        log.info("memory [TEST]: would run health check")  # noqa: F821
        return {"status": "test_mode_skip"}

    _ensure_result_entity_name(force=True)
    # ── Initialize sqlite-vec flag (must run outside @pyscript_compile) ──
    global _VEC_AVAILABLE, _VEC_DIMENSIONS
    try:
        dim_val = state.get("input_number.ai_embedding_dimensions")  # noqa: F821
        _VEC_DIMENSIONS = int(float(dim_val)) if dim_val not in (None, "unknown", "unavailable") else 512
    except (TypeError, ValueError):
        _VEC_DIMENSIONS = 512
    vec_ok = _check_vec0_sync()
    _VEC_AVAILABLE = vec_ok
    if vec_ok:
        log.info("memory.py: sqlite-vec loaded (dimensions=%d)", _VEC_DIMENSIONS)  # noqa: F821
    else:
        log.warning("memory.py: sqlite-vec not available (vec0.so missing or failed to load)")  # noqa: F821
        # ── T24-2c: Persistent notification on vec0 failure ──
        try:
            service.call(  # noqa: F821
                "persistent_notification", "create",
                title="AI Memory: sqlite-vec unavailable",
                message=(
                    "vec0.so failed to load — semantic search is degraded to text-only. "
                    "Run the sqlite_vec_recompile blueprint or check /share/vec0."
                ),
                notification_id="ai_vec0_failure",
            )
        except Exception:
            pass
    try:
        rows, expired, fts_rows, rel_count, db_size_bytes, archived_count = await _memory_health_check_db()
        db_size_mb = round(db_size_bytes / (1024 * 1024), 2)
        ts = _utcnow_iso()

        # ── Read threshold helpers (fallback to safe defaults) ──
        try:
            rl_val = state.get("input_number.ai_memory_record_limit")  # noqa: F821
            record_limit = int(float(rl_val)) if rl_val not in (None, "unknown", "unavailable", "0") else 5000
        except (TypeError, ValueError):
            record_limit = 5000
        try:
            db_val = state.get("input_number.ai_memory_db_max_mb")  # noqa: F821
            db_max_mb = int(float(db_val)) if db_val not in (None, "unknown", "unavailable", "0") else 100
        except (TypeError, ValueError):
            db_max_mb = 100

        # ── Read archive toggle (I-42 Phase 2) ──
        try:
            archive_val = state.get("input_boolean.ai_memory_auto_archive")  # noqa: F821
            archive_enabled = archive_val == "on"
        except (TypeError, AttributeError):
            archive_enabled = True

        # ── Threshold comparison ──
        breached = []
        if rows >= record_limit:
            breached.append({"metric": "record_count", "current": rows, "limit": record_limit})
        if db_size_mb >= db_max_mb:
            breached.append({"metric": "db_size_mb", "current": db_size_mb, "limit": db_max_mb})
        threshold_exceeded = len(breached) > 0

        if threshold_exceeded:
            log.warning(  # noqa: F821
                "memory.py: threshold exceeded — %s",
                ", ".join([f"{b['metric']}: {b['current']}/{b['limit']}" for b in breached]),
            )
            event.fire(  # noqa: F821
                "ai_memory_threshold_exceeded",
                metrics=breached,
                rows=rows,
                expired=expired,
                db_size_mb=db_size_mb,
                record_limit=record_limit,
                db_max_mb=db_max_mb,
            )

        _set_result(
            "idle",
            op="health",
            db_path=DB_PATH,
            rows=rows,
            expired=expired,
            fts_rows=fts_rows,
            rel_count=rel_count,
            db_size_mb=db_size_mb,
            record_limit=record_limit,
            db_max_mb=db_max_mb,
            threshold_exceeded=threshold_exceeded,
            archived_count=archived_count,
            archive_enabled=archive_enabled,
            ts=ts,
        )
        # ── Scope options validation (Task 22) ──
        # Warn if discovered persons don't match YAML docstring scope options.
        # Reads entity_config.yaml via executor (avoids blocking event loop).
        try:
            _discovered = set()
            # Source 1: person.* entities
            for _eid in state.names("person"):  # noqa: F821
                _discovered.add(_eid.split(".", 1)[1])
            # Source 2: entity_config.yaml persons overlay
            _ec_raw = _read_entity_config_sync("/config/pyscript/entity_config.yaml")
            if _ec_raw:
                import yaml as _yaml
                _ec = _yaml.safe_load(_ec_raw) or {}
                for _name in (_ec.get("persons") or {}):
                    _discovered.add(_name)
            # Person validation — entity selectors are now dynamic (no static options to check)
        except Exception:
            pass

        log.info(  # noqa: F821
            "memory.py health: rows=%d, expired=%d, fts=%d, rels=%d, db=%.2fMB, archived=%d, threshold_exceeded=%s",
            rows, expired, fts_rows, rel_count, db_size_mb, archived_count, threshold_exceeded,
        )
        return {
            "status": "ok",
            "op": "health",
            "db_path": DB_PATH,
            "rows": rows,
            "expired": expired,
            "fts_rows": fts_rows,
            "rel_count": rel_count,
            "db_size_mb": db_size_mb,
            "record_limit": record_limit,
            "db_max_mb": db_max_mb,
            "threshold_exceeded": threshold_exceeded,
            "archived_count": archived_count,
            "archive_enabled": archive_enabled,
            "ts": ts,
        }
    except Exception as e:
        log.error(f"memory_health_check failed: {e}")  # noqa: F821
        _set_result("error", op="health", error=str(e))
        return {"status": "error", "op": "health", "error": str(e)}


@time_trigger("cron(0 3 * * *)")  # noqa: F821
async def memory_daily_housekeeping():
    """Daily housekeeping: purge expired entries, prune orphan relationships, and tidy the FTS index."""
    try:
        await memory_purge_expired(grace_days=HOUSEKEEPING_GRACE_DAYS)
    except Exception as e:
        log.error(f"memory_daily_housekeeping purge failed: {e}")  # noqa: F821
    try:
        pruned = await _memory_prune_orphan_rels_db()
        if pruned:
            log.info(f"memory_daily_housekeeping: pruned {pruned} orphan relationships")  # noqa: F821
    except Exception as e:
        log.error(f"memory_daily_housekeeping orphan pruning failed: {e}")  # noqa: F821


# ── Degradation Recovery Probe ───────────────────────────────────────────────


@pyscript_executor  # noqa: F821
def _db_recovery_probe_sync() -> bool:
    """Attempt a test write to memory.db. Returns True on success."""
    import sqlite3 as _sqlite3
    from datetime import datetime as _dt, timezone as _tz

    try:
        now_iso = _dt.now(_tz.utc).isoformat()
        conn = _sqlite3.connect(DB_PATH, timeout=5)
        conn.execute("PRAGMA busy_timeout=3000;")
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute(
            """INSERT OR REPLACE INTO mem(
                key, value, scope, tags, tags_search, created_at, last_used_at, owner
            ) VALUES ('_health:db_probe', '1', 'system', 'system probe',
                      'system probe', ?, ?, 'system')""",
            (now_iso, now_iso),
        )
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False


@time_trigger("cron(*/5 * * * *)")  # noqa: F821
async def _memory_recovery_probe():
    """When in read_only mode, attempt a test write every 5 min to promote back."""
    if _db_mode != "read_only":
        return
    ok = await _db_recovery_probe_sync()
    if ok:
        transition = _track_write_success()
        if transition:
            log.info("memory: recovery probe succeeded — promoted back to normal")  # noqa: F821
            event.fire("ai_memory_mode_changed", old_mode="read_only", new_mode="normal")  # noqa: F821
    else:
        log.debug("memory: recovery probe failed — staying in read_only mode")  # noqa: F821


# ── Memory Auto-Archive (I-42 Phase 2) ───────────────────────────────────────


@pyscript_executor  # noqa: F821
def _memory_archive_db_sync(
    target_count: int,
    protection_tags: list[str],
    recency_days: int,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Move the coldest unprotected entries from mem to mem_archive.

    Returns {archived, before_count, after_count, target_count, protected_skipped, dry_run}.
    """
    for attempt in range(2):
        try:
            _ensure_db_once(force=attempt == 1)
            with closing(_get_db_connection()) as conn:
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) FROM mem")
                before_count = cur.fetchone()[0]
                if before_count <= target_count:
                    return {
                        "archived": 0,
                        "before_count": before_count,
                        "after_count": before_count,
                        "target_count": target_count,
                        "protected_skipped": 0,
                        "dry_run": dry_run,
                    }

                to_remove = before_count - target_count
                recency_cutoff = (
                    datetime.now(UTC) - timedelta(days=max(int(recency_days), 0))
                ).isoformat()

                # Build tag protection clause
                tag_clauses = []
                tag_params: list[Any] = []
                for tag in protection_tags:
                    tag_clauses.append("tags_search LIKE ?")
                    tag_params.append(f"%{tag}%")

                protection_sql = ""
                if tag_clauses:
                    protection_sql = " AND NOT (" + " OR ".join(tag_clauses) + ")"

                # Count protected entries (for reporting)
                prot_sql = (
                    "SELECT COUNT(*) FROM mem WHERE "
                    "(last_used_at >= ?)"  # recently accessed
                    " OR (expires_at IS NULL AND scope = 'user')"  # permanent user
                )
                prot_params: list[Any] = [recency_cutoff]
                if tag_clauses:
                    prot_sql += " OR (" + " OR ".join(tag_clauses) + ")"
                    prot_params.extend(tag_params)
                cur.execute(prot_sql, prot_params)
                protected_skipped = cur.fetchone()[0]

                # Select candidates: coldest unprotected entries
                cand_sql = (
                    "SELECT id, key, value, scope, tags, tags_search, "
                    "created_at, last_used_at, expires_at "
                    "FROM mem WHERE "
                    "last_used_at < ?"  # not recently accessed
                    " AND NOT (expires_at IS NULL AND scope = 'user')"  # not permanent user
                    + protection_sql
                    + " ORDER BY last_used_at ASC, created_at ASC LIMIT ?"
                )
                cand_params: list[Any] = [recency_cutoff] + tag_params + [to_remove]
                cur.execute(cand_sql, cand_params)
                candidates = cur.fetchall()

                if not candidates:
                    return {
                        "archived": 0,
                        "before_count": before_count,
                        "after_count": before_count,
                        "target_count": target_count,
                        "protected_skipped": protected_skipped,
                        "dry_run": dry_run,
                    }

                if dry_run:
                    return {
                        "archived": len(candidates),
                        "before_count": before_count,
                        "after_count": before_count - len(candidates),
                        "target_count": target_count,
                        "protected_skipped": protected_skipped,
                        "dry_run": True,
                    }

                # ── Transaction: insert into archive → delete from mem ──
                now_iso = _utcnow_iso()
                ids = []
                keys = []
                for row in candidates:
                    cur.execute(
                        """
                        INSERT OR IGNORE INTO mem_archive
                            (original_id, key, value, scope, tags, tags_search,
                             created_at, last_used_at, expires_at, archived_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (row[0], row[1], row[2], row[3], row[4], row[5],
                         row[6], row[7], row[8], now_iso),
                    )
                    ids.append(row[0])
                    keys.append(row[1])

                placeholders = ",".join("?" * len(ids))
                cur.execute(f"DELETE FROM mem WHERE id IN ({placeholders})", ids)
                # Clean vec entries (best-effort, vec0 may not be loaded)
                if keys:
                    try:
                        key_ph = ",".join("?" * len(keys))
                        cur.execute(f"DELETE FROM mem_vec WHERE key IN ({key_ph})", keys)
                    except sqlite3.OperationalError:
                        pass
                # Clean relationship entries
                if keys:
                    key_ph = ",".join("?" * len(keys))
                    cur.execute(
                        f"DELETE FROM mem_rel WHERE from_key IN ({key_ph}) OR to_key IN ({key_ph})",
                        keys + keys,
                    )
                conn.commit()

                cur.execute("SELECT COUNT(*) FROM mem")
                after_count = cur.fetchone()[0]
                return {
                    "archived": len(ids),
                    "before_count": before_count,
                    "after_count": after_count,
                    "target_count": target_count,
                    "protected_skipped": protected_skipped,
                    "dry_run": False,
                }
        except sqlite3.OperationalError:
            _reset_db_ready()
            if attempt == 0:
                time.sleep(0.1)
                continue
            raise
    return {"archived": 0, "before_count": 0, "after_count": 0, "target_count": target_count,
            "protected_skipped": 0, "dry_run": dry_run}


@service(supports_response="only")  # noqa: F821
async def memory_archive(dry_run: bool = False):
    """
    yaml
    name: Memory Archive
    description: >-
      Move the coldest unprotected L2 entries to mem_archive.
      Reads target_pct, recency_days, and protection_tags from helpers.
    fields:
      dry_run:
        name: Dry Run
        description: If true, report what would be archived without moving data.
        default: false
        selector:
          boolean:
    """
    if _is_test_mode():
        log.info("memory [TEST]: would run archive (dry_run=%s)", dry_run)  # noqa: F821
        return {"status": "test_mode_skip"}

    # ── Read helpers ──
    try:
        rl_val = state.get("input_number.ai_memory_record_limit")  # noqa: F821
        record_limit = int(float(rl_val)) if rl_val not in (None, "unknown", "unavailable", "0") else 5000
    except (TypeError, ValueError):
        record_limit = 5000
    try:
        tp_val = state.get("input_number.ai_memory_archive_target_pct")  # noqa: F821
        target_pct = int(float(tp_val)) if tp_val not in (None, "unknown", "unavailable") else 80
    except (TypeError, ValueError):
        target_pct = 80
    target_count = int(record_limit * target_pct / 100)

    try:
        rd_val = state.get("input_number.ai_memory_archive_recency_days")  # noqa: F821
        recency_days = int(float(rd_val)) if rd_val not in (None, "unknown", "unavailable") else 30
    except (TypeError, ValueError):
        recency_days = 30

    try:
        pt_val = state.get("input_text.ai_memory_archive_protection_tags")  # noqa: F821
        protection_tags = [t.strip() for t in (pt_val or "").split() if t.strip()]
    except (TypeError, AttributeError):
        protection_tags = ["important", "remember", "pinned", "permanent"]
    if not protection_tags:
        protection_tags = ["important", "remember", "pinned", "permanent"]

    try:
        result = _memory_archive_db_sync(target_count, protection_tags, recency_days, bool(dry_run))
        result["status"] = "ok"
        result["op"] = "archive"
        log.info(  # noqa: F821
            "memory_archive: archived=%d, before=%d, after=%d, target=%d, protected=%d, dry_run=%s",
            result["archived"], result["before_count"], result["after_count"],
            result["target_count"], result["protected_skipped"], result["dry_run"],
        )
        return result
    except Exception as e:
        log.error(f"memory_archive failed: {e}")  # noqa: F821
        return {"status": "error", "op": "archive", "error": str(e)}


@pyscript_executor  # noqa: F821
def _memory_archive_search_db_sync(
    query: str, limit: int = 20, scope: str = "all"
) -> list[dict[str, Any]]:
    """LIKE-based search on mem_archive (no FTS on cold storage)."""
    for attempt in range(2):
        try:
            _ensure_db_once(force=attempt == 1)
            with closing(_get_db_connection()) as conn:
                cur = conn.cursor()
                pattern = f"%{query}%"
                sql = (
                    "SELECT key, value, scope, tags, created_at, last_used_at, archived_at "
                    "FROM mem_archive WHERE (key LIKE ? OR value LIKE ? OR tags LIKE ?)"
                )
                params: list[Any] = [pattern, pattern, pattern]
                if scope != "all":
                    sql += " AND scope = ?"
                    params.append(scope)
                sql += " ORDER BY archived_at DESC LIMIT ?"
                params.append(min(max(int(limit), 1), 50))
                cur.execute(sql, params)
                results = []
                for row in cur.fetchall():
                    results.append({
                        "key": row[0],
                        "value": row[1],
                        "scope": row[2],
                        "tags": row[3],
                        "created_at": row[4],
                        "last_used_at": row[5],
                        "archived_at": row[6],
                    })
                return results
        except sqlite3.OperationalError:
            _reset_db_ready()
            if attempt == 0:
                time.sleep(0.1)
                continue
            raise
    return []


@service(supports_response="only")  # noqa: F821
async def memory_archive_search(query: str = "", limit: int = 20, scope: str = "all"):
    """
    yaml
    name: Memory Archive Search
    description: Search archived L2 entries by keyword (LIKE-based, no FTS).
    fields:
      query:
        name: Query
        description: Search term for key, value, or tags.
        required: true
        selector:
          text:
      limit:
        name: Limit
        description: Max results.
        default: 20
        selector:
          number:
            min: 1
            max: 50
      scope:
        name: Scope
        description: Filter by scope or 'all'.
        default: "all"
        selector:
          text:
    """
    if _is_test_mode():
        log.info("memory [TEST]: would search archive query=%s", query)  # noqa: F821
        return {"status": "test_mode_skip"}

    q = (query or "").strip()
    if not q:
        return {"status": "error", "op": "archive_search", "error": "query_empty"}
    try:
        results = _memory_archive_search_db_sync(q, int(limit), scope)
        return {"status": "ok", "op": "archive_search", "query": q, "count": len(results), "results": results}
    except Exception as e:
        log.error(f"memory_archive_search failed: {e}")  # noqa: F821
        return {"status": "error", "op": "archive_search", "error": str(e)}


@pyscript_executor  # noqa: F821
def _memory_archive_restore_db_sync(key: str) -> dict[str, Any]:
    """Move an entry from mem_archive back to mem. Returns {restored, key}."""
    for attempt in range(2):
        try:
            _ensure_db_once(force=attempt == 1)
            with closing(_get_db_connection()) as conn:
                cur = conn.cursor()
                cur.execute(
                    "SELECT key, value, scope, tags, tags_search, created_at, expires_at "
                    "FROM mem_archive WHERE key = ?",
                    (key,),
                )
                row = cur.fetchone()
                if not row:
                    return {"restored": False, "key": key, "error": "not_found"}
                now_iso = _utcnow_iso()
                cur.execute(
                    """
                    INSERT OR REPLACE INTO mem
                        (key, value, scope, tags, tags_search, created_at, last_used_at, expires_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (row[0], row[1], row[2], row[3], row[4], row[5], now_iso, row[6]),
                )
                cur.execute("DELETE FROM mem_archive WHERE key = ?", (key,))
                conn.commit()
            return {"restored": True, "key": key}
        except sqlite3.OperationalError:
            _reset_db_ready()
            if attempt == 0:
                time.sleep(0.1)
                continue
            raise
    return {"restored": False, "key": key, "error": "db_error"}


@service(supports_response="only")  # noqa: F821
async def memory_archive_restore(key: str = "", reembed: bool = True):
    """
    yaml
    name: Memory Archive Restore
    description: >-
      Move an archived entry back to active mem table.
      Optionally re-embeds the vector if sqlite-vec is available.
    fields:
      key:
        name: Key
        description: The key of the archived entry to restore.
        required: true
        selector:
          text:
      reembed:
        name: Re-embed
        description: Re-generate vector embedding after restore.
        default: true
        selector:
          boolean:
    """
    if _is_test_mode():
        log.info("memory [TEST]: would restore archived key=%s", key)  # noqa: F821
        return {"status": "test_mode_skip"}

    k = (key or "").strip()
    if not k:
        # C4: Fall back to editor helper for dashboard button
        try:
            k = state.get("input_text.ai_memory_edit_key").strip()  # noqa: F821
        except (TypeError, AttributeError, NameError):
            k = ""
    if not k:
        return {"status": "error", "op": "archive_restore", "error": "key_empty"}
    try:
        result = _memory_archive_restore_db_sync(k)
        if not result.get("restored"):
            return {"status": "error", "op": "archive_restore", "error": result.get("error", "unknown")}
        # Re-embed if requested and vec is available
        if reembed and _VEC_AVAILABLE:
            try:
                await memory_embed(key=k)
            except Exception as e:
                log.warning("memory_archive_restore: re-embed failed for %s: %s", k, e)  # noqa: F821
        log.info("memory_archive_restore: restored key=%s, reembed=%s", k, reembed)  # noqa: F821
        return {"status": "ok", "op": "archive_restore", "key": k, "reembedded": reembed and _VEC_AVAILABLE}
    except Exception as e:
        log.error(f"memory_archive_restore failed: {e}")  # noqa: F821
        return {"status": "error", "op": "archive_restore", "error": str(e)}


@pyscript_executor  # noqa: F821
def _memory_archive_stats_db_sync() -> dict[str, Any]:
    """Return basic stats for mem_archive."""
    for attempt in range(2):
        try:
            _ensure_db_once(force=attempt == 1)
            with closing(_get_db_connection()) as conn:
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) FROM mem_archive")
                count = cur.fetchone()[0]
                if count == 0:
                    return {"count": 0, "oldest_archived": None, "newest_archived": None}
                cur.execute("SELECT MIN(archived_at), MAX(archived_at) FROM mem_archive")
                row = cur.fetchone()
                return {
                    "count": count,
                    "oldest_archived": row[0],
                    "newest_archived": row[1],
                }
        except sqlite3.OperationalError:
            _reset_db_ready()
            if attempt == 0:
                time.sleep(0.1)
                continue
            raise
    return {"count": 0, "oldest_archived": None, "newest_archived": None}


@service(supports_response="only")  # noqa: F821
async def memory_archive_stats():
    """
    yaml
    name: Memory Archive Stats
    description: Return count and date range of archived entries.
    """
    if _is_test_mode():
        log.info("memory [TEST]: would return archive stats")  # noqa: F821
        return {"status": "test_mode_skip"}

    try:
        stats = _memory_archive_stats_db_sync()
        stats["status"] = "ok"
        stats["op"] = "archive_stats"
        return stats
    except Exception as e:
        log.error(f"memory_archive_stats failed: {e}")  # noqa: F821
        return {"status": "error", "op": "archive_stats", "error": str(e)}


# ── Memory Browse (Dashboard) ────────────────────────────────────────────────

BROWSE_SENSOR = "sensor.ai_memory_browse"
ARCHIVE_BROWSE_SENSOR = "sensor.ai_memory_archive_browse"
RELATED_BROWSE_SENSOR = "sensor.ai_memory_related_browse"


@service(supports_response="only")  # noqa: F821
async def memory_browse(query: str = "", limit: int = 10):
    """
    yaml
    name: Memory Browse
    description: >-
      Search L2 memory and write formatted results to sensor.ai_memory_browse
      for dashboard display. If query is empty, reads from
      input_text.ai_memory_search_query.
    fields:
      query:
        name: Query
        description: FTS search query. If empty, reads from dashboard helper.
        required: false
        example: "cooking dinner"
        selector:
          text:
      limit:
        name: Limit
        description: Max results.
        default: 10
        example: 10
        selector:
          number:
            min: 1
            max: 25
    """
    if _is_test_mode():
        log.info("memory [TEST]: would browse query=%s", query)  # noqa: F821
        return {"status": "test_mode_skip"}

    # Resolve query from helper if not provided directly
    q = query.strip() if query else ""
    if not q:
        try:
            q = state.get("input_text.ai_memory_search_query").strip()  # noqa: F821
        except (TypeError, AttributeError, NameError):
            q = ""
    if not q:
        state.set(BROWSE_SENSOR, value="empty",  # noqa: F821
                  new_attributes={"friendly_name": "Memory Browse", "query": "", "count": 0, "results_md": "_Enter a search query above._"})
        return {"status": "ok", "op": "browse", "query": "", "count": 0}

    lim = max(1, min(25, int(limit)))
    try:
        results = await _memory_search_db(q, lim)
    except Exception as e:
        log.error(f"memory_browse failed: {e}")  # noqa: F821
        state.set(BROWSE_SENSOR, value="error",  # noqa: F821
                  new_attributes={"friendly_name": "Memory Browse", "query": q, "count": 0, "results_md": f"**Error:** {e}"})
        return {"status": "error", "op": "browse", "query": q, "error": str(e)}

    # Format as markdown for dashboard
    if not results:
        md = f"_No results for '{q}'._"
    else:
        lines = []
        for r in results:
            key = r.get("key", "?")
            val = r.get("value", "")
            scope = r.get("scope", "")
            tags = r.get("tags", "")
            rank = r.get("rank", "")
            preview = (val[:120] + "…") if len(val) > 120 else val
            lines.append(f"**{key}** `{scope}`")
            lines.append(f"> {preview}")
            if tags:
                lines.append(f"Tags: `{tags}` | Rank: {rank}")
            lines.append("")
        md = "\n".join(lines)

    state.set(BROWSE_SENSOR, value="ok",  # noqa: F821
              new_attributes={"friendly_name": "Memory Browse", "query": q, "count": len(results), "results_md": md})
    return {"status": "ok", "op": "browse", "query": q, "count": len(results)}


# ── C4: Archive & Relationship Browse (Dashboard) ────────────────────────────

@service(supports_response="optional")  # noqa: F821
async def memory_archive_browse(query: str = "", limit: int = 10):
    """
    yaml
    name: Memory Archive Browse
    description: >-
      Search archived memory and write formatted results to
      sensor.ai_memory_archive_browse for dashboard display.
      If query is empty, shows archive stats.
    fields:
      query:
        name: Query
        description: Search term. If empty, reads from dashboard helper.
        required: false
        selector:
          text:
      limit:
        name: Limit
        description: Max results.
        default: 10
        selector:
          number:
            min: 1
            max: 25
    """
    if _is_test_mode():
        log.info("memory [TEST]: would archive_browse query=%s", query)  # noqa: F821
        return {"status": "test_mode_skip"}

    q = query.strip() if query else ""
    if not q:
        try:
            q = state.get("input_text.ai_memory_archive_search_query").strip()  # noqa: F821
        except (TypeError, AttributeError, NameError):
            q = ""
    if not q:
        # Show archive stats when no query
        try:
            stats = _memory_archive_stats_db_sync()
            count = stats.get("count", 0)
            oldest = stats.get("oldest_archived") or ""
            newest = stats.get("newest_archived") or ""
            md = f"**Archive:** {count} entries"
            if oldest and newest:
                md += f" ({oldest[:10]} — {newest[:10]})"
            md += "\n\n_Enter a query above to search archived entries._"
        except Exception:
            md = "_Enter a query above to search archived entries._"
        state.set(ARCHIVE_BROWSE_SENSOR, value="idle",  # noqa: F821
                  new_attributes={"friendly_name": "Archive Browse", "query": "", "count": 0, "results_md": md})
        return {"status": "ok", "op": "archive_browse", "query": "", "count": 0}

    lim = max(1, min(25, int(limit)))
    try:
        results = _memory_archive_search_db_sync(q, lim, "all")
    except Exception as e:
        log.error(f"memory_archive_browse failed: {e}")  # noqa: F821
        state.set(ARCHIVE_BROWSE_SENSOR, value="error",  # noqa: F821
                  new_attributes={"friendly_name": "Archive Browse", "query": q, "count": 0, "results_md": f"**Error:** {e}"})
        return {"status": "error", "op": "archive_browse", "query": q, "error": str(e)}

    if not results:
        md = f"_No archived entries matching '{q}'._"
    else:
        lines = []
        for r in results:
            key = r.get("key", "?")
            val = r.get("value", "")
            scope = r.get("scope", "")
            archived_at = (r.get("archived_at") or "")[:10]
            preview = (val[:120] + "…") if len(val) > 120 else val
            lines.append(f"**{key}** `{scope}` archived {archived_at}")
            lines.append(f"> {preview}")
            lines.append("")
        md = "\n".join(lines)

    state.set(ARCHIVE_BROWSE_SENSOR, value="ok",  # noqa: F821
              new_attributes={"friendly_name": "Archive Browse", "query": q, "count": len(results), "results_md": md})
    return {"status": "ok", "op": "archive_browse", "query": q, "count": len(results)}


@service(supports_response="optional")  # noqa: F821
async def memory_related_browse(key: str = ""):
    """
    yaml
    name: Memory Related Browse
    description: >-
      Show related entries for a key, write formatted results to
      sensor.ai_memory_related_browse for dashboard display.
      If key is empty, reads from the Editor key helper.
    fields:
      key:
        name: Key
        description: The key to find relations for. If empty, reads from Editor.
        required: false
        selector:
          text:
    """
    if _is_test_mode():
        log.info("memory [TEST]: would related_browse key=%s", key)  # noqa: F821
        return {"status": "test_mode_skip"}

    k = key.strip() if key else ""
    if not k:
        try:
            k = state.get("input_text.ai_memory_edit_key").strip()  # noqa: F821
        except (TypeError, AttributeError, NameError):
            k = ""
    if not k:
        state.set(RELATED_BROWSE_SENSOR, value="empty",  # noqa: F821
                  new_attributes={"friendly_name": "Related Entries", "key": "", "count": 0,
                                  "results_md": "_Enter a key in the Editor and tap Relations._"})
        return {"status": "ok", "op": "related_browse", "key": "", "count": 0}

    k_norm = _normalize_key(k)
    try:
        results = await _memory_related_db(k_norm, limit=10, depth=1)
    except Exception as e:
        log.error(f"memory_related_browse failed: {e}")  # noqa: F821
        state.set(RELATED_BROWSE_SENSOR, value="error",  # noqa: F821
                  new_attributes={"friendly_name": "Related Entries", "key": k, "count": 0,
                                  "results_md": f"**Error:** {e}"})
        return {"status": "error", "op": "related_browse", "key": k, "error": str(e)}

    if not results:
        md = f"_No related entries for '{k}'._"
    else:
        lines = []
        for r in results:
            rel_key = r.get("key", "?")
            rel_type = r.get("rel_type", "?")
            weight = r.get("weight", 0)
            val = r.get("value", "")
            preview = (val[:100] + "…") if len(val) > 100 else val
            lines.append(f"**{rel_key}** — {rel_type} (w={weight:.2f})")
            lines.append(f"> {preview}")
            lines.append("")
        md = "\n".join(lines)

    state.set(RELATED_BROWSE_SENSOR, value="ok",  # noqa: F821
              new_attributes={"friendly_name": "Related Entries", "key": k, "count": len(results),
                              "results_md": md})
    return {"status": "ok", "op": "related_browse", "key": k, "count": len(results)}


# ── Memory Editor Services (Dashboard V2.1) ──────────────────────────────────

@service(supports_response="only")  # noqa: F821
async def memory_edit():
    """Read key/value/tags/scope from dashboard helpers, call memory_set."""
    if _is_test_mode():
        log.info("memory [TEST]: would edit memory from dashboard")  # noqa: F821
        return {"status": "test_mode_skip"}

    key = (state.get("input_text.ai_memory_edit_key") or "").strip()  # noqa: F821
    value = (state.get("input_text.ai_memory_edit_value") or "").strip()  # noqa: F821
    tags = (state.get("input_text.ai_memory_edit_tags") or "").strip()  # noqa: F821
    scope = (state.get("input_text.ai_memory_edit_scope") or "household").strip()  # noqa: F821
    if not key:
        return {"status": "error", "op": "edit", "error": "key_empty"}
    return await memory_set(key=key, value=value, scope=scope, tags=tags)


@service(supports_response="only")  # noqa: F821
async def memory_delete():
    """Read key from dashboard helper, call memory_forget."""
    if _is_test_mode():
        log.info("memory [TEST]: would delete memory from dashboard")  # noqa: F821
        return {"status": "test_mode_skip"}

    key = (state.get("input_text.ai_memory_edit_key") or "").strip()  # noqa: F821
    if not key:
        return {"status": "error", "op": "delete", "error": "key_empty"}
    return await memory_forget(key=key)


@service(supports_response="only")  # noqa: F821
async def memory_load():
    """Load a memory entry into the dashboard edit fields."""
    if _is_test_mode():
        log.info("memory [TEST]: would load memory into dashboard fields")  # noqa: F821
        return {"status": "test_mode_skip"}

    key = (state.get("input_text.ai_memory_edit_key") or "").strip()  # noqa: F821
    if not key:
        return {"status": "error", "op": "load", "error": "key_empty"}
    result = await memory_get(key=key)
    if result.get("status") == "ok":
        state.set("input_text.ai_memory_edit_value", value=result.get("value", ""))  # noqa: F821
        state.set("input_text.ai_memory_edit_tags", value=result.get("tags", ""))  # noqa: F821
        state.set("input_text.ai_memory_edit_scope", value=result.get("scope", ""))  # noqa: F821
    return result


# ── Semantic Search Services (I-2: sqlite-vec) ─────────────────────────────


@service(supports_response="only")  # noqa: F821
async def memory_vec_health_check() -> dict[str, Any]:
    """
    yaml
    name: Memory Vec Health Check
    description: >-
      Test-load vec0.so and report status. Used by the recompile blueprint
      and startup initialization.
    """
    if _is_test_mode():
        log.info("memory [TEST]: would run vec health check")  # noqa: F821
        return {"status": "test_mode_skip"}

    if not Path(f"{VEC0_PATH}.so").exists():
        return {"status": "error", "error": "vec0.so not found", "vec_available": False}
    try:
        def _check_sync():
            with closing(sqlite3.connect(":memory:")) as conn:
                conn.enable_load_extension(True)
                conn.load_extension(VEC0_PATH)
                conn.execute("CREATE VIRTUAL TABLE _test USING vec0(e float[4])")
                conn.execute("INSERT INTO _test(rowid, e) VALUES (1, '[1,0,0,0]')")
                rows = conn.execute(
                    "SELECT rowid FROM _test WHERE e MATCH '[1,0,0,0]' AND k=1"
                ).fetchall()
                return len(rows) > 0
        ok = await asyncio.to_thread(_check_sync)
        return {
            "status": "ok" if ok else "error",
            "vec_available": ok,
            "vec0_path": f"{VEC0_PATH}.so",
            "dimensions": _VEC_DIMENSIONS,
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc), "vec_available": False}


@service(supports_response="only")  # noqa: F821
async def memory_embed(key: str) -> dict[str, Any]:
    """
    yaml
    name: Memory Embed
    description: >-
      Generate and store an embedding for a single memory entry.
      The vector is stored in mem_vec keyed by the memory key.
    fields:
      key:
        name: Key
        description: Memory key to embed.
        required: true
        selector:
          text:
    """
    if _is_test_mode():
        log.info("memory [TEST]: would embed key=%s", key)  # noqa: F821
        return {"status": "test_mode_skip"}

    if not key:
        return {"status": "error", "error": "key_missing"}
    if not _VEC_AVAILABLE:
        return {"status": "error", "error": "vec0_not_available"}

    # Fetch the memory entry
    result = await memory_get(key=key)
    if result.get("status") != "ok":
        return {"status": "error", "error": "memory_not_found", "key": key}

    # Build embedding input: tags + value
    tags = result.get("tags", "")
    value = result.get("value", "")
    embed_text = f"{tags} {value}".strip()
    if not embed_text:
        return {"status": "error", "error": "empty_content", "key": key}

    # Generate embedding via common_utilities.llm_direct_embed (cross-module service call)
    embed_result = await _call_llm_direct_embed(embed_text)
    if not isinstance(embed_result, dict) or embed_result.get("status") != "ok":
        error = embed_result.get("error", "embed_failed") if isinstance(embed_result, dict) else "embed_failed"
        return {"status": "error", "error": error, "key": key}

    embedding = embed_result["embedding"]
    vec_bytes = struct.pack(f"<{len(embedding)}f", *embedding)

    # Store in mem_vec
    def _store_sync():
        _ensure_db_once()
        with closing(_get_db_connection()) as conn:
            conn.enable_load_extension(True)
            conn.load_extension(VEC0_PATH)
            # Delete existing vector if present, then insert
            conn.execute("DELETE FROM mem_vec WHERE key = ?", (key,))
            conn.execute(
                "INSERT INTO mem_vec(key, embedding) VALUES (?, ?)",
                (key, vec_bytes),
            )
            conn.commit()

    try:
        await asyncio.to_thread(_store_sync)
    except Exception as exc:
        log.error("memory_embed: store failed for key=%s: %s", key, exc)  # noqa: F821
        return {"status": "error", "error": str(exc), "key": key}

    _set_result("ok", op="embed", key=key, dimensions=len(embedding))
    return {
        "status": "ok",
        "key": key,
        "dimensions": len(embedding),
        "tokens_used": embed_result.get("tokens_used", 0),
    }


@service(supports_response="only")  # noqa: F821
async def memory_embed_batch(
    batch_size: int = 50,
    scope: str = "all",
) -> dict[str, Any]:
    """
    yaml
    name: Memory Embed Batch
    description: >-
      Embed all memory entries that are missing vectors. Called by the nightly
      embedding blueprint. If ai_embedding_reindex_needed is ON, drops and
      recreates mem_vec first.
    fields:
      batch_size:
        name: Batch Size
        description: Max entries to embed per run (reads from helper if omitted).
        default: 50
        selector:
          number:
            min: 10
            max: 200
            mode: box
      scope:
        name: Scope
        description: Filter by scope, or "all" for everything.
        default: all
        selector:
          text:
    """
    if _is_test_mode():
        log.info("memory [TEST]: would embed batch (size=%d scope=%s)", batch_size, scope)  # noqa: F821
        return {"status": "test_mode_skip"}

    if not _VEC_AVAILABLE:
        return {"status": "error", "error": "vec0_not_available"}

    # Read batch size from helper if default
    try:
        helper_size = int(float(state.get("input_number.ai_embedding_batch_size") or 50))  # noqa: F821
        bs = max(10, min(helper_size, 200))
    except (TypeError, ValueError):
        bs = 50
    if batch_size and batch_size != 50:
        bs = max(10, min(int(batch_size), 200))

    # Check if reindex is needed
    reindex = False
    try:
        reindex_val = state.get("input_boolean.ai_embedding_reindex_needed")  # noqa: F821
        reindex = reindex_val == "on"
    except (TypeError, AttributeError):
        pass

    def _reindex_sync():
        """Drop and recreate mem_vec with current dimensions."""
        _ensure_db_once()
        with closing(_get_db_connection()) as conn:
            conn.enable_load_extension(True)
            conn.load_extension(VEC0_PATH)
            conn.execute("DROP TABLE IF EXISTS mem_vec")
            conn.execute(
                f"CREATE VIRTUAL TABLE mem_vec USING vec0("
                f"    key TEXT PRIMARY KEY,"
                f"    embedding float[{_VEC_DIMENSIONS}]"
                f");"
            )
            conn.commit()

    if reindex:
        try:
            # Re-read dimensions in case they changed
            global _VEC_DIMENSIONS
            try:
                dim_val = state.get("input_number.ai_embedding_dimensions")  # noqa: F821
                _VEC_DIMENSIONS = int(float(dim_val)) if dim_val not in (None, "unknown", "unavailable") else 512
            except (TypeError, ValueError):
                pass
            await asyncio.to_thread(_reindex_sync)
            log.info("memory_embed_batch: reindex — mem_vec recreated with %d dimensions", _VEC_DIMENSIONS)  # noqa: F821
        except Exception as exc:
            return {"status": "error", "error": f"reindex_failed: {exc}"}

    # Find keys missing vectors
    def _find_unembedded_sync():
        _ensure_db_once()
        with closing(_get_db_connection()) as conn:
            conn.enable_load_extension(True)
            conn.load_extension(VEC0_PATH)
            query = """
                SELECT m.key FROM mem AS m
                LEFT JOIN mem_vec AS v ON m.key = v.key
                WHERE v.key IS NULL
            """
            params: list[Any] = []
            if scope and scope != "all":
                query += " AND m.scope = ?"
                params.append(scope)
            query += " ORDER BY m.last_used_at DESC LIMIT ?"
            params.append(bs)
            return [row[0] for row in conn.execute(query, params).fetchall()]

    try:
        keys_to_embed = await asyncio.to_thread(_find_unembedded_sync)
    except Exception as exc:
        return {"status": "error", "error": f"query_failed: {exc}"}

    if not keys_to_embed:
        # Clear reindex flag if it was on
        if reindex:
            try:
                service.call(  # noqa: F821
                    "input_boolean", "turn_off",
                    entity_id="input_boolean.ai_embedding_reindex_needed",
                )
            except Exception:
                pass
        return {"status": "ok", "embedded": 0, "total_missing": 0, "reindexed": reindex}

    # Embed each key
    embedded = 0
    failed = 0
    tokens_total = 0
    for key in keys_to_embed:
        try:
            result = await memory_embed(key=key)
            if isinstance(result, dict) and result.get("status") == "ok":
                embedded += 1
                tokens_total += result.get("tokens_used", 0)
            else:
                failed += 1
        except Exception:
            failed += 1

    # Clear reindex flag after batch completes
    if reindex:
        try:
            service.call(  # noqa: F821
                "input_boolean", "turn_off",
                entity_id="input_boolean.ai_embedding_reindex_needed",
            )
        except Exception:
            pass

    log.info(  # noqa: F821
        "memory_embed_batch: embedded=%d, failed=%d, tokens=%d, reindexed=%s",
        embedded, failed, tokens_total, reindex,
    )
    return {
        "status": "ok",
        "embedded": embedded,
        "failed": failed,
        "tokens_used": tokens_total,
        "batch_size": bs,
        "reindexed": reindex,
    }


@service(supports_response="only")  # noqa: F821
async def memory_semantic_search(
    query: str,
    limit: int = 5,
) -> dict[str, Any]:
    """
    yaml
    name: Memory Semantic Search
    description: >-
      Pure semantic (vector similarity) search against mem_vec.
      Does NOT blend with FTS5 — use memory_search for blended results.
    fields:
      query:
        name: Query
        description: Natural language query to find semantically similar memories.
        required: true
        selector:
          text:
            multiline: true
      limit:
        name: Limit
        description: Maximum number of results.
        default: 5
        selector:
          number:
            min: 1
            max: 20
    """
    if _is_test_mode():
        log.info("memory [TEST]: would semantic search query=%s", query)  # noqa: F821
        return {"status": "test_mode_skip"}

    if not query:
        return {"status": "error", "op": "semantic_search", "error": "query_missing"}
    if not _VEC_AVAILABLE:
        return {"status": "error", "op": "semantic_search", "error": "vec0_not_available"}

    try:
        lim = max(1, min(int(limit), SEARCH_LIMIT_MAX))
    except (TypeError, ValueError):
        lim = 5

    # Read threshold
    try:
        raw = state.get("input_number.ai_semantic_similarity_threshold")  # noqa: F821
        threshold = float(raw) if raw not in (None, "unknown", "unavailable") else 0.7
    except (TypeError, ValueError):
        threshold = 0.7

    # Embed the query
    embed_result = await _call_llm_direct_embed(query)
    if not isinstance(embed_result, dict) or embed_result.get("status") != "ok":
        error = embed_result.get("error", "embed_failed") if isinstance(embed_result, dict) else "embed_failed"
        return {"status": "error", "op": "semantic_search", "error": error}

    query_vec = embed_result["embedding"]

    # KNN search
    def _search_sync():
        _ensure_db_once()
        with closing(_get_db_connection()) as conn:
            conn.enable_load_extension(True)
            conn.load_extension(VEC0_PATH)
            vec_bytes = struct.pack(f"<{len(query_vec)}f", *query_vec)
            rows = conn.execute(
                """
                SELECT v.key, v.distance
                FROM mem_vec AS v
                WHERE v.embedding MATCH ?
                  AND k = ?
                ORDER BY v.distance
                """,
                (vec_bytes, lim * 2),
            ).fetchall()

            results = []
            for row in rows:
                dist = float(row["distance"]) if row["distance"] is not None else 999.0
                similarity = 1.0 / (1.0 + dist)
                if similarity < threshold:
                    continue
                # Fetch full memory entry
                mem_row = conn.execute(
                    """
                    SELECT key, value, scope, tags, created_at, last_used_at, expires_at
                    FROM mem WHERE key = ?
                    """,
                    (row["key"],),
                ).fetchone()
                if mem_row:
                    results.append({
                        "key": mem_row["key"],
                        "value": mem_row["value"],
                        "scope": mem_row["scope"],
                        "tags": mem_row["tags"],
                        "created_at": mem_row["created_at"],
                        "last_used_at": mem_row["last_used_at"],
                        "expires_at": mem_row["expires_at"],
                        "similarity": round(similarity, 4),
                        "distance": round(dist, 4),
                    })
                if len(results) >= lim:
                    break
            return results

    try:
        results = await asyncio.to_thread(_search_sync)
    except Exception as exc:
        log.error("memory_semantic_search failed: %s", exc)  # noqa: F821
        return {"status": "error", "op": "semantic_search", "error": str(exc)}

    return {
        "status": "ok",
        "op": "semantic_search",
        "query": query,
        "count": len(results),
        "results": results,
        "tokens_used": embed_result.get("tokens_used", 0),
    }


# ── Ambient Memory Context (I-4) ──────────────────────────────────────────────

MEMORY_CONTEXT_ENTITY = "sensor.ai_memory_context"
MEMORY_CTX_SUMMARY_LIMIT = 5
MEMORY_CTX_MOOD_LIMIT = 3
MEMORY_CTX_TOPIC_LIMIT = 5
MEMORY_CTX_SUMMARY_CHARS = 120
MEMORY_CTX_MOOD_CHARS = 80


@time_trigger("startup", "cron(*/15 * * * *)")  # noqa: F821
async def memory_context_refresh():
    """Refresh sensor.ai_memory_context with recent summaries, moods, and topics from L2."""
    try:
        _ensure_db_once()
        summaries = await _memory_search_db("whisper summary", MEMORY_CTX_SUMMARY_LIMIT)
        moods = await _memory_search_db("whisper mood", MEMORY_CTX_MOOD_LIMIT)
        topics = await _memory_search_db("whisper topic", MEMORY_CTX_TOPIC_LIMIT)
    except Exception as exc:
        log.error("memory_context_refresh search failed: %s", exc)  # noqa: F821
        return

    parts = []

    for section_name, entries, char_limit in (
        ("Recent summaries", summaries, MEMORY_CTX_SUMMARY_CHARS),
        ("Recent moods", moods, MEMORY_CTX_MOOD_CHARS),
        ("Recent topics", topics, MEMORY_CTX_SUMMARY_CHARS),
    ):
        if not entries:
            continue
        lines = []
        for entry in entries:
            tag_list = entry.get("tags", "").split()
            if "whisper" not in tag_list:
                continue
            if "source_automation" in tag_list or "source_system" in tag_list:
                continue
            val = entry.get("value", "")
            if not val or not val.strip():
                continue
            if len(val) > char_limit:
                val = val[: char_limit - 3] + "..."
            lines.append(f"- {val}")
        if lines:
            parts.append(f"{section_name}:\n" + "\n".join(lines))

    context_text = "\n".join(parts) if parts else ""

    state.set(  # noqa: F821
        MEMORY_CONTEXT_ENTITY,
        value="ok" if context_text else "empty",
        new_attributes={
            "friendly_name": "AI Memory Context",
            "context": context_text,
            "icon": "mdi:brain",
        },
    )


@service(supports_response="optional")  # noqa: F821
async def memory_context_force_refresh():
    """Force-refresh sensor.ai_memory_context immediately (used at handoff time)."""
    if _is_test_mode():
        log.info("memory [TEST]: would force-refresh memory context")  # noqa: F821
        return

    await memory_context_refresh()
    return {"status": "ok", "op": "memory_context_force_refresh"}


# ── Todo Mirror (I-6) ─────────────────────────────────────────────────────────

TODO_L2_MARKER = "[L2:"
TODO_DEFAULT_ENTITY = "todo.ai_memory"


@pyscript_compile  # noqa: F821
def _parse_l2_key_from_description(desc: str) -> str | None:
    """Extract L2 key from todo description like '[L2:my_key]...'."""
    if not desc or TODO_L2_MARKER not in desc:
        return None
    start = desc.index(TODO_L2_MARKER) + len(TODO_L2_MARKER)
    end = desc.index("]", start) if "]" in desc[start:] else len(desc)
    return desc[start:end].strip() or None


@pyscript_compile  # noqa: F821
def _key_to_title(key: str) -> str:
    """Convert L2 key to human-readable title. 'project:implementation_plan_status' → 'Project: Implementation Plan Status'."""
    if ":" in key:
        prefix, rest = key.split(":", 1)
        return prefix.replace("_", " ").title() + ": " + rest.replace("_", " ").title()
    return key.replace("_", " ").title()


@pyscript_compile  # noqa: F821
def _build_todo_description(key: str, scope: str, tags: str, value: str = "") -> str:
    """Format todo item description: L2 marker line + full value."""
    marker = f"{TODO_L2_MARKER}{key}] scope:{scope} tags:{tags}"
    if value:
        return f"{marker}\n\n{value}"
    return marker


@pyscript_compile  # noqa: F821
def _extract_value_from_description(desc: str) -> str:
    """Extract value portion from todo description (after marker + blank line)."""
    if not desc or TODO_L2_MARKER not in desc:
        return ""
    parts = desc.split("\n\n", 1)
    return parts[1].strip() if len(parts) > 1 else ""


@pyscript_compile  # noqa: F821
def _extract_scope_from_description(desc: str) -> str:
    """Extract scope from marker line: [L2:key] scope:VALUE tags:..."""
    if not desc or "scope:" not in desc:
        return ""
    marker_line = desc.split("\n")[0]
    for part in marker_line.split():
        if part.startswith("scope:"):
            return part[6:]
    return ""


@pyscript_compile  # noqa: F821
def _extract_tags_from_description(desc: str) -> str:
    """Extract tags from marker line: [L2:key] scope:... tags:VALUE."""
    if not desc or "tags:" not in desc:
        return ""
    marker_line = desc.split("\n")[0]
    idx = marker_line.find("tags:")
    if idx < 0:
        return ""
    return marker_line[idx + 5:].strip()


@service(supports_response="optional")  # noqa: F821
async def memory_todo_sync(
    todo_entity: str = TODO_DEFAULT_ENTITY,
    scope_filter: str = "all",
    owner_filter: str = "",
    tag_filter: str = "",
    query_filter: str = "",
    max_age_days: int = 0,
    max_items: int = 50,
    include_important: bool = True,
    default_scope: str = "user",
):
    """
    yaml
    name: Memory Todo Sync
    description: >-
      Bidirectional sync between L2 memory and a HA todo list.
      L2→todo: mirrors matching entries. todo→L2: propagates user additions
      and edits. Completed (checked off) synced items delete the L2 entry.
    fields:
      todo_entity:
        name: Todo entity
        description: Target todo list entity.
        default: todo.ai_memory
        selector:
          entity:
            domain: todo
      scope_filter:
        name: Scope filter
        description: "Filter by scope type: all (no filter), user, or household."
        default: all
        selector:
          select:
            options: [all, user, household]
      owner_filter:
        name: Owner filter
        description: "Optional: filter by a specific person. Only applies when scope is 'user' or 'all'."
        default: ""
        selector:
          entity:
            domain: person
      tag_filter:
        name: Tag filter
        description: Comma-separated tags. Entry must have at least one. Empty = all.
        default: ""
        selector:
          text:
      query_filter:
        name: Query filter
        description: FTS search query. Empty = use scope/tag filters only.
        default: ""
        selector:
          text:
      max_age_days:
        name: Max age (days)
        description: Only sync entries created within N days. 0 = no limit.
        default: 0
        selector:
          number:
            min: 0
            max: 365
      max_items:
        name: Max items
        description: Cap total synced items.
        default: 50
        selector:
          number:
            min: 10
            max: 200
      include_important:
        name: Include important
        description: Always include entries tagged 'remember' or 'important'.
        default: true
        selector:
          boolean:
      default_scope:
        name: Default scope for user items
        description: "Scope assigned to user-created todo items synced to L2."
        default: user
        selector:
          select:
            options: [user, household]
    """
    if _is_test_mode():
        log.info("memory [TEST]: would sync todo entity=%s", todo_entity)  # noqa: F821
        return

    owner_slug = owner_filter.split(".", 1)[1] if "." in str(owner_filter) else (owner_filter or "")

    added_to_todo = 0
    removed_from_todo = 0
    added_to_l2 = 0
    deleted_from_l2 = 0
    edited_in_l2 = 0

    # ── Step 1: Get current todo items ──
    try:
        def _get_items():
            return service.call(  # noqa: F821
                "todo", "get_items",
                entity_id=todo_entity,
                status=["needs_action", "completed"],
                return_response=True,
            )
        raw = await asyncio.to_thread(_get_items)
        # Response format: {entity_id: {"items": [...]}}
        items_data = raw.get(todo_entity, {}) if isinstance(raw, dict) else {}
        todo_items = items_data.get("items", []) if isinstance(items_data, dict) else []
    except Exception as exc:
        log.error("memory_todo_sync: failed to get todo items: %s", exc)  # noqa: F821
        return {"status": "error", "op": "todo_sync", "error": str(exc)}

    # Parse existing synced keys and detect completed items
    synced_keys: dict[str, dict] = {}  # key → todo item
    completed_keys: list[tuple[str, dict]] = []  # (key, item) pairs
    user_items: list[dict] = []  # items without L2 marker

    for item in todo_items:
        desc = item.get("description", "") or ""
        l2_key = _parse_l2_key_from_description(desc)
        if l2_key:
            if item.get("status") == "completed":
                completed_keys.append((l2_key, item))
            else:
                synced_keys[l2_key] = item
        else:
            if item.get("status") != "completed":
                user_items.append(item)

    # ── Step 2: Handle completed items → delete from L2 ──
    for l2_key, item in completed_keys:
        try:
            await memory_forget(key=l2_key)
            deleted_from_l2 += 1
        except Exception:
            pass
        try:
            def _remove(uid=item.get("uid", "")):
                service.call("todo", "remove_item", entity_id=todo_entity, item=uid)  # noqa: F821
            await asyncio.to_thread(_remove)
            removed_from_todo += 1
        except Exception:
            pass

    # ── Step 3: Query L2 for matching entries ──
    _ensure_db_once()
    try:
        search_q = query_filter.strip() if query_filter else ""
        if search_q:
            l2_entries = await _memory_search_db(search_q, max_items)
        else:
            # No query filter — direct SQL fetch (FTS5 doesn't support "get all")
            def _fetch_all():
                with closing(_get_db_connection()) as conn:
                    rows = conn.execute(
                        """
                        SELECT key, value, scope, tags, created_at, last_used_at, expires_at
                        FROM mem
                        WHERE expires_at IS NULL OR expires_at > ?
                        ORDER BY last_used_at DESC
                        LIMIT ?
                        """,
                        (_utcnow_iso(), max_items * 2),
                    ).fetchall()
                    return [
                        {
                            "key": r["key"], "value": r["value"], "scope": r["scope"],
                            "tags": r["tags"], "created_at": r["created_at"],
                            "last_used_at": r["last_used_at"], "expires_at": r["expires_at"],
                        }
                        for r in rows
                    ]
            l2_entries = await asyncio.to_thread(_fetch_all)
    except Exception as exc:
        log.warning("memory_todo_sync: L2 query failed: %s", exc)  # noqa: F821
        l2_entries = []

    # Also fetch "important" entries if enabled
    important_entries = []
    if include_important:
        try:
            important_entries = await _memory_search_db("remember important", 20)
        except Exception:
            pass

    # Merge, dedup by key
    all_entries: dict[str, dict] = {}
    for entry in l2_entries + important_entries:
        key = entry.get("key", "")
        if key and key not in all_entries:
            all_entries[key] = entry

    # ── Step 4: Filter entries ──
    tag_set = {t.strip().lower() for t in tag_filter.split(",") if t.strip()} if tag_filter else set()
    cutoff_iso = None
    if max_age_days and max_age_days > 0:
        cutoff = datetime.now(UTC) - timedelta(days=max_age_days)
        cutoff_iso = cutoff.isoformat()

    filtered: dict[str, dict] = {}
    for key, entry in all_entries.items():
        # Scope filter
        if scope_filter != "all" and entry.get("scope", "") != scope_filter:
            continue
        # Owner filter — match scope == owner_slug (person-scoped entries)
        if owner_slug and entry.get("scope", "") != owner_slug:
            continue
        # Tag filter
        if tag_set:
            entry_tags = {t.strip().lower() for t in (entry.get("tags", "") or "").split(",") if t.strip()}
            # Also split on spaces for space-separated tags
            entry_tags |= {t.strip().lower() for t in (entry.get("tags", "") or "").split() if t.strip()}
            if not tag_set & entry_tags:
                continue
        # Age filter
        if cutoff_iso:
            created = entry.get("created_at", "")
            if created and created < cutoff_iso:
                continue
        filtered[key] = entry
        if len(filtered) >= max_items:
            break

    # ── Step 5: L2→todo — add new, update changed, remove stale ──
    updated_todo = 0
    sorted_filtered = sorted(filtered.items(), key=lambda kv: kv[1].get("created_at", ""), reverse=True)
    for key, entry in sorted_filtered:
        value = entry.get("value", "")
        created = entry.get("created_at", "")
        ts_prefix = ""
        if created:
            dt = _dt_from_iso(created)
            if dt:
                ts_prefix = dt.astimezone().strftime("%b %d %H:%M") + " — "
        summary = ts_prefix + _key_to_title(key)
        desc = _build_todo_description(key, entry.get("scope", ""), entry.get("tags", ""), value)
        if key in synced_keys:
            existing = synced_keys[key]
            old_summary = (existing.get("summary", "") or "").strip()
            old_desc = (existing.get("description", "") or "").strip()
            if old_summary != summary.strip() or old_desc != desc.strip():
                # ── I-6a: Detect user edits on todo side ──
                old_todo_value = _extract_value_from_description(old_desc)
                l2_value = (value or "").strip()

                if old_todo_value and old_todo_value != l2_value:
                    # Todo value differs from L2 — user edited the todo
                    # Propagate todo edit back to L2
                    edit_scope = (
                        _extract_scope_from_description(old_desc)
                        or entry.get("scope", "user")
                    )
                    edit_tags = (
                        _extract_tags_from_description(old_desc)
                        or entry.get("tags", "")
                    )
                    try:
                        await memory_set(
                            key=key,
                            value=old_todo_value,
                            scope=edit_scope,
                            tags=edit_tags,
                            expiration_days=0,
                            force_new=True,
                        )
                        edited_in_l2 += 1
                        log.info(  # noqa: F821
                            "memory_todo_sync: user edit propagated "
                            "todo→L2 key=%s", key,
                        )
                    except Exception as exc:
                        log.warning(  # noqa: F821
                            "memory_todo_sync: failed to propagate "
                            "edit for %s: %s", key, exc,
                        )
                    # Regenerate description from updated value
                    desc = _build_todo_description(
                        key, edit_scope, edit_tags, old_todo_value,
                    )

                # Update todo to match (L2-changed or post-edit-propagation)
                try:
                    def _update(uid=existing.get("uid", ""), s=summary, d=desc):
                        service.call(  # noqa: F821
                            "todo", "update_item",
                            entity_id=todo_entity,
                            item=uid,
                            rename=s,
                            description=d,
                        )
                    await asyncio.to_thread(_update)
                    updated_todo += 1
                except Exception:
                    pass
            continue
        try:
            def _add(s=summary, d=desc):
                service.call(  # noqa: F821
                    "todo", "add_item",
                    entity_id=todo_entity,
                    item=s,
                    description=d,
                )
            await asyncio.to_thread(_add)
            added_to_todo += 1
        except Exception as exc:
            log.warning("memory_todo_sync: failed to add todo item for %s: %s", key, exc)  # noqa: F821

    # Remove synced items whose keys are no longer in filtered set
    for key, item in synced_keys.items():
        if key not in filtered:
            try:
                def _remove(uid=item.get("uid", "")):
                    service.call("todo", "remove_item", entity_id=todo_entity, item=uid)  # noqa: F821
                await asyncio.to_thread(_remove)
                removed_from_todo += 1
            except Exception:
                pass

    # ── Step 6: todo→L2 — sync user-created items ──
    for item in user_items:
        summary = (item.get("summary", "") or "").strip()
        if not summary:
            continue
        new_key = f"todo:{_normalize_key(summary)}"
        if not new_key or new_key == "todo:":
            continue
        try:
            await memory_set(
                key=new_key,
                value=summary,
                scope=default_scope,
                tags="todo,user_added",
                expiration_days=365,
            )
            added_to_l2 += 1
        except Exception as exc:
            log.warning("memory_todo_sync: failed to create L2 entry for '%s': %s", summary, exc)  # noqa: F821
            continue
        # Update todo item with L2 marker
        desc = _build_todo_description(new_key, default_scope, "todo,user_added")
        try:
            def _update(uid=item.get("uid", ""), s=summary, d=desc):
                service.call(  # noqa: F821
                    "todo", "update_item",
                    entity_id=todo_entity,
                    item=uid,
                    rename=s,
                    description=d,
                )
            await asyncio.to_thread(_update)
        except Exception:
            pass

    log.info(  # noqa: F821
        "memory_todo_sync: +%d todo, ~%d todo, -%d todo, "
        "+%d L2, -%d L2, edit→L2 %d",
        added_to_todo, updated_todo, removed_from_todo,
        added_to_l2, deleted_from_l2, edited_in_l2,
    )
    return {
        "status": "ok",
        "op": "todo_sync",
        "added_to_todo": added_to_todo,
        "updated_todo": updated_todo,
        "removed_from_todo": removed_from_todo,
        "added_to_l2": added_to_l2,
        "deleted_from_l2": deleted_from_l2,
        "edited_in_l2": edited_in_l2,
    }


# ── BUDGET HISTORY: Rolling Usage Tracking ──────────────────────────────────


@service(supports_response="only")  # noqa: F821
async def budget_history_record(
    date: str = "",
    usage_usd: float = 0.0,
    exchange_rate: float = 0.92,
    llm_calls: int = 0,
    llm_tokens: int = 0,
    tts_chars: int = 0,
    stt_calls: int = 0,
    serper_credits: int = 0,
    model_cost_eur: float = 0.0,
    model_breakdown: str = "{}",
    music_generations: int = 0,
):
    """
    yaml
    name: Budget History Record
    description: >-
      Record a daily usage row into budget_history. Called from ai_budget_reset
      Step 1b after L2 log, before counter reset. INSERT OR REPLACE ensures
      idempotency (manual resets won't duplicate).
      C5: Added model_cost_eur, model_breakdown, music_generations.
    fields:
      date:
        name: Date
        description: "YYYY-MM-DD date for this record."
        required: true
        selector:
          text:
      usage_usd:
        name: Usage USD
        description: "Daily OpenRouter usage in USD."
        required: true
        selector:
          number:
            min: 0
            max: 9999
            step: 0.0001
      exchange_rate:
        name: Exchange rate
        description: "USD→EUR rate at time of recording."
        default: 0.92
        selector:
          number:
            min: 0
            max: 10
            step: 0.0001
      llm_calls:
        name: LLM calls
        description: "Total LLM calls for the day."
        default: 0
        selector:
          number:
            min: 0
            max: 999999
      llm_tokens:
        name: LLM tokens
        description: "Total LLM tokens for the day."
        default: 0
        selector:
          number:
            min: 0
            max: 999999
      tts_chars:
        name: TTS chars
        description: "Total TTS characters for the day."
        default: 0
        selector:
          number:
            min: 0
            max: 999999
      stt_calls:
        name: STT calls
        description: "Total STT calls for the day."
        default: 0
        selector:
          number:
            min: 0
            max: 999999
      serper_credits:
        name: Serper credits
        description: "Serper web search credits consumed for the day."
        default: 0
        selector:
          number:
            min: 0
            max: 999999
      model_cost_eur:
        name: Model Cost EUR
        description: "Per-model cost total in EUR (C5)."
        default: 0
        selector:
          number:
            min: 0
            max: 9999
            step: 0.0001
      model_breakdown:
        name: Model Breakdown
        description: "JSON string of per-model cost breakdown (C5)."
        default: "{}"
        selector:
          text:
            multiline: true
      music_generations:
        name: Music Generations
        description: "Total music generations for the day (C5)."
        default: 0
        selector:
          number:
            min: 0
            max: 999999
    """
    if _is_test_mode():
        log.info("memory [TEST]: would record budget history for date=%s", date)  # noqa: F821
        return {"status": "test_mode_skip"}

    _ensure_db_once()
    if not date:
        return {"status": "error", "op": "budget_history_record", "error": "date required"}

    usage_usd_f = float(usage_usd)
    exchange_rate_f = float(exchange_rate)
    usage_eur = round(usage_usd_f * exchange_rate_f, 4)
    model_cost_f = float(model_cost_eur)
    music_gens_i = int(music_generations)

    def _insert():
        with closing(_get_db_connection()) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO budget_history
                    (date, usage_usd, usage_eur, exchange_rate,
                     llm_calls, llm_tokens, tts_chars, stt_calls, serper_credits,
                     model_cost_eur, model_breakdown, music_generations)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (date, usage_usd_f, usage_eur, exchange_rate_f,
                 int(llm_calls), int(llm_tokens), int(tts_chars), int(stt_calls),
                 int(serper_credits), model_cost_f, str(model_breakdown), music_gens_i),
            )
            conn.commit()

    await asyncio.to_thread(_insert)
    log.info("budget_history_record: %s — $%.4f (€%.4f) model_cost=€%.4f", date, usage_usd_f, usage_eur, model_cost_f)  # noqa: F821

    # Refresh rolling sensor
    await budget_history_rolling()

    return {
        "status": "ok",
        "op": "budget_history_record",
        "date": date,
        "usage_usd": usage_usd_f,
        "usage_eur": usage_eur,
        "model_cost_eur": model_cost_f,
    }


@service(supports_response="only")  # noqa: F821
async def budget_history_rolling(months: int = 0):
    """
    yaml
    name: Budget History Rolling
    description: >-
      Query budget_history for the rolling window and update
      sensor.ai_openrouter_rolling_usage. Reads ai_budget_rolling_months
      unless months param is provided.
    fields:
      months:
        name: Months
        description: "Rolling window in months. 0 = read from helper."
        default: 0
        selector:
          number:
            min: 0
            max: 24
    """
    if _is_test_mode():
        log.info("memory [TEST]: would query rolling budget history")  # noqa: F821
        return {"status": "test_mode_skip"}

    _ensure_db_once()
    window = int(months) if int(months) > 0 else int(
        float(state.get("input_number.ai_budget_rolling_months") or 1)  # noqa: F821
    )
    cutoff_date = (datetime.now() - timedelta(days=window * 30)).strftime("%Y-%m-%d")

    def _query():
        with closing(_get_db_connection()) as conn:
            row = conn.execute(
                """
                SELECT
                    COALESCE(SUM(usage_eur), 0.0) AS total_eur,
                    COALESCE(SUM(usage_usd), 0.0) AS total_usd,
                    COALESCE(SUM(serper_credits), 0) AS total_serper,
                    COALESCE(SUM(model_cost_eur), 0.0) AS total_model_cost,
                    COUNT(*) AS days_with_data,
                    MIN(date) AS period_start,
                    MAX(date) AS period_end
                FROM budget_history
                WHERE date >= ?
                """,
                (cutoff_date,),
            ).fetchone()
            return dict(row) if row else {}

    result = await asyncio.to_thread(_query)
    hist_eur = round(result.get("total_eur", 0.0), 2)
    hist_usd = round(result.get("total_usd", 0.0), 4)
    hist_serper = result.get("total_serper", 0)
    days = result.get("days_with_data", 0)

    # Add today's live OpenRouter delta (not yet recorded by midnight reset)
    try:
        or_attrs = state.getattr("sensor.openrouter_credits") or {}  # noqa: F821
        total_usage_usd = float(or_attrs.get("total_usage", 0))
        midnight_usd = float(state.get("input_number.ai_openrouter_usage_midnight") or 0)  # noqa: F821
        today_usd = max(total_usage_usd - midnight_usd, 0.0)
        rate = float(state.get("sensor.usd_eur_exchange_rate") or 0.92)  # noqa: F821
        today_eur = round(today_usd * rate, 4)
    except Exception:
        today_usd = 0.0
        today_eur = 0.0

    # Serper live delta (credits consumed today, not yet in DB)
    try:
        serper_remaining = int(float(state.get("sensor.serper_account") or 0))  # noqa: F821
        serper_midnight = int(float(state.get("input_number.ai_serper_credits_midnight") or 0))  # noqa: F821
        today_serper = max(serper_midnight - serper_remaining, 0)
    except Exception:
        today_serper = 0

    total_eur = round(hist_eur + today_eur, 2)
    total_usd = round(hist_usd + today_usd, 4)
    total_days = days + (1 if today_usd > 0 or today_serper > 0 else 0)
    daily_avg = round(total_eur / total_days, 2) if total_days > 0 else 0.0
    total_serper = hist_serper + today_serper
    daily_avg_serper = round(total_serper / total_days, 1) if total_days > 0 else 0.0

    # Serper cost in EUR (credits × per-credit rate)
    try:
        serper_rate = float(state.get("sensor.ai_cost_per_serper_credit") or 0)  # noqa: F821
    except Exception:
        serper_rate = 0.0
    serper_total_cost = round(total_serper * serper_rate, 4)
    serper_today_cost = round(today_serper * serper_rate, 4)

    hist_model_cost = round(result.get("total_model_cost", 0.0), 4)
    # C5: Add today's live model cost delta
    try:
        today_model_cost = float(state.get("input_number.ai_model_cost_today") or 0)  # noqa: F821
    except Exception:
        today_model_cost = 0.0
    total_model_cost = round(hist_model_cost + today_model_cost, 4)

    state.set(  # noqa: F821
        "sensor.ai_openrouter_rolling_usage",
        total_eur,
        {
            "friendly_name": "AI OpenRouter Rolling Usage",
            "unit_of_measurement": "€",
            "icon": "mdi:router-wireless",
            "state_class": "measurement",
            "months": window,
            "days_with_data": total_days,
            "total_usd": total_usd,
            "today_eur": today_eur,
            "daily_average_eur": daily_avg,
            "model_cost_eur": total_model_cost,
            "period_start": result.get("period_start", ""),
            "period_end": result.get("period_end", ""),
        },
    )

    state.set(  # noqa: F821
        "sensor.ai_serper_rolling_usage",
        total_serper,
        {
            "friendly_name": "AI Serper Rolling Usage",
            "unit_of_measurement": "credits",
            "icon": "mdi:web",
            "state_class": "measurement",
            "months": window,
            "days_with_data": total_days,
            "today_credits": today_serper,
            "daily_average": daily_avg_serper,
            "total_cost_eur": serper_total_cost,
            "today_cost_eur": serper_today_cost,
            "cost_per_credit": serper_rate,
            "period_start": result.get("period_start", ""),
            "period_end": result.get("period_end", ""),
        },
    )

    return {
        "status": "ok",
        "op": "budget_history_rolling",
        "total_eur": total_eur,
        "today_eur": today_eur,
        "total_serper": total_serper,
        "today_serper": today_serper,
        "months": window,
        "days_with_data": total_days,
    }


@service(supports_response="only")  # noqa: F821
async def budget_history_backfill(fallback_rate: float = 0.92):
    """
    yaml
    name: Budget History Backfill
    description: >-
      One-time migration: parse existing budget_daily:* L2 entries and insert
      into budget_history. Uses INSERT OR IGNORE so it's safe to run multiple
      times. Uses fallback exchange rate for historical entries.
    fields:
      fallback_rate:
        name: Fallback exchange rate
        description: "USD→EUR rate for historical entries (rate wasn't stored in L2)."
        default: 0.92
        selector:
          number:
            min: 0
            max: 10
            step: 0.01
    """
    if _is_test_mode():
        log.info("memory [TEST]: would backfill budget history")  # noqa: F821
        return {"status": "test_mode_skip"}

    _ensure_db_once()
    rate = float(fallback_rate)

    def _backfill():
        inserted = 0
        skipped = 0
        with closing(_get_db_connection()) as conn:
            rows = conn.execute(
                "SELECT key, value FROM mem WHERE key LIKE 'budget_daily:%'"
            ).fetchall()
            for row in rows:
                key = row["key"]
                value = row["value"]
                # Extract date from key: budget_daily:YYYY-MM-DD
                date_match = re.match(r"budget_daily:(\d{4}-\d{2}-\d{2})", key)
                if not date_match:
                    skipped += 1
                    continue
                entry_date = date_match.group(1)
                # Parse fields from value string
                usd_match = re.search(r"openrouter_usage=\$?([\d.]+)", value)
                calls_match = re.search(r"llm_calls=(\d+)", value)
                tokens_match = re.search(r"llm_tokens=(\d+)", value)
                tts_match = re.search(r"tts_chars=(\d+)", value)
                stt_match = re.search(r"stt_calls=(\d+)", value)
                usage_usd = float(usd_match.group(1)) if usd_match else 0.0
                usage_eur = round(usage_usd * rate, 4)
                llm_c = int(calls_match.group(1)) if calls_match else 0
                llm_t = int(tokens_match.group(1)) if tokens_match else 0
                tts_c = int(tts_match.group(1)) if tts_match else 0
                stt_c = int(stt_match.group(1)) if stt_match else 0
                try:
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO budget_history
                            (date, usage_usd, usage_eur, exchange_rate,
                             llm_calls, llm_tokens, tts_chars, stt_calls)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (entry_date, usage_usd, usage_eur, rate,
                         llm_c, llm_t, tts_c, stt_c),
                    )
                    if conn.total_changes:
                        inserted += 1
                except Exception:
                    skipped += 1
            conn.commit()
        return inserted, skipped

    inserted, skipped = await asyncio.to_thread(_backfill)
    log.info("budget_history_backfill: inserted=%d, skipped=%d", inserted, skipped)  # noqa: F821

    # Refresh rolling sensor with backfilled data
    await budget_history_rolling()

    return {
        "status": "ok",
        "op": "budget_history_backfill",
        "inserted": inserted,
        "skipped": skipped,
        "fallback_rate": rate,
    }


@time_trigger("startup", "cron(5 0 * * *)")  # noqa: F821
async def budget_history_auto_refresh():
    """Refresh rolling usage sensor at startup and 5 min after midnight reset."""
    _ensure_db_once()
    await budget_history_rolling()


@state_trigger("input_number.ai_budget_rolling_months")  # noqa: F821
async def budget_history_window_change(**kwargs):
    """Re-query rolling usage when user changes the window."""
    await budget_history_rolling()


@state_trigger("sensor.openrouter_credits")  # noqa: F821
async def budget_history_credits_change(**kwargs):
    """Refresh rolling sensor when OpenRouter credits update (includes live today delta)."""
    await budget_history_rolling()


@state_trigger("sensor.serper_account")  # noqa: F821
async def budget_history_serper_change(**kwargs):
    """Refresh rolling sensor when Serper credits update."""
    await budget_history_rolling()
