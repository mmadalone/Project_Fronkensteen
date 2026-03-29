![Music -- Batch Composition Trigger](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/music_compose_batch_trigger-header.jpeg)

# Music -- Batch Composition Trigger

Trigger batch generation of static music compositions (themes, chimes, thinking loops, stingers) for all or selected agents via the ElevenLabs Music/SFX API. Press the batch button on the dashboard to start.

## How It Works

```
┌──────────────────────────────────────┐
│          TRIGGER                     │
│  input_button.ai_music_compose_batch │
│  (state change = button press)       │
└──────────────────┬───────────────────┘
                   │
                   ▼
┌──────────────────────────────────────┐
│          CONDITIONS                  │
│  • Kill switch ON?                   │
└──────────────────┬───────────────────┘
                   │ pass
                   ▼
┌──────────────────────────────────────┐
│   pyscript.music_compose_batch       │
│   • agents (selected or all)         │
│   • content_types (selected or all   │
│     static: theme, chime, thinking,  │
│     stinger)                         │
│   • auto_approve (staging or prod)   │
└──────────────────┬───────────────────┘
                   │
                   ▼
┌──────────────────────────────────────┐
│   Log batch result                   │
│   logbook.log with generated/cached/ │
│   error counts                       │
└──────────────────────────────────────┘
```

## Features

- Dashboard-triggered batch generation via `input_button` press
- Per-agent filtering: generate for all agents or a selected subset (rick, quark, deadpool, kramer, portuondo)
- Per-type filtering: generate all static types or select from theme (5s), chime (1-2s), thinking (10s), stinger (2-3s)
- Auto-approve mode: write directly to production cache or stage for review
- Kill switch integration with the global music composer toggle
- Logbook entry with generated/cached/error counts on completion
- `continue_on_error: true` on the batch call to prevent partial failures from stopping the log step

## Prerequisites

- Home Assistant 2024.10.0+
- Pyscript service: `pyscript.music_compose_batch`
- `input_boolean.ai_music_composer_enabled` (kill switch)
- `input_button.ai_music_compose_batch` (dashboard trigger)

## Installation

1. Copy `music_compose_batch_trigger.yaml` to `config/blueprints/automation/madalone/`
2. Create automation: **Settings -> Automations -> Create -> Use Blueprint**

## Configuration

<details><summary>① Generation Settings</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `agents_to_generate` | `[]` (all agents) | Which agents to include in batch generation. Leave empty for all agents |
| `content_types` | `[]` (all static types) | Which composition types to include. Leave empty for all static types (theme, chime, thinking, stinger) |
| `auto_approve` | `false` | Skip staging and write directly to production cache. Disable for first-time generation to review quality before use |

</details>

<details><summary>② Infrastructure</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `kill_switch` | `input_boolean.ai_music_composer_enabled` | Global enable/disable for the music composition engine |
| `batch_button` | `input_button.ai_music_compose_batch` | Input button entity that triggers batch generation |

</details>

## Technical Notes

- **Mode:** `single` / `max_exceeded: silent` -- only one batch at a time
- **Trigger:** `state` change on the `batch_button` entity (any state change from a button press)
- **Empty list handling:** Empty `agents_to_generate` or `content_types` lists are passed as `[]` to the pyscript service, which interprets this as "all"
- **Staging vs production:** When `auto_approve` is false, compositions go to a staging area for manual review before promotion to the production cache

## Changelog

- **v1.0:** Initial version -- batch static composition generation

## Author

**madalone**

## License

See [LICENSE](../../LICENSE) in the repository root.
