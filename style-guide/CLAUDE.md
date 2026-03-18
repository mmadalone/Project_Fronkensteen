# CLI Claude — Base Project Instructions

## Project Paths
- PROJECT_DIR: /Users/madalone/_Claude Projects/HA Master Style Guide/
- HA_CONFIG: /Users/madalone/Library/Containers/nz.co.pixeleyes.AutoMounter/Data/Mounts/Home Assistant/SMB/config/
- GIT_REPO: /Users/madalone/_Claude Projects/HA-Master-Repo/
- GIT_REPO_URL: https://github.com/mmadalone/HA-Master-Repo/
- HEADER_IMG: /Users/madalone/_Claude Projects/HA-Master-Repo/images/header/
- HEADER_IMG_RAW: https://raw.githubusercontent.com/mmadalone/HA-Master-Repo/main/images/header/
- README_AUTO_DIR: /Users/madalone/_Claude Projects/HA-Master-Repo/readme/automation/
- README_SCRI_DIR: /Users/madalone/_Claude Projects/HA-Master-Repo/readme/script/
- README_TEMPL_DIR: /Users/madalone/_Claude Projects/HA-Master-Repo/readme/template/
- IMG_PREMISES: Rick & Quark series episode premise based off the blueprint features; Rick & Morty (Adult Swim cartoon) episode premise based off the blueprint features

All edits happen in PROJECT_DIR and HA_CONFIG — never directly in GIT_REPO.
The git repo is a publish-only mirror.

## The Style Guide — "Rules of Acquisition"

The HA Master Style Guide is referred to as the **"Rules of Acquisition"** throughout the project. Have fun with it — but the code must be flawless.

`ha_style_guide_project_instructions.md` in `PROJECT_DIR` is the master index that routes to all style guide sections.

Key sections:
- **§1:** Core philosophy — always load the minimum sections needed for the task
- **§2.3:** QA checklist — use as a pre-flight checklist

## Helper Files

Helper entities are split by type across these files in `HA_CONFIG`:
- `helpers_input_boolean.yaml`
- `helpers_input_button.yaml`
- `helpers_input_datetime.yaml`
- `helpers_input_number.yaml`
- `helpers_input_select.yaml`
- `helpers_input_text.yaml`

When a blueprint requires input helpers, define them in the matching file.
Before creating a new helper, check the relevant file — it may already exist.

## Git Workflow

- **Source of truth:** Style guide files live in `PROJECT_DIR`. Blueprints live on `HA_CONFIG`.
- **Git repo** (`GIT_REPO`) is a **publish-only mirror** — never edit files there directly.
- Sync flow: `PROJECT_DIR` / `HA_CONFIG` → rsync → `GIT_REPO` → git commit → push.
- Never auto-push. Always wait for Miquel's explicit go-ahead.

## Context Management Principles

1. Never paste full config files — reference sections by path and line range.
2. Don't auto-load style guide sections, build logs, or directories unless explicitly needed for the task.
3. One automation/integration per session where possible.
4. Don't repeat code blocks that were already established — reference them by name.
5. Bias toward editing files rather than explaining changes conversationally.

## Maintaining This File

As you work through the codebase, **update this CLAUDE.md** with important discoveries that should persist across sessions — paths you found, architectural decisions confirmed, conventions detected, key file locations. This file is your memory between sessions. Keep it concise and factual.