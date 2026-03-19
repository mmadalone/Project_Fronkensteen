# Agent Randomizer

![Image](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/agent_randomizer-header.jpeg)

Script blueprint that returns a random Voice Assistant (Assist Pipeline) from a configurable pool of up to 10 slots. Each slot carries a pipeline ID and optional display name with aliases. Supports a dispatcher mode that bypasses randomization entirely and delegates persona selection to the AI dispatcher. Empty slots are filtered out automatically -- fill any combination you need.

## How It Works

```
START
  |
  v
[Capture 10 pipeline slots + 10 name slots]
  |
  v
<Dispatcher enabled?>
  |           |
 YES          NO
  |           |
  v           v
[agent_dispatch      [Build pool from
 selects persona]     non-empty slots]
  |                   |
  v                   v
[Resolve agent,      [Pick random pair]
 TTS, voice,          |
 persona]             v
  |                  [Resolve pipeline
  v                   via agent_dispatch]
[Whisper --           |
 self-awareness]      v
  |                  [Whisper --
  v                   self-awareness]
[STOP: return         |
 result dict]         v
                     [STOP: return
                      result dict]
```

## Features

- Up to 10 Voice Assistant pipeline slots with display names and aliases
- Dispatcher mode bypasses randomization for AI-driven persona selection
- Empty slots automatically excluded from the pool
- Comma-separated alias support per slot (first = canonical name, rest = detection-only)
- Returns structured result: `agent`, `tts_engine`, `tts_voice`, `persona`, `pipeline_name`, `name`, `roster`
- Self-awareness whisper after selection
- Must be called with `response_variable` (not `script.turn_on`)

## Prerequisites

- Home Assistant **2024.10.0** or newer
- `pyscript.agent_dispatch` service (agent dispatcher pyscript module)
- `pyscript.agent_whisper` service (agent whisper pyscript module)
- AI dispatcher enabled helper (`input_boolean.ai_dispatcher_enabled`)

## Installation

1. Copy `agent_randomizer.yaml` to `config/blueprints/script/madalone/`
2. Create script: **Settings > Automations & Scenes > Scripts > Add > Use Blueprint**

## Configuration

<details>
<summary><strong>Section 0 -- Dispatcher</strong></summary>

| Input | Default | Description |
|---|---|---|
| `use_dispatcher` | `true` | When enabled, the AI dispatcher selects the persona dynamically, bypassing the pool |

</details>

<details>
<summary><strong>Section 1 -- Voice Assistant Pairs 1-5</strong></summary>

| Input | Default | Description |
|---|---|---|
| `agent_1` | `Rick` | Voice Assistant pipeline name (leave empty to exclude) |
| `name_1` | _(empty)_ | Comma-separated display name + aliases |
| `agent_2` | `Quark` | Voice Assistant pipeline name |
| `name_2` | _(empty)_ | Comma-separated display name + aliases |
| `agent_3` | `Deadpool` | Voice Assistant pipeline name |
| `name_3` | _(empty)_ | Comma-separated display name + aliases |
| `agent_4` | `Kramer` | Voice Assistant pipeline name |
| `name_4` | _(empty)_ | Comma-separated display name + aliases |
| `agent_5` | _(empty)_ | Voice Assistant pipeline name |
| `name_5` | _(empty)_ | Comma-separated display name + aliases |

</details>

<details>
<summary><strong>Section 2 -- Voice Assistant Pairs 6-10</strong></summary>

| Input | Default | Description |
|---|---|---|
| `agent_6` | `Rick - Bedtime` | Voice Assistant pipeline name |
| `name_6` | _(empty)_ | Comma-separated display name + aliases |
| `agent_7` - `agent_10` | _(empty)_ | Additional pipeline slots |
| `name_7` - `name_10` | _(empty)_ | Matching display name + aliases |

</details>

<details>
<summary><strong>Section 3 -- Infrastructure</strong></summary>

| Input | Default | Description |
|---|---|---|
| `dispatcher_enabled` | `input_boolean.ai_dispatcher_enabled` | Boolean that enables the AI agent dispatcher |

</details>

## Technical Notes

- **Mode:** No explicit mode set (default `single`)
- **Calling convention:** Must use `action: script.<instance_id>` with `response_variable`. Using `script.turn_on` is fire-and-forget and will NOT return the response.
- **Error handling:** `continue_on_error: true` on dispatcher and whisper calls
- **Empty pool:** If all 10 slots are empty, returns a result with empty `pipeline_name` and `name`

## Changelog

- **v2.0 (2026-03-03):** Pipeline migration -- replaced conversation_agent selectors with assist_pipeline; removed TTS entity inputs (TTS now resolved from pipeline); added dispatcher toggle; pipeline resolution via pyscript.agent_dispatch; whisper after selection
- **v1.2 (2026-02-27):** Alias support -- name inputs accept comma-separated aliases
- **v1.1 (2026-02-27):** Added display name per pair + roster return
- **v1.0 (2026-02-27):** Initial version -- 10 conversation agent/TTS pair slots

## Author

**madalone**

## License

See repository for license details.
