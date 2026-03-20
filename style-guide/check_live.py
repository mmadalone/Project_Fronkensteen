#!/usr/bin/env python3
"""
LIVE Codebase Validation — checks LIVE-1 through LIVE-6
Run from PROJECT_DIR: python3 check_live.py

Requires: PyYAML (python3 -c "import yaml")
"""

import json
import re
import sys
import yaml
from pathlib import Path
from collections import defaultdict

HA_CONFIG = Path(
    "/Users/madalone/Library/Containers/nz.co.pixeleyes.AutoMounter"
    "/Data/Mounts/Home Assistant/SMB/config"
)

BLUEPRINTS_AUTO = HA_CONFIG / "blueprints" / "automation" / "madalone"
BLUEPRINTS_SCRIPT = HA_CONFIG / "blueprints" / "script" / "madalone"
PYSCRIPT_DIR = HA_CONFIG / "pyscript"
PACKAGES_DIR = HA_CONFIG / "packages"

# Severity markers
ERROR = "[ERROR]"
WARNING = "[WARNING]"
INFO = "[INFO]"

findings = []


def report(sev, check_id, location, msg):
    findings.append(f"{sev} {check_id} | {location} | {msg}")


# ─────────────────────────────────────────────────────────────────────
# YAML Loader — handles HA custom tags
# ─────────────────────────────────────────────────────────────────────
class HALoader(yaml.SafeLoader):
    """YAML loader that handles HA-specific tags like !secret, !include, !input."""
    pass


def _ha_tag_constructor(loader, node):
    """Pass-through constructor for HA custom YAML tags."""
    try:
        val = loader.construct_scalar(node)
        return f"__{node.tag}_{val}__"
    except yaml.constructor.ConstructorError:
        # Handle sequence/mapping nodes (e.g., !include_dir_list)
        return None


for _tag in ("!secret", "!include", "!include_dir_list", "!include_dir_named",
             "!include_dir_merge_list", "!include_dir_merge_named", "!input",
             "!env_var", "!lambda"):
    HALoader.add_constructor(_tag, _ha_tag_constructor)


def load_yaml_safe(path):
    """Load YAML, returning None on failure."""
    try:
        with open(path, "r") as f:
            return yaml.load(f, Loader=HALoader)
    except Exception as e:
        report(WARNING, "INFRA", str(path.name), f"Failed to parse YAML: {e}")
        return None


def resolve_blueprint_path(bp_path):
    """Resolve a use_blueprint path to an actual file on disk."""
    for domain_dir in ("automation", "script"):
        candidate = HA_CONFIG / "blueprints" / domain_dir / bp_path
        if candidate.exists():
            return candidate
    return None


# ─────────────────────────────────────────────────────────────────────
# Blueprint Input Extraction
# ─────────────────────────────────────────────────────────────────────
def get_blueprint_inputs(blueprint_path):
    """Return dict of {input_name: has_default} for a blueprint file.

    Handles both flat inputs and collapsible sections (nested input: blocks).
    Collapsible sections have: name, icon, description, collapsed, input.
    """
    data = load_yaml_safe(blueprint_path)
    if not data or "blueprint" not in data:
        return None
    bp_inputs = data.get("blueprint", {}).get("input", {})
    if not bp_inputs:
        return {}

    result = {}

    def _extract_inputs(inputs_dict):
        if not isinstance(inputs_dict, dict):
            return
        for key, val in inputs_dict.items():
            if not isinstance(val, dict):
                result[key] = False
                continue
            # Collapsible section: has 'input' key with dict value
            if "input" in val and isinstance(val["input"], dict):
                _extract_inputs(val["input"])
            else:
                result[key] = "default" in val

    _extract_inputs(bp_inputs)
    return result


def get_blueprint_input_names(blueprint_path):
    """Return just the set of input names (for quick lookup)."""
    inputs = get_blueprint_inputs(blueprint_path)
    return set(inputs.keys()) if inputs is not None else None


# ─────────────────────────────────────────────────────────────────────
# Instance Extraction
# ─────────────────────────────────────────────────────────────────────
def extract_use_blueprint_blocks(yaml_path, is_list=True):
    """Extract use_blueprint blocks from automations.yaml (list) or scripts.yaml (dict).

    Returns list of (alias, blueprint_path, instance_inputs_dict).
    """
    data = load_yaml_safe(yaml_path)
    if data is None:
        return []

    blocks = []

    if is_list and isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            ub = item.get("use_blueprint")
            if not ub:
                continue
            alias = item.get("alias", item.get("id", "unknown"))
            bp_path = ub.get("path", "")
            inputs = ub.get("input", {}) or {}
            blocks.append((alias, bp_path, inputs))

    elif not is_list and isinstance(data, dict):
        for script_id, script_def in data.items():
            if not isinstance(script_def, dict):
                continue
            ub = script_def.get("use_blueprint")
            if not ub:
                continue
            alias = script_def.get("alias", script_id)
            bp_path = ub.get("path", "")
            inputs = ub.get("input", {}) or {}
            blocks.append((alias, bp_path, inputs))

    return blocks


