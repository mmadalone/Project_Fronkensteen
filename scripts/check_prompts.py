#!/usr/bin/env python3
"""Assert every _Functions_*.md parses as the YAML that EOC expects.

WHY THIS EXISTS
  INSTALL.md tells users to copy these files into the Extended OpenAI
  Conversation "Functions" field, which parses them as YAML. They are the
  only published record of the agents' tool definitions.

  On 2026-08-14 all five had their indentation flattened to a single space
  and stopped parsing. Nothing noticed, because nothing reads them in CI and
  the live agents keep working from .storage/core.config_entries. A user
  following INSTALL.md would have hit a parse error with no explanation.

CHECKS, per file
  1. parses as YAML
  2. top level is a non-empty list
  3. every item has `spec` and `function` as SIBLINGS (the shape EOC wants;
     nesting `function` under `spec` is the classic hand-edit mistake)
  4. every spec has a name, and names are unique within the file
  5. no live API key leaked in (the sync script sanitizes X-API-KEY on the
     way to the mirror, so a real key here means the sanitizer was bypassed)

Usage:  python3 scripts/check_prompts.py [REPO_ROOT]
Exit 0 when all files are valid, 1 otherwise.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

PROMPTS_DIR = "Extended OpenAi Conversation Prompts"

# The sync script rewrites X-API-KEY values to this before publishing.
PLACEHOLDER = "YOUR_API_KEY"
SECRET = re.compile(
    r"""[Xx]-[Aa][Pp][Ii]-[Kk][Ee][Yy]:\s*"([^"]+)" """.strip()
)


def check_file(path: Path) -> list[str]:
    """Return a list of problems; empty means the file is good."""
    problems: list[str] = []
    text = path.read_text(encoding="utf-8")

    try:
        specs = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        first = str(exc).splitlines()[0]
        return [f"does not parse as YAML: {first}"]

    if not isinstance(specs, list) or not specs:
        return ["top level is not a non-empty list of specs"]

    names: list[str] = []
    for i, item in enumerate(specs):
        where = f"item {i}"
        if not isinstance(item, dict):
            problems.append(f"{where}: not a mapping")
            continue

        if "spec" not in item:
            problems.append(f"{where}: missing `spec`")
            continue

        spec = item["spec"]
        name = spec.get("name") if isinstance(spec, dict) else None
        where = f"`{name}`" if name else where

        if not name:
            problems.append(f"{where}: spec has no `name`")
        else:
            names.append(name)

        # `function` must be a sibling of `spec`, not nested inside it.
        if "function" not in item:
            if isinstance(spec, dict) and "function" in spec:
                problems.append(
                    f"{where}: `function` is nested under `spec` - it must be "
                    f"a sibling (same indent as `spec`)"
                )
            else:
                problems.append(f"{where}: missing `function`")

    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        problems.append(f"duplicate spec name(s): {', '.join(dupes)}")

    for value in SECRET.findall(text):
        if value != PLACEHOLDER:
            problems.append(
                f"contains a live X-API-KEY value ({len(value)} chars) - it "
                f"should read \"{PLACEHOLDER}\"; the sync sanitizer was bypassed"
            )

    return problems


def main() -> int:
    repo = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    root = repo / PROMPTS_DIR

    if not root.is_dir():
        print(f"ERROR: no prompts directory at {root}")
        return 1

    # Skip *.bak.* — backups are excluded from the mirror by the sync script.
    files = sorted(
        p for p in root.glob("*/_Functions_*.md") if ".bak." not in p.name
    )
    if not files:
        print(f"ERROR: no _Functions_*.md found under {root}")
        return 1

    failed = 0
    for path in files:
        problems = check_file(path)
        rel = path.relative_to(repo)
        if problems:
            failed += 1
            print(f"FAIL {rel}")
            for p in problems:
                print(f"       - {p}")
        else:
            count = len(yaml.safe_load(path.read_text(encoding="utf-8")))
            print(f"ok   {rel} ({count} specs)")

    if failed:
        print(f"\n{failed} of {len(files)} prompt spec file(s) invalid. "
              f"INSTALL.md tells users to paste these into EOC verbatim.")
        return 1

    print(f"\nAll {len(files)} prompt spec files parse.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
