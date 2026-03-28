![Music Taste Rebuild](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/music_taste_rebuild-header.jpeg)

# Music Taste -- Manual Rebuild

Triggers a full music taste profile aggregation when a rebuild button is pressed, on a scheduled interval, or at HA startup. Merges Music Assistant play logs and Spotify data into a unified taste profile on `sensor.ai_music_taste_status`. Optionally generates an LLM-powered genre/style summary (no artist names) for use in voice agent context.

## How It Works

```
┌────────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│  Rebuild button    │  │  Time pattern    │  │  HA start        │
│  pressed           │  │  (default /6 hr) │  │  (if enabled)    │
└────────┬───────────┘  └────────┬─────────┘  └────────┬─────────┘
         │                       │                      │
         └───────────┬───────────┘──────────────────────┘
                     │
                     ▼
         ┌───────────────────────────┐
         │  HA start gate            │
         │  (skip if run_on_start    │
         │   disabled + ha_start)    │
         └───────────┬───────────────┘
                     │
                     ▼
         ┌───────────────────────────┐
         │  pyscript.music_taste_    │
         │  rebuild                  │
         │  ├─ Merge play logs       │
         │  ├─ Aggregate profile     │
         │  └─ LLM genre summary    │
         └───────────────────────────┘
```

## Features

- Manual rebuild via input_button trigger
- Scheduled auto-rebuild at configurable intervals (1/2/6/12 hours)
- Optional rebuild on HA startup
- LLM-generated genre/style summary (configurable instance, prompt, and character limit)
- No artist or track names in the summary (privacy-safe for voice agents)
- Customizable LLM prompt with `{profile}` and `{max_chars}` placeholders

## Prerequisites

- Pyscript integration with `music_taste_rebuild` service deployed
- Music Assistant integration (for play log data)
- `input_button.ai_music_taste_rebuild` helper (or custom button entity)
- Optional: `ha_text_ai` sensor for LLM summarization

## Installation

1. Copy `music_taste_rebuild.yaml` to `config/blueprints/automation/madalone/`
2. Create automation: **Settings -> Automations -> Create -> Use Blueprint**

## Configuration

<details>
<summary><strong>① Core</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| `rebuild_button` | `input_button.ai_music_taste_rebuild` | The input_button that triggers the rebuild |
| `refresh_interval` | `/6` (every 6 hours) | Auto-rebuild interval: /1, /2, /6, /12 hours |
| `run_on_start` | `true` | Rebuild automatically when Home Assistant starts |

</details>

<details>
<summary><strong>② LLM Configuration</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| `llm_instance` | `sensor.ha_text_ai_deepseek_chat` | ha_text_ai sensor for genre summary. Leave blank to skip LLM summarization |
| `summary_max_chars` | `100` | Maximum characters for the genre summary (40-200) |
| `llm_prompt` | *(see below)* | Custom prompt with `{profile}` and `{max_chars}` placeholders |

Default LLM prompt: "Given this music profile, write a concise genre/style summary in plain text. No artist or track names. No markdown, no bold, no char counts, no alternatives. Just one short phrase, max {max_chars} characters."

</details>

## Technical Notes

- **Mode:** `single`
- Scheduled trigger runs at minute :30 of the configured hour pattern
- HA start trigger is gated by the `run_on_start` boolean
- LLM summarization is handled within the pyscript service -- leave `llm_instance` blank to use raw profile instead

## Changelog

- **v1.0:** Initial release -- manual + scheduled rebuild with LLM genre summary

## Author

**madalone**

## License

See repository for license details.
