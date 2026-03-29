# AI Identity Confidence — Multi-User Recognition

Core identity layer of the Voice Context Architecture. Computes per-person confidence scores (0-100 pts) from WiFi MAC presence, GPS companion app, FP2 mmWave zones, and sustained occupancy patterns. Derives an occupancy mode that drives privacy gating, personalization, and context filtering across the entire system.

## What's Inside

- **Template binary sensors:** 2 (`binary_sensor.ai_solo_single_zone`, `binary_sensor.ai_wifi_stale_condition_jessica`)
- **Template sensors:** 3 (`sensor.identity_confidence_miquel`, `sensor.identity_confidence_jessica`, `sensor.occupancy_mode`)
- **Automations:** 4 (sustained solo zone on/off, WiFi stale Jessica on/off)
- **Input helpers:** 3+ (moved to consolidated helper files) -- booleans, numbers

## Entity Reference

| Entity ID | Type | Purpose |
|---|---|---|
| `sensor.identity_confidence_miquel` | template sensor | 0-100 confidence score (WiFi 30 + GPS 50 + FP2 solo 15 + sustained 5, configurable via `ai_wifi_score_*` helpers) |
| `sensor.identity_confidence_jessica` | template sensor | 0-50 confidence score (WiFi 30 + FP2 solo 15 + sustained 5; no GPS, configurable via `ai_wifi_score_*` helpers) |
| `sensor.occupancy_mode` | template sensor | `solo_miquel`, `solo_jessica`, `dual`, `away`, or `guest` |
| `binary_sensor.ai_solo_single_zone` | template binary_sensor | True when one phone on WiFi + exactly one FP2 zone occupied |
| `binary_sensor.ai_wifi_stale_condition_jessica` | template binary_sensor | True when Jessica WiFi home but no FP2 presence detected |
| `input_boolean.ai_guest_mode` | input_boolean | Manual override, forces all scores to 0 |
| `input_boolean.ai_sustained_solo_zone` | input_boolean | Set after 10 min sustained solo occupancy (+5 pts default) |
| `input_boolean.ai_wifi_stale_jessica` | input_boolean | WiFi stale flag (zeroes Jessica's WiFi signal) |
| `input_number.ai_wifi_stale_timeout` | input_number | Tunable WiFi staleness timeout (5-60 min) |
| `automation.ai_sustained_solo_zone_on` | automation | Sets sustained flag after 10 min solo + single FP2 zone |
| `automation.ai_sustained_solo_zone_off` | automation | Clears sustained flag immediately when condition breaks |
| `automation.ai_wifi_stale_jessica_on` | automation | Marks WiFi stale after configurable timeout |
| `automation.ai_wifi_stale_jessica_off` | automation | Clears WiFi stale flag on FP2 presence recovery |

## Dependencies

- **Device trackers:** `device_tracker.oppo_a60` (Miquel WiFi), `device_tracker.oppo_a38` (Jessica WiFi), `device_tracker.madoppo` (Miquel GPS)
- **Hardware:** Aqara FP2 presence sensors (7 zones), GL.iNet router (WiFi MAC tracking)
- **Integration:** HA Companion App (GPS for Miquel)

## Cross-References

- **Package:** `ai_context_hot.yaml` -- occupancy mode and identity scores drive presence/privacy sections
- **Package:** `ai_away_patterns.yaml` -- uses `sensor.occupancy_mode` for departure detection
- **Package:** `ai_email_promotion.yaml` -- identity confidence gates email visibility
- **Package:** `ai_focus_guard.yaml` -- uses occupancy for social nudges
- **Pyscript:** `pyscript/presence_identity.py` (I-51) -- builds on top of these base signals
- **Privacy gate:** Confidence thresholds (70+/30-69/<30) applied by consumers for personalization tiers

## Notes

- Jessica's max score is 50 pts with default weights (no companion app GPS yet). Miquel's max is 100 pts. Scoring weights are configurable via `input_number.ai_wifi_score_primary` (default 30), `ai_wifi_score_secondary` (default 50), `ai_wifi_score_tertiary` (default 15), `ai_wifi_score_quaternary` (default 5).
- WiFi staleness handles the common case where Jessica's phone stays on WiFi after she leaves (router slow to deregister). If WiFi says home but no FP2 zone detects a body for N minutes, the WiFi signal (default 30 pts) is zeroed.
- Guest mode is a hard override: all confidence scores forced to 0, no exceptions.
- The occupancy mode sensor incorporates WiFi staleness for Jessica -- if her WiFi is stale, she's treated as not home for occupancy purposes.
- Deployed: 2026-03-01. Updated: 2026-03-06 (WiFi staleness for Jessica).
