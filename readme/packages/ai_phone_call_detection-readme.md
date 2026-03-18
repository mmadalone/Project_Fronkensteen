# AI Phone Call Detection

Detects active phone calls via the HA Companion App phone state sensor and defers TTS playback while a call is in progress. When the call ends, any deferred TTS items are automatically flushed and played back. Part of the I-30 integration milestone.

## What's Inside

| Type | Count |
|------|-------|
| Automations | 2 |
| Input helpers (external) | 2 |

## Entity Reference

| Entity ID | Type | Purpose |
|-----------|------|---------|
| `automation.ai_phone_call_start` | Automation | Detects ringing/offhook state and sets call-active flag |
| `automation.ai_phone_call_end` | Automation | Detects return to idle, clears flag, flushes deferred TTS after 2s delay |
| `input_boolean.ai_phone_call_active` | Input Boolean | Current call state (auto-managed by automations) |
| `input_boolean.ai_phone_call_defer_tts` | Input Boolean | Whether to defer TTS during calls |

## Dependencies

- **Sensor:** `sensor.madaringer_phone_state` (HA Companion App — states: idle, ringing, offhook)
- **Pyscript:** `pyscript/tts_queue.py` — provides `pyscript.tts_queue_flush_deferred` service and deferred queue logic
- **Helper file:** `helpers_input_boolean.yaml` (both input booleans defined there)

## Cross-References

- **ai_tts_queue.yaml** — TTS queue checks `ai_phone_call_active` / `ai_phone_call_defer_tts` to decide whether to defer items
- **pyscript/tts_queue.py** — deferred queue implementation and flush event handler

## Notes

- The call-end automation includes a 2-second delay before flushing to avoid premature playback during brief state transitions.
- Both automations use `mode: single` — concurrent call detections are safely ignored.