# ─────────────────────────────────────────────────────────────────────
# LIVE-1: Instance ↔ Blueprint Input Alignment
# ─────────────────────────────────────────────────────────────────────
def check_live_1():
    print("\n── LIVE-1: Instance ↔ Blueprint Input Alignment ──")

    auto_blocks = extract_use_blueprint_blocks(HA_CONFIG / "automations.yaml", is_list=True)
    script_blocks = extract_use_blueprint_blocks(HA_CONFIG / "scripts.yaml", is_list=False)
    all_blocks = [("automations.yaml", b) for b in auto_blocks] + \
                 [("scripts.yaml", b) for b in script_blocks]

    blueprint_cache = {}

    for source_file, (alias, bp_path, instance_inputs) in all_blocks:
        if bp_path not in blueprint_cache:
            full_path = resolve_blueprint_path(bp_path)
            if full_path:
                blueprint_cache[bp_path] = get_blueprint_inputs(full_path)
            else:
                blueprint_cache[bp_path] = None

        bp_inputs = blueprint_cache[bp_path]
        if bp_inputs is None:
            continue

        for ikey in instance_inputs:
            if ikey not in bp_inputs:
                report(ERROR, "LIVE-1", f"{source_file} ({alias})",
                       f"Orphaned input '{ikey}' — not in {bp_path}")

        for bkey, has_default in bp_inputs.items():
            if not has_default and bkey not in instance_inputs:
                report(WARNING, "LIVE-1", f"{source_file} ({alias})",
                       f"Required input '{bkey}' (no default) missing — {bp_path}")


# ─────────────────────────────────────────────────────────────────────
# LIVE-2: Pipeline Name Existence
# ─────────────────────────────────────────────────────────────────────

# Input names that hold pipeline/agent references
PIPELINE_INPUT_NAMES = {
    "conversation_agent", "llm_agent", "llm_agent_id", "persona_agent_id",
    "bedtime_conversation_agent", "fallback_pipeline", "dispatcher_agent",
    "pipeline_name", "pipeline",
}
# Also match agent_1 through agent_10
PIPELINE_INPUT_PATTERN = re.compile(r'^agent_\d+$')

# Patterns that indicate a stale entity ID or ULID (AP-54)
ULID_PATTERN = re.compile(r'^[0-9A-Z]{26}$')  # 26-char uppercase alphanumeric
ENTITY_ID_PATTERN = re.compile(r'^conversation\.\w+$')


# Input names that are entity selectors, NOT pipeline display names
PIPELINE_ENTITY_INPUTS = {
    "pipeline_select", "pipeline_selector", "pipeline_entity",
}


def _is_pipeline_input(name):
    """Check if an input name holds a pipeline display name (not an entity selector)."""
    name_lower = name.lower()
    # Exclude entity selector inputs that contain "pipeline" but hold entity IDs
    if name_lower in PIPELINE_ENTITY_INPUTS:
        return False
    if name_lower in PIPELINE_INPUT_NAMES:
        return True
    if PIPELINE_INPUT_PATTERN.match(name_lower):
        return True
    if "pipeline" in name_lower and "select" not in name_lower:
        return True
    return False


def check_live_2():
    print("\n── LIVE-2: Pipeline Name Existence ──")

    # 1. Load pipeline storage to get valid display names
    pipeline_file = HA_CONFIG / ".storage" / "assist_pipeline.pipelines"
    pipeline_names = set()

    if pipeline_file.exists():
        try:
            with open(pipeline_file) as f:
                pdata = json.load(f)
            # Structure: {"data": {"items": [{"name": "...", ...}, ...]}}
            items = pdata.get("data", {}).get("items", [])
            for item in items:
                name = item.get("name", "")
                if name:
                    pipeline_names.add(name.lower())
        except Exception as e:
            report(ERROR, "LIVE-2", ".storage/assist_pipeline", f"Failed to parse: {e}")
            return
    else:
        report(WARNING, "LIVE-2", ".storage/assist_pipeline", "Pipeline storage file not found")
        return

    print(f"  Found {len(pipeline_names)} pipelines: {', '.join(sorted(pipeline_names))}")

    # 2. Check blueprint defaults
    for bp_dir in (BLUEPRINTS_AUTO, BLUEPRINTS_SCRIPT):
        for bp_file in sorted(bp_dir.glob("*.yaml")):
            data = load_yaml_safe(bp_file)
            if not data or "blueprint" not in data:
                continue
            bp_inputs = data.get("blueprint", {}).get("input", {})
            if not bp_inputs:
                continue

            def _check_defaults(inputs_dict, file_name):
                if not isinstance(inputs_dict, dict):
                    return
                for iname, ival in inputs_dict.items():
                    if not isinstance(ival, dict):
                        continue
                    # Recurse into collapsible sections
                    if "input" in ival and isinstance(ival["input"], dict):
                        _check_defaults(ival["input"], file_name)
                        continue
                    if not _is_pipeline_input(iname):
                        continue
                    default_val = ival.get("default", "")
                    if not isinstance(default_val, str) or not default_val:
                        continue
                    _check_pipeline_value(default_val, f"{file_name} (default: {iname})")

            _check_defaults(bp_inputs, bp_file.name)

    # 3. Check instance values in automations.yaml and scripts.yaml
    auto_blocks = extract_use_blueprint_blocks(HA_CONFIG / "automations.yaml", is_list=True)
    script_blocks = extract_use_blueprint_blocks(HA_CONFIG / "scripts.yaml", is_list=False)
    all_blocks = [("automations.yaml", b) for b in auto_blocks] + \
                 [("scripts.yaml", b) for b in script_blocks]

    for source_file, (alias, _bp_path, instance_inputs) in all_blocks:
        for iname, ival in instance_inputs.items():
            if not _is_pipeline_input(iname):
                continue
            if not isinstance(ival, str) or not ival:
                continue
            _check_pipeline_value(ival, f"{source_file} ({alias}) → {iname}")

    def _check_pipeline_value(val, location):
        # AP-54: entity ID or ULID
        if ENTITY_ID_PATTERN.match(val):
            report(ERROR, "LIVE-2", location,
                   f"AP-54: Entity ID '{val}' used as pipeline selector — use display name")
            return
        if ULID_PATTERN.match(val):
            report(ERROR, "LIVE-2", location,
                   f"AP-54: ULID '{val}' used as pipeline selector — use display name")
            return
        # Check against known pipeline names (case-insensitive)
        if val.lower() not in pipeline_names:
            # Skip template expressions (contain {{ or {%)
            if "{{" in val or "{%" in val:
                return
            report(WARNING, "LIVE-2", location,
                   f"Pipeline name '{val}' not found in assist_pipeline storage")

    # Re-run the checks with the inner function now defined
    # (Python quirk: inner function was defined after calls — restructure)
    pass


