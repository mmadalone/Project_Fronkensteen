# Home Assistant Style Guide — QA Audit Checklist

> **Purpose:** This checklist defines quality gates that AI agents MUST run when generating HA configurations, and that auditors (human or AI) should run periodically against the style guide itself. Every finding has a severity level and a concrete check procedure.
>
> **How to use:** When generating or reviewing HA YAML, run through each applicable section. When auditing the style guide, run ALL sections. Report findings using the severity format: `[ERROR]`, `[WARNING]`, or `[INFO]`.

---

## Severity Levels

| Level | Meaning | Action Required |
|-------|---------|-----------------|
| **ERROR** | Will cause failures, security issues, or incorrect behavior at runtime | Must fix before merge/deploy |
| **WARNING** | May cause confusion, maintenance burden, or subtle bugs; degrades AI-readability | Should fix; document exception if skipped |
| **INFO** | Improvement opportunity; better DX or completeness | Fix when convenient |

---

## 15. QA AUDIT CHECKLIST

## 15.1 — Check Definitions

### 0 — Blueprint-First Gate (Pre-Build)

### BPG-1: Blueprint-First Decision Tree [WARNING]

**Check:** Before ANY automation code is written, verify the §3.0 decision tree has been applied.

```
FAIL if: automation: block exists in a package file AND the logic follows
         trigger → conditions → actions with configurable parameters that
         could be blueprint inputs (entity selections, time schedules,
         thresholds, person entities, zone references)

PASS if: blueprint created in blueprints/automation/madalone/, OR
         automation is confirmed infrastructure glue with no user-facing
         inputs (startup resets, midnight housekeeping, pyscript coordination)
```

**When to run:** At the START of any build workflow — as part of §11.1 steps 0–1, before any code is written. This is a pre-build gate, not a post-build review.

**Detection heuristics:**
- Does the automation have `input:` sections or variables that could be `!input` references? → Blueprint candidate.
- Could someone deploy this for a different room, person, or device by changing parameters? → Blueprint candidate.
- Does it only exist to reset helpers at midnight or initialize state on HA boot? → Package glue. Pass.

**Fix:** Migrate the automation to a blueprint in `blueprints/automation/madalone/`. Move configurable parameters to blueprint `input:` sections. Shared-state helpers consumed by pyscript or dashboards stay in the package.

**Cross-references:** §3.0 (decision tree), §5.0 (when to use what), AP-52 (anti-pattern).

---

### 1 — Security & Secrets Management

### SEC-1: No Inline Secrets [ERROR]

**Check:** Scan ALL YAML examples (in guide files AND generated output) for hardcoded API keys, tokens, passwords, or credentials.

```
# What to look for:
api_key: "sk-..."
token: "eyJ..."
password: "..."
api_key: !env_var ...   # Also suspicious — prefer !secret
```

**Rule:** Every secret MUST use `!secret` references. No exceptions, not even in "example" blocks — the guide's own examples are copy-pasted by AI agents and humans alike.

**Fix pattern:**
```yaml
# ❌ WRONG — even in examples
api_key: "sk-proj-abc123"

# ✅ CORRECT
api_key: !secret openai_api_key
```

### SEC-2: Safety Carve-outs in Directive Precedence [ERROR]

**Check:** If the guide defines a directive precedence hierarchy (e.g., "user instructions override style preferences"), verify it includes an explicit carve-out:

> Explicit user instructions override style preferences but **NOT** safety-critical rules: error handling, secrets management, cleanup patterns, and input validation.

**Why:** An AI agent told "skip error handling, just make it work" must still include error handling.

### SEC-3: Template Injection via Blueprint Inputs [ERROR]

**Check:** Any blueprint `input:` with a `text` or `template` selector whose value is inserted into a Jinja2 template block MUST be sanitized or constrained. Flag when:
1. A `text` input is dropped directly into `{{ input_variable }}` inside a template that executes actions, REST calls, or shell commands
2. A `text` input is concatenated into a conversation agent prompt without escaping
3. No `pattern:` constraint is applied to free-text inputs that reach sensitive contexts

**Risk contexts (highest to lowest):**
- `rest_command:` bodies and URLs — can exfiltrate data
- `shell_command:` arguments — can execute arbitrary commands
- `conversation.process` prompts — can override agent instructions
- `tts.speak` messages — low risk but can produce unexpected speech

**Fix pattern:**
```yaml
# ❌ WRONG — user input goes straight into a REST body
input:
  custom_message:
    name: "Custom message"
    selector:
      text:

action:
  - action: rest_command.send_notification
    data:
      payload: '{"text": "{{ custom_message }}"}'

# ✅ BETTER — constrained input with validation
input:
  custom_message:
    name: "Custom message"
    description: "Alphanumeric only, max 100 chars"
    selector:
      text:
        multiline: false

# And validate in the action sequence before use:
action:
  - alias: "Validate input length"
    condition: template
    value_template: "{{ custom_message | length <= 100 }}"
  - action: rest_command.send_notification
    data:
      payload: '{"text": "{{ custom_message | replace('\"', '') }}"}'
```

📋 QA Check: Run on every blueprint that has a `text` or `template` selector input. Trace where the input value flows.

---

### 2 — Version Accuracy

### VER-1: All Version Claims Must Be Verified [ERROR]

**Check:** Every statement claiming a feature requires "HA 20XX.X+", "ESPHome 20XX.X+", or "Music Assistant X.X+" MUST be verified against official release notes or changelogs.

**Verification sources (in priority order):**
1. Official release notes: `https://www.home-assistant.io/blog/categories/release-notes/`
2. ESPHome changelog: `https://esphome.io/changelog/`
3. Music Assistant GitHub releases: `https://github.com/music-assistant/server/releases`
4. HA breaking changes: `https://www.home-assistant.io/blog/categories/breaking-changes/`

**Known checks to verify periodically:**

| Claim | File | Verification Source |
|-------|------|---------------------|
| `conversation_agent` selector requires HA 2024.2+ | 01_blueprint_patterns.md | HA release notes |
| `collapsed: true` requires HA 2024.6+ | 01_blueprint_patterns.md | HA release notes |
| Modern blueprint syntax requires HA 2024.10+ | 01_blueprint_patterns.md | HA release notes |
| Dual wake word support requires HA 2025.10+ | 04_esphome_patterns.md | HA release notes |
| Sub-devices require HA 2025.7+ | 04_esphome_patterns.md | ESPHome changelog |
| `ask_question` full capabilities require HA 2025.7+ | 08_voice_assistant_pattern.md | HA release notes |
| TTS streaming requires HA 2025.10+ | 08_voice_assistant_pattern.md | HA release notes |
| MCP servers introduced HA 2025.2+ | 03_conversation_agents.md | HA release notes |
| `data_template` deprecated ~HA 0.115/2020, no removal date announced | 06_anti_patterns_and_workflow.md | HA release notes |

**Procedure:**
1. Web search: `site:home-assistant.io "<feature_name>" release`
2. If not found in release notes, search GitHub PRs/issues
3. If unverifiable, add caveat: `<!-- UNVERIFIED: version claim needs confirmation -->`

### VER-2: Blueprint Examples Must Include min_version [WARNING]

**Check:** All blueprint examples using modern syntax (actions instead of action, response_variable, conversation_agent selector) MUST include:

```yaml
homeassistant:
  min_version: "2024.10.0"
```

**Why:** Without `min_version`, blueprints silently break on older HA installs with confusing errors. AI agents copy these examples verbatim.

### VER-3: Deprecation Dates Must Be Tracked [WARNING]

**Check:** Any mention of deprecated features (e.g., `data_template`, `service` → `action`) MUST include:
- The version it was deprecated
- The target removal version (if announced)
- The migration path

**Format:**
```markdown
> ⚠️ **Deprecated:** `data_template` was deprecated in ~HA 0.115 (2020).
> Target removal: No removal date announced (verify against release notes).
> Migration: Replace with `data:` under the new `action:` syntax.
```

---

### 3 — AI-Readability & Vibe Coding Readiness

### AIR-1: No "Use Good Judgment" Without Concrete Thresholds [WARNING]

**Check:** Search for vague guidance that assumes human-level inference. An AI agent cannot interpret:
- "use appropriate delays"
- "set a reasonable timeout"
- "keep it short"
- "use common sense"

**Fix pattern:** Replace with concrete numbers, ranges, or decision trees:

```markdown
# ❌ Vague
Use an appropriate delay between retries.

# ✅ Concrete
Use exponential backoff between retries:
- 1st retry: 2 seconds
- 2nd retry: 5 seconds
- 3rd retry: 15 seconds
- Max retries: 3
- Max total wait: 22 seconds
```

### AIR-2: Every Pattern Must Have an Implementation Skeleton [WARNING]

**Check:** If the guide describes a pattern (dispatcher, fallback, duck-and-restore, etc.), it MUST include a copy-pasteable YAML skeleton, not just a prose description.

**What counts as a skeleton:**
- Complete enough that an AI agent can adapt it without inventing structure
- Includes all required keys (even if values are placeholder)
- Has comments explaining what to customize

