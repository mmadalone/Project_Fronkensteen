![Weather -- Tomorrow Forecast Promote](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/weather_forecast_promote-header.jpeg)

# Weather -- Tomorrow Forecast Promote

Reads weather sensor states (AEMET, Met.no, etc.) and an optional weather domain entity, sends all data to an LLM for a natural-language summary, and stores the result on `sensor.ai_weather_tomorrow_summary` (through `pyscript.set_sensor_value`) for hot context injection. The weather integration updates sensors on its own schedule -- this blueprint just reads the current values and summarizes them on a configurable interval.

## How It Works

```
┌──────────────────────────────────┐
│ Triggers                         │
│  ├─ Scheduled (every N hours)    │
│  ├─ Manual rebuild button        │
│  └─ HA start (if enabled)        │
└──────────────┬───────────────────┘
               │
    ┌──────────▼──────────────┐
    │ Condition               │
    │  HA start → run_on_start│
    │  enabled?               │
    └──────────┬──────────────┘
               │
    ┌──────────▼──────────────────────┐
    │ 1. Gather raw data              │
    │    ├─ Read all weather sensors  │
    │    └─ Read weather entity attrs │
    └──────────┬──────────────────────┘
               │
        ┌──────▼──────────┐
        │ Data > 5 chars? │
        └──┬──────────┬───┘
          yes          no
           │           │
    ┌──────▼───────┐   │
    │ 2. Build LLM │   │
    │    prompt     │   │
    │    Call LLM   │   │
    │    Clean text │   │
    └──────┬───────┘   │
           │     ┌─────▼──────────────┐
           │     │ "No weather data"  │
           │     └─────┬──────────────┘
           │           │
    ┌──────▼───────────▼──────┐
    │ 3. Store in sensor      │
    │    (bridge service)     │
    └─────────────────────────┘
```

## Features

- Multi-source data collection: individual sensors + weather entity attributes
- LLM-powered natural language summarization via `pyscript.llm_task_call`
- Configurable summary length (40-255 characters)
- Customizable LLM prompt with `{data}` and `{max_chars}` placeholders
- Configurable refresh interval (1/2/6/12 hours)
- Manual rebuild via `input_button` trigger
- Optional run-on-HA-start
- Post-processing: strips character counts, quotes, and multi-line artifacts from LLM output
- Falls back to raw data if LLM summary is too short

## Prerequisites

- Home Assistant 2024.10.0 or later
- `pyscript` with `llm_task_call` service
- `ha_text_ai` integration: the sensor picked in `llm_instance`, or the household task instance (`input_text.ai_task_instance`, else the install's ha_text_ai sensor)
- Weather sensor entities (e.g., AEMET, Met.no)
- `pyscript.set_sensor_value` (state_bridge.py), which writes the summary sensor
- `input_button` helper for manual rebuild

## Installation

1. Copy `weather_forecast_promote.yaml` to `config/blueprints/automation/madalone/`
2. Create automation: **Settings -> Automations -> Create -> Use Blueprint**

## Configuration

<details><summary><strong>① Data Sources</strong></summary>

| Input | Default | Description |
|---|---|---|
| `weather_sensors` | `[]` | Weather sensor entities to include (friendly names + states sent to LLM) |
| `weather_entity` | _(empty)_ | Optional `weather.*` entity; its state and attributes are included alongside sensors |

</details>

<details><summary><strong>② Configuration</strong></summary>

| Input | Default | Description |
|---|---|---|
| `summary_max_chars` | `120` | Maximum characters for the forecast summary |
| `refresh_interval` | `/6` | How often to refresh (every 1, 2, 6, or 12 hours) |
| `llm_prompt` | _(summarize prompt)_ | Custom LLM prompt; use `{data}` and `{max_chars}` placeholders |
| `run_on_start` | `true` | Refresh summary automatically on HA start |

</details>

<details><summary><strong>③ Infrastructure</strong></summary>

| Input | Default | Description |
|---|---|---|
| `llm_instance` | _(empty)_ | HA Text AI sensor for summarization (only ha_text_ai sensors are listed). Empty = household task instance (`input_text.ai_task_instance`, else the install's ha_text_ai sensor) |
| `rebuild_button` | `input_button.ai_weather_forecast_rebuild` | Manual rebuild trigger |
| `summary_helper` | `sensor.ai_weather_tomorrow_summary` | Sensor that stores the forecast summary (written through the bridge service) |

</details>

## Technical Notes

- **Mode:** `single`
- **LLM parameters:** `max_tokens: 80`, `temperature: 0.3` for concise, deterministic output; `instance` is the `llm_instance` input
- **Post-processing:** Regex strips trailing character counts (e.g., "(120 characters)"), quotes, and newlines from LLM output
- **Fallback:** If LLM returns fewer than 5 characters, raw sensor data is used instead (truncated to max chars)
- **Error handling:** `continue_on_error: true` on the LLM call

## Changelog

- **v1.1:** LLM Instance is used now (blank = household task instance)
- **v1:** Initial version

## Author

**madalone**

## License

See repository for license details.
