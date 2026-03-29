# AI User Interview

Provides helper entities for the LLM-driven user preference interview system. The interview engine conducts structured conversations to learn user preferences and stores them in L2 memory. Part of the I-36 integration milestone.

## What's Inside

| Type | Count |
|------|-------|
| Input helpers (external) | 3 |

## Entity Reference

| Entity ID | Type | Purpose |
|-----------|------|---------|
| `input_boolean.ai_interview_mode` | Input Boolean | Whether an interview session is currently active |
| `input_text.ai_interview_progress` | Input Text | JSON tracking interview progress (initial: `{}`, max: 255 chars) |
| `input_select.ai_privacy_gate_user_interview` | Input Select | Privacy gate per-feature override for user interview |
| `sensor.ai_user_interview_status` | Pyscript sensor | Interview status (ok/error/idle); attrs: interview progress, last completed topic |

## Dependencies

- **Pyscript:** `pyscript/user_interview.py` — interview engine (services: `user_interview_save`, `user_interview_status`, `user_interview_reset`, `user_interview_preseed`, `user_interview_exchanges`)
- **Pyscript:** `pyscript/memory.py` — L2 memory for persisting learned preferences
- **Blueprint:** `user_interview.yaml` — interview session orchestration
- **Helper files:** `helpers_input_boolean.yaml`, `helpers_input_text.yaml`; `ai_privacy_gate_helpers.yaml` (per-feature select)

## Cross-References

- **ai_context_hot.yaml** — reads `ai_interview_mode` for gate
- **Voice agent prompts** — agents may check `ai_interview_mode` to adjust conversational behavior during interviews
- **L2 memory** — interview results are stored as preference entries with appropriate scope and tags

## Notes

- This is a minimal package — three helpers (boolean, text, privacy gate select). All interview logic lives in the pyscript engine.
- The progress helper stores JSON tracking which topics have been covered and responses collected, capped at 255 characters.