**What does NOT count:**
- "You could use a choose block for this" (prose only)
- A partial snippet missing required fields
- A reference to another file without inline example

### AIR-3: Decision Logic Must Be Explicit [WARNING]

**Check:** When the guide says "choose between X and Y," it MUST provide selection criteria:

```markdown
# ❌ Unclear
You can use either `conversation.process` or `assist_satellite.start_conversation`.

# ✅ Clear decision tree
## Choosing Between Conversation Actions
- **Need the response text in an automation variable?**
  → Use `conversation.process` — returns `response.speech.plain.speech`
- **Need audio output on a satellite device?**
  → Use `assist_satellite.start_conversation` — does NOT return response text
- **Need both?**
  → Use `conversation.process` first, then pipe result to TTS
```

### AIR-4: Anti-patterns Must Show the Fix Alongside the Bad Example [INFO]

**Check:** Every ❌ example MUST be immediately followed by its ✅ corrected version. An AI agent seeing only the wrong pattern may accidentally learn from it.

### AIR-5: Numerical Thresholds for Subjective Guidance [WARNING]

**Check:** Look for subjective quality guidance and add numbers:

| Subjective | Concrete |
|------------|----------|
| "Don't make automations too complex" | "If a single automation exceeds 200 lines or 5 nested conditions, split it" |
| "Keep descriptions concise" | "Blueprint descriptions: 1-2 sentences, max 160 characters for UI display" |
| "Avoid too many triggers" | "More than 8 triggers in one automation suggests it should be split by domain" |
| "Use reasonable delays" | "TTS duck/restore: 300ms fade, 500ms restore delay (adjust ±200ms per speaker)" |

### AIR-6: Token Count Accuracy [WARNING]

**Check:** Every token estimate in the master index and file headers must be verifiable. Use `1 token ≈ 4 characters` as the baseline conversion.

**Threshold:** Flag when a claim drifts by more than **15%** from the measured value.

**What to verify:**
- Per-file token estimates in the master index routing table
- The total token count claim (e.g., "~86K tokens total")
- Any per-section token budget claims (e.g., "§1 alone: ~5.7K")

**Measurement method:**
```bash
# Approximate tokens for a file (chars / 4)
wc -c <filename> | awk '{printf "%.1fK tokens\n", $1/4/1000}'
```

