# AI -- Conversation Summarizer (v1.0.0)

Scheduled batch summarization of raw conversation responses stored in L2 memory by `conversation_sensor.py`. Groups entries by agent persona, compresses each group via LLM into a 2--3 sentence summary, and stores summaries back in L2 with configurable retention. Summaries auto-embed on the next `embedding_batch` run.

## How It Works

```
┌──────────────────────────────────┐
│  TRIGGER                          │
│  Time trigger at configured       │
│  batch time (e.g., 03:00)        │
└──────────────┬───────────────────┘
               │
               ▼
┌──────────────────────────────────┐
│  Kill switch gate                 │
│  (must be ON / enabled)           │
└──────────────┬───────────────────┘
               │ pass
               ▼
┌──────────────────────────────────┐
│  pyscript.summarize_             │
│  conversations                    │
│                                   │
│  • Search L2 for unsummarized    │
│    conversation responses         │
│  • Filter by lookback hours       │
│  • Group by agent persona         │
│  • Skip agents below min count    │
│  • Cap at max conversations       │
│  • Compress via LLM per agent     │
│  • Store summary in L2            │
│  • Tag/delete/leave sources       │
│    per retention mode             │
└──────────────┬───────────────────┘
               │
               ▼
┌──────────────────────────────────┐
│  Log result to system_log         │
│  (summaries, processed, skipped,  │
│   llm_calls, tokens, agents)      │
└──────────────────────────────────┘
```

## Features

- Scheduled batch execution at configurable time (recommendation: 03:00, 30 min before embedding batch)
- Groups unsummarized conversation responses by agent persona
- LLM-compressed summaries (2--3 sentences per agent per batch)
- Configurable lookback window to only process aged entries
- Minimum conversation threshold per agent (prevents wasting LLM calls on single entries)
- Maximum conversations cap per run (budget safeguard)
- Three retention modes: tag sources (let TTL expire), delete sources immediately, or leave untouched
- Configurable summary expiry (1--365 days) in L2 memory
- Budget floor gate to skip summarization when LLM budget is low
- Kill switch for easy enable/disable
- Result logging to `system_log` with full metrics (summaries created, entries processed/skipped, LLM calls, tokens, agents)

## Prerequisites

- Home Assistant 2024.10.0+
- Pyscript modules: `conversation_sensor` (stores raw conversation responses in L2), `summarize_conversations` service
- `input_datetime.ai_conversation_summarizer_batch_time` (batch time control)
- `input_boolean.ai_conversation_sensor_enabled` (kill switch)
- `sensor.ha_text_ai` (or configured LLM instance)
- L2 memory system (`memory.py`)

## Installation

1. Copy `conversation_summarizer.yaml` to `config/blueprints/automation/madalone/`
2. Create the helper entities (batch time + kill switch)
3. Create automation: **Settings -> Automations -> Create -> Use Blueprint**

## Configuration

<details><summary>① Schedule & Control</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `batch_time` | `input_datetime.ai_conversation_summarizer_batch_time` | Time entity that controls when the batch runs |
| `kill_switch` | `input_boolean.ai_conversation_sensor_enabled` | Boolean that enables/disables summarization. ON = active |

</details>

<details><summary>② Summarization Tuning</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `lookback_hours` | `36` | Only summarize conversations older than this many hours |
| `min_conversations` | `3` | Skip agents with fewer unsummarized conversations than this |
| `max_conversations` | `50` | Total cap on conversations processed per run (budget safeguard) |
| `retention_mode` | `summary_and_tag` | How to handle sources after summarizing: `summary_and_tag` (tag, let TTL expire), `summary_and_delete` (remove sources), `summary_only` (leave sources untouched) |
| `summary_expiry_days` | `30` | How long summary entries persist in L2 memory |

</details>

<details><summary>③ Infrastructure</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `llm_instance` | `sensor.ha_text_ai` | ha_text_ai sensor for LLM compression calls |
| `budget_floor` | `30` | Skip summarization when remaining LLM budget drops below this %. 0 = always run |

</details>

## Technical Notes

- **Mode:** `single` -- prevents overlapping summarization runs
- **Cost:** Approximately $0.001/run at gpt-4o-mini tier
- **Trigger:** Time trigger using `input_datetime` entity (not a fixed time pattern), allowing runtime schedule changes
- **Budget gate:** Checked inside `pyscript.summarize_conversations` using the `budget_floor` parameter
- **Retention modes:**
  - `summary_and_tag`: Tags source entries as "summarized"; they expire naturally via their own TTL
  - `summary_and_delete`: Immediately removes source entries after summarization
  - `summary_only`: Creates summaries without modifying source entries
- **Embedding pipeline:** Summaries auto-embed on the next `embedding_batch` run (typically 03:30), making them searchable via semantic memory queries
- **Result logging:** Writes to `conversation_sensor.summarizer` logger at `info` level with structured metrics
- **All pyscript calls** use `continue_on_error: true`

## Author

**madalone**

## License

See [LICENSE](../../LICENSE) in the repository root.
