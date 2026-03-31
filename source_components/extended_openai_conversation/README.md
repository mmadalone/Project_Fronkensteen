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

### Added: Fallback Model on Transient API Errors (`conversation.py`, `const.py`, `config_flow.py`, `strings.json`)

When the primary model returns a transient error (429 rate limit, 5xx upstream failure, 404 model not found), the component now retries once with a configurable fallback model. Particularly useful with OpenRouter where upstream providers can be temporarily rate-limited.

| Aspect | Detail |
|--------|--------|
| **Config** | New "Fallback Model" text field per agent subentry (empty = disabled) |
| **Eligible errors** | `RateLimitError` (429), `InternalServerError` (500/502/503), `NotFoundError` (404) |
| **Non-eligible** | `AuthenticationError`, `BadRequestError` — these indicate config problems, not transient issues |
| **Behavior** | Per-turn only. Each new conversation turn starts with the primary model. Fallback is a single retry — if it also fails, returns the original error |
| **Recursive calls** | `model_override` parameter threaded through `query()` → `execute_function_call()` → `execute_function()` → `execute_tool_calls()`. Once fallen back, stays on fallback for the entire tool-call chain |
| **Message cleanup** | On failure, messages list is trimmed back to pre-query snapshot before retrying (removes any partial tool-call messages from the failed attempt) |
| **Token params** | Extracted `_token_kwargs_for_model()` helper re-evaluates `max_tokens` vs `max_completion_tokens` for the fallback model |
| **Device info** | `DeviceInfo.model` shows `primary → fallback` in the integration overview when a fallback is configured (e.g., `meta-llama/llama-4-maverick → openai/gpt-4o-mini`) |

### Changes to `conversation.py`

| Section | What Changed |
|---------|-------------|
| Lines 10-15 | Import `RateLimitError`, `InternalServerError`, `NotFoundError` from `openai._exceptions` |
| Lines 107-118 | Added `_FALLBACK_ELIGIBLE_ERRORS` tuple and `_token_kwargs_for_model()` helper |
| Lines 76-97 | Added 3 compiled regex patterns: `_TOOL_CALL_SYNTAX`, `_ORPHAN_TOOL_ARGS`, `_INLINE_TOOL_PARAMS` |
| Lines 219-270 | Fallback retry wrapper in `_async_handle_message()` — catches eligible errors, trims messages, retries with fallback model |
| Lines 477-486 | `query()` — added `model_override` parameter, uses extracted `_token_kwargs_for_model()` |
| Lines 534-549 | `query()` tool-call dispatch — passes `model_override` to `execute_function_call()` and `execute_tool_calls()` |
| Lines 555-578 | `execute_function_call()` — added `model_override` param, passes through to `execute_function()` |
| Lines 581-625 | `execute_function()` — added `model_override` param, passes through to recursive `query()` |
| Lines 627-661 | `execute_tool_calls()` — added `model_override` param, passes through to recursive `query()` |
| Lines 161-171 | `__init__()` — `DeviceInfo.model` shows `primary → fallback` when fallback is configured |
| Line 304, 308 | Wrapped `query_response.message.content` in `self._sanitize_for_speech()` before returning to TTS |
| Lines 382-439 | `_sanitize_for_speech()` — 4-layer tool-call cascade + Layer 5 ElevenLabs stage direction strip |

### Changes to Other Files

| File | What Changed |
|------|-------------|
| `const.py` | Added `CONF_FALLBACK_MODEL = "fallback_model"` and `DEFAULT_FALLBACK_MODEL = ""` |
| `config_flow.py` | Imported new constants, added to `DEFAULT_OPTIONS`, added `vol.Optional` field in options schema |
| `strings.json` | Added `"fallback_model"` UI label |

### Files Unchanged from Upstream

- `__init__.py` — integration setup
- `exceptions.py` — custom exceptions
- `helpers.py` — utility functions
- `services.py` — service definitions
- `services.yaml` — service schemas
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
