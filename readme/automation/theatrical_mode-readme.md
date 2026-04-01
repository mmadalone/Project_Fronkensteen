![Theatrical Mode](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/theatrical_mode-header.jpeg)

# Theatrical Mode — Multi-Agent Debate (v1.0)

Pattern 4 of inter-agent communication. Orchestrates multi-turn debate exchanges between 2–5 AI personas, each speaking in character via their own TTS voice on optionally different physical speakers for a spatial staging effect. Triggered by voice command ("debate this"), banter escalation, or direct event. Builds on Pattern 1 (Reactive Banter) and extends it into coordinated multi-turn exchanges.

## How It Works

```
Entry Points                          Orchestration
┌─────────────────────┐
│ 1. Voice command     │──┐
│    ("debate this")   │  │  ai_theatrical_request
│                      │  │         event
│ 2. Banter escalation │──┼──────────────────────┐
│    (Pattern 1 → P4)  │  │                      │
│                      │  │                      ▼
│ 3. Automation/event  │──┘        ┌──────────────────────┐
└─────────────────────┘           │ Blueprint             │
                                  │  Gate checks          │
                                  │  Refcount bypass      │
                                  │  Optional stinger     │
                                  │  ▼                    │
                                  │  pyscript             │
                                  │  .theatrical_mode_    │
                                  │   start               │
                                  └──────────┬───────────┘
                                             ▼
                                  ┌──────────────────────┐
                                  │ Pyscript Engine       │
                                  │  1. Resolve personas  │
                                  │     (pipeline cache)  │
                                  │  2. Assign speakers   │
                                  │  3. Turn loop:        │
                                  │     ├─ Build I-45a    │
                                  │     │  prompt          │
                                  │     ├─ conversation    │
                                  │     │  .process        │
                                  │     ├─ Sanitize        │
                                  │     ├─ tts_queue_speak │
                                  │     ├─ Wait playback   │
                                  │     └─ Interrupt check │
                                  │  4. Teardown + log    │
                                  └──────────────────────┘
```

## Features

- **Multi-persona debate** — 2–5 agents take turns arguing a topic in character
- **Spatial staging** — assign different physical speakers to different agents (parallel ordered list selector, same pattern as Music Assistant Follow-Me)
- **Three interrupt modes** — `turn_limit` (default, runs to completion), `mic_gap` (asks user between turns via `ask_question`), `wake_word` (detects wake word in inter-turn gap)
- **Three context modes** — `full` (sliding window of previous turns), `topic_only` (independent takes), `whisper` (L2 memory network)
- **I-45a tool suppression** — all debate turns prefixed with tool-suppression instructions
- **Own pipeline cache** — batch resolves all participants from `assist_pipeline.pipelines` (zero service calls), with dispatcher fallback
- **Budget gating** — pre-exchange and mid-exchange budget checks (default floor: 70%)
- **Cooldown** — configurable minimum time between exchanges (default: 60 min)
- **Banter escalation** — reactive banter can probabilistically escalate into a full theatrical exchange (Section ⑧ in `reactive_banter.yaml`)
- **Volume save/restore** — optional exchange-level volume override with automatic restore
- **40 blueprint knobs** across 11 collapsible sections (①–⑪)
- **Native fallback** — simplified single-agent loop when pyscript/dispatcher is unavailable

## Prerequisites

- Home Assistant **2025.7.0+** (for `ask_question` support)
- **Pyscript** integration with the following modules:
  - `common_utilities.py` — `conversation_with_timeout` service
  - `tts_queue.py` — `tts_queue_speak` service
  - `agent_dispatcher.py` — `dispatcher_resolve_engine` (fallback resolution)
- At least **2 conversation agent pipelines** configured in Voice Assistants
- **ElevenLabs** or other multi-voice TTS integration (for distinct persona voices)
- Helper entities (created automatically from helper YAML files):
  - `input_boolean.ai_theatrical_mode_enabled` / `ai_theatrical_mode_active`
  - `input_number.ai_theatrical_turn_limit` / `ai_theatrical_max_words` / `ai_theatrical_budget_floor`
  - `input_select.ai_theatrical_interrupt_mode` / `ai_theatrical_context_mode` / `ai_theatrical_turn_order`
  - `input_datetime.ai_theatrical_last_exchange`
- `packages/ai_theatrical.yaml` — template sensor for dashboard config aggregation

## Installation

1. Copy `theatrical_mode.yaml` to `config/blueprints/automation/madalone/`
2. Copy `theatrical_mode.py` to `config/pyscript/`
3. Copy `ai_theatrical.yaml` to `config/packages/`
4. Add helper entries to `helpers_input_boolean.yaml`, `helpers_input_number.yaml`, `helpers_input_select.yaml`, `helpers_input_datetime.yaml`
5. Restart Home Assistant (for helpers + package)
6. Add `start_debate` tool to Extended OpenAI Conversation function specs
7. Add theatrical awareness paragraph to each agent's Standard prompt
8. Reload Extended OpenAI Conversation in HA UI
9. Settings > Automations > Create > Use Blueprint > **Theatrical Mode**

## Configuration

<details>
<summary><strong>① Control</strong> — Enable toggle, satellite, dispatcher switches</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `enable_toggle` | *(required)* | Per-instance kill switch (`input_boolean`) |
| `satellite` | *(required)* | Voice satellite for interrupt modes |
| `satellite_speaker` | *(required)* | Satellite's media_player for idle detection |
| `conversation_agent` | `""` | Fallback agent when dispatcher is off |
| `use_dispatcher` | `true` | Route through pyscript orchestration |
| `use_tts_queue` | `true` | Use TTS queue for delivery |
| `use_whisper` | `true` | Log exchanges to L2 memory |

</details>

