# Home Assistant Style Guide — Conversation Agents

Section 8 — Agent prompt structure, separation from blueprints, naming conventions.

> **Scope:** This section covers conversation agent prompts and configuration. Agents are built on **Extended OpenAI Conversation** (HACS — execution backend providing LLM-powered conversation entities with function calling) and assigned to **HA Voice Assistant pipelines** (routing/config layer — Decision #49). The Assist Pipeline handles wake word → STT → agent → TTS routing; Extended OpenAI Conversation provides the conversation entities. Patterns for prompt structure, tool/function exposure, PERMISSIONS tables, and multi-agent coordination are specific to how Extended OpenAI handles system prompts and custom functions. Native HA integrations (OpenAI Conversation, Anthropic, Google Gemini, Ollama) use the Assist API with Exposed Entities and have different scoping mechanisms — consult their respective docs.

---

## 8. CONVERSATION AGENT PROMPT STANDARDS

### 8.1 Follow the integration's official documentation
The prompt structure and configuration method depends on which conversation integration the user is using. While this guide focuses on Extended OpenAI Conversation, the general principles (separation of concerns, clear permissions, structured prompts) apply broadly. **Always consult the official documentation** for the specific integration being used to understand:
- How the system prompt is configured
- What template variables are available
- How tool/function calling works
- What model-specific constraints apply
- How `extra_system_prompt` interacts with the base prompt

Do not assume all integrations work the same way.

### 8.2 Separation from blueprints
- The agent's static system prompt lives in the integration's configuration (typically via HA UI).
- Blueprints ONLY pass dynamic, per-run context via `extra_system_prompt`:

```yaml
extra_system_prompt: >-
  {{ person_name }} just arrived home and heard: "{{ welcome_line }}".
  This is an arrival conversation. Help them set up their lights, TV,
  and music as per your rules.
```

**Three ways to invoke an agent with dynamic context:**

1. **Dispatcher-first via `pyscript.agent_dispatch`** (PREFERRED) — the standard path in this setup. The dispatcher selects the agent, TTS voice, and persona based on a 6-level routing algorithm (name → wake word → continuity → keywords → era → random). Blueprints call `pyscript.agent_dispatch` first, then use the returned `dispatch_agent` in `conversation.process`. See §14.5.1 Pattern 1 for the full calling convention.

```yaml
# Step 1: Dispatcher selects agent + voice + persona
- action: pyscript.agent_dispatch
  response_variable: dispatch
  data:
    wake_word: "bedtime"
    intent_text: "Starting bedtime routine"
    skip_continuity: true
  continue_on_error: true
- variables:
    dispatch_agent: "{{ (dispatch | default({})).get('agent', '') }}"
    dispatch_voice: "{{ (dispatch | default({})).get('tts_engine', '') }}"
    dispatch_persona: "{{ (dispatch | default({})).get('persona', 'rick') }}"

# Step 2: Use the selected agent for conversation
- action: conversation.process
  data:
    agent_id: "{{ dispatch_agent }}"
    text: "{{ prompt_text }}"
    extra_system_prompt: >-
      {{ person_name }} just arrived. Greet them and offer to set up
      their lights and music.
  response_variable: agent_response

# Step 3: Log to whisper network
- action: pyscript.agent_whisper
  data:
    agent_name: "{{ dispatch_persona }}"
    user_query: "Arrival greeting"
    agent_response: "{{ agent_response.response.speech.plain.speech | default('') | truncate(200) }}"
  continue_on_error: true
```

2. **Direct `conversation.process`** (FALLBACK) — used when the pyscript layer is unavailable, or for simple setups without the orchestration layer. The agent is specified via `!input conversation_agent`.

```yaml
- action: conversation.process
  data:
    agent_id: !input conversation_agent
    text: "{{ prompt_text }}"
    extra_system_prompt: >-
      {{ person_name }} just arrived. Greet them and offer to set up
      their lights and music.
    conversation_id: "{{ context.id }}"
  response_variable: agent_response
```

> 📋 **QA Check CQ-10:** Multi-step flows involving LLM calls, TTS, or Music Assistant should include observability hooks (logbook/notification on failure paths). See `09_qa_audit_checklist.md`.

2. **`assist_satellite.start_conversation`** (HA 2025.4+) — the preferred action for **proactive voice conversations** on Voice PE satellites. This wakes the satellite, speaks a TTS prompt, and listens for a reply — all routed through the satellite's assigned pipeline and conversation agent.

```yaml
- action: assist_satellite.start_conversation
  target:
    entity_id: !input voice_satellite
  data:
    start_message: "{{ welcome_line }}"
    extra_system_prompt: >-
      {{ person_name }} just arrived home. This is an arrival
      conversation. Help them set up lights, TV, and music.
    conversation_id: "{{ context.id }}"
```

**Key differences:**
- `conversation.process` **returns a response** you can extract and act on. The agent doesn't directly speak — you route the response to TTS yourself. Access the response text via:
  ```yaml
  response_variable: agent_response
  # Then use: {{ agent_response.response.speech.plain.speech | default('') }}
  ```
  The full response object also contains `agent_response.response.speech.plain.extra_data` (if the agent returned structured data) and `agent_response.conversation_id` (for multi-turn threading).
- `start_conversation` is **fire-and-forget** — it does NOT return a response variable. The satellite handles the full voice loop (speak → listen → respond → listen…) autonomously through its assigned pipeline. If your blueprint needs to extract or branch on the agent's response text, you **must** use `conversation.process` instead.
- Both accept `extra_system_prompt` for per-run context injection.
- Both accept `conversation_id` for multi-turn context (see below).

**Which one to use — decision rule:**

| Scenario | Use | Why |
|---|---|---|
| Blueprint needs to read/branch on the LLM response | `conversation.process` | Only way to get the response text |
| Proactive voice prompt on a satellite ("Hey, welcome home!") | `start_conversation` | Handles TTS + wake + listen loop automatically |
| Automation-only flow, no voice satellite involved | `conversation.process` | No satellite to target |
| Voice flow where you need fallback logic on the response | `conversation.process` + manual TTS | Fire-and-forget won't let you inspect the reply |

> 📋 **QA Check CQ-4:** Return values must be documented — what the action returns, access path, and whether it returns at all. See `09_qa_audit_checklist.md`.

The `extra_system_prompt` should be **short** — just the facts that change per invocation. Never repeat personality, rules, or device lists that belong in the agent's own prompt.

**`conversation_id` for multi-turn context:**
When a conversation spans multiple exchanges (bedtime negotiator, coming-home flow, interactive troubleshooting), pass a consistent `conversation_id` so the agent retains memory of prior turns within the session. Without it, each invocation is stateless — the agent forgets what was just said.

- Use `{{ context.id }}` to tie conversation turns to the automation run.
- For `start_conversation`, the satellite's built-in listen loop handles multi-turn automatically within a single invocation, but if your blueprint calls it multiple times (e.g., after a delay or user action), you need an explicit `conversation_id` to maintain continuity.
- **Do not reuse** a `conversation_id` across different automation runs — stale context from a previous session will confuse the agent.

**Token budget awareness:** The static system prompt + `extra_system_prompt` + conversation history + tool definitions all compete for the model's context window. Keep the static prompt as lean as possible.

**Practical sizing for Extended OpenAI Conversation:**
- A PERMISSIONS table with 10 devices ≈ 300–500 tokens. 30 devices ≈ 1,000–1,500 tokens.
- Each exposed tool/function adds ~100–200 tokens for its schema.
- Llama 4 Maverick (current default): 1M tokens. Claude Opus 4.6 (Portuondo Standard): 1M tokens. Local models via compatible API: varies wildly (check your model card).
- **Rule of thumb:** If your system prompt + tool schemas exceed 20% of the model's context window, you're eating into conversation depth. A 3,000-token system prompt on a 128K model is fine; the same prompt on a 4K model is a disaster.
- To check token count: paste your full system prompt into [OpenAI's tokenizer](https://platform.openai.com/tokenizer) or use `tiktoken` locally.

**Max token budget guidance:**

| Component | Target budget | Notes |
|---|---|---|
| Static system prompt (PERSONALITY + PERMISSIONS + RULES + STYLE) | < 2,500 tokens | This is what you control directly. Aim for the leanest prompt that still constrains the agent properly. |
| `extra_system_prompt` (per-run context) | < 500 tokens | Just the facts: who triggered, what time, what sensor readings. Not personality. |
| Tool/function schemas (auto-generated from exposed scripts) | < 1,500 tokens | Each tool ~100–200 tokens. 8 tools ≈ 1,000–1,600 tokens. |
| **Total pre-conversation overhead** | **< 4,500 tokens** | Everything that's consumed before the user says a word. |

Extended OpenAI Conversation's `extra_system_prompt` field has no hard character limit, but excessively long prompts degrade response quality even on large-context models — the model spends attention budget parsing your instructions instead of reasoning about the user's request. If your static prompt exceeds ~3,000 tokens, audit it:
- Are device entries duplicated between PERMISSIONS and RULES?
- Are examples too verbose? (One example per concept is enough.)
- Can rule sets be compressed? ("Never do X, Y, or Z" vs three separate rules.)

### 8.3 Mandatory prompt sections
Every conversation agent system prompt MUST be organized into these sections, in this order:

**PERSONALITY**
- Who the agent is (character, tone, mannerisms)
- How they address the user
- **Direct-address anchor:** The prompt must include an explicit statement that the agent is speaking directly to the user (e.g., `You are speaking directly to the user — always address them as "you", never in third person.`). Without this, LLMs default to third-person framing when context mentions the user's name.
- Response length and style constraints
- **Gender & pronoun markers (multi-persona systems):** When a persona has a specific gender identity, state it explicitly in the PERSONALITY section with pronouns (e.g., `You are a man. Pronouns: he/him.`). LLMs — especially instruction-tuned models — will default to assumptions without reinforcement. In multi-agent systems, every agent's roster/expertise table that names the persona must also include the pronoun marker (e.g., `Doctor Portuondo (he/him)`). One mention in the persona's own prompt is not enough — every cross-reference across all agents must carry the marker, or the LLM loses the signal.

**PERMISSIONS**
- Explicit list of allowed devices with entity IDs and allowed services
- Clear statement: "You are NOT allowed to control any devices outside this list."
- Use a table format for clarity:

```
| Device           | Entity ID              | Services                          |
|------------------|------------------------|-----------------------------------|
| Workshop lights  | light.workshop_lights  | light.turn_on / light.turn_off    |
```

> **Why a manual table?** Extended OpenAI Conversation uses `async_should_expose` for entity **visibility** (the CSV list agents see), so the Exposed Entities UI does control which entities appear in the prompt. However, it bypasses HA's native Assist API for **service execution** — agents can call services on ANY entity they know the ID of, regardless of exposure settings. The PERMISSIONS table is a **compensating control** for this execution bypass — the prompt is the only place to enforce device scoping. For native integrations (OpenAI Conversation, Google Gemini, etc.) that use the Assist API, both visibility AND execution are managed through the Exposed Entities UI, and a manual table would be redundant. The tool exposure pattern in §8.3.2 is the first line of defense; this table is the second.

**RULES**
- Specific behavioral rules for the scenario (arrival flow, bedtime flow, etc.)
- What to do on unclear/misheard input
- What NOT to do (e.g., never toggle TV unless explicitly asked)
- Conversation flow / decision tree
- **Proactive-call guardrail:** When the agent is called programmatically (e.g., by `notification_follow_me`, `email_follow_me`, or any blueprint using `conversation.process`) to summarize content, it must respond with the summary only. It must NOT look up, check, or call any automation entities — the calling blueprint already verified all preconditions. Without this guardrail, LLMs will "helpfully" try to verify automation states, hallucinate entity names (e.g., appending a persona suffix), and break the flow with 404 errors.

**STYLE**
- Output constraints (max sentence count, no emojis, no entity names spoken aloud, etc.)
- "Act first, talk second" — call the service, then confirm. **Exception: safety-critical devices** (see below).
- Any per-persona quirks

**Safety tier for device actions:**

Not all actions should be fire-and-forget. Divide exposed devices into two tiers:

| Tier | Behavior | Examples |
|------|----------|----------|
| **Fire-and-forget** | Act first, confirm after. No confirmation needed. | Lights, speakers, media players, thermostats (within safe range) |
| **Confirm-first** | Ask the user to confirm BEFORE executing. Never act on ambiguous input. | Locks, garage doors, covers, alarm panels, irrigation, any device where accidental activation causes a security or safety risk |

In the agent's RULES section, explicitly list which devices require confirmation:

```
## RULES
- CONFIRM BEFORE ACTING on: front_door_lock, garage_door, alarm_panel.
  Say what you're about to do and wait for explicit "yes" / "do it" / "go ahead".
  Never infer confirmation from ambiguous responses like "sure" or "I guess".
- All other devices: act first, confirm after.
```

**Implementing confirm-first in practice:**

The RULES section tells the LLM to ask for confirmation, but the conversation must actually support multi-turn exchange. Two patterns depending on how you invoke the agent:

*Pattern 1: `conversation_id` threading (for `conversation.process`).* Pass a stable `conversation_id` so the agent remembers it asked for confirmation on the previous turn. The LLM internally tracks "I asked about the garage door, user said yes, now I'll execute."

```yaml
# Turn 1 — user says "close the garage"
- action: conversation.process
  data:
    agent_id: !input conversation_agent
    text: "{{ user_request }}"
    conversation_id: "{{ context.id }}"
  response_variable: turn1
# Agent responds: "You want me to close the garage door? Say 'yes' to confirm."

# Turn 2 — user says "yes"
- action: conversation.process
  data:
    agent_id: !input conversation_agent
    text: "yes"
    conversation_id: "{{ context.id }}"   # Same conversation_id — agent remembers Turn 1
  response_variable: turn2
# Agent now executes the garage door close, because it has multi-turn memory.
```

*Pattern 2: `start_conversation` (for Voice PE satellites).* The satellite's built-in listen loop already handles multi-turn — the agent asks for confirmation, the satellite listens for the reply, and the agent acts. No blueprint-side threading needed within a single `start_conversation` invocation.

*Pattern 3: `ask_question` for structured confirmation (HA 2025.7+).* When you need programmatic branching on the user's answer (not just LLM judgment):

```yaml
# Blueprint asks the user directly, bypassing the LLM for the confirmation step
- action: assist_satellite.ask_question
  data:
    entity_id: !input voice_satellite
    question: "I'm about to close the garage door. Should I go ahead?"
    preannounce: false
    answers:
      - id: confirm
        sentences:
          - "yes"
          - "do it"
          - "go ahead"
          - "close it"
      - id: cancel
        sentences:
          - "no"
          - "cancel"
          - "never mind"
          - "stop"
  response_variable: confirm_answer
  continue_on_error: true

- choose:
    - conditions: "{{ confirm_answer is defined and confirm_answer.id == 'confirm' }}"
      sequence:
        - alias: "Close the garage door (confirmed)"
          action: cover.close_cover
          target:
            entity_id: cover.garage_door
  default:
    - alias: "Announce cancellation"
      action: tts.speak
      data:
        message: "Cancelled. Garage door stays open."
```

Pattern 3 is the most robust because confirmation isn't relying on LLM judgment — the sentence matching is deterministic. Use it for the highest-risk actions (locks, alarm panels). Patterns 1–2 are fine for medium-risk confirmations where the LLM's own judgment is adequate.

> **Forward-looking note:** HA's voice roadmap (Chapter 10) plans native "protected entities" that enforce verbal confirmation at the platform level. Until that ships, this prompt-level guardrail is the only defense. When HA adds native support, the confirm-first tier moves from prompt rules to entity configuration — but keep the prompt rules as defense-in-depth.

**Time-based personality progressions (cadence formulas):**

Persona prompts can include `now().hour` Jinja2 conditionals that shift personality across the day. These are placed in the PERSONALITY section and control what the LLM *generates* (text content, speech patterns, mood). Five time brackets are used to distinguish late night (still up) from early morning (waking up):

```
Your current drunk level: {% if now().hour < 5 %}still completely hammered from last night{% elif now().hour < 9 %}severely hungover{% elif now().hour < 12 %}hungover but functional{% elif now().hour < 17 %}casually drinking{% elif now().hour < 21 %}noticeably drunk{% else %}completely hammered{% endif %}.
```

The `hour < 5` bracket ensures that 0:00-4:59 continues the late-evening persona (e.g., "it's way too late") rather than triggering morning behavior (e.g., "hate mornings"). The boundary at hour 5 aligns with the dispatcher's `late_night` era (0-5).

The cadence formula is a TEXT layer — it affects LLM output (including audio tags like `[slurring]`, `[burps]` that ElevenLabs v3 processes as voice direction). A separate VOICE layer adds mood modulation for non-agent TTS (notifications, announcements, briefings) via per-agent helpers: `input_number.ai_voice_mood_{agent}_stability` (v3's one working VoiceSettings param) + `input_text.ai_voice_mood_{agent}_tags` (audio tag prefixes like `[slurring]`, `[whispers]`). Written hourly by the `voice_mood_modulation.yaml` blueprint. See §14.8 for TTS voice profile routing.

**Rules for cadence formulas:**
- Keep the `now().hour` breakpoints consistent between the prompt formula and the TTS voice profile mapping.
- Never exceed 250 words in any persona's response constraint — TTS has a hard character limit.
- Tag placement instructions (`[burps]`, `[slurring]`, `[groaning]`) are text cues for the LLM, not SSML — ElevenLabs reads them as text or skips them.

### 8.3.1 Example prompt skeleton
Here's a minimal but complete example following all four mandatory sections:

```
You are Rick, a sarcastic but helpful AI assistant in a smart home.
Keep responses under 2 sentences unless the user asks for detail.
Address the user by name when you know it. Never break character.

## PERMISSIONS

You may ONLY control the devices listed below. You are NOT allowed to control
any devices outside this list. If the user asks for something you can't do,
tell them it's not in your jurisdiction.

| Device             | Entity ID                | Allowed services                        |
|--------------------|--------------------------|------------------------------------------|
| Workshop lights    | light.workshop_lights    | light.turn_on / light.turn_off / light.toggle |
| Workshop speaker   | media_player.workshop    | media_player.volume_set / media_player.media_pause |
| Workshop TV        | media_player.workshop_tv | media_player.turn_on / media_player.turn_off |

## RULES

- If the user says something unclear, ask ONE clarifying question. Don't guess.
- Never turn on the TV unless the user explicitly mentions TV or a show/movie.
- When the user says "goodnight", turn off all lights and stop media. Don't ask.
- If the user asks about the weather, answer from context. Don't make up data.

## STYLE

- Act first, confirm after. Call the service, THEN tell the user what you did.
- Never speak entity IDs aloud. Say "workshop lights", not "light.workshop_lights".
- Max 2 sentences per response. Exception: if the user explicitly asks for an explanation.
- No emojis. No markdown formatting. Responses are spoken aloud via TTS.
```

This skeleton is intentionally lean. Scenario-specific agents (Coming Home, Bedtime, etc.) add to the RULES and PERMISSIONS sections but keep the same structure.

**What a badly structured prompt looks like (and why it fails):**

```
# ❌ BAD — common AI-generated prompt anti-patterns

You are Rick. You're sarcastic. You control smart home devices.
You can turn on lights. The lights are light.workshop_lights.
Don't turn on the TV unless asked. You can also control the speaker
which is media_player.workshop. Be brief. If someone says goodnight
turn everything off. You can use light.turn_on and light.turn_off.
Also media_player.volume_set. Keep it short. No emojis.
The user is Miquel. Always be in character.
```

**Why this fails:**
- **No sections** — LLMs lose track of permissions vs rules vs style when everything is a wall of text. Device A's entity gets mixed up with Device B's allowed services.
- **Permissions scattered** — entity IDs and allowed services are sprinkled across multiple sentences. The model can't reliably extract "what can I control?" from this.
- **Repeated instructions** — "be brief" and "keep it short" waste tokens saying the same thing. Token budget matters (§8.2).
- **No explicit denial** — missing "you are NOT allowed to control anything else." Without this, LLMs happily hallucinate additional capabilities.
- **No structured device table** — tables let the model do exact lookup. Prose descriptions invite interpolation and guessing.

**Result in practice:** The agent occasionally controls devices not in its scope, confuses which services go with which entity, and responds inconsistently because style rules are buried between device definitions.

### 8.3.2 Tool/function exposure patterns
When using integrations that support tool/function calling (Extended OpenAI Conversation, etc.), exposed scripts and services become the agent's hands. Structure them for clarity:

**Expose thin wrapper scripts as tools (see also §7.8):**
- One script per atomic action: `voice_media_pause`, `voice_lights_cinema_mode`, `voice_set_thermostat`.
- Script `description` fields serve **two audiences**: the LLM sees them as tool descriptions, AND humans see them in the HA UI script list. Write primarily for the model (be explicit about when to call, what parameters to pass, what NOT to use it for), but keep the language clear enough that a human scanning the UI can also understand the script's purpose. This is a different standard from blueprint input descriptions (§3.3), which are written for humans only.
- Keep the script's `sequence` minimal. Complex logic belongs in an automation the script triggers, not in the script itself.

**Tool description best practices:**

```yaml
script:
  voice_media_pause:
    alias: "Voice – Pause Active Media"
    icon: mdi:pause-circle
    description: >-
      Pauses whatever is currently playing on the nearest speaker.
      Call this when the user says "pause", "stop the music", "shut up",
      or any variation of wanting audio to stop. Do NOT call this for
      volume changes — use voice_volume_set instead.
    sequence:
      - action: automation.trigger
        target:
          entity_id: automation.voice_active_media_controls
        data:
          skip_condition: true
          variables:
            command: "pause_active"
```

**What NOT to expose as tools:**
- Raw `homeassistant.turn_off` with no target constraints — the agent could nuke anything.
- Services that modify automations or system config.
- Anything that writes to the filesystem or installs packages.

Constrain the agent's capabilities through which tools you expose. The PERMISSIONS section in the prompt is a second line of defense, not the first.

**`execute_service` naming and guards:**
- The function spec name MUST be `execute_service` (singular). **Never** `execute_services` (plural) — the plural form breaks the native function handler silently.
- The native function name is `execute_service` (batch/list variant) or `execute_service_single` (Standard single-call variant).
- LLMs will hallucinate plausible-sounding services that don't exist in HA (e.g., `notify.clear_messages`, `notify.*.clear_count`). When a hallucinated call fails, the `ServiceNotFound` error gets spoken back through TTS. **Guard against known hallucination patterns** by adding explicit "NEVER use this for X" clauses in the `execute_service` description. Current guards:
  - Phone notifications cannot be cleared, dismissed, or marked as read from HA — no such services exist.

### 8.3.3 MCP servers as tool sources (HA 2025.2+)

Since HA 2025.2, **Model Context Protocol (MCP)** servers provide a second, integration-agnostic way to expose tools to conversation agents. An MCP server can make scripts, REST APIs, databases, or external services available as callable tools to any MCP-compatible agent.

**How MCP tools relate to wrapper scripts:**

| Tool source | Best for | Limitations |
|---|---|---|
| Exposed scripts (§8.3.2) | Device control, HA service calls, anything needing HA entity targeting | Requires creating scripts in HA; tool descriptions live in YAML |
| MCP servers | Information retrieval, external APIs, multi-step reasoning, to-do lists, calendar queries | Requires running a separate MCP server process; available since HA 2025.2 |

These are **complementary, not competing** tool sources. A single conversation agent can use both exposed scripts AND MCP-provided tools simultaneously. The two-variants-per-persona rule (§8.4) limits the number of *agents*, not the number of tool sources per agent. A single `rick_standard` agent can have 5 exposed scripts AND 3 MCP servers feeding it tools.

**Security principle:** The same caution applies to MCP as to exposed scripts — only connect MCP servers you trust. Each MCP server extends what the LLM can *do*, and there's no sandbox. The PERMISSIONS section in the agent prompt is your compensating control for MCP tools, just as it is for exposed scripts.

**When to use MCP over scripts:**
- The capability doesn't map to an HA service call (e.g., "search the web", "check my calendar", "query a database").
- The tool needs complex input/output schemas that are awkward to express as script fields.
- You're using the native OpenAI Conversation integration, which supports MCP tools (HA 2025.2+).

**When to stick with scripts:**
- Device control (lights, media, climate) — scripts give you validation, logging, and a single source of truth in HA.
- You need the tool to appear in the HA script list for manual testing.
- You're on Extended OpenAI Conversation, which uses its own function spec format (MCP interop depends on the integration version).

> **HA as MCP server:** Conversely, HA can also act as an MCP *server*, exposing your home's entities and actions to external AI systems (Claude Desktop, ChatGPT, etc.). This is configured separately from the conversation agent stack and is not covered in this guide. See the [HA MCP integration docs](https://www.home-assistant.io/integrations/mcp_server/).

### 8.4 Agent naming convention
Agent entity IDs follow the pattern: `conversation.<persona>_<variant>`

Two variants exist per persona:
- **standard** — all non-bedtime interactions. Tools: execute_service(s), memory_tool, web_search, pause_media, shut_up, stop_radio
- **bedtime** — sleep transition, audiobook, countdown. Tools: execute_service(s), memory_tool, web_search, audiobook, countdown, skip

**Current agents (21 total = 5 personas × 4 variants + 1 Therapy):**

| Persona | Standard | Bedtime | Music Compose | Music Transfer |
|---------|----------|---------|
| Rick Sanchez | `conversation.rick_standard` | `conversation.rick_bedtime` | `conversation.rick_music_compose` | `conversation.rick_music_transfer` |
| Quark | `conversation.quark_standard` | `conversation.quark_bedtime` | `conversation.quark_music_compose` | `conversation.quark_music_transfer` |
| Deadpool | `conversation.deadpool_standard` | `conversation.deadpool_bedtime` | `conversation.deadpool_music_compose` | `conversation.deadpool_music_transfer` |
| Kramer | `conversation.kramer_standard` | `conversation.kramer_bedtime` | `conversation.kramer_music_compose` | `conversation.kramer_music_transfer` |

**Why four variants?** Each variant has a genuinely different tool set that justifies a separate conversation agent:
- **Standard:** Full general-purpose tool set (execute_services, web_search, memory, handoff, escalation, focus guard, etc.)
- **Bedtime:** Sleep-specific tools (audiobook, countdown, skip) + safety concerns (user is falling asleep)
- **Music Compose:** Composition tools (compose_music, music_library) + per-persona musical identity. Reached via `handoff_agent` with `variant: "music compose"`.
- **Music Transfer:** Library management tools (music_library, web_search, execute_services) + per-persona library context. Reached via `handoff_agent` with `variant: "music transfer"`.
- **Therapy** (Portuondo only): Memory-focused tools (memory_tool, memory_related, save_user_preference). Reactive-only handoff — no proactive routing during sessions.

All other context differences (time of day, presence, media state, scenario) are handled by `sensor.ai_hot_context` injection — no separate agent needed.

**Why not per-scenario agents?** Scenarios like "coming home" or "proactive announcement" inject their context via `extra_system_prompt` to the same standard agent. The per-scenario agent model (which would produce O(personas × scenarios) agents) was explicitly rejected in favor of L1 hot context injection. Only different tool sets justify separate variants.

**Variant discovery:** The dispatcher auto-discovers variants from HA pipeline display names. Any pipeline named `"<Persona> - <Variant>"` auto-registers. No hardcoded allowlist — adding a new variant type is just creating a pipeline in the HA UI.

Each agent's system prompt is configured in the Extended OpenAI Conversation integration UI. The agent is assigned to an Assist Pipeline (Settings → Voice Assistants), which handles wake word → STT → agent → TTS routing.

**Invalid — don't do this:**
- ~~`Rick - Coming Home`~~ — "Coming Home" is a scenario, not a different tool set. Inject via `extra_system_prompt`.
- ~~Creating a separate agent per room~~ — Use `extra_system_prompt` to inject room context.

**Valid variant pipelines** (different tool sets):
- `Rick - Bedtime` — audiobook/countdown tools
- `Rick - Music Compose` — compose_music/music_library tools + Rick's musical identity
- `Rick - Music Transfer` — music_library/web_search tools + Rick's library voice
- `Doctor Portuondo - Therapy` — memory/preference tools + reactive-only handoff

### 8.5 Multi-agent coordination
When multiple agents exist (Rick, Quark, Deadpool, Kramer), they operate independently — each agent has its own system prompt, tools, and conversation history.

**Current state:** This system uses a **pyscript orchestration layer** for inter-agent coordination:

- **`agent_dispatcher.py`** — 6-level routing: explicit name → wake word → continuity → topic keywords → time-of-day era → random fallback. Reads from `assist_pipeline.pipelines` for persona discovery.
- **`voice_handoff.yaml`** — Voice-initiated agent switching blueprint (I-24). LLM tool sets flag → blueprint switches satellite pipeline → greeting → mic reopen. Per-satellite, chainable. Supersedes the archived `agent_handoff.py`.
- **`agent_whisper.py`** — Records interactions to L2 memory. Detects mood via keyword matching (zero LLM calls). Auto-updates dispatcher topic keywords from conversation content. Maintains rolling topic history in `sensor.ai_recent_topics` (C7) — agents see recent conversation topics with agent attribution and relative time.

These are documented in `voice_context_architecture.md`. The blueprint-level patterns below remain valid for understanding the coordination concepts and for setups that don't use pyscript orchestration.

Each blueprint invocation targets a single `conversation_agent` entity. There are two patterns for multi-agent behavior at the blueprint level:

#### Pattern A: Dispatcher agent (PREFERRED for Extended OpenAI Conversation)

A single "dispatcher" agent receives all requests and uses Extended OpenAI's function/tool calling to route to specialized agents. The dispatcher's system prompt describes available specialists, and each specialist is exposed as a tool/function.

```
## ROUTING

You are the front desk. Route requests to the right specialist:

- **workshop_agent** — lights, music, and devices in the workshop
- **living_room_agent** — TV, Sonos, and living room climate
- **media_agent** — Music Assistant playback, queue management, radio

If a request spans multiple domains, call the relevant specialists in sequence.
If no specialist fits, handle it yourself using your general knowledge.
Never tell the user about the routing — just handle it seamlessly.
```

**Implementation skeleton — specialist wrapper scripts:**

Each specialist is a script exposed as a tool to the dispatcher agent. The script calls `conversation.process` with the specialist agent's ID, forwards the user's request, and returns the specialist's response to the dispatcher.

```yaml
script:
  dispatch_to_workshop:
    alias: "Dispatch – Ask Workshop Agent"
    description: >-
      Forward a request to the workshop specialist agent.
      Call this for anything involving workshop lights, speakers,
      or devices. Returns the specialist's text response.
    mode: single
    fields:
      user_request:
        description: "The user's request to forward to the workshop specialist."
        required: true
        selector:
          text:
    sequence:
      - alias: "Forward request to workshop specialist"
        action: conversation.process
        data:
          agent_id: "conversation.rick_extended"   # Workshop specialist agent entity
          text: "{{ user_request }}"
          # NOTE: no extra_system_prompt here — the specialist has its own static prompt.
          # Pass conversation_id if you need multi-turn context threading.
        response_variable: specialist_response
        continue_on_error: true
      - stop: "{{ specialist_response.response.speech.plain.speech | default('No response from workshop agent.') }}"
        response_variable: result
```

**Dispatcher agent tool setup:** Expose one `dispatch_to_*` script per specialist. The dispatcher's system prompt describes when to call each one (see the ROUTING section above). The `stop:` action with `response_variable` returns the specialist's reply to the dispatcher, which can then relay, rephrase, or chain another specialist call.

**Limitations:**
- Each specialist call is a separate `conversation.process` invocation — the specialist doesn't see the dispatcher's conversation history (only what you pass in `text`).
- If you need the specialist to retain multi-turn context, pass a shared `conversation_id`.
- Latency compounds — each specialist call adds an LLM round-trip. Keep the specialist count low (2–4 is typical).

**Why this works better than blueprint-level fallback:**
- The LLM makes the routing decision using semantic understanding, not string matching.
- Multi-domain requests get handled in a single conversation turn.
- The dispatcher maintains conversation context across specialist calls.

#### Pattern B: Blueprint-level fallback (cross-integration or simple setups)

When agents use different integrations (e.g., Extended OpenAI + Ollama) or when you want blueprint-level control, orchestrate in the action sequence:

```yaml
# In the blueprint action sequence — NOT in the agent prompt
- alias: "Try primary agent"
  action: conversation.process
  data:
    agent_id: !input primary_agent
    text: "{{ user_request }}"
  response_variable: primary_response

- alias: "Fallback to secondary if primary couldn't help"
  if:
    - condition: template
      value_template: >-
        {% set reply = primary_response.response.speech.plain.speech | default('') | lower %}
        {{ 'can\'t help' in reply or 'not in my' in reply
           or 'outside my' in reply or 'don\'t have access' in reply }}
  then:
    - action: conversation.process
      data:
        agent_id: !input fallback_agent
        text: "{{ user_request }}"
      continue_on_error: true
```

> **⚠️ Fragility warning:** This pattern matches against free-form LLM output. LLMs don't reliably produce exact phrases. The template above checks for multiple common refusal patterns to improve reliability, but it will never be 100% accurate. Use Pattern A when possible.

**Rules:**
- In Pattern A, the dispatcher knows specialists exist (it has to — they're its tools). Specialists should NOT know about each other or the dispatcher.
- In Pattern B, no agent knows other agents exist. Handoff logic lives entirely in the blueprint.
- Each agent's PERMISSIONS section must be independent — don't assume shared device access.
- **Observability:** Multi-LLM-call flows are hard to debug from traces alone. Add `logbook.log` entries after each `conversation.process` call to record which agent was called and whether it succeeded. This makes the routing path visible in the logbook without digging through automation traces.
- This is an area likely to evolve as HA's voice pipeline matures. Revisit when HA adds native multi-agent support.

### 8.6 Voice pipeline constraints on agent behavior

Conversation agents don't exist in a vacuum — when used with voice assistants, the **voice pipeline** imposes constraints that affect how agents should be configured. This section summarizes what agent authors need to know; full pipeline architecture is in §14 (Voice Assistant Pattern).

**Pipeline-to-agent binding:**
- Each HA voice pipeline has exactly one conversation agent assigned to it.
- Each Voice PE satellite is assigned to exactly one pipeline.
- This means: **one satellite = one agent** (at any given time). To switch agents on a satellite, you switch its pipeline assignment.
- `assist_satellite.start_conversation` uses the satellite's assigned pipeline — you cannot override the agent per-call. If your flow needs a different agent, either switch the pipeline first or use `conversation.process` with explicit `agent_id` and handle TTS output yourself.

**Implications for agent design:**
- **Don't create per-scenario agent instances** (e.g., a separate "Coming Home" agent). Instead, use the persona's standard agent and inject scenario context via `extra_system_prompt`. Only different tool sets justify separate variants (Bedtime, Music Compose, Music Transfer, Therapy) — see §8.4.
- **TTS is not the agent's job.** The agent returns text; the pipeline's TTS engine converts it to speech. Don't include TTS-specific instructions (speed, pitch) in the agent prompt — those belong in the TTS engine or ESPHome config.
- **The agent doesn't know which satellite it's on** unless you tell it via `extra_system_prompt`. If room-aware behavior matters ("dim the lights" should mean *this room's* lights), the blueprint must inject the satellite's location into the prompt.

**Cross-references:**
- Full pipeline architecture, satellite mapping, and TTS output patterns: §14 (Voice Assistant Pattern)
- ESPHome satellite configuration: §6 (ESPHome Patterns)
- Wake word and STT configuration: §6.5
- TTS duck/restore for music coexistence: §7.4, §7.9 (Music Assistant Patterns)

> 📋 **QA Check INT-1:** Conversation agent completeness — verify dispatcher pattern, MCP servers, confirm-then-execute, naming rationale, token budget, and multi-agent coordination are all documented. See `09_qa_audit_checklist.md`.
