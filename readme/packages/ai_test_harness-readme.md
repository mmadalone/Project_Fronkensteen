# AI Test Harness

Provides a global test mode toggle and override helpers for identity and routine stage, plus scripts to seed and clear L2 memory with test data. When test mode is active, TTS routes to a log sink (no audio), identity can be overridden to any household member, and routine stage can be manually set. Part of DC-5 of the Voice Context Architecture.

## What's Inside

| Type | Count |
|------|-------|
| Scripts | 2 |
| Input helpers (external) | 4 |

## Entity Reference

| Entity ID | Type | Purpose |
|-----------|------|---------|
| `script.ai_test_seed_memory` | Script | Seeds L2 memory with 6 test entries across miquel/jessica/household scopes (idempotent) |
| `script.ai_test_clear_memory` | Script | Removes all seeded test entries from L2 memory |
| `input_boolean.ai_test_mode` | Input Boolean | Global test flag (OFF = production) |
| `input_text.ai_test_identity` | Input Text | Override identity ("miquel"/"jessica"/"guest"/"") |
| `input_text.ai_test_routine_stage` | Input Text | Override routine stage |
| `input_text.ai_test_calendar_event` | Input Text | Mock calendar data for test mode |

## Dependencies

- **Pyscript:** `pyscript/memory.py` — `memory_set` and `memory_forget` services (scripts degrade gracefully if unavailable)
- **Helper files:** `helpers_input_boolean.yaml`, `helpers_input_text.yaml`

## Cross-References

- **Consumed by most ai_* packages** — many pyscript modules and blueprints check `input_boolean.ai_test_mode` to alter behavior:
  - **TTS queue** (`pyscript/tts_queue.py`) — logs instead of playing audio when test mode is ON
  - **Identity consumers** — use `ai_test_identity` override instead of real confidence sensors
  - **ai_predictive_schedule.yaml** — uses `ai_test_calendar_event` for mock calendar data
  - **ai_routine_tracker.yaml** — references test mode for simulation
  - **ai_presence_patterns.yaml** — references test mode for simulation

## Notes

- **Test data entries:** user profiles for Miquel and Jessica, Jessica's birthday, music preferences for both, household anniversary. Designed to exercise auto-relationship linking across scopes and tags.
- Both scripts use `continue_on_error: true` on every step to ensure partial failures don't abort the sequence.
- The seed script is idempotent — `memory_set` upserts by key, so running twice updates rather than duplicates.
- Includes a commented-out dashboard card with test controls, identity readouts, and a conditional "TEST MODE ACTIVE" banner.
