#!/usr/bin/env python3
"""Assert helper_defaults.json still agrees with the helper YAML it was built from.

WHY THIS EXISTS
  `initial:` in an input helper is not a default -- HA assigns it at construction
  and skips restore-state, so it overwrites the user's value on every boot. 252 of
  them were stripped from this config, which fixed persistence but removed the only
  thing giving a fresh install sensible starting values (a helper with no `initial:`
  and nothing to restore falls back to `min:` / `off` / `""` / the first option).

  helper_defaults.json carries those values instead, and the integration applies
  them once per helper. That makes it a second copy of facts that live in the YAML:
  bounds, options, and which helpers exist. Copies drift. When this one drifts the
  failure is invisible in CI and lands in someone else's fresh install -- a service
  call rejected at seed time, or a default quietly stuck at a value the UI cannot
  even reach.

CHECKS
  1. ghosts     - manifest entity not defined in any helper YAML
  2. conflicts  - manifest entity that still carries `initial:` (both mechanisms)
  3. bounds     - numeric default outside [min, max]
  4. options    - select default not among that helper's options
  5. dead       - default equal to the fallback HA already supplies (pure noise)
  6. private    - household identity that must never ship (see below)
  7. behaviour  - the seeder applies all of them to a fresh install, none to a
                  configured one

CHECK 6 IS THE ONE WITH TEETH
  The manifest is generated from a live household's config, and this repo is a
  PUBLIC mirror. The first generated draft carried the maintainer's own given
  name in `ai_context_user_name`, the household roster in
  `ai_context_household`, spoken-name pronunciations, per-person language
  lists, and a blocked-senders list holding real email addresses. All of it
  would have shipped as everyone's defaults -- greeting each new installation
  by a stranger's name, and undoing the 2026-03-29 shareability refactor that
  removed ~130 hardcoded personal references. Regenerating the manifest re-reads
  that same config, so the leak returns unless something checks every time.

  Names cannot be grepped for in a public repo without writing them into it,
  which is the same mistake. The two rules that generalise: per-household
  FILES, and value SHAPES (email address, bare IP, credential).

Exit 1 on any failure. Warnings (off-`step:` values) do not fail the build --
`step` is a UI hint and set_value accepts off-grid values.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path

# --repo lets this run against the live /config tree before a sync, so the check
# can be proven against the real files rather than only the mirror.
REPO = Path(
    sys.argv[sys.argv.index("--repo") + 1] if "--repo" in sys.argv
    else Path(__file__).resolve().parent.parent
)
COMPONENT = Path(__file__).resolve().parent.parent / "custom_components" / "project_fronkensteen"
MANIFEST = COMPONENT / "helper_defaults.json"

SEEDABLE = ("input_boolean", "input_number", "input_select", "input_text")

try:
    import yaml
except ImportError:  # pragma: no cover
    print("PyYAML required", file=sys.stderr)
    sys.exit(2)


class _Loader(yaml.SafeLoader):
    """Ignore HA tags (!secret, !include, ...) so the parse does not explode."""


for _tag in ("!secret", "!include", "!include_dir_named", "!include_dir_merge_named",
             "!include_dir_list", "!include_dir_merge_list", "!env_var", "!input"):
    _Loader.add_constructor(_tag, lambda loader, node: f"<{node.tag}>")


import re

# Files whose helpers describe one household -- names, languages, per-person
# thresholds. Nothing defined here may become a shipped default.
PER_HOUSEHOLD_FILES = ("ai_per_user_helpers.yaml",)

# Value shapes that are private regardless of which helper carries them.
PRIVATE_SHAPES = (
    ("an email address", re.compile(r"[\w.+-]+@[\w-]+\.[\w.]{2,}")),
    ("a bare IP address", re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")),
    ("a credential", re.compile(r"\b(?:sk-[A-Za-z0-9_-]{8,}|Bearer\s+\S+)")),
)


def load_helpers() -> tuple[dict[str, dict], set[str]]:
    """entity_id -> config, plus the ids that come from per-household files."""
    found: dict[str, dict] = {}
    household: set[str] = set()

    for path in sorted((REPO / "helpers").glob("helpers_input_*.yaml")):
        domain = path.stem[len("helpers_"):]
        if domain not in SEEDABLE:
            continue
        data = yaml.load(path.read_text(encoding="utf-8"), Loader=_Loader) or {}
        for object_id, cfg in data.items():
            if isinstance(cfg, dict):
                found[f"{domain}.{object_id}"] = cfg

    for path in sorted((REPO / "packages").glob("*.yaml")):
        data = yaml.load(path.read_text(encoding="utf-8"), Loader=_Loader) or {}
        if not isinstance(data, dict):
            continue
        for domain, block in data.items():
            if domain not in SEEDABLE or not isinstance(block, dict):
                continue
            for object_id, cfg in block.items():
                if isinstance(cfg, dict):
                    entity_id = f"{domain}.{object_id}"
                    found[entity_id] = cfg
                    if path.name in PER_HOUSEHOLD_FILES:
                        household.add(entity_id)

    return found, household


def fallback(entity_id: str, cfg: dict):
    domain = entity_id.split(".")[0]
    if domain == "input_boolean":
        return False
    if domain == "input_text":
        return ""
    if domain == "input_number":
        return cfg.get("min")
    if domain == "input_select":
        options = cfg.get("options") or []
        return options[0] if options else None
    return None


def as_bool(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("true", "on", "yes", "1")
    return bool(value)


def load_seeder():
    """Import seeder.py with a stubbed homeassistant, for the behaviour check."""
    ha = types.ModuleType("homeassistant")
    core = types.ModuleType("homeassistant.core")
    core.HomeAssistant = type("HomeAssistant", (), {})
    sys.modules.setdefault("homeassistant", ha)
    sys.modules.setdefault("homeassistant.core", core)
    spec = importlib.util.spec_from_file_location("seeder", COMPONENT / "seeder.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def behaviour_check(defaults: dict, helpers: dict, errors: list[str]) -> None:
    """A fresh install gets every default; a configured one gets nothing."""
    import asyncio

    seeder = load_seeder()

    class FakeState:
        def __init__(self, state, attributes):
            self.state, self.attributes = state, attributes

    class FakeHass:
        def __init__(self, states):
            self.calls = []
            outer = self

            class _States:
                def get(self, eid):
                    s = states.get(eid)
                    return FakeState(*s) if s else None

            class _Services:
                async def async_call(self, domain, service, data, blocking=False):
                    outer.calls.append((domain, service, data))

            class _Config:
                def path(self, *parts):
                    return str(COMPONENT / parts[-1])

            self.states, self.services, self.config = _States(), _Services(), _Config()

        async def async_add_executor_job(self, fn, *args):
            return fn(*args)

    fresh, configured = {}, {}
    for eid, value in defaults.items():
        cfg = helpers.get(eid, {})
        domain = eid.split(".")[0]
        attrs = {}
        if domain == "input_number":
            attrs = {"min": cfg.get("min"), "max": cfg.get("max")}
            fresh[eid] = (str(float(cfg.get("min", 0))), attrs)
            configured[eid] = (str(float(value)), attrs)
        elif domain == "input_select":
            attrs = {"options": cfg.get("options") or []}
            fresh[eid] = (attrs["options"][0] if attrs["options"] else "", attrs)
            configured[eid] = (str(value), attrs)
        elif domain == "input_boolean":
            fresh[eid] = ("off", {})
            configured[eid] = ("on" if as_bool(value) else "off", {})
        else:
            fresh[eid] = ("", {})
            configured[eid] = (str(value), {})

    async def run():
        hass = FakeHass(fresh)
        await seeder.seed(hass, [])
        if len(hass.calls) != len(defaults):
            errors.append(
                f"behaviour: fresh install seeded {len(hass.calls)} of {len(defaults)} helpers"
            )
        hass = FakeHass(configured)
        report = await seeder.seed(hass, [])
        if hass.calls:
            errors.append(
                f"behaviour: a configured install was written to "
                f"({len(hass.calls)} calls, first {hass.calls[0][2].get('entity_id')})"
            )
        if report["errors"]:
            errors.append(f"behaviour: seeder reported {report['errors'][:3]}")

    asyncio.run(run())


def main() -> int:
    defaults = json.loads(MANIFEST.read_text(encoding="utf-8"))
    helpers, household = load_helpers()
    errors: list[str] = []
    warnings: list[str] = []

    for eid, value in sorted(defaults.items()):
        domain = eid.split(".")[0]
        if domain not in SEEDABLE:
            errors.append(f"{eid}: domain {domain} cannot be seeded")
            continue

        if eid in household:
            errors.append(
                f"{eid}: defined in a per-household file, so its value describes "
                f"ONE house -- it must not ship as everyone's default"
            )
        if isinstance(value, str):
            for label, rx in PRIVATE_SHAPES:
                if rx.search(value):
                    errors.append(f"{eid}: default contains {label} -- not shippable")
                    break

        cfg = helpers.get(eid)
        if cfg is None:
            errors.append(f"{eid}: in the manifest, not defined in any helper YAML")
            continue

        if "initial" in cfg:
            errors.append(
                f"{eid}: has BOTH a manifest default and `initial:` -- "
                f"`initial:` wins and reverts it every boot"
            )

        if domain == "input_number":
            lo, hi = cfg.get("min"), cfg.get("max")
            if lo is None or hi is None:
                errors.append(f"{eid}: no min/max in the YAML")
            elif not (float(lo) <= float(value) <= float(hi)):
                errors.append(f"{eid}: default {value} outside [{lo}, {hi}]")
            else:
                step = cfg.get("step")
                if step and float(step) > 0:
                    n = (float(value) - float(lo)) / float(step)
                    if abs(n - round(n)) > 1e-9:
                        warnings.append(
                            f"{eid}: default {value} is off the step-{step} grid, "
                            f"so the UI slider cannot reach it"
                        )
        elif domain == "input_select":
            options = cfg.get("options") or []
            if value not in options:
                errors.append(f"{eid}: default {value!r} is not one of {options}")
        elif domain == "input_text":
            mx = cfg.get("max")
            if mx is not None and len(str(value)) > int(mx):
                errors.append(f"{eid}: default is {len(str(value))} chars, max is {mx}")

        want = fallback(eid, cfg)
        same = as_bool(value) == as_bool(want) if domain == "input_boolean" else value == want
        if want is not None and same:
            errors.append(
                f"{eid}: default equals the fallback HA already supplies -- drop it"
            )

    if not errors:
        behaviour_check(defaults, helpers, errors)

    print(f"helper defaults: {len(defaults)} checked against {len(helpers)} defined helpers")
    for w in warnings:
        print(f"  warning: {w}")
    for e in errors:
        print(f"  ERROR: {e}")
    print("  OK" if not errors else f"  {len(errors)} error(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
