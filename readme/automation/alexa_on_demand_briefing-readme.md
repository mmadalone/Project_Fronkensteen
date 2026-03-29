![Alexa On-Demand Briefing](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/alexa_on_demand_briefing-header.jpeg)

# Alexa On-Demand Briefing

Thin orchestration layer triggered by Alexa-exposed `input_boolean` entities. Two voice commands ("Alexa, turn on Briefing" / "Alexa, turn on Mail Status") toggle the trigger booleans; the blueprint auto-resets them, determines content mode, manages follow-me refcount bypass, and hands off to `pyscript.proactive_briefing_now` for TTS delivery. Deliberately minimal -- pyscript handles TTS routing, agent selection, ducking, and volume internally.

## How It Works

```
"Alexa, turn on Briefing"         "Alexa, turn on Mail Status"
        |                                   |
        v                                   v
+------------------+               +------------------+
| input_boolean ON |               | input_boolean ON |
+------------------+               +------------------+
        |                                   |
        +-----------------------------------+
                        |
                        v
               +-----------------+
               | Privacy gate    |
               +-----------------+
                        |
                        v
               +-----------------+
               | Auto-off trigger|
               | boolean         |
               +-----------------+
                        |
                        v
               +-----------------+
               | Person home     |
               | gate (optional) |
               +-----------------+
                        |
                        v
               +-----------------+
               | Claim follow-me |
               | bypass (if ON)  |
               +-----------------+
                        |
                        v
      +--------------------------------------+
      | pyscript.proactive_briefing_now      |
      | (sections, prompt, speaker, volume)  |
      +--------------------------------------+
                        |
                        v
               +-----------------+
               | Release follow- |
               | me bypass       |
               +-----------------+
```

## Features

- Two content modes: full briefing (configurable sections) or mail-only status
- Auto-off trigger booleans to prevent stuck-ON state
- Configurable briefing sections (CSV): greeting, weather, calendar, email, schedule, household, memory, media_today, media_tomorrow, media_weekly
- Custom LLM prompt override with `{content}` and `{context}` placeholders
- Jinja2 context template injection evaluated by HA before passing to pyscript
- Household entity monitoring (CSV entity IDs)
- Presence-based routing with follow-me bypass via refcount scripts
- Agent dispatcher toggle with manual pipeline fallback
- Optional person-home gate with multi-person support
- Privacy gate with tiered suppression (T1/T2/T3) and per-automation overrides

## Prerequisites

- Home Assistant 2024.10.0+
- Two Alexa-exposed `input_boolean` entities (briefing trigger and mail status trigger)
- `pyscript/proactive_briefing.py` (briefing delivery)
- Refcount bypass scripts (for follow-me bypass)
- Privacy gate helpers (if privacy gating enabled)

## Installation

1. Copy `alexa_on_demand_briefing.yaml` to `config/blueprints/automation/madalone/`
2. Create automation: **Settings -> Automations -> Create -> Use Blueprint**

## Configuration

<details><summary>① Trigger & Content</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `trigger_briefing` | _(required)_ | Alexa-exposed input_boolean for full briefing |
| `trigger_mail_status` | _(required)_ | Alexa-exposed input_boolean for mail-only briefing |
| `briefing_sections` | `greeting,weather,calendar,email,schedule,household,memory` | Comma-separated sections for full briefing |
| `mail_prompt` | `Summarize my current email status concisely.` | LLM prompt for mail status mode |
| `briefing_prompt` | _(empty)_ | LLM prompt override for full briefing |
| `context_template` | _(empty)_ | Jinja2 template evaluated before passing to pyscript |
| `household_entities` | _(empty)_ | CSV entity IDs for household section |

</details>

<details><summary>② Delivery</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `fallback_speaker` | _(required)_ | Speaker used when no presence detected or bypass ON |
| `tts_volume` | `0.0` | Volume for TTS delivery. 0 = let pyscript handle it |

</details>

<details><summary>③ Bypass Toggles</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `bypass_dispatcher` | `false` | Skip agent dispatcher; use manual pipeline |
| `bypass_follow_me` | `false` | Skip presence-based routing; use fallback speaker |
| `bypass_claim_script` | `script.refcount_bypass_claim` | Refcount bypass claim script |
| `bypass_release_script` | `script.refcount_bypass_release` | Refcount bypass release script |

</details>

<details><summary>④ Infrastructure</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `use_dispatcher` | `true` | Use agent dispatcher for persona selection |
| `conversation_agent` | `Rick` | Pipeline used when dispatcher is disabled |
| `person_required` | `false` | Only deliver if at least one listed person is home |
| `persons` | `[]` | Person entities for the person-home gate |
| `privacy_tier` | `t2` | Privacy gate tier (off/t1/t2/t3) |
| `privacy_gate_enabled` | `input_boolean.ai_privacy_gate_enabled` | Privacy gate toggle |
| `privacy_gate_mode` | `input_select.ai_privacy_gate_mode` | Privacy gate mode selector |
| `privacy_gate_person` | `person.miquel` | Person entity for tier suppression lookups |

</details>

## Technical Notes

- **Mode:** `queued` (max 3, silent on exceeded) -- handles rapid Alexa toggles gracefully
- **Content mode detection:** Uses `trigger.id` to determine briefing vs. mail mode
- **Briefing label:** Automatically set to `mail_status`, `morning`, `afternoon`, or `evening` based on trigger and time of day
- **Dispatcher bypass:** Both `bypass_dispatcher` and `use_dispatcher` inputs are combined -- bypass overrides dispatcher even when enabled
- **Follow-me bypass:** Uses refcount claim/release pattern to prevent stuck bypass states when multiple automations share the toggle
- **Error handling:** `continue_on_error: true` on pyscript calls and bypass operations

## Author

**madalone**

## License

See repository for license details.
