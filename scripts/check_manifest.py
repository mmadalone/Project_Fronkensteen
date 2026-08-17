#!/usr/bin/env python3
"""Assert the installer bundle and const.py manifests agree.

WHY THIS EXISTS
  installer.py installs a file only if it appears in a const.py manifest.
  sync_bundle.sh, by contrast, copies whole directories with globs. So a new
  file lands in the bundle automatically and *looks* shipped, while
  get_files_for_groups() never yields it and installer.py never copies it.

  installer.py reports the opposite direction only ("Missing from bundle:
  ...") and stays silent about a bundled file with no manifest entry. Nothing
  else catches it either: the release.yaml count guards are minimums
  (blueprints_automation >= 70 against an actual 80), and validate.yaml runs
  only hacs/action + hassfest.

  This drifted to 15 undeclared files before anyone noticed — including
  assist_tts_reroute.yaml, the blueprint the whole [MARKER] convention exists
  to serve. sync_bundle.sh:43-48 documents an earlier instance of the same
  bug class (modules/shared_utils.py never installing).

CHECKS
  1. orphans  - in the bundle, absent from the manifest  -> never installed
  2. ghosts   - in the manifest, absent from the bundle  -> logged every install
  3. groups   - every manifest value is "core" or a FEATURE_GROUPS key

Usage:  python3 scripts/check_manifest.py [REPO_ROOT]
Exit 0 when consistent, 1 otherwise.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

# bundle subdir -> (const.py name, kind). "dict" manifests are feature-gated
# {filename: group}; "list" manifests are always installed.
SUBDIR_MANIFESTS = {
    "pyscript": ("PYSCRIPT_FILES", "dict"),
    "packages": ("PACKAGE_FILES", "dict"),
    "blueprints_automation": ("BLUEPRINT_AUTOMATION_FILES", "dict"),
    "blueprints_script": ("BLUEPRINT_SCRIPT_FILES", "dict"),
    "helpers": ("HELPER_FILES", "list"),
    "pyscript_templates": ("CONFIG_TEMPLATES", "list"),
    "scripts": ("SCRIPT_FILES", "list"),
}

# Bundle entries that are intentionally not in any file manifest.
# installer.py consumes these through COMPONENT_ZIPS instead.
# Add here ONLY with a reason — an empty allowlist is the healthy state.
ALLOWLIST: dict[str, str] = {
    "elevenlabs_custom_tts.zip": "patched fork, installed via COMPONENT_ZIPS",
    "extended_openai_conversation.zip": "patched fork, installed via COMPONENT_ZIPS",
}


def load_const(path: Path) -> dict[str, object]:
    """Extract module-level literal assignments without importing the module.

    const.py is import-safe today, but importing it from CI would couple this
    check to whatever it imports tomorrow. ast keeps the check dependency-free.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    out: dict[str, object] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not isinstance(target, ast.Name):
                continue
            try:
                out[target.id] = ast.literal_eval(node.value)
            except ValueError:
                # Computed values (e.g. dict merges) are not manifests.
                continue
    return out


def bundle_files(subdir: Path) -> set[str]:
    """Files in a bundle subdir, as manifest-style relative paths.

    Recursive because PYSCRIPT_FILES declares "modules/shared_utils.py".
    """
    return {
        p.relative_to(subdir).as_posix()
        for p in subdir.rglob("*")
        if p.is_file() and not p.name.endswith((".pyc", ".zip"))
    }


def main() -> int:
    repo = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    component = repo / "custom_components" / "project_fronkensteen"
    bundle = component / "bundle"

    if not bundle.is_dir():
        print(f"ERROR: no bundle at {bundle}")
        print("       run: bash scripts/sync_bundle.sh")
        return 1

    const = load_const(component / "const.py")
    valid_groups = {"core"} | set(const.get("FEATURE_GROUPS", {}))

    problems = 0

    for subdir_name, (manifest_name, kind) in SUBDIR_MANIFESTS.items():
        subdir = bundle / subdir_name
        manifest = const.get(manifest_name)

        if manifest is None:
            print(f"FAIL {subdir_name}: const.py has no {manifest_name}")
            problems += 1
            continue

        declared = set(manifest if kind == "list" else manifest.keys())
        present = bundle_files(subdir) if subdir.is_dir() else set()

        orphans = sorted(present - declared - set(ALLOWLIST))
        ghosts = sorted(declared - present)

        if orphans:
            problems += len(orphans)
            print(f"FAIL {subdir_name}: {len(orphans)} file(s) in bundle, "
                  f"absent from {manifest_name} - these never install:")
            for name in orphans:
                print(f"       - {name}")

        if ghosts:
            problems += len(ghosts)
            print(f"FAIL {subdir_name}: {len(ghosts)} entr(y/ies) in "
                  f"{manifest_name}, absent from bundle - every install logs "
                  f"'Missing from bundle':")
            for name in ghosts:
                print(f"       * {name}")

        if kind == "dict":
            bad = sorted({g for g in manifest.values() if g not in valid_groups})
            if bad:
                problems += len(bad)
                print(f"FAIL {subdir_name}: {manifest_name} uses unknown "
                      f"feature group(s): {', '.join(bad)}")
                print(f"       valid: {', '.join(sorted(valid_groups))}")

        if not orphans and not ghosts:
            print(f"ok   {subdir_name}: {len(present)} file(s) match "
                  f"{manifest_name}")

    if problems:
        print(f"\n{problems} manifest problem(s). A file must be declared in "
              f"const.py to reach a HACS user.")
        return 1

    print("\nBundle and const.py manifests agree.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