<details>
<summary><strong>② Gating</strong> — Budget floor, cooldown</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `budget_floor` | `70` | Skip if budget remaining below this % |
| `cooldown_minutes` | `60` | Minimum minutes between exchanges |
| `cooldown_helper` | `input_datetime.ai_theatrical_last_exchange` | Tracks last exchange time |

</details>

<details>
<summary><strong>③ Participants</strong> — Agent roster</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `agent_pool_list` | `"Rick, Quark, Deadpool, Kramer, Doctor Portuondo"` | Comma-separated eligible personas |
| `min_participants` | `2` | Minimum agents for exchange to start |
| `max_participants` | `5` | Maximum agents (random subset if pool is larger) |

</details>

<details>
<summary><strong>④ Turn Management</strong> — Limits, ordering, pacing</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `turn_limit` | `6` | Max total turns (6 turns / 3 agents = 2 rounds each) |
| `turn_order` | `round_robin` | `round_robin` or `random` |
| `max_words` | `40` | Per-turn word limit (prompt + post-truncation) |
| `inter_turn_pause` | `0.8` | Seconds between speakers after TTS |

</details>

<details>
<summary><strong>⑤ Interrupt Mode</strong> — How users stop/redirect</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `interrupt_mode` | `turn_limit` | `turn_limit`, `mic_gap`, or `wake_word` |
| `mic_gap_question` | `"Anything to add?"` | Spoken between turns in mic_gap mode |
| `mic_gap_stop_phrases` | `"stop, enough, shut up, ..."` | Phrases that end the exchange |
| `mic_gap_redirect_phrases` | `"actually, wait, hold on, ..."` | Phrases that return control to user |

</details>

<details>
<summary><strong>⑥ Context Mode</strong> — Cross-agent awareness</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `context_mode` | `full` | `full` (sliding window), `topic_only`, or `whisper` (L2) |
| `context_window` | `6` | Turns in sliding buffer for `full` mode |

</details>

<details>
<summary><strong>⑦ Delivery</strong> — Speaker mapping, voices, volume</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `speaker_list` | `[]` | Media players in same order as agent pool (positional mapping) |
| `tts_priority` | `2` | TTS queue priority (0–4) |
| `native_fallback_voice` | `tts.google_en_com` | TTS engine for participants without pipeline TTS configured |
| `tts_output_volume` | `0.0` | Volume override during exchange (0 = use current) |
| `tts_volume_restore_delay` | `5` | Seconds before restoring volume |
| `tts_playback_buffer` | `1` | Extra seconds after speaker idle before next turn |
| `bypass_ducking` | `false` | Skip volume ducking on other speakers during TTS |

</details>

<details>
<summary><strong>⑧ Stinger</strong> — Pre-exchange chime</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `enable_pre_exchange_stinger` | `false` | Play chime before first agent speaks |
| `stinger_fallback_media_url` | `""` | URL or `/local/` path to chime file |

</details>

<details>
<summary><strong>⑨ Prompt</strong> — Debate template, I-45a prefix</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `theatrical_prompt_template` | *(built-in)* | Full mode template with `{topic}`, `{context_text}`, `{persona}`, `{opponents}`, `{turn}`, `{total_turns}` |
| `topic_only_template` | *(built-in)* | Topic-only mode template (agents know topic but not others' responses) |
| `whisper_template` | *(built-in)* | Whisper mode template (L2 context) |
| `i45a_prefix` | *(built-in)* | Tool-suppression prefix for all LLM calls |
| `lang_hint` | *(built-in)* | Language hint suffix for multilingual personas |
| `native_fallback_prompt` | *(built-in)* | Prompt for native fallback path (single-agent loop) |

</details>

<details>
<summary><strong>⑩ Banter Escalation</strong> — Accept Pattern 1 escalations</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `enable_banter_escalation` | `true` | Respond to `banter_escalation` source events |

</details>

<details>
<summary><strong>⑪ Infrastructure</strong> — Bypass scripts</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `bypass_claim_script` | `script.refcount_bypass_claim` | Follow-me bypass during exchange |
| `bypass_release_script` | `script.refcount_bypass_release` | Release bypass after exchange |
| `theatrical_mode_active_entity` | `input_boolean.ai_theatrical_mode_active` | Boolean tracking active exchange state |

</details>

## Technical Notes

- **Mode:** `single` / `max_exceeded: silent` — only one exchange at a time
- **Pipeline cache:** Own `_ensure_cache()` with configurable TTL (reuses `ai_dispatcher_cache_ttl` helper). Falls back to `dispatcher_resolve_engine` per-participant on cache miss.
- **Sanitization:** Lazy-initialized regex patterns via `@pyscript_executor` strip tool narration, entity IDs, and JSON fragments from LLM output before TTS.
- **Two-phase speaker wait:** Waits for speaker to start playing (phase 1, 15s max), then finish playing (phase 2, 90s max), then playback buffer — prevents "passes immediately" race condition.
- **Satellite dual idle check:** Gate-level check before exchange starts + per-TTS re-check before each speak (§14.10 pattern).
- **Generator expressions:** All avoided per AP-57 — list comprehensions used throughout.
- **`ask_question` safety:** Each mic_gap call separated by a full LLM+TTS cycle, avoiding known sequential call issues (#147695).
- **Status sensor:** `sensor.ai_theatrical_status` is pyscript-owned via `state.set()` (not a template sensor — Decision #78).

## Changelog

- **v1.0:** Initial implementation. 6-phase build with plan audit corrections (C1–C3, H1–H5, M1–M5). 40 blueprint knobs, 3 interrupt modes, 3 context modes, spatial staging, banter escalation, own pipeline cache.

## Author

Miquel Madaleno ([@mmadalone](https://github.com/mmadalone))

## License

See [LICENSE](../../LICENSE) in the repository root.