def check_live_2_v2():
    """Properly structured LIVE-2 check."""
    print("\n── LIVE-2: Pipeline Name Existence ──")

    pipeline_file = HA_CONFIG / ".storage" / "assist_pipeline.pipelines"
    pipeline_names = set()

    if pipeline_file.exists():
        try:
            with open(pipeline_file) as f:
                pdata = json.load(f)
            items = pdata.get("data", {}).get("items", [])
            for item in items:
                name = item.get("name", "")
                if name:
                    pipeline_names.add(name.lower())
        except Exception as e:
            report(ERROR, "LIVE-2", ".storage/assist_pipeline", f"Failed to parse: {e}")
            return
    else:
        report(WARNING, "LIVE-2", ".storage/assist_pipeline", "Pipeline storage file not found")
        return

    print(f"  Found {len(pipeline_names)} pipelines: {', '.join(sorted(pipeline_names))}")

    def _check_pipeline_value(val, location):
        if ENTITY_ID_PATTERN.match(val):
            report(ERROR, "LIVE-2", location,
                   f"AP-54: Entity ID '{val}' used as pipeline selector — use display name")
            return
        if ULID_PATTERN.match(val):
            report(ERROR, "LIVE-2", location,
                   f"AP-54: ULID '{val}' used as pipeline selector — use display name")
            return
        if "{{" in val or "{%" in val:
            return  # Jinja template — can't validate statically
        if val.lower() not in pipeline_names:
            report(WARNING, "LIVE-2", location,
                   f"Pipeline name '{val}' not found in assist_pipeline storage")

    # Check blueprint defaults
    for bp_dir in (BLUEPRINTS_AUTO, BLUEPRINTS_SCRIPT):
        for bp_file in sorted(bp_dir.glob("*.yaml")):
            data = load_yaml_safe(bp_file)
            if not data or "blueprint" not in data:
                continue
            bp_inputs = data.get("blueprint", {}).get("input", {})
            if not bp_inputs:
                continue

            def _check_defaults(inputs_dict, file_name):
                if not isinstance(inputs_dict, dict):
                    return
                for iname, ival in inputs_dict.items():
                    if not isinstance(ival, dict):
                        continue
                    if "input" in ival and isinstance(ival["input"], dict):
                        _check_defaults(ival["input"], file_name)
                        continue
                    if not _is_pipeline_input(iname):
                        continue
                    default_val = ival.get("default", "")
                    if not isinstance(default_val, str) or not default_val:
                        continue
                    _check_pipeline_value(default_val, f"{file_name} (default: {iname})")

            _check_defaults(bp_inputs, bp_file.name)

    # Check instance values
    auto_blocks = extract_use_blueprint_blocks(HA_CONFIG / "automations.yaml", is_list=True)
    script_blocks = extract_use_blueprint_blocks(HA_CONFIG / "scripts.yaml", is_list=False)
    all_blocks = [("automations.yaml", b) for b in auto_blocks] + \
                 [("scripts.yaml", b) for b in script_blocks]

    for source_file, (alias, _bp_path, instance_inputs) in all_blocks:
        for iname, ival in instance_inputs.items():
            if not _is_pipeline_input(iname):
                continue
            if not isinstance(ival, str) or not ival:
                continue
            _check_pipeline_value(ival, f"{source_file} ({alias}) → {iname}")


