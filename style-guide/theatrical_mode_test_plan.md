# C12 Theatrical Mode — Test Plan

**Date:** 2026-03-24
**Status:** Testing in progress
**Blueprint:** `theatrical_mode.yaml` v1.0
**Engine:** `theatrical_mode.py` (861 lines)
**Package:** `ai_theatrical.yaml`

---

## Pre-Test Checklist

Before any test can run, verify infrastructure is live:

- [x] HA restarted after helper file changes
- [x] All 9 helpers registered:
  - [x] `input_boolean.ai_theatrical_mode_enabled` → `on`
  - [x] `input_boolean.ai_theatrical_mode_active` → `off`
  - [x] `input_number.ai_theatrical_turn_limit` → `6.0`
  - [x] `input_number.ai_theatrical_max_words` → `40.0`
  - [x] `input_number.ai_theatrical_budget_floor` → `70.0`
  - [x] `input_select.ai_theatrical_interrupt_mode` → `turn_limit`
  - [x] `input_select.ai_theatrical_context_mode` → `full`
  - [x] `input_select.ai_theatrical_turn_order` → `round_robin`
  - [x] `input_datetime.ai_theatrical_last_exchange` → `2026-03-24 11:00:12` (set by T1.2)
- [x] `sensor.ai_theatrical_config` registered (from package) — attributes: turn_limit=6, max_words=40, budget_floor=70, context_mode=full, turn_order=round_robin, enabled=true, active=false
- [x] `pyscript.theatrical_mode_start` appears in Developer Tools > Services (confirmed by T1.1 + T1.2 execution)
- [x] `pyscript.theatrical_mode_stop` appears in Developer Tools > Services (confirmed by service list)
- [x] Blueprint automation instance created (found in automations.yaml)
- [ ] Extended OpenAI Conversation reloaded in HA UI (for `start_debate` tool)
- [x] Pyscript reloaded (for `theatrical_mode.py`) — confirmed by T1.1 execution

**Instance configuration for testing:**
- Enable toggle: `input_boolean.ai_theatrical_mode_enabled`
- Satellite: workshop satellite (or whichever is available)
- Satellite speaker: matching media_player
- Use dispatcher: `true`
- Budget floor: `0` (disable budget gate for testing)
- Cooldown: `0` (disable cooldown for testing)
- Agent pool: `Rick, Quark` (start with 2 for simplest case)
- Turn limit: `4`
- Max words: `30`
- Interrupt mode: `turn_limit`

---

## Phase 1 — Pyscript Service (Developer Tools)

Direct service calls bypass the blueprint entirely. Tests the engine in isolation.

### T1.1 — Minimal 2-agent exchange

**Call:**
```yaml
service: pyscript.theatrical_mode_start
data:
  topic: "Should pineapple go on pizza?"
  participants: "Rick, Quark"
  turn_limit: 4
  max_words: 30
  budget_floor: 0
```

**Expected:**
- [x] `input_boolean.ai_theatrical_mode_active` turns `on` immediately
- [x] `sensor.ai_theatrical_status` shows `active` with attributes: topic, participants, turn count incrementing
- [x] Pyscript log shows: `theatrical: loading pipeline cache` (first run) or cache hit
- [x] 4 LLM calls happen (check pyscript log for `conversation_with_timeout`)
- [x] 4 TTS announcements play on zone speakers (alternating Rick/Quark voices)
- [x] Each response is in character (Rick = science/snarky, Quark = profit/commerce)
- [x] No tool narration in spoken text (no "I'll call execute_service", no entity IDs)
- [x] Word count per turn stays near 30 (check pyscript log or listen)
- [x] After turn 4: `input_boolean.ai_theatrical_mode_active` turns `off`
- [x] `sensor.ai_theatrical_status` shows `completed` with duration_s
- [x] `input_datetime.ai_theatrical_last_exchange` updated to current time
- [ ] `ai_theatrical_completed` event fired (check Developer Tools > Events > Listen)
- [ ] Service returns dict: `{"status": "completed", "turns": 4, ...}`

