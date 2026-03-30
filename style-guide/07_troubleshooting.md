# Home Assistant Style Guide — Troubleshooting & Debugging

Section 13 — Trace reading, Developer Tools, common failure modes, log analysis, and domain-specific debugging.

---

## 13. TROUBLESHOOTING & DEBUGGING

### 13.1 Automation traces — your first stop

Traces are the single most useful debugging tool in HA. Every automation run records a step-by-step execution trace showing exactly what happened, what values were evaluated, and where things went wrong.

**Accessing traces:**
- Settings → Automations → click the automation → Traces (top-right clock icon)
- Or: Developer Tools → States → find the automation entity → check `last_triggered`

**What each trace node tells you:**

| Node color | Meaning |
|---|---|
| **Green** | Step executed successfully |
| **Gray** | Step was skipped (condition failed, `choose` branch not taken) |
| **Red** | Step threw an error |
| **No node at all** | Execution never reached this step — something above it stopped the run |

**Reading a trace effectively:**

1. **Start at the trigger node.** Verify it fired for the reason you expected. Click it to see `trigger.to_state`, `trigger.from_state`, and any `trigger.id`. If the trigger data looks wrong, the problem is upstream of your automation.

2. **Check the condition node.** If it's gray, your conditions blocked the run. Click it to see each individual condition's result — HA shows `true`/`false` per condition. This is where 90% of "my automation never runs" issues die.

3. **Walk the action nodes in order.** Each green node shows the data it was called with — expand it to verify entity IDs, action data, and template evaluations resolved correctly. If a node is green but the result wasn't what you expected, the action succeeded but your *data* was wrong.

4. **Check `choose`/`if` branches.** The trace shows which branch was taken (green) and which were skipped (gray). If the wrong branch fires, click the condition node on each branch to see why.

5. **Look at the `changed_variables` section** at the top of the trace. This shows every variable and its resolved value at the start of the run — invaluable for catching template evaluation issues.

**Increasing trace history:**

The default is 5 stored traces. During active development, bump it up per automation:

```yaml
automation:
  - alias: "My automation"
    trace:
      stored_traces: 20
    triggers:
      # ...
```

> **Note:** `stored_traces` is configured *inside* each automation definition, not as a standalone top-level block. There is no global setting — each automation must be configured individually.

Reduce back to 5–10 once stable. Each trace consumes memory, and HA doesn't persist them across restarts.

### 13.2 Quick tests from the automation editor

Before diving into traces or Developer Tools, use the built-in testing features in the automation editor itself:

**Run Actions button (three-dot menu → Run actions):**
Executes all actions in the automation, **skipping all triggers and conditions**. Useful for verifying your action sequence works in isolation. Note: automations that depend on `trigger.id`, trigger variables, or data from previous `choose` branches won't work correctly this way — those values are undefined during a manual run.

**Per-step testing (visual editor only):**
In the automation editor UI, each individual condition and action has its own three-dot menu with a test option:
- **Testing a condition** highlights it green (passed) or red (failed) based on current HA state — invaluable for catching logic errors without triggering the full automation.
- **Testing an action** executes just that single action step.
- For compound conditions (e.g., `and` blocks), you can test the whole block or drill into individual sub-conditions.

**Automation: Trigger via Developer Tools:**
Developer Tools → Actions → search for "Automation: Trigger" → pick your automation. This method lets you choose whether to **skip or evaluate conditions**, giving you more control than the editor's "Run Actions" button. You can also pass additional trigger data in YAML mode for testing specific trigger scenarios.

### 13.3 Developer Tools patterns

**States tab — check entity values before assuming:**