# ─────────────────────────────────────────────────────────────────────
# LIVE-3: Pyscript Service Signature Drift (YAML-parsed, not regex)
# ─────────────────────────────────────────────────────────────────────
def extract_pyscript_signatures():
    """Return dict of {service_name: {param_name: has_default}}."""
    signatures = {}

    for py_file in sorted(PYSCRIPT_DIR.glob("*.py")):
        try:
            content = py_file.read_text()
        except Exception:
            continue

        # Find @service decorated functions with multi-line support
        pattern = re.compile(
            r'@service[^\n]*\n'
            r'(?:async\s+)?def\s+'
            r'(\w+)\s*\('
            r'(.*?)\)\s*(?:->.*?)?:',
            re.DOTALL
        )

        for match in pattern.finditer(content):
            func_name = match.group(1)
            params_str = match.group(2).strip()

            params = {}
            if params_str:
                depth = 0
                current = ""
                for ch in params_str:
                    if ch in "([{":
                        depth += 1
                    elif ch in ")]}":
                        depth -= 1
                    elif ch == "," and depth == 0:
                        _parse_param(current.strip(), params)
                        current = ""
                        continue
                    current += ch
                _parse_param(current.strip(), params)

            signatures[func_name] = params

    return signatures


def _parse_param(param_str, params_dict):
    """Parse a single parameter string into params_dict."""
    if not param_str or param_str == "self":
        return
    pname = param_str.split(":")[0].split("=")[0].strip()
    has_default = "=" in param_str
    if pname and pname != "**kwargs" and not pname.startswith("*"):
        params_dict[pname] = has_default


def _walk_yaml_actions(data, callback, path=""):
    """Recursively walk a YAML structure finding all action: pyscript.* calls.

    Calls callback(service_name, data_keys, location) for each found call.
    Handles: lists, dicts, choose/default/conditions/sequence/repeat blocks.
    """
    if isinstance(data, list):
        for i, item in enumerate(data):
            _walk_yaml_actions(item, callback, f"{path}[{i}]")
    elif isinstance(data, dict):
        # Check if this dict is a pyscript action call
        action = data.get("action", "")
        if isinstance(action, str) and action.startswith("pyscript."):
            service_name = action[len("pyscript."):]
            data_block = data.get("data", {})
            data_keys = set()
            if isinstance(data_block, dict):
                data_keys = set(data_block.keys())
            callback(service_name, data_keys, path)

        # Recurse into known structural keys
        for key in ("action", "actions", "sequence", "default", "then", "else",
                     "steps", "repeat"):
            if key in data:
                _walk_yaml_actions(data[key], callback, f"{path}.{key}")

        # Handle choose blocks
        if "choose" in data and isinstance(data["choose"], list):
            for i, choice in enumerate(data["choose"]):
                if isinstance(choice, dict) and "sequence" in choice:
                    _walk_yaml_actions(choice["sequence"], callback,
                                      f"{path}.choose[{i}].sequence")

        # Handle if/then/else
        if "if" in data and "then" in data:
            _walk_yaml_actions(data["then"], callback, f"{path}.then")
            if "else" in data:
                _walk_yaml_actions(data["else"], callback, f"{path}.else")


def check_live_3():
    print("\n── LIVE-3: Pyscript Service Signature Drift ──")

    signatures = extract_pyscript_signatures()
    print(f"  Found {len(signatures)} pyscript services")

    # Collect all YAML files to check
    yaml_sources = []

    # Blueprints — parse the full YAML structure
    for bp_dir in (BLUEPRINTS_AUTO, BLUEPRINTS_SCRIPT):
        yaml_sources.extend(sorted(bp_dir.glob("*.yaml")))

    # Packages
    yaml_sources.extend(sorted(PACKAGES_DIR.glob("*.yaml")))

    # automations.yaml and scripts.yaml
    yaml_sources.append(HA_CONFIG / "automations.yaml")
    yaml_sources.append(HA_CONFIG / "scripts.yaml")

    for yf in yaml_sources:
        data = load_yaml_safe(yf)
        if data is None:
            continue

        rel_path = yf.name

        def _check_call(service_name, data_keys, location):
            if service_name not in signatures:
                return  # PSY-5 territory

            func_params = signatures[service_name]

            for dk in sorted(data_keys):
                if dk not in func_params:
                    report(ERROR, "LIVE-3",
                           f"{rel_path}{location} → pyscript.{service_name}",
                           f"Data key '{dk}' not in function signature "
                           f"(params: {', '.join(sorted(func_params.keys())) or 'none'})")

            for pname, has_default in func_params.items():
                if not has_default and pname not in data_keys:
                    report(WARNING, "LIVE-3",
                           f"{rel_path}{location} → pyscript.{service_name}",
                           f"Required param '{pname}' (no default) not provided")

        _walk_yaml_actions(data, _check_call)


