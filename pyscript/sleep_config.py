"""Sleep Config — Entity Picker Services for Sleep Lights and Detection.

Provides add/remove picker services for managing sleep light targets stored
in L2 memory, and populates dropdown options for sleep detection sensors
and light entity selectors from FP2 presence sensors and the light registry.
"""
import asyncio
import json
from typing import Any

from shared_utils import build_result_entity_name, load_entity_config

# =============================================================================
# Sleep Config — Entity Picker Services for Sleep Lights & Detection
# =============================================================================
# Provides Add/Remove picker pattern for sleep light targets (stored in L2)
# and populates sensor pickers for sleep detection/lights.
#
# Services:
#   pyscript.sleep_lights_add_target    — add light from picker to targets
#   pyscript.sleep_lights_remove_target — remove light from targets
#   pyscript.sleep_lights_load_display  — refresh target display sensor
#   pyscript.sleep_config_populate_pickers — refresh dropdown options
#
# Dependencies:
#   pyscript/memory.py (L2: memory_get, memory_set)
#   input helpers defined in packages/ai_sleep_lights.yaml
#   input helpers defined in packages/ai_sleep_detection.yaml
# Deployed: 2026-03-04
# =============================================================================

DISPLAY_ENTITY = "sensor.ai_sleep_lights_display"
L2_KEY = "sleep_lights:targets"
L2_SCOPE = "household"
L2_TAGS = "sleep lights targets config"

# All FP2 presence sensors
_DEFAULT_FP2_SENSORS = [
    "binary_sensor.fp2_presence_sensor_main_room",
    "binary_sensor.fp2_presence_sensor_living_room",
    "binary_sensor.fp2_presence_sensor_bed",
    "binary_sensor.fp2_presence_sensor_workshop",
    "binary_sensor.fp2_presence_sensor_kitchen",
    "binary_sensor.fp2_presence_sensor_lobby",
    "binary_sensor.fp2_presence_sensor_bathroom",
    "binary_sensor.fp2_presence_sensor_shower",
]


def _get_fp2_sensors() -> list:
    """Get FP2 sensor entities from config (keys of fp2_zones map)."""
    cfg = load_entity_config()
    fp2 = cfg.get("fp2_zones")
    return list(fp2.keys()) if fp2 else _DEFAULT_FP2_SENSORS

# ── State ─────────────────────────────────────────────────────────────────────
_targets: list = []     # current sleep light entity targets
result_entity_name: dict = {}


def _ensure_result_entity_name(force: bool = False) -> None:
    global result_entity_name
    if force or not result_entity_name:
        result_entity_name = build_result_entity_name(DISPLAY_ENTITY)


def _set_display(content: str) -> None:
    """Update the sleep lights display sensor."""
    _ensure_result_entity_name()
    try:
        state.set(  # noqa: F821
            DISPLAY_ENTITY,
            value="ok",
            new_attributes={
                **result_entity_name,
                "content": content,
                "targets": list(_targets),
                "count": len(_targets),
            },
        )
    except Exception as exc:
        log.warning(f"sleep_config: display set failed: {exc}")  # noqa: F821


# ── L2 Memory Access ─────────────────────────────────────────────────────────

async def _load_targets_from_l2() -> list:
    """Load light targets from L2 memory."""
    try:
        result = pyscript.memory_get(key=L2_KEY)  # noqa: F821
        resolved = await result
        if resolved and resolved.get("status") == "ok":
            value = resolved.get("value", "[]")
            return json.loads(value) if isinstance(value, str) else value
    except Exception as exc:
        log.warning(f"sleep_config: L2 load failed: {exc}")  # noqa: F821
    return []


async def _save_targets_to_l2() -> None:
    """Save light targets to L2 memory."""
    try:
        result = pyscript.memory_set(  # noqa: F821
            key=L2_KEY,
            value=json.dumps(_targets),
            scope=L2_SCOPE,
            expiration_days=0,
            tags=L2_TAGS,
            force_new=True,
        )
        await result
    except Exception as exc:
        log.error(f"sleep_config: L2 save failed: {exc}")  # noqa: F821


# ── Display ───────────────────────────────────────────────────────────────────

def _update_display() -> None:
    """Refresh the display sensor with current targets."""
    if _targets:
        lines = ["**Sleep Light Targets:**"]
        for t in _targets:
            lines.append(f"- {t}")
        _set_display("\n".join(lines))
    else:
        _set_display("No light targets configured (area mode active).")


# ── Test Mode ────────────────────────────────────────────────────────────────

def _is_test_mode() -> bool:
    try:
        return str(
            state.get("input_boolean.ai_test_mode") or "off"  # noqa: F821
        ).lower() == "on"
    except NameError:
        return False


# ── Services ──────────────────────────────────────────────────────────────────

@service(supports_response="optional")  # noqa: F821
async def sleep_lights_add_target():
    """
    yaml
    name: Sleep Lights Add Target
    description: Add light from picker to sleep light targets.
    """
    if _is_test_mode():
        log.info("sleep_config [TEST]: would add light target from picker")  # noqa: F821
        return

    entity_id = state.get("input_select.ai_sleep_lights_light_picker") or ""  # noqa: F821
    if not entity_id or entity_id == "(none)":
        return {"status": "error", "error": "no_entity_selected"}

    if entity_id not in _targets:
        _targets.append(entity_id)
        await _save_targets_to_l2()
        _update_display()

    return {"status": "ok", "added": entity_id, "count": len(_targets)}


