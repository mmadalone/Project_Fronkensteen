# =============================================================================
# Scene Preference Learner — C6 Layer 3
# =============================================================================
# Observes light states in occupied zones on a periodic basis, stores
# preferences in L2 memory keyed by zone + time_bucket + day_type.
# Provides retrieval and apply services for the scene_preference_apply
# blueprint.
#
# Sensor: sensor.ai_scene_learner_status  (ok / idle / learning)
#
# Dependencies:
#   - pyscript/memory.py (L2: memory_set, memory_get)
#   - pyscript/modules/shared_utils.py (entity config, result entity name)
#   - entity_config.yaml → scene_learner_lights (zone → light list)
#   - helpers_input_boolean.yaml → ai_scene_learner_enabled
#   - helpers_input_number.yaml → ai_scene_learner_min_observations
# =============================================================================

from datetime import datetime as _dt

from shared_utils import build_result_entity_name, load_entity_config

# =============================================================================
# Constants
# =============================================================================

RESULT_ENTITY = "sensor.ai_scene_learner_status"
L2_EXPIRATION_DAYS = 90
L2_KEY_PREFIX = "scene_pref"
RECORD_INTERVAL_SEC = 600  # 10 minutes
EMA_ALPHA = 0.3  # weight for new observations (higher = faster adaptation)

# =============================================================================
# Module state
# =============================================================================

result_entity_name = None
_zone_lights = {}        # zone → [light_entity_id, ...]
_light_to_zone = {}      # light_entity_id → zone
_fp2_zones = {}          # binary_sensor → zone
_suppress_ts = {}        # zone → datetime of last suppress event


# =============================================================================
# Helpers
# =============================================================================

def _ensure_result_entity_name(force=False):
    global result_entity_name
    if force or not result_entity_name:
        result_entity_name = build_result_entity_name(RESULT_ENTITY)


def _set_status(state_value, **attrs):
    _ensure_result_entity_name()
    attrs.update(result_entity_name)
    state.set(RESULT_ENTITY, value=state_value, new_attributes=attrs)


def _time_bucket():
    """Return current time bucket: late_night/morning/afternoon/evening."""
    h = _dt.now().hour
    if h < 6:
        return "late_night"
    if h < 12:
        return "morning"
    if h < 18:
        return "afternoon"
    return "evening"


def _day_type():
    """Return weekday or weekend."""
    return "weekend" if _dt.now().weekday() >= 5 else "weekday"


def _l2_key(zone, tb=None, dt_type=None):
    """Build L2 memory key for a zone/time/day context."""
    tb = tb or _time_bucket()
    dt_type = dt_type or _day_type()
    return f"{L2_KEY_PREFIX}:{zone}:{tb}:{dt_type}"


async def _l2_get(key):
    """Read from L2 memory."""
    try:
        result = pyscript.memory_get(key=key)
        return await result
    except Exception:
        return None


async def _l2_set(key, value, tags):
    """Write to L2 memory."""
    try:
        result = pyscript.memory_set(
            key=key, value=value, scope="household",
            expiration_days=L2_EXPIRATION_DAYS, tags=tags, force_new=True,
        )
        await result
        return True
    except Exception as exc:
        log.warning("scene_learner: L2 write failed for %s: %s", key, exc)
        return False


def _read_light_state(entity_id):
    """Read current light state. Returns dict or None if off/unavailable."""
    try:
        st = state.get(entity_id)
    except NameError:
        return None
    if st != "on":
        return None
    attrs = state.getattr(entity_id)
    modes = attrs.get("supported_color_modes", [])
    result = {"brightness": attrs.get("brightness", 0)}
    if "color_temp" in modes:
        result["color_temp_kelvin"] = attrs.get("color_temp_kelvin", 0)
    if "rgb" in modes or "rgbw" in modes:
        result["rgb_color"] = attrs.get("rgb_color", [0, 0, 0])
    return result