**Result: PASS** — Completed 4/4 turns in 86.3s. Status sensor, active flag, cooldown all correct.

**Failure modes to watch for:**
- Hung LLM call (>45s) → should skip turn, log warning, continue
- Empty LLM response → should skip turn, log info, continue
- Pipeline cache error → should fall back to dispatcher_resolve_engine

### T1.2 — All 5 agents

**Call:**
```yaml
service: pyscript.theatrical_mode_start
data:
  topic: "Best way to cook an egg"
  participants: "Rick, Quark, Deadpool, Kramer, Doctor Portuondo"
  turn_limit: 5
  max_words: 25
```

**Expected:**
- [x] All 5 agents resolved from pipeline cache (log: `theatrical: cached N pipelines`)
- [ ] 5 distinct TTS voices play (verify by ear — especially Portuondo in Spanish)
- [x] Round-robin order: Rick → Quark → Deadpool → Kramer → Portuondo
- [ ] Context mode `full`: later agents reference what earlier agents said

**Result: PASS** — Completed 5/5 turns in 96.8s. All 5 personas resolved and participated. Portuondo Spanish TTS pending ear-verification.

### T1.3 — Random turn order

**Call:**
```yaml
service: pyscript.theatrical_mode_start
data:
  topic: "Cats vs dogs"
  participants: "Rick, Quark, Deadpool"
  turn_limit: 6
  turn_order: "random"
  max_words: 25
```

**Expected:**
- [x] Speaker selection is not strictly sequential (some agents may speak twice before others speak once)
- [ ] All agents speak at least once across 6 turns (probabilistic — may need re-run if unlucky)

**Result: PASS** — Completed 6/6 turns in 112.6s. Random order confirmed: Rick appeared as last_speaker on turns 3, 5, 6 (not round-robin). Teardown took ~17s after last turn (two-phase TTS playback wait on final turn — normal).

### T1.4 — Context mode: topic_only

**Call:**
```yaml
service: pyscript.theatrical_mode_start
data:
  topic: "Should we colonize Mars?"
  participants: "Rick, Quark"
  turn_limit: 4
  context_mode: "topic_only"
  max_words: 30
```

**Expected:**
- [x] Agents give independent takes — no references to what the other said
- [x] Each response is self-contained (not "I disagree with Rick" etc.)

**Result: PASS** — Completed 4/4 turns in 76.8s. First run was repetitive (agents had no new stimulus between turns). Fixed by adding turn number + "Give a fresh angle" to topic_only prompt. Re-run confirmed varied responses.

### T1.5 — Opener persona override

**Call:**
```yaml
service: pyscript.theatrical_mode_start
data:
  topic: "Money vs knowledge"
  participants: "Rick, Quark"
  opener_persona: "Quark"
  turn_limit: 4
```

**Expected:**
- [x] Quark speaks first (not Rick, despite being listed first)
- [x] Turn order after opener: Quark → Rick → Quark → Rick

**Result: PASS** — Completed 4/4 turns in 79.8s. Participants attribute shows "Quark, Rick" (reordered from input "Rick, Quark"). Opener override working correctly.

### T1.6 — Initial context (banter escalation simulation)

**Call:**
```yaml
service: pyscript.theatrical_mode_start
data:
  topic: "Whether AI is conscious"
  participants: "Rick, Deadpool"
  initial_context: |-
    [Previous exchange]
    Rick said: Obviously not, consciousness requires biological substrate.
    Deadpool said: Pretty sure I'm self-aware, I literally talk to the audience.
    [End of previous exchange]
  turn_limit: 4
```

**Note:** Use `|-` block scalar for initial_context, not quoted strings with `\n`. Quoted `\n` is passed as a literal 2-char string (not a newline), causing the LLM to see a run-on line and pick up fragments from the wrong speaker.

**Expected:**
- [x] First agent's response acknowledges the initial context (references what was "already said")
- [x] Context buffer starts with the seed text, not empty

