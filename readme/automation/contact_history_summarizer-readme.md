![Contact History Summarizer (v1.0.0)](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/contact_history_summarizer-header.jpeg)

# Contact History Summarizer (v1.0.0)

Batch job that compresses raw per-contact message entries into LLM-compressed digests for the notification follow-me contact history feature (I-47). Searches L2 memory for unsummarized `contact_msg_*` entries, groups them by contact, compresses each group via LLM into a 2-3 sentence digest, and stores the result with a configurable TTL. Three trigger modes allow tuning the cost/freshness tradeoff.

## How It Works

```
+--------------------+     +--------------------+
| Scheduled trigger  |     | Event trigger      |
| (15m/30m/1h/2h/   |     | (contact_history_  |
|  4h/6h/12h)       |     |  log_complete)     |
+--------------------+     +--------------------+
         |                          |
         +----------+---+-----------+
                    |   |
                    v   v
            +-------------------+
            | Kill switch ON?   |
            +-------------------+
                    |
                    v
            +-------------------+
            | Trigger mode      |
            | + schedule gate   |
            +-------------------+
                    |
          +---------+---------+
          |                   |
          v                   v
   +-----------+       +-----------+
   | EVENT:    |       | SCHEDULED:|
   | Hybrid    |       | Run full  |
   | cooldown  |       | batch     |
   | gate      |       |           |
   +-----------+       +-----------+
          |                   |
          v                   |
   +-----------+              |
   | Threshold |              |
   | check per |              |
   | contact   |              |
   +-----------+              |
          |                   |
          v                   v
   +-----------+       +-----------+
   | Summarize |       | Summarize |
   | single    |       | all       |
   | contact   |       | contacts  |
   +-----------+       +-----------+
          |                   |
          v                   v
   +-----------+       +-----------+
   | Log result|       | Log result|
   +-----------+       +-----------+
```

## Features

- Three trigger modes: scheduled (fixed interval), event-driven (per message log), hybrid (both with cooldown)
- Configurable schedule intervals: 15m, 30m, 1h, 2h, 4h, 6h, 12h
- Event-driven threshold: only triggers when unsummarized messages per contact reach the configured count
- Hybrid cooldown: prevents excessive LLM calls when many messages arrive quickly
- Per-contact or full batch processing depending on trigger type
- Configurable minimum messages per contact to prevent wasting LLM calls on single entries
- Maximum contacts per run as a budget safeguard
- Configurable digest retention (1-90 days) in L2 memory
- Kill switch for easy disable without removing the automation
- Result logging to `system_log` for monitoring

## Prerequisites

- Home Assistant
- `pyscript/contact_history.py` (L2 contact history services)
- `pyscript/memory.py` (L2 memory search)
- `input_boolean.ai_contact_history_enabled` (kill switch)
- `sensor.ha_text_ai` (or configured LLM instance)
- Notification follow-me system (I-47) generating `contact_history_log_complete` events

## Installation

1. Copy `contact_history_summarizer.yaml` to `config/blueprints/automation/madalone/`
2. Create automation: **Settings -> Automations -> Create -> Use Blueprint**

## Configuration

<details><summary>① Trigger Mode</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `trigger_mode` | `scheduled` | Trigger strategy: scheduled, event_driven, or hybrid |
| `schedule_interval` | `1h` | How often scheduled trigger fires (15m/30m/1h/2h/4h/6h/12h) |
| `event_threshold` | `3` | Unsummarized messages per contact before event-driven fires |
| `hybrid_cooldown_minutes` | `30` | Minimum interval between event-driven runs in hybrid mode |

</details>

<details><summary>② Tuning</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `min_messages` | `2` | Skip contacts with fewer unsummarized messages |
| `max_contacts` | `20` | Max contacts processed per run (budget safeguard) |
| `summary_expiry_days` | `7` | How long digest entries persist in L2 memory |

</details>

<details><summary>③ Infrastructure</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `llm_instance` | `sensor.ha_text_ai` | ha_text_ai sensor for LLM compression calls |
| `kill_switch` | `input_boolean.ai_contact_history_enabled` | Boolean to enable/disable summarization |

</details>

## Technical Notes

- **Mode:** `single` -- prevents overlapping summarization runs
- **Cost:** Approximately $0.001/contact at gpt-4o-mini tier
- **Schedule implementation:** Uses two time_pattern triggers (minutes and hours) with condition logic to match the configured interval. Sub-hour intervals (15m, 30m) use the minutes trigger; hourly+ intervals use the hours trigger with modulo checks
- **Hybrid cooldown:** Checks `this.attributes.last_event_run` to calculate elapsed time since last event-driven run
- **Event-driven path:** Searches L2 for the specific contact's unsummarized entries, counts them, and only runs if threshold is met. Processes only the single triggering contact (max_contacts=1)
- **Scheduled path:** Runs full batch processing across all contacts up to max_contacts limit
- **Tagging:** Source entries are tagged as "summarized" after processing to prevent re-compression
- **Error handling:** All pyscript calls use `continue_on_error: true`

## Author

**madalone**

## License

See repository for license details.
