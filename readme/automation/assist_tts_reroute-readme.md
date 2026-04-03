![Assist TTS Reroute](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/assist-tts-reroute-header.jpeg)

# Assist TTS Reroute

Intercepts Assist pipeline conversations from a voice device with a weak or inaudible speaker (e.g., Unfolded Circle Remote 3), re-processes the user's question with the agent dispatcher's selected persona, and plays the response on a nearby room speaker via the centralized TTS queue.

## How It Works

```
UC3 voice button pressed
        |
        v
HA Assist Pipeline: STT --> Rick LLM --> free TTS (inaudible on UC3)
        |
        v
eoc_finished event fires on HA event bus
        |
        v
Blueprint triggers:
  S1  Extract user_input.text (original question) + satellite_id
  S2  Guard: kill switch ON, satellite_id absent, 5s cooldown
  S3  Guard: text does NOT start with '[' (programmatic call filter)
  S4  Call agent_dispatch --> current agent (e.g., Deadpool) + TTS voice
  S5  Guard: dispatcher returned valid agent
  S6  Call conversation.process with dispatcher agent + original question
  S7  Guard: response text exists
  S8  Call tts_queue_speak --> room speaker plays dispatcher response
```

## Features

- **Dispatcher integration** -- uses `pyscript.agent_dispatch` for time-of-day agent/voice selection
- **Re-processing** -- the dispatcher's agent generates its own response (correct personality + voice)
- **Presence-aware** -- speaker selection via FP2 zones and `tts_speaker_config.json`
- **Ducking & priority** -- routes through `tts_queue_speak` for full queue coordination
- **Recursive loop protection** -- `mode: single` + 5-second cooldown guard prevents `conversation.process` -> `eoc_finished` feedback loops
- **Satellite exclusion** -- `satellite_id` filter excludes ESPHome satellites (they have their own speakers)
- **Programmatic call filter** -- skips `eoc_finished` events where the user text starts with `[` (all blueprints that call `conversation.process` use `[MARKER]` prefixes like `[NOTIFICATION]`, `[REMINDER ...]`, `[ALARM ...]`; real voice commands never do)
- **Kill switch** -- `input_boolean.assist_tts_reroute_enabled` controls when rerouting is active

## Why Not `assist_pipeline/run/end`?

The original approach was to capture the TTS audio URL from `assist_pipeline/run/end` events. Testing revealed this event does **not** fire on the HA event bus for WebSocket-initiated pipelines (UC3, dashboard). It only fires for native Assist satellite platform devices (ESPHome). The `extended_openai_conversation.conversation.finished` event is the only reliable hook.

## Cost Per Interaction

| Component | Cost |
|-----------|------|
| Device pipeline LLM (Rick on UC3) | ~0.005 EUR (Llama on OpenRouter) |
| Device pipeline TTS (HA Cloud on UC3) | Free |
| Reroute LLM (dispatcher agent) | ~0.005 EUR |
| Reroute TTS (ElevenLabs on room speaker) | 1 ElevenLabs call |

The device pipeline should use free TTS (HA Cloud/Piper) since its speaker is inaudible. Add the device pipeline to `input_text.ai_dispatcher_excluded_pipelines` to prevent the dispatcher from routing satellites to it.

## Prerequisites

- Home Assistant 2024.10.0+
- `pyscript.tts_queue_speak` service (TTS queue)
- `pyscript.agent_dispatch` service (agent dispatcher)
- FP2 presence sensors (for presence mode)
- Extended OpenAI Conversation integration (triggers on `eoc_finished`)
- A dedicated Assist pipeline for the device with free TTS (recommended)

## Installation

1. Copy `assist_tts_reroute.yaml` to `config/blueprints/automation/madalone/`
2. Create a dedicated pipeline for the device (e.g., "Rick - UC3") with HA Cloud TTS
3. Add the pipeline name to `input_text.ai_dispatcher_excluded_pipelines` (comma-separated)
4. Configure the device to use the dedicated pipeline
5. Create automation: **Settings -> Automations -> Create -> Use Blueprint**

## Configuration

<details>
<summary><strong>① Speaker routing</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| `target_mode` | `presence` | Speaker selection: presence (auto room), explicit, or broadcast |
| `explicit_speaker` | *(empty)* | Media player for explicit mode |
| `priority` | `2` | TTS queue priority (0=emergency, 4=ambient) |
| `announce` | `true` | Use announce mode on supported speakers |
| `duck` | `true` | Duck background audio during playback |

</details>

<details>
<summary><strong>② Safety</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| `kill_switch` | `input_boolean.assist_tts_reroute_enabled` | Master toggle for rerouting |

</details>

## Technical Notes

- **Mode:** `single` / `max_exceeded: silent` -- prevents recursive loop from `conversation.process` firing `eoc_finished`
- **Cooldown:** 5-second `last_triggered` guard as secondary protection
- **Trigger:** `extended_openai_conversation.conversation.finished` -- fires for ALL EOC conversations, not just the target device
- **Programmatic call guard (v1.2.1):** All blueprints that call `conversation.process` prefix their prompt text with a `[MARKER]` tag (e.g., `[NOTIFICATION]`, `[REMINDER ...]`, `[ALARM ...]`, `[BEDTIME ...]`, `[ESCALATION ...]`). The reroute skips any event where `user_input.text` starts with `[`. Real voice commands from STT never start with `[`. This convention is enforced across all Fronkensteen blueprints.

## Changelog

- **v1.2.1:** Fix double-trigger bug -- programmatic `conversation.process` calls from other automations (Notification Follow-me, Email Follow-me, Charge Reminder, etc.) fire `eoc_finished` without a `satellite_id`, causing the reroute to re-process them (double LLM + double TTS + double speaker). Added `§3b` guard: skip events where user text starts with `[` (all blueprints use `[MARKER]` prefixes; real voice commands never do).
- **v1.2.0:** Re-process with dispatcher agent -- captures user question, calls dispatcher for agent + voice, re-asks with correct persona. Recursive loop protection via `mode: single` + cooldown.
- **v1.1.0:** Direct text capture with dispatcher voice (character/voice mismatch)
- **v1.0.0:** Initial implementation (`assist_pipeline/run/end` trigger -- did not fire for UC3)

## Author

**madalone**

## License

See repository for license details.
