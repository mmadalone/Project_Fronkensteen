# AI Phone Call Detection

Detects active phone calls through each person's HA Companion App call-state sensor and defers TTS playback while a call is in progress. When the call ends, any deferred TTS items are automatically flushed and played back. Part of the I-30 integration milestone.

## What's Inside

| Type | Count |
|------|-------|
| Automations | 2 |
| Input helpers (external) | 1 |
| Runtime sensors (pyscript) | 1 |

## Entity Reference

| Entity ID | Type | Purpose |
|-----------|------|---------|
| `automation.ai_phone_call_start` | Automation | Fires when any phone starts ringing or goes offhook; sets the call-active flag |
| `automation.ai_phone_call_end` | Automation | Fires once no phone is ringing or offhook and at least one is idle; clears the flag, flushes deferred TTS after a 2 s delay |
| `sensor.ai_phone_call_active` | Sensor (pyscript `state.set`) | Current call state (`on`/`off`), written by the automations through `pyscript.set_sensor_value`. Seeded `off` at startup by `state_bridge.py` |
| `input_boolean.ai_phone_call_defer_tts` | Input Boolean | Whether to defer TTS during calls |

## Dependencies

- **Phones:** `sensor.ai_person_phones`, published by `pyscript/person_phones.py`. Lists every person's Companion App `phone_state` sensor (states: idle, ringing, offhook). No phone entity ID is configured in this package.
- **Pyscript:** `pyscript/tts_queue.py` — provides `pyscript.tts_queue_flush_deferred` and the deferred queue logic
- **Pyscript:** `pyscript/state_bridge.py` — provides `pyscript.set_sensor_value` and seeds `sensor.ai_phone_call_active`
- **Helper file:** `helpers_input_boolean.yaml` (`ai_phone_call_defer_tts`)

## Cross-References

- **pyscript/tts_queue.py** — checks `sensor.ai_phone_call_active` and `ai_phone_call_defer_tts` to decide whether to defer an item; implements the flush handler
- **pyscript/person_phones.py** — finds each person's phone from their device trackers

## Notes

- Both automations use template triggers over `sensor.ai_person_phones`, so renaming a phone, or another person installing the Companion App, needs no edit here.
- A phone that drops to `unavailable` mid-call does not end the call. The call ends when no phone is ringing or offhook and at least one is idle, which also clears the flag if the phone comes back idle after an unavailable spell.
- A call already in progress when Home Assistant starts is detected once the phones are discovered.
- The call-end automation waits 2 seconds before flushing to avoid premature playback during brief state transitions.
- Both automations use `mode: single` — concurrent call detections are safely ignored.