# ─────────────────────────────────────────────────────────────────────
# LIVE-4: Helper Entity Definition Completeness
# ─────────────────────────────────────────────────────────────────────
def check_live_4():
    print("\n── LIVE-4: Helper Entity Definition Completeness ──")

    helper_domains = ["input_boolean", "input_number", "input_text",
                      "input_select", "input_datetime"]
    entity_pattern = re.compile(
        r"""(?:^|['"(\s,=])"""          # preceded by boundary
        r'(input_(?:boolean|number|text|select|datetime))'
        r'\.'
        r'(\w+)'
        r"""(?=['")\s,\]}|]|$)"""       # followed by boundary
    )

    # Service calls / method calls that look like entity references
    SERVICE_SUFFIXES = {
        "set_value", "reload", "turn_on", "turn_off", "toggle",
        "increment", "decrement", "select_option", "select_first",
        "select_last", "select_next", "select_previous", "set_options",
        "set_datetime",
    }

    # 1. Collect references from pyscript modules
    referenced = set()
    ref_sources = defaultdict(set)

    for py_file in sorted(PYSCRIPT_DIR.glob("*.py")):
        try:
            lines = py_file.read_text().splitlines()
        except Exception:
            continue
        for lineno, line in enumerate(lines, 1):
            # Skip comment lines
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            for match in entity_pattern.finditer(line):
                domain = match.group(1)
                name = match.group(2)
                entity = f"{domain}.{name}"
                # Skip service calls
                if name in SERVICE_SUFFIXES:
                    continue
                # Skip dynamic patterns (trailing underscore = prefix for f-string)
                if name.endswith("_"):
                    continue
                referenced.add(entity)
                ref_sources[entity].add(py_file.name)

    # 2. Collect references from ai_* packages
    for pkg_file in sorted(PACKAGES_DIR.glob("ai_*.yaml")):
        try:
            lines = pkg_file.read_text().splitlines()
        except Exception:
            continue
        for lineno, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            for match in entity_pattern.finditer(line):
                domain = match.group(1)
                name = match.group(2)
                entity = f"{domain}.{name}"
                if name in SERVICE_SUFFIXES:
                    continue
                if name.endswith("_"):
                    continue
                referenced.add(entity)
                ref_sources[entity].add(pkg_file.name)

    # 3. Collect definitions from helper files
    defined = set()

    for domain in helper_domains:
        helper_file = HA_CONFIG / f"helpers_{domain}.yaml"
        if not helper_file.exists():
            continue
        data = load_yaml_safe(helper_file)
        if isinstance(data, dict):
            for key in data:
                defined.add(f"{domain}.{key}")

    # 4. Collect definitions from packages
    for pkg_file in sorted(PACKAGES_DIR.glob("*.yaml")):
        data = load_yaml_safe(pkg_file)
        if not isinstance(data, dict):
            continue
        for domain in helper_domains:
            if domain in data and isinstance(data[domain], dict):
                for key in data[domain]:
                    defined.add(f"{domain}.{key}")

    # 5. Set differences
    missing = referenced - defined
    orphaned = defined - referenced

    for entity in sorted(missing):
        sources = ", ".join(sorted(ref_sources[entity]))
        sev = ERROR
        note = ""
        report(sev, "LIVE-4", sources,
               f"Helper '{entity}' referenced but not defined in YAML{note}")

    for entity in sorted(orphaned):
        report(INFO, "LIVE-4", "helpers/packages",
               f"Helper '{entity}' defined but never referenced in pyscript/ai_* packages")


# ─────────────────────────────────────────────────────────────────────
# LIVE-5: Orphaned Automation/Script Instances
# ─────────────────────────────────────────────────────────────────────
def check_live_5():
    print("\n── LIVE-5: Orphaned Automation/Script Instances ──")

    auto_blocks = extract_use_blueprint_blocks(HA_CONFIG / "automations.yaml", is_list=True)
    script_blocks = extract_use_blueprint_blocks(HA_CONFIG / "scripts.yaml", is_list=False)
    all_blocks = [("automations.yaml", b) for b in auto_blocks] + \
                 [("scripts.yaml", b) for b in script_blocks]

    seen_paths = set()

    for source_file, (alias, bp_path, _inputs) in all_blocks:
        if bp_path in seen_paths:
            continue

        found = resolve_blueprint_path(bp_path) is not None

        if not found:
            archive_candidates = [
                HA_CONFIG / "blueprints" / "automation" / bp_path.replace(
                    "madalone/", "madalone/archive/"),
                HA_CONFIG / "blueprints" / "script" / bp_path.replace(
                    "madalone/", "madalone/archive/"),
            ]
            archived = any(c.exists() for c in archive_candidates)

            if archived:
                report(WARNING, "LIVE-5", f"{source_file} ({alias})",
                       f"Blueprint '{bp_path}' was archived — stale instance")
            else:
                report(ERROR, "LIVE-5", f"{source_file} ({alias})",
                       f"Blueprint '{bp_path}' does not exist on disk")
        seen_paths.add(bp_path)


