# Voice -- Set Bedtime Countdown

![Header](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/voice_set_bedtime_countdown-header.jpeg)

LLM tool wrapper that sets the bedtime countdown duration on an `input_number` helper. Designed as a voice-agent tool script -- the conversation agent calls this during bedtime negotiation to adjust how many minutes remain before the lamp turns off. Values outside the configured min/max range are silently clamped.

## How It Works

```
LLM calls script with minutes
            |
            v
  ┌──────────────────────────────┐
  │ Resolve inputs               │
  │ Clamp minutes to [min, max]  │
  │ Track if value was clamped   │
  └───────────┬──────────────────┘
              |
              v
  ┌──────────────────────────────┐
  │ Set countdown helper         │
  │ input_number.set_value       │
  │ (NO continue_on_error --     │
  │  failure surfaces to LLM)    │
  └───────────┬──────────────────┘
              |
              v
  ┌──────────────────────────────┐
  │ Return confirmation          │
  │ (includes clamping notice    │
  │  if value was adjusted)      │
  └──────────────────────────────┘
```

## Features

- Voice-agent tool script -- LLM passes `minutes` at runtime
- Configurable min/max bounds to prevent negotiation abuse (e.g. user sweet-talking a 3-hour countdown)
- Silent clamping with explicit feedback to the conversation agent when adjusted
- Structured response via `stop:` + `response_variable` for tool-call reply
- Failure on `input_number.set_value` intentionally surfaces to the LLM (no `continue_on_error`)

## Prerequisites

- Home Assistant **2024.10.0** or later
- An `input_number` helper configured for bedtime countdown (must match the helper in your bedtime routine blueprint)

## Installation

1. Copy `voice_set_bedtime_countdown.yaml` to `config/blueprints/script/madalone/`
2. Create script: **Settings -> Automations & Scenes -> Scripts -> Add -> Use Blueprint**

## Configuration

<details>
<summary><strong>① Configuration</strong></summary>

| Input | Default | Description |
|---|---|---|
| `countdown_helper` | _(none)_ | The `input_number` entity that stores the bedtime countdown duration |
| `min_minutes` | `1` | Floor for negotiation -- agent cannot set fewer than this (1--10 min) |
| `max_minutes` | `15` | Ceiling for negotiation -- agent cannot set more than this (5--60 min) |

</details>

### Runtime Fields (passed by LLM)

| Field | Required | Description |
|---|---|---|
| `minutes` | Yes | Countdown duration in minutes; clamped to configured min/max bounds |

## Technical Notes

- **Mode:** `single`
- **Version:** 1.1.0
- Clamping uses `[_min, [_requested, _max] | min] | max` -- standard min/max clamp pattern
- The `stop:` action returns a structured response to the calling conversation agent, including whether the value was adjusted
- `continue_on_error` is intentionally omitted on the `input_number.set_value` step -- if the helper is misconfigured, the error must surface to the LLM rather than silently succeeding with no effect

## Changelog

- **v1.1.0** -- Clamping logic, structured response to conversation agent

## Author

**madalone**

## License

See repository for license details.
