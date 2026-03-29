# Task: Runtime State Migration — Session 1 (LOW risk clusters)

## Context

Converting runtime state helpers (written by code, never by users) from `input_text`/`input_number` helpers to `state.set()` pyscript sensors. This is part of a multi-session migration plan.

Full migration plan: `_build_logs/2026-03-29_runtime_state_migration_plan.md`
Helper consolidation analysis: `_build_logs/2026-03-29_helper_elimination_analysis.md`

## This session: 2 clusters, 12 helpers

### Cluster A: Notification/email tracking (8 input_text)

| Helper | Writer | Reader |
|--------|--------|--------|
| `ai_notification_follow_me_bypass_log` | `refcount_bypass_claim.yaml` blueprint | `follow_me_refcount_watchdog.yaml` blueprint |
| `ai_notification_follow_me_ledger` | `notification_follow_me.yaml` blueprint | same blueprint |
| `ai_notification_last_announced_sender_name_rick` | `notification_follow_me.yaml` blueprint | same blueprint |
| `ai_notification_follow_me_reminder_loop_owner` | `notification_follow_me.yaml` blueprint | same blueprint |
| `ai_email_last_announce_sender` | `email_follow_me.yaml` blueprint | same blueprint |
| `ai_email_follow_me_dedup_uids` | `email_follow_me.yaml` blueprint | same blueprint |
| `ai_email_follow_me_last_subject` | `email_follow_me.yaml` blueprint | same blueprint |
| `ai_notification_follow_me_last_post_time` | `notification_follow_me.yaml` blueprint | same blueprint |

**Pattern:** All 8 are single-consumer — the same blueprint that writes also reads. They're passed as `!input` blueprint inputs and referenced by input variable names inside the blueprint, not by hardcoded entity IDs.

**Key challenge:** These are blueprint `!input` helpers — the blueprint declares an input of type `entity` (or `text`), the automation instance wires the helper entity to that input. Inside the blueprint, the helper is written via `input_text.set_value` targeting the `!input` variable.

**Conversion approach for blueprint-coupled helpers:**
Since the blueprint controls both read and write, the conversion happens INSIDE the blueprint:
1. The blueprint input stays as-is (still accepts an entity selector)
2. The writer changes from `input_text.set_value` → a pyscript bridge service OR the blueprint writes to the sensor directly
3. The reader changes entity ID in Jinja templates
4. The automation instance in `automations.yaml` changes the wired entity ID

**IMPORTANT:** For blueprint-coupled helpers, you CANNOT simply swap `input_text.set_value` to `state.set()` in YAML — blueprints don't have `state.set()`. You need ONE of:
- A `pyscript.set_sensor_value` bridge service that blueprints call via `action: pyscript.set_sensor_value` with `data: {entity_id: "sensor.ai_*", value: "..."}`
- OR keep these as helpers (they're internal to one blueprint — the helper is the simplest mechanism)

**Decision needed:** These 8 are tightly blueprint-coupled. The blueprint is both writer and reader. Converting them gains almost nothing (the entity is internal to one blueprint + one instance). Consider whether these are worth converting or should be reclassified as "blueprint-internal state" and kept.

### Cluster B: Goodnight negotiator state (3 input_text + 1 input_number)

| Helper | Writer | Reader |
|--------|--------|--------|
| `ai_gn_last_opening_line` | `goodnight_negotiator_hybrid.yaml` script blueprint | same blueprint |
| `ai_gn_last_question` | same | same |
| `ai_gn_last_reply` | same | same |
| `ai_gn_last_run_epoch` | same | same |

**Pattern:** Identical to Cluster A — single-consumer, blueprint-internal state. The script blueprint writes and reads all 4 via `!input` variables.

**Same decision needed:** These are blueprint-internal. Converting them requires a pyscript bridge service that the blueprint calls instead of `input_text.set_value`. The gain is architectural purity; the cost is adding a pyscript dependency to a self-contained blueprint.

## Pre-requisite: Bridge service

If you decide to proceed with conversion, create this pyscript service FIRST:

```python
@service
async def set_sensor_value(entity_id: str = "", value: str = "", icon: str = "", friendly_name: str = ""):
    """Bridge: allows blueprints to write state.set() sensors."""
    attrs = {}
    if icon:
        attrs["icon"] = icon
    if friendly_name:
        attrs["friendly_name"] = friendly_name
    state.set(entity_id, value=value, new_attributes=attrs if attrs else None)
```

File: `/config/pyscript/state_bridge.py`

Blueprints then call:
```yaml
- action: pyscript.set_sensor_value
  data:
    entity_id: "sensor.ai_notification_follow_me_ledger"
    value: "{{ new_ledger_value }}"
```

## Conversion steps per helper

1. **Grep for ALL references** — verify against the migration plan's verified consumer list
2. **Create the sensor** — add `state.set()` call in the writer (or pyscript startup handler for initial state)
3. **Update the writer** — `input_text.set_value` → `pyscript.set_sensor_value` (in blueprint) or `state.set()` (in pyscript)
4. **Update all readers** — entity ID swap in Jinja/conditions
5. **Update automation instance** — `automations.yaml` / `scripts.yaml` entity ID wiring
6. **Update dashboard** — `ai-dashboard.yaml` if referenced
7. **Update LCARS panel** — `lcars-panel.js` if referenced
8. **Remove from helper YAML** — `helpers_input_text.yaml` / `helpers_input_number.yaml`
9. **Verify** — `ha_check_config` → restart → check logs → trigger the feature

## Search paths (check ALL of these for each helper)

- Pyscript: `/config/pyscript/*.py` and `modules/shared_utils.py`
- Blueprints: `/config/blueprints/automation/madalone/*.yaml` and `/config/blueprints/script/madalone/*.yaml`
- Packages: `/config/packages/*.yaml`
- Automations: `/config/automations.yaml`
- Scripts: `/config/scripts.yaml`
- Dashboard: `/config/ai-dashboard.yaml`
- LCARS: `/config/www/lcars-panel/lcars-panel.js`
- Template: `/config/template.yaml`
- Custom components: `/config/custom_components/elevenlabs_custom_tts/tts.py`
- Agent prompts: check Extended OpenAI Conversation function specs

## Rules

- Follow the style guide (read `ha_style_guide_project_instructions.md` for BUILD mode)
- Create a build log before the first edit
- Research-first: check if any of these helpers have consumers the migration plan didn't catch
- No hacky solutions — if the bridge service pattern doesn't work cleanly, keep the helper
- Flag breaking changes before making them
- Verify config + restart + check logs after each cluster
- **CRITICAL:** If you determine that blueprint-internal helpers aren't worth converting (because the gain is minimal and the cost is a new pyscript dependency), SAY SO. Don't convert for the sake of converting. The goal is architectural purity, not busywork.
