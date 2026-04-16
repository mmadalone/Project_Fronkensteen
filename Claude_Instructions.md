## Project Paths

These are the canonical variable names used throughout the Rules of Acquisition. The actual absolute paths live in the user's local `CLAUDE.md` — this file just documents the variable contract.

| Variable | Purpose |
|---|---|
| `PROJECT_DIR` | Root of the HA Master Style Guide directory (where Rules of Acquisition and build logs live) |
| `HA_CONFIG` | Home Assistant config directory (SMB mount or UNC share) |
| `GIT_REPO` | Local clone of `Project_Fronkensteen` — publish-only mirror |
| `HEADER_IMG` | Generated header images: `<GIT_REPO>/images/header/` |
| `README_AUTO_DIR` | Automation blueprint READMEs: `<GIT_REPO>/readme/automation/` |
| `README_SCRI_DIR` | Script blueprint READMEs: `<GIT_REPO>/readme/script/` |
| `README_TEMPL_DIR` | Template blueprint READMEs: `<GIT_REPO>/readme/template/` |
| `GIT_REPO_URL` | `https://github.com/mmadalone/Project_Fronkensteen/` |
| `HEADER_IMG_RAW` | `https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/` |
| `IMG_PREMISES` | Rick & Quark series episode premises for header image generation, based off the blueprint features (Rick & Morty / Adult Swim style) |

All edits happen in `PROJECT_DIR` and `HA_CONFIG` — never directly in `GIT_REPO`. The git repo is a publish-only mirror. If any path changes, update the user's local `CLAUDE.md`, not this file.

## Rules of Acquisition — Index
`ha_style_guide_project_instructions.md` in `PROJECT_DIR` is the master index
that routes to all style guide sections. When referring to the style guide,
call it the "Rules of Acquisition." Have fun with it — but the code must be flawless.
**Always load:** §1 core philosophy (only the minimum sections needed for the task).
**Pre-flight:** use §2.3 as a checklist, but do not load full files—extract only the relevant bullets.

## Context Budget Gate (Max Plan)

default execution mode is **single-file execution**:
- read only the one target file you will change
- do not auto-load other guide sections, checklists, logs, or directories

reference mode is explicit:
- only when the user says "reference mode: <file/section>"
- read the smallest necessary excerpt, then exit reference mode

debug mode is explicit:
- only when the user says "enter debug mode"
- use **diff-first + excerpt-second**: prefer git diff and small log slices (error + limited surrounding lines)
- never ingest full raw logs unless explicitly requested

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

---

## File Transfer Rules
1. **NEVER** chunk files over SSH. NEVER use base64 encoding over SSH.
2. For ALL file writes to Home Assistant, use Desktop Commander `write_file` directly to the SMB mount path (`HA_CONFIG` above).
3. For files over 30KB, use append mode — write the first section with `mode: rewrite`, then continue with `mode: append`. Do NOT attempt a single monolithic write.
4. **Always verify** the file after writing with a Desktop Commander `read_file` operation. No exceptions.
5. For style guide and build log writes, use Desktop Commander `write_file` to `PROJECT_DIR`.

---

