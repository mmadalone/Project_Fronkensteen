"""I-48: Per-Person Room Identity Inference via Anchor-and-Track.

Uses FP2 mmWave zones, WiFi device trackers, voice satellite events,
and Markov priors to infer which person occupies which room. With N=2
residents, elimination logic resolves most ambiguity. Outputs per-person
location sensors with confidence scores and decay over time.
"""
import asyncio
import time
from datetime import datetime

from shared_utils import (
    build_result_entity_name,
    discover_persons,
    get_person_config,
    get_person_slugs,
    get_person_tracker,
    load_entity_config,
    reload_entity_config,
)

# =============================================================================
# Presence Identity — I-48 Per-Person Room Inference
# =============================================================================
# Anchor-and-Track algorithm: uses FP2 mmWave zones, WiFi device trackers,
# voice satellite events, and Markov priors to infer which person is in which
# room. With N=2 residents, elimination logic covers most scenarios.
#
# Services:
#   pyscript.presence_identity_status    — debug dump (supports_response="only")
#   pyscript.presence_identity_force_anchor — manual pin person→zone
#   pyscript.presence_identity_reset     — clear all tracking
#
# State triggers:
#   - 8 FP2 binary sensors → zone change processing
#   - 2 WiFi device trackers → arrival/departure anchoring
#   - input_text.ai_last_satellite → voice anchor
#
# Time triggers:
#   - cron(*/5 * * * *) → confidence decay tick
#   - startup → initialize zone state, anchor if solo
#
# Dependencies:
#   - packages/ai_presence_identity.yaml (helpers)
#   - packages/ai_identity.yaml (occupancy_mode, WiFi stale flag)
#   - packages/ai_self_awareness.yaml (ai_last_satellite)
#   - pyscript/presence_patterns.py (presence_predict_next service)
#
# Deployed: 2026-03-13
# =============================================================================

# ── Dynamic Getters (read from entity_config.yaml) ───────────────────────────

def _get_fp2_entities() -> dict:
    cfg = load_entity_config()
    fp2 = cfg.get("fp2_zones")
    if not fp2:
        log.error("presence_identity: fp2_zones not found in entity_config.yaml")  # noqa: F821
    return fp2 or {}


def _get_zone_friendly() -> dict:
    """Derive friendly zone names from the current FP2 entity map."""
    fp2 = _get_fp2_entities()
    return {v: v.replace("_", " ").title() for v in fp2.values()}


def _get_person_trackers() -> dict:
    """Build person→tracker map from discover_persons() (Task 22)."""
    persons = discover_persons()
    return {slug: p["trackers"][0] for slug, p in persons.items() if p.get("trackers")}


def _get_satellite_to_zone() -> dict:
    cfg = load_entity_config()
    sat = cfg.get("satellite_zones")
    if not sat:
        log.error("presence_identity: satellite_zones not found in entity_config.yaml")  # noqa: F821
    return sat or {}


def _get_agent_to_zone() -> dict:
    cfg = load_entity_config()
    agt = cfg.get("agent_zones")
    if not agt:
        log.error("presence_identity: agent_zones not found in entity_config.yaml")  # noqa: F821
    return agt or {}


def _get_persons() -> list:
    """Return person slug list from discover_persons() (Task 22)."""
    return get_person_slugs()


def _get_other() -> dict:
    """Derive person->other-person map (N=2 elimination).

    N≠2: returns empty dict + logs warning (FP2 zone-count constraint
    requires exactly 2 residents for elimination logic).
    """
    persons = _get_persons()
    if len(persons) == 2:
        return {persons[0]: persons[1], persons[1]: persons[0]}
    if len(persons) > 2:
        log.warning(  # noqa: F821
            "presence_identity: N=%d persons detected — elimination logic "
            "requires N=2. Identity inference degraded.", len(persons),
        )
    return {}

SENSOR_PREFIX = "sensor.ai_location_"
STATUS_ENTITY = "sensor.ai_presence_identity_status"


# ── Helper Utilities ────────────────────────────────────────────────────────

def _helper_int(entity_id: str, default: int) -> int:
    try:
        val = state.get(entity_id)  # noqa: F821
        if val and val not in ("unknown", "unavailable", ""):
            return int(float(val))
    except Exception:
        pass
    return default

def _helper_float(entity_id: str, default: float) -> float:
    try:
        val = state.get(entity_id)  # noqa: F821
        if val and val not in ("unknown", "unavailable", ""):
            return float(val)
    except Exception:
        pass
    return default


def _get_min_dwell_sec() -> int:
    return _helper_int("input_number.ai_presence_fp2_dwell_sec", 30)


# ── Anchor confidence values ─────────────────────────────────────────────────

_CONF_DEFAULTS = {
    "solo": 100, "voice": 95, "departure": 95, "arrival": 90,
    "count": 85, "transition": 80, "markov_cap": 50,
}

def _get_conf(name: str) -> int:
    return _helper_int(f"input_number.ai_presence_conf_{name}", _CONF_DEFAULTS.get(name, 50))

# ── Module State ─────────────────────────────────────────────────────────────
# LOCK DISCIPLINE: All reads/writes to _location, _zone_state, _zone_change_ts,
# and _recent_zone_off MUST happen inside `async with _lock:`. Helper functions
# (_assign, _compute_confidence, _update_sensors, _anchor_*, _track_transition,
# _apply_count_constraint) are called from within locked trigger handlers —
# they do NOT acquire the lock themselves to avoid re-entrancy deadlocks.

_location = {}  # populated at startup from discover_persons()

_zone_state: dict = {}           # zone → "on"/"off"
_zone_change_ts: dict = {}       # zone → last state change timestamp
_recent_zone_off: dict = {}      # zone → last OFF timestamp
_lock = asyncio.Lock()
_fp2_triggers = []             # factory-created FP2 trigger references (keep alive)
_wifi_triggers = []            # factory-created WiFi trigger references (keep alive)


# ── Helper: Kill Switch ──────────────────────────────────────────────────────

def _is_enabled():
    """Check if the identity engine is enabled."""
    return state.get("input_boolean.ai_presence_identity_enabled") == "on"  # noqa: F821


# ── Helper: Read Tuning Parameters ──────────────────────────────────────────

def _get_transition_window():
    """Transition window in seconds."""
    try:
        return float(state.get("input_number.ai_presence_identity_transition_window"))  # noqa: F821
    except (TypeError, ValueError):
        return 120.0


def _get_confidence_floor():
    """Minimum confidence to report (below this → 'unknown')."""
    try:
        return int(float(state.get("input_number.ai_presence_identity_confidence_floor")))  # noqa: F821
    except (TypeError, ValueError):
        return 20


def _get_departure_debounce():
    """Departure debounce in seconds."""
    try:
        return float(state.get("input_number.ai_presence_identity_departure_debounce"))  # noqa: F821
    except (TypeError, ValueError):
        return 60.0


# ── FP2 State Readers ───────────────────────────────────────────────────────

def _get_active_zones() -> list:
    """Return list of zone names where FP2 reports 'on'."""
    active = []
    for entity, zone in _get_fp2_entities().items():
        if state.get(entity) == "on":  # noqa: F821
            active.append(zone)
    return active


def _get_active_zone_count() -> int:
    """Count of currently active FP2 zones."""
    return len(_get_active_zones())


# ── Occupancy Mode ───────────────────────────────────────────────────────────

def _get_occupancy_mode() -> str:
    """Return current occupancy mode: solo_miquel, solo_jessica, dual, away, guest."""
    val = state.get("sensor.occupancy_mode")  # noqa: F821
    if val in ("unavailable", "unknown", None, ""):
        return "unknown"
    return val


