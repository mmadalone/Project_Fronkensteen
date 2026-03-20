# AI Privacy Gate — Identity-Confidence Feature Gating

## Overview

The Privacy Gate suppresses personal automations when another household member
is likely home, based on identity confidence scoring. Jessica's confidence
gates Miquel's features; Miquel's gates Jessica's.

**Package:** `packages/ai_privacy_gate.yaml`
**Blueprint:** `blueprints/automation/madalone/privacy_gate_hysteresis.yaml`
**Deployed:** 2026-03-10
**Configurable tiers added:** 2026-03-11

---

## Architecture

```
Identity Confidence Sensor
        │
        ▼
┌──────────────────────────┐
│  Hysteresis Controller   │  ← 6 instances (3 tiers × 2 persons)
│  (blueprint)             │
│                          │
│  confidence >= suppress  │──► gate boolean ON  (features suppressed)
│  confidence <  reenable  │──► gate boolean OFF (features allowed)
└──────────────────────────┘
        │
        ▼
┌──────────────────────────┐
│  Consumer Blueprints     │  ← 22 gated blueprints
│                          │
│  privacy_tier input      │──► off / t1 / t2 / t3 (configurable)
│  conditions: privacy gate│──► checks gate boolean for selected tier
└──────────────────────────┘
```

## Three Tiers

| Tier | Label | Suppress At | Re-enable At | Features |
|------|-------|-------------|--------------|----------|
| **T1** | Intimate | 30 pts | 20 pts | bedtime/wake automations |
| **T2** | Personal | 40 pts | 30 pts | notifications, briefings, email |
| **T3** | Ambient  | 50 pts | 40 pts | detection, tracking, sensors |

Hysteresis gap (suppress > re-enable) prevents flapping near the threshold.

---

## Helpers

### Global Controls

| Helper | Type | Purpose |
|--------|------|---------|
| `input_boolean.ai_privacy_gate_enabled` | boolean | Master kill switch |
| `input_select.ai_privacy_gate_mode` | select | `auto` / `force_suppress_all` / `force_allow_all` |

### Per-Person Per-Tier Gate Booleans

Set automatically by the hysteresis blueprint instances.

| Helper | Person | Tier |
|--------|--------|------|
| `input_boolean.ai_privacy_gate_miquel_t1_suppressed` | Miquel | T1 |
| `input_boolean.ai_privacy_gate_miquel_t2_suppressed` | Miquel | T2 |
| `input_boolean.ai_privacy_gate_miquel_t3_suppressed` | Miquel | T3 |
| `input_boolean.ai_privacy_gate_jessica_t1_suppressed` | Jessica | T1 |
| `input_boolean.ai_privacy_gate_jessica_t2_suppressed` | Jessica | T2 |
| `input_boolean.ai_privacy_gate_jessica_t3_suppressed` | Jessica | T3 |

### Per-Person Per-Tier Thresholds

| Suppress At | Re-enable At | Person | Tier |
|-------------|--------------|--------|------|
| `input_number.ai_privacy_gate_miquel_t1_suppress_at` | `input_number.ai_privacy_gate_miquel_t1_reenable_at` | Miquel | T1 |
| `input_number.ai_privacy_gate_miquel_t2_suppress_at` | `input_number.ai_privacy_gate_miquel_t2_reenable_at` | Miquel | T2 |
| `input_number.ai_privacy_gate_miquel_t3_suppress_at` | `input_number.ai_privacy_gate_miquel_t3_reenable_at` | Miquel | T3 |
| `input_number.ai_privacy_gate_jessica_t1_suppress_at` | `input_number.ai_privacy_gate_jessica_t1_reenable_at` | Jessica | T1 |
| `input_number.ai_privacy_gate_jessica_t2_suppress_at` | `input_number.ai_privacy_gate_jessica_t2_reenable_at` | Jessica | T2 |
| `input_number.ai_privacy_gate_jessica_t3_suppress_at` | `input_number.ai_privacy_gate_jessica_t3_reenable_at` | Jessica | T3 |

### Per-Feature Overrides

Each gated feature has its own override selector with options:
`auto` / `force_suppress` / `force_allow` / `off`

