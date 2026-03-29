# AI System Recovery Alert (v2.0.0)

Fires when the self-healing recovery engine exhausts its retry budget for a health category. Sends a persistent notification, optionally pushes to a mobile device, and optionally announces via TTS using the full voice stack (dispatcher, presence routing, follow-me bypass). One instance is usually sufficient, but multiple instances can be created with different category filters or notification targets.

## How It Works

```
┌──────────────────────────────────────┐
│  TRIGGER                              │
│  event: ai_recovery_exhausted         │
│  (fired by self-healing engine)       │
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│  Category filter                      │
│  (empty = all categories pass)        │
└──────────────┬───────────────────────┘
               │ pass
               ▼
┌──────────────────────────────────────┐
│  1. Persistent notification           │
│  (always — category, attempts, grade) │
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│  2. Mobile push (if configured)       │
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│  3. TTS announcement (if enabled     │
│     + satellite resolved)             │
│                                       │
│  3a. Dispatcher resolution            │
│      (or direct agent)                │
│  3b. Claim follow-me bypass           │
│  3c. LLM announcement via             │
│      conversation.process             │
│  3d. TTS delivery via queue           │
│  3e. Release follow-me bypass         │
└──────────────────────────────────────┘
```

## Features

- Event-driven trigger on `ai_recovery_exhausted` from the self-healing recovery engine
- Persistent notification always created with category, attempt count, and health grade
- Optional mobile push notification via configurable notify target
- Full voice stack for TTS announcements:
  - AI dispatcher for dynamic agent selection (or direct agent fallback)
  - Presence-based satellite routing (first occupied zone wins)
  - LLM-generated announcement text via `conversation.process` with alert data context
  - Follow-me bypass (refcount claim/release) during announcement
- Category filtering: comma-separated list to alert on specific subsystems only
- Configurable announce mode and output volume

## Prerequisites

- Home Assistant 2024.10.0+
- Self-healing recovery engine (fires `ai_recovery_exhausted` events)
- Pyscript modules: `agent_dispatcher` (`agent_dispatch`), `tts_queue` (`tts_queue_speak`)
- `input_boolean.ai_dispatcher_enabled` (dispatcher gate)
- Refcount bypass scripts (claim + release)
- Presence sensors + paired media player satellites (for TTS routing)

## Installation

1. Copy `system_recovery_alert.yaml` to `config/blueprints/automation/madalone/`
2. Create automation: **Settings -> Automations -> Create -> Use Blueprint**

## Configuration

<details><summary>① Core</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `notify_target` | _(empty)_ | Mobile push target (e.g., `notify.mobile_app_phone`). Empty = skip mobile push |
| `enable_tts` | `false` | Announce recovery failure via TTS using the full voice pipeline |
| `conversation_agent` | `Rick` | Voice Assistant pipeline used for the alert. Overridden when dispatcher is enabled |
| `alert_prompt` | _(see below)_ | LLM instructions for announcement tone. Category, attempts, and grade are auto-appended |

Default alert prompt:
> A system recovery attempt has failed. Announce this briefly and clearly as a system alert. Keep it to one or two sentences. State which subsystem failed and that manual attention is needed.

</details>

<details><summary>② Presence Routing</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `presence_sensors` | `[]` | Binary sensors indicating room occupancy. Order matters -- first occupied zone wins |
| `target_satellites` | `[]` | Media players for announcement, paired with presence sensors (same index order) |

</details>

<details><summary>③ Filtering</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `category_filter` | _(empty)_ | Comma-separated categories to alert on. Empty = all categories. Options: `status_sensors`, `services`, `memory_db`, `tts_queue`, `pipeline_entities`, `json_configs`, `helpers` |

</details>

<details><summary>④ TTS Configuration</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `tts_announce` | `false` | Use announce mode for TTS (ducks current audio, plays, resumes) |
| `tts_output_volume` | `0.0` | Fixed volume (0.0--1.0) before announcement. 0 = disable volume control |

</details>

<details><summary>⑤ Agent Selection</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `use_dispatcher` | `true` | Use AI dispatcher for dynamic persona selection |
| `bypass_follow_me` | `true` | Temporarily pause notification follow-me during TTS |
| `bypass_claim_script` | `script.refcount_bypass_claim` | Script entity that registers a bypass claim |
| `bypass_release_script` | `script.refcount_bypass_release` | Script entity that releases a bypass claim |

</details>

<details><summary>⑥ Infrastructure</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `dispatcher_enabled` | `input_boolean.ai_dispatcher_enabled` | Boolean that enables the AI agent dispatcher |

</details>

## Technical Notes

- **Mode:** `queued` / `max: 5` -- multiple recovery failures can fire in quick succession
- **Trigger:** `ai_recovery_exhausted` event with `category`, `attempts`, and `grade` in event data
- **Category filter:** Comma-separated, trimmed. Empty string = all categories pass
- **Presence resolution:** Iterates presence sensors in order; first `on` sensor's paired satellite is selected. If no sensor is active, TTS is skipped
- **Dispatcher resolution:** When enabled and `ai_dispatcher_enabled` is ON, calls `pyscript.agent_dispatch` with intent `"system recovery alert"`. Falls back to the configured Voice Assistant when dispatcher is off or resolution fails
- **LLM announcement:** `conversation.process` generates in-character alert text. Falls back to a static message if LLM returns empty
- **TTS metadata:** Includes `agent_name`, `message`, `topic: "system_alert"`, and `source: "system_recovery_alert"` for downstream processing
- **All actions** use `continue_on_error: true`

## Changelog

- **v2.0.0:** Full voice stack for TTS -- dispatcher toggle, agent selector, presence routing, follow-me bypass, speaker/volume options, LLM prompt for announcement text
- **v1.0.0:** Initial release (persistent notification + mobile push only)

## Author

**madalone**

## License

See [LICENSE](../../LICENSE) in the repository root.