def _get_solo_person() -> str | None:
    """If solo mode, return the person name. Otherwise None."""
    occ = _get_occupancy_mode()
    # occupancy_mode values: solo_<person>, dual, away, guest
    for person in _get_persons():
        if occ == f"solo_{person}":
            return person
    return None


def _is_person_home(person: str) -> bool:
    """Check if person's WiFi tracker shows 'home'."""
    tracker = _get_person_trackers().get(person)
    if not tracker:
        return False
    return state.get(tracker) == "home"  # noqa: F821


# ── Confidence Decay ────────────────────────────────────────────────────────

def _compute_confidence(person: str) -> int:
    """Decay confidence from anchor score based on elapsed time."""
    loc = _location.get(person)
    if not loc:
        return 0
    if loc["zone"] == "unknown" or loc["confidence"] == 0:
        return 0

    elapsed_min = (time.monotonic() - loc["since"]) / 60.0
    base = loc["confidence"]

    decay_start = _helper_float("input_number.ai_presence_decay_start", 15.0)
    decay_cap = _helper_float("input_number.ai_presence_decay_cap", 60.0)
    decay_range = _helper_float("input_number.ai_presence_decay_range", 45.0)
    decay_factor = _helper_float("input_number.ai_presence_decay_factor", 0.5)

    if elapsed_min <= decay_start:
        return base
    if elapsed_min <= decay_cap:
        # Linear decay from base to floor over decay range
        decay_frac = (elapsed_min - decay_start) / decay_range
        decayed = int(base * (1 - decay_frac * decay_factor))
        return max(decayed, _get_confidence_floor())
    # Past decay cap — cap at Markov level
    return min(base, _get_conf("markov_cap"))


def _confidence_label(conf: int) -> str:
    """Human-readable confidence label."""
    if conf >= 85:
        return "high"
    if conf >= 60:
        return "medium"
    if conf >= 30:
        return "low"
    return "very low"


# ── Sensor Output ────────────────────────────────────────────────────────────

def _update_sensors():
    """Push current location state to HA sensors."""
    now_iso = datetime.now().isoformat()

    zone_friendly = _get_zone_friendly()
    for person in _get_persons():
        if person not in _location:
            continue
        loc = _location[person]
        conf = _compute_confidence(person)
        zone = loc["zone"]
        floor = _get_confidence_floor()

        # If below floor, report unknown
        if conf < floor and zone != "unknown":
            display_zone = "unknown"
        else:
            display_zone = zone

        friendly = zone_friendly.get(display_zone, display_zone)
        entity = f"{SENSOR_PREFIX}{person}"

        state.set(  # noqa: F821
            entity,
            value=display_zone,
            new_attributes={
                "friendly_name": f"AI Location {person.title()}",
                "icon": "mdi:map-marker-account",
                "confidence": conf,
                "confidence_label": _confidence_label(conf),
                "source": loc["source"],
                "since": loc["since"],
                "zone_friendly": friendly,
                "updated": now_iso,
            },
        )

    # Engine status
    occ = _get_occupancy_mode()
    active = _get_active_zones()
    state.set(  # noqa: F821
        STATUS_ENTITY,
        value="active" if _is_enabled() else "disabled",
        new_attributes={
            "friendly_name": "AI Presence Identity Status",
            "icon": "mdi:account-search",
            "occupancy_mode": occ,
            "active_zones": active,
            **{
                f"{p}_zone": _location[p]["zone"]
                for p in _get_persons() if p in _location
            },
            **{
                f"{p}_confidence": _compute_confidence(p)
                for p in _get_persons() if p in _location
            },
            "updated": now_iso,
        },
    )


# ── Location Assignment ─────────────────────────────────────────────────────

def _assign(person: str, zone: str, confidence: int, source: str):
    """Assign a person to a zone with confidence and source."""
    if person not in _location:
        _location[person] = {"zone": "unknown", "confidence": 0, "source": "none", "since": 0.0}
    _location[person]["zone"] = zone
    _location[person]["confidence"] = confidence
    _location[person]["source"] = source
    _location[person]["since"] = time.monotonic()
    log.info(  # noqa: F821
        f"presence_identity: {person} → {zone} "
        f"(conf={confidence}, source={source})"
    )


