#!/usr/bin/env python3
"""Fail when shipped files hardcode one household's entity IDs.

WHY THIS EXISTS
  Project Fronkensteen began as one household's working config, and much of it
  shipped as it was. An entity ID such as sensor.<someone's phone>_phone_state
  works in that house and silently does nothing in every other one: templates
  read an unknown entity, triggers never fire, and nothing logs an error. It
  bit at home too: renaming the maintainer's phone needed a release (v1.1.7).
  Rule AP-86: shipped code discovers entities at runtime or reads them from
  configuration (entity_config.yaml, blueprint inputs, helpers).

WHAT IS SCANNED
  Every file the installer ships, selected by the const.py manifests and read
  from the same repo paths scripts/sync_bundle.sh copies into the bundle:
  pyscript modules, packages, automation and script blueprints, helper files.
  Config templates are not scanned: they are filled in per household.

  - Python: string constants, minus docstrings (f-string literal parts too).
  - YAML: keys and string values, minus human-readable text (description,
    example, name, alias, title, friendly_name) and service calls (action,
    service). A service call is still checked when it targets script.* or
    notify.*, which name one household's scripts and devices.

WHAT IS ALLOWED
  - ai_* object IDs: created by the project itself
  - IDs ending in "_": prefixes completed at runtime, e.g. per person
  - entities the shipped files create themselves: state.set() targets,
    RESULT_ENTITY constants, named template/REST/platform sensors, helpers,
    scripts and automations defined in packages
  - ALLOWLIST below: IDs that are the same on every install that has them,
    each with its reason
  - CONVENTION_SCRIPTS below: script IDs that blueprints default to, created
    from a named blueprint under exactly that ID. INSTALL.md must list each
    one, or the check fails

  Hardcoded IDs that predate this check are grandfathered in
  scripts/hardcoded_entities_baseline.json, per file. The check fails on any
  other hardcoded ID, and on a baseline entry that no longer occurs. After
  fixing one, run with --update-baseline, which only ever removes entries.

Usage:  python3 scripts/check_hardcoded_entities.py [REPO_ROOT] [--update-baseline]
Exit 0 when clean, 1 otherwise.
"""

from __future__ import annotations

import ast
import json
import re
import sys
import unicodedata
from pathlib import Path

import yaml

from check_manifest import load_const

# const.py manifest -> repo directory it ships from (mirrors sync_bundle.sh).
SCANNED = {
    "PYSCRIPT_FILES": "pyscript",
    "PACKAGE_FILES": "packages",
    "BLUEPRINT_AUTOMATION_FILES": "automation",
    "BLUEPRINT_SCRIPT_FILES": "script",
    "HELPER_FILES": "helpers",
}

BASELINE = Path(__file__).with_name("hardcoded_entities_baseline.json")

# Entity IDs that are the same on every install that has them. Add here ONLY
# with a reason.
ALLOWLIST: dict[str, str] = {
    "sun.sun": "created by the sun integration, part of default_config",
    "zone.home": "always exists",
    "conversation.home_assistant": "Home Assistant's built-in Assist agent",
    "tts.home_assistant_cloud": "fixed entity ID of Home Assistant Cloud TTS",
    "stt.home_assistant_cloud": "fixed entity ID of Home Assistant Cloud STT",
    "update.home_assistant_core_update": "Home Assistant's own Core update entity",
    "media_player.unknown": "tts_queue.py sentinel for an unresolved speaker, not an entity",
}

# Project convention: blueprint inputs default to the script that the install
# guide (INSTALL.md, Step 12) tells you to create from this blueprint, under
# exactly this ID.
CONVENTION_SCRIPTS: dict[str, str] = {
    "script.refcount_bypass_claim": "refcount_bypass_claim.yaml",
    "script.refcount_bypass_release": "refcount_bypass_release.yaml",
    "script.wake_guard_tts_speak": "voice_wake_guard_tts_router.yaml",
    "script.wake_guard_stop_cleanup": "voice_wake_guard_cleanup.yaml",
    "script.voice_play_bedtime_audiobook": "voice_play_bedtime_audiobook.yaml",
    "script.voice_play_media": "voice_play_bedtime_audiobook.yaml, second instance",
    "script.voice_memory_tool": "luuquangvu memory_tool_full_llm.yaml, third-party",
}

