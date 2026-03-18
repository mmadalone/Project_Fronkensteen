# AI Presence Identity

Provides helper entities for the per-person room identity inference engine (I-48/I-51). The Anchor-and-Track algorithm infers which person occupies which room using FP2 zones, WiFi trackers, voice satellites, and Markov priors. Output sensors are created dynamically by the pyscript module.

## What's Inside

| Type | Count |
|------|-------|
| Input helpers (external) | 4 |
| Pyscript sensors (dynamic) | 2 |

## Entity Reference

| Entity ID | Type | Purpose |
|-----------|------|---------|
| `input_boolean.ai_presence_identity_enabled` | Input Boolean | Kill switch (ON = active) |
| `input_number.ai_presence_identity_transition_window` | Input Number | Transition window in seconds (default: 120s) |
| `input_number.ai_presence_identity_confidence_floor` | Input Number | Minimum confidence threshold (default: 20%) |
| `input_number.ai_presence_identity_departure_debounce` | Input Number | Departure debounce in seconds (default: 60s) |
| `sensor.ai_location_miquel` | Pyscript sensor | Miquel's inferred zone (attrs: confidence, source, since, zone_friendly) |
| `sensor.ai_location_jessica` | Pyscript sensor | Jessica's inferred zone (attrs: confidence, source, since, zone_friendly) |

## Dependencies

- **Pyscript:** `pyscript/presence_identity.py` — 3 services, 4 triggers, creates output sensors via `state.set()`
- **Pyscript:** `pyscript/presence_patterns.py` — `pyscript.presence_predict_next()` for Markov tiebreaks
- **Hardware:** FP2 presence sensors, WiFi trackers, voice satellites
- **Helper files:** `helpers_input_boolean.yaml`, `helpers_input_number.yaml`

## Cross-References

- **ai_context_hot.yaml** — shows per-person location lines when identity is enabled and above confidence floor; falls back to anonymous presence when disabled
- **ai_privacy_gate.yaml** — identity confidence sensors gate feature suppression per person
- **privacy_gate_hysteresis.yaml** blueprint — uses identity confidence to trigger tier suppression

## Notes

- Output sensors are created dynamically by pyscript, not defined in the package YAML.
- Anchor types and confidence values: solo (100), voice_satellite (95), wifi_departure (95), wifi_arrival (90), count_constraint (85), fp2_transition (80), markov_prior (50 cap).
- Confidence decay: 0-15 min = full, 15-60 min = linear decay to 50%, 60+ min = capped at markov level.
- N=2 elimination logic: when only 2 people are tracked and one is confidently placed, the other is inferred by exclusion.
