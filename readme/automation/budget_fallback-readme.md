![Budget Fallback -- Per-Satellite Pipeline Switch](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/budget_fallback-header.jpeg)

# Budget Fallback -- Per-Satellite Pipeline Switch

When the AI budget is exhausted (`ai_budget_fallback_active` turns ON), this blueprint saves the current pipeline for each satellite and switches to a low-cost fallback pipeline (default: Davis). When the flag turns OFF (midnight reset or manual toggle), it restores the original pipeline. One instance per satellite, following the same per-satellite pattern as `voice_handoff.yaml`.

## How It Works

```
input_boolean.ai_budget_fallback_active
        |
   +----+----+
   |         |
   v         v
  ON        OFF
   |         |
   v         v
+--------+ +--------+
| Read   | | Read   |
| current| | saved  |
| pipe-  | | pipe-  |
| line   | | lines  |
+--------+ +--------+
   |         |
   v         v
+--------+ +--------+
| Save   | | Restore|
| to JSON| | from   |
| helper | | JSON   |
+--------+ +--------+
   |         |
   v         v
+--------+ +--------+
| Switch | | Select |
| to     | | saved  |
| fall-  | | pipe-  |
| back   | | line   |
+--------+ +--------+
   |         |
   v         v
+--------+ +--------+
| TTS    | | Remove |
| announce| | JSON  |
| (opt.) | | entry  |
+--------+ +--------+
```

## Features

- Automatic pipeline save/restore on budget exhaustion and recovery
- Shared JSON storage (`input_text.ai_budget_saved_pipelines`) supports multiple satellite instances
- Case-insensitive pipeline matching against available options
- Optional TTS announcement when switching to fallback (via HA Cloud TTS)
- Per-instance enable toggle to exclude specific satellites from budget fallback
- Clean JSON entry removal on restore to prevent stale data

## Prerequisites

- Home Assistant
- `input_boolean.ai_budget_fallback_active` (set by the budget exhaustion automation)
- `input_text.ai_budget_saved_pipelines` (shared JSON storage for saved pipelines)
- `pyscript/tts_queue.py` (for TTS announcement)
- A fallback pipeline (e.g., Davis) configured in the satellite's pipeline selector

## Installation

1. Copy `budget_fallback.yaml` to `config/blueprints/automation/madalone/`
2. Create automation: **Settings -> Automations -> Create -> Use Blueprint**
3. Create one instance per satellite

## Configuration

<details><summary>① Core</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `satellite` | _(empty)_ | Voice PE satellite entity (assist_satellite domain) |
| `pipeline_select` | _(empty)_ | Select entity controlling this satellite's pipeline |
| `enable_budget_fallback` | `true` | When off, this satellite ignores budget exhaustion |

</details>

<details><summary>② Fallback Configuration</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `fallback_pipeline` | `Davis` | Pipeline name to switch to when budget exhausted |
| `announcement_text` | `Budget limit reached. Switching to basic mode.` | TTS announcement text. Empty = skip |
| `tts_speaker` | _(empty)_ | Speaker for the fallback announcement |
| `tts_fallback_voice` | `tts.home_assistant_cloud` | TTS engine entity for fallback announcements |
| `bypass_ducking` | `false` | Skip volume ducking on other speakers during TTS |

</details>

<details><summary>③ Infrastructure</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `fallback_active_entity` | `input_boolean.ai_budget_fallback_active` | Boolean that signals budget fallback is active |
| `saved_pipelines_entity` | `input_text.ai_budget_saved_pipelines` | input_text storing saved pipeline JSON for restore |

</details>

## Technical Notes

- **Mode:** `restart` -- a new trigger (ON/OFF) cancels the previous run, which is correct for flag-based lifecycle
- **Separate from voice_handoff.yaml by design:** Both use `mode: restart` but have different lifecycles (handoff = per-event, fallback = flag-based). Mixing flows in one blueprint would cause cancellation conflicts
- **Pipeline matching:** Case-insensitive comparison against the satellite's available pipeline options
- **JSON persistence:** Uses Jinja2 `from_json`/`to_json` with namespace-based dict construction to add/remove entries
- **Guard clauses:** Only switches if the target pipeline exists in available options and differs from the current pipeline
- **Error handling:** TTS announcement uses `continue_on_error: true`
- **Recovery flow:** Midnight budget reset turns off the flag, which triggers the restore path for all satellite instances

## Author

**madalone**

## License

See repository for license details.
