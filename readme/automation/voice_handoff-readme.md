![Voice Handoff -- Agent Switching](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/voice_handoff-header.jpeg)

# Voice Handoff -- Agent Switching

Switches the active voice assistant pipeline on a satellite when a user requests a different AI persona (e.g., "pass me to Deadpool"). Supports two trigger paths: the LLM `handoff_agent` tool sets `ai_handoff_pending`, or the dispatcher fires an `ai_handoff_request` event for self-handoffs. Optionally plays a farewell from the outgoing agent and a greeting from the incoming agent, then reopens the mic for continued conversation.

## How It Works

```
┌──────────────────────────────┐
│ Trigger                      │
│  ├─ ai_handoff_pending ≠ ""  │
│  ├─ ai_handoff_request event │
│  └─ watchdog (30s stale)     │
└──────────┬───────────────────┘
           │
     ┌─────▼─────┐
     │ Conditions │
     │  ├─ Privacy gate          │
     │  ├─ Handoff enabled       │
     │  ├─ Satellite match       │
     │  └─ Re-entry guard        │
     └─────┬─────┘
           │
  ┌────────▼────────┐
  │ 0. Watchdog?    │──yes──▶ Clear flag + stop
  └────────┬────────┘
           │ no
  ┌────────▼────────┐
  │ 1. Set guard    │
  │    Parse target │
  │    Save pipeline│
  │    Bypass F-M   │
  └────────┬────────┘
           │
  ┌────────▼────────────┐
  │ 2. Resolve persona  │
  │    Alias lookup     │
  │    Match pipeline   │
  └────────┬────────────┘
           │
  ┌────────▼────────────────┐
  │ 3-5. Expertise gate     │
  │      Farewell TTS       │
  │      Switch pipeline    │
  └────────┬────────────────┘
           │
  ┌────────▼────────────────┐
  │ 6-8. Greeting via       │
  │      start_conversation │
  │      Echo guard delay   │
  └────────┬────────────────┘
           │
  ┌────────▼────────────────┐
  │ 9. Continuous convo?    │
  │    └─ Reopen mic loop   │
  └────────┬────────────────┘
           │
  ┌────────▼────────────────┐
  │ 10. Restore bypass      │
  │     Clear guard + flag  │
  └─────────────────────────┘
```

## Features

- Dual trigger: LLM tool flag or dispatcher event
- Persona alias resolution (e.g., "el doctor" maps to "doctor portuondo")
- Per-persona TTS voice resolved dynamically from Assist Pipeline config via dispatcher
- Four LLM text generation modes: static, ha_text_ai, pipeline_agent, conversation_agent
- Expertise-based proactive handoff (I-45) with separate prompts
- Continuous conversation loop with configurable timeout
- Echo guard delay prevents satellite from hearing its own greeting
- Follow-me and ducking bypass via refcount scripts (I-45b)
- Re-entry guard with stale timeout prevents feedback loops
- Watchdog trigger clears stuck handoff flags after 30 seconds
- Privacy gate with per-tier suppression
- Mic behavior control: LLM-decides or single-turn

## Prerequisites

- Home Assistant 2024.10.0 or later
- `input_boolean.ai_voice_handoff_enabled`
- `input_text.ai_handoff_pending`
- `input_boolean.ai_handoff_processing` (re-entry guard)
- `pyscript/agent_dispatcher.py`
- `pyscript/tts_queue.py`

## Installation

1. Copy `voice_handoff.yaml` to `config/blueprints/automation/madalone/`
2. Create automation: **Settings -> Automations -> Create -> Use Blueprint**

## Configuration

<details><summary><strong>① Core</strong></summary>

| Input | Default | Description |
|---|---|---|
| `satellite` | _(empty)_ | Voice PE satellite entity |
| `pipeline_select` | _(empty)_ | Select entity controlling this satellite's pipeline |
| `enable_commentary` | `false` | Outgoing agent speaks a farewell via TTS before handoff |
| `enable_greeting` | `true` | Incoming agent speaks a greeting after the switch |

</details>

<details><summary><strong>② Persona & Voice</strong></summary>

| Input | Default | Description |
|---|---|---|
| `tts_speaker` | _(empty)_ | Media player for TTS output |
| `persona_aliases` | `deadpool=deepee,...` | Map canonical names to spoken nicknames |
| `bypass_ducking` | `false` | Skip volume ducking on other speakers during TTS |

</details>

<details><summary><strong>③ Farewell & Greeting</strong></summary>