## Tool Routing Quick Reference
Per §1.13 — use the right tool for the operation, not the first one that comes to mind.
- **Search text in files** → ripgrep (`search` / `advanced-search`). One call, context lines, line numbers.
- **Read precise line ranges** → Filesystem MCP `read_file` with `head`/`tail`.
- **Read full files** → Desktop Commander `read_file` (skip `range` param — it's broken).
- **Edit in place** → Desktop Commander `edit_block`.
- **Write / overwrite** → Desktop Commander `write_file`. Over 30KB → append mode.
- **HA docs lookup** → Context7 (`resolve-library-id` → `query-docs`), fall back to web search.
- default: prefer search + precise line ranges over full-file reads (full-file reads are allowed only for the single target file being edited).

## Filesystem Rules — Claude's Computer vs User's Computer
Claude has access to TWO filesystems. Confusing them wastes time and breaks things.

| Filesystem | Access via | Use for |
|---|---|---|
| **User's machine** (Windows / macOS / Linux) | Desktop Commander / Filesystem MCP tools (`read_file`, `write_file`, `list_directory`, `edit_block`, etc.) | ALL reads/writes to HA config, project files, build logs, style guide docs. This is where real work happens. |
| **Claude's container** (`/home/claude/`, `/mnt/`) | Claude's internal tools (`bash_tool`, `create_file`, `view`, `present_files`) | Temporary scratch work, generating artifacts for download, running scripts. Files here reset between sessions. |

**Rules:**
- **Default to the user's filesystem** for everything. If the task involves reading, writing, or editing any project file, HA config, or build log — use Desktop Commander / Filesystem MCP.
- **Never use Claude's internal computer** (`bash_tool`, `create_file`) for files destined for the user's system. Those tools operate on a separate, ephemeral container.
- **Only use Claude's computer** for: temporary computation, generating downloadable artifacts, running validation scripts, or tasks that explicitly don't touch the user's files.
- When the user says "read this file" or "check this path" — assume they mean THEIR filesystem unless the path starts with `/home/claude/` or `/mnt/`.
- If a tool call fails on one filesystem, check whether you're targeting the wrong one before retrying.

---

## Git Workflow
- Source of truth: style guide files live in `PROJECT_DIR`. Blueprints live on `HA_CONFIG`.
- Git repo (`GIT_REPO`) is a publish-only mirror — never edit files there directly.
- For HA config changes tracked by the HA MCP git tools: use `ha_create_checkpoint` / `ha_git_commit` / `ha_git_rollback` as documented in the Rules of Acquisition §2.
- For style guide changes: edit in `PROJECT_DIR`, then publish via the workflow below.

## Post-Edit Publish Workflow
When the user says "commit this", "publish", "sync and commit", or any build log is marked
COMPLETE, execute this 3-phase chain. Do NOT skip phases or reorder them.

### Phase 1 — Sync (rsync source → repo)
Run the following three `rsync -av` commands via Desktop Commander `start_process`.
These are additive only (no `--delete`). Order does not matter.

```
rsync -av \
  --exclude='_versioning' \
  --exclude='_build_logs' \
  "<PROJECT_DIR>" "<GIT_REPO>/style-guide/"
rsync -av "<HA_CONFIG>/blueprints/automation/madalone/" "<GIT_REPO>/automation/"
rsync -av "<HA_CONFIG>/blueprints/script/madalone/" "<GIT_REPO>/script/"
```

Expand `<PROJECT_DIR>`, `<HA_CONFIG>`, and `<GIT_REPO>` to their full canonical paths
from the user's local `CLAUDE.md`. Quote all paths (spaces in directory names).

After sync completes, confirm success from rsync output before proceeding.

### Phase 2 — Stage + Commit (git MCP)
1. `git_status` on `GIT_REPO` — show the user a summary of changed files.
2. `git_add` all changed files.
3. `git_commit` with a descriptive commit message. Format:
   - First line: short summary (≤72 chars), e.g. `§1.13: add git MCP + Context7 routing`
   - Blank line, then bullet list of changes if multi-file.
   - Reference the build log filename if one exists for this session.

### Phase 3 — Push Gate (user confirms)
After commit succeeds, present the user with two options:
- **Push now** — run `git push` in `GIT_REPO` via Desktop Commander `start_process`.
- **Open GitHub Desktop** — run `open -a "GitHub Desktop"` via Desktop Commander
  `start_process`, user handles push and any pre-push review themselves.

**Never auto-push.** Always wait for the user's explicit choice.

## ⚠️ Context Window — MANDATORY
After every 3–4 exchanges, state your estimated context usage (low/medium/high/critical).
At HIGH: warn the user. At CRITICAL: stop work, produce a state checkpoint and handoff summary.
Never silently degrade — if recall is slipping, say so immediately.

## Context Management Rules
1. NEVER paste full config files — reference sections by path and line range
2. After every major task completion, produce a STATE CHECKPOINT:
   - Decisions made
   - Current config state  
   - Outstanding items
3. Write all finalized configs to files/artifacts immediately
4. One automation/integration per conversation session
5. If conversation exceeds ~15 exchanges, proactively summarize
6. Front-load critical HA conventions in every new session
7. Disable unused tools/features per session — if you're doing pure YAML config work, turning off web search and extended thinking saves real token budget.
8. Redundancy prohibition — rule 1 hints at it, but explicitly telling Claude "don't repeat code blocks that were already established, reference them by name" is worth its own line.
9. Artifact-first workflow — bias toward editing artifacts rather than having Claude explain changes conversationally. A 50-line YAML artifact costs way fewer tokens than Claude talking about the same 50 lines of YAML across three back-and-forth messages.
10. never auto-load style guide sections, build instructions, or logs unless the user explicitly requests reference/debug mode.

## Crash Recovery — The Salvage Directive

When the user indicates a previous session crashed, was interrupted, or
produced incomplete results, this is a **crash recovery trigger**. The AI
must immediately execute the §11.0 crash-recovery checkpoint protocol —
do NOT begin fresh work until recovery state has been assessed.

**Trigger phrases (non-exhaustive — match intent, not exact wording):**
- "The last session crashed" / "it crashed mid-run" / "the conversation died"
- "You bugged out" / "you glitched" / "Claude crashed" / "the AI broke"
- "Pick up where we left off" / "continue the build" / "resume from the crash"
- "A previous attempt failed" / "we lost progress" / "the session timed out"
- "It died mid-build" / "you stopped mid-chunk" / "the write was interrupted"
- Any reference to incomplete prior work on a file the user is now asking about

**On trigger detection, execute this sequence:**

1. **Acknowledge the crash.** Don't pretend it didn't happen. Tell the user
   you're checking for recovery state.

2. **Scan `_build_logs/`** in `PROJECT_DIR` for recovery candidates:
   - List directory, sort by modification date descending
   - Read the most recent log's `Status` field
   - If `completed` → skip, check the next log
   - If `in-progress` or `aborted` → this is the recovery candidate
   - If no incomplete log exists → proceed to step 3
   - when scanning build logs, do not read full logs: pull only status + the smallest error excerpt needed.
git diff remains the source of truth; logs are advisory.

3. **Check git state** via `ha_git_pending` and `ha_git_diff`:
   - Uncommitted changes = work was interrupted mid-edit
   - These are the source of truth — build logs are advisory, git is fact
   - when scanning build logs, do not read full logs: pull only status + the smallest error excerpt needed.
git diff remains the source of truth; logs are advisory.

4. **Search past conversations** using `conversation_search` with keywords
   from the user's description (blueprint name, feature being built, etc.)
   and/or `recent_chats` for the most recent sessions. Extract:
   - What was being built
   - Key decisions made
   - Where it stopped

5. **Present a recovery summary** to the user (keep it to 3–5 sentences):
   - Task that was in progress
   - Last confirmed-good state (from build log + git diff)
   - Files touched and their current condition
   - Proposed next action

6. **Wait for user confirmation** before touching anything. The user may have
   manually fixed things, changed their mind, or want to start fresh.

**If no recovery state is found** (no build logs, no uncommitted changes, no
relevant past conversations): tell the user you couldn't find traces of the
previous session. Ask them to describe what was being built so you can start
a clean build with full context.

**Critical:** Do NOT skip this protocol because the user "just wants to get
going." Recovery takes 60 seconds. Rebuilding from scratch because you
overwrote partially-correct work takes 60 minutes. The 23rd Rule of
Acquisition: "Nothing is more important than your health — except your money."
Time is money. Recover first.