@service(supports_response="optional")  # noqa: F821
async def sleep_lights_remove_target():
    """
    yaml
    name: Sleep Lights Remove Target
    description: Remove light from sleep light targets.
    """
    if _is_test_mode():
        log.info("sleep_config [TEST]: would remove light target from picker")  # noqa: F821
        return

    entity_id = state.get("input_select.ai_sleep_lights_light_picker") or ""  # noqa: F821
    if not entity_id or entity_id == "(none)":
        return {"status": "error", "error": "no_entity_selected"}

    if entity_id in _targets:
        _targets.remove(entity_id)
        await _save_targets_to_l2()
        _update_display()

    return {"status": "ok", "removed": entity_id, "count": len(_targets)}


@service(supports_response="optional")  # noqa: F821
async def sleep_lights_load_display():
    """
    yaml
    name: Sleep Lights Load Display
    description: Refresh target display sensor from L2.
    """
    if _is_test_mode():
        log.info("sleep_config [TEST]: would refresh target display from L2")  # noqa: F821
        return

    global _targets
    _targets = await _load_targets_from_l2()
    _update_display()
    return {"status": "ok", "count": len(_targets)}


@service(supports_response="optional")  # noqa: F821
async def sleep_config_populate_pickers():
    """
    yaml
    name: Sleep Config Populate Pickers
    description: Refresh all sleep-related dropdown options.
    """
    if _is_test_mode():
        log.info("sleep_config [TEST]: would populate sleep config pickers")  # noqa: F821
        return

    # Sleep lights light picker
    try:
        light_ids = sorted([
            eid for eid in state.names(domain="light")  # noqa: F821
            if state.get(eid) not in ("unavailable",)  # noqa: F821
        ])
        options = ["(none)"] + light_ids if light_ids else ["(none)"]
        service.call(  # noqa: F821
            "input_select", "set_options",
            entity_id="input_select.ai_sleep_lights_light_picker",
            options=options,
        )
    except Exception as exc:
        log.warning(f"sleep_config: light picker populate failed: {exc}")  # noqa: F821

    # Sleep lights sensor picker
    try:
        service.call(  # noqa: F821
            "input_select", "set_options",
            entity_id="input_select.ai_sleep_lights_sensor",
            options=_get_fp2_sensors(),
        )
    except Exception as exc:
        log.warning(f"sleep_config: lights sensor picker populate failed: {exc}")  # noqa: F821

    # Sleep detection sensor picker
    try:
        service.call(  # noqa: F821
            "input_select", "set_options",
            entity_id="input_select.ai_sleep_detection_sensor",
            options=_get_fp2_sensors(),
        )
    except Exception as exc:
        log.warning(f"sleep_config: detection sensor picker populate failed: {exc}")  # noqa: F821

    return {"status": "ok"}


# ── Startup ───────────────────────────────────────────────────────────────────

@time_trigger("startup")  # noqa: F821
async def _sleep_config_startup():
    """Initialize sleep config — load targets, populate pickers."""
    global _targets

    _ensure_result_entity_name(force=True)

    # Wait for helpers to be ready after reload
    await asyncio.sleep(5)

    # Load targets from L2
    _targets = await _load_targets_from_l2()

    # Populate pickers
    await sleep_config_populate_pickers()

    # Set default sensor selections if empty/unknown
    try:
        det_val = state.get("input_select.ai_sleep_detection_sensor") or ""  # noqa: F821
        if det_val in ("unknown", "unavailable", ""):
            service.call(  # noqa: F821
                "input_select", "select_option",
                entity_id="input_select.ai_sleep_detection_sensor",
                option="binary_sensor.fp2_presence_sensor_bed",
            )
    except Exception:
        pass

    try:
        lights_val = state.get("input_select.ai_sleep_lights_sensor") or ""  # noqa: F821
        if lights_val in ("unknown", "unavailable", ""):
            service.call(  # noqa: F821
                "input_select", "select_option",
                entity_id="input_select.ai_sleep_lights_sensor",
                option="binary_sensor.fp2_presence_sensor_bed",
            )
    except Exception:
        pass

    try:
        lp_val = state.get("input_select.ai_sleep_lights_light_picker") or ""  # noqa: F821
        if lp_val in ("unknown", "unavailable", "", "(none)"):
            light_ids = sorted([
                eid for eid in state.names(domain="light")  # noqa: F821
                if state.get(eid) not in ("unavailable",)  # noqa: F821
            ])
            if light_ids:
                service.call(  # noqa: F821
                    "input_select", "select_option",
                    entity_id="input_select.ai_sleep_lights_light_picker",
                    option=light_ids[0],
                )
    except Exception:
        pass

    _update_display()

    log.info(  # noqa: F821
        f"sleep_config.py loaded — {len(_targets)} light targets"
    )