# ── Anchor Functions ─────────────────────────────────────────────────────────

def _anchor_solo(person: str):
    """Solo home — all active FP2 zones belong to this person."""
    active = _get_active_zones()
    if not active:
        _assign(person, "unknown", _get_conf("solo"), "solo_no_fp2")
        return

    # Pick the most recently activated zone if tracked, else first
    best_zone = active[0]
    best_ts = 0.0
    for z in active:
        ts = _zone_change_ts.get(z, 0.0)
        if ts > best_ts:
            best_ts = ts
            best_zone = z

    _assign(person, best_zone, _get_conf("solo"), "solo")

    # Other person is away
    other = _get_other().get(person)
    if other and _location[other]["zone"] != "away":
        _assign(other, "away", _get_conf("solo"), "solo_elimination")


def _anchor_voice(person: str, zone: str):
    """Voice interaction pins person to satellite's zone."""
    _assign(person, zone, _get_conf("voice"), "voice_satellite")


def _anchor_departure(departed: str):
    """WiFi departure — remaining FP2 bodies belong to other person."""
    other = _get_other().get(departed)
    if not other:
        return
    _assign(departed, "away", _get_conf("departure"), "wifi_departure")

    # Remaining bodies = other person
    active = _get_active_zones()
    if active:
        best_zone = active[0]
        best_ts = 0.0
        for z in active:
            ts = _zone_change_ts.get(z, 0.0)
            if ts > best_ts:
                best_ts = ts
                best_zone = z
        _assign(other, best_zone, _get_conf("departure"), "departure_elimination")


def _anchor_arrival(arriving: str):
    """WiFi arrival — if FP2 count increased, new body = arriving person."""
    active = _get_active_zones()
    if not active:
        # WiFi home but no FP2 yet (e.g., still outside smoking)
        _assign(arriving, "home", 70, "wifi_arrival_no_fp2")
        return

    other = _get_other().get(arriving)
    if not other:
        return
    other_zone = _location[other]["zone"]

    # If other person is tracked to a zone, arriving person is in a different zone
    unassigned = [z for z in active if z != other_zone]
    if unassigned:
        # Pick most recently activated unassigned zone
        best_zone = unassigned[0]
        best_ts = 0.0
        for z in unassigned:
            ts = _zone_change_ts.get(z, 0.0)
            if ts > best_ts:
                best_ts = ts
                best_zone = z
        _assign(arriving, best_zone, _get_conf("arrival"), "wifi_arrival")
    elif active:
        # Both in same zone
        _assign(arriving, active[0], _get_conf("arrival"), "wifi_arrival_same_zone")


# ── Transition Tracking ─────────────────────────────────────────────────────

def _track_transition(from_zone: str, to_zone: str):
    """A zone turned OFF and another turned ON — someone moved."""
    occ = _get_occupancy_mode()
    window = _get_transition_window()

    # Check timing: from_zone OFF must be recent
    off_ts = _recent_zone_off.get(from_zone, 0.0)
    on_ts = _zone_change_ts.get(to_zone, 0.0)
    if on_ts - off_ts > window or on_ts < off_ts:
        return  # too far apart, not a transition

    # Find who was in from_zone
    for person in _get_persons():
        if _location[person]["zone"] == from_zone:
            _assign(person, to_zone, _get_conf("transition"), "fp2_transition")
            return

    # Nobody tracked to from_zone — if solo mode, assign solo person
    solo = _get_solo_person()
    if solo:
        _assign(solo, to_zone, _get_conf("transition"), "fp2_transition_solo")