# "<domain>.<service>" looks like an entity ID. A real entity is almost never
# named after one of its domain's services, so these objects are skipped.
SERVICE_NAMES = {
    "announce", "cancel", "clear_playlist", "close_cover", "create_event",
    "decrement", "finish", "get_events", "get_forecasts", "get_items",
    "increment", "join", "lock", "media_next_track", "media_pause",
    "media_play", "media_play_pause", "media_previous_track", "media_stop",
    "open_cover", "pause", "play_media", "press", "process", "reload",
    "remove_item", "repeat_set", "reset", "seek", "select_option",
    "select_source", "send_message", "set_datetime", "set_value",
    "shuffle_set", "speak", "start", "start_conversation", "stop_cover",
    "toggle", "trigger", "turn_off", "turn_on", "unjoin", "unlock",
    "volume_down", "volume_mute", "volume_set", "volume_up",
}

ENTITY_DOMAINS = (
    "air_quality", "alarm_control_panel", "assist_satellite", "automation",
    "binary_sensor", "button", "calendar", "camera", "climate", "conversation",
    "counter", "cover", "date", "datetime", "device_tracker", "event", "fan",
    "group", "humidifier", "image", "input_boolean", "input_button",
    "input_datetime", "input_number", "input_select", "input_text",
    "lawn_mower", "light", "lock", "media_player", "notify", "number",
    "person", "remote", "scene", "schedule", "script", "select", "sensor",
    "siren", "stt", "sun", "switch", "text", "time", "timer", "todo", "tts",
    "update", "vacuum", "valve", "water_heater", "weather", "zone",
)

# "<domain>.<object>" not inside a longer dotted name (so the event type
# extended_openai_conversation.conversation.finished is not one), except
# after Jinja's "states." (states.sensor.x is a reference), and not followed
# by "(" (group.split(...) is a method call on a variable).
ENTITY_RE = re.compile(
    r"(?:(?<=states\.)|(?<![\w.]))"
    r"(?P<domain>" + "|".join(sorted(ENTITY_DOMAINS, key=len, reverse=True)) + r")"
    r"\.(?P<obj>[a-z0-9_]+)\b(?!\s*\()"
)
FILE_EXTENSIONS = {"py", "yaml", "yml", "json", "js", "md", "txt", "db", "log",
                   "png", "jpg", "jpeg", "csv", "html", "sh", "template"}
JINJA_COMMENT = re.compile(r"\{#.*?#\}", re.DOTALL)
TEXT_KEYS = {"description", "example", "name", "alias", "title", "friendly_name"}
SERVICE_KEYS = {"action", "service"}


class _Loader(yaml.SafeLoader):
    """SafeLoader that reads HA's custom tags (!input, !secret, ...) as None."""


_Loader.add_multi_constructor("!", lambda loader, suffix, node: None)


def slugify(text: str) -> str:
    """Approximate HA's slugify, which derives entity IDs from names."""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", ascii_text.lower()).strip("_")


# ── Python ────────────────────────────────────────────────────────────────────

def python_strings(tree: ast.Module) -> list[tuple[int, int, str]]:
    """(first line, last line, text) for every string constant except docstrings."""
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            first = node.body[0] if node.body else None
            if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                docstrings.add(id(first.value))
    return [
        (node.lineno, node.end_lineno or node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        and id(node) not in docstrings
    ]


def python_owned(tree: ast.Module) -> set[str]:
    """Entities a module creates: state.set() targets and RESULT_ENTITY."""
    consts = {}
    for node in tree.body:
        if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    consts[target.id] = node.value.value
    owned = {v for k, v in consts.items() if k in ("RESULT_ENTITY", "_RESULT_ENTITY")}
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "set" and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "state" and node.args):
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                owned.add(arg.value)
            elif isinstance(arg, ast.Name) and arg.id in consts:
                owned.add(consts[arg.id])
    return owned


