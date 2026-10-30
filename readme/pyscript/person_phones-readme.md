# Person Phones — Companion App Phone Discovery

Finds each person's Home Assistant Companion App phone and the entity IDs of the phone sensors Project Fronkensteen reads: call state, next alarm and charging. Call detection, the hot context and sleep detection all read from the sensor this module publishes, so no phone entity ID is written into any of them. Renaming a phone, or a second person installing the app, needs no edit anywhere.

## How phones are found

1. Each `person.*` entity lists its device trackers in its `device_trackers` attribute.
2. A tracker whose entity registry platform is `mobile_app` belongs to a Companion App device.
3. That device's other `mobile_app` entities are the app's sensors. The app sets each one's registry unique ID to `<webhook_id>_<key>`, and the key (`phone_state`, `next_alarm`, `is_charging`) identifies the sensor.

The key never changes when entities are renamed, and it doesn't depend on the language the app runs in, so discovery keeps working where matching on entity IDs would not. Router trackers (GL-iNet, ping, and so on) have no app device and are skipped. Disabled entities are skipped.

## Published sensor

`sensor.ai_person_phones`

| Field | Content |
|-------|---------|
| state | Number of phones found |
| `phones` | One entry per phone: `person`, `device_id`, `tracker`, plus `phone_state`, `next_alarm` and `is_charging` when the phone has that sensor |
| `phone_state_entities` | Every phone's call-state sensor |
| `next_alarm_entities` | Every phone's next-alarm sensor |
| `is_charging_entities` | Every phone's charging sensor |

Example, for one person with one phone:

```yaml
state: "1"
phones:
  - person: person.alex
    device_id: 4f1c...
    tracker: device_tracker.alex_phone
    phone_state: sensor.alex_phone_phone_state
    next_alarm: sensor.alex_phone_next_alarm
    is_charging: binary_sensor.alex_phone_is_charging
phone_state_entities: [sensor.alex_phone_phone_state]
next_alarm_entities: [sensor.alex_phone_next_alarm]
is_charging_entities: [binary_sensor.alex_phone_is_charging]
```

The phone sensors must be enabled in the Companion App (Settings → Companion app → Manage sensors). A phone without a given sensor just lacks that key.

## Services

| Service | Parameters | Returns | Description |
|---------|-----------|---------|-------------|
| `pyscript.person_phones_refresh` | (none) | `{status, op, phones, phone_state_entities, next_alarm_entities, is_charging_entities}` | Re-discover now and return what was published. `supports_response="optional"` |

## Triggers

| Trigger | Function | Condition |
|---------|----------|-----------|
| `@time_trigger("startup")` | `person_phones_startup` | Discover once Home Assistant has started |
| `@event_trigger("entity_registry_updated")` | `person_phones_registry_changed` | Entities added, removed or renamed. Debounced: waits 20 s after the last event, because the registry reaches disk 10 s after a change |
| `@time_trigger("cron(23 * * * *)")` | `person_phones_hourly` | Catches trackers added to or removed from a person, which change no registry entry |

## Key Functions

- `_discover_phones()` — `@pyscript_executor`. Reads `/config/.storage/core.entity_registry` and matches trackers to app sensors. Returns `None` if the registry can't be read, and the previous result stays published.
- `_person_trackers()` — Reads `device_trackers` from every `person.*` entity.
- `_refresh()` — Discovers and publishes. Logs at info level only when the result changes. Republishing identical data doesn't change the sensor, so the hourly check doesn't write to the recorder.

## Package Pairing

No package of its own. `sensor.ai_person_phones` is seeded to `0` at startup by `state_bridge.py` and filled in by this module. `RESULT_ENTITY` registers the sensor with `system_health.py`.

## Called By

- **packages/ai_phone_call_detection.yaml** — template triggers over `phone_state_entities`: a call starts when any phone rings or goes offhook
- **packages/ai_context_hot.yaml** — "Next alarm" line from each phone's `next_alarm`; with two or more alarms, each line names the person
- **pyscript/presence_patterns.py** — `sleep_detect_log` adds the charging bonus when any phone in `is_charging_entities` is charging

## Notes

- A person with two Companion App devices (say, a phone and a tablet) gets two entries in `phones`.
- iOS devices are found the same way, but the iOS app has no call-state or next-alarm sensor, and reports charging through `battery_state` rather than `is_charging`. To publish another sensor, add its key to `_APP_SENSOR_KEYS`.
- Added in v1.1.8. It replaced phone entity IDs that were hardcoded in three files and broke when the maintainer's phone was renamed.