def _apply_count_constraint():
    """If dual mode + exactly 2 zones active + 2 people home → one per zone."""
    occ = _get_occupancy_mode()
    if occ != "dual":
        return

    active = _get_active_zones()
    if len(active) != 2:
        return

    persons = _get_persons()
    if len(persons) != 2:
        return

    p0, p1 = persons[0], persons[1]

    # If both people already assigned to different active zones, nothing to do
    p0_zone = _location[p0]["zone"]
    p1_zone = _location[p1]["zone"]

    if p0_zone in active and p1_zone in active and p0_zone != p1_zone:
        return  # already correctly assigned

    # If one person is assigned to an active zone, other gets the remaining
    if p0_zone in active and p1_zone not in active:
        other_zone = [z for z in active if z != p0_zone][0]
        _assign(p1, other_zone, _get_conf("count"), "count_constraint")
        return

    if p1_zone in active and p0_zone not in active:
        other_zone = [z for z in active if z != p1_zone][0]
        _assign(p0, other_zone, _get_conf("count"), "count_constraint")
        return

    # Neither assigned — use Markov priors as tiebreaker
    _apply_markov_tiebreak(active)


# ── Markov Fallback ──────────────────────────────────────────────────────────

async def _apply_markov_fallback_async(person: str, candidates: list):
    """Use Markov chain predictions to pick the most likely zone."""
    if not candidates:
        return

    best_zone = candidates[0]
    best_prob = 0.0

    for zone in candidates:
        try:
            result = pyscript.presence_predict_next(current_zone=zone)  # noqa: F821
            resp = await result
            if resp and resp.get("status") == "ok":
                probs = resp.get("probabilities", {})
                # Sum of probabilities for this zone being a destination = proxy for popularity
                total = sum(probs.values()) if probs else 0
                if total > best_prob:
                    best_prob = total
                    best_zone = zone
        except Exception:
            pass

    _assign(person, best_zone, _get_conf("markov_cap"), "markov_prior")


async def _apply_markov_tiebreak(active_zones: list):
    """Both people unassigned, 2 zones active — Markov decides who goes where."""
    if len(active_zones) != 2:
        return

    z1, z2 = active_zones

    # Query Markov for which zone is more likely for Miquel at this time
    try:
        result = pyscript.presence_predict_next(current_zone=z1)  # noqa: F821
        resp = await result
        z1_score = sum(resp.get("probabilities", {}).values()) if resp and resp.get("status") == "ok" else 0
    except Exception:
        z1_score = 0

    try:
        result = pyscript.presence_predict_next(current_zone=z2)  # noqa: F821
        resp = await result
        z2_score = sum(resp.get("probabilities", {}).values()) if resp and resp.get("status") == "ok" else 0
    except Exception:
        z2_score = 0

    # Higher score = more typical zone = assign first person there (primary resident pattern)
    persons = _get_persons()
    if len(persons) < 2:
        return
    p0, p1 = persons[0], persons[1]
    if z1_score >= z2_score:
        _assign(p0, z1, _get_conf("markov_cap"), "markov_tiebreak")
        _assign(p1, z2, _get_conf("markov_cap"), "markov_tiebreak")
    else:
        _assign(p0, z2, _get_conf("markov_cap"), "markov_tiebreak")
        _assign(p1, z1, _get_conf("markov_cap"), "markov_tiebreak")


# ── State Triggers ───────────────────────────────────────────────────────────

def _fp2_trigger_factory(entity_id):
    """Create a @state_trigger for a single FP2 entity."""
    @state_trigger(entity_id)  # noqa: F821
    async def _trig(var_name=None, value=None, old_value=None):
        await _on_fp2_change(var_name=var_name, value=value, old_value=old_value)
    return _trig


