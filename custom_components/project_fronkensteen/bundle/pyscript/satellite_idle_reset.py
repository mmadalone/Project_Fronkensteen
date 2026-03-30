"""Satellite Idle Reset — resets pipeline to era-correct persona.

Uses the dispatcher cache for satellite discovery and era resolution.
Trigger factory pattern (proven in duck_manager.py).

On startup: sets all satellites to the era-correct pipeline immediately.
On idle transition: resets pipeline after each conversation ends.
"""
import asyncio
from datetime import datetime


_idle_triggers = []


def _get_era():
    """Return current time-of-day era name."""
    hour = datetime.now().hour
    if 0 <= hour <= 5:
        return "late_night"
    if 6 <= hour <= 11:
        return "morning"
    if 12 <= hour <= 17:
        return "afternoon"
    return "evening"


def _get_era_display_name():
    """Resolve era persona to pipeline display name. Returns (display_name, era) or (None, era)."""
    era = _get_era()
    era_helper = "input_select.ai_dispatcher_era_" + era
    era_persona = (state.get(era_helper) or "").lower().strip()  # noqa: F821
    if not era_persona or era_persona in ("rotate", "unknown", "unavailable", "none", ""):
        return None, era

    try:
        disp_result = service.call(  # noqa: F821
            "pyscript", "agent_dispatch",
            pipeline_name=era_persona.capitalize(),
            return_response=True,
        )
        display_name = (disp_result or {}).get("pipeline_name", "")
    except Exception:
        return None, era

    return display_name or None, era


def _set_pipeline(select_entity, display_name):
    """Set the primary assistant slot on a satellite."""
    service.call(  # noqa: F821
        "select", "select_option",
        entity_id=select_entity, option=display_name,
    )


def _idle_trigger_factory(sat_entity, select_entity):
    """Create a state_trigger for a single satellite going idle."""
    trig_str = sat_entity + " == 'idle'"

    @state_trigger(trig_str)  # noqa: F821
    async def _on_idle(var_name=None, value=None, old_value=None):
        await _handle_idle(
            var_name=var_name, old_value=old_value,
            select_entity=select_entity,
        )
    return _on_idle


async def _handle_idle(var_name=None, old_value=None, select_entity=""):
    """Reset satellite pipeline to era-correct persona after conversation ends."""
    if state.get("input_boolean.ai_dispatcher_enabled") != "on":  # noqa: F821
        return
    if old_value in ("idle", "unknown", "unavailable", None, ""):
        return
    if not select_entity:
        return

    display_name, era = _get_era_display_name()
    if not display_name:
        return

    current = state.get(select_entity)  # noqa: F821
    if current == display_name:
        return

    _set_pipeline(select_entity, display_name)
    mac = (var_name or "").split(".")[-1]
    log.info(  # noqa: F821
        "satellite_idle_reset: %s idle -> pipeline reset to %s (%s)",
        mac, display_name, era,
    )


@time_trigger("startup")  # noqa: F821
async def _satellite_idle_startup():
    """Register triggers and set initial era-correct pipelines on all satellites."""
    global _idle_triggers
    await asyncio.sleep(25)

    if state.get("input_boolean.ai_dispatcher_enabled") != "on":  # noqa: F821
        log.info("satellite_idle_reset: dispatcher disabled, skipping")  # noqa: F821
        return

    try:
        result = service.call(  # noqa: F821
            "pyscript", "dispatcher_get_satellite_maps",
            return_response=True,
        )
    except Exception as exc:
        log.warning("satellite_idle_reset: dispatcher unavailable: %s", exc)  # noqa: F821
        return

    sat_map = (result or {}).get("satellite_select_map", {})
    if not sat_map:
        log.warning("satellite_idle_reset: no satellites found")  # noqa: F821
        return

    # Register idle triggers
    _idle_triggers = []
    for sat_entity in sat_map:
        sel = sat_map[sat_entity]
        _idle_triggers.append(_idle_trigger_factory(sat_entity, sel))

    # Initial pipeline set — push era-correct persona to all satellites now
    display_name, era = _get_era_display_name()
    set_count = 0
    if display_name:
        for sat_entity in sat_map:
            sel = sat_map[sat_entity]
            current = state.get(sel)  # noqa: F821
            if current != display_name:
                _set_pipeline(sel, display_name)
                set_count = set_count + 1

    log.info(  # noqa: F821
        "satellite_idle_reset: started for %d satellites, "
        "initial set %d to %s (%s)",
        len(_idle_triggers), set_count,
        display_name or "none", era,
    )