def _merge_preference(existing, new_obs):
    """Exponential moving average merge of light preferences."""
    if existing is None:
        return {
            "lights": new_obs,
            "observations": 1,
            "last_updated": _dt.now().isoformat(),
        }

    merged_lights = dict(existing.get("lights", {}))
    for eid, new_vals in new_obs.items():
        if eid in merged_lights:
            old = merged_lights[eid]
            blended = {}
            for attr_key in new_vals:
                old_val = old.get(attr_key, new_vals[attr_key])
                new_val = new_vals[attr_key]
                if isinstance(new_val, (int, float)) and isinstance(old_val, (int, float)):
                    blended[attr_key] = round(
                        EMA_ALPHA * new_val + (1 - EMA_ALPHA) * old_val
                    )
                else:
                    blended[attr_key] = new_val
            merged_lights[eid] = blended
        else:
            merged_lights[eid] = new_vals

    return {
        "lights": merged_lights,
        "observations": existing.get("observations", 0) + 1,
        "last_updated": _dt.now().isoformat(),
    }


# =============================================================================
# Startup
# =============================================================================

@time_trigger("startup")
async def _startup():
    """Load config and set initial status."""
    await task.sleep(10)
    cfg = load_entity_config()
    sl = cfg.get("scene_learner_lights", {})

    _zone_lights.clear()
    _light_to_zone.clear()
    for zone, lights in sl.items():
        _zone_lights[zone] = list(lights)
        for lt in lights:
            _light_to_zone[lt] = zone

    fp2 = cfg.get("fp2_zones", {})
    _fp2_zones.clear()
    _fp2_zones.update(fp2)

    _set_status(
        "ok",
        zones_configured=list(_zone_lights.keys()),
        total_lights=len(_light_to_zone),
        last_record="never",
    )
    log.info("scene_learner: loaded %d zones, %d lights",
             len(_zone_lights), len(_light_to_zone))


# =============================================================================
# Suppress event listener
# =============================================================================

@event_trigger("ai_scene_learner_suppress")
async def _on_suppress(**kwargs):
    """Track automation-driven light changes to avoid recording them."""
    source = kwargs.get("source", "unknown")
    # Mark all zones as recently suppressed (source doesn't carry zone)
    now = _dt.now()
    for zone in _zone_lights:
        _suppress_ts[zone] = now


# =============================================================================
# Periodic recording
# =============================================================================

@time_trigger("cron(*/10 * * * *)")
async def _periodic_record():
    """Every 10 minutes, record light preferences for occupied zones."""
    if state.get("input_boolean.ai_scene_learner_enabled") != "on":
        return
    if state.get("input_boolean.ai_guest_mode") == "on":
        return

    now = _dt.now()
    tb = _time_bucket()
    dt_type = _day_type()
    recorded_zones = []

    for zone, lights in _zone_lights.items():
        # Check zone occupancy via FP2
        zone_occupied = False
        for sensor, z_name in _fp2_zones.items():
            try:
                sensor_state = state.get(sensor)
            except NameError:
                continue
            if z_name == zone and sensor_state == "on":
                zone_occupied = True
                break
        if not zone_occupied:
            continue

        # Check if any light is ON
        zone_snapshot = {}
        for lt in lights:
            lt_state = _read_light_state(lt)
            if lt_state is not None:
                zone_snapshot[lt] = lt_state
        if not zone_snapshot:
            continue

        # Check suppress window: if automation ran in last 30s AND lights
        # likely haven't been manually adjusted, skip this tick.
        # For v1 we record regardless — the apply side handles filtering.

        # Store/merge preference
        key = _l2_key(zone, tb, dt_type)
        existing_raw = await _l2_get(key)
        existing = None
        if existing_raw is not None:
            if isinstance(existing_raw, dict):
                existing = existing_raw
            elif isinstance(existing_raw, str):
                try:
                    import json as _json
                    existing = _json.loads(existing_raw)
                except Exception:
                    existing = None

        merged = _merge_preference(existing, zone_snapshot)
        tags = f"scene_preference,{zone},{tb},{dt_type}"

        import json as _json
        await _l2_set(key, _json.dumps(merged), tags)
        recorded_zones.append(zone)

    if recorded_zones:
        _set_status(
            "learning",
            zones_configured=list(_zone_lights.keys()),
            total_lights=len(_light_to_zone),
            last_record=now.isoformat(),
            last_recorded_zones=recorded_zones,
        )