# ─────────────────────────────────────────────────────────────────────
# LIVE-6: Cross-File Variable Consistency
# ─────────────────────────────────────────────────────────────────────
def check_live_6():
    print("\n── LIVE-6: Cross-File Variable Consistency ──")

    # Template reference patterns: {{ v_xxx }}, {{ v_xxx | filter }}, {{v_xxx}}
    # Also handle: {% set x = v_xxx %}, {% if v_xxx %}
    ref_pattern = re.compile(r'\bv_(\w+)')

    for bp_dir in (BLUEPRINTS_AUTO, BLUEPRINTS_SCRIPT):
        for bp_file in sorted(bp_dir.glob("*.yaml")):
            try:
                content = bp_file.read_text()
                lines = content.splitlines()
            except Exception:
                continue

            # 1. Extract all variable definitions from variables: blocks
            #    Use YAML parsing for accuracy
            data = load_yaml_safe(bp_file)
            if data is None:
                continue

            defined_vars = set()
            _collect_variable_defs(data, defined_vars)

            # 2. Find all v_* references in Jinja templates
            #    Scan raw text for {{ ... v_xxx ... }} and {% ... v_xxx ... %}
            #    Also collect {% set v_xxx = ... %} as template-local definitions
            jinja_set_pattern = re.compile(r'\{%[-\s]*set\s+(v_\w+)')
            referenced_vars = set()
            for lineno, line in enumerate(lines, 1):
                # Collect {% set v_xxx %} as template-local definitions
                for set_match in jinja_set_pattern.finditer(line):
                    defined_vars.add(set_match.group(1))
                # Only look inside Jinja expressions
                for jinja_match in re.finditer(r'\{\{.*?\}\}|\{%.*?%\}', line):
                    jinja_expr = jinja_match.group()
                    for var_match in ref_pattern.finditer(jinja_expr):
                        referenced_vars.add(f"v_{var_match.group(1)}")

                # Also check bare template lines (in >- or | blocks)
                # These are lines that ARE templates but don't have {{ }} on
                # this specific line — they're part of a multi-line template
                # We need a smarter approach: check if we're inside a template value

            # 3. Also collect v_* from variables: block values that are templates
            #    These define vars using other vars (e.g., v_foo: "{{ v_bar }}")
            _collect_template_refs_from_vars(data, referenced_vars, ref_pattern)

            # 4. Compare
            # Undefined references (referenced but not in variables: block)
            undefined = referenced_vars - defined_vars
            # Dead variables (defined but never referenced)
            dead = defined_vars - referenced_vars

            for var in sorted(undefined):
                # Check if it might be a blueprint input name with v_ prefix
                # (HA makes inputs available by name in templates)
                input_name = var  # v_xxx could be input named v_xxx
                input_name_no_prefix = var[2:]  # or input named xxx
                # This is valid HA behavior — inputs are in scope
                # Only flag if it's truly not an input AND not a variable
                report(ERROR, "LIVE-6", bp_file.name,
                       f"Template references '{var}' but no variables: definition found")

            for var in sorted(dead):
                report(INFO, "LIVE-6", bp_file.name,
                       f"Variable '{var}' defined in variables: but never referenced in templates")


def _collect_variable_defs(data, defined_vars):
    """Recursively find all variables: blocks and collect their keys."""
    if isinstance(data, dict):
        if "variables" in data and isinstance(data["variables"], dict):
            for key in data["variables"]:
                if key.startswith("v_") or key.startswith("_"):
                    defined_vars.add(key)
        for val in data.values():
            _collect_variable_defs(val, defined_vars)
    elif isinstance(data, list):
        for item in data:
            _collect_variable_defs(item, defined_vars)


def _collect_template_refs_from_vars(data, referenced_vars, pattern):
    """Find v_* references inside variables: block values (inter-variable refs)."""
    if isinstance(data, dict):
        if "variables" in data and isinstance(data["variables"], dict):
            for key, val in data["variables"].items():
                if isinstance(val, str):
                    for match in pattern.finditer(val):
                        var_name = f"v_{match.group(1)}"
                        if var_name != key:  # Don't count self-references
                            referenced_vars.add(var_name)
        for val in data.values():
            _collect_template_refs_from_vars(val, referenced_vars, pattern)
    elif isinstance(data, list):
        for item in data:
            _collect_template_refs_from_vars(item, referenced_vars, pattern)


# ─────────────────────────────────────────────────────────────────────
# LIVE-7: TTS Sanitization Validation
# ─────────────────────────────────────────────────────────────────────
def _import_sanitizer():
    """Import _sanitize_tool_narration from tts_queue.py via minimal shim.

    Injects no-op shims for pyscript globals/decorators, imports the module,
    extracts the function, then cleans up completely.  Returns the function
    or None on failure.
    """
    import builtins
    import importlib

    class _Noop:
        """Catch-all mock — any attribute access returns a silent callable."""
        def __getattr__(self, _):
            return lambda *a, **kw: None
        def __call__(self, *a, **kw):
            return None

    _sentinel = object()

    def _decorator_noop(_f=None, **kw):
        if _f is not None:
            return _f
        return lambda f: f

    _inject = {
        'state': _Noop(),
        'log': _Noop(),
        'event': _Noop(),
        'task': _Noop(),
        'pyscript': _Noop(),
        'pyscript_compile': lambda f: f,
        'service': _decorator_noop,
        'state_trigger': lambda *a, **kw: lambda f: f,
        'time_trigger': lambda *a, **kw: lambda f: f,
        'event_trigger': lambda *a, **kw: lambda f: f,
    }

    originals = {n: getattr(builtins, n, _sentinel) for n in _inject}
    for n, obj in _inject.items():
        setattr(builtins, n, obj)

    # Mock shared_utils (lives in pyscript/modules/) via sys.modules injection
    # — standard Python pattern for synthetic module mocking during import
    from types import ModuleType
    mock_shared = ModuleType("shared_utils")
    mock_shared.build_result_entity_name = lambda entity_id: {"friendly_name": entity_id}
    sys.modules["shared_utils"] = mock_shared

    pyscript_str = str(PYSCRIPT_DIR)
    path_added = pyscript_str not in sys.path
    if path_added:
        sys.path.insert(0, pyscript_str)
    sys.modules.pop('tts_queue', None)

    try:
        mod = importlib.import_module('tts_queue')
        return getattr(mod, '_sanitize_tool_narration', None)
    except Exception as e:
        report(WARNING, "LIVE-7", "tts_queue.py", f"Could not import: {e}")
        return None
    finally:
        for n, orig in originals.items():
            if orig is _sentinel:
                if hasattr(builtins, n):
                    delattr(builtins, n)
            else:
                setattr(builtins, n, orig)
        sys.modules.pop('tts_queue', None)
        sys.modules.pop('shared_utils', None)
        if path_added and pyscript_str in sys.path:
            sys.path.remove(pyscript_str)


