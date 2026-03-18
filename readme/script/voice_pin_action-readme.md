# Voice -- PIN-Gated Action (tool script)

Require a spoken passphrase before executing a protected action. Uses `assist_satellite.ask_question` with the passphrase as a templated answer, retries on wrong answers, and announces the result. Designed to chain with the `va_confirmation_dialog` automation blueprint for a full voice command to PIN challenge to action pipeline.

## How It Works

```
Start
  |
  v
+----------------------------+
| PIN enabled?               |
+----------------------------+
  | yes                 | no (bypass)
  v                     v
+------------------+   +------------------+
| PIN configured?  |   | Call protected   |
+------------------+   | script directly  |
  | yes        | no    +------------------+
  v            v               |
  |     +-------------+       STOP
  |     | Announce    |
  |     | "not config"|
  |     +-> STOP      |
  |
  v
+----------------------------+
| PIN challenge loop         |
| (up to max_attempts)       |
+----------------------------+
  |
  +----------+----------+----------+
  |          |          |          |
  v          v          v          v
CORRECT    CANCEL    WRONG      WRONG
  |          |       (retry)   (last attempt)
  v          v          |          |
+--------+ +--------+  |          v
| Call   | | Announce|  |   +----------+
| script | | cancel |  |   | Announce |
+--------+ +--------+  |   | denied   |
  |                     |   +----------+
  v                     |
+--------+              |
| Announce              |
| success|              |
+--------+              |
```

## Features

- Spoken passphrase challenge via `assist_satellite.ask_question`
- Configurable retry count (1-5 attempts)
- Bypass mode when PIN protection is disabled (runs protected script immediately)
- Safety gate when PIN is not configured (blocks action, announces error)
- Cancel phrase recognition: cancel, stop, never mind, forget it
- Customizable messages: challenge prompt, retry prompt, success, failure, cancel
- Word-based passphrases recommended over numeric PINs for reliable STT transcription

## Prerequisites

- Home Assistant 2024.10.0+
- An `assist_satellite` entity (voice satellite with question support)
- `input_text.ai_voice_pin` (passphrase helper, mode: password)
- `input_boolean.ai_voice_pin_enabled` (PIN enable/disable toggle)
- A target script entity to protect (e.g. `script.unlock_front_door`)

## Installation

1. Copy `voice_pin_action.yaml` to `config/blueprints/script/madalone/`
2. Create script: **Settings -> Automations & Scenes -> Scripts -> Add -> Use Blueprint**
3. Create the PIN helper: Settings -> Helpers -> Text (mode: password)
4. Create the PIN enabled toggle: Settings -> Helpers -> Toggle
5. Set the passphrase in the UI: Helpers -> AI Voice PIN -> "banana"

## Configuration

<details><summary>① Core configuration</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `satellite_entity` | _(required)_ | The voice satellite for the PIN challenge |
| `protected_script` | _(required)_ | The script entity to call on correct passphrase |
| `pin_entity` | `input_text.ai_voice_pin` | input_text storing the passphrase (mode: password) |
| `pin_enabled_entity` | `input_boolean.ai_voice_pin_enabled` | Toggle to enable/disable PIN protection |
| `max_attempts` | `2` | Maximum tries before lockout (1-5) |

</details>

<details><summary>② Messages</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `challenge_prompt` | `Please say your access code.` | Question asked on the first attempt |
| `retry_prompt` | `That's not right. Try again.` | Question asked on subsequent attempts |
| `success_message` | `Access granted.` | Announced when the correct passphrase is spoken |
| `failure_message` | `Access denied. Too many attempts.` | Announced when all attempts are exhausted |
| `cancel_message` | `Cancelled.` | Announced when the user cancels |

</details>

## Technical Notes

- **Mode:** `single` / `max_exceeded: silent`
- The `satellite_entity` is set per instance -- multi-satellite homes need one PIN script instance per satellite per action
- Use word-based passphrases ("banana", "open sesame"), not numeric PINs. STT may transcribe "1234" as "one thousand two hundred thirty-four"
- The challenge loop uses `repeat/until` with a compound exit condition: correct answer, cancel spoken, or max attempts reached
- Designed to chain: voice command -> `va_confirmation_dialog` (automation) -> `voice_pin_action` (PIN challenge) -> protected action script
- `continue_on_error` on `ask_question` ensures the loop handles timeouts gracefully

## Changelog

- **v1.0** -- Initial release

## Author

**madalone**

## License

See repository for license details.