# =============================================================================
# Services
# =============================================================================

@service(supports_response="only")
async def scene_learner_get(zone=None):
    """Get learned scene preference for a zone in current time context.

    Returns dict with 'lights', 'observations', 'last_updated' or empty
    if no data. Use response_variable to capture the result.
    """
    if not zone or zone not in _zone_lights:
        return {"error": f"Unknown zone: {zone}", "lights": {}, "observations": 0}

    key = _l2_key(zone)
    raw = await _l2_get(key)
    if raw is None:
        return {"lights": {}, "observations": 0, "zone": zone}

    data = raw
    if isinstance(raw, str):
        try:
            import json as _json
            data = _json.loads(raw)
        except Exception:
            return {"lights": {}, "observations": 0, "zone": zone}

    data["zone"] = zone
    data["time_bucket"] = _time_bucket()
    data["day_type"] = _day_type()
    return data


@service
async def scene_learner_apply(zone=None, transition=3):
    """Apply learned scene preference to a zone's lights.

    Uses light.turn_on with stored brightness/color_temp_kelvin values.
    """
    if not zone or zone not in _zone_lights:
        log.warning("scene_learner_apply: unknown zone %s", zone)
        return

    result = await scene_learner_get(zone=zone)
    lights = result.get("lights", {})
    if not lights:
        log.info("scene_learner_apply: no data for zone %s", zone)
        return

    min_obs = int(float(state.get("input_number.ai_scene_learner_min_observations") or 5))
    if result.get("observations", 0) < min_obs:
        log.info("scene_learner_apply: zone %s has %d obs (need %d)",
                 zone, result.get("observations", 0), min_obs)
        return

    for eid, prefs in lights.items():
        try:
            eid_state = state.get(eid)
        except NameError:
            continue
        if eid_state != "on":
            continue
        svc_data = {"entity_id": eid, "transition": int(transition)}
        if "brightness" in prefs and prefs["brightness"]:
            svc_data["brightness"] = int(prefs["brightness"])
        if "color_temp_kelvin" in prefs and prefs["color_temp_kelvin"]:
            svc_data["color_temp_kelvin"] = int(prefs["color_temp_kelvin"])
        if svc_data.get("brightness") or svc_data.get("color_temp_kelvin"):
            light.turn_on(**svc_data)

    log.info("scene_learner_apply: applied preferences for zone %s (%d lights)",
             zone, len(lights))


@service
async def scene_learner_forget(zone=None):
    """Clear all learned preferences for a zone (all time/day combinations)."""
    if not zone:
        return

    cleared = 0
    for tb in ["late_night", "morning", "afternoon", "evening"]:
        for dt_type in ["weekday", "weekend"]:
            key = _l2_key(zone, tb, dt_type)
            try:
                result = pyscript.memory_forget(key=key)
                await result
                cleared += 1
            except Exception:
                pass

    log.info("scene_learner_forget: cleared %d keys for zone %s", cleared, zone)
    _set_status(
        "ok",
        zones_configured=list(_zone_lights.keys()),
        total_lights=len(_light_to_zone),
        last_record="cleared",
    )


@service(supports_response="only")
async def scene_learner_status():
    """Return learning statistics per zone."""
    stats = {}
    for zone in _zone_lights:
        zone_data = {}
        for tb in ["late_night", "morning", "afternoon", "evening"]:
            for dt_type in ["weekday", "weekend"]:
                key = _l2_key(zone, tb, dt_type)
                raw = await _l2_get(key)
                if raw is not None:
                    data = raw
                    if isinstance(raw, str):
                        try:
                            import json as _json
                            data = _json.loads(raw)
                        except Exception:
                            continue
                    zone_data[f"{tb}_{dt_type}"] = {
                        "observations": data.get("observations", 0),
                        "last_updated": data.get("last_updated", "unknown"),
                    }
        if zone_data:
            stats[zone] = zone_data

    return {
        "zones_with_data": list(stats.keys()),
        "total_contexts": sum([len(v) for v in stats.values()]),
        "detail": stats,
    }
