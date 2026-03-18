# AI Proactive Briefing

Provides the kill switch, delivery flags, and last-summary storage for the unified proactive briefing system. This is a slimmed-down package — all scheduling, section selection, speaker configuration, and delivery controls have moved into the unified `proactive_briefing.yaml` blueprint inputs. Part of Task 19 of the Voice Context Architecture.

## What's Inside

| Type | Count |
|------|-------|
| Input helpers (external) | 5 |

## Entity Reference

| Entity ID | Type | Purpose |
|-----------|------|---------|
| `input_boolean.ai_proactive_briefing_enabled` | Input Boolean | Master kill switch |
| `input_boolean.ai_briefing_delivered_morning` | Input Boolean | Per-instance delivered flag (morning) |
| `input_boolean.ai_briefing_delivered_afternoon` | Input Boolean | Per-instance delivered flag (afternoon) |
| `input_boolean.ai_briefing_delivered_evening` | Input Boolean | Per-instance delivered flag (evening) |
| `input_text.ai_last_briefing_summary` | Input Text | Last delivered briefing content |

## Dependencies

- **Pyscript:** `pyscript/proactive_briefing.py` — content assembly (`proactive_build_briefing`) and delivery pipeline (`proactive_briefing_now`)
- **Blueprint:** `proactive_briefing.yaml` — unified blueprint with 6 input sections, 5 triggers, self-resetting delivered flag
- **Helper files:** `helpers_input_boolean.yaml`, `helpers_input_text.yaml`

## Cross-References

- **Automation instances:** `automation.ai_proactive_morning_briefing`, `automation.ai_proactive_afternoon_briefing`, `automation.ai_proactive_evening_briefing`
- **ai_context_hot.yaml** — briefing content may reference hot context data
- **ai_privacy_gate.yaml** — proactive_briefing is a T2 (Personal) gated feature
- **pyscript/proactive_briefing.py** — `_section_projects()` pulls from project tracking system

## Notes

- This package was significantly slimmed during the unified briefing merge (2026-03-07). 12 helpers were removed (section toggles, household entities, output speaker, schedule, min confidence, time helpers) plus the midnight reset automation.
- The blueprint handles its own scheduling, delivery logic, and per-instance flag management — the package only provides shared state.
- Archived predecessors: `proactive_briefing_morning.yaml` and `proactive_briefing_slot.yaml`.
