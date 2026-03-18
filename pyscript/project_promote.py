"""Project Promotion Engine — Project Awareness for Voice Agents.

Reads /config/projects/*.md files with YAML frontmatter, filters by status
(active/blocked), and promotes project data to L2 memory keys and L1
input_text helpers for hot context injection. Supports optional LLM-generated
summaries cached by body hash.
"""
import os
import time
from datetime import datetime
from typing import Any

from shared_utils import build_result_entity_name

# =============================================================================
# Project Promotion Engine — Project Awareness for Voice Agents
# =============================================================================
# Promotes project data from /config/projects/*.md files to L2 memory and
# L1 input_text helpers for hot context injection.
#
# Services:
#   pyscript.project_promote_now
#     On-demand project promotion. Reads markdown files with YAML frontmatter,
#     filters active/blocked projects, writes to L2 memory, updates L1 helpers.
#     Called by automations (periodic sync, manual trigger) and at startup.
#
# Key design:
#   - Source of truth: /config/projects/*.md with YAML frontmatter
#   - L2 keys: project:{filename-slug}
#   - L1 helpers: input_text.ai_project_hot_context_line, _active_projects_summary
#   - Stale flag: input_boolean.ai_project_data_stale (set on scan failure)
#   - Promote cache: 5 min TTL to debounce rapid triggers
#   - Optional LLM summary: auto_summary: true in frontmatter triggers
#     pyscript.llm_task_call to generate summary from body
#   - Test mode: mock data from ai_test_mode toggle
#
# Dependencies:
#   - pyscript/memory.py (L2: memory_set, memory_search)
#   - packages/ai_project_tracking.yaml (helpers)
#   - packages/ai_test_harness.yaml (test mode toggle)
#
# Deployed: 2026-03-11
# =============================================================================

PROJECT_DIR = "/config/projects"
RESULT_ENTITY = "sensor.ai_project_promotion_status"
PROMOTE_CACHE_TTL = 300  # 5 min — debounce rapid triggers

# Statuses to promote (skip paused/done/archived)
PROMOTABLE_STATUSES = {"active", "blocked"}

# Priority sort order for hot context line
PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}

# ── Module-Level State ───────────────────────────────────────────────────────

_promote_cache: dict[str, Any] = {}
result_entity_name: dict[str, str] = {}
_consecutive_failures: int = 0
_FAILURE_NOTIFY_THRESHOLD: int = 3
# Cache of auto-generated summaries keyed by slug → (body_hash, summary)
_auto_summary_cache: dict[str, tuple] = {}


# ── Entity Name Helpers (standard pattern) ───────────────────────────────────

def _ensure_result_entity_name(force: bool = False) -> None:
    global result_entity_name
    if force or not result_entity_name:
        result_entity_name = build_result_entity_name(RESULT_ENTITY)


def _set_result(state_value: str = "ok", **attrs: Any) -> None:
    _ensure_result_entity_name()
    attrs.update(result_entity_name)
    state.set(RESULT_ENTITY, value=state_value, new_attributes=attrs)  # noqa: F821


# ── Test Mode ────────────────────────────────────────────────────────────────

def _check_test_mode() -> bool:
    try:
        return str(state.get("input_boolean.ai_test_mode") or "off").lower() == "on"  # noqa: F821
    except NameError:
        return False


# ── Pure-Python Sync Helpers ─────────────────────────────────────────────────

@pyscript_compile  # noqa: F821
def _parse_frontmatter(content: str) -> tuple:
    """Parse YAML frontmatter from markdown content.

    Returns (metadata_dict, body_text). Frontmatter is delimited by --- lines.
    Simple key: value parsing — no external YAML lib needed.
    """
    if not content or not content.strip().startswith("---"):
        return ({}, content or "")

    lines = content.split("\n")
    # Find closing ---
    end_idx = -1
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break

    if end_idx < 0:
        return ({}, content)

    # Parse frontmatter lines
    meta = {}
    for line in lines[1:end_idx]:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip().lower()
        val = val.strip()
        # Strip surrounding quotes
        if len(val) >= 2 and val[0] in ('"', "'") and val[-1] == val[0]:
            val = val[1:-1]
        # Type coercion for known fields
        if key == "auto_summary":
            val = val.lower() in ("true", "yes", "1", "on")
        meta[key] = val

    body = "\n".join(lines[end_idx + 1:]).strip()
    return (meta, body)