async def _on_fp2_change(var_name=None, value=None, old_value=None):
    """Handle FP2 zone state changes."""
    if not _is_enabled():
        return

    zone = _get_fp2_entities().get(var_name)
    if not zone:
        return

    now = time.monotonic()

    # Debounce: ignore rapid flapping
    last_change = _zone_change_ts.get(zone, 0.0)
    if now - last_change < _get_min_dwell_sec() and old_value is not None:
        return

    async with _lock:
        prev_state = _zone_state.get(zone, "off")

        if value == "on" and prev_state != "on":
            # Zone activated
            _zone_state[zone] = "on"
            _zone_change_ts[zone] = now

            # Check for transition: was another zone recently turned off?
            for off_zone, off_ts in _recent_zone_off.items():
                if off_zone != zone and (now - off_ts) < _get_transition_window():
                    _track_transition(off_zone, zone)
                    break

            # Solo mode: all bodies = solo person
            solo = _get_solo_person()
            if solo:
                _anchor_solo(solo)

        elif value == "off" and prev_state != "off":
            # Zone deactivated
            _zone_state[zone] = "off"
            _recent_zone_off[zone] = now

            # If someone was tracked here and it's now off, they moved
            # Don't clear immediately — wait for transition detection

        # Apply count constraint in dual mode
        if _get_occupancy_mode() == "dual":
            _apply_count_constraint()

        _update_sensors()


def _wifi_trigger_factory(entity_id):
    """Create a @state_trigger for a single WiFi tracker entity."""
    @state_trigger(entity_id)  # noqa: F821
    async def _trig(var_name=None, value=None, old_value=None):
        await _on_wifi_change(var_name=var_name, value=value, old_value=old_value)
    return _trig


async def _on_wifi_change(var_name=None, value=None, old_value=None):
    """Handle WiFi tracker state changes (arrival/departure)."""
    if not _is_enabled():
        return

    # Determine which person
    person = None
    for p, tracker in _get_person_trackers().items():
        if tracker == var_name:
            person = p
            break
    if not person:
        return

    # Arrival — lock, anchor, done
    if value == "home" and old_value != "home":
        async with _lock:
            log.info(f"presence_identity: {person} WiFi arrived")  # noqa: F821
            _anchor_arrival(person)
            _update_sensors()
        return

    # Departure — debounce OUTSIDE lock to avoid deadlock
    if value != "home" and old_value == "home":
        debounce = _get_departure_debounce()
        log.info(  # noqa: F821
            f"presence_identity: {person} WiFi departed, "
            f"debouncing {debounce}s"
        )
        await asyncio.sleep(debounce)

        # Re-check after debounce
        current = state.get(var_name)  # noqa: F821
        if current != "home":
            async with _lock:
                _anchor_departure(person)
                _update_sensors()
        else:
            log.info(  # noqa: F821
                f"presence_identity: {person} WiFi flap absorbed"
            )


@state_trigger("input_text.ai_last_satellite")  # noqa: F821
async def presence_identity_satellite_trigger(var_name=None, value=None, old_value=None):
    """Handle voice satellite interaction — anchor speaker to zone."""
    if not _is_enabled():
        return

    if not value or value in ("", "unknown", "unavailable"):
        return

    zone = _get_satellite_to_zone().get(value)
    if not zone:
        return

    async with _lock:
        occ = _get_occupancy_mode()
        persons = _get_persons()
        other_map = _get_other()

        if occ.startswith("solo_"):
            # Solo: speaker is the only person home
            solo = _get_solo_person()
            if solo:
                _anchor_voice(solo, zone)

        elif occ == "dual":
            # Dual: check if someone is already tracked to this zone
            # If yes, that person spoke. If ambiguous, don't anchor.
            tracked_here = [
                p for p in persons
                if _location[p]["zone"] == zone
                and _compute_confidence(p) >= _get_confidence_floor()
            ]

            if len(tracked_here) == 1:
                # Person already tracked here — reinforce
                _anchor_voice(tracked_here[0], zone)
            elif len(tracked_here) == 0:
                # Nobody tracked here — check if one person is confidently elsewhere
                other_zone_persons = [
                    p for p in persons
                    if _location[p]["zone"] not in ("unknown", "away", zone)
                    and _compute_confidence(p) >= 60
                ]
                if len(other_zone_persons) == 1:
                    # One person is confidently elsewhere → speaker is the other
                    speaker = other_map.get(other_zone_persons[0])
                    if speaker:
                        _anchor_voice(speaker, zone)
                else:
                    log.info(  # noqa: F821
                        f"presence_identity: satellite in {zone} but "
                        "can't determine speaker in dual mode"
                    )
            # len(tracked_here) == 2: both tracked here, can't distinguish

        _update_sensors()


