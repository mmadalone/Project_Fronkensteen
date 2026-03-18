# AI Escalation — Agent Threat Follow-Through

Helpers and status sensor for the agent escalation system (I-23). When voice agents make threats or promises, this system probabilistically decides whether to follow through. Supports 7 action types, each with independent probability overrides, plus a global cooldown gate.

## What's Inside

- **Template sensors:** 1 (`sensor.ai_escalation_status`)
- **Input helpers:** 12 (moved to consolidated helper files) -- 1 boolean, 9 numbers, 1 text, 1 datetime

## Entity Reference

| Entity ID | Type | Purpose |
|---|---|---|
| `sensor.ai_escalation_status` | template sensor | Dashboard status: last outcome, probabilities, cooldown, enabled state |
| `input_boolean.ai_escalation_enabled` | input_boolean | Master toggle |
| `input_number.ai_escalation_probability` | input_number | Global fallback probability (%) |
| `input_number.ai_escalation_cooldown_minutes` | input_number | Cooldown gate between escalations |
| `input_number.ai_escalation_prob_persona_switch` | input_number | Per-type probability: persona switch (-1 = use global) |
| `input_number.ai_escalation_prob_play_media` | input_number | Per-type probability: play media |
| `input_number.ai_escalation_prob_light_flash` | input_number | Per-type probability: light flash |
| `input_number.ai_escalation_prob_volume_boost` | input_number | Per-type probability: volume boost |
| `input_number.ai_escalation_prob_send_notification` | input_number | Per-type probability: send notification |
| `input_number.ai_escalation_prob_prompt_barrage` | input_number | Per-type probability: prompt barrage |
| `input_number.ai_escalation_prob_run_script` | input_number | Per-type probability: run script |
| `input_text.ai_escalation_last_outcome` | input_text | Last escalation event outcome |
| `input_datetime.ai_escalation_last_followthrough` | input_datetime | Cooldown timestamp |

## Dependencies

- **Blueprint:** `agent_escalation.yaml` (per-satellite event-triggered automation)
- **Pyscript:** `pyscript/agent_dispatcher.py` (for `dispatcher_resolve_engine` in prompt barrage)
- **Voice agents:** Extended OpenAI agents must have the `escalate_action` tool function added via HA UI

## Cross-References

- **Blueprint:** `agent_escalation.yaml` -- reads all helpers from this package for probability/cooldown decisions
- **Blueprint:** `voice_handoff.yaml` -- persona switch action reuses handoff by setting `ai_handoff_pending`
- **Voice agents:** The `escalate_action` LLM tool fires events consumed by the blueprint

## Notes

- Per-type probability of `-1` means "use global fallback." A value of `0` means always bluff (never follow through). `1-100` is the type-specific probability.
- The 7 action types are: `persona_switch`, `play_media`, `light_flash`, `volume_boost`, `send_notification`, `prompt_barrage`, `run_script`.
- Prompt barrage uses embedded per-agent prompt pools, resolves the engine via dispatcher, runs `conversation.process`, and speaks the result in the target agent's voice.
- Deployed as part of I-23 (2026-03-07).