@pyscript_compile  # noqa: F821
def _slug_from_filename(filename: str) -> str:
    """Derive slug from filename: strip .md, lowercase."""
    if filename.lower().endswith(".md"):
        filename = filename[:-3]
    return filename.lower().strip()


@pyscript_compile  # noqa: F821
def _format_l2_value(meta: dict, body: str, summary_text: str = "") -> str:
    """Format project data for L2 storage.

    Format: Name | Status: active | Priority: high | Summary: ... | Next: ... | Due: ...
    """
    name = meta.get("name", meta.get("_slug", "Unknown"))
    parts = [name]
    parts.append(f"Status: {meta.get('status', 'unknown')}")
    parts.append(f"Priority: {meta.get('priority', 'medium')}")

    summary = summary_text or meta.get("summary", "")
    if summary:
        parts.append(f"Summary: {summary}")

    next_action = meta.get("next_action", "")
    if next_action:
        parts.append(f"Next: {next_action}")

    due = meta.get("due_date", "")
    if due:
        parts.append(f"Due: {due}")

    # Include body in L2 for semantic search (truncated)
    if body and len(body) > 10:
        truncated = body[:500] if len(body) > 500 else body
        parts.append(f"Detail: {truncated}")

    return " | ".join(parts)


@pyscript_compile  # noqa: F821
def _format_hot_context_entry(meta: dict, summary_text: str = "") -> str:
    """Format a single project for the hot context line.

    Format: "Bathroom Reno (blocked — waiting on tiles)"
    """
    name = meta.get("name", meta.get("_slug", "Unknown"))
    status = meta.get("status", "active")
    next_action = meta.get("next_action", "")
    summary = summary_text or meta.get("summary", "")

    if status == "blocked" and next_action:
        return f"{name} (blocked — {next_action})"
    elif next_action:
        return f"{name} ({status} — {next_action})"
    elif summary:
        short = summary[:40] + "..." if len(summary) > 40 else summary
        return f"{name} ({status} — {short})"
    return f"{name} ({status})"


@pyscript_compile  # noqa: F821
def _build_hot_context_line(projects: list, limit: int = 5) -> str:
    """Build the 255-char hot context line from sorted projects.

    projects: list of (meta, summary_text) tuples, pre-sorted by priority.
    """
    entries = []
    for meta, summary_text in projects[:limit]:
        entries.append(_format_hot_context_entry(meta, summary_text))

    line = ", ".join(entries)
    if len(line) > 250:
        line = line[:247] + "..."
    return line


@pyscript_compile  # noqa: F821
def _build_summary_line(projects: list) -> str:
    """Build the active projects summary (counts + high-priority names).

    Format: "8 active, 2 blocked. High: Bathroom Reno, HA Voice v3"
    """
    active_count = 0
    blocked_count = 0
    high_names = []

    for meta, _ in projects:
        status = meta.get("status", "active")
        if status == "active":
            active_count += 1
        elif status == "blocked":
            blocked_count += 1

        if meta.get("priority") == "high":
            high_names.append(meta.get("name", meta.get("_slug", "?")))

    parts = []
    if active_count:
        parts.append(f"{active_count} active")
    if blocked_count:
        parts.append(f"{blocked_count} blocked")

    line = ", ".join(parts) if parts else "No active projects"

    if high_names:
        line += ". High: " + ", ".join(high_names[:5])

    if len(line) > 250:
        line = line[:247] + "..."
    return line


