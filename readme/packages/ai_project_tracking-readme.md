# AI Project Tracking

Provides helper entities for the project awareness system, allowing voice agents to reference active projects in hot context and briefings. The source of truth is markdown files with YAML frontmatter in `/config/projects/`. The pyscript engine reads those files and promotes project data to L2 memory and L1 helpers.

## What's Inside

| Type | Count |
|------|-------|
| Input helpers (external) | 5 |
| Pyscript sensors (dynamic) | 1 |

## Entity Reference

| Entity ID | Type | Purpose |
|-----------|------|---------|
| `input_boolean.ai_project_tracking_enabled` | Input Boolean | Kill switch |
| `input_boolean.ai_project_data_stale` | Input Boolean | Flag indicating project data needs refresh |
| `input_text.ai_project_last_sync` | Input Text | Timestamp of last project sync |
| `sensor.ai_project_hot_context_line` | Pyscript sensor | Top priorities for hot context. `full_text` attribute has untruncated content (set by pyscript via `state.set()`) |
| `input_number.ai_project_hot_context_limit` | Input Number | Max number of projects shown in hot context |
| `sensor.ai_project_promotion_status` | Pyscript sensor | Last sync result (ok/error/idle); attrs include project counts by status (set by pyscript via `state.set()`) |

## Dependencies

- **Pyscript:** `pyscript/project_promote.py` — reads project files, promotes to L2 + L1 helpers
- **Blueprint:** `project_sync.yaml` — triggers project sync on file changes or schedule
- **Source files:** `/config/projects/*.md` — markdown with YAML frontmatter (status, priority, category, etc.)
- **Pyscript:** `pyscript/memory.py` — L2 memory (key=`project:{slug}`, tags=`project {category} {status} {priority}`)
- **Helper files:** `helpers_input_boolean.yaml`, `helpers_input_text.yaml`; `ai_dev_helpers.yaml` (number helper — hot context limit)

## Cross-References

- **ai_context_hot.yaml** — projects block injected after Schedule section using `ai_project_hot_context_line` `full_text` attribute
- **pyscript/proactive_briefing.py** — `_section_projects()` includes active projects in briefing content
- **proactive_briefing.yaml** blueprint — `projects` available as a briefing section

## Notes

- Frontmatter fields: `status` (active/paused/blocked/done/archived), `priority` (high/medium/low), `category` (ha/tech/personal/work), `next_action`, `due_date`, `auto_summary`, `summary`.
- When `auto_summary: true` is set in frontmatter, the engine calls `llm_task_call` to generate a summary, cached by body hash.
- L2 entries use scope=user, expiry=7d.