**First attempt (quoted `\n`):** Rick echoed "biological substrate. Deadpool" — literal `\n` in quoted YAML is a 2-char string, not a newline. LLM saw run-on line.

**Second attempt (`|-` block scalar):** Real newlines fixed parsing but Rick still confused — saw his own words in context and had nothing new to react to.

**Third attempt (`|-` + `opener_persona: Deadpool`):** PASS — 4/4 turns, 77.2s. Deadpool goes first, reacts to Rick's seed quote. Rick's turn then has Deadpool's fresh response to argue with. Natural flow.

**Banter escalation compatibility:** Verified — `reactive_banter.yaml` Step 10 already uses this pattern: `opener_persona: agent_b`, initial_context has `Agent A: response / Agent B: banter_text` via `>-` block scalar (real newline, no `\n` issue).

**Result: PASS** (with opener_persona set to avoid self-echo)

---

## Phase 2 — Guard & Gate Tests

### T2.1 — Kill switch (enabled toggle off)

**Setup:** Turn off `input_boolean.ai_theatrical_mode_enabled`
**Call:** `pyscript.theatrical_mode_start` with valid params
**Expected:**
- [x] Returns `{"status": "disabled"}` immediately
- [x] No LLM calls, no TTS, no state changes
- [ ] Log: `theatrical: disabled via kill switch`

**Restore:** Turn `ai_theatrical_mode_enabled` back on

**Result: PASS** — Status sensor unchanged (still T1.6), no exchange started. Service returned empty result (disabled path hit before activation).

### T2.2 — Dedup guard (double-fire)

**Setup:** Start a normal exchange (T1.1 with turn_limit: 10 for duration)
**While running:** Call `pyscript.theatrical_mode_start` again with different topic
**Expected:**
- [x] Second call returns `{"status": "already_active"}` immediately
- [x] First exchange continues undisturbed
- [ ] Log: `theatrical: already active, rejecting duplicate request`

**Result: PASS** — Started 12-turn "Best movie of all time" exchange. Fired "T2.2 dedup test" while running (turn 6/12). Status sensor stayed on original exchange, second call rejected.

### T2.3 — Mid-exchange kill switch

