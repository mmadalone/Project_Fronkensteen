![Calendar Pre-Event Reminder -- TTS Announcement](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/calendar_pre_event_reminder-header.jpeg)

# Calendar Pre-Event Reminder -- TTS Announcement

Announces upcoming calendar events before they start using a calendar trigger with configurable offset. Uses `dedup_announce` to prevent duplicate announcements from overlapping systems. Gated by kill switch, presence, and privacy tier.

## How It Works

```
calendar entity
        |
        v
+---------------------+
| Calendar trigger     |
| (event start -       |
|  offset)             |
+---------------------+
        |
        v
+---------------------+
| Kill switch ON?     |
+---------------------+
        |
        v
+---------------------+
| Someone home?       |
| (presence entities) |
+---------------------+
        |
        v
+---------------------+
| Privacy gate        |
+---------------------+
        |
        v
+---------------------+
| Dispatch agent      |
| (optional)          |
+---------------------+
        |
        v
+---------------------+
| Announce via dedup  |
| or direct TTS       |
+---------------------+
```

## Features

- Calendar trigger with configurable offset (5 min, 10 min, 15 min, 30 min, 1 hour, or custom)
- Duplicate announcement prevention via `pyscript.dedup_announce`
- Presence gating with multi-entity support (device_tracker and person entities)
- Agent dispatcher integration for context-appropriate TTS engine selection
- Fallback to `tts.home_assistant_cloud` when dispatcher is disabled
- Privacy gate with tiered suppression (T2 personal by default)
- Kill switch for easy enable/disable without removing the automation

## Prerequisites

- Home Assistant 2024.10.0+
- Calendar entity (e.g., Google Calendar integration)
- `input_boolean` entity for kill switch
- `pyscript/agent_dispatcher.py` (if dispatcher enabled)
- `pyscript/tts_queue.py` (TTS playback)
- `pyscript/dedup_announce.py` (if dedup enabled)

## Installation

1. Copy `calendar_pre_event_reminder.yaml` to `config/blueprints/automation/madalone/`
2. Create automation: **Settings -> Automations -> Create -> Use Blueprint**

## Configuration

<details><summary>① Calendar Source</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `calendar_entity` | _(empty)_ | Calendar entity to monitor for upcoming events |
| `reminder_offset` | `-0:15:00` | How long before the event to fire (negative duration string) |

</details>

<details><summary>② Presence Gate</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `presence_entities` | `[]` | Device trackers or person entities. At least one must be "home" |

</details>

<details><summary>③ TTS Delivery</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `use_dedup` | `true` | Use dedup_announce to prevent duplicate announcements |
| `use_dispatcher` | `true` | Use agent dispatcher for TTS engine selection |
| `kill_switch` | _(empty)_ | Input boolean to enable/disable the reminder |

</details>

<details><summary>④ Notification Threshold</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `enable_notify_threshold` | `false` | Gate TTS against the active user's notification threshold preference |
| `tts_priority` | `2` | TTS queue priority (0=emergency, 1=alert, 2=normal, 3=low, 4=ambient) |

</details>

<details><summary>⑤ Privacy</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `privacy_tier` | `t2` | Privacy gate tier (off/t1/t2/t3) |
| `privacy_gate_enabled` | `input_boolean.ai_privacy_gate_enabled` | Privacy gate toggle |
| `privacy_gate_mode` | `input_select.ai_privacy_gate_mode` | Privacy gate mode selector |
| `privacy_gate_person` | `person.miquel` | Person entity for tier suppression lookups |

</details>

## Technical Notes

- **Mode:** `single` (silent on exceeded) -- one reminder at a time
- **Announcement text:** Generated from the calendar event summary: "Hey, heads up -- you've got {event_name} coming up soon."
- **Dedup topic:** Based on slugified event name (`calendar_event_{slug}`) to prevent repeats of the same event
- **TTS routing:** When dedup is enabled, uses presence-based targeting (`target_mode: presence`). When disabled, uses direct `tts_queue_speak` at priority 2
- **Offset format:** Must be a negative duration string (e.g., `-0:15:00`). The selector provides common presets with custom value support

## Changelog

- **v1:** Initial blueprint -- replaces automation from ai_calendar_promotion.yaml

## Author

**madalone**

## License

See repository for license details.
