# AI Privacy Gate

Implements identity-confidence-based feature gating to suppress personal features when another household member is home. Jessica's presence confidence gates Miquel's features and vice versa. Features are organized into three fixed tiers with hysteresis to prevent flapping, plus per-feature overrides.

## What's Inside

| Type | Count |
|------|-------|
| Template sensors | 1 |
| Input helpers (external) | ~51 |

## Entity Reference

| Entity ID | Type | Purpose |
|-----------|------|---------|
| `sensor.ai_privacy_gate_status` | Template sensor | Count of currently suppressed features; attributes include mode, per-person per-tier status, confidence values, and full feature map |
| `input_boolean.ai_privacy_gate_enabled` | Input Boolean | Master kill switch |
| `input_boolean.ai_privacy_gate_miquel_t1_suppressed` | Input Boolean | Miquel T1 (Intimate) tier suppression flag |
| `input_boolean.ai_privacy_gate_miquel_t2_suppressed` | Input Boolean | Miquel T2 (Personal) tier suppression flag |
| `input_boolean.ai_privacy_gate_miquel_t3_suppressed` | Input Boolean | Miquel T3 (Ambient) tier suppression flag |
| `input_boolean.ai_privacy_gate_jessica_t1_suppressed` | Input Boolean | Jessica T1 suppression flag |
| `input_boolean.ai_privacy_gate_jessica_t2_suppressed` | Input Boolean | Jessica T2 suppression flag |
| `input_boolean.ai_privacy_gate_jessica_t3_suppressed` | Input Boolean | Jessica T3 suppression flag |
| `input_select.ai_privacy_gate_mode` | Input Select | Global mode (auto, force_suppress_all, force_allow_all) |
| `input_select.ai_privacy_gate_<feature>` | Input Select | Per-feature override (auto/force_suppress/force_allow/off) — 31 features total |
| `input_number.ai_privacy_gate_<person>_<tier>_suppress_at` | Input Number | Confidence threshold to suppress (6 entries) |
| `input_number.ai_privacy_gate_<person>_<tier>_reenable_at` | Input Number | Confidence threshold to re-enable (6 entries) |

## Dependencies

- **Blueprint:** `privacy_gate_hysteresis.yaml` — 6 instances (3 tiers x 2 persons), handles threshold crossing with hysteresis
- **Sensors:** `sensor.identity_confidence_miquel`, `sensor.identity_confidence_jessica` — from presence identity system
- **Helper files:** `helpers_input_boolean.yaml` (master kill switch); `helpers_input_select.yaml` (mode select); `ai_privacy_gate_helpers.yaml` (31 per-feature override selects); `ai_per_user_helpers.yaml` (6 tier suppression booleans + 12 threshold numbers)

## Cross-References

- **31 gated features** across all tiers check their suppression state before executing — including wake_up_guard, calendar_alarm, bedtime routines (T1), email/notification follow-me, proactive briefings (T2), sleep/meal detection, interaction summarizer (T3), plus newer additions (bedtime_winddown, circadian_lighting, scene_preference, ambient_music, user_interview, alexa_on_demand_briefing, therapy_session)
- **ai_context_hot.yaml** — may reflect privacy gate status in hot context
- **ai_presence_identity.yaml** — provides the identity confidence sensors that drive tier suppression

## Notes

- **Three fixed tiers:** T1 (Intimate) = bedtime/wake features, T2 (Personal) = notifications/briefings/email, T3 (Ambient) = detection/summarization/sensors. Features marked `off` are never suppressed.
- **Hysteresis:** `suppress_at` > `reenable_at` prevents rapid toggling near the threshold.
- **Per-feature overrides** allow individual features to be forced on/off regardless of tier state.
- The template sensor's `features` attribute outputs a full JSON map of every feature's current allowed/suppressed status.
