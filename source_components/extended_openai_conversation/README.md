# Extended OpenAI Conversation — Patched Fork

Patched fork of [jekalmin's Extended OpenAI Conversation](https://github.com/jekalmin/extended_openai_conversation) with a 4-layer speech sanitizer that strips tool-call leaks from LLM responses before TTS.

**HACS auto-updates must be disabled for this component.** It is distributed automatically by the Project Fronkensteen installer (core dependency — always installed).

---

## What Was Changed

### Added: Tool-Call Speech Sanitizer (`conversation.py`)

LLMs (especially Llama 4 Maverick and Gemini 2.5 Flash) sometimes leak raw function-call syntax into `message.content` alongside actual tool calls. Without sanitization, TTS would speak things like `"execute_services(domain="light", service="turn_on", action_type="call")"` aloud.

The patch adds `_sanitize_for_speech()` — a 4-layer cascade that strips progressively:

| Layer | What It Catches | Example |
|-------|----------------|---------|
| **Layer 1** | Entire response is a bare function call | `end_conversation()` → returns None (silent) |
| **Layer 2** | Response contains known function names | `"Sure! execute_services(domain="light"...)"` → `"Sure!"` |
| **Layer 3** | Orphaned keyword arguments (Maverick pattern) | `action="promote", library_id="foo")` → stripped |
| **Layer 4** | Inline tool-param sequences mid-sentence | `"Done (key="value", key2="value2") enjoy"` → `"Done enjoy"` |

Layers cascade: Layer 2 stripping a function name exposes orphaned args for Layer 3, and remaining inline params are caught by Layer 4.

### Changes to `conversation.py`

| Section | What Changed |
|---------|-------------|
| Lines 76-97 | Added 3 compiled regex patterns: `_TOOL_CALL_SYNTAX`, `_ORPHAN_TOOL_ARGS`, `_INLINE_TOOL_PARAMS` |
| Line 239, 243 | Wrapped `query_response.message.content` in `self._sanitize_for_speech()` before returning to TTS |
| Lines 317-366 | New method `_sanitize_for_speech()` implementing the 4-layer cascade |

### Files Unchanged from Upstream

- `__init__.py` — integration setup
- `config_flow.py` — agent configuration flow with subentries
- `const.py` — constants
- `exceptions.py` — custom exceptions
- `helpers.py` — utility functions
- `services.py` — service definitions
- `services.yaml` — service schemas
- `strings.json` — UI translations
- `translations/` — all translation files

---

## Why This Patch Exists

When using Extended OpenAI Conversation with voice assistants (TTS output), function-call leaks are spoken aloud. The upstream component doesn't sanitize `message.content` before passing it to the conversation response — it assumes a text-based interface where raw function syntax is harmless.

In a voice-first system with 5 AI personas responding through TTS, every leaked `execute_services(domain="light")` becomes an audible interruption. This patch makes the voice experience clean.

### LLM-Specific Patterns

| LLM | Leak Pattern | Layer |
|-----|-------------|-------|
| **Gemini 2.5 Flash** | Returns text alongside function calls: `end_conversation()` | Layer 1 |
| **Llama 4 Maverick** | Leaks arguments without function prefix: `action="promote", library_id="foo")` | Layer 3 |
| **General** | Function name + args in natural text: `"Sure! memory_tool(key="foo")"` | Layer 2 |
| **Residual** | Partial params after earlier stripping: `(key="value")` mid-sentence | Layer 4 |

---

## Upstream Attribution

- **Original component**: [extended_openai_conversation](https://github.com/jekalmin/extended_openai_conversation) by jekalmin
- **License**: Apache 2.0
- **Forked at**: v2.0.2
- **Upstream features preserved**: All conversation agent functionality, config flow, subentries, function calling, context management
