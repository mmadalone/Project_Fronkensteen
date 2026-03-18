# AI User Interview

Provides helper entities for the LLM-driven user preference interview system. The interview engine conducts structured conversations to learn user preferences and stores them in L2 memory. Part of the I-36 integration milestone.

## What's Inside

| Type | Count |
|------|-------|
| Input helpers (external) | 2 |

## Entity Reference

| Entity ID | Type | Purpose |
|-----------|------|---------|
| `input_boolean.ai_interview_mode` | Input Boolean | Whether an interview session is currently active |
| `input_text.ai_interview_progress` | Input Text | JSON tracking interview progress (initial: `{}`, max: 255 chars) |

## Dependencies

- **Pyscript:** `pyscript/user_interview.py` — interview engine
- **Pyscript:** `pyscript/memory.py` — L2 memory for persisting learned preferences
- **Helper files:** `helpers_input_boolean.yaml`, `helpers_input_text.yaml`

## Cross-References

- **Voice agent prompts** — agents may check `ai_interview_mode` to adjust conversational behavior during interviews
- **L2 memory** — interview results are stored as preference entries with appropriate scope and tags

## Notes

- This is a minimal package — only two helpers. All interview logic lives in the pyscript engine.
- The progress helper stores JSON tracking which topics have been covered and responses collected, capped at 255 characters.