# ── Time Triggers ────────────────────────────────────────────────────────────

@time_trigger("cron(*/5 * * * *)")  # noqa: F821
async def presence_identity_decay_tick():
    """Periodic confidence decay and Markov fallback."""
    if not _is_enabled():
        return

    async with _lock:
        occ = _get_occupancy_mode()
        floor = _get_confidence_floor()

        for person in _get_persons():
            if person not in _location:
                continue
            conf = _compute_confidence(person)
            zone = _location[person]["zone"]

            # If confidence has decayed below floor and we're in dual mode,
            # try Markov fallback
            if conf < floor and zone not in ("unknown", "away") and occ == "dual":
                active = _get_active_zones()
                if active:
                    await _apply_markov_fallback_async(person, active)

        _update_sensors()


# ── Person Change Detection (Task 22 Phase 7) ──────────────────────────────

_known_person_slugs: set = set()


@time_trigger("cron(*/15 * * * *)")  # noqa: F821
async def presence_identity_person_check():
    """Detect person additions/removals every 15 minutes."""
    global _known_person_slugs, _location
    from shared_utils import reload_persons

    current = set(get_person_slugs())

    if not _known_person_slugs:
        # First run — seed without logging
        _known_person_slugs = current
        return

    if current == _known_person_slugs:
        return

    added = current - _known_person_slugs
    removed = _known_person_slugs - current

    if added:
        reload_persons()
        async with _lock:
            for p in added:
                _location[p] = {"zone": "unknown", "confidence": 0, "source": "none", "since": 0.0}
            _update_sensors()
        log.info(f"presence_identity: persons added: {added}")  # noqa: F821

    if removed:
        reload_persons()
        async with _lock:
            for p in removed:
                _location.pop(p, None)
            _update_sensors()
        log.info(f"presence_identity: persons removed: {removed}")  # noqa: F821

    _known_person_slugs = current


@time_trigger("startup")  # noqa: F821
async def presence_identity_startup():
    """Initialize on HA startup."""
    # Brief delay for entities/SMB mount to settle
    task.sleep(10)  # noqa: F821

    # Force re-read of entity_config.yaml (cache may be stale from early import)
    await asyncio.to_thread(reload_entity_config)

    log.info("presence_identity: initializing")  # noqa: F821

    # Initialize _location + known slugs from discover_persons() (Task 22)
    global _location, _known_person_slugs
    _known_person_slugs = set(get_person_slugs())
    for p in get_person_slugs():
        if p not in _location:
            _location[p] = {"zone": "unknown", "confidence": 0, "source": "none", "since": 0.0}

    # Register FP2 and WiFi triggers dynamically from config
    global _fp2_triggers, _wifi_triggers
    fp2_entities = _get_fp2_entities().keys()
    _fp2_triggers = [_fp2_trigger_factory(e) for e in fp2_entities]
    trackers = list(_get_person_trackers().values())
    _wifi_triggers = [_wifi_trigger_factory(t) for t in trackers]
    log.info(  # noqa: F821
        f"presence_identity: registered {len(_fp2_triggers)} FP2 + "
        f"{len(_wifi_triggers)} WiFi triggers"
    )

    if not _is_enabled():
        log.info("presence_identity: disabled, setting status only")  # noqa: F821
        _update_sensors()
        return

    async with _lock:
        # Initialize zone state from current FP2 readings
        now = time.monotonic()
        for entity, zone in _get_fp2_entities().items():
            s = state.get(entity)  # noqa: F821
            _zone_state[zone] = s if s in ("on", "off") else "off"
            if s == "on":
                _zone_change_ts[zone] = now

        # Check occupancy mode and anchor if possible
        solo = _get_solo_person()
        if solo:
            _anchor_solo(solo)
        elif _get_occupancy_mode() == "away":
            for p in _get_persons():
                _assign(p, "away", _get_conf("solo"), "startup_away")
        elif _get_occupancy_mode() == "dual":
            # Dual mode at startup — can't anchor, start unknown
            # Count constraint might help
            _apply_count_constraint()

        _update_sensors()

    log.info("presence_identity: startup complete")  # noqa: F821