# Each tuple: (input_text, expected_result)
#   expected_result can be:
#     str  — sanitized output must equal this exactly
#     None — sanitized output must be None (everything stripped)
#     ("contains", substr) — output must contain substr
#     ("not_contains", substr) — output must NOT contain substr
_SANITIZE_CASES = [
    # ── Tool narration ──
    ("I'll call execute_services now.",
     None),
    ("Let me use the memory_tool to check.",
     None),
    ("Using web_search to find that.",
     None),
    ("execute_services",
     None),
    # ── Entity IDs ──
    ("The light.living_room is on",
     ("not_contains", "light.living_room")),
    ("Check sensor.temperature for the reading",
     ("not_contains", "sensor.temperature")),
    # ── JSON fragments ──
    ('Found {"key": "value"} in response',
     ("not_contains", '"key"')),
    # ── URLs ──
    ("Visit https://example.com/path for details",
     ("not_contains", "https://")),
    # ── Email headers ──
    ("Content-Type: text/plain; charset=utf-8",
     None),
    # ── Base64 ──
    ("Data: QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVphYmNkZWY=",
     ("not_contains", "QUJDREVG")),
    # ── CSS ──
    ("font-size: 14px; color: red",
     None),
    # ── Hex colors ──
    ("The color is #FF5733 today",
     ("not_contains", "#FF5733")),
    # ── Footer / legal ──
    ("Thanks! Unsubscribe from this list.",
     ("not_contains", "nsubscribe")),
    ("© 2026 Acme Corp. All rights reserved.",
     None),
    ("OK. Sent from my iPhone",
     ("not_contains", "iPhone")),
    # ── Tracking params ──
    ("Link: page?utm_source=email&fbclid=abc",
     ("not_contains", "utm_source")),
    # ── Clean passthrough ──
    ("The weather is sunny and warm",
     "The weather is sunny and warm"),
    # ── Mixed ──
    ("It's 22 degrees. I'll call execute_services. Enjoy!",
     ("contains", "22 degrees")),
    # ── All stripped → None ──
    ("execute_services light.living_room",
     None),
    # ── Param assignment ──
    ('Setting target="light.kitchen" now',
     ("not_contains", 'target="light.kitchen"')),
]


def check_live_7():
    print("\n── LIVE-7: TTS Sanitization Validation ──")

    sanitize = _import_sanitizer()
    if sanitize is None:
        report(ERROR, "LIVE-7", "tts_queue.py",
               "Could not import _sanitize_tool_narration — skipping tests")
        return

    passed = 0
    failed = 0

    for i, (input_text, expected) in enumerate(_SANITIZE_CASES, 1):
        result = sanitize(input_text)

        ok = False
        if expected is None:
            ok = result is None or (isinstance(result, str) and result.strip() == "")
        elif isinstance(expected, str):
            ok = result == expected
        elif isinstance(expected, tuple):
            mode, substr = expected
            if result is None:
                ok = (mode == "not_contains")
            elif mode == "contains":
                ok = substr in result
            elif mode == "not_contains":
                ok = substr not in result

        if ok:
            passed += 1
        else:
            failed += 1
            # Truncate for readability
            r_display = repr(result)[:80] if result else repr(result)
            report(ERROR, "LIVE-7", f"case {i}",
                   f"Input: {repr(input_text)[:60]}... | Got: {r_display} | Expected: {repr(expected)[:60]}")

    print(f"  {passed}/{passed + failed} sanitization cases passed")


# ─────────────────────────────────────────────────────────────────────
# LIVE-8: Duck Guard Coverage Audit
# ─────────────────────────────────────────────────────────────────────
def check_live_8():
    print("\n── LIVE-8: Duck Guard Coverage Audit ──")

    # Blueprints that intentionally skip duck guard (they ARE the duck system)
    live8_suppress = {"duck_refcount_watchdog.yaml"}

    for bp_dir in (BLUEPRINTS_AUTO, BLUEPRINTS_SCRIPT):
        for bp_file in sorted(bp_dir.glob("*.yaml")):
            if bp_file.name in live8_suppress:
                continue
            try:
                content = bp_file.read_text()
            except Exception:
                continue

            # Quick scan: does this blueprint use media_player.volume_set?
            if "media_player.volume_set" not in content:
                continue

            # Count volume_set calls and duck_manager_update_snapshot calls
            vol_set_count = len(re.findall(
                r'action:\s*media_player\.volume_set', content))
            duck_guard_count = len(re.findall(
                r'action:\s*pyscript\.duck_manager_update_snapshot', content))

            if vol_set_count > 0 and duck_guard_count == 0:
                report(WARNING, "LIVE-8", bp_file.name,
                       f"{vol_set_count} volume_set call(s) with no duck guard "
                       f"(pyscript.duck_manager_update_snapshot)")
            elif vol_set_count > duck_guard_count:
                report(INFO, "LIVE-8", bp_file.name,
                       f"{vol_set_count} volume_set vs {duck_guard_count} duck guard "
                       f"— some sites may be unguarded")


