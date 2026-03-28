![AI Dispatcher](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/ai_dispatcher-header.jpeg)

# AI Agent Dispatcher — Voice Pipeline Routing

Package shell for the agent dispatcher system (DC-7 / Task 11). Routes voice queries to the appropriate conversation agent based on satellite identity, user preferences, and contextual signals. All helpers have been moved to consolidated helper files.

## What's Inside

- **Input helpers:** Multiple (moved to consolidated helper files) -- booleans, selects, texts, numbers, buttons

Note: This package file now contains only comments after helper consolidation. All entity definitions live in the respective `helpers_*.yaml` files.

## Entity Reference

| Entity ID | Type | Purpose |
|---|---|---|
| `input_button.ai_dispatcher_*` | input_button | Manual dispatch triggers |
| `input_boolean.ai_dispatcher_*` | input_boolean | Dispatcher feature toggles |
| `input_select.ai_dispatcher_*` | input_select | Agent selection and mode controls |
| `input_text.ai_dispatcher_*` | input_text | Configuration values |
| `input_number.ai_dispatcher_*` | input_number | Numeric tuning parameters |

## Dependencies

- **Pyscript:** `pyscript/agent_dispatcher.py` (core routing engine, Priority 0 regex, LLM tool dispatch)
- **Voice agents:** All Standard and Extended conversation agents
- **Package:** `ai_identity.yaml` (identity confidence for personalized routing)
- **Package:** `ai_llm_budget.yaml` (budget gating for luxury dispatches)

## Cross-References

- **Blueprint:** `voice_handoff.yaml` -- uses dispatcher for pipeline switching
- **Blueprint:** `dispatcher_profile.yaml` -- per-satellite dispatcher configuration
- **Pyscript:** `agent_dispatcher.py` -- reads dispatcher helpers for routing decisions
- **All voice blueprints** that use `dispatcher_resolve_engine` for agent selection

## Notes

- The dispatcher package is intentionally thin -- all logic lives in `pyscript/agent_dispatcher.py` and configuration in blueprint instances.
- Deployed: 2026-03-01. Updated: 2026-03-11 (dispatcher_profile blueprint).
