# Project Promotion Engine

Reads `/config/projects/*.md` files with YAML frontmatter, filters by status (active/blocked), and promotes project data to L2 memory keys and L1 input_text helpers for hot context injection. Supports optional LLM-generated summaries cached by body hash. Part of the Project Awareness for Voice Agents feature.

## Services

| Service | Parameters | Returns | Description |
|---------|-----------|---------|-------------|
| `pyscript.project_promote_now` | `force` (bool, default false) | `{status, op, total_files, total_parsed, promotable, l2_ok, l2_fail, llm_summaries, hot_line, summary, scan_failed, stale, test_mode, elapsed_ms}` | Promote project data from markdown files to L2 memory and L1 helpers. Use `force=true` to bypass cache and kill switch. |

Service uses `supports_response="only"`.

## Triggers

| Trigger | Function | Condition |
|---------|----------|-----------|
| `@time_trigger("startup")` | `project_promote_startup` | Initialize status sensor and run initial promotion with `force=true`. |
| `@time_trigger("cron(*/30 * * * *)")` | `project_promote_periodic` | Periodic sync every 30 minutes (respects cache TTL). |

## Key Functions

- `_parse_frontmatter(content)` -- Parse YAML frontmatter from markdown. Simple key:value parsing, no external YAML lib. `@pyscript_compile`.
- `_slug_from_filename(filename)` -- Derive slug from filename (strip .md, lowercase). `@pyscript_compile`.
- `_format_l2_value(meta, body, summary_text)` -- Format project data for L2 storage with pipe-delimited fields. `@pyscript_compile`.
- `_format_hot_context_entry(meta, summary_text)` -- Format single project for hot context line. `@pyscript_compile`.
- `_build_hot_context_line(projects, limit)` -- Build 255-char hot context line from sorted projects. `@pyscript_compile`.
- `_build_summary_line(projects)` -- Build active/blocked counts + high-priority names. `@pyscript_compile`.
- `_scan_project_files(directory)` -- Scan directory for .md files. `@pyscript_executor`.
- `_simple_hash(text)` -- Simple hash for change detection (no crypto needed). `@pyscript_compile`.
- `_generate_llm_summary(slug, body)` -- LLM-generated 1-2 sentence summary, cached by body hash.
- `_promote_internal(test_mode, force)` -- Core promotion logic: scan, parse, filter, write L2 + L1.

## State Dependencies

- `input_boolean.ai_project_tracking_enabled` -- Kill switch (off = skip unless forced)
- `input_boolean.ai_test_mode` -- Test mode (log what would happen, no writes)
- `input_boolean.ai_project_data_stale` -- Output: stale flag (set on scan failure)
- `input_text.ai_project_hot_context_line` -- Output: top priorities for hot context (255 chars)
- `input_text.ai_active_projects_summary` -- Output: counts + high-priority names
- `input_text.ai_project_last_sync` -- Output: last sync timestamp
- `input_number.ai_project_hot_context_limit` -- Max projects in hot context line (default 5)

## Package Pairing

Pairs with `packages/ai_project_tracking.yaml` (kill switch, hot context line, summary, last sync, stale flag, hot context limit). Status sensor: `sensor.ai_project_promotion_status`.

## Called By

- **Blueprints**: `project_sync.yaml` automation calls `project_promote_now` on periodic and manual triggers
- **Hot context**: `packages/ai_context_hot.yaml` reads `ai_project_hot_context_line` for agent injection
- **Briefing**: `proactive_briefing.py` reads project data via `_section_projects()` for briefing assembly
- **Depends on**: `pyscript/memory.py` (L2), `pyscript/common_utilities.py` (llm_task_call for summaries)

## Notes

- **Source of truth**: Markdown files in `/config/projects/*.md` with YAML frontmatter (status, priority, category, next_action, due_date, auto_summary, summary).
- **Promotable statuses**: Only `active` and `blocked` projects are promoted. Paused/done/archived are skipped.
- **Promote cache**: 5-minute TTL debounces rapid triggers. Bypassed with `force=true`.
- **LLM summaries**: When `auto_summary: true` in frontmatter, calls `pyscript.llm_task_call` to generate a summary. Cached by body hash to avoid re-summarizing unchanged content.
- **Failure handling**: Consecutive scan failures increment a counter. After 3 failures, creates a persistent notification. Counter resets on success and dismisses the notification.
- **L2 schema**: key=`project:{slug}`, tags=`project {category} {status} {priority}`, scope=user, expiry=7d.
- **Priority sort**: high=0, medium=1, low=2. Hot context line shows highest priority first.