# ─────────────────────────────────────────────────────────────────────
# LIVE-9: Test Mode Coverage
# ─────────────────────────────────────────────────────────────────────
def check_live_9():
    print("\n── LIVE-9: Test Mode Coverage ──")

    for py_file in sorted(PYSCRIPT_DIR.glob("*.py")):
        try:
            content = py_file.read_text()
        except Exception:
            continue

        has_service = bool(re.search(r'@service\b', content))
        has_test_mode = bool(re.search(
            r'def\s+_(?:is_test_mode|check_test_mode)\s*\(', content))

        if has_service and not has_test_mode:
            report(INFO, "LIVE-9", py_file.name,
                   "Has @service functions but no _is_test_mode() / _check_test_mode() gate")


# ─────────────────────────────────────────────────────────────────────
# Verification Pass
# ─────────────────────────────────────────────────────────────────────
def verify_live_1_sample(sample_size=10):
    """Double-check LIVE-1 findings by re-reading blueprint files directly."""
    live1_findings = [f for f in findings if "LIVE-1" in f and f.startswith(ERROR)]
    if not live1_findings:
        return

    print(f"\n── Verification: spot-checking {min(sample_size, len(live1_findings))} LIVE-1 findings ──")

    verified = 0
    failed = 0

    for finding in live1_findings[:sample_size]:
        # Parse: [ERROR] LIVE-1 | automations.yaml (Alias) | Orphaned input 'key' — not in path
        match = re.search(r"Orphaned input '(\w+)' — not in (.+)$", finding)
        if not match:
            continue
        input_key = match.group(1)
        bp_rel_path = match.group(2)

        full_path = resolve_blueprint_path(bp_rel_path)
        if not full_path:
            print(f"  VERIFY FAIL: Blueprint not found: {bp_rel_path}")
            failed += 1
            continue

        bp_inputs = get_blueprint_inputs(full_path)
        if bp_inputs is None:
            print(f"  VERIFY FAIL: Could not parse blueprint: {bp_rel_path}")
            failed += 1
            continue

        if input_key in bp_inputs:
            print(f"  FALSE POSITIVE: '{input_key}' IS defined in {bp_rel_path}")
            failed += 1
        else:
            verified += 1

    print(f"  Verified: {verified}/{verified + failed} "
          f"({'100%' if failed == 0 else f'{failed} FALSE POSITIVE(S)'})")


# ─────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────
def main():
    if not HA_CONFIG.exists():
        print(f"ERROR: HA_CONFIG not accessible at {HA_CONFIG}")
        print("Mount the SMB share first.")
        sys.exit(1)

    print(f"Running LIVE codebase validation against:")
    print(f"  HA_CONFIG = {HA_CONFIG}")
    print(f"  Automation blueprints: {sum(1 for _ in BLUEPRINTS_AUTO.glob('*.yaml'))}")
    print(f"  Script blueprints: {sum(1 for _ in BLUEPRINTS_SCRIPT.glob('*.yaml'))}")
    print(f"  Pyscript modules: {sum(1 for _ in PYSCRIPT_DIR.glob('*.py'))}")
    print(f"  Packages: {sum(1 for _ in PACKAGES_DIR.glob('*.yaml'))}")

    check_live_1()
    check_live_2_v2()
    check_live_3()
    check_live_4()
    check_live_5()
    check_live_6()
    check_live_7()
    check_live_8()
    check_live_9()

    # Verification pass
    verify_live_1_sample(20)

    # ── Summary ──
    print("\n" + "=" * 70)
    if not findings:
        print("ALL CLEAR — no findings.")
    else:
        errors = [f for f in findings if f.startswith(ERROR)]
        warnings = [f for f in findings if f.startswith(WARNING)]
        infos = [f for f in findings if f.startswith(INFO)]

        # Group by check
        by_check = defaultdict(lambda: {"E": 0, "W": 0, "I": 0})
        for f in findings:
            check = re.search(r'(LIVE-\d+|INFRA)', f)
            if check:
                cid = check.group(1)
                if f.startswith(ERROR):
                    by_check[cid]["E"] += 1
                elif f.startswith(WARNING):
                    by_check[cid]["W"] += 1
                else:
                    by_check[cid]["I"] += 1

        print(f"\nTOTAL: {len(errors)} ERROR, {len(warnings)} WARNING, {len(infos)} INFO\n")
        print("Per-check breakdown:")
        for cid in sorted(by_check):
            c = by_check[cid]
            print(f"  {cid}: {c['E']}E / {c['W']}W / {c['I']}I")

        print(f"\n{'─' * 70}")
        for f in findings:
            print(f)

    return 1 if any(f.startswith(ERROR) for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
