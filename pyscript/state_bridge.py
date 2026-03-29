"""
State Bridge — generic bridge for blueprints to write state.set() sensors.

Blueprints cannot call state.set() directly.  This module exposes a thin
pyscript service (pyscript.set_sensor_value) that any blueprint or automation
can call to create/update a pyscript-managed sensor.

Usage from a blueprint action:
    - action: pyscript.set_sensor_value
      data:
        entity_id: sensor.ai_my_thing
        value: "hello"
        attrs_json: '{"detail": "world"}'
        icon: mdi:brain
        friendly_name: AI My Thing
"""

import json as _json  # noqa: F811 — shadow-safe alias


@service  # noqa: F821
async def set_sensor_value(
    entity_id: str = "",
    value: str = "",
    attrs_json: str = "",
    icon: str = "",
    friendly_name: str = "",
):
    """
    yaml
    name: Set Sensor Value
    description: >-
      Generic bridge — creates or updates a pyscript-managed sensor via
      state.set().  Blueprints and automations can call this instead of
      needing their own pyscript bridge service.
    fields:
      entity_id:
        name: Entity ID
        description: "Full entity ID, e.g. sensor.ai_my_thing"
        required: true
        selector:
          text:
      value:
        name: Value
        description: "State value to set"
        required: true
        selector:
          text:
      attrs_json:
        name: Attributes JSON
        description: >-
          Optional JSON string of extra attributes to merge.
          Existing attributes are preserved; only keys present in the
          JSON are overwritten.
        required: false
        selector:
          text:
      icon:
        name: Icon
        description: "Optional MDI icon, e.g. mdi:brain"
        required: false
        selector:
          icon:
      friendly_name:
        name: Friendly Name
        description: "Optional friendly name for the sensor"
        required: false
        selector:
          text:
    """
    if not entity_id:
        log.error("state_bridge: entity_id is required")  # noqa: F821
        return

    if not entity_id.startswith("sensor."):
        log.error(  # noqa: F821
            "state_bridge: entity_id must start with 'sensor.' — got %s",
            entity_id,
        )
        return

    # Build attributes — preserve existing, merge new
    try:
        existing_attrs = dict(state.getattr(entity_id) or {})  # noqa: F821
    except Exception:
        existing_attrs = {}

    if attrs_json:
        try:
            new_attrs = _json.loads(attrs_json)
            if isinstance(new_attrs, dict):
                existing_attrs.update(new_attrs)
            else:
                log.warning(  # noqa: F821
                    "state_bridge: attrs_json must be a JSON object — got %s",
                    type(new_attrs).__name__,
                )
        except _json.JSONDecodeError as exc:
            log.warning("state_bridge: invalid attrs_json — %s", exc)  # noqa: F821

    if icon:
        existing_attrs["icon"] = icon
    if friendly_name:
        existing_attrs["friendly_name"] = friendly_name

    state.set(entity_id, value, new_attributes=existing_attrs)  # noqa: F821
    log.debug(  # noqa: F821
        "state_bridge: set %s = %s (attrs=%s)",
        entity_id,
        value,
        list(existing_attrs.keys()),
    )