**Why:** Stale token estimates cause the AI to either overload context (loads too many files) or underload it (skips a file thinking it won't fit). Both degrade output quality.

📋 QA Check: Re-measure after any structural change to a style guide file.

### AIR-7: Contradictory Guidance Detection [WARNING]

**Check:** Scan for topics covered in multiple files where the guidance conflicts. Common contradiction zones:

| Topic | Files that may conflict |
|-------|------------------------|
| Error handling strategy | 01 (blueprint patterns) vs 02 (automation patterns) vs 06 (anti-patterns) |
| `continue_on_error` usage | 01 vs 06 |
| Volume management approach | 05 (Music Assistant) vs 08 (voice assistant) |
| TTS provider selection | 03 (conversation agents) vs 08 (voice assistant) |
| Entity naming conventions | 00 (core philosophy) vs any file with examples |

**How to check:**
1. Identify all topics that appear in 2+ files (grep for shared keywords)
2. For each shared topic, extract the specific guidance from each file
3. Flag if the guidance differs in: recommended approach, threshold values, severity, or exceptions

**Severity escalation:**
- Two files give different numbers for the same threshold → WARNING
- Two files recommend opposite approaches for the same scenario → ERROR
- A pattern in one file is an anti-pattern in another without explicit cross-reference → ERROR

📋 QA Check: Run after any substantive content change. Especially important when editing 06_anti_patterns — every anti-pattern must not accidentally contradict a recommended pattern elsewhere.

---

### 4 — Code Quality & Patterns

### CQ-1: Action Aliases Are Strongly Recommended [WARNING]

**Check:** All `action:` blocks in examples SHOULD include `alias:` fields.

**Why:** When debugging in HA's trace viewer, unnamed actions show as "Action 1", "Action 2" — useless. Aliases show "Turn on living room lights", "Set TTS volume" — dramatically easier to debug.

**Note:** This is "strongly recommended," not mandatory. But if an example omits aliases, it should have a comment explaining this is for brevity.

### CQ-2: Error Handling Must Not Be Optional [ERROR]

**Check:** Any example involving:
- API calls (REST, conversation agents, TTS)
- Network-dependent actions
- Multi-step sequences where failure mid-way leaves bad state

MUST include error handling (try/catch via `choose` with `continue_on_error`, or explicit state checks).

### CQ-3: Cleanup Patterns for Stateful Operations [WARNING]

**Check:** If an automation sets a temporary state (e.g., volume duck, temporary mode change, helper toggle), it MUST include a cleanup/restore mechanism, even on failure paths.

```yaml
# Pattern: always-restore
sequence:
  - alias: "Save current volume"
    action: scene.create
    data:
      scene_id: tts_volume_restore
      snapshot_entities:
        - media_player.living_room
  - alias: "Duck volume"
    action: media_player.volume_set
    # ... TTS actions ...
  - alias: "Restore volume (runs even if TTS fails)"
    action: scene.turn_on
    target:
      entity_id: scene.tts_volume_restore
    continue_on_error: true
```

### CQ-4: Return Values Must Be Documented [ERROR]

**Check:** Any action described in the guide that has a return value MUST document:
- What the return variable contains
- The exact access path (e.g., `response.speech.plain.speech`)
- Whether the action returns anything at all (some don't!)

Known return value documentation required:

| Action | Returns | Access Path |
|--------|---------|-------------|
| `conversation.process` | Yes | `response.speech.plain.speech` |
| `assist_satellite.start_conversation` | No | N/A — does not return response text |

### CQ-5: YAML Example Validity [ERROR]

**Check:** Every fenced YAML block (```` ```yaml ````) in the style guide must:
1. Parse without syntax errors (valid YAML structure)
2. Use real HA action/service domain names (not invented ones)
3. Use real entity domain prefixes (e.g., `light.`, `climate.`, not `thing.`)

**Known valid action domains:** `homeassistant`, `light`, `switch`, `climate`, `media_player`, `music_assistant`, `cover`, `fan`, `scene`, `script`, `automation`, `input_boolean`, `input_number`, `input_select`, `input_text`, `input_datetime`, `input_button`, `timer`, `counter`, `number`, `select`, `button`, `notify`, `tts`, `conversation`, `assist_satellite`, `rest_command`, `shell_command`, `logbook`, `persistent_notification`. This is not exhaustive — verify against HA docs if unsure.

**Exceptions:** Blocks explicitly marked as pseudocode, illustrative fragments, or `# (not real YAML)` are exempt.

📋 QA Check: Run on every YAML example added or modified in the guide.

### CQ-6: Modern Syntax in Examples [WARNING]

**Check:** All YAML examples must use HA 2024.10+ syntax. Flag these violations:

| Legacy (pre-2024.10) | Modern (2024.10+) | Ties to |
|---|---|---|
| `service:` | `action:` | AP-10 |
| `service_data:` | `data:` (under `action:`) | AP-10 |
| `trigger:` (singular, inside automation) | `triggers:` (plural) | §3.8 |
| `condition:` (singular, inside automation) | `conditions:` (plural) | §3.8 |
| `action:` (singular, inside automation) | `actions:` (plural) | §3.8 |

**Note:** Top-level `automation:` and `script:` keys in `configuration.yaml`, packages, and `scripts.yaml` are correctly singular — do NOT flag these.

**Exceptions:** Blocks that explicitly demonstrate the migration (showing old → new) or that document legacy behavior are exempt if clearly labeled.

📋 QA Check: Run on every YAML example added or modified in the guide.

### CQ-7: Template Safety / Jinja Robustness [WARNING]

**Check:** Every Jinja2 template in YAML examples must handle missing or unavailable entities gracefully. Flag any template that:
1. Uses `states('sensor.x')` without a `| default(...)` filter or an `{% if %}` availability guard
2. Accesses `.attributes.something` without checking the entity exists first
3. Pipes template output into TTS or conversation agents without guarding against `None`/`unavailable`/`unknown` results

**Fix pattern:**
```yaml
# ❌ WRONG — blows up if entity is unavailable
action:
  - alias: "Announce temperature"
    action: tts.speak
    data:
      message: "It's {{ states('sensor.outdoor_temp') }} degrees"

# ✅ CORRECT — guarded template
action:
  - alias: "Announce temperature"
    action: tts.speak
    data:
      message: >-
        {% set temp = states('sensor.outdoor_temp') | default('unknown') %}
        {% if temp not in ['unknown', 'unavailable'] %}
          It's {{ temp }} degrees
        {% else %}
          Temperature sensor is not available right now
        {% endif %}
```

**Special attention:** Blueprint inputs that feed into templates — the user's selected entity might not exist or might go offline. Always guard.

📋 QA Check: Run on every YAML example that contains `{{ }}` or `{% %}` blocks.

### CQ-8: Idempotency / Re-trigger Safety [WARNING]

**Check:** Every automation example must be safe to fire twice in rapid succession without producing unintended side effects. Flag these violations:

| Dangerous | Safe | Why |
|-----------|------|-----|
| `homeassistant.toggle` | `homeassistant.turn_on` / `turn_off` | Toggle reverses on re-trigger |
| `input_number.increment` without guard | `input_number.set_value` with absolute value | Increment doubles on re-trigger |
| No `mode:` specified on automations with slow actions | `mode: single` or `mode: restart` | Default `mode: single` is fine, but document it explicitly |
| Stateful sequences with no cooldown | `for:` duration on trigger or `delay:` with `mode: restart` | Prevents rapid-fire execution |

**Fix pattern:**
```yaml
# ❌ WRONG — GPS bounce triggers this twice, lights flash
action:
  - alias: "Toggle hallway"
    action: homeassistant.toggle
    target:
      entity_id: light.hallway

# ✅ CORRECT — idempotent, safe on re-trigger
action:
  - alias: "Turn on hallway"
    action: homeassistant.turn_on
    target:
      entity_id: light.hallway
```

**Exception:** Examples that explicitly demonstrate toggle behavior or counting are exempt if clearly labeled.

📋 QA Check: Run on every automation example. Flag any use of `toggle`, `increment`, or `decrement` without explicit justification.

### CQ-9: Entity Availability Guards [WARNING]

**Check:** Automation and blueprint examples that act on entities which may be optional or offline MUST include availability checks before the action. Flag when:
1. Blueprint inputs with `entity` selectors have no availability guard before use
2. Examples use `media_player`, `climate`, or `cover` entities without checking state != `unavailable`
3. Multi-entity sequences don't handle partial availability (e.g., 2 of 3 speakers are online)

**Fix pattern:**
```yaml
# ❌ WRONG — fails silently if speaker is offline
action:
  - alias: "Play music"
    action: media_player.play_media
    target:
      entity_id: !input target_speaker
    data:
      media_content_id: "some_uri"
      media_content_type: "music"

# ✅ CORRECT — checks availability first
action:
  - alias: "Check speaker available"
    condition: template
    value_template: >-
      {{ not is_state(target_speaker, 'unavailable') }}
  - alias: "Play music"
    action: media_player.play_media
    target:
      entity_id: !input target_speaker
    data:
      media_content_id: "some_uri"
      media_content_type: "music"
```

**Exception:** Examples explicitly demonstrating error handling or fallback patterns are exempt.

📋 QA Check: Run on every example that targets entities from blueprint inputs or entities that depend on network/cloud services.

### CQ-10: Observability for Multi-Step Flows [INFO]

**Check:** Any automation or blueprint with 3+ sequential actions involving external services (LLM calls, TTS, REST, Music Assistant) SHOULD include observability hooks for debugging. Flag when a multi-step flow has:
1. No `logbook.log` or `persistent_notification.create` on failure paths
2. No way to determine which step failed after the fact
3. Error handling that silently swallows failures (e.g., `continue_on_error: true` with no logging)

**What qualifies as a "multi-step flow":**
- LLM → TTS → speaker routing
- Presence detection → music selection → volume duck → playback
- Any sequence with 2+ network-dependent actions in a row

**Fix pattern:**
```yaml
# ❌ WRONG — if the LLM call fails, you'll never know why the speaker stayed silent
actions:
  - alias: "Get LLM response"
    action: conversation.process
    data:
      text: "What's the weather?"
      agent_id: !input conversation_agent
    response_variable: llm_response
    continue_on_error: true
  - alias: "Speak response"
    action: tts.speak
    data:
      message: "{{ llm_response.response.speech.plain.speech }}"

# ✅ CORRECT — logs failure, notifies on critical errors
actions:
  - alias: "Get LLM response"
    action: conversation.process
    data:
      text: "What's the weather?"
      agent_id: !input conversation_agent
    response_variable: llm_response
  - alias: "Check LLM response valid"
    if:
      - condition: template
        value_template: "{{ llm_response is defined and llm_response.response is defined }}"
    then:
      - alias: "Speak response"
        action: tts.speak
        data:
          message: "{{ llm_response.response.speech.plain.speech }}"
    else:
      - alias: "Log LLM failure"
        action: logbook.log
        data:
          name: "Blueprint Debug"
          message: "LLM call failed or returned empty response"
          entity_id: !input conversation_agent
```

**Note:** This is [INFO] severity — not every 3-step automation needs full observability. But if you've spent 20 minutes staring at a trace wondering why your proactive LLM blueprint went silent, you'll wish you had it.

📋 QA Check: Run on multi-step blueprints involving LLM, TTS, or Music Assistant flows. Suggest — don't enforce.

---

### 5 — Architecture & Structure

### ARCH-1: Layer Boundary Enforcement [WARNING]

**Check:** If the guide defines a layered architecture (e.g., the 6-layer voice assistant pattern), each layer MUST include explicit "MUST NOT" boundary rules.

**Format:**
```markdown
### Layer 1 — Hardware / ESPHome
- **MUST:** Define wake words, audio pipeline, LED patterns
- **MUST NOT:** Contain conversation logic, TTS selection, or intent routing
```

**Why:** Without negative boundaries, AI agents stuff logic into whatever layer they encounter first.

### ARCH-2: Naming Conventions Must Include Rationale [WARNING]

**Check:** If the guide recommends a naming convention (e.g., persona-based agents vs. scenario-based agents), it MUST explain WHY with a concrete comparison:

```markdown
# Why persona-based naming
- Persona-based: 2 agents (Rick, Quark) × unlimited intents = 2 agents
- Scenario-based: 1 agent per intent × 50 intents = 50 agents
Persona-based avoids agent explosion. Each persona is a reusable router.
```

### ARCH-3: File Location References Must Be Concrete [INFO]

**Check:** If the guide references where files should live, include:
- Exact paths (not "in the ESPHome config directory")
- A directory tree view for complex structures
- Which files are optional vs. required

### ARCH-4: Internal Cross-Reference Integrity [ERROR]

**Check:** Every internal reference must resolve:

1. **Section references** (`§X.X`) — must match an actual heading in the target file. Verify the number AND the heading text.
2. **File references** (e.g., `06_anti_patterns_and_workflow.md`) — the file must exist in `PROJECT_DIR`.
3. **AP-code references** (e.g., `AP-15`, `AP-39`) — must exist in the §10 scan tables.
4. **Check-ID references** (e.g., `SEC-1`, `CQ-3`) — must exist in this QA checklist.

**How to scan:**
```bash
# Find all §X.X references
grep -oE '§[0-9]+\.[0-9]+(\.[0-9]+)?' *.md | sort -u

# Find all file references
grep -oE '[0-9]{2}_[a-z_]+\.md' *.md | sort -u

# Find all AP-code references
grep -oE 'AP-[0-9]+' *.md | sort -u
```

Then verify each one resolves to an actual target. Dangling references are ERROR severity — they send the AI on a wild goose chase through files that don't exist.

📋 QA Check: Run after any section renumbering, file rename, or AP-code addition/removal.

### ARCH-5: Routing Reachability [WARNING]

**Check:** Every section in every style guide file must be reachable from at least one entry in the master index routing tables (operational mode tables, task-specific routing, or quick reference).

**How to verify:**
1. Collect all section numbers from all files: `grep -oE '^#{1,3} [0-9]+\.' *.md`
2. Collect all section numbers referenced in the master index routing tables
3. Flag any section that appears in (1) but not in (2)

**Orphan sections** — sections with no routing path — will never be loaded by the AI unless it happens to read the entire file. This defeats the token budget system (§1.9).

**Fix:** Either add the orphan section to a routing table entry, or move its content into a section that IS routed.

📋 QA Check: Run after adding new sections or modifying routing tables.

### ARCH-6: README Existence and Currency [WARNING]

**Check:** Every blueprint and script in the project must have a companion README file in the appropriate `readme/` subdirectory (see §11.14).

**Verification procedure:**
1. List all blueprint YAML files in `HA_CONFIG/blueprints/automation/madalone/` and `HA_CONFIG/blueprints/script/madalone/`.
2. For each YAML file, check that a corresponding `<stem>-readme.md` exists in `README_AUTO_DIR` or `README_SCRI_DIR`.
3. For each existing README, verify the header image URL matches the blueprint's `description:` field (both should use `HEADER_IMG_RAW` + filename).
4. Flag READMEs whose feature lists, input tables, or changelogs are visibly stale (e.g., README lists fewer inputs than the blueprint, changelog is behind the YAML description's "Recent changes").

**Naming convention check:**
- README filename must be `<blueprint_stem>-readme.md` — flag files using other patterns (e.g., missing `-readme` suffix, wrong stem).
- Agent prompt files (`*_agent_prompt_*.md`) in the readme directory are separate deliverables, not READMEs — don't flag them as naming violations.

**When to run:**
- During full audits (`run audit`)
- After any BUILD that creates a new blueprint/script
- After any EDIT that materially changes a blueprint's inputs or features

---

### 6 — Integration-Specific Checks

### INT-1: Conversation Agent Completeness [WARNING]

**Checks for 03_conversation_agents.md:**
- [ ] Dispatcher pattern has implementation skeleton
- [ ] MCP servers documented as tool source (HA 2025.2+)
- [ ] Confirm-then-execute pattern included (using `ask_question` or `conversation_id`)
- [ ] Agent naming rationale explains persona vs. scenario trade-off
- [ ] Max token budget guidance for `extra_system_prompt`
- [ ] Multi-agent coordination pattern documented

### INT-2: ESPHome Pattern Completeness [WARNING]

**Checks for 04_esphome_patterns.md:**
- [ ] `web_server` → `ota: platform:` dependency explained (web_server uses OTA platform for firmware upload endpoint)
- [ ] Packages merge/replace/`!extend`/`!remove` behaviors shown with examples
- [ ] Config archiving method recommended (git as primary)
- [ ] Debug sensor toggle via packages substitution documented
- [ ] Sub-devices version verified

### INT-3: Music Assistant Pattern Completeness [WARNING]

**Checks for 05_music_assistant_patterns.md:**
- [ ] `media_type` "no auto value" claim verified against current MA docs
- [ ] Enqueue mode list verified: `play`, `replace`, `next`, `add`, `replace_next`
- [ ] TTS duck/restore race condition addressed (polling `media_player.is_playing` OR note that `play_announcement` handles ducking natively)
- [ ] Alexa ↔ MA volume sync stability caveat included
- [ ] Search → select → play disambiguation pattern included
- [ ] MA + TTS coexistence on Voice PE guidance expanded
- [ ] Extra zone mapping implementation example included

### INT-4: Voice Assistant Pattern Completeness [WARNING]

**Checks for 08_voice_assistant_pattern.md:**
- [ ] 6-layer architecture has MUST NOT boundary rules per layer
- [ ] TTS streaming (HA 2025.10+) configuration or "documentation pending" note
- [ ] ElevenLabs fallback pattern: try ElevenLabs → fallback to HA Cloud TTS or Piper
- [ ] One-agent-per-persona clarified: doesn't mean one tool source per agent; MCP multi-tool is fine
- [ ] Mermaid data flow diagrams for interactive + one-shot flows
- [ ] Directory tree view in file locations reference
- [ ] All examples use `!secret` for API keys

---

### 7 — Zone & Presence Checks

### ZONE-1: GPS Bounce Protection Guidance [WARNING]

**Check:** If the guide includes zone-based automations or presence detection:
- Note whether HA 2024.x+ zone radius improvements reduce the need for manual GPS bounce protection
- If manual protection is still recommended, include the specific pattern (e.g., `for:` duration on zone triggers)
- Include concrete radius recommendations

### ZONE-2: Purpose-Specific Triggers [WARNING]

**Check:** If the guide documents `purpose`-specific triggers (e.g., `purpose: zone.enter`), include:
- Version requirement
- Stability status (stable, beta, experimental)
- Which trigger types support `purpose`

---

### 8 — Periodic Maintenance Checks

These checks should be run on a schedule (e.g., after every major HA release):

### MAINT-1: Version Claim Sweep

Re-verify ALL version claims in the guide against the latest release notes. Use the table in VER-1.

### MAINT-2: Deprecated Feature Sweep

Search the guide for any features that have been deprecated or removed in the latest HA release. Update migration paths.

### MAINT-3: New Feature Coverage

Check if the latest HA/ESPHome/MA releases introduced features that should be documented in the guide. Common areas:
- New conversation agent capabilities
- New voice assistant features
- New Music Assistant integration options
- New ESPHome components
- New automation trigger types or conditions

### MAINT-4: Link Rot Check

Verify all external links in the guide still resolve. Replace broken links with current equivalents.

### MAINT-5: Community Alignment Check [INFO]

**Check:** Periodically compare guide patterns against:
1. Official HA blueprint exchange: trending blueprints may reveal new conventions
2. HA community forums: recurring questions may indicate the guide missed a common use case
3. HA Discord / GitHub discussions: core devs may signal upcoming pattern changes

**What to look for:**
- Community-standard patterns the guide doesn't cover
- Patterns the guide recommends that the community has moved away from
- New HA features with community-established best practices not yet in the guide

**Frequency:** After every major HA release, or quarterly — whichever comes first.

📋 QA Check: Low priority. Run when updating the guide for a new HA release (pairs with MAINT-1/2/3).

---

## 9 — Blueprint Validation

These checks apply specifically to newly created or modified blueprint YAML files, not to the style guide prose.

### BP-1: Blueprint Metadata Completeness [ERROR]

**Check:** Every blueprint file MUST include all required metadata fields with valid content. Flag when any of these are missing or empty:

| Field | Required | Validation |
|-------|----------|------------|
| `blueprint.name` | YES | Non-empty, descriptive (not just "My Blueprint") |
| `blueprint.description` | YES | 1-2 sentences, max 160 characters (UI display truncation) |
| `blueprint.domain` | YES | Must be `automation` or `script` |
| `blueprint.homeassistant.min_version` | YES | Must match the highest-version feature used in the blueprint |
| `blueprint.source_url` | RECOMMENDED | URL to the blueprint's source (GitHub, community forum) |
| `blueprint.author` | RECOMMENDED | Attribution |
| Every `input:` → `name` | YES | Human-readable label |
| Every `input:` → `description` | YES | Explains what the input does and any constraints |
| Every `input:` → `default` | RECOMMENDED | Sensible default where possible; required for optional inputs |

**min_version cross-check:** The `min_version` value must be >= the highest version-dependent feature in the blueprint. Cross-reference against VER-1's verification table:

```yaml
# ❌ WRONG — uses collapsed sections (2024.6+) but claims 2024.2
blueprint:
  homeassistant:
    min_version: "2024.2.0"
  input:
    advanced:
      collapsed: true  # Requires 2024.6+

# ✅ CORRECT
blueprint:
  homeassistant:
    min_version: "2024.6.0"
```

📋 QA Check: Run on every new or modified blueprint file. This is the first check to run — if metadata is wrong, everything downstream is suspect.

### BP-2: Selector Correctness [WARNING]

**Check:** Every blueprint `input:` must use the most appropriate selector type for its purpose. Flag these mismatches:

| Input purpose | Wrong selector | Correct selector |
|---------------|---------------|------------------|
| Picking an entity | `text:` | `entity:` with `filter:` by domain/device_class |
| Picking a device | `entity:` | `device:` with `filter:` by integration/manufacturer |
| Picking an area | `text:` | `area:` |
| Picking a conversation agent | `entity:` filtered to `conversation` | `conversation_agent:` (native selector) |
| Yes/no toggle | `text:` or `input_boolean` entity | `boolean:` |
| Numeric value with range | `text:` | `number:` with `min:`/`max:`/`step:` |
| Choosing from fixed options | `text:` | `select:` with `options:` list |
| Time of day | `text:` | `time:` |
| Duration | `number:` in seconds | `duration:` |

**Also flag:**
- `entity:` selectors without `filter:` — the user sees ALL entities, making selection overwhelming and error-prone
- `entity:` selectors with `multiple: true` but no guidance on how many to select
- `number:` selectors without `min:`/`max:` — allows nonsensical values

**Fix pattern:**
```yaml
# ❌ WRONG — raw text for entity selection
input:
  speaker:
    name: "Speaker"
    selector:
      text:

# ✅ CORRECT — proper entity selector with domain filter
input:
  speaker:
    name: "Target speaker"
    description: "Media player to use for audio output"
    selector:
      entity:
        filter:
          domain: media_player
```

📋 QA Check: Run on every new or modified blueprint. Check each `input:` entry against the table above.

### BP-3: Edge Case / Instantiation Safety [WARNING]

**Check:** Mentally (or actually) instantiate the blueprint with edge-case inputs and verify it doesn't break. Test these scenarios:

| Scenario | What to check |
|----------|---------------|
| All optional inputs left blank | Do defaults produce a working automation? Do templates handle missing values? |
| `multiple: true` entity selector with 0 entities | Does the action sequence handle an empty list? |
| `multiple: true` entity selector with 1 entity | Does it still work (no list-vs-string bugs)? |
| `number:` input at min value | Does the automation behave sensibly (e.g., delay of 0 seconds)? |
| `number:` input at max value | No overflow, no absurd behavior (e.g., volume 100% at 3 AM)? |
| Target entity is unavailable | Does CQ-9 availability guard catch it, or does it fail silently? |
| Automation fires during HA restart | Are entity states `unknown` briefly? Does the blueprint handle that? |

**Integration with other checks:**
- BP-3 failures often trace back to CQ-7 (template safety) or CQ-9 (availability guards) violations
- If BP-3 finds a failure, check whether the root cause is already caught by another check — if not, that's a gap

**Reporting format:**
```
[WARNING] BP-3 | blueprint_name.yaml | Scenario: all optional inputs blank | input "custom_message" has no default, template renders "None"
```

📋 QA Check: Run on every new blueprint before sharing or deploying. This is the final validation — the "would a real user hit this?" check.

---

## 10 — Performance

### PERF-1: Resource-Aware Triggers [WARNING]

**Check:** Flag automation triggers and templates that cause unnecessary load on the HA event bus. Violations:

| Pattern | Problem | Fix |
|---------|---------|-----|
| `platform: state` without `entity_id:` | Fires on EVERY state change in the entire instance | Always specify `entity_id:` or use a more specific trigger |
| `platform: state` with broad `entity_id:` like `sensor.*` | Still fires too often on busy domains | Narrow to specific entities or use `attribute:` filter |
| Template trigger using `states.sensor` or `states.binary_sensor` | Iterates ALL entities in domain on every evaluation | Reference specific entities with `states('sensor.x')` |
| `platform: time_pattern` with `seconds: "*"` or `/1` | Evaluates every second — rarely justified | Use `/5`, `/10`, `/15`, or `/30` unless sub-second precision is required |
| Multiple triggers where one would suffice with `or` conditions | Extra event listeners for no benefit | Consolidate where possible |

**Fix pattern:**
```yaml
# ❌ WRONG — fires on every single state change in HA
triggers:
  - platform: state

# ❌ STILL BAD — broad domain match
triggers:
  - platform: state
    entity_id: sensor.*

# ✅ CORRECT — specific entity
triggers:
  - platform: state
    entity_id: sensor.outdoor_temperature
    attribute: temperature

# ❌ WRONG — evaluates every second
triggers:
  - platform: time_pattern
    seconds: "/1"

# ✅ CORRECT — evaluates every 30 seconds (sufficient for most monitoring)
triggers:
  - platform: time_pattern
    seconds: "/30"
```

**Context:** With a busy HA instance (Aqara sensors, Sonos speakers, Music Assistant, multiple conversation agents, ESPHome devices), unfiltered triggers can generate hundreds of unnecessary evaluations per minute, degrading system responsiveness.

📋 QA Check: Run on every automation and blueprint. Flag any `platform: state` without `entity_id:` and any `time_pattern` with intervals under 5 seconds.

---

### 11 — Pyscript Integration

These checks validate the interface between YAML configurations (automations, blueprints, scripts, packages) and the pyscript orchestration layer. Pyscript failures are particularly dangerous because HA does not surface them as visible errors — a wrong service call or missing helper silently does nothing.

### PSY-1: Service Call Parameter Correctness [ERROR]

**Check:** Every YAML action that calls a `pyscript.*` service MUST pass all required parameters with correct names and types. Flag when:
1. A `pyscript.*` service call is missing a required parameter
2. A parameter name doesn't match the `@service` function signature in the pyscript module
3. A parameter type is wrong (e.g., passing a string where the function expects a list)

**Why ERROR severity:** A misspelled or missing parameter in a pyscript service call produces no HA error log, no UI warning, no automation trace failure — the call silently does nothing. This is the hardest class of bug to diagnose.

**Verification procedure:**
1. Collect all `pyscript.*` service calls from YAML files: `grep -rn 'action: pyscript\.' *.yaml`
2. For each call, locate the corresponding `@service` function in `pyscript/*.py`
3. Compare the `data:` keys in the YAML call against the function's parameter list
4. Flag any mismatch — missing params, extra params, wrong names

**Common pyscript services to verify (update as modules are added):**

| Service | Module | Required Parameters |
|---------|--------|---------------------|
| `pyscript.agent_dispatch` | `agent_dispatcher.py` | Verify against `@service` signature |
| `pyscript.tts_queue_speak` | `tts_queue.py` | Verify against `@service` signature |
| `pyscript.memory_store` | `memory.py` | Verify against `@service` signature |
| `pyscript.duck_manager_*` | `duck_manager.py` | Verify against `@service` signature |

> **Note:** Parameter lists are not hardcoded here because they change as the pyscript modules evolve. Always verify against the actual `@service` decorator in the source file, not against this table.

📋 QA Check: Run on every automation, blueprint, or script that calls a `pyscript.*` service. Run after any pyscript module refactor that changes function signatures.

### PSY-2: Helper ↔ Package Coupling [ERROR]

**Check:** The `ai_*` helper ecosystem must be bidirectionally consistent:

**Direction A — Package → Pyscript:** Every `ai_*` helper entity defined in `packages/ai_*.yaml` SHOULD be referenced by at least one pyscript module. An orphan helper (defined but never read) is dead weight that clutters the entity registry and confuses dashboard builders.

**Direction B — Pyscript → Package:** Every `ai_*` helper entity referenced in a pyscript module (`state.get()`, `state.set()`, or Jinja2 `states()` calls) MUST be defined in the corresponding `packages/ai_*.yaml`. A missing helper definition causes a silent `None` return — no error, just wrong behavior.

**Severity:**
- Direction A (orphan helpers): [WARNING] — cleanup opportunity, not a runtime failure
- Direction B (missing definitions): [ERROR] — causes silent failures at runtime

**Verification procedure:**
1. Extract all helper entity IDs from `packages/ai_*.yaml` (look for `input_boolean`, `input_number`, `input_text`, `input_select`, `input_datetime` entries with `ai_` prefix)
2. Extract all `ai_*` entity references from `pyscript/*.py` (look for `state.get("input_*.ai_")`, `state.set()`, and string literals matching `input_*.ai_*`)
3. Compute set difference in both directions
4. Flag Direction B mismatches as [ERROR], Direction A as [WARNING]

📋 QA Check: Run after adding or removing helpers from AI packages, or after pyscript modules are refactored. Include in deep-pass audits.

### PSY-3: Blueprint Orchestration Toggles [WARNING]

**Check:** Every blueprint that integrates with pyscript orchestration features (dispatcher, TTS queue, ducking, dedup, whisper, etc.) MUST:
1. Expose each pyscript feature as an **optional boolean input** (or appropriate selector) with a sensible default
2. **Function without the orchestration layer enabled** — the pyscript features are enhancements, not hard dependencies
3. Use the HA Voice Assistant pipeline's configured agent as the **default** agent selection mechanism (Decision #49) — the pyscript dispatcher overrides this only when its toggle is enabled
4. Guard pyscript service calls behind the corresponding toggle:

```yaml
# ✅ CORRECT — dispatcher is optional, falls back to pipeline default
input:
  use_dispatcher:
    name: "Use AI dispatcher for agent selection"
    description: "When enabled, routes through pyscript.agent_dispatch instead of using the pipeline's configured agent. Requires pyscript orchestration layer."
    default: false
    selector:
      boolean:

actions:
  - alias: "Route through dispatcher or use pipeline default"
    choose:
      - conditions:
          - condition: template
            value_template: "{{ use_dispatcher }}"
        sequence:
          - alias: "Dispatch via pyscript"
            action: pyscript.agent_dispatch
            data:
              # ... dispatcher params
      - conditions: []
        sequence:
          - alias: "Use pipeline default agent"
            action: conversation.process
            data:
              agent_id: !input conversation_agent
```

```yaml
# ❌ WRONG — hard dependency on pyscript dispatcher, no fallback
actions:
  - alias: "Dispatch"
    action: pyscript.agent_dispatch
    data:
      # ... no toggle, no fallback
```

**Why:** Blueprints are shared artifacts. Users who haven't installed the pyscript orchestration layer must still be able to use the blueprint with basic functionality. The orchestration features are power-user enhancements.

📋 QA Check: Run on every blueprint that contains a `pyscript.*` service call. Verify toggle exists, default is sensible, and fallback path works.

### PSY-4: Dashboard Exposure Completeness [WARNING]

**Check:** Every tunable parameter in the pyscript orchestration layer and AI packages should be evaluated for dashboard exposure. Flag when:
1. A threshold, timeout, or limit is **hardcoded** in a pyscript module but could reasonably be user-tunable (e.g., TTS cache size limit, dedup TTL, budget tier thresholds, escalation intervals)
2. A tunable parameter has a helper entity defined but is **not documented** as a candidate for the AI management dashboard
3. An `input_number` helper lacks `min:`/`max:`/`step:` constraints (users will set nonsensical values via dashboard sliders)
4. An `input_select` helper has options that don't match the values the pyscript module actually checks for

**Decision framework for "should this be dashboard-exposed?":**

| Parameter type | Expose? | Example |
|---------------|---------|---------|
| On/off feature flag | Yes — `input_boolean` | Enable/disable proactive briefings |
| Numeric threshold with reasonable user control | Yes — `input_number` with min/max/step | TTS volume override, dedup TTL seconds, budget daily limit |
| Mode selection from fixed options | Yes — `input_select` | Dispatcher era override, ducking mode |
| Internal implementation detail | No — keep hardcoded | Markov chain decay factor, FTS5 tokenizer config |
| Security-sensitive value | No — keep in `!secret` or hardcoded | API keys, PIN codes, rate limit internals |

**Note:** This check is aspirational — not every hardcoded value needs a helper today. The goal is to ensure the *pattern* is followed: if it's tunable and user-facing, it gets a helper and a dashboard element. Flag gaps for future work, don't treat them as blockers.

📋 QA Check: Run during deep-pass audits. Compare pyscript module constants/config values against the helper entities in `packages/ai_*.yaml`. Low urgency — [INFO] severity for individual findings, [WARNING] at category level.

### PSY-5: Pyscript Service Registration [INFO]

**Check:** Every `pyscript.*` service call in YAML must correspond to an actually registered pyscript service (a function decorated with `@service` in a loaded pyscript module). Flag when:
1. A YAML file calls `pyscript.some_service` but no `@service` decorated function named `some_service` exists in any pyscript module
2. A pyscript module registers a service (`@service`) that is never called from any YAML file (potential dead code)

**Verification procedure:**
1. Collect all `@service` decorated functions: `grep -rn '@service' pyscript/*.py`
2. Collect all `pyscript.*` action calls: `grep -rn 'action: pyscript\.' *.yaml automations.yaml scripts.yaml blueprints/**/*.yaml`
3. Compare the two sets
4. Flag YAML calls with no matching registration as [ERROR] (will fail at runtime)
5. Flag registrations with no YAML callers as [INFO] (might be called programmatically from other pyscript modules — verify before flagging as dead code)

📋 QA Check: Run after adding or removing pyscript services, or during deep-pass audits.

### 13 — Live Codebase Validation

These checks validate the **live codebase on disk** (`HA_CONFIG`) — not style guide content. They catch integration-level bugs that slip through per-file reviews: orphaned inputs, stale entity references, parameter signature drift, and naming mismatches between YAML callers and their targets.

**Prerequisite:** `HA_CONFIG` must be mounted and accessible. If the SMB mount is unavailable, report all LIVE checks as `[SKIP] mount unavailable`.

### LIVE-1: Instance↔Blueprint Input Alignment [ERROR]

**Check:** Every key under `use_blueprint.input:` in `automations.yaml` and `scripts.yaml` must exist as a defined `input:` in the referenced blueprint YAML. Conversely, required blueprint inputs (no `default:`) must appear in every instance.

**Procedure:**
1. Extract all `use_blueprint:` blocks from `HA_CONFIG/automations.yaml` + `HA_CONFIG/scripts.yaml`
2. For each instance, read the referenced blueprint's `input:` definitions at `HA_CONFIG/<path>`
3. Flag: instance key not in blueprint inputs → `[ERROR]` orphaned input (will be silently ignored — likely a rename leftover)
4. Flag: required blueprint input (no `default:`) missing from instance → `[WARNING]` (HA may fail to load or use unexpected empty value)
5. Flag: instance value type mismatch (e.g., entity ID where `text:` selector expects display name) → `[WARNING]`

**Grep patterns:**
```bash
grep -n 'use_blueprint:' HA_CONFIG/automations.yaml HA_CONFIG/scripts.yaml
grep -n 'path:' HA_CONFIG/automations.yaml HA_CONFIG/scripts.yaml
```

📋 QA Check: Run after renaming, adding, or removing blueprint inputs. Critical after refactors like I-53 (pipeline_name migration).

### LIVE-2: Pipeline Name Existence [WARNING]

**Check:** Every `pipeline_name` value in automation/script instances and blueprint defaults resolves to an actual pipeline display name in HA's pipeline storage.

**Procedure:**
1. Read `HA_CONFIG/.storage/assist_pipeline.pipelines`, extract all `name` fields
2. Grep all blueprint defaults + instance values for pipeline-related inputs (`conversation_agent`, `llm_agent`, `llm_agent_id`, `persona_agent_id`, `bedtime_conversation_agent`, `agent_1`–`agent_10`, and any input with `pipeline` in the name)
3. Flag: value is a non-empty string that doesn't match any pipeline display name (case-insensitive) → `[WARNING]`
4. Flag: value looks like a ULID (26-char alphanumeric) or `conversation.*` entity ID → `[ERROR]` (should be display name post-I-53, see AP-54)

**Grep patterns:**
```bash
grep -rn 'pipeline' HA_CONFIG/blueprints/automation/madalone/*.yaml HA_CONFIG/blueprints/script/madalone/*.yaml | grep 'default:'
grep -n 'conversation_agent\|llm_agent\|persona_agent' HA_CONFIG/automations.yaml HA_CONFIG/scripts.yaml
```

📋 QA Check: Run after pipeline creation/deletion or after migrating from entity IDs to display names.

### LIVE-3: Pyscript Service Signature Drift [ERROR]

**Check:** Every `data:` key in a `pyscript.*` service call (across blueprints, automations, scripts, packages) matches an actual parameter name in the corresponding `@service`-decorated Python function.

**Procedure:**
1. Collect all `action: pyscript.*` calls from YAML files, extract each call's `data:` keys
2. For each pyscript service, read the `@service` function signature from `HA_CONFIG/pyscript/*.py`
3. Flag: YAML `data:` key not in function params → `[ERROR]` (will cause `unexpected keyword argument` at runtime)
4. Flag: required function param (no default value) not in YAML `data:` → `[WARNING]` (will cause `missing required argument`)

**Note:** This is a stricter, live-file version of PSY-1 (which checks guide examples). LIVE-3 checks the actual codebase.

**Grep patterns:**
```bash
grep -rn 'action: pyscript\.' HA_CONFIG/blueprints/**/*.yaml HA_CONFIG/automations.yaml HA_CONFIG/scripts.yaml HA_CONFIG/packages/*.yaml
grep -rn '@service' HA_CONFIG/pyscript/*.py
```

📋 QA Check: Run after adding/removing/renaming pyscript service parameters, or after any refactor that touches pyscript call sites.

### LIVE-4: Helper Entity Definition Completeness [ERROR]

**Check:** Every `input_boolean.*`, `input_number.*`, `input_text.*`, `input_select.*`, `input_datetime.*` entity referenced in pyscript modules or package YAML exists in either:
- A `helpers_input_*.yaml` file, OR
- A `packages/*.yaml` file, OR
- Created via HA UI (verified via `ha_get_entity_state`)

**Procedure:**
1. Extract all `input_*.*` references from `HA_CONFIG/pyscript/*.py` and `HA_CONFIG/packages/ai_*.yaml`
2. Extract all defined helpers from `HA_CONFIG/helpers_input_*.yaml` + `HA_CONFIG/packages/*.yaml`
3. Set difference: referenced − defined = missing → `[ERROR]` (entity won't exist at runtime)
4. Set difference: defined − referenced = potentially orphaned → `[INFO]` (may be used by UI automations or dashboards — verify before removing)

**Note:** Stricter live-file version of PSY-2. Some helpers are UI-created (especially `input_text` — see CLAUDE.md note about `helpers_input_text.yaml` not loading). Check HA state for those before flagging as missing.

**Grep patterns:**
```bash
grep -rn 'input_boolean\.\|input_number\.\|input_text\.\|input_select\.\|input_datetime\.' HA_CONFIG/pyscript/*.py HA_CONFIG/packages/ai_*.yaml
grep -n '^  [a-z_]*:' HA_CONFIG/helpers_input_*.yaml
```

📋 QA Check: Run after adding new pyscript modules, new packages, or after helper cleanup sweeps.

### LIVE-5: Orphaned Automation/Script Instances [WARNING]

**Check:** Every `use_blueprint.path:` value in `automations.yaml` and `scripts.yaml` points to a blueprint file that actually exists on disk.

**Procedure:**
1. Extract all `path:` values under `use_blueprint:` blocks from `HA_CONFIG/automations.yaml` + `HA_CONFIG/scripts.yaml`
2. Verify each path exists at `HA_CONFIG/<path>`
3. Flag: path not found on disk → `[ERROR]` (automation/script will fail to load)
4. Flag: blueprint exists but is in an `archive/` directory → `[WARNING]` (stale instance referencing a retired blueprint)

**Grep patterns:**
```bash
grep -A1 'use_blueprint:' HA_CONFIG/automations.yaml HA_CONFIG/scripts.yaml | grep 'path:'
```

📋 QA Check: Run after archiving, deleting, or moving blueprint files.

### LIVE-6: Cross-File Variable Consistency [WARNING]

**Check:** Variable names used in blueprint `variables:` blocks match the template references in `action:` blocks within the same file. Catches rename drift (e.g., `v_pipeline_id` renamed to `v_pipeline_name` in variables but stale `{{ v_pipeline_id }}` remains in an action template).

**Procedure:**
1. For each blueprint YAML file, extract all keys from `variables:` blocks (e.g., `v_pipeline_name`, `v_satellite_id`)
2. Grep the same file for all `{{ v_* }}` and `{{ v_*` template references (accounting for filters like `{{ v_name | default('') }}`)
3. Flag: template references a variable not defined in any `variables:` block in that file → `[ERROR]` (will render as empty string or cause Jinja error)
4. Flag: variable defined in `variables:` but never referenced in any template → `[INFO]` (dead variable — cleanup candidate)

**Note:** Variables may be defined in one `variables:` block and used in a nested `choose:` or `repeat:` scope — scan the entire file, not just adjacent action blocks.

📋 QA Check: Run after variable renames or blueprint refactors. Critical after bulk find-and-replace operations.

---

## 15.2 — When to Run Checks

### Automatic (AI suggests when relevant)

| Trigger | Checks to suggest |
|---------|-------------------|
| Generating or reviewing any YAML output | SEC-1, CQ-1, CQ-2, CQ-3, CQ-4, CQ-5, CQ-6, CQ-7, CQ-8, CQ-9, CQ-10, PERF-1, VER-2 |
| Editing a style guide `.md` file | AIR-1, AIR-2, AIR-3, AIR-4, AIR-6, AIR-7 for that file, plus its INT-x checklist if it has one |
| User mentions upgrading HA, ESPHome, or MA | MAINT-1 (version sweep), MAINT-2 (deprecation sweep), MAINT-3 (new feature coverage) |
| Adding or changing a version claim in the guide | VER-1 for that claim — verify before committing |
| Adding a new pattern or architecture section | AIR-2 (needs skeleton), ARCH-1 (needs boundary rules), ARCH-2 (needs rationale), ARCH-5 (must be routable) |
| User shares a changelog, release notes URL, or mentions a new release | MAINT-1, MAINT-2, MAINT-3 against that release |
| Renaming, renumbering, or moving sections between files | ARCH-4 (cross-ref integrity), ARCH-5 (routing reachability) |
| Building a new blueprint/script or materially editing one | ARCH-6 (README exists and reflects current state — §11.14) |
| Creating or materially editing a blueprint YAML file | BP-1 (metadata), BP-2 (selectors), BP-3 (edge cases), PERF-1, plus SEC-1, SEC-3, CQ-1 through CQ-10, VER-2 |
| Creating, editing, or refactoring pyscript modules or `packages/ai_*.yaml` | PSY-1 (service params), PSY-2 (helper coupling), PSY-4 (dashboard exposure), PSY-5 (service registration) |
| Creating or editing a blueprint that calls `pyscript.*` services | PSY-1 (service params), PSY-3 (orchestration toggles), LIVE-3 (signature drift) |
| Blueprint has `text` or `template` selector inputs | SEC-3 (template injection review) |
| Renaming, adding, or removing blueprint inputs | LIVE-1 (instance alignment), LIVE-6 (variable consistency) |
| Renaming or refactoring pyscript service parameters | LIVE-3 (signature drift), LIVE-4 (helper completeness) |
| Archiving, deleting, or moving blueprint files | LIVE-5 (orphaned instances) |
| Migrating pipeline references (entity IDs → display names) | LIVE-2 (pipeline name existence) |
| First conversation in a new session involving the style guide | Mention that `run audit` is available if it's been a while |

**For YAML generation checks:** run silently, fix violations before presenting output. Don't ask — just fix.

**For style guide edit checks:** mention which checks apply and offer to run them. Don't force it.

### User-triggered commands

The user can say any of these at any time:

| Command | What it does |
|---------|--------------|
| `run audit` | Full checklist against all style guide files. Report findings in `[SEVERITY] CHECK-ID \| file \| description` format. |
| `run audit on <filename>` | Full checklist scoped to one file. |
| `check secrets` | SEC-1 scan across all files — grep for inline keys/tokens. |
| `check versions` | VER-1 sweep — verify all version claims against current release notes via web search. |
| `check vibe readiness` | AIR-1 through AIR-7 — find vague guidance, missing skeletons, unclear decision logic, stale token counts, contradictory guidance. |
| `run maintenance` | MAINT-1 through MAINT-5 — version sweep, deprecation sweep, new features, link rot, community alignment. |
| `check <CHECK-ID>` | Run a single specific check (e.g., `check CQ-3`). |
| `sanity check` | Technical correctness scan: SEC-1 + SEC-3 + VER-1 + VER-3 + CQ-5 + CQ-6 + CQ-7 + CQ-8 + CQ-9 + PERF-1 + AIR-6 + ARCH-4 + ARCH-5 + PSY-1 + PSY-2 + LIVE-1 + LIVE-3 + LIVE-5. Only flags broken things — no style nits. |
| `check blueprint` or `check blueprint <filename>` | Full blueprint validation: BP-1 (metadata) + BP-2 (selectors) + BP-3 (edge cases) + SEC-1 + SEC-3 + CQ-5 + CQ-6 + CQ-7 + CQ-8 + CQ-9 + CQ-10 + PERF-1 + VER-2 + PSY-3 + LIVE-1 + LIVE-2 + LIVE-5 + LIVE-6. The complete pre-deployment checklist for a blueprint file. |
| `check pyscript` | PSY-1 through PSY-5 + LIVE-3 + LIVE-4 — full pyscript integration validation. Verifies service call parameters, helper coupling, blueprint toggles, dashboard exposure, service registration, and live signature/helper alignment. |
| `check live` | LIVE-1 through LIVE-6 — full live codebase validation against `HA_CONFIG`. Checks instance↔blueprint alignment, pipeline names, pyscript signatures, helper completeness, orphaned instances, and variable consistency. Requires `HA_CONFIG` to be mounted. |

> **Execution standard (applies to ALL commands above):** Every check runs to its full procedure as defined in §15.1. Spot-checking, eyeballing, sampling, or "structural scans" do not satisfy a check. If a procedure says "verify all 9 claims," verify all 9. If it says "parse every YAML block," parse every YAML block. If it says "compute the set difference," compute it — don't declare PASS on vibes. A check is either fully executed or reported as `[SKIP]` with a reason.

> **📋 Log pair requirement (§11.8.2):** Every command in the table above requires a mandatory log pair (progress + report) in `_build_logs/` before the first check runs. This is unconditional — a clean scan with zero findings still gets both logs. See §11.8.2 for naming conventions and format. Skipping the log pair is an AP-39 violation.

### Progress tracking

When fixing findings from any audit run, maintain a progress log:

```
fix_progress.log format:
[DONE] CHECK-ID | filename | one-line summary of change
[SKIP] CHECK-ID | filename | reason for skipping
```

If a fix session crashes or is resumed, read `fix_progress.log` FIRST and skip anything marked `[DONE]`.

---

## 15.3 — Quick Grep Patterns

Useful searches to catch common violations in YAML files:

```bash
# SEC-1: Find potential inline secrets
grep -rn 'api_key:\s*"' *.md *.yaml
grep -rn 'token:\s*"' *.md *.yaml
grep -rn 'password:\s*"' *.md *.yaml
grep -rn 'sk-' *.md *.yaml

# AIR-1: Find vague guidance
grep -rn 'appropriate\|reasonable\|common sense\|as needed\|good judgment' *.md

# VER-1: Find version claims to verify
grep -rn 'HA 20[0-9][0-9]\.[0-9]' *.md
grep -rn 'requires.*20[0-9][0-9]' *.md
grep -rn 'min_version' *.md

# CQ-1: Find action blocks without aliases
# (Requires YAML-aware parsing — use as rough indicator)
grep -rn 'action:' *.md | grep -v 'alias:'

# ARCH-1: Find layers without boundaries
grep -rn 'Layer [0-9]' *.md | grep -v 'MUST NOT'

# CQ-5: Find YAML blocks to validate
grep -n '```yaml' *.md

# CQ-6: Find legacy syntax in examples (should be action:, not service:)
# Run inside YAML fenced blocks only — manual review needed
grep -n 'service:' *.md | grep -v '#\|service_data\|service call\|service name'

# AIR-6: Measure actual token counts per file
for f in 0*.md; do printf "%-40s %sK tokens\n" "$f" "$(wc -c < "$f" | awk '{printf "%.1f", $1/4/1000}')"; done

# ARCH-4: Find all internal cross-references to verify
grep -oE '§[0-9]+\.[0-9]+(\.[0-9]+)?' *.md | sort | uniq -c | sort -rn
grep -oE '[0-9]{2}_[a-z_]+\.md' *.md | sort -u
grep -oE 'AP-[0-9]+' *.md | sort -u

# ARCH-5: Find all section headings (candidates for routing check)
grep -n '^#{1,3} [0-9]' *.md

# CQ-7: Find unguarded Jinja templates
grep -n "states('" *.md | grep -v 'default\|unknown\|unavailable'

# CQ-8: Find toggle/increment usage (potential re-trigger issues)
grep -rn 'homeassistant.toggle\|input_number.increment\|input_number.decrement' *.md *.yaml

# SEC-3: Find text inputs that may reach templates
grep -n 'selector:' *.md -A2 | grep 'text:'

# CQ-9: Find entity actions without availability checks
# (Rough — needs manual review of surrounding context)
grep -n 'media_player\.\|climate\.\|cover\.' *.md | grep -v 'unavailable'

# AIR-7: Find topics covered in multiple files (contradiction candidates)
for term in "continue_on_error" "volume" "tts" "error handling" "naming"; do
  echo "=== $term ===" && grep -l "$term" *.md
done

# BP-1: Check blueprint metadata completeness
for f in *.yaml; do
  echo "=== $f ===" && grep -c 'name:\|description:\|domain:\|min_version:\|source_url:' "$f"
done

# BP-2: Find text selectors that should probably be typed selectors
grep -n 'selector:' *.yaml -A2 | grep 'text:'

# BP-3: Find multiple:true inputs (edge case candidates)
grep -n 'multiple: true' *.yaml

# PERF-1: Find unfiltered state triggers
grep -n 'platform: state' *.md *.yaml | grep -v 'entity_id:'

# PERF-1: Find broad template iterations
grep -rn 'states\.sensor\|states\.binary_sensor\|states\.switch' *.md *.yaml

# PERF-1: Find aggressive time patterns
grep -n 'time_pattern' *.md *.yaml -A3 | grep -E 'seconds:.*(/1"|/1$|\*)'

# CQ-10: Find multi-step flows without logging (rough — look for conversation.process or tts without logbook)
grep -l 'conversation.process\|tts.speak\|music_assistant' *.md *.yaml | xargs grep -L 'logbook.log\|persistent_notification'

# PSY-1: Find all pyscript service calls in YAML (verify params against @service signatures)
grep -rn 'action: pyscript\.' *.yaml automations.yaml scripts.yaml
grep -rn 'action: pyscript\.' blueprints/**/*.yaml

# PSY-2: Find ai_* helper definitions in packages
grep -rn 'input_boolean\.\|input_number\.\|input_text\.\|input_select\.\|input_datetime\.' packages/ai_*.yaml | grep 'ai_'

# PSY-2: Find ai_* helper references in pyscript modules
grep -rn 'state\.get\|state\.set\|states(' pyscript/*.py | grep 'ai_'

# PSY-3: Find blueprints that call pyscript services (candidates for toggle check)
grep -rln 'pyscript\.' blueprints/**/*.yaml

# PSY-5: Find registered pyscript services
grep -rn '@service' pyscript/*.py | grep 'def '

# PSY-5: Cross-reference — pyscript services called but never registered
comm -23 \
  <(grep -roh 'pyscript\.[a-z_]*' *.yaml blueprints/**/*.yaml | sort -u) \
  <(grep -A1 '@service' pyscript/*.py | grep 'def ' | sed 's/.*def /pyscript./' | sed 's/(.*//' | sort -u)

# LIVE-1: Find all use_blueprint instances and their paths
grep -n 'use_blueprint:' automations.yaml scripts.yaml
grep -A1 'use_blueprint:' automations.yaml scripts.yaml | grep 'path:'

# LIVE-2: Find pipeline-related values (check against .storage/assist_pipeline.pipelines)
grep -rn 'conversation_agent\|llm_agent\|persona_agent\|pipeline' automations.yaml scripts.yaml | grep -v '^#'
# AP-54: Find stale entity IDs or ULIDs in pipeline inputs
grep -rn 'conversation\.[a-z_]*\|[0-9A-Z]\{26\}' automations.yaml scripts.yaml blueprints/**/*.yaml

# LIVE-3: Cross-reference pyscript data: keys against @service function params
grep -rn 'action: pyscript\.' blueprints/**/*.yaml automations.yaml scripts.yaml packages/*.yaml
grep -rn '@service' pyscript/*.py

# LIVE-5: Verify use_blueprint paths exist on disk
grep -A1 'use_blueprint:' automations.yaml scripts.yaml | grep 'path:' | sed 's/.*path: //' | while read p; do [ -f "$p" ] || echo "MISSING: $p"; done

# LIVE-6: Find variable definitions and template references in blueprints
grep -rn 'variables:' blueprints/**/*.yaml
grep -rn '{{ v_' blueprints/**/*.yaml
```

---

## 15.4 — Audit Tiers

Not every audit needs the full proctological exam. Loading all checks, all style guide sections, and the full target file in one pass is how audits crash mid-run — context load exceeds capacity and the AI starts dropping checks, forgetting earlier findings, or hallucinating passes on things it never actually verified.

Two tiers. Pick one based on the situation.

### Quick-Pass Tier

**Purpose:** Catch the stuff that actually breaks things. Template safety, naming violations, broken references, security holes, stale token counts. Fast, cheap, high-impact.

**When to use:**
- Routine reviews of a single file
- Post-edit sanity checks (not the formal `sanity check` command — that has its own check set)
- Quick sweeps when the user says "give it a once-over"
- Default tier when the user says "audit this" without specifying depth

**Check roster (15 checks):**

| Check ID | Category | What it catches |
|----------|----------|-----------------|
| SEC-1 | Security | Inline secrets — hardcoded API keys, tokens, passwords |
| SEC-3 | Security | Template injection via blueprint inputs |
| CQ-5 | Code Quality | Invalid YAML examples — syntax errors, invented domains |
| CQ-6 | Code Quality | Legacy syntax in examples (`service:` instead of `action:`, etc.) |
| CQ-7 | Code Quality | Unguarded Jinja templates — missing `| default()`, no availability checks |
| VER-1 | Version | Unverified version claims (skip web verification — flag unverifiable claims only) |
| VER-3 | Version | Deprecation entries missing version/removal/migration info |
| ARCH-4 | Architecture | Broken cross-references — dangling §X.X, missing AP-codes, dead file refs |
| PERF-1 | Performance | Resource-hungry triggers — unfiltered state triggers, aggressive time patterns |
| AIR-6 | AI-Readability | Token count drift — estimates off by >15% from measured values |
| PSY-1 | Pyscript Integration | Wrong or missing parameters in pyscript service calls |
| PSY-2 | Pyscript Integration | Helper entities referenced in pyscript but not defined in packages (Direction B only) |
| LIVE-1 | Live Codebase | Orphaned or missing inputs in automation/script instances vs. blueprint definitions |
| LIVE-3 | Live Codebase | Pyscript `data:` keys that don't match `@service` function parameters |
| LIVE-5 | Live Codebase | `use_blueprint.path:` pointing to non-existent or archived blueprint files |

**Context budget:** ~5–7K tokens of style guide. Load §10 scan table + §10.5 security checklist + the target file. No need for full pattern docs.

**Expected duration:** Single file: 1 turn. Multi-file: 1 turn per file, sequential.

### Deep-Pass Tier

**Purpose:** Full battery. Every check in §15.1, no shortcuts. This is the pre-publish review, the quarterly maintenance sweep, the "I haven't looked at this in a month and need to know it's solid" pass.

**When to use:**
- User explicitly says "deep audit", "full audit", or "deep-pass"
- Pre-publish reviews before syncing to git
- Quarterly maintenance sweeps (MAINT-1 through MAINT-5)
- After major HA version upgrades
- After significant style guide restructuring

**Check roster:** All checks in §15.1 — SEC-1 through SEC-3, VER-1 through VER-3, AIR-1 through AIR-7, CQ-1 through CQ-10, ARCH-1 through ARCH-6, INT-1 through INT-4, ZONE-1 through ZONE-2, MAINT-1 through MAINT-5, BP-1 through BP-3, PERF-1, PSY-1 through PSY-5, LIVE-1 through LIVE-6. No exclusions. **Note:** LIVE checks require `HA_CONFIG` to be mounted — report as `[SKIP] mount unavailable` if the SMB share is not accessible.

**Context budget:** ~12–15K tokens of style guide, loaded in stages per §11.15 (sectional chunking). Never load all at once.

**MANDATORY: Deep-pass audits MUST use sectional chunking (§11.15).** Running all checks in a single pass is what causes crashes. Each stage loads only the style guide sections relevant to that stage's checks, executes those checks, writes results to the audit checkpoint, then unloads before the next stage. See §11.15 for the stage definitions and execution protocol.

**Expected duration:** Single file: 3–4 turns (one per stage). Full guide sweep: 4–8 turns depending on finding density.

### Tier Selection Rules

| Situation | Tier | Rationale |
|-----------|------|-----------|
| `run audit` (no qualifier) | Deep-pass | The user asked for a full audit — give them one |
| `run audit on <file>` | Quick-pass | Single-file scope suggests a targeted check |
| `run audit on <file> deep` | Deep-pass | User explicitly requested depth |
| `sanity check` | Neither — uses its own check set (§15.2) | Sanity check is a defined command with a fixed roster |
| `check <CHECK-ID>` | Neither — runs one specific check | Single-check commands bypass tier selection |
| "Review this" / "look at this" | Quick-pass | Casual language → lightweight response |
| "Full review" / "thorough review" | Deep-pass | Explicit depth request |
| Post-edit verification (§11.1 step 7) | Quick-pass | Just checking the work, not auditing the universe |
| MAINT-x sweep | Deep-pass (MAINT checks only) | Maintenance sweeps are inherently comprehensive |

**Escalation:** A quick-pass that uncovers 3+ ERROR-severity findings automatically suggests escalation to deep-pass: *"I found 3 errors on quick-pass — want me to run a deep-pass to make sure there isn't more hiding underneath?"* The user decides.

**Log requirements:** Both tiers follow the same AP-39 log pair mandate (§11.8.2). Quick-pass gets a log pair. Deep-pass gets a log pair. No exceptions.

**Cross-references:** §11.15 (sectional chunking — how deep-pass stages are executed), §11.8.2 (log pair requirements), §15.2 (command table — tier selection per command).