# ── YAML ──────────────────────────────────────────────────────────────────────

def _span(node) -> tuple[int, int]:
    return node.start_mark.line + 1, node.end_mark.line + 1


def yaml_strings(node, key=None) -> list[tuple[int, int, str]]:
    """(first line, last line, text) for keys and string values that could hold
    entity IDs. Works on the composed node graph, which keeps line numbers."""
    out = []
    if isinstance(node, yaml.MappingNode):
        for k_node, v_node in node.value:
            k = k_node.value if isinstance(k_node, yaml.ScalarNode) else None
            if isinstance(k, str):
                if k in TEXT_KEYS:
                    continue
                out.append((*_span(k_node), k))
            out.extend(yaml_strings(v_node, k))
    elif isinstance(node, yaml.SequenceNode):
        for item in node.value:
            out.extend(yaml_strings(item, key))
    elif isinstance(node, yaml.ScalarNode) and node.tag == "tag:yaml.org,2002:str":
        text = node.value
        if key in SERVICE_KEYS:
            # A service call names a service, not an entity, unless it runs one
            # household's script or notifies one device directly.
            if not text.startswith(("script.", "notify.")):
                return out
        out.append((*_span(node), JINJA_COMMENT.sub("", text)))
    return out


def yaml_owned(obj, domain: str | None = None) -> set[str]:
    """Entities a YAML file defines: helpers, scripts, named sensors, automations."""
    owned = set()
    if isinstance(obj, dict):
        if domain:
            label = obj.get("alias" if domain == "automation" else "name")
            if isinstance(label, str) and "{" not in label:
                owned.add(f"{domain}.{slugify(label)}")
            if isinstance(obj.get("default_entity_id"), str):
                owned.add(obj["default_entity_id"])
        if obj.get("action") == "pyscript.set_sensor_value" and isinstance(obj.get("data"), dict):
            target = obj["data"].get("entity_id")
            if isinstance(target, str):
                owned.add(target)
        for k, v in obj.items():
            if isinstance(k, str) and k in ENTITY_DOMAINS:
                if isinstance(v, dict):
                    owned.update(f"{k}.{name}" for name in v if isinstance(name, str))
                elif isinstance(v, list):
                    for item in v:
                        owned |= yaml_owned(item, k)
            else:
                owned |= yaml_owned(v)
    elif isinstance(obj, list):
        for item in obj:
            owned |= yaml_owned(item, domain)
    return owned


# ── Scan ──────────────────────────────────────────────────────────────────────

def shipped_files(repo: Path) -> list[Path]:
    const = load_const(repo / "custom_components" / "project_fronkensteen" / "const.py")
    files = []
    for manifest_name, directory in SCANNED.items():
        manifest = const.get(manifest_name) or []
        names = manifest.keys() if isinstance(manifest, dict) else manifest
        files.extend(repo / directory / name for name in sorted(names))
    return files


def load(path: Path) -> tuple[list[tuple[int, int, str]], set[str], list[str]]:
    """(strings with line spans, owned entities, raw lines) for one shipped file."""
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".py":
        tree = ast.parse(text, filename=str(path))
        return python_strings(tree), python_owned(tree), text.splitlines()
    node = yaml.compose(text, Loader=_Loader)
    data = yaml.load(text, Loader=_Loader)
    return yaml_strings(node), yaml_owned(data), text.splitlines()


