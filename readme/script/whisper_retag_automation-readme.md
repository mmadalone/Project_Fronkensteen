![Whisper Re-tag Automation Entries](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/whisper_retag_automation-header.jpeg)

# Whisper Re-tag Automation Entries

One-shot cleanup script that scans existing whisper interaction entries whose values match known automation patterns (goodnight negotiator, music follow-me, notification replay, etc.) but were logged without the `source_automation` tag, and re-tags them. Run with Dry Run enabled first to preview matches, then disable to apply. This is a maintenance tool -- run it once after deploying the whisper source filtering update, then disable or delete the script instance.

## How It Works

```
User runs script
        |
        v
┌────────────────────────────────────┐
│ Call pyscript service              │
│ pyscript.whisper_retag_automation  │
│ (dry_run: true/false)              │
│                                    │
│ → Scans L2 whisper entries         │
│ → Matches automation patterns      │
│ → Re-tags missing entries          │
└───────────┬────────────────────────┘
            |
            v
┌───────────────────────────────┐
│ Log result to logbook         │
│ scanned / matched / retagged  │
│ failed / already_tagged /     │
│ skipped (dry_run)             │
└───────────────────────────────┘
```

## Features

- Dry run mode -- preview matches without writing changes
- Delegates to `pyscript.whisper_retag_automation` for pattern matching
- Logbook entry with full statistics: scanned, matched, retagged, failed, already tagged, skipped
- `continue_on_error: true` on the pyscript call for resilience
- After re-tagging, the summarizer correctly labels entries as `[AUTO]` (system-delivered) instead of `[USER]` (user-initiated)

## Prerequisites

- Home Assistant **2024.10.0** or later
- `pyscript` integration with `whisper_retag_automation` service deployed
- Existing whisper interaction entries in the L2 memory system

## Installation

1. Copy `whisper_retag_automation.yaml` to `config/blueprints/script/madalone/`
2. Create script: **Settings -> Automations & Scenes -> Scripts -> Add -> Use Blueprint**

## Configuration

<details>
<summary><strong>① Configuration</strong></summary>

| Input | Default | Description |
|---|---|---|
| `dry_run` | `true` | Preview matches without writing. Enable first to see what would be re-tagged, then disable to apply. |

</details>

## Technical Notes

- **Mode:** `single`
- This is a one-shot maintenance tool -- run once after deploying the whisper source filtering update, then disable or delete
- Dry run is ON by default to prevent accidental writes
- The pyscript service returns a result dict with keys: `scanned`, `matched`, `retagged`, `failed`, `already_tagged`, `skipped`, `dry_run`
- The logbook step renders all result fields with safe `| default({})` and `.get()` fallbacks

## Changelog

- **v1.0** -- Initial version; one-shot re-tagging utility

## Author

**madalone**

## License

See repository for license details.
