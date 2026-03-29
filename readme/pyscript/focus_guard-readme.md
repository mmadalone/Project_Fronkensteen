# Focus Guard — Anti-ADHD Nudge System with Escalating Alerts

Task 20 of the Voice Context Architecture. Evaluates 6 nudge conditions every 15 minutes (and on FP2 zone changes), delivering escalating TTS nudges via the priority queue. Respects focus-mode and snooze states, and logs nudge patterns to L2 memory. Designed to help users with ADHD stay on track without being intrusive.

## Services

| Service | Parameters | Returns | Description |
|---------|-----------|---------|-------------|
| `pyscript.focus_guard_evaluate` | _(none)_ | `{status, op, nudges_fired, nudge_details, elapsed_ms}` | Full evaluation of all 6 nudge conditions. Returns which nudges fired, their priority levels, and escalation states. Can be called on-demand or by the 15-min cron / FP2 state trigger. `supports_response="only"` |
| `pyscript.focus_guard_mark_meal` | `meal_time` (optional) | `{status, op, meal_time}` | Set last_meal_time to now (or a specific time). Called by voice: "I just ate." Resets the meal reminder escalation. `supports_response="only"` |
| `pyscript.focus_guard_snooze` | `minutes` (default 30) | `{status, op, snooze_until}` | Snooze all non-critical nudges for N minutes. Called by voice: "Remind me in 30 minutes." `supports_response="only"` |

## Triggers

| Trigger | Function | Condition |
|---------|----------|-----------|
| `@time_trigger("cron(*/15 * * * *)")` | `_cron_evaluate` | 15-minute evaluation cycle |
| `@state_trigger("binary_sensor.fp2_presence_sensor_workshop")` | `_on_workshop_zone_change` | Workshop zone entry/exit triggers evaluation (primary focus zone) |
| `@state_trigger("binary_sensor.fp2_presence_sensor_living_room == 'on'", ...)` | `_zone_change_re_eval` | Living room, kitchen, bathroom, bed, main room zone entry triggers zone tracking update and break suggestion reset |
| `@time_trigger("startup")` | `_startup` | Initializes status sensor and workshop tracking state |

## Key Functions

- `_evaluate_all()` — Core evaluation: runs all 6 nudge condition checks inline (time_check, meal_reminder, calendar_warn, social_nudge, break_suggest, bedtime_approach), manages escalation states, and delivers nudges
- `_deliver_nudge()` — Delivers a nudge via TTS priority queue with persona routing through the dispatcher
- `_is_snoozed()` — Returns True if all nudges are currently snoozed
- `_get_active_zones()` — Returns list of currently active FP2 zones
- `_clear_escalation()` — Resets escalation level for a specific nudge type

## State Dependencies

- `input_boolean.ai_focus_guard_enabled` — Kill switch
- `input_boolean.ai_focus_mode` — When ON, suppresses non-critical nudges (only P1 calendar warnings pass through)
- `input_number.ai_focus_guard_threshold_hours` — Workshop time before first nudge (default: 2h)
- `input_number.ai_focus_meal_reminder_hours` — Hours since last meal before nudge (default: 4h)
- `input_number.ai_focus_nudge_cooldown_minutes` — Cooldown between nudges of the same type (default: 30 min)
- `input_number.ai_focus_social_nudge_minutes` — Partner present time before social nudge (default: 30 min)
- `input_number.ai_focus_break_suggest_hours` — Hours in same zone before break suggestion (default: 2h)
- `input_number.ai_focus_bedtime_approach_minutes` — Minutes before bedtime to start nudging (default: 60 min)
- `input_datetime.ai_last_meal_time` — Timestamp of last meal
- `input_datetime.ai_context_bed_time` — Configured bedtime for bedtime approach nudge
- `input_datetime.ai_focus_guard_snooze_until` — Snooze expiry timestamp
- `binary_sensor.fp2_presence_sensor_*` — FP2 zone sensors (workshop, living room, main room, kitchen, bathroom, shower, bed, lobby). Configured via `entity_config.yaml` `fp2_zones` with hardcoded defaults as fallback.
- `input_text.ai_calendar_today_summary` — Calendar data for appointment proximity checks
- `person.miquel` / `person.jessica` — Home/away state for social nudge

## Package Pairing

Pairs with `packages/ai_focus_guard.yaml` which defines the kill switch, focus mode toggle, threshold helpers, snooze datetime, and the `sensor.ai_focus_guard_status` result entity.

## Called By

- **Self-triggered** — 15-minute cron, FP2 zone state changes, and startup
- **Voice commands** — "I just ate" triggers `focus_guard_mark_meal`, "Remind me in 30 minutes" triggers `focus_guard_snooze`
- **Dashboard** — kill switch and status display

## Notes

- 6 nudge types with independent escalation chains: `time_check` (P4-P3-P2), `meal_reminder` (P4-P3-P2), `calendar_warn` (P3-P2-P1), `social_nudge` (P4-P3), `break_suggest` (P4 only), `bedtime_approach` (P3-P2-P1).
- Escalation is time-based: each nudge type tracks its own escalation level. Moving to a new zone resets some escalations (break_suggest). Marking a meal resets meal_reminder.
- Focus mode suppression: when `ai_focus_mode` is ON, only P1 (critical calendar) nudges pass through. All others are silently skipped.
- Snooze is global: `focus_guard_snooze` suppresses all non-critical nudges for the specified duration.
- Workshop tracking: the module maintains `_workshop_entry_time` as module-level state to calculate continuous workshop duration without relying on entity history.
- Social nudge logic: requires partner to be `home` for 30+ minutes AND user to be in a solo zone (workshop, bathroom). Designed to gently remind users to spend time with their partner.
- Nudge delivery routes through the agent dispatcher for persona-appropriate TTS and uses the priority queue to respect ongoing conversations.
- Nudge patterns are logged to L2 memory for retrospective analysis of ADHD patterns and nudge effectiveness.
