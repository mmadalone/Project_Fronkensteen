# CLI Claude — Base Project Instructions

> **!! ACTION ITEMS from 2026-03-16 deep audit (Grade: B-).** Read `_build_logs/2026-03-16_codebase_grade_action_items.md` before starting new features. Critical: run test plan, verify 4 untested deployments, address bedtime_routine divergence.

## Project Paths
- PROJECT_DIR: /Users/madalone/_Claude Projects/HA Master Style Guide/
- HA_CONFIG: /Users/madalone/Library/Containers/nz.co.pixeleyes.AutoMounter/Data/Mounts/Home Assistant/SMB/config/
- GIT_REPO: /Users/madalone/_Claude Projects/Project_Fronkensteen/
- GIT_REPO_URL: https://github.com/mmadalone/Project_Fronkensteen/
- HEADER_IMG: /Users/madalone/_Claude Projects/Project_Fronkensteen/images/header/
- HEADER_IMG_RAW: https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/
- README_AUTO_DIR: /Users/madalone/_Claude Projects/Project_Fronkensteen/readme/automation/
- README_SCRI_DIR: /Users/madalone/_Claude Projects/Project_Fronkensteen/readme/script/
- README_TEMPL_DIR: /Users/madalone/_Claude Projects/Project_Fronkensteen/readme/template/
- IMG_PREMISES: Rick & Quark series episode premise based off the blueprint features; Rick & Morty (Adult Swim cartoon) episode premise based off the blueprint features

- HELPER_DIR: /Users/madalone/_Claude Projects/Project_Fronkensteen/helpers/
- README_PYSCrIPT_DIR: /Users/madalone/_Claude Projects/Project_Fronkensteen/readme/pyscript/
- README_PACKAGES_DIR: /Users/madalone/_Claude Projects/Project_Fronkensteen/readme/packages/
- Source of truth for Extended OpenAI conversation agent prompts: /Users/madalone/_Claude Projects/HA Master Style Guide/Extended OpenAi Conversation Prompts

All edits happen in PROJECT_DIR and HA_CONFIG — never directly in GIT_REPO.
The git repo is a publish-only mirror.

## The Style Guide — "Rules of Acquisition"

The HA Master Style Guide is referred to as the **"Rules of Acquisition"** throughout the project. Have fun with it — but the code must be flawless.

`ha_style_guide_project_instructions.md` in `PROJECT_DIR` is the master index that routes to all style guide sections.

Key sections:
- **§1:** Core philosophy — always load the minimum sections needed for the task
- **§2.3:** QA checklist — use as a pre-flight checklist

## Operational Mode (MANDATORY — Every HA Task)

At the start of every HA-related task:

1. **Identify the mode** — Match the user's request against the operational mode table in `ha_style_guide_project_instructions.md` (BUILD / TROUBLESHOOT / AUDIT). If ambiguous, default to BUILD.
2. **Load the right docs** — Use the task routing table in the master index to load only the style guide sections needed for the identified mode and task type.
3. **Auto-escalate** — If a TROUBLESHOOT session requires editing files to fix the issue, escalate to BUILD mode BEFORE the first edit: load remaining BUILD-mode docs, run `ha_create_checkpoint`, and stay in BUILD mode for the rest of the session.
4. **Never skip mode identification.** Don't jump straight to coding without determining which mode applies and which docs to load.

## Research & Solution Quality (MANDATORY — Every Task)

Before proposing or implementing ANY solution:

1. **Research first** — Search official HA docs, integration docs, and community forums (HA Community, GitHub issues) for proven solutions with reported success. Use web search tools. Don't invent approaches when documented ones exist.
2. **Codebase check** — Search the existing codebase for duplicates, related implementations, and reusable patterns before proposing new code. Propose architectural improvements where relevant.
3. **No hacky solutions** — Only use tried-and-tested approaches. If the only available solution is a workaround, flag it explicitly and explain why no clean solution exists.
4. **Preserve working logic** — Improve upon existing patterns; never silently alter working behavior.
5. **Flag breaking changes** — Any change that alters existing behavior, renames entities, changes service signatures, or modifies data flow MUST be explicitly called out in the plan with impact assessment.

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
- Sync flow: `PROJECT_DIR` / `HA_CONFIG` → `ha-master-sync-to-repo.sh` → `GIT_REPO` → git commit → push. Script handles rsync, patched component sync to `source_components/`, bundle population, and zipped patched components.
- Never auto-push. Always wait for Miquel's explicit go-ahead.
- **GitHub CI:** `.github/workflows/validate.yaml` (HACS + hassfest) and `.github/workflows/release.yaml` (bundle sync + GitHub Release) run automatically on push/PR.

## HACS Installer Integration

- **Custom component:** `HA_CONFIG/custom_components/project_fronkensteen/` — config flow wizard (5 steps), file installer, helper merge, version tracking, 4 services.
- **Source components:** `GIT_REPO/source_components/` — patched EOC v2.0.2 and ElevenLabs v0.6.3 source dirs. These are the source of truth for the zipped bundles.
- **Both patched components bundled** as zips (manual distribution) AND pre-extracted subdirectories (installer). `manifest.json` → `manifest.json.bundle` rename avoids hassfest. ElevenLabs installed with voice feature group; EOC always installed (core). Unified `_FILE_RENAMES` map.
- **Community docs:** `GIT_REPO/PREREQUISITES.md`, `INSTALL.md`, `ARCHITECTURE.md`, `helpers/helpers_setup_guide.md`, `helpers/helpers_reference.md`.

## HACS Component Patches

- **`custom_components/extended_openai_conversation/`** — patched against **v2.0.2** with two additions: (1) **6-layer tool-call speech sanitizer** in `conversation.py` strips function-call leaks before TTS (Layers 3-4 handle unquoted/single-quoted `key=value` patterns, Layer 5 strips JSON tool objects `{"name":...,"parameters":...}`, Layer 6 strips ElevenLabs `[tags]` in test mode). (2) **Fallback model support** (2026-03-31) — new `fallback_model` config option per agent subentry. On `RateLimitError` (429), `InternalServerError` (5xx), or `NotFoundError` (404): retries once with the fallback model. Per-turn only (not sticky). `model_override` threaded through all recursive tool-call paths. Files changed from upstream: `conversation.py`, `const.py`, `config_flow.py`, `strings.json`. **HACS auto-updates disabled** for this component.
- **`custom_components/elevenlabs_custom_tts/tts.py`** — patched against **v0.6.3** with voice mood modulation (v3 pivot). Reads `voice_mood_profile_map.json` at init, reads per-agent `input_number.ai_voice_mood_{agent}_stability` + `input_text.ai_voice_mood_{agent}_tags` helpers at TTS time. Injects stability into VoiceSettings and tag prefix into message text (only for non-tagged messages — `"[" not in message` guard avoids double-tagging agent responses). **HACS auto-updates disabled** for this component.

## Context Management Principles

1. Never paste full config files — reference sections by path and line range.
2. Don't auto-load style guide sections, build logs, or directories unless explicitly needed for the task.
3. One automation/integration per session where possible.
4. Don't repeat code blocks that were already established — reference them by name.
5. Bias toward editing files rather than explaining changes conversationally.

## Maintaining This File

As you work through the codebase, **update this CLAUDE.md** with important discoveries that should persist across sessions — paths you found, architectural decisions confirmed, conventions detected, key file locations. This file is your memory between sessions. Keep it concise and factual.