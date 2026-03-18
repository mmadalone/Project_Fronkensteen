# Memory Embedding Batch

Runs a batch of memory embeddings on a schedule. At the configured time, calls `pyscript.memory_embed_batch` to vectorize unembedded L2 memory entries for semantic search. Configurable batch size, schedule time, and kill switch.

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
│  • Kill switch not ON? (skip if unconfigured)          │
└────────────────────────┬────────────────────────────────┘
                         │ pass
                         ▼
┌─────────────────────────────────────────────────────────┐
│                  ACTION SEQUENCE                        │
│  1. Call pyscript.memory_embed_batch                   │
│     (batch_size from helper, scope: all)               │
│  2. Log result to system_log                           │
│     (embedded, failed, tokens, reindexed)              │
└─────────────────────────────────────────────────────────┘
```

## Features

- **Scheduled embedding** -- runs at a configurable time (typically overnight) to vectorize new L2 memory entries.
- **Configurable batch size** -- controlled via an input_number helper (default 50 entries per run).
- **Kill switch** -- optional input_boolean to disable embedding without removing the automation.
- **Result logging** -- logs embedded count, failed count, tokens used, and reindex status to `system_log`.

## Prerequisites

- Home Assistant
- Pyscript with `memory_embed_batch` service (L2 memory system)
- `input_datetime` helper for schedule time
- `input_number` helper for batch size (default: `input_number.ai_embedding_batch_size`)

## Installation

1. Copy `embedding_batch.yaml` to `config/blueprints/automation/madalone/`
2. Create automation: **Settings -> Automations -> Create -> Use Blueprint**

## Configuration

<details>
<summary>Section 1 -- Schedule and Control</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `batch_time` | `""` *(required)* | Input datetime entity controlling when the batch runs |
| `batch_size` | `input_number.ai_embedding_batch_size` | Input number controlling entries per run (default 50) |
| `kill_switch` | `{}` (none) | Optional input boolean to disable embedding (ON = disabled) |

</details>

## Technical Notes

- **Mode:** Default (single).
- **Kill switch logic:** If the kill switch entity is empty, unconfigured, or `None`, the automation always runs. If configured and ON, the automation is suppressed.
- **Scope:** Always runs with `scope: all` -- processes all unembedded entries regardless of origin.
- **Batch size:** Read from the helper entity's state at runtime, defaulting to 50 if the entity is unavailable.

## Changelog

- **v1.1.0:** Fixed kill switch (was checking trigger entity instead of kill switch input).
- **v1.0.0:** Initial version.

## Author

**madalone**

## License

See repository for license details.
