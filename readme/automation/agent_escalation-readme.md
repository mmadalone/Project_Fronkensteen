# Agent Escalation -- Probability Gate

When an LLM agent threatens escalation, it fires the `escalate_action` tool which emits an `ai_escalation_request` event. This blueprint catches the event and rolls dice against a per-type configurable probability. On a hit, the threatened action executes. On a miss, the bluff is logged to L2 memory so agents can reference escalation history. Seven action types are supported, each with independent probability overrides and permission toggles.

## How It Works

```
ai_escalation_request event
        |
        v
+-------------------+     +------------------+
| Master toggle ON? |---->| Satellite match? |
+-------------------+     +------------------+
        |                         |
        v                         v
+-------------------+     +------------------+
| Action permitted? |---->| Cooldown clear?  |
+-------------------+     +------------------+
                                  |
                    +-------------+-------------+
                    |                           |
                    v                           v
          +-----------------+          +-----------------+
          | Roll dice       |          | Blocked by      |
          | (per-type prob) |          | cooldown        |
          +-----------------+          +-----------------+
                    |
          +---------+---------+
          |                   |
          v                   v
   +----------+        +------------+
   | MISS:    |        | HIT:       |
   | Log bluff|        | Execute    |
   | + whisper|        | action     |
   +----------+        +------------+
                              |
                    +---------+---------+
                    | Update timestamp  |
                    | Log to L2         |
                    | Whisper context   |
                    +-------------------+
```

## Features

- Seven escalation action types: persona switch, play media, light flash, volume boost, send notification, prompt barrage, run script
- Per-type probability overrides (-1 = use global fallback, 0 = always bluff, 100 = always follow through)
- Per-type permission toggles to enable/disable individual action types
- Configurable cooldown between follow-throughs (any type)
- Bluff and follow-through logging to L2 memory with configurable retention
- Agent whisper context injection after every escalation attempt
- Prompt barrage: summons another agent with persona-specific prompt pools, resolves their conversation engine, and plays their TTS response in their voice
- Persona switch reuses `voice_handoff.yaml` via the handoff pending flag
- Volume boost uses TTS priority 0 (emergency) at configurable volume
- Map-based permission and probability lookups (no if/elif chains)

## Prerequisites

- Home Assistant
- `input_boolean.ai_escalation_enabled` (master toggle)
- `input_text.ai_last_satellite` (satellite tracking)
- `input_text.ai_escalation_last_outcome` (status tracking)
- `input_datetime.ai_escalation_last_followthrough` (cooldown gate)
- `input_text.ai_handoff_pending` (for persona_switch)
- `input_text.ai_last_agent_name` (current agent)
- `pyscript/memory.py` (L2 logging)
- `pyscript/agent_whisper.py` (whisper context)
- `pyscript/agent_dispatcher.py` (engine resolution for prompt barrage)
- `pyscript/tts_queue.py` (TTS playback)
- `voice_handoff.yaml` (persona switching)

## Installation

1. Copy `agent_escalation.yaml` to `config/blueprints/automation/madalone/`
2. Create automation: **Settings -> Automations -> Create -> Use Blueprint**

## Configuration

<details><summary>① Core</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `satellite` | _(none)_ | Voice PE satellite entity (assist_satellite domain) |
| `cooldown_minutes` | `30` | Minimum minutes between follow-throughs. 0 = no cooldown |
| `log_escalations` | `true` | Log bluffs and follow-throughs to L2 memory |

</details>

<details><summary>② Probability</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `escalation_probability` | `15` | Global fallback probability (0-100%) |
| `probability_persona_switch` | `-1` | Per-type override. -1 = use global |
| `probability_play_media` | `-1` | Per-type override. -1 = use global |
| `probability_light_flash` | `-1` | Per-type override. -1 = use global |
| `probability_volume_boost` | `-1` | Per-type override. -1 = use global |
| `probability_send_notification` | `-1` | Per-type override. -1 = use global |
| `probability_prompt_barrage` | `-1` | Per-type override. -1 = use global |
| `probability_run_script` | `-1` | Per-type override. -1 = use global |

</details>

<details><summary>③ Action Toggles</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `allow_persona_switch` | `true` | Hand conversation to another agent via voice_handoff |
| `allow_play_media` | `true` | Play audio clip from media folder |
| `allow_light_flash` | `true` | Flash room lights to get attention |
| `allow_volume_boost` | `true` | Repeat message louder via TTS at emergency priority |
| `allow_send_notification` | `true` | Push mobile notification |
| `allow_prompt_barrage` | `true` | Summon another agent to chime in via TTS |
| `allow_run_script` | `true` | Run a configured HA script |

</details>

<details><summary>④ Devices</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `tts_output_player` | _(empty)_ | Media player for audio clips and TTS output |
| `flash_light_entity` | `[]` | Light entity to flash for light_flash escalation |
| `notify_service_name` | _(empty)_ | Notify service name (e.g. `notify.mobile_app_iphone`) |
| `escalation_script` | _(empty)_ | Script entity for run_script escalation |

</details>

<details><summary>⑤ Tuning</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `media_folder` | `/config/media/agent_escalation/` | Path to escalation audio clips |
| `flash_count` | `5` | Number of on/off flash cycles |
| `flash_brightness` | `255` | Brightness for flash cycles (0-255) |
| `boost_volume_level` | `0.9` | Volume level (0.0-1.0) for volume_boost TTS |

</details>

## Technical Notes

- **Mode:** `single` -- only one escalation can process at a time
- **Event-driven:** Triggered by `ai_escalation_request` events, typically fired by the LLM `escalate_action` tool
- **Satellite scoping:** Each instance handles one satellite; the condition block matches `input_text.ai_last_satellite` against the configured satellite entity
- **Prompt pool:** Embedded in the variables block with per-agent prompt lists (quark, deadpool, rick, kramer, doctor portuondo). Edit the `prompt_pool` variable directly to customize
- **Voice map:** Maps persona names to TTS engine entity IDs for correct voice output
- **Error handling:** All action execution steps use `continue_on_error: true`; guard checks bail early with `stop:` on validation failures

## Author

**madalone**

## License

See repository for license details.
