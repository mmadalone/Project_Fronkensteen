"""First-run defaults for input helpers.

WHY THIS EXISTS
---------------
Home Assistant's `input_*` helpers have no "default value" concept. The only key
that looks like one, `initial:`, is not a default at all: when it is present HA
assigns it at construction and skips the restore-state path entirely, so it
overwrites whatever the user set on *every* boot. Auditing this config found 283
helpers carrying it, which made more than half the settings dashboard write-only.

Stripping `initial:` fixes persistence but removes the only thing supplying a
sensible starting value, because a helper with no `initial:` and no restorable
state does not fall back to anything thoughtful -- it falls back to `min:` for
input_number, `off` for input_boolean, `""` for input_text, and the first option
for input_select. On an existing install that is harmless (restore-state carries
the real value). On a *fresh* install there is no restore-state, so every helper
would come up at those floors: scoring weights at 0, thresholds at 0, timeouts at
whatever the lowest allowed value happens to be.

So the two jobs `initial:` was conflating get separated the way HA's own `counter`
domain already separates them -- `counter` ships both `initial:` and
`restore: true`, and gets this right. This module is the `initial:` half for
helpers: it applies curated starting values exactly once per helper, and never
again.

WHEN IT RUNS
------------
After EVENT_HOMEASSISTANT_STARTED, because the helpers are YAML-defined and do
not exist as entities until HA has loaded the files the installer just wrote --
which is the boot *after* the install. Helpers that are not present yet (a
feature group the user did not select, or the pre-restart boot) are simply left
for a later boot; nothing is recorded as seeded unless it was actually set.

WHAT IT WILL NOT DO
-------------------
Overwrite a value somebody chose. Two independent guards:

  1. Each entity id is recorded in .storage once seeded and never revisited,
     so a user who later returns a helper to its floor keeps that choice.
  2. Even on the first pass, a helper is only seeded if it is still sitting on
     the exact fallback HA would have given it. Anything else means something
     already set it -- restore-state, an automation, or a person -- and it is
     left alone.

Guard 1 alone would be enough for a clean install; guard 2 is what makes it safe
to call from `repair_installation`, where most helpers already hold real values
and only genuinely-new ones should be touched.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

DEFAULTS_FILE = "helper_defaults.json"

# domain -> (service, payload key). The value itself is domain-shaped, so the
# caller builds the payload; this is only the routing.
_SERVICE = {
    "input_number": ("set_value", "value"),
    "input_text": ("set_value", "value"),
    "input_select": ("select_option", "option"),
}


def _defaults_path(hass: HomeAssistant) -> Path:
    return Path(hass.config.path("custom_components", "project_fronkensteen", DEFAULTS_FILE))


def _load_defaults(path: Path) -> dict[str, Any]:
    """Read the manifest. encoding= is required -- it holds non-ASCII strings."""
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _is_at_fallback(domain: str, state: str, attrs: dict) -> bool:
    """Is this helper still sitting on the value HA gives it with nothing restored?

    Returns False for anything it cannot judge, so an unrecognised shape is left
    alone rather than overwritten.
    """
    if state in ("unknown", "unavailable"):
        # No usable reading. Not "at fallback" -- just unjudgeable, so skip and
        # let a later boot decide.
        return False

    if domain == "input_boolean":
        return state == "off"

    if domain == "input_text":
        return state == ""

    if domain == "input_number":
        minimum = attrs.get("min")
        if minimum is None:
            return False
        try:
            return abs(float(state) - float(minimum)) < 1e-9
        except (TypeError, ValueError):
            return False

    if domain == "input_select":
        options = attrs.get("options") or []
        return bool(options) and state == options[0]

    return False


async def _apply(hass: HomeAssistant, entity_id: str, domain: str, value: Any) -> None:
    """Set one helper. Raises on failure so the caller can record it."""
    if domain == "input_boolean":
        service = "turn_on" if value else "turn_off"
        await hass.services.async_call(
            domain, service, {"entity_id": entity_id}, blocking=True
        )
        return

    service, key = _SERVICE[domain]
    await hass.services.async_call(
        domain, service, {"entity_id": entity_id, key: value}, blocking=True
    )


async def manifest_ids(hass: HomeAssistant) -> list[str]:
    """Every entity id this module would ever seed.

    Used to adopt a pre-existing install wholesale: its helpers already hold
    chosen values, and defaults must never be applied to it retroactively.
    Returns [] if the manifest is unreadable, which errs toward seeding nothing.
    """
    try:
        defaults = await hass.async_add_executor_job(_load_defaults, _defaults_path(hass))
    except (OSError, ValueError) as err:
        _LOGGER.warning("Cannot read helper defaults manifest: %s", err)
        return []
    return list(defaults)


async def seed(hass: HomeAssistant, already_seeded: list[str] | None = None) -> dict:
    """Apply first-run defaults to helpers that have never been seeded.

    Returns {"seeded": [...], "skipped": int, "missing": int, "errors": [...]},
    where "seeded" is the list of entity ids actually written this pass. The
    caller is responsible for persisting it -- this function does not touch
    storage, so a failed save cannot mark helpers as done when they are not.
    """
    report: dict[str, Any] = {"seeded": [], "skipped": 0, "missing": 0, "errors": []}
    done = set(already_seeded or [])

    path = _defaults_path(hass)
    try:
        defaults = await hass.async_add_executor_job(_load_defaults, path)
    except FileNotFoundError:
        report["errors"].append(f"Defaults manifest not found: {path}")
        return report
    except (OSError, ValueError) as err:
        report["errors"].append(f"Cannot read {path}: {err}")
        return report

    for entity_id, value in defaults.items():
        if entity_id in done:
            continue

        domain = entity_id.split(".", 1)[0]
        if domain != "input_boolean" and domain not in _SERVICE:
            report["errors"].append(f"{entity_id}: no seeding rule for domain {domain}")
            continue

        state = hass.states.get(entity_id)
        if state is None:
            # Not loaded yet, or belongs to a feature group this user did not
            # install. Deliberately NOT recorded as seeded, so a later boot
            # picks it up if it appears.
            report["missing"] += 1
            continue

        if not _is_at_fallback(domain, state.state, state.attributes):
            # Something already set this -- restore-state, an automation, or a
            # person. Record it as done so we never reconsider it.
            report["seeded"].append(entity_id)
            report["skipped"] += 1
            continue

        try:
            await _apply(hass, entity_id, domain, value)
        except Exception as err:  # noqa: BLE001 - one bad helper must not stop the rest
            report["errors"].append(f"{entity_id}: {err}")
            continue

        report["seeded"].append(entity_id)

    written = len(report["seeded"]) - report["skipped"]
    if written or report["missing"] or report["errors"]:
        _LOGGER.info(
            "Helper defaults: %d set, %d already configured, %d not present yet, %d errors",
            written, report["skipped"], report["missing"], len(report["errors"]),
        )
    for err in report["errors"]:
        _LOGGER.warning("Helper default failed: %s", err)

    return report