def scan(repo: Path) -> dict[str, dict[str, int]]:
    """{repo-relative file: {hardcoded entity ID: first line it appears on}}."""
    loaded, owned = {}, set()
    for path in shipped_files(repo):
        if not path.is_file():
            continue  # check_manifest.py reports missing files
        strings, file_owned, lines = load(path)
        loaded[path] = (strings, lines)
        owned |= file_owned

    found: dict[str, dict[str, int]] = {}
    for path, (strings, lines) in loaded.items():
        rel = path.relative_to(repo).as_posix()
        for first, last, text in strings:
            for m in ENTITY_RE.finditer(text):
                entity_id, obj = m.group(0), m.group("obj")
                if (obj.startswith("ai_") or obj.endswith("_") or obj in FILE_EXTENSIONS
                        or obj in SERVICE_NAMES or entity_id in owned
                        or entity_id in ALLOWLIST or entity_id in CONVENTION_SCRIPTS):
                    continue
                # Folded YAML scalars join lines, so find the line in the source.
                line = next((n for n in range(first, min(last, len(lines)) + 1)
                             if entity_id in lines[n - 1]), first)
                previous = found.setdefault(rel, {}).get(entity_id)
                if previous is None or line < previous:
                    found[rel][entity_id] = line
    return found


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    repo = Path(args[0] if args else ".").resolve()
    found = scan(repo)

    baseline = json.loads(BASELINE.read_text(encoding="utf-8")) if BASELINE.is_file() else {}

    if "--update-baseline" in sys.argv:
        # Shrink-only: drop entries that were fixed, never grandfather new ones.
        # Only the very first run, with no baseline yet, records everything.
        if baseline:
            kept = {f: sorted(set(ids) & set(found.get(f, {})))
                    for f, ids in sorted(baseline.items())}
            kept = {f: ids for f, ids in kept.items() if ids}
        else:
            kept = {f: sorted(ids) for f, ids in sorted(found.items())}
        removed = sum(len(v) for v in baseline.values()) - sum(len(v) for v in kept.values())
        BASELINE.write_text(json.dumps(kept, indent=2) + "\n", encoding="utf-8")
        print(f"Baseline: {sum(len(v) for v in kept.values())} ID(s) in {len(kept)} "
              f"file(s); {max(removed, 0)} fixed ID(s) removed.")
        baseline = kept
    new = [(f, eid, line) for f, ids in sorted(found.items())
           for eid, line in sorted(ids.items()) if eid not in baseline.get(f, [])]
    stale = [(f, eid) for f, ids in sorted(baseline.items())
             for eid in ids if eid not in found.get(f, {})]

    install_guide = (repo / "INSTALL.md").read_text(encoding="utf-8")
    # Backticked, so script.x does not count as documenting script.x_y
    undocumented = [s for s in CONVENTION_SCRIPTS if f"`{s}`" not in install_guide]

    for f, eid, line in new:
        print(f"FAIL {f}:{line}: hardcoded entity ID {eid}")
    for s in undocumented:
        print(f"FAIL INSTALL.md: convention script {s} is not documented")
    for f, eid in stale:
        print(f"FAIL {f}: baseline lists {eid}, which no longer occurs")

    grandfathered = sum(len(v) for v in baseline.values()) - len(stale)
    if new:
        print(f"\n{len(new)} hardcoded entity ID(s). Shipped code must discover "
              f"entities at runtime or read them from configuration (AP-86); "
              f"an ID that every install has belongs in ALLOWLIST with a reason.")
    if stale:
        print(f"\n{len(stale)} fixed ID(s) still in the baseline. Run: "
              f"python3 scripts/check_hardcoded_entities.py --update-baseline")
    if undocumented:
        print(f"\n{len(undocumented)} convention script(s) missing from INSTALL.md "
              f"(Step 12, 'Script IDs Other Blueprints Expect').")
    if new or stale or undocumented:
        return 1

    print(f"No new hardcoded entity IDs ({grandfathered} grandfathered in "
          f"{BASELINE.name}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
