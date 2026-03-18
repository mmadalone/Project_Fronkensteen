# Bedtime Advisory Actions (I-40)

Fires when `predictive_schedule.py` detects the user is within 15 minutes of their target routine start time. Consumes the `ai_bedtime_advisory` event and runs configurable actions such as dimming lights, starting wind-down playlists, or setting thermostats to sleep mode. Includes a TTS announcement with static or LLM-generated message support.

## How It Works

```
predictive_schedule.py
        |
        v
ai_bedtime_advisory event
        |
        v
+-------------------+
| Enable toggle ON? |
+-------------------+
        |
        v
+-------------------+
| Confidence gate   |
| (low/med/high)    |
+-------------------+
        |
        v
+-------------------+
| Routine stage     |
| suppression gate  |
+-------------------+
        |
        v
+-------------------+
| TTS announcement  |
| (static or LLM)   |
+-------------------+
        |
        v
+-------------------+
| Run advisory      |
| actions           |
+-------------------+
```

## Features

- Event-driven: fires on `ai_bedtime_advisory` event from the predictive schedule engine
- Confidence gating: only fires when prediction confidence meets the configured threshold (low/medium/high)
- Routine suppression: optionally skips if a bedtime routine is already in progress (`ai_routine_stage` not "none")
- TTS announcement with two modes: static text or LLM-generated message
- LLM mode uses `{recommendation}` placeholder to inject the bedtime advisor's recommendation text
- Custom action block for wind-down automation (lights, thermostat, playlist, etc.)
- Per-instance kill switch via input_boolean

## Prerequisites

- Home Assistant 2024.10.0+
- `predictive_schedule.py` pyscript engine (fires `ai_bedtime_advisory` events)
- `input_boolean` entity for per-instance kill switch
- `input_text.ai_routine_stage` (if routine suppression enabled)
- Conversation agent entity (if LLM TTS mode used)
- Media player entity (if TTS announcements used)

## Installation

1. Copy `bedtime_advisory_actions.yaml` to `config/blueprints/automation/madalone/`
2. Create automation: **Settings -> Automations -> Create -> Use Blueprint**

## Configuration

<details><summary>① Control</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `enable_toggle` | _(required)_ | Per-instance kill switch (input_boolean) |
| `min_confidence` | `medium` | Minimum prediction confidence (low/medium/high) |
| `suppress_if_routine_active` | `true` | Don't fire if a routine is already in progress |

</details>

<details><summary>② Actions</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `advisory_actions` | `[]` | Actions to run (e.g., dim lights, wind-down playlist) |
| `tts_speaker` | _(empty)_ | Media player for TTS announcements |
| `tts_mode` | `static` | TTS mode: `static` (text) or `llm` (LLM-generated) |
| `tts_message` | `Time to start winding down.` | Static TTS message (static mode only) |
| `llm_prompt` | `Generate a brief, gentle bedtime reminder...` | LLM prompt with `{recommendation}` placeholder (llm mode only) |
| `llm_agent` | _(empty)_ | Conversation agent entity for LLM-generated messages |

</details>

## Technical Notes

- **Mode:** `single` (silent on exceeded) -- prevents overlapping advisory runs
- **Relationship to other blueprints:** This handles pre-advisory (before target time). `proactive_bedtime_escalation.yaml` handles overdue escalation (past target time)
- **Confidence mapping:** `low=1`, `medium=2`, `high=3` -- event confidence must meet or exceed configured minimum
- **LLM fallback:** If LLM call fails or returns empty speech, falls back to the static `tts_message`
- **Event data:** Reads `confidence`, `recommendation`, and `minutes_until` from the `ai_bedtime_advisory` event payload
- **Error handling:** LLM call and LLM-based TTS both use `continue_on_error: true`

## Author

**madalone**

## License

See repository for license details.
