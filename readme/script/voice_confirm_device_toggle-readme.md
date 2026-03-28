![Voice -- Confirm Device Toggle (tool script)](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/voice_confirm_device_toggle-header.jpeg)

# Voice -- Confirm Device Toggle (tool script)

Ask for voice confirmation before toggling a device on or off. Uses `assist_satellite.ask_question` to present a yes/no dialog, then toggles the device and announces the result. Supports both on and off directions from a single blueprint -- create one instance per direction per satellite.

## How It Works

```
Start
  |
  v
+----------------------------+
| ask_question on satellite  |
| ("Are you sure?")          |
+----------------------------+
  |
  +------------+-------------+
  |            |             |
  v            v             v
 YES          NO         (timeout)
  |            |             |
  v            v             v
+--------+ +----------+ +----------+
| Toggle | | Announce | | Announce |
| device | | cancel   | | cancel   |
+--------+ +----------+ +----------+
  |
  v
+----------------------------+
| Announce confirmation      |
| ("Done.")                  |
+----------------------------+
```

## Features

- Voice confirmation dialog via `assist_satellite.ask_question`
- Supports both ON and OFF toggle directions from one blueprint
- Recognizes multiple affirmative phrases: yes, yeah, si, affirmative, sure, go ahead, do it
- Recognizes multiple negative phrases: no, nope, cancel, don't, never mind
- Customizable question, confirm, and cancel messages
- Designed to pair with the `va_confirmation_dialog` automation blueprint

## Prerequisites

- Home Assistant
- An `assist_satellite` entity (voice satellite with question support)
- A switchable entity (switch, light, etc.)

## Installation

1. Copy `voice_confirm_device_toggle.yaml` to `config/blueprints/script/madalone/`
2. Create script: **Settings -> Automations & Scenes -> Scripts -> Add -> Use Blueprint**

## Configuration

<details><summary>① Core configuration</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `target_entity` | _(required)_ | The switch/light/etc. entity to toggle |
| `toggle_direction` | `off` | Whether to turn the device ON or OFF when confirmed |
| `satellite_entity` | _(required)_ | The voice satellite for the confirmation dialog |

</details>

<details><summary>② Messages</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `question` | `Are you sure?` | The confirmation question asked before toggling |
| `confirm_message` | `Done.` | Announced when the user confirms |
| `cancel_message` | `Okay, cancelled.` | Announced when the user cancels or times out |

</details>

## Technical Notes

- **Mode:** `single` / `max_exceeded: silent`
- Create one instance per direction: e.g. `script.confirm_turning_off_madteevee` (direction: off) and `script.confirm_turning_on_madteevee` (direction: on)
- Uses `homeassistant.turn_off` / `homeassistant.turn_on` so it works with any entity domain that supports on/off
- The cancel branch handles both explicit "no" answers and timeouts (default branch)

## Changelog

- **v1.0** -- Initial release

## Author

**madalone**

## License

See repository for license details.