| Input | Default | Description |
|---|---|---|
| `commentary_prompt` | _(handoff prompt)_ | LLM prompt for outgoing agent farewell. `{target}` placeholder. |
| `greeting_prompt` | _(greeting prompt)_ | LLM prompt for incoming agent. `{source}` placeholder. |
| `llm_lines_mode` | `static` | How to generate text: static / ha_text_ai / pipeline_agent / conversation_agent |
| `llm_lines_agent` | _(empty)_ | Conversation agent entity (conversation_agent mode only) |
| `llm_lines_instance` | _(empty)_ | HA Text AI sensor (ha_text_ai mode only) |
| `farewell_text` | `Switching you over to {target} now.` | Static farewell text or LLM prompt |
| `greeting_text` | `Hey there, I'm here.` | Static greeting text or LLM prompt |

</details>

<details><summary><strong>④ Mic & Conversation</strong></summary>

| Input | Default | Description |
|---|---|---|
| `echo_guard_delay` | `2` | Seconds to wait after greeting before opening mic |
| `mic_behavior` | `llm_decides` | Mic behavior: llm_decides or single_turn |
| `extra_system_prompt` | _(empty)_ | Custom instructions injected into conversation agent context |
| `enable_continuous_conversation` | `false` | Keep mic open after each response without wake word |
| `continuous_conversation_timeout` | `120` | Max duration for continuous conversation (seconds) |
| `silence_media_url` | `http://homeassistant.local:8123/local/silence.wav` | Audio file for silent mic open |

</details>

<details><summary><strong>⑤ Bypass</strong></summary>

| Input | Default | Description |
|---|---|---|
| `bypass_follow_me` | `true` | Pause notification follow-me during handoff |
| `bypass_claim_script` | `script.refcount_bypass_claim` | Refcount claim script |
| `bypass_release_script` | `script.refcount_bypass_release` | Refcount release script |

</details>

<details><summary><strong>⑥ Expertise Routing</strong></summary>

| Input | Default | Description |
|---|---|---|
| `enable_expertise_handoff` | `true` | Accept proactive expertise-based handoffs on this satellite |
| `expertise_commentary_prompt` | _(expertise prompt)_ | Outgoing agent farewell prompt for expertise routing |
| `expertise_greeting_prompt` | _(expertise prompt)_ | Incoming agent greeting prompt for expertise routing |

</details>

<details><summary><strong>⑦ Infrastructure</strong></summary>

| Input | Default | Description |
|---|---|---|
| `voice_handoff_enabled` | `input_boolean.ai_voice_handoff_enabled` | Master kill switch |
| `processing_guard` | _(empty)_ | Re-entry prevention boolean |
| `stale_guard_timeout` | `30` | Seconds before stuck guard is bypassed |
| `restore_mode` | `source` | Pipeline restore after handoff: source / preferred / never |
| `restore_timeout` | `300` | Seconds before restoring pipeline (0 = disabled) |
| `privacy_tier` | `t2` | Privacy gate tier (off / t1 / t2 / t3) |
| `privacy_gate_enabled` | `input_boolean.ai_privacy_gate_enabled` | Privacy gate toggle |
| `privacy_gate_mode` | `input_select.ai_privacy_gate_mode` | Privacy gate behavior |
| `privacy_gate_person` | `person.miquel` | Person entity for tier suppression lookups |

</details>

<details><summary><strong>⑧ Music</strong></summary>

| Input | Default | Description |
|---|---|---|
| `enable_agent_jingle` | `false` | Play target agent's theme jingle before greeting |
| `jingle_cooldown_s` | `60` | Minimum seconds between jingles on same speaker |
| `enable_handoff_stinger` | `false` | Play transition stinger between farewell and greeting |
| `enable_thinking_music` | `false` | Play thinking loop during LLM response wait |
| `jingle_library_id_override` | `""` | Explicit library ID for jingle (bypasses auto-resolve) |
| `stinger_library_id_override` | `""` | Explicit library ID for stinger (bypasses auto-resolve) |
| `music_delay_after` | `2` | Seconds to wait after music before continuing |
| `music_fallback_media_url` | `""` | Fallback audio URL if library is empty |

</details>

## Technical Notes

- **Mode:** `restart` -- new handoff requests kill any in-progress handoff cleanly
- **Re-entry prevention:** Processing guard boolean blocks feedback loops when farewell TTS accidentally triggers another handoff. Stale timeout auto-recovers.
- **Watchdog:** Third trigger fires if `ai_handoff_pending` stays non-empty for 30 seconds, clearing the stuck flag.
- **LLM lines modes:** `static` is zero-risk (no LLM calls). `pipeline_agent` resolves the pipeline's conversation agent via `dispatcher_resolve_engine`. `conversation_agent` lets you pick manually. Both LLM modes carry re-entry risk on Standard agents.
- **Template safety:** All Jinja templates use `| default()` guards for unavailable/unknown states.

## Author

**madalone**

## License

See repository for license details.
