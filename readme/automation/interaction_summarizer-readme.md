![Interaction Summarizer](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/interaction_summarizer-header.jpeg)

# Interaction Summarizer

Scheduled job that compresses whisper interaction logs into per-agent summaries using a cheap LLM call. At the scheduled time, searches L2 memory for unsummarized interaction entries older than the lookback window, groups them by agent persona, and compresses each group via LLM into a compact 2-3 sentence digest. Summaries are stored as new L2 entries with a long TTL and auto-embed on the next nightly embedding batch run.

## How It Works

```
┌─────────────────────────────────────────────────────────┐
│                      TRIGGER                            │
│  ┌───────────────────────────────────────────────────┐  │
│  │ Time trigger: at scheduled batch_time             │  │
│  └──────────────────────┬────────────────────────────┘  │
└─────────────────────────┼───────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│                  CONDITION GATE                         │
│  • Kill switch not ON?                                 │
└────────────────────────┬────────────────────────────────┘
                         │ pass
                         ▼
┌─────────────────────────────────────────────────────────┐
│                  ACTION SEQUENCE                        │
│  1. Call pyscript.summarize_interactions                │
│     • lookback_hours: only entries older than N hours   │
│     • min_interactions: skip agents with too few        │
│     • max_interactions: total cap per run               │
│     • retention_mode: tag/delete/archive sources        │
│     • summary_expiry_days: TTL for summaries            │
│  2. Log result to system_log                           │
│     (summaries created, entries processed/skipped,      │
│      LLM calls, tokens, agents summarized)             │
└─────────────────────────────────────────────────────────┘
```

## Features

- **Per-agent compression** -- groups raw interaction entries by voice assistant persona, summarizes each group separately.
- **LLM-powered summarization** -- uses a cheap LLM call (~$0.001/run at gpt-4o-mini) to distill N entries into 2-3 sentences.
- **3 retention modes:**
  - `summary_and_tag` (default) -- tag sources as "summarized", let their natural 2-day TTL expire. Auditable, zero risk.
  - `summary_only` -- delete source entries immediately after summarizing.
  - `both` -- tag as "archived" and extend TTL to match summary lifetime.
- **Configurable lookback** -- only processes entries older than N hours (default 36h, must be < 48h interaction TTL).
- **Min interactions gate** -- skips agents with fewer than N unsummarized entries to avoid wasting LLM calls on single sentences.
- **Max interactions cap** -- budget safeguard limiting total entries processed per run.
- **Long-lived summaries** -- summaries persist with configurable TTL (default 30 days).
- **Auto-embedding** -- summaries are picked up by the next nightly embedding batch run (no special wiring needed).
- **Budget safety** -- uses the standard LLM budget tier; pauses gracefully if budget drops below 30%.
- **Kill switch** -- disable summarization without removing the automation.

## Prerequisites

- Home Assistant
- Pyscript with `summarize_interactions` service (L2 memory system)
- `input_datetime` helper for schedule time (e.g., `input_datetime.ai_summarizer_batch_time`)
- L2 memory system with interaction log entries

## Installation

1. Copy `interaction_summarizer.yaml` to `config/blueprints/automation/madalone/`
2. Create automation: **Settings -> Automations -> Create -> Use Blueprint**

## Configuration

<details>
<summary>Section 1 -- Schedule and Control</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `batch_time` | `input_datetime.ai_summarizer_batch_time` | Input datetime entity for batch schedule |
| `kill_switch` | `""` | Input boolean to disable summarization (ON = disabled) |

</details>

<details>
<summary>Section 2 -- Summarization Tuning</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `lookback_hours` | `36` | Only summarize entries older than this (12-47, must be < 48h TTL) |
| `min_interactions` | `3` | Skip agents with fewer unsummarized entries |
| `max_interactions` | `50` | Total cap on entries processed per run |
| `retention_mode` | `summary_and_tag` | Source handling: `summary_and_tag`, `summary_only`, or `both` |
| `summary_expiry_days` | `30` | How long summary entries persist in L2 (7-365 days) |

</details>


## Technical Notes

- **Mode:** `single` -- only one summarization run at a time.
- **Recommended schedule:** 03:00 (30 minutes before embedding batch at 03:30) so summaries are ready for embedding.
- **Budget tier:** Standard tier by default. If budget drops below 30%, summarization pauses gracefully.
- **Cost:** Approximately $0.001 per run at gpt-4o-mini pricing.
- **Result logging:** Logs to `agent_whisper.summarizer` logger with summaries created, entries processed/skipped, LLM calls, tokens, and agent names.

## Changelog

- **v1.0.0:** Initial release -- scheduled L2 interaction compression with per-agent grouping, 3 retention modes, budget safety.

## Author

**madalone**

## License

See repository for license details.
