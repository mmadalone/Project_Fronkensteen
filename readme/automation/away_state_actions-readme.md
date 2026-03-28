![Away State Actions (I-40)](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/away_state_actions-header.jpeg)

# Away State Actions (I-40)

Per-person automation that fires on departure, arrival, predicted pre-return, and extended away events. Uses the I-40 away prediction engine for pre-return timing. Supports configurable departure debounce, confidence-gated pre-return actions, optional TTS announcements with away duration, and custom action blocks for each event type.

## How It Works

```
device_tracker entity
        |
        +-------+-------+--------+-----------+
        |       |       |        |           |
        v       v       v        v           v
   not_home   home   /5 min   not_home    (enable
   (+ delay)         pattern   (+ ext.    toggle
        |       |       |      minutes)    OFF)
        |       |       |        |           |
        v       v       v        v           v
  DEPARTURE  ARRIVAL  PRE-     EXTENDED    STOP
        |       |    RETURN      AWAY
        |       |       |        |
        v       v       v        v
  +--------+ +-----+ +------+ +------+
  | TTS?   | |Calc | |Parse | |Run   |
  | Depart | |away | |away  | |ext.  |
  | msg    | |dur. | |pred. | |away  |
  +--------+ +-----+ +------+ |acts  |
        |       |       |      +------+
        v       v       v
  +--------+ +-----+ +------+
  | Run    | |TTS? | |Conf. |
  | depart | |Arr. | |gate  |
  | actions| |msg  | +------+
  +--------+ +-----+    |
                |        v
                v   +--------+
           +-----+  |Time    |
           |Run  |  |window  |
           |arr. |  |check   |
           |acts |  +--------+
           +-----+      |
                         v
                    +--------+
                    |Run pre-|
                    |return  |
                    |actions |
                    +--------+
```

## Features

- Four event types: departure, arrival, pre-return, and extended away
- Configurable departure delay (1-30 min) to debounce WiFi flapping and router reboots
- Pre-return actions with confidence gating (low/medium/high) using I-40 prediction engine
- Optional pre-return range mode: use earliest predicted return (range_low) instead of point estimate
- Extended away threshold (30-1440 min) for deep eco mode or notification actions
- Optional TTS announcements on departure and arrival with template variables (`{{ person }}`, `{{ duration }}`)
- Away duration calculation from departure timestamp for arrival messages
- Per-instance kill switch via `input_boolean`
- Custom action blocks for each event type (use HA action selector)

## Prerequisites

- Home Assistant 2024.10.0+
- `device_tracker` entity for the target person
- `input_boolean` entity for the per-instance kill switch
- `input_text.ai_away_prediction_raw` (I-40 away prediction data, for pre-return)
- `input_datetime.ai_away_departed_<person>` (departure timestamp, for arrival duration)
- Media player entity (if TTS announcements enabled)

## Installation

1. Copy `away_state_actions.yaml` to `config/blueprints/automation/madalone/`
2. Create automation: **Settings -> Automations -> Create -> Use Blueprint**

## Configuration

<details><summary>① Tracking</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `person_tracker` | _(required)_ | device_tracker entity for the person to monitor |
| `enable_toggle` | _(required)_ | Per-instance kill switch (input_boolean) |

</details>

<details><summary>② Departure</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `departure_delay_minutes` | `5` | Minutes to wait after not_home before firing (debounce) |
| `departure_actions` | `[]` | Actions to run on departure |

</details>

<details><summary>③ Arrival</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `arrival_actions` | `[]` | Actions to run on arrival |

</details>

<details><summary>④ Pre-Return</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `pre_return_actions` | `[]` | Actions to run before predicted return |
| `pre_return_minutes` | `30` | Fire actions this many minutes before predicted return |
| `pre_return_min_confidence` | `medium` | Minimum prediction confidence (low/medium/high) |
| `pre_return_use_range` | `false` | Use earliest predicted return (range_low) instead of point estimate |

</details>

<details><summary>⑤ Extended Away</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `extended_away_actions` | `[]` | Actions to run after extended absence |
| `extended_away_minutes` | `240` | Fire after this many minutes away |

</details>

<details><summary>⑥ Announcements</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `announce_departure` | `false` | Speak TTS on departure |
| `announce_arrival` | `false` | Speak TTS on arrival (includes away duration) |
| `tts_speaker` | _(empty)_ | Media player for TTS announcements |
| `departure_message` | `{{ person }} has left home.` | TTS departure message template |
| `arrival_message` | `{{ person }} is back after {{ duration }} minutes.` | TTS arrival message template |

</details>

## Technical Notes

- **Mode:** `restart` (silent on exceeded) -- a new event cancels any in-progress action sequence
- **Pre-return polling:** Uses a 5-minute `time_pattern` trigger; only fires when the tracker is `not_home`, pre-return actions are configured, and the prediction data passes confidence and time-window checks
- **Person resolution:** Maps tracker entity IDs to person names via an embedded lookup map; falls back to titlecased entity ID suffix
- **Confidence mapping:** `low=1`, `medium=2`, `high=3` -- prediction must meet or exceed the configured minimum
- **Prediction parsing:** Reads `input_text.ai_away_prediction_raw` JSON, supports both single and multi-person prediction formats
- **Empty action guard:** All action blocks check `length > 0` before execution to skip gracefully when unconfigured

## Author

**madalone**

## License

See repository for license details.