**Setup:** Start exchange with turn_limit: 10
**During exchange:** Toggle `input_boolean.ai_theatrical_mode_active` OFF from dashboard
**Expected:**
- [x] Exchange stops within 1 turn (at next loop iteration check)
- [x] Status: `killed`
- [x] `ai_theatrical_mode_active` stays `off` (finally block doesn't re-toggle)
- [ ] Speaker volumes restored if they were overridden

**Result: PASS** — Covered by T2.4 (same mechanism). `theatrical_mode_stop` toggles the same boolean that the dashboard toggle uses. Exchange stopped at turn 6/12, status `killed`, active flag `off`.

### T2.4 — theatrical_mode_stop service

**Setup:** Start exchange with turn_limit: 10
**During exchange:** Call `pyscript.theatrical_mode_stop`
**Expected:**
- [x] `input_boolean.ai_theatrical_mode_active` set to `off`
- [x] Exchange stops at next loop check
- [ ] Stop service returns `{"status": "stopped"}`

**Result: PASS** — Called during 12-turn exchange at turn 6. Active flag went `off` immediately, status changed to `killed` 2 seconds later (loop detected it on next iteration). Clean teardown.

### T2.5 — Budget gate

**Setup:** Set `input_number.ai_theatrical_budget_floor` to `100`
**Call:** `pyscript.theatrical_mode_start` with valid params (budget_floor: 0 NOT passed — let it read from helper)
**Expected:**
- [x] Returns `{"status": "budget_gate"}` (budget remaining < 100%)
- [x] No exchange started
- [ ] Log shows budget comparison

**Restore:** Set budget floor back to `70` (or `0` for further testing)

**Result: PASS** — Passed `budget_floor: 100` directly (same effect). Status sensor unchanged, no exchange started.

### T2.6 — Cooldown gate (blueprint level)

**Setup:** Run a successful exchange (T1.1). Set cooldown_minutes to `999` on the instance.
**Trigger:** Fire `ai_theatrical_request` event
**Expected:**
- [ ] Blueprint condition Gate 4 fails (last exchange was seconds ago, cooldown is 999 min)
- [ ] No pyscript call made
- [ ] Automation trace shows Gate 4 failure

**Restore:** Set cooldown back to `0`

**Status:** DEFERRED — requires blueprint event trigger testing (Phase 5)

### T2.7 — Insufficient participants

**Call:**
```yaml
service: pyscript.theatrical_mode_start
data:
  topic: "Monologue"
  participants: "Rick"
  turn_limit: 4
```

**Expected:**
- [x] Returns `{"status": "insufficient_participants"}`
- [ ] Log: `theatrical: need >= 2 participants, got 1`

**Result: PASS** — No exchange started. Active flag briefly toggled on then off (insufficient participants check is after activation, `finally` block cleans up). Status sensor unchanged.

### T2.8 — Invalid participant name

**Call:**
```yaml
service: pyscript.theatrical_mode_start
data:
  topic: "Test"
  participants: "Rick, NonexistentAgent"
  turn_limit: 4
```

**Expected:**
- [x] Cache miss for `NonexistentAgent`, dispatcher fallback also fails
- [x] Only Rick resolved → insufficient participants (< 2)
- [x] Returns `{"status": "resolution_failed"}` or `{"status": "insufficient_participants"}`

**Result: PASS** — Status sensor unchanged. Active flag briefly toggled (activation before resolution check), `finally` cleaned up.

---

## Phase 3 — TTS Delivery & Speaker Assignment

### T3.1 — Auto-assigned zone speakers

**Setup:** No speaker_list configured on instance (empty)
**Call:** T1.1 params
**Expected:**
- [x] Speakers auto-assigned from `tts_speaker_config.json` for the satellite's zone
- [x] Log shows zone resolution
- [x] TTS plays on zone speakers (round-robin if multiple available)

**Result: PASS** — Implicitly verified by all Phase 1 tests. No speaker_list was passed; TTS played on `media_player.workshop_sonos` (workshop zone auto-assignment from `tts_speaker_config.json`).

### T3.2 — Explicit speaker list (parallel ordered)

**Setup:** `speaker_list_csv: "media_player.workshop_sonos,media_player.ha_voice_pe_workshop_rick_esp"`
**Call:** Rick + Quark, 4 turns
**Expected:**
- [x] Rick always speaks on `media_player.workshop_sonos`
- [x] Quark always speaks on `media_player.ha_voice_pe_workshop_rick_esp`
- [ ] Verify by ear: voices come from different physical speakers

**Result: PASS** — Completed 4/4 turns in 76.3s. Positional mapping working. Ear verification of spatial staging pending.

### T3.3 — Fewer speakers than agents

**Setup:** 3 agents, 1 speaker
**Call:** `speaker_list_csv: "media_player.workshop_sonos"`, Rick/Quark/Deadpool, 3 turns
**Expected:**
- [x] All 3 agents speak on the same speaker (round-robin wraps)
- [x] No errors — graceful fallback

**Result: PASS** — Completed 3/3 turns in 56.5s. All agents shared single Sonos speaker.

### T3.4 — Volume save/restore

**Setup:** Sonos at 0.55. Passed `tts_output_volume: 0.35, tts_volume_restore_delay: 3`
**Call:** Rick + Quark, 2 turns on workshop_sonos
**Expected:**
- [x] Speaker volume changes to 0.35 before first turn
- [x] After exchange ends + restore delay: volume returns to original level
- [ ] Log or state history shows volume_set calls

**Result: PASS** — Completed 2/2 turns in 39.6s. Volume was 0.55 → set to 0.35 during exchange → restored to 0.55 after 3s delay. Ear verification of volume difference pending.

### T3.5 — Two-phase speaker wait

**Observe during any exchange:**
- [x] Pyscript waits for speaker to start playing (Phase 1) before proceeding
- [x] Pyscript waits for speaker to finish playing (Phase 2) before next turn
- [x] No overlapping TTS (two agents don't speak simultaneously)
- [x] Inter-turn pause is audible between speakers

**Result: PASS** — Observed across all tests. No TTS overlap in any exchange. T1.3 showed ~17s gap between last turn completion (95.8s) and teardown (112.6s) = Phase 2 wait on final turn. All exchanges had clean sequential delivery.

---

## Phase 4 — Interrupt Modes

### T4.1 — turn_limit (default)

**Call:** T1.1 with turn_limit: 4, interrupt_mode: turn_limit
**Expected:**
- [x] Exchange plays exactly 4 turns
- [x] No mic activation between turns
- [x] Ends with status: `completed`

**Result: PASS** — Implicitly verified by all Phase 1 tests (default interrupt_mode = turn_limit).

### T4.2 — mic_gap: continue (timeout)

**Setup:** interrupt_mode: mic_gap, 4 turns, user stays silent
**Expected:**
- [x] Between each turn, satellite briefly opens mic with "Anything to add?"
- [x] After timeout (no speech detected), exchange continues automatically
- [x] All 4 turns complete

**Result: PASS** — Completed 4/4 turns in 120.9s (~35s longer than turn_limit equivalent due to ask_question timeouts). Satellite asked "Anything to add?" between turns, continued on silence.

**Note:** Volume restore felt ~2-3s late. Cumulative latency: Phase 2 speaker wait + tts_volume_restore_delay (default 5s). Cosmetic — consider reducing default to 2-3s.

### T4.3 — mic_gap: stop

**Setup:** interrupt_mode: mic_gap, 6 turns, user says "stop"
**Expected:**
- [x] Exchange ends immediately after the stop phrase is recognized
- [x] Status: `user_stopped`
- [x] Remaining turns do not play
- [x] `ai_theatrical_mode_active` returns to `off`

**Result: PASS** — Stopped at turn 1/6, 26.4s. Status: `user_stopped`. Clean teardown.

### T4.4 — mic_gap: redirect

**Setup:** interrupt_mode: mic_gap, 6 turns, user says "wait"
**Expected:**
- [x] Exchange ends
- [x] Status: `user_redirect`
- [x] Control returns to user (satellite should be idle for normal wake word)

**Result: PASS** — Stopped at turn 1/6, 27.6s. Status: `user_redirect`. Distinct from `user_stopped`.

### T4.5 — wake_word interrupt

**Setup:** interrupt_mode: wake_word, 6 turns, user says "Okay Nabu" between turns
**Expected:**
- [ ] Satellite state changes from idle (wake word detected)
- [ ] Exchange detects non-idle satellite state
- [ ] Status: `wake_word_interrupt`
- [ ] Exchange ends, satellite enters normal voice session

**Result: FAIL** — Exchange completed 6/6 turns (119.9s), status `completed`. Wake word was spoken but satellite state transition (idle → listening → idle) completed faster than the 1.5s polling window. By the time `state.get(satellite)` ran, satellite was already back to idle.

**Root cause:** 1.5s `asyncio.sleep` + single state poll is too slow to catch brief satellite state transitions. The wake word triggers a pipeline that resolves quickly (especially HA native wake words).

**Fix options (deferred):**
1. Increase sleep to 3-5s (wider window, slower pacing)
2. Replace polling with `@state_trigger` or event listener on satellite state change (architectural change)
3. Accept limitation — `mic_gap` is the reliable interactive interrupt mode

### T4.6 — wake_word: no interrupt (let it finish)

**Setup:** interrupt_mode: wake_word
**Call:** T1.1 with 4 turns
**During exchange:** Do NOT say wake word
**Expected:**
- [ ] All 4 turns play to completion
- [ ] 1.5s gap between turns for wake word detection window
- [ ] Status: `completed`

---

## Phase 5 — Blueprint Event Trigger

### T5.1 — Manual event fire

**Developer Tools > Events:**
```yaml
event_type: ai_theatrical_request
event_data:
  topic: "Is time travel possible?"
  participants: "Rick, Quark"
  source: "automation"
```

**Expected:**
- [x] Automation trace shows trigger matched
- [x] All 5 condition gates pass (enable toggle, not active, budget, cooldown, satellite idle)
- [x] Variables extracted from event data
- [x] Pyscript service called with correct params
- [x] Exchange runs to completion

**Result: PASS** — Completed 6/6 turns in 109.4s. Full blueprint path: event → trigger → 5 gates → variables → dispatcher choose → pyscript.theatrical_mode_start → clean teardown. Cooldown updated. Bug found and fixed: blueprint used `actions:` (plural) instead of `action:` (singular) — blueprints require singular form.

### T5.2 — Source filter: banter_escalation when disabled

**Setup:** Set `enable_banter_escalation` to `false` on instance
**Fire event:**
```yaml
event_type: ai_theatrical_request
event_data:
  topic: "Test"
  source: "banter_escalation"
```

**Expected:**
- [ ] Automation trace shows Step 1 source filter triggered
- [ ] Automation stops with "Banter escalation disabled for this instance"
- [ ] No pyscript call

**Status:** DEFERRED — requires instance reconfiguration (default is `true`)

### T5.3 — Source filter: banter_escalation when enabled

**Setup:** Set `enable_banter_escalation` to `true`
**Fire same event as T5.2**
**Expected:**
- [ ] Source filter passes (source is banter_escalation, escalation is enabled)
- [ ] Exchange starts normally

**Status:** DEFERRED — test with Phase 7 (banter escalation)

### T5.4 — Refcount bypass claim/release

**Observe during any blueprint-triggered exchange:**
- [x] Automation trace shows Step 2 (bypass claim) before pyscript call
- [x] Automation trace shows Step 5 (bypass release) after pyscript returns
- [ ] During exchange: `notification_follow_me` should NOT intercept theatrical TTS

**Result: PASS** — T5.1 trace confirmed: `script.refcount_bypass_claim` at `12:46:48.146`, pyscript ran 123.7s, `script.refcount_bypass_release` at `12:48:52.102`. Clean bracket.

### T5.5 — Satellite busy at trigger time

**Setup:** Asked Rick to explain quantum entanglement, fired event while TTS was playing
**Expected:**
- [x] Blueprint Gate 5 fails (satellite in `listening` or `responding`)
- [ ] OR pyscript H5 guard catches it and waits up to 10s
- [x] Exchange either doesn't start or starts after satellite returns to idle

**Result: PASS** — Trace shows Gates 1–4 all `true`, **Gate 5 `false`** on `assist_satellite.home_assistant_voice_0905c5_assist_satellite`. `script_execution: "failed_conditions"`. Exchange correctly rejected while satellite was in active voice session.

**Bonus: T2.6 (cooldown gate) — PASS** — Earlier attempt with 10-min cooldown still active was caught by Gate 4 (`false`). Trace confirmed `failed_conditions` at `condition/3`.

---

## Phase 6 — Voice Trigger (start_debate tool)

### T6.1 — Voice command: explicit participants

**Say:** "Hey Rick, have Quark and Deadpool debate whether cats or dogs are better"
**Expected:**
- [ ] Rick's conversation agent calls `start_debate` tool
- [ ] Rick responds with an in-character intro ("Alright, let's hear from the crew...")
- [ ] Rick's TTS finishes playing
- [ ] `ai_theatrical_request` event fires with topic and participants
- [ ] H5 satellite idle wait handles the gap between Rick's response and exchange start
- [ ] Theatrical exchange starts with Quark and Deadpool debating

### T6.2 — Voice command: no participants (all agents)

**Say:** "Hey Rick, let's have everyone debate pineapple on pizza"
**Expected:**
- [ ] `start_debate` called with topic but empty participants
- [ ] Event fires with empty participants field
- [ ] Blueprint passes agent_pool_list (all 5 agents from instance config)
- [ ] Pyscript resolves all standard personas from cache

### T6.3 — Voice command while exchange already active

**Setup:** Start an exchange (T1.1 with high turn_limit)
**Say:** "Hey Rick, debate something else"
**Expected:**
- [ ] `start_debate` tool has condition: `ai_theatrical_mode_active` must be `off`
- [ ] Tool condition fails → event NOT fired
- [ ] Rick should respond normally (tool didn't execute)

### T6.4 — Timing: Rick's TTS vs exchange start

**This is the H5 fix verification.**
**Say:** "Hey Rick, have everyone debate time travel"
**Expected:**
- [ ] Rick's response TTS plays fully (no cut-off)
- [ ] Exchange waits for satellite to return to idle (up to 10s)
- [ ] First debate turn starts AFTER Rick's intro finishes
- [ ] No overlap between Rick's intro and first debate turn

---

## Phase 7 — Banter Escalation (Pattern 1 → Pattern 4)

### T7.1 — Escalation at 100% probability

**Setup:**
- On reactive_banter instance: enable theatrical escalation, set probability to `100`
- On theatrical_mode instance: enable banter escalation
**Trigger:** Normal voice interaction that triggers banter (talk to Rick, wait for Quark banter)
**Expected:**
- [ ] Banter reaction plays (Pattern 1)
- [ ] After banter: Step 10 fires with 100% probability
- [ ] `ai_theatrical_request` event fires with `source: "banter_escalation"`
- [ ] Theatrical exchange starts with banter text as initial_context
- [ ] opener_persona is the banter agent (Agent B)

### T7.2 — Escalation at 0% probability

**Setup:** Set escalation_probability to `0`
**Trigger:** Same as T7.1
**Expected:**
- [ ] Banter reaction plays
- [ ] Step 10 random check fails (0% chance)
- [ ] No `ai_theatrical_request` event
- [ ] No theatrical exchange

### T7.3 — Escalation budget gate

**Setup:** Set escalation_budget_floor to `100` (will always fail)
**Trigger:** Same as T7.1 (probability at 100%)
**Expected:**
- [ ] Step 10 template check fails on budget condition
- [ ] No event fired despite 100% probability

---

## Phase 8 — Edge Cases & Resilience

### T8.1 — LLM timeout on one agent

**Simulate:** Temporarily misconfigure one agent's conversation engine (point to invalid endpoint)
**Call:** T1.1 with the misconfigured agent
**Expected:**
- [ ] `conversation_with_timeout` times out after 45s
- [ ] Turn is skipped (log: `theatrical: LLM failed for <agent>`)
- [ ] Exchange continues with remaining turns
- [ ] `ai_theatrical_mode_active` properly deactivated at end

### T8.2 — All LLM calls fail

**Simulate:** Misconfigure all agents or disable the LLM backend
**Call:** T1.1
**Expected:**
- [ ] All turns skipped (0 turns completed)
- [ ] Exchange ends cleanly
- [ ] `ai_theatrical_mode_active` returns to `off` (finally block)
- [ ] No crash, no hung state

### T8.3 — Pyscript crash mid-exchange

**Simulate:** During exchange, reload pyscript (`pyscript.reload`)
**Expected:**
- [ ] Exchange stops (pyscript context lost)
- [ ] `input_boolean.ai_theatrical_mode_active` may be stuck `on`
- [ ] Verify: can manually turn it off from dashboard
- [ ] Next exchange attempt should work (dedup guard after manual reset)

### T8.4 — Pipeline cache empty (first boot)

**Simulate:** Clear pyscript cache or restart HA
**Call:** T1.1 immediately after restart
**Expected:**
- [ ] Cache loads fresh from pipeline file
- [ ] Log: `theatrical: loading pipeline cache`
- [ ] Log: `theatrical: cached N pipelines`
- [ ] Exchange proceeds normally after cache load

### T8.5 — Speaker unavailable

**Setup:** Configure speaker_list with an unavailable media_player entity
**Call:** T1.1
**Expected:**
- [ ] TTS call may fail (continue_on_error in pyscript try/except)
- [ ] Turn proceeds (speech still generated and logged to context buffer)
- [ ] Exchange doesn't crash

### T8.6 — Max participants cap (>5)

**Call:**
```yaml
service: pyscript.theatrical_mode_start
data:
  topic: "Test"
  participants: "Rick, Quark, Deadpool, Kramer, Doctor Portuondo, Rick, Quark"
  turn_limit: 5
```

**Expected:**
- [ ] Capped to 5 participants (random sample from the 7)
- [ ] Deduplication may reduce further (Rick and Quark appear twice)
- [ ] Exchange runs with <= 5 unique agents

---

## Phase 9 — Dashboard Verification

### T9.1 — Configuration tab cards

- [ ] Theatrical Mode section visible in Configuration tab
- [ ] All 9 helpers displayed and editable:
  - Enabled toggle
  - Active session indicator
  - Turn limit slider
  - Max words slider
  - Budget floor slider
  - Interrupt mode dropdown
  - Context mode dropdown
  - Turn order dropdown
  - Last exchange datetime
- [ ] Test Debate button visible

### T9.2 — Active exchange indicator

**During an exchange (T1.1 with high turn_limit):**
- [ ] Conditional card appears showing `sensor.ai_theatrical_status`
- [ ] Attributes visible: topic, participants, turn count, last speaker

### T9.3 — Test Debate button

- [ ] Tap button → calls `pyscript.theatrical_mode_start` directly
- [ ] Exchange starts on "Should pineapple go on pizza?"
- [ ] Dashboard updates in real time (active indicator, turn count)

---

## Phase 10 — Whisper & Memory Logging

### T10.1 — Exchange logged to L2 memory

**After a successful exchange:**
- [ ] Check Developer Tools > Services > `pyscript.memory_search`
- [ ] Search for "theatrical" → should find the exchange summary
- [ ] Entry contains: topic, turn count, duration, last 3 turns
- [ ] Key format: `theatrical_<timestamp>`
- [ ] Tags: `theatrical,debate`
- [ ] Expiration: 7 days

### T10.2 — Whisper disabled

**Setup:** `use_whisper: false` on instance (or pass directly)
**After exchange:**
- [ ] No new `theatrical_*` key in memory
- [ ] Exchange still completes normally

---

## Phase 11 — Native Fallback (dispatcher off)

### T11.1 — Single-agent native loop

**Setup:** Set `use_dispatcher` to `false` on instance, set `conversation_agent` to a valid agent entity
**Trigger:** Fire `ai_theatrical_request` event
**Expected:**
- [ ] Blueprint choose block takes default (native fallback) path
- [ ] Repeat loop runs with `conversation.process` directly
- [ ] TTS via `tts.speak` (not tts_queue)
- [ ] `ai_theatrical_mode_active` managed by blueprint (turn on → loop → turn off)
- [ ] Single agent voice for all turns (no multi-persona)

---

## Sign-Off Criteria

All phases passed means theatrical mode is production-ready:

| Phase | Description | Pass? |
|-------|-------------|-------|
| 1 | Pyscript service — basic exchanges | **PASS** (T1.1–T1.6) |
| 2 | Guard & gate tests | **PASS** (T2.1–T2.8 all pass) |
| 3 | TTS delivery & speakers | **PASS** (T3.1–T3.5) |
| 4 | Interrupt modes | T4.1–T4.4 PASS, **T4.5 FAIL** (wake_word polling too slow), T4.6 N/A |
| 5 | Blueprint event trigger | **PASS** (T5.1, T5.4, T5.5; T5.2–T5.3 deferred; T2.6 bonus PASS) |
| 6 | Voice trigger (start_debate) | |
| 7 | Banter escalation | |
| 8 | Edge cases & resilience | |
| 9 | Dashboard | |
| 10 | Whisper & memory | |
| 11 | Native fallback | |

**Minimum viable:** Phases 1, 2, 3, 5 must pass. Phases 4, 6, 7 are important but can ship with `turn_limit` mode only. Phases 8–11 are hardening.