| Helper | Feature | Default Tier |
|--------|---------|--------------|
| `input_select.ai_privacy_gate_wake_up_guard` | Wake-Up Guard | T1 |
| `input_select.ai_privacy_gate_calendar_alarm` | Calendar Alarm | T1 |
| `input_select.ai_privacy_gate_escalating_wakeup` | Escalating Wake-Up | T1 |
| `input_select.ai_privacy_gate_bedtime_routine` | Bedtime Routine | T1 |
| `input_select.ai_privacy_gate_bedtime_routine_plus` | Bedtime Routine Plus | T1 |
| `input_select.ai_privacy_gate_bedtime_last_call` | Bedtime Last Call | T1 |
| `input_select.ai_privacy_gate_email_follow_me` | Email Follow-Me | T2 |
| `input_select.ai_privacy_gate_notification_follow_me` | Notification Follow-Me | T2 |
| `input_select.ai_privacy_gate_email_priority_filter` | Email Priority Filter | T2 |
| `input_select.ai_privacy_gate_proactive_briefing` | Proactive Briefing | T2 |
| `input_select.ai_privacy_gate_proactive_unified` | Proactive Unified | T2 |
| `input_select.ai_privacy_gate_phone_charge_reminder` | Phone Charge Reminder | T2 |
| `input_select.ai_privacy_gate_bedtime_escalation` | Bedtime Escalation | T2 |
| `input_select.ai_privacy_gate_calendar_pre_event` | Calendar Pre-Event | T2 |
| `input_select.ai_privacy_gate_llm_alarm` | LLM Alarm | T2 |
| `input_select.ai_privacy_gate_voice_handoff` | Voice Handoff | T2 |
| `input_select.ai_privacy_gate_meal_detection` | Meal Detection | T3 |
| `input_select.ai_privacy_gate_sleep_detection` | Sleep Detection | T3 |
| `input_select.ai_privacy_gate_memory_todo_mirror` | Memory Todo Mirror | T3 |
| `input_select.ai_privacy_gate_interaction_summarizer` | Interaction Summarizer | T3 |
| `input_select.ai_privacy_gate_proactive_llm_sensors` | Proactive LLM Sensors | T3 |
| `input_select.ai_privacy_gate_dispatcher_profile` | Dispatcher Profile | Off |
| `input_select.ai_privacy_gate_sleep_lights` | Sleep Lights | Off |
| `input_select.ai_privacy_gate_media_tracking` | Media Tracking | Off |
| `input_select.ai_privacy_gate_refcount_watchdog` | Refcount Watchdog | Off |
| `input_select.ai_privacy_gate_coming_home` | Coming Home | Off |

---

## Hysteresis Blueprint Setup

### Instance Configuration (6 required)

Create 6 automation instances of `privacy_gate_hysteresis.yaml`, one for each
person + tier combination.

#### Miquel Instances (watch Jessica's confidence)

| Instance Name | Confidence Sensor | Suppress-at Helper | Re-enable-at Helper | Gate Boolean |
|---------------|-------------------|-------------------|---------------------|--------------|
| Privacy Gate — Miquel T1 | `sensor.identity_confidence_jessica` | `input_number.ai_privacy_gate_miquel_t1_suppress_at` | `input_number.ai_privacy_gate_miquel_t1_reenable_at` | `input_boolean.ai_privacy_gate_miquel_t1_suppressed` |
| Privacy Gate — Miquel T2 | `sensor.identity_confidence_jessica` | `input_number.ai_privacy_gate_miquel_t2_suppress_at` | `input_number.ai_privacy_gate_miquel_t2_reenable_at` | `input_boolean.ai_privacy_gate_miquel_t2_suppressed` |
| Privacy Gate — Miquel T3 | `sensor.identity_confidence_jessica` | `input_number.ai_privacy_gate_miquel_t3_suppress_at` | `input_number.ai_privacy_gate_miquel_t3_reenable_at` | `input_boolean.ai_privacy_gate_miquel_t3_suppressed` |

#### Jessica Instances (watch Miquel's confidence)

| Instance Name | Confidence Sensor | Suppress-at Helper | Re-enable-at Helper | Gate Boolean |
|---------------|-------------------|-------------------|---------------------|--------------|
| Privacy Gate — Jessica T1 | `sensor.identity_confidence_miquel` | `input_number.ai_privacy_gate_jessica_t1_suppress_at` | `input_number.ai_privacy_gate_jessica_t1_reenable_at` | `input_boolean.ai_privacy_gate_jessica_t1_suppressed` |
| Privacy Gate — Jessica T2 | `sensor.identity_confidence_miquel` | `input_number.ai_privacy_gate_jessica_t2_suppress_at` | `input_number.ai_privacy_gate_jessica_t2_reenable_at` | `input_boolean.ai_privacy_gate_jessica_t2_suppressed` |
| Privacy Gate — Jessica T3 | `sensor.identity_confidence_miquel` | `input_number.ai_privacy_gate_jessica_t3_suppress_at` | `input_number.ai_privacy_gate_jessica_t3_reenable_at` | `input_boolean.ai_privacy_gate_jessica_t3_suppressed` |

All instances use the same kill switch: `input_boolean.ai_privacy_gate_enabled` (default).

---

## Consumer Blueprint — Privacy Tier Input

All 22 gated blueprints include a configurable `privacy_tier` input in a
collapsed "Privacy" section:

```yaml
privacy_tier:
  name: Privacy gate tier
  description: >
    Which privacy tier this feature belongs to.
    Off = no privacy gating.
  default: "t1"        # ← varies per blueprint: t1, t2, t3, or off
  selector:
    select:
      options:
        - "Off — no privacy gating"    → off
        - "T1 — Intimate (bedtime/wake)" → t1
        - "T2 — Personal (notifications/briefings)" → t2
        - "T3 — Ambient (detection/tracking)" → t3
```

The condition template in each blueprint:

```jinja2
{%- set tier = privacy_tier -%}
{%- set mode = states('input_select.ai_privacy_gate_mode') -%}
{%- set override = states('input_select.ai_privacy_gate_FEATURE') -%}
{%- if tier == 'off'
    or not is_state('input_boolean.ai_privacy_gate_enabled', 'on')
    or mode == 'force_allow_all' or override == 'force_allow'
    or override == 'off' -%}
  true
{%- elif mode == 'force_suppress_all' or override == 'force_suppress' -%}
  false
{%- else -%}
  {{ is_state('input_boolean.ai_privacy_gate_miquel_' ~ tier ~ '_suppressed', 'off') }}
{%- endif -%}
```

Moving a feature between tiers is a **UI-only change** — edit the automation
instance and change the tier selector. No YAML edits required.

---

## Gated Blueprints (22)

| Blueprint | FEATURE key | Default Tier |
|-----------|-------------|--------------|
| `wake-up-guard.yaml` | wake_up_guard | T1 |
| `calendar_alarm.yaml` | calendar_alarm | T1 |
| `escalating_wakeup_guard.yaml` | escalating_wakeup | T1 |
| `bedtime_routine.yaml` | bedtime_routine | T1 |
| `bedtime_routine_plus.yaml` | bedtime_routine_plus | T1 |
| `bedtime_last_call.yaml` | bedtime_last_call | T1 |
| `email_follow_me.yaml` | email_follow_me | T2 |
| `notification_follow_me.yaml` | notification_follow_me | T2 |
| `email_priority_filter.yaml` | email_priority_filter | T2 |
| `proactive_briefing.yaml` | proactive_briefing | T2 |
| `proactive_unified.yaml` | proactive_unified | T2 |
| `phone_charge_reminder.yaml` | phone_charge_reminder | T2 |
| `proactive_bedtime_escalation.yaml` | bedtime_escalation | T2 |
| `calendar_pre_event_reminder.yaml` | calendar_pre_event | T2 |
| `llm_alarm.yaml` | llm_alarm | T2 |
| `voice_handoff.yaml` | voice_handoff | T2 |
| `proactive_llm_sensors.yaml` | proactive_llm_sensors | T3 |
| `dispatcher_profile.yaml` | dispatcher_profile | Off |
| `sleep_lights.yaml` | sleep_lights | Off |
| `media_tracking.yaml` | media_tracking | Off |
| `follow_me_refcount_watchdog.yaml` | refcount_watchdog | Off |
| `coming_home.yaml` | coming_home | Off |

### Special Cases

- **voice_handoff.yaml** — Has both a top-level gate (suppresses the entire
  automation) AND a commentary-level gate (step 6, suppresses commentary only).
  Both use the same `privacy_tier` input.
- **dispatcher_profile.yaml** — Had no `conditions:` block. A new one was
  inserted between `trigger:` and `action:`.
- **Off-default blueprints** (5) — Gate is inert by default. Set tier to
  T1/T2/T3 in the automation UI to activate gating.

---

## Template Sensor

`sensor.ai_privacy_gate_status` provides a live dashboard view:

- **State:** Count of currently suppressed features
- **Attributes:**
  - `mode` — current gate mode
  - `miquel_t1` / `miquel_t2` / `miquel_t3` — `suppressed` or `allowed`
  - `jessica_t1` / `jessica_t2` / `jessica_t3` — `suppressed` or `allowed`
  - `jessica_confidence` / `miquel_confidence` — current scores
  - `features` — JSON map of every feature → `suppressed` / `allowed`

Features with `tier: off` in the sensor map always resolve to `allowed`
regardless of override or gate boolean state.

---

## Blueprint-Level Identity Gate (proactive_unified)

In addition to the privacy gate, `proactive_unified.yaml` has its own identity
confidence gate that requires `max(identity_confidence_miquel,
identity_confidence_jessica) >= threshold` before speaking. This is separate from
the privacy gate — it ensures *someone known* is home, not just that the *other*
person isn't.

| Input | Default | Effect |
|-------|---------|--------|
| `identity_confidence_threshold` | 50 pts | Minimum identity confidence from any known user. Set to 0 to disable. |

**Interaction with privacy gate:** Both gates must pass. The identity gate checks
"is anyone identified?" while the privacy gate checks "should personal features
be suppressed because the *other* person is home?" They are independent conditions
evaluated in sequence.

**Open item:** GPS secondary score (30 pts) alone cannot pass the default 50 pt
gate. When WiFi is off, identity drops to GPS-only and all proactive nags silently
fail. Score tiers in `ai_identity.yaml` should be revisited to give GPS enough
weight to pass alone.

---

## Evaluation Order (condition logic)

```
1. tier == 'off'              → ALLOW (bypass entirely)
2. kill switch OFF             → ALLOW
3. mode == 'force_allow_all'   → ALLOW
4. override == 'force_allow'   → ALLOW
5. override == 'off'           → ALLOW
6. mode == 'force_suppress_all' → SUPPRESS
7. override == 'force_suppress' → SUPPRESS
8. gate boolean for tier        → ALLOW if OFF, SUPPRESS if ON
```