# ── Test Mode ────────────────────────────────────────────────────────────────

def _is_test_mode() -> bool:
    try:
        return str(
            state.get("input_boolean.ai_test_mode") or "off"  # noqa: F821
        ).lower() == "on"
    except NameError:
        return False


# ── Services ─────────────────────────────────────────────────────────────────

@service(supports_response="only")  # noqa: F821
async def presence_identity_status():
    """Return current tracking state for debugging.

    fields: {}
    """
    if _is_test_mode():
        log.info("presence_identity [TEST]: would return tracking status")  # noqa: F821
        return {"status": "test_mode_skip"}

    async with _lock:
        result = {}
        zone_friendly = _get_zone_friendly()
        for person in _get_persons():
            loc = _location[person]
            conf = _compute_confidence(person)
            result[person] = {
                "zone": loc["zone"],
                "zone_friendly": zone_friendly.get(loc["zone"], loc["zone"]),
                "confidence": conf,
                "confidence_label": _confidence_label(conf),
                "source": loc["source"],
                "elapsed_min": round((time.monotonic() - loc["since"]) / 60.0, 1)
                if loc["since"] > 0 else 0,
            }

        result["engine"] = {
            "enabled": _is_enabled(),
            "occupancy_mode": _get_occupancy_mode(),
            "active_zones": _get_active_zones(),
            "zone_state": dict(_zone_state),
        }
        return result


@service  # noqa: F821
async def presence_identity_force_anchor(person: str = "", zone: str = ""):
    """Manually pin a person to a zone.

    fields:
      person:
        description: Person name
        example: "miquel"
        required: true
        selector:
          # Static options — sync with person.* entities if persons change
          select:
            options:
              - miquel
              - jessica
      zone:
        description: Zone name
        example: "workshop"
        required: true
        selector:
          select:
            options:
              - workshop
              - living_room
              - main_room
              - kitchen
              - bed
              - lobby
              - bathroom
              - shower
              - away
              - unknown
    """
    if _is_test_mode():
        log.info("presence_identity [TEST]: would force-anchor %s to %s", person, zone)  # noqa: F821
        return

    if person not in _get_persons():
        log.warning(f"presence_identity: force_anchor invalid person '{person}'")  # noqa: F821
        return

    async with _lock:
        _assign(person, zone, _get_conf("solo"), "manual_anchor")
        _update_sensors()

    log.info(f"presence_identity: force anchored {person} → {zone}")  # noqa: F821


@service  # noqa: F821
async def presence_identity_reset():
    """Clear all tracking state and reinitialize.

    fields: {}
    """
    if _is_test_mode():
        log.info("presence_identity [TEST]: would reset all tracking state")  # noqa: F821
        return

    async with _lock:
        for person in _get_persons():
            _location[person] = {
                "zone": "unknown",
                "confidence": 0,
                "source": "none",
                "since": 0.0,
            }
        _zone_state.clear()
        _zone_change_ts.clear()
        _recent_zone_off.clear()
        _update_sensors()

    log.info("presence_identity: reset complete")  # noqa: F821

    # Re-initialize
    await presence_identity_startup()


@service(supports_response="only")  # noqa: F821
async def discover_persons_status():
    """Return current person discovery cache for debugging.

    fields: {}
    """
    persons = discover_persons()
    return {
        "status": "ok",
        "person_count": len(persons),
        "persons": persons,
    }
