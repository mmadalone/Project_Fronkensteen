# Per-Person Room Identity Inference

Uses FP2 mmWave zones, WiFi device trackers, voice satellite events, and Markov priors to infer which person occupies which room. With N=2 residents, elimination logic resolves most ambiguity. Outputs per-person location sensors with confidence scores and decay over time. Part of I-48 of the Voice Context Architecture.

## Services

| Service | Parameters | Returns | Description |
|---------|-----------|---------|-------------|
| `pyscript.presence_identity_status` | (none) | `{miquel: {zone, zone_friendly, confidence, confidence_label, source, elapsed_min}, jessica: {...}, engine: {enabled, occupancy_mode, active_zones, zone_state}}` | Debug dump of current tracking state. `supports_response="only"`. |
| `pyscript.presence_identity_force_anchor` | `person` (str, required: miquel/jessica), `zone` (str, required) | (none) | Manually pin a person to a zone with max confidence. |
| `pyscript.presence_identity_reset` | (none) | (none) | Clear all tracking state and reinitialize from current FP2/WiFi readings. |

## Triggers

| Trigger | Function | Condition |
|---------|----------|-----------|
| `@state_trigger` (8 FP2 binary sensors) | `presence_identity_fp2_trigger` | Zone state changes: transition detection, solo anchoring, count constraint. |
| `@state_trigger` (2 WiFi device trackers) | `presence_identity_wifi_trigger` | WiFi arrival/departure: anchor arriving person, eliminate departed person. Departure has debounce delay. |
| `@state_trigger("input_text.ai_last_satellite")` | `presence_identity_satellite_trigger` | Voice satellite interaction: anchor speaker to satellite's zone. In dual mode, uses elimination to resolve speaker identity. |
| `@time_trigger("cron(*/5 * * * *)")` | `presence_identity_decay_tick` | Periodic confidence decay. Applies Markov fallback when confidence drops below floor in dual mode. |
| `@time_trigger("startup")` | `presence_identity_startup` | Initialize zone state from FP2 readings. Anchor if solo mode detected. |

## Key Functions

- `_assign(person, zone, confidence, source)` -- Core assignment: set person's zone, confidence, source, and timestamp.
- `_anchor_solo(person)` -- Solo home: all active FP2 zones belong to this person.
- `_anchor_voice(person, zone)` -- Voice interaction pins person to satellite's zone.
- `_anchor_departure(departed)` -- WiFi departure: remaining FP2 bodies belong to other person.
- `_anchor_arrival(arriving)` -- WiFi arrival: new FP2 body is the arriving person.
- `_track_transition(from_zone, to_zone)` -- Zone OFF + zone ON within window = someone moved.
- `_apply_count_constraint()` -- Dual mode + exactly 2 zones active = one person per zone.
- `_apply_markov_tiebreak(active_zones)` -- Markov chain decides who goes where when both unassigned.
- `_compute_confidence(person)` -- Decay from anchor score: 0-15min = full, 15-60min = linear decay to 50%, 60min+ = capped at Markov level.
- `_update_sensors()` -- Push location state to `sensor.ai_location_miquel` and `sensor.ai_location_jessica`.

## State Dependencies

- `input_boolean.ai_presence_identity_enabled` -- Kill switch
- `input_number.ai_presence_identity_transition_window` -- Transition window in seconds (default 120)
- `input_number.ai_presence_identity_confidence_floor` -- Minimum confidence to report (default 20%)
- `input_number.ai_presence_identity_departure_debounce` -- Departure debounce in seconds (default 60)
- `sensor.occupancy_mode` -- Current mode: solo_miquel, solo_jessica, dual, away, guest
- `device_tracker.oppo_a60` / `device_tracker.oppo_a38` -- WiFi trackers for Miquel/Jessica
- `input_text.ai_last_satellite` -- Last-used voice satellite entity
- 8 FP2 binary sensors -- Zone presence detection
- `input_boolean.ai_test_mode` -- Test mode toggle

## Package Pairing

Pairs with `packages/ai_presence_identity.yaml` (kill switch, transition window, confidence floor, departure debounce). Output sensors: `sensor.ai_location_miquel`, `sensor.ai_location_jessica`, `sensor.ai_presence_identity_status`. Also reads from `packages/ai_identity.yaml` (occupancy mode) and `packages/ai_self_awareness.yaml` (last satellite).

## Called By

- **Hot context**: `packages/ai_context_hot.yaml` reads per-person location sensors for identity-aware presence lines
- **Other pyscript**: Calls `pyscript.presence_predict_next()` from `presence_patterns.py` for Markov tiebreaks
- **Dashboard**: Status sensor attributes visible in HA dashboard

## Notes

- **Lock discipline**: All reads/writes to `_location`, `_zone_state`, `_zone_change_ts`, and `_recent_zone_off` happen inside `async with _lock`. Helper functions are called from within locked handlers and do NOT acquire the lock themselves to avoid re-entrancy deadlocks.
- **Confidence anchor values**: solo=100, voice_satellite=95, wifi_departure=95, wifi_arrival=90, count_constraint=85, fp2_transition=80, markov_cap=50.
- **Confidence decay**: 0-15min = full base score, 15-60min = linear decay losing up to 50%, 60min+ = capped at Markov level (50).
- **Departure debounce**: WiFi departure triggers a configurable delay (default 60s) OUTSIDE the lock, then re-checks tracker state to absorb WiFi flapping.
- **MIN_DWELL_SEC**: 30-second flicker filter on FP2 zone changes.
- **N=2 assumption**: Hardcoded for 2 residents (Miquel and Jessica). Elimination logic depends on this.
