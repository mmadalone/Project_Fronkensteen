# Notification Replay

![Notification Replay header](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/notification_replay-header.jpeg)

On-demand replay of the last phone notification through the same pipeline as Notification Follow-Me -- minus the trigger, cooldown, and filtering gates. Resolves your current room via FP2 presence sensors, routes to the nearest voice satellite, and has a conversation agent summarize the message with full sender alias support. Call it from a dashboard button, a voice intent, or any automation.

## How It Works

```
Start
  |
  v
+------------------------+
| Agent selection        |
| (dispatcher > manual)  |
+------------------------+
  |
  v
+------------------------+     +-------------------+
| Read notification      |---->| Gate: sensor has  |
| sensor attributes      |     | usable data?      |
+------------------------+     +-------------------+
                                  | yes
                                  v
                         +-------------------+
                         | Resolve sender    |
                         | alias             |
                         +-------------------+
                                  |
                                  v
                         +-------------------+
                         | Detect media msgs |
                         | + truncate text   |
                         +-------------------+
                                  |
                                  v
                         +-------------------+
                         | Build sensor      |
                         | context for LLM   |
                         +-------------------+
                                  |
                                  v
+------------------------+     +-------------------+
| Resolve presence       |---->| Gate: satellite   |
| to target satellite    |     | available?        |
+------------------------+     +-------------------+
                                  | yes
                                  v
                         +-------------------+
                         | Claim follow-me   |
                         | bypass (refcount) |
                         +-------------------+
                                  |
                                  v
                 +----------------+----------------+
                 |                                 |
          media + short_tts               LLM summary path
                 |                                 |
                 v                                 v
        +----------------+              +-------------------+
        | Hardcoded      |              | conversation      |
        | announcement   |              | .process + whisper|
        +----------------+              +-------------------+
                 |                                 |
                 +----------------+----------------+
                                  |
                                  v
                         +-------------------+
                         | TTS queue speak   |
                         +-------------------+
                                  |
                                  v
                         +-------------------+
                         | Wait for playback |
                         | + release bypass  |
                         +-------------------+
                                  |
                                  v
                         +-------------------+
                         | Log successful    |
                         | replay            |
                         +-------------------+
```

## Features

- Full Notification Follow-Me delivery pipeline without trigger, cooldown, or filtering gates
- AI dispatcher integration with manual pipeline fallback
- Presence-based satellite routing with configurable fallback
- Sender alias map (Key=Value CSV) for friendly display names
- Media message detection with short TTS or LLM summary options
- User pet name context for the LLM (recognizes diminutives automatically)
- Extra context entities passed to the LLM as environmental awareness
- Group chat context toggle
- Message character cap with truncation
- TTS delivery via `pyscript.tts_queue_speak` with optional volume setting
- Follow-me refcount bypass prevents re-routing during replay
- Defensive fallback if LLM call fails

## Prerequisites

- Home Assistant 2024.10.0+
- Android Companion App with `last_notification` sensor
- `pyscript/agent_dispatcher.py` (agent dispatch)
- `pyscript/tts_queue.py` (TTS queue)
- `pyscript/agent_whisper.py` (whisper context)
- FP2 presence sensors and voice satellites (for presence routing)
- `input_boolean.ai_dispatcher_enabled` (dispatcher toggle)
- Refcount bypass scripts (for follow-me bypass)

## Installation

1. Copy `notification_replay.yaml` to `config/blueprints/script/madalone/`
2. Create script: **Settings -> Automations & Scenes -> Scripts -> Add -> Use Blueprint**

## Configuration

<details><summary>① Core setup</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `notification_sensor` | _(required)_ | Android Companion App `last_notification` sensor |
| `conversation_agent` | `Rick` | Assist Pipeline name (overridden when dispatcher is enabled) |
| `use_dispatcher` | `true` | Use AI dispatcher for dynamic persona selection |
| `notification_prompt` | _(summarize prompt)_ | LLM summarization instructions |
| `sender_aliases` | `""` | Comma-separated Key=Value alias pairs (e.g. `Mare=Mum`) |
| `include_group_context` | `false` | Include group/direct message status in LLM prompt |
| `context_entities` | `[]` | Extra sensors/entities whose states are passed to the LLM |
| `user_petnames` | `""` | Comma-separated pet names for the notification recipient |
| `char_cap` | `500` | Maximum characters of message text sent to the LLM |
| `media_message_behavior` | `short_tts` | Media message handling: `short_tts` or `llm_summary` |

</details>

<details><summary>② Presence routing</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `presence_sensors` | `[]` | Binary sensors indicating room occupancy (priority order) |
| `target_satellites` | `[]` | Media players paired with presence sensors (same order) |
| `fallback_satellite` | `""` | Satellite to use when no presence is detected |

</details>

<details><summary>③ TTS configuration</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `tts_announce` | `false` | Use announce mode for TTS (ducks + resumes audio) |
| `tts_output_volume` | `0.0` | Fixed volume for TTS playback. 0 = use current volume |

</details>

<details><summary>④ Duck other players (deprecated)</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `duck_player_list` | `[]` | **Deprecated v2.0.0** -- ignored, kept for backward compat |
| `duck_volume` | `0.10` | **Deprecated v2.0.0** -- ignored, kept for backward compat |
| `duck_snapshot_helper` | `""` | **Deprecated v2.0.0** -- ignored, kept for backward compat |
| `restore_delay` | `8` | **Deprecated v2.0.0** -- ignored, kept for backward compat |

</details>

<details><summary>⑤ Follow-me bypass</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `bypass_follow_me` | `true` | Pause notification follow-me during replay |
| `bypass_claim_script` | `script.refcount_bypass_claim` | Refcount claim script entity |
| `bypass_release_script` | `script.refcount_bypass_release` | Refcount release script entity |

</details>

<details><summary>⑥ Infrastructure</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `dispatcher_enabled` | `input_boolean.ai_dispatcher_enabled` | Boolean that enables the AI agent dispatcher |
| `follow_me_entity` | `input_boolean.ai_notification_follow_me` | Follow-me boolean (checked before claiming bypass) |
| `tts_queue_status_entity` | `sensor.ai_tts_queue_status` | TTS queue status sensor (used for playback completion wait) |

</details>

## Technical Notes

- **Mode:** `single`
- The script reads the notification sensor's current state directly (no trigger) -- it replays whatever notification is current at call time
- Deprecated section 4 inputs are declared but never read in the sequence -- HA silently ignores them, and removing them would break existing instances
- TTS queue sets volume but does not restore it afterward -- VA satellites set their own volume on the next voice interaction
- The follow-me bypass uses a refcount pattern so multiple concurrent callers cannot accidentally leave follow-me permanently disabled

## Changelog

- **v2.0.0** -- TTS queue migration: replaced raw `tts.speak` + manual volume/ducking (~175 lines) with single `pyscript.tts_queue_speak` call. Section 4 duck inputs deprecated as no-ops.
- **v1.2.0** -- Duck guard integration + follow-me bypass refcount
- **v1.1.0** -- TTS output volume slider + user pet names
- **v1.0** -- Initial release

## Author

**madalone**

## License

See repository for license details.