Before debugging an automation, verify the entities it depends on are in the state you think they're in. Common surprises:
- Entity shows `unavailable` (device offline, integration error)
- Entity shows `unknown` (just restarted, integration hasn't polled yet)
- Attribute you're reading doesn't exist on that entity (wrong entity type)
- State value is a string `"25.3"`, not a number — your template needs `| float`

**Pro move:** Filter by typing the entity ID prefix. `binary_sensor.motion` shows all motion sensors instantly.

**Actions tab — test actions in isolation:**

Before embedding an action in an automation, test it here first:
1. Pick the action (e.g., `light.turn_on`)
2. Fill in the target and data
3. Click "Perform action"
4. Check if the device actually responded

This eliminates the "is my automation wrong or is the device not responding?" question in one step.

> **Terminology note (HA 2024.8+):** The Developer Tools tab formerly called "Services" is now called "Actions." The YAML key `service:` was replaced by `action:`. Old `service:` syntax still works but all new code should use `action:`.

**Template tab — the Jinja2 playground:**

Test any template expression live against your current HA state:

```jinja2
{# Paste this in the Template editor to debug #}
Entity state: {{ states('sensor.temperature') | default('unknown') }}
As float: {{ states('sensor.temperature') | float(0) }}
Attribute: {{ state_attr('light.workshop', 'brightness') | default('no brightness attr') }}
Last triggered: {{ states.automation.coming_home.attributes.last_triggered | default('never') }}
Time since: {{ (now() - states.automation.coming_home.attributes.last_triggered | default(now(), true)).total_seconds() }}
```

The right pane updates in real time as you type. Use this to verify every template expression before putting it in a blueprint.

**Events tab — watch triggers fire in real time:**

1. Subscribe to `state_changed` and filter by your entity to watch state transitions.
2. Subscribe to `call_service` to see what actions are being called and by whom.
3. Subscribe to `automation_triggered` to see which automations are firing and why.

This is essential for debugging "the automation triggers too often" or "something keeps turning my lights on" problems.

### 13.4 The "why didn't my automation trigger?" flowchart

Work through this in order. Stop at the first failure — that's your bug.

**Step 1 — Is the automation enabled?**
- Settings → Automations → check the toggle. Disabled automations don't trigger.
- Also check: `Developer Tools → States → automation.your_automation` — state should be `on`.

**Step 2 — Did the trigger event actually happen?**
- Check the entity's state history (click the entity → History).
- For state triggers: did the entity actually transition from → to the states you specified?
- For `for:` duration triggers: did the entity stay in that state for the full duration without bouncing?
- For time triggers: is HA's timezone correct? (Settings → General → Time Zone)

**Step 3 — Did conditions block the run?**
- Look at the automation's trace. If there's a trace with a gray condition node, conditions blocked it.
- Click the condition node to see which specific condition returned `false`.
- Common traps:
  - `condition: state` comparing against `"on"` (string) when the state is `"On"` or `"ON"` (case sensitive).
  - `condition: numeric_state` when the entity is `unavailable` — numeric conditions fail on non-numeric states.
  - `condition: time` with `before`/`after` that crosses midnight (use two conditions OR a template).
  - GPS bounce cooldown (§5.5) blocking a legitimate trigger because the last one was too recent.

**Step 4 — Is the automation in `single` mode and already running?**
- If `mode: single` (the default), a trigger while the automation is already running is silently dropped. No trace, no log, nothing.
- Check: is there a long-running `wait_for_trigger` or `delay` in the automation that's holding it open?
- Fix: Change to `mode: restart` if a new trigger should interrupt the current run, or `mode: queued` if events should stack.

**Step 5 — Is the automation disabled by an error?**
- After certain errors, HA may disable an automation. Check the logs for `Setup of automation <name> failed`.
- Invalid YAML, broken templates, or references to non-existent entities can cause this.
- Fix the error and reload automations (Developer Tools → YAML → Reload Automations).

**Step 6 — Is it a blueprint input resolution failure?**
- If a blueprint `!input` reference points to an entity that no longer exists (renamed, deleted, re-paired), the automation may fail silently at setup.
- Check: Settings → Automations → click the automation → verify all inputs have valid values.
- Symptom: the automation appears enabled but never triggers and produces no traces.

### 13.5 Common failure modes and symptoms

Each failure mode maps to one or more anti-patterns from §10. The `AP-XX` references help you connect symptoms to root causes and prevention rules.

**"Template evaluates to empty string"** — *see AP-16*

Symptom: Action runs but does nothing. Target entity is blank. No error in logs.

Cause: A template variable resolved to `''` because the entity was `unavailable` or the `| default()` fell through to an empty string.

Diagnosis: Check the trace's `changed_variables` — look for any variable that's `''`, `None`, or `unknown`.

Fix: Add explicit guards:
```yaml
- alias: "Skip if target entity is empty"
  condition: template
  value_template: "{{ target_entity | default('') | length > 0 }}"
```

**"Action targets wrong entity"** — *see AP-02*

Symptom: The wrong light turns on, the wrong speaker plays music.

Cause: Usually a list-index mismatch in paired-list patterns (§7.5, §7.6). Alexa player list and MA player list are in different orders.

Diagnosis: Check the trace — expand the action node and look at `target.entity_id`. Is it the entity you expected?

Fix: Verify paired lists are in the same order. Add a `logbook.log` or `system_log.write` step before the action that prints the resolved target for debugging. (`logbook.log` writes to the Activity panel; `system_log.write` writes to `home-assistant.log` — use whichever suits your workflow.)

**"Automation fires twice"** — *see AP-23*

Symptom: Lights toggle on then immediately off. TTS speaks the same message twice. 

Cause: Multiple triggers matching the same event. Common with `state` triggers that don't specify `from:` — they fire on ANY state change, including attribute-only changes.

Diagnosis: Check the automation's trace list — are there two traces within seconds of each other?

Fix: Add `from:` and `to:` to state triggers. Or add `not_from:` / `not_to:` with `['unavailable', 'unknown']` to filter out transient states:

```yaml
triggers:
  - trigger: state
    entity_id: binary_sensor.motion
    from: "off"
    to: "on"
```

**When `from:`/`to:` isn't an option:** Some sensors (e.g., Android Companion App `last_notification`) carry meaningful data in attributes (`post_time`) while the state text may repeat across different notifications (e.g., "📷 Photo"). Adding `from:`/`to:` would break the trigger. In these cases, add a **post-trigger dedup gate** that compares a unique attribute (like `post_time`) against previously processed values — see `notification_follow_me.yaml` §2c (v3.19.0) for an example using the ledger as the dedup source.

**"Action succeeds but device doesn't respond"**

Symptom: Trace shows green (success) on the action, but the physical device didn't do anything.

Cause: HA acknowledged the action, but the device is offline, unreachable, or the integration has a stale connection.

Diagnosis:
1. Try the same action in Developer Tools → Actions. Same result?
2. Check the device's entity state — is it `unavailable`?
3. Check the integration's config entry — is it in an error state?

Fix: This is a device/integration issue, not an automation issue. Check the device's connectivity, restart the integration, or power-cycle the device.

**"Variable has stale value inside repeat loop"** — *see §3.4 caveat*

Symptom: A `repeat` loop does the same thing every iteration despite the state changing between iterations.

Cause: Top-level variables are evaluated once at automation start, not per-iteration (see §3.4 caveat).

Fix: Define a local `variables:` block inside the `repeat.sequence`:
```yaml
repeat:
  count: 5
  sequence:
    - variables:
        current_temp: "{{ states('sensor.temperature') | float(0) }}"
    - alias: "Act on current temperature"
      # current_temp is fresh each iteration
```

**"`wait_for_trigger` hangs forever"** — *see AP-04, AP-20*

Symptom: Automation starts, reaches a `wait_for_trigger`, and never continues. Eventually the timeout fires (if you have one — and you damn well better per §5.1).

Cause: The entity was already in the target state when the wait started. `wait_for_trigger` waits for a *transition*, not a *condition* (see §5.1).

Fix: Add a pre-check before the wait:
```yaml
- if:
    - condition: state
      entity_id: !input door_sensor
      state: "on"
  then:
    - alias: "Already in target state — skip wait"
  else:
    - alias: "Wait for state transition"
      wait_for_trigger:
        - trigger: state
          entity_id: !input door_sensor
          to: "on"
      timeout: ...
      continue_on_timeout: true
```

### 13.6 Log analysis

**Configuring targeted logging:**

Don't turn on `DEBUG` for everything — it'll flood your logs and tank performance. Target specific integrations:

```yaml
# In configuration.yaml
logger:
  default: warning
  logs:
    # Automation execution
    homeassistant.components.automation: info

    # Blueprint/script issues
    homeassistant.components.script: info

    # Music Assistant
    custom_components.music_assistant: debug

    # Extended OpenAI Conversation
    custom_components.extended_openai_conversation: debug

    # ESPHome device communication
    homeassistant.components.esphome: info

    # Template rendering errors
    homeassistant.helpers.template: warning
```

Reload after changes: Developer Tools → YAML → Reload Logger.

**What to look for in logs:**

| Log pattern | What it means |
|---|---|
| `Error while executing automation` | Action threw an exception — check the full traceback |
| `Setup of automation X failed` | YAML parse error or invalid entity reference — automation is dead until fixed |
| `Template X resulted in: None` | Template returned nothing — missing `| default()` |
| `Entity not found: sensor.xxx` | The entity doesn't exist — renamed, deleted, or integration not loaded |
| `Timeout while executing action call` | The device didn't respond within HA's internal timeout |
| `Already running` | `single` mode automation was triggered while still executing |
| `Exceeded maximum` | `queued`/`parallel` mode hit `max:` limit — triggers being dropped |

**Reading logs from the command line (HA OS):**

```bash
# SSH into HA OS, then:
ha core logs --follow           # Live stream
ha core logs | grep automation  # Filter for automation issues
ha core logs | grep -i error    # All errors
```

**Reading logs from the UI:**

Settings → System → Logs. Use the search box to filter. The "Show raw logs" toggle gives you the full traceback instead of the summarized version.

> **Terminology note (HA 2025.10+):** The UI "Logbook" panel has been renamed to **"Activity"**. The underlying YAML action `logbook.log` and integration name `logbook:` in `configuration.yaml` remain unchanged. When referring users to the UI, say "Activity panel"; when writing YAML, continue using `logbook.log` and `logbook:`.

#### 13.6.1 AI log file access protocol (MANDATORY)

Never load entire log files into context — `home-assistant.log` can be tens of thousands of lines and will obliterate your token budget.

1. **Start with `tail`** — read the last 50–100 lines. The problem is almost always at the end.
2. **Use `grep` / `search_files`** to find specific error keywords, entity IDs, or automation names before reading surrounding context.
3. **Read surgically** — when a relevant section is found, read only that section ± 10 lines for context.
4. **Refine, don't expand** — if the first search doesn't find the issue, adjust search terms. Never fall back to reading the whole file.

Common HA log path: `home-assistant.log` in the HA config directory.

> **For long-running automations** (bedtime routines, multi-stage sequences, etc.), don't try to catch everything in one read — see §13.6.2 for the round-based live troubleshooting protocol.

#### 13.6.2 Live troubleshooting protocol — long-running automations (MANDATORY)

Automations that take minutes to complete — bedtime routines, multi-stage sequences, follow-me orchestrations, media handoff chains — require a different debugging rhythm. The AI cannot watch logs in real time, cannot poll, and cannot detect when an automation finishes. Attempting to do so produces stale reads, incomplete data, and wasted turns.

**Work in rounds, not in a single pass.**

**Round structure:**

1. **Establish a baseline before triggering.** Grep the log for the automation's entity ID or alias name. Note the last timestamp associated with it. This is your "before" marker — everything after it belongs to the current run.

   ```bash
   grep -n "bedtime_routine" home-assistant.log | tail -5
   ```

2. **User triggers the automation.** The AI does not read the log during this step. Hands off the wheel.

3. **Wait for user confirmation.** The user says "it's done," "it failed at step X," or "I got an error on screen." Do not assume completion based on elapsed time — some automations have variable-length waits, user interactions, or LLM round-trips that make duration unpredictable.

4. **Read from the baseline timestamp forward.** Use grep or line ranges scoped to the automation's entity ID or alias. Pull only new entries related to the run.

   ```bash
   # From the baseline line number forward, filtered to the automation
   grep "bedtime_routine" home-assistant.log | awk 'NR > <baseline_line>'
   ```

5. **Repeat for distinct phases.** If the automation has clearly separated stages (e.g., "music selection → playback → TTS goodnight → lights off"), run a round per phase when granular diagnosis is needed. Ask the user to signal phase transitions if possible.

**Hard rules:**

- **Never poll the log in a loop.** Claude cannot watch in real time. Repeated reads on a timer waste tool calls and produce duplicate or incomplete data.
- **Never assume the automation is finished.** Always wait for the user to confirm. A 30-second automation might take 3 minutes if an LLM call is slow or a device is unresponsive.
- **Ask the user for on-screen errors first.** HA notification banners, persistent notifications, and toast messages are often faster and more specific than anything in the log. If the user says "I got a red banner that said X," that's your diagnosis — don't go log diving for what they already told you.
- **Check traces before logs.** Per §13.1, the automation trace shows step-by-step execution with resolved values. For most failures, the trace tells you *what* broke. The log tells you *why* the underlying integration or device failed. Trace first, log second.

**Anti-pattern this prevents:**

Without this protocol, the AI tends to read the log immediately after triggering, gets a partial picture (the automation is still running), draws wrong conclusions, and then reads again after the user reports a problem — now confused by entries from two different reads mixed together. The round-based approach keeps each read clean, scoped, and tied to a known automation state.

**Cross-references:** §13.6.1 (log access mechanics — tail, grep, surgical reads), §13.1 (traces as first stop), §5.1 (timeouts — long-running automations must always have them).

### 13.7 Debugging Music Assistant issues

**"Music doesn't play after `music_assistant.play_media`"**

Diagnosis checklist:
1. Is the MA player entity `available`? (Check Developer Tools → States)
2. Is the MA server running? (Settings → Integrations → Music Assistant → check status)
3. Did you use `music_assistant.play_media` or the generic `media_player.play_media`? (§7.2 — use the MA-specific one)
4. Does the `media_id` exactly match what MA knows? Try searching in the MA UI first.
5. Is `media_type` correct? An album name passed with `media_type: track` will fail to resolve.

**"Volume doesn't restore after TTS"**

Diagnosis checklist:
1. Is the ducking system stuck? Two mechanisms exist:
   - **Legacy blueprints:** Check `input_boolean.voice_pe_ducking` — if stuck ON, the volume restore step errored or the automation was killed mid-duck.
   - **Pyscript orchestration:** Check `duck_manager.py` reference count via `ai_duck_*` helper states. The duck manager uses reference counting — if the count is > 0 after all TTS has finished, a caller didn't release its duck. See §13.11 "Duck manager stuck" for recovery.
2. Is the `post_tts_delay` long enough? ElevenLabs streams asynchronously — if the delay is too short, volume restores while TTS is still playing (§7.4).
3. Check the automation trace — did the restore step actually fire? If the automation errored or timed out between duck and restore, volume stays ducked.

Manual recovery:
```yaml
# In Developer Tools → Actions:
action: input_boolean.turn_off
target:
  entity_id: input_boolean.voice_pe_ducking
# Then manually set the volume back
```

If using the pyscript duck manager, also reset the reference count:
```yaml
# In Developer Tools → Actions:
action: input_number.set_value
target:
  entity_id: input_number.ai_duck_ref_count
data:
  value: 0
```

**"Volume sync keeps firing / feedback loop"**

Symptom: Volume changes rapidly between two values, logs show volume sync automation firing repeatedly.

Cause: The tolerance threshold is too tight, or the ducking flag isn't being checked. Two volume-change events bounce back and forth forever.

Fix:
1. Increase the tolerance threshold (the minimum difference that triggers a sync). 0.02 (2%) is usually the floor.
2. Verify the ducking flag check is in the conditions (§7.4).
3. Add a short cooldown delay at the end of the sync automation to absorb rounding-induced re-triggers.

```yaml
# In the volume sync automation conditions:
conditions:
  - alias: "Ducking not active"
    condition: state
    entity_id: input_boolean.voice_pe_ducking
    state: "off"
  - alias: "Volume difference exceeds tolerance"
    condition: template
    value_template: >-
      {{ (state_attr(source_player, 'volume_level') | float(0)
          - state_attr(target_player, 'volume_level') | float(0))
         | abs > 0.02 }}

# At the end of the sync action sequence:
  - alias: "Cooldown — absorb rounding re-triggers"
    delay:
      seconds: 2
```

### 13.8 Debugging ESPHome devices

**"ESPHome device shows as unavailable in HA"**

Diagnosis:
1. Can you reach the device's web server? `http://<device-ip>/` (if web_server is enabled, §6.6).
2. Can you ping it? `ping <device-ip>`
3. Check ESPHome dashboard — is the device showing as online?
4. Check HA logs for `esphome` entries — look for connection refused, timeout, or API key mismatch errors.

Common causes:
- WiFi signal too weak — check `sensor.xxx_wifi_signal` if you have a WiFi signal sensor (§6.7).
- API encryption key mismatch — the key in HA doesn't match the one on the device. Re-adopt the device in ESPHome dashboard.
- Device ran out of memory (heap) — check heap free sensor. Below 20KB is trouble.
- mDNS not working — some routers/VLANs block mDNS. Use a static IP in the ESPHome wifi config.

**"ESP device keeps crashing / rebooting"**

Diagnosis:
1. Check HA core logs for crash reports: `ha core logs | grep -i "esphome.*crash"`. Look for `*** CRASH DETECTED ON PREVIOUS BOOT ***` — this is the ESP reporting what happened on its last boot.
2. Identify the fault type from the log:
   - **`LoadProhibited`** — null pointer dereference or invalid memory read. Most common ESP32 crash. Often caused by accessing freed memory, stack overflow, or firmware bugs.
   - **`StoreProhibited`** — invalid memory write. Similar causes to LoadProhibited.
   - **`InstrFetchProhibited`** — code execution from invalid address. Usually stack corruption or buffer overflow.
3. Check heap trend: monitor `sensor.ha_voice_XX_heap_free` over time. A steady decline indicates a memory leak. Below 20KB is danger zone.
4. Check for recurring `sendspin.ws_server` errors: `ha core logs | grep sendspin`. The error `"No connection found for sockfd XX"` at regular intervals (~56 min) indicates the ESP-IDF httpd websocket keepalive race condition — a stale connection cycling. Not a crash itself but can contribute to memory pressure over time.
5. Check for `[W][micro_wake_word:356]: Wake word detection is already running` — benign warning after reboot when HA sends a start command but the device already auto-started.

Common causes:
- **Firmware regression** — ESPHome 2026.3.0 had a `web_server` stack overflow (esphome#14991) that crashed devices every 60-90s. Check your ESPHome version via `update.ha_voice_XX_firmware`.
- **Custom wake word HTTP loading** — if models reference `http://homeassistant.local:8123/...`, the ESP depends on HA being reachable at boot. During HA restarts, model loading can fail and trigger null pointer faults. **Fix:** use local model files (§6.5).
- **Sendspin websocket memory leak** — Voice PE firmware's Sendspin web server can leak memory through stale websocket connections. Fixed in Voice PE firmware 26.3.0 (esphome/home-assistant-voice-pe#562).
- **Simultaneous HA + ESP restart** — if HA restarts while the ESP is reconnecting, both devices can enter a race condition. `fast_connect: true` in WiFi config (§6.10) reduces reconnection time.

Recovery: If crashes are persistent, get the backtrace from the crash log and use `addr2line` against the firmware ELF to identify the crashing function. The crash log includes the command: `addr2line -pfiaC -e firmware.elf <addresses>`. The ELF file is in `.esphome/build/<device>/.pioenvs/<device>/firmware.elf`.

**"Wake word not triggering"**

Diagnosis:
1. Check the Voice PE satellite's state in HA — is it `idle` (listening) or `unavailable`?
2. Check the ESPHome logs (ESPHome dashboard → Logs) for microphone activity. You should see wake word processing logs.
3. Is the custom model file accessible? For local files, verify the `.json` and `.tflite` files exist in `/config/esphome/`. For HTTP models (not recommended — see §6.5), try navigating to the URL in a browser.
4. Is the microphone physically working? Check if the on-device voice activity detection (VAD) is triggering.

**"OTA update fails"**

Common causes:
- Device is unreachable (see unavailable diagnosis above).
- Not enough free heap/flash — large configs with many components can run out of space.
- OTA password mismatch — check `!secret ota_password` matches in both ESPHome secrets and the device's compiled firmware. Note: OTA **MD5** password auth was removed in ESPHome 2026.1.0 (passwords now require SHA256). If you're on 2026.1.0+ and OTA fails with an auth error, ensure your password config uses SHA256 (the new default) or remove the password and rely on API encryption key auth.
- For ESPHome 2024.6+: missing `platform: esphome` in the OTA config (§6.6).

### 13.9 Debugging conversation agents

**"Agent doesn't call the right action / uses wrong entity"**

Diagnosis:
1. Check the tool/script descriptions (§8.3.2). Is the description clear enough for the LLM to pick the right tool?
2. Check the PERMISSIONS table in the system prompt — is the entity listed? Is the action listed?
3. Check the integration's debug logs (Extended OpenAI Conversation, etc.) — most log the full LLM request/response including tool calls.

Fix: Make tool descriptions more explicit. Instead of "controls lights", write "turns on the workshop ceiling lights. Call this when the user says 'turn on the lights', 'lights on', or 'I need light'."

**"Agent prompt templates aren't rendering correctly"**

Diagnosis: If your conversation agent system prompt uses Jinja2 templates (e.g., `{{ states('sensor.x') }}` in `extra_system_prompt`), test them in **Developer Tools → Template** first. Paste the template portion and verify it renders the values you expect against current HA state. This is the fastest way to catch template syntax errors, missing `| default()` guards, and entity reference typos in agent prompts — without waiting for a full conversation round-trip.

**"Agent hallucinates entity IDs or actions"**

Cause: The system prompt doesn't explicitly constrain the agent, or the PERMISSIONS table is missing/incomplete.

Fix:
1. Add the explicit constraint: "You are NOT allowed to control any devices outside this list."
2. Make sure every entity the agent should use is in the PERMISSIONS table with exact entity IDs.
3. Reduce exposed tools to only what's needed — fewer options means fewer hallucination targets (§8.3.2).

**"Agent responds but no action happens"**

Diagnosis:
1. Check the integration's logs — did the LLM actually generate a tool/function call, or just text?
2. If it generated a tool call, check: did the tool call succeed? Look for errors in the response.
3. If the tool call succeeded, check the underlying automation/script's trace — did IT work?

This is a three-layer debug: LLM → tool/script → device. Work from the top down.

**"Agent responds but the wrong persona / wrong voice / wrong context"**

Symptom: You said "Hey Rick" but got Quark's personality, or the agent responded without time-of-day context, or bedtime tools appeared during daytime.

Diagnosis — check the pyscript orchestration layer:

1. **Was the dispatcher routing correctly?** Check pyscript logs for the last `agent_dispatch` call. Look for the routing decision chain: explicit name → wake word → continuity → topic keywords → era → fallback. If the wrong level won, the dispatcher's input data was wrong (stale era helper, wrong wake word mapping, etc.).
   ```bash
   grep "agent_dispatch" home-assistant.log | tail -10
   ```
2. **Was an unexpected handoff triggered?** Check `voice_handoff` logs (blueprint + pyscript `voice_handoff.py`). If the previous conversation triggered the `handoff_agent` LLM tool, the handoff blueprint may have switched the satellite's pipeline to the wrong persona. (`agent_handoff.py` was archived — superseded by `voice_handoff.yaml` / I-24.)
   ```bash
   grep "voice_handoff" home-assistant.log | tail -10
   ```
3. **Is the whisper network interfering?** `agent_whisper.py` auto-updates dispatcher topic keywords from conversation content. If a conversation about cooking got tagged with keywords that now route to the wrong agent, the keyword table has drifted.
4. **Is the L1 hot context stale?** Check `sensor.ai_hot_context` in Developer Tools → States. If it shows wrong time-of-day data, wrong presence zone, or wrong identity confidence, every agent downstream gets wrong context.
5. **Is the voice profile mismatched?** If using loryanstrant voice profiles, check whether `tts_queue.py` resolved the correct time-based profile. A wrong profile means the right text in the wrong voice.

This is a five-layer debug when the orchestration layer is involved: wake word → dispatcher → agent → pyscript context injection → TTS/voice profile. Work from the top down.

### 13.10 The nuclear options — escalation ladder

When nothing else works, escalate one step at a time. **Never skip levels** — each step is more disruptive than the last.

| Level | Action | Disruption | When to use |
|-------|--------|------------|-------------|
| **1** | **Reload automations** — Developer Tools → YAML → Reload Automations | ⭐ None — re-parses YAML, no downtime | Changed automation YAML, need HA to pick it up |
| **1.5** | **Reload pyscript** — Developer Tools → Actions → `pyscript.reload` | ⚠️ **Resets in-memory state** — pending queue items, active duck counts, and write batches are lost | Changed a `.py` file in `pyscript/`, service isn't registering, or pyscript module is in a bad state |
| **2** | **Reload specific component** — Developer Tools → YAML → individual reload buttons (scripts, scenes, groups, input helpers, etc.) | ⭐ None — targeted reload | Changed scripts, helpers, or scene definitions |
| **3** | **Check config validity** — Developer Tools → YAML → Check Configuration | ⭐ None — read-only validation | **Always run this before level 4+.** A YAML error can prevent HA from starting. (Button requires Advanced Mode: Settings → People → your user → Advanced Mode toggle) |
| **4** | **Restart Home Assistant** — Settings → System → Restart | ⚠️ **1–5 min downtime** — all automations stop, integrations reconnect | Reload didn't fix it, integration is stuck, entity won't update |
| **5** | **Hard restart (HA OS)** — SSH in, run `ha core restart` | ⚠️ **1–5 min downtime** — same as above but bypasses unresponsive UI | UI is frozen/unresponsive, can't reach restart button |
| **6** | **Restore from backup** | ❌ **Destructive** — rolls back ALL changes since backup | Everything is worse after restart. Last resort. Try to undo changes manually first (§11). |

**Rule of thumb:** Start at level 1. Move to the next level only if the previous one didn't fix it. And always pass through level 3 before hitting level 4+, or you might be staring at a boot loop like a damn Ferengi who forgot to read the fine print.

> For pyscript-specific issues, try level 1.5 before level 4. A pyscript reload is much faster than a full HA restart and resolves most module-level problems. But be aware it resets all in-memory state — check §13.11 for what's affected.

### 13.11 Debugging pyscript modules

The pyscript orchestration layer (550KB, 15 modules) runs inside HA's Python runtime but has no automation trace visibility. When pyscript fails, there are no trace nodes, no gray/green/red indicators, and often no visible error. Debugging requires a different approach than YAML automations.

**Enabling pyscript logging:**

```yaml
# In configuration.yaml
logger:
  logs:
    custom_components.pyscript: info        # General pyscript runtime
    custom_components.pyscript.eval: info    # Script evaluation (function calls, service dispatch)
    custom_components.pyscript.trigger: debug # Trigger evaluation (only enable temporarily — verbose)
```

Reload after changes: Developer Tools → YAML → Reload Logger.

**"Pyscript service call does nothing"**

This is the most common and most frustrating pyscript failure. The YAML calls `pyscript.some_service`, HA accepts it, pyscript receives it, and... nothing happens. No error, no log, no trace.

Diagnosis:
1. **Does the service exist?** Developer Tools → Actions → search for `pyscript.`. If your service isn't listed, it's not registered — either the module isn't loaded, or the function lacks `@service`.
2. **Are the parameters correct?** The most common cause. Pyscript doesn't validate parameter names — if you pass `speaker_entity` but the function expects `speaker`, it silently ignores the unknown parameter and runs with the default (if any) or `None`. Compare your YAML `data:` keys against the function signature in the `.py` file character by character.
3. **Is the module loaded?** Check HA logs during startup for pyscript module load messages. If a module has a syntax error, it won't load and its services won't register — but HA won't tell you unless you check the logs.
4. **Is there a runtime exception?** Set `custom_components.pyscript.eval` to `debug` and re-trigger. Pyscript catches exceptions internally and logs them — but at debug level, not error level.

**"L2 memory not updating"**

Diagnosis:
1. Check `memory.db` exists and is growing: file size and modification timestamp.
2. Verify the `memory_store` service is being called — grep pyscript logs for `memory` entries.
3. Check if `agent_whisper.py` is recording interactions — it's the primary writer to L2.
4. Verify the FTS5 index is intact — a corrupted index causes silent search failures. If suspected, the nuclear option is deleting `memory.db` and letting it rebuild from scratch (you lose history).

**"TTS queue not processing"**

Diagnosis:
1. Check `pyscript.tts_queue_speak` is registered (Developer Tools → Actions).
2. Check the queue state — is it stuck? Look for `tts_queue` entries in pyscript logs.
3. Verify the target speaker entity is available and not in an error state.
4. Check the ducking manager — if `duck_manager.py` has an unreleased reference count, the queue may be waiting for a duck release that never comes. Check `ai_duck_*` helper states in Developer Tools → States.
5. Verify the TTS entity (ElevenLabs or loryanstrant) is responsive — test with a direct `tts.speak` call in Developer Tools → Actions. If direct TTS works but the queue doesn't, the problem is in the queue logic, not the TTS service.

**"Dispatcher routing to wrong agent"**

Diagnosis:
1. Check the `ai_dispatcher_*` helper states — era, mode, last-used persona.
2. Check the dispatcher's routing decision in pyscript logs. It logs the decision chain: which level matched and why.
3. If keyword routing is wrong, the whisper network may have auto-learned bad keywords. Check `agent_whisper.py` logs for recent keyword updates.
4. Override test: temporarily set `ai_dispatcher_mode` to force a specific persona and verify the pipeline works. If it works with a forced persona, the routing logic is the problem. If it still fails, the problem is downstream.

**"Duck manager stuck / volume won't restore"**

Symptom: Media volume stays ducked after TTS finishes.

Diagnosis:
1. Check `ai_duck_*` helper states — is the reference count > 0? The duck manager uses reference counting, so multiple concurrent ducking requests stack. If one caller didn't release, the count never hits zero.
2. Check pyscript logs for `duck_manager` entries — look for acquire/release pairs. A missing release means a caller crashed or errored between duck and unduck.
3. Manual recovery:
   ```yaml
   # In Developer Tools → Actions:
   # Reset the duck reference count to 0
   action: input_number.set_value
   target:
     entity_id: input_number.ai_duck_ref_count
   data:
     value: 0
   # Then restore volume manually
   ```

**Reloading pyscript modules:**

Pyscript modules cache state in memory. After editing a `.py` file, the module must be reloaded for changes to take effect. Unlike automations, there is no "Reload Pyscript" button in Developer Tools → YAML.

Options:
1. **Service call:** Developer Tools → Actions → `pyscript.reload`. This reloads all pyscript modules without restarting HA. Registered services are re-registered, but any in-memory state (counters, caches, active timers) is lost.
2. **Full HA restart:** Settings → System → Restart. Use this if `pyscript.reload` doesn't pick up changes (rare, usually means a syntax error prevented reload).

**Caution:** `pyscript.reload` resets all in-memory state. If the TTS queue has items pending, they're lost. If the duck manager has an active reference count, it resets to zero (which may be what you want if it's stuck, or may cause a volume jump if a legitimate duck was in progress). If `memory.py` has a pending write batch, it may be lost — check `memory.db` timestamps after reload.

> **Cross-references:** §13.6.1 (log access protocol — tail/grep/surgical reads apply to pyscript logs too), §13.9 (conversation agent debugging — now includes orchestration layer), §13.10 (nuclear options — pyscript.reload is between levels 1 and 2).
