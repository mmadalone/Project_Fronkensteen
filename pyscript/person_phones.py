"""Person Phones: find each person's Companion App phone and its sensors.

Call detection, the hot context and sleep detection read a person's phone.
Those entity IDs depend on what the phone is called in the Companion App, so
hardcoding them broke on the first phone rename (v1.1.7) and never worked on
any other install.

Discovery follows each person's own device trackers. A Companion App tracker
shares a device with the app's sensors, and the app sets each sensor's
registry unique_id to "<webhook_id>_<key>" ("phone_state", "next_alarm",
"is_charging"). The key does not change when entities are renamed and does
not depend on the language the app runs in.

Publishes sensor.ai_person_phones:
  state               number of phones found
  phones              one dict per phone: person, device_id, tracker, and the
                      entity ID of each sensor key the phone has
  <key>_entities      every phone's entity for that key, for templates
"""

RESULT_ENTITY = "sensor.ai_person_phones"
# Companion App sensor keys the project reads. Adding a key here publishes it
# for every phone that has that sensor.
_APP_SENSOR_KEYS = ["phone_state", "next_alarm", "is_charging"]
# The entity registry reaches disk 10 s after a change while HA is running.
_REGISTRY_SETTLE_S = 20

_last_phones = None


@pyscript_executor  # noqa: F821
def _discover_phones(person_trackers, keys):
    """Match each person's Companion App trackers to the app's sensors.

    person_trackers: {person entity_id: [device_tracker entity_ids]}
    keys:            Companion App sensor keys to resolve

    Returns {"phones": [...], "<key>_entities": [...]}, or None when the
    registry cannot be read, so the caller keeps the previous result.
    """
    import orjson as _orjson

    try:
        with open("/config/.storage/core.entity_registry", "rb") as f:
            entities = _orjson.loads(f.read()).get("data", {}).get("entities", [])
    except Exception:
        return None

    by_entity_id = {}
    app_entities_by_device = {}
    for ent in entities:
        by_entity_id[ent.get("entity_id")] = ent
        device_id = ent.get("device_id")
        if device_id and ent.get("platform") == "mobile_app" and not ent.get("disabled_by"):
            app_entities_by_device.setdefault(device_id, []).append(ent)

    phones = []
    for person in sorted(person_trackers):
        seen_devices = set()
        for tracker in person_trackers[person]:
            entry = by_entity_id.get(tracker)
            if not entry or entry.get("platform") != "mobile_app":
                continue  # router and other non-app trackers have no app sensors
            device_id = entry.get("device_id")
            if not device_id or device_id in seen_devices:
                continue
            seen_devices.add(device_id)
            phone = {"person": person, "device_id": device_id, "tracker": tracker}
            for ent in app_entities_by_device.get(device_id, []):
                # The webhook ID is hex, so the key is everything after the
                # first underscore.
                _, _, key = (ent.get("unique_id") or "").partition("_")
                if key in keys:
                    phone[key] = ent.get("entity_id")
            phones.append(phone)

    result = {"phones": phones}
    for key in keys:
        result[f"{key}_entities"] = sorted({p[key] for p in phones if key in p})
    return result


def _person_trackers():
    """{person entity_id: [device_tracker entity_ids]} from the person entities."""
    trackers = {}
    for person in state.names("person"):  # noqa: F821
        try:
            attrs = state.getattr(person) or {}  # noqa: F821
        except NameError:
            continue
        trackers[person] = list(attrs.get("device_trackers") or [])
    return trackers


def _refresh(reason):
    """Discover and publish. Returns the result, or None if the registry was unreadable."""
    global _last_phones

    result = _discover_phones(_person_trackers(), _APP_SENSOR_KEYS)
    if result is None:
        log.warning(  # noqa: F821
            f"person_phones: entity registry unreadable ({reason}); keeping the previous result"
        )
        return None

    attrs = dict(result)
    attrs["friendly_name"] = "AI Person Phones"
    attrs["icon"] = "mdi:cellphone-link"
    state.set(RESULT_ENTITY, str(len(result["phones"])), new_attributes=attrs)  # noqa: F821

    if result["phones"] != _last_phones:
        found = [f"{p['person']} -> {p['tracker']}" for p in result["phones"]]
        log.info(  # noqa: F821
            f"person_phones: {len(found)} phone(s) after {reason}: {', '.join(found) or 'none'}"
        )
        _last_phones = result["phones"]
    return result


@time_trigger("startup")  # noqa: F821
def person_phones_startup():
    """Discover once HA has started; the person entities are loaded by then."""
    _refresh("startup")


@event_trigger("entity_registry_updated")  # noqa: F821
def person_phones_registry_changed(**kwargs):
    """Re-discover after entities are added, removed or renamed.

    Debounced: a burst of registry events (an integration setting up, a device
    rename touching every entity) yields one refresh, once the registry has
    been written to disk.
    """
    task.unique("person_phones_registry_refresh")  # noqa: F821
    task.sleep(_REGISTRY_SETTLE_S)  # noqa: F821
    _refresh("entity registry change")


@time_trigger("cron(23 * * * *)")  # noqa: F821
def person_phones_hourly():
    """Catch trackers added to or removed from a person, which change no registry entry."""
    _refresh("hourly check")


@service(supports_response="optional")  # noqa: F821
def person_phones_refresh():
    """
    yaml
    name: Person Phones Refresh
    description: >-
      Re-discover each person's Companion App phone and its sensors now, and
      return what was published on sensor.ai_person_phones.
    """
    result = _refresh("service call")
    if result is None:
        return {"status": "error", "op": "person_phones_refresh",
                "error": "entity registry unreadable"}
    response = {"status": "ok", "op": "person_phones_refresh"}
    response.update(result)
    return response