@pyscript_compile  # noqa: F821
def _scan_project_files(directory: str) -> tuple:
    """Scan directory for .md files and return their contents.

    Runs via task.executor() — has access to open(), os.*, etc.
    Returns (projects_raw, error_msg) where projects_raw is list of
    (filename, content) tuples. error_msg is None on success.
    """
    projects_raw = []
    try:
        if not os.path.isdir(directory):
            os.makedirs(directory, exist_ok=True)
            return ([], None)

        for fname in os.listdir(directory):
            if not fname.lower().endswith(".md"):
                continue
            fpath = os.path.join(directory, fname)
            if not os.path.isfile(fpath):
                continue
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    content = f.read()
                projects_raw.append((fname, content))
            except Exception as exc:
                projects_raw.append(None)  # signal partial failure
    except Exception as exc:
        return ([], str(exc))

    # Filter out None entries (partial read failures)
    projects_raw = [p for p in projects_raw if p is not None]
    return (projects_raw, None)


@pyscript_compile  # noqa: F821
def _simple_hash(text: str) -> str:
    """Simple hash for change detection (no crypto needed)."""
    h = 0
    for ch in text:
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    return hex(h)


# ── L2 Memory Helper ────────────────────────────────────────────────────────

async def _l2_set(
    key: str, value: str, tags: str,
    scope: str = "user", expiration_days: int = 7,
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
        log.warning(f"project_promote: L2 set failed key={key}: {exc}")  # noqa: F821
        return False


# ── LLM Summary Helper ──────────────────────────────────────────────────────

async def _generate_llm_summary(slug: str, body: str) -> str:
    """Generate a 1-2 sentence summary of a project body via LLM.

    Caches by body hash to avoid re-summarizing unchanged content.
    Returns empty string on failure (fallback to manual summary).
    """
    global _auto_summary_cache

    body_hash = _simple_hash(body)

    # Check cache
    cached = _auto_summary_cache.get(slug)
    if cached and cached[0] == body_hash:
        return cached[1]

    try:
        result = pyscript.llm_task_call(  # noqa: F821
            instance="sensor.ha_text_ai",
            prompt=(
                "Summarize this project in 1-2 concise sentences for a voice "
                "assistant context line. Focus on current status and next steps. "
                "No markdown, no bullet points.\n\n" + body[:1500]
            ),
        )
        resp = await result
        if resp and isinstance(resp, dict):
            summary = resp.get("text", "") or resp.get("response", "")
            if summary:
                summary = summary.strip()[:200]
                _auto_summary_cache[slug] = (body_hash, summary)
                return summary
    except Exception as exc:
        log.warning(f"project_promote: LLM summary failed for {slug}: {exc}")  # noqa: F821

    return ""


# ── HA Helper Updates ────────────────────────────────────────────────────────

def _update_helper(entity_id: str, value: str) -> None:
    """Update an input_text helper, truncating to 255 chars."""
    try:
        service.call(  # noqa: F821
            "input_text", "set_value",
            entity_id=entity_id, value=str(value)[:255],
        )
    except Exception as exc:
        log.warning(  # noqa: F821
            f"project_promote: helper update failed {entity_id}: {exc}"
        )


def _set_stale_flag(stale: bool) -> None:
    """Set or clear the project data stale flag."""
    try:
        svc = "turn_on" if stale else "turn_off"
        service.call(  # noqa: F821
            "input_boolean", svc,
            entity_id="input_boolean.ai_project_data_stale",
        )
    except Exception as exc:
        log.warning(f"project_promote: stale flag failed: {exc}")  # noqa: F821


def _update_last_sync() -> None:
    """Update last sync timestamp."""
    try:
        now_iso = datetime.now().isoformat(timespec="seconds")
        service.call(  # noqa: F821
            "input_text", "set_value",
            entity_id="input_text.ai_project_last_sync",
            value=now_iso,
        )
    except Exception as exc:
        log.warning(f"project_promote: last sync failed: {exc}")  # noqa: F821


# ── Core Promotion Logic ─────────────────────────────────────────────────────

async def _promote_internal(test_mode: bool, force: bool) -> dict:
    """Core promotion logic.

    Scans project files, parses frontmatter, filters active/blocked,
    writes L2 + L1.
    """
    global _promote_cache

    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")

    # ── Cache check (debounce rapid triggers) ──
    if (not force
            and not test_mode
            and _promote_cache.get("date") == today_str
            and (time.time() - _promote_cache.get("fetched_at", 0))
                < PROMOTE_CACHE_TTL):
        return {
            "status": "ok", "op": "promote",
            "skipped": True, "reason": "cache_valid",
        }

    # ── Kill switch ──
    try:
        enabled = str(
            state.get("input_boolean.ai_project_tracking_enabled")  # noqa: F821
            or "on"
        ).lower()
    except NameError:
        enabled = "on"

    if enabled == "off" and not force:
        return {
            "status": "ok", "op": "promote",
            "skipped": True, "reason": "disabled",
        }

    # ── Hot context limit ──
    try:
        hot_limit = int(float(
            state.get("input_number.ai_project_hot_context_limit") or 5  # noqa: F821
        ))
    except (TypeError, ValueError, NameError):
        hot_limit = 5

    # ── Scan project files (via task.executor — pyscript sandboxes open/os) ──
    scan_failed = False
    projects_raw = []

    try:
        projects_raw, scan_error = await task.executor(  # noqa: F821
            _scan_project_files, PROJECT_DIR,
        )
        if scan_error:
            scan_failed = True
            log.warning(  # noqa: F821
                f"project_promote: directory scan failed: {scan_error}"
            )
    except Exception as exc:
        scan_failed = True
        log.warning(f"project_promote: directory scan failed: {exc}")  # noqa: F821

    # ── Handle scan failure ──
    if scan_failed:
        global _consecutive_failures
        _consecutive_failures += 1
        _set_stale_flag(True)
        log.warning(  # noqa: F821
            f"project_promote: scan failed — stale flag set "
            f"(failures={_consecutive_failures})"
        )
        if _consecutive_failures >= _FAILURE_NOTIFY_THRESHOLD:
            try:
                service.call(  # noqa: F821
                    "persistent_notification", "create",
                    title="Project Tracking: Repeated Failures",
                    message=(
                        f"Project file scan has failed {_consecutive_failures} "
                        f"consecutive times. Check {PROJECT_DIR} is accessible."
                    ),
                    notification_id="ai_project_scan_failure",
                )
            except Exception:
                pass
        return {
            "status": "ok", "op": "promote",
            "scan_failed": True, "stale": True,
            "consecutive_failures": _consecutive_failures,
        }

    # ── Reset failure counter on success ──
    global _consecutive_failures
    if _consecutive_failures > 0:
        _consecutive_failures = 0
        try:
            service.call(  # noqa: F821
                "persistent_notification", "dismiss",
                notification_id="ai_project_scan_failure",
            )
        except Exception:
            pass

    # ── Parse and filter ──
    promotable = []  # list of (meta, body, slug) for active/blocked projects
    all_parsed = []  # all projects regardless of status

    for fname, content in projects_raw:
        slug = _slug_from_filename(fname)
        meta, body = _parse_frontmatter(content)
        meta["_slug"] = slug

        # Derive name from first H1 or filename
        if "name" not in meta:
            for line in body.split("\n"):
                if line.startswith("# "):
                    meta["name"] = line[2:].strip()
                    break
            if "name" not in meta:
                meta["name"] = slug.replace("-", " ").title()

        status = meta.get("status", "active").lower()
        meta["status"] = status
        meta["priority"] = meta.get("priority", "medium").lower()

        all_parsed.append((meta, body, slug))

        if status in PROMOTABLE_STATUSES:
            promotable.append((meta, body, slug))

    # ── Sort by priority ──
    promotable.sort(
        key=lambda x: (
            PRIORITY_ORDER.get(x[0].get("priority", "medium"), 1),
            x[0].get("name", ""),
        )
    )

    # ── L2 writes + optional LLM summaries ──
    l2_ok_count = 0
    l2_fail_count = 0
    llm_summaries_generated = 0
    # (meta, summary_text) for hot context building
    project_entries = []

    for meta, body, slug in promotable:
        summary_text = ""

        # Optional LLM summary
        if meta.get("auto_summary") is True and body and not test_mode:
            summary_text = await _generate_llm_summary(slug, body)
            if summary_text:
                llm_summaries_generated += 1

        # Fall back to manual summary
        if not summary_text:
            summary_text = meta.get("summary", "")

        project_entries.append((meta, summary_text))

        # Format L2 value
        l2_value = _format_l2_value(meta, body, summary_text)
        l2_tags = (
            f"project {meta.get('category', 'personal')} "
            f"{meta['status']} {meta['priority']}"
        )

        if test_mode:
            log.info(  # noqa: F821
                f"project_promote [TEST]: WOULD write L2 project:{slug} "
                f"({len(l2_value)} chars, tags={l2_tags})"
            )
            l2_ok_count += 1
        else:
            ok = await _l2_set(
                key=f"project:{slug}",
                value=l2_value,
                tags=l2_tags,
                scope="user",
                expiration_days=7,
            )
            if ok:
                l2_ok_count += 1
            else:
                l2_fail_count += 1

    # ── Update L1 helpers ──
    hot_line = _build_hot_context_line(project_entries, hot_limit)
    summary_line = _build_summary_line(project_entries)

    if test_mode:
        log.info(  # noqa: F821
            f"project_promote [TEST]: hot_line: {hot_line}"
        )
        log.info(  # noqa: F821
            f"project_promote [TEST]: summary: {summary_line}"
        )
    else:
        _update_helper("input_text.ai_project_hot_context_line", hot_line)
        _update_helper("input_text.ai_active_projects_summary", summary_line)
        _update_last_sync()
        _set_stale_flag(False)

    # ── Update cache ──
    _promote_cache = {
        "date": today_str,
        "fetched_at": time.time(),
    }

    return {
        "status": "ok",
        "op": "promote",
        "total_files": len(projects_raw),
        "total_parsed": len(all_parsed),
        "promotable": len(promotable),
        "l2_ok": l2_ok_count,
        "l2_fail": l2_fail_count,
        "llm_summaries": llm_summaries_generated,
        "hot_line": hot_line,
        "summary": summary_line,
        "scan_failed": False,
        "stale": False,
        "test_mode": test_mode,
    }


# ── Services ─────────────────────────────────────────────────────────────────

@service(supports_response="only")  # noqa: F821
async def project_promote_now(force: bool = False):
    """
    yaml
    name: Project Promote Now
    description: >-
      Promote project data from /config/projects/*.md files to L2 memory.
      Reads markdown files with YAML frontmatter, filters active/blocked
      projects, writes to L2 memory and updates L1 input_text helpers for
      hot context injection. Use force=true for on-demand refresh bypassing
      cache.
    fields:
      force:
        name: Force
        description: Bypass cache and kill switch — force a fresh promotion.
        default: false
        selector:
          boolean:
    """
    t_start = time.monotonic()
    test_mode = _check_test_mode()

    result = await _promote_internal(test_mode, bool(force))

    elapsed = round((time.monotonic() - t_start) * 1000, 1)
    result["elapsed_ms"] = elapsed

    sensor_state = "test" if test_mode else result.get("status", "ok")
    _set_result(sensor_state, **result)

    if result.get("skipped"):
        log.info(  # noqa: F821
            f"project_promote: skipped ({result.get('reason', '')}) {elapsed}ms"
        )
    else:
        log.info(  # noqa: F821
            f"project_promote: promoted {result.get('promotable', 0)} projects "
            f"(l2_ok={result.get('l2_ok', 0)}, "
            f"llm={result.get('llm_summaries', 0)}) "
            f"stale={result.get('stale', False)} "
            f"{elapsed}ms{' [TEST]' if test_mode else ''}"
        )

    return result


# ── Startup ──────────────────────────────────────────────────────────────────

@time_trigger("startup")  # noqa: F821
async def project_promote_startup():
    """Initialize status sensor and run initial promotion."""
    _ensure_result_entity_name(force=True)
    _set_result("idle", op="startup")
    log.info("project_promote.py loaded — running initial promotion")  # noqa: F821

    await project_promote_now(force=True)


# ── Periodic Sync ────────────────────────────────────────────────────────────

@time_trigger("cron(*/30 * * * *)")  # noqa: F821
async def project_promote_periodic():
    """Periodic sync — refresh project data every 30 minutes."""
    log.info("project_promote: periodic sync triggered")  # noqa: F821
    await project_promote_now(force=False)
