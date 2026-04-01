# Reactive Banter -- Agent Post-Response Commentary (v2.2.0)

Pattern 1 of inter-agent communication. After Agent A responds to the user, another agent probabilistically chimes in with a brief, in-character reaction via TTS. Uses `conversation.process` for full agent personality and hot context. Tool-suppression prefix prevents re-entry. Per-satellite instances. Foundation for Pattern 4 (Theatrical Mode).

## How It Works

```
┌──────────────────────────────────┐
│  ai_conversation_response_ready  │ (voice — from conversation_sensor.py)
│  tts_queue_item_completed        │ (notification — after TTS delivery)
└──────────────┬───────────────────┘
               │
               ▼
┌──────────────────────────────────┐
│  Gates (0–8)                     │
│  • Master notification gate      │
│  • Enable toggle                 │
│  • Satellite match (voice only)  │
│  • Trigger sanity                │
│  • Budget floor (Luxury tier)    │
│  • Cooldown                      │
│  • Theatrical mode not active    │
│  • Satellite idle check          │
│  • Notification threshold        │
└──────────────┬───────────────────┘
               │ pass
               ▼
┌──────────────────────────────────┐
│  Step 1: Resolve event data      │
│  Step 2: Probability roll        │
│  Step 3: Filter pool (excl A)   │
│  Step 4: Random-select Agent B   │
│  Step 4b: Resolve engine via     │
│           dispatcher             │
└──────────────┬───────────────────┘
               │
               ▼
┌──────────────────────────────────┐
│  Step 5: Build banter prompt     │
│  (safety prefix + user prefs)    │
│  Step 5a: Claim follow-me bypass │
│  Step 5b: conversation.process   │
└──────────────┬───────────────────┘
               │
               ▼
┌──────────────────────────────────┐
│  Step 6: Extract speech          │
│  Step 6c: Wait for Agent A TTS   │
│  Step 6e: Resolve pre-TTS stinger│
│  Step 6g: Wait for ducking clear │
│  Step 6h: Final satellite guard  │
└──────────────┬───────────────────┘
               │
               ▼
┌──────────────────────────────────┐
│  Step 7: TTS via tts_queue_speak │
│  Step 7b: Release bypass         │
│  Step 8: Update cooldown helper  │
│  Step 9: Log banter via whisper  │
│  Step 10: Theatrical escalation  │
│           check (optional)       │
└──────────────────────────────────┘
```

## Features

- Two trigger paths: voice interactions (`ai_conversation_response_ready`) and notification deliveries (`tts_queue_item_completed`)
- Probabilistic firing with configurable chance (0--100%)
- Cooldown gate prevents rapid-fire commentary
- Budget floor gate (Luxury tier -- first to be cut)
- Agent pool with automatic exclusion of Agent A (the responding agent)
- Persona-normalized pool filtering (handles pipeline variant names)
- TTS delivery via `tts_queue_speak` with presence or explicit speaker targeting
- Two-phase speaker wait (start playing, then finish playing) for voice triggers
- Ducking flag wait prevents banter over ducked audio
- Final satellite guard suppresses banter if user starts a new voice session
- Optional pre-TTS stinger/chime with 3-tier resolution (library ID, auto-resolve/compose, fallback URL)
- Follow-me bypass (refcount claim/release) during banter
- User preference injection (humor, off-limits, pet peeves)
- Notification threshold gating against user preference
- Theatrical escalation: banter can probabilistically escalate into a full Pattern 4 multi-agent debate

## Prerequisites

- Home Assistant 2024.10.0+
- Pyscript modules: `conversation_sensor` (fires `ai_conversation_response_ready`), `agent_dispatcher` (`dispatcher_resolve_engine`), `tts_queue` (`tts_queue_speak`), `agent_whisper`
- `input_datetime.ai_banter_last_reaction` (cooldown tracking)
- `input_boolean.ai_theatrical_mode_active` (theatrical mode guard)
- `input_text.ai_last_satellite` (satellite routing)
- `input_boolean.ai_ducking_flag` (ducking state)
- Refcount bypass scripts (claim + release)

## Installation

1. Copy `reactive_banter.yaml` to `config/blueprints/automation/madalone/`
2. Create automation: **Settings -> Automations -> Create -> Use Blueprint**
3. Create one instance per satellite

## Configuration

<details><summary>① Control</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `enable_toggle` | _(required)_ | Per-instance kill switch for reactive banter (input_boolean entity) |
| `notification_master_gate` | `input_boolean.ai_notifications_master_enabled` | Global notification gate. When OFF, all notification automations using this gate are suppressed |
| `enable_notification_banter` | `true` | Independent toggle for banter after notification/email deliveries |
| `satellite` | _(required)_ | Which satellite this instance serves (assist_satellite entity) |
| `satellite_speaker` | _(required)_ | Media player for the satellite's ESP speaker. Used to detect when Agent A's TTS finishes |

</details>

<details><summary>② Gating</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `banter_probability` | `20` | Chance of banter after each interaction (0--100%) |
| `cooldown_minutes` | `30` | Minimum minutes between banter reactions |
| `budget_floor` | `60` | Skip banter when LLM budget remaining drops below this %. 0 = disable |

</details>

<details><summary>③ Agent Pool</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `agent_pool_list` | `Rick, Quark, Deadpool, Kramer, Doctor Portuondo` | Comma-separated pipeline display names eligible for banter. Agent A is auto-excluded |

</details>

<details><summary>④ Delivery</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `tts_speaker` | _(empty)_ | Media player for banter delivery. Only used when TTS Target Mode is "explicit" |
| `tts_target_mode` | `presence` | Speaker targeting: "presence" routes via FP2 zones, "explicit" uses the TTS Speaker above |
| `tts_output_volume` | `0.0` | Volume level (0.0--1.0) before TTS. 0 = use current volume |
| `tts_restore_delay` | `8` | Seconds to wait after TTS before restoring original volume |
| `tts_playback_buffer` | `3` | Extra seconds after satellite idle before banter speaks |

</details>

<details><summary>⑤ Stinger</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `enable_pre_tts_stinger` | `false` | Play a chime/stinger before banter TTS |
| `stinger_library_id_override` | _(empty)_ | Explicit music library ID. Skips auto-resolve when set |
| `compose_stinger_if_missing` | `true` | Compose a stinger locally via FluidSynth when not found in library |
| `stinger_fallback_media_url` | _(empty)_ | Fallback chime URL when library lookup and compose both fail |

</details>

<details><summary>⑥ Infrastructure</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `cooldown_helper` | `input_datetime.ai_banter_last_reaction` | input_datetime for cooldown tracking |
| `bypass_claim_script` | `script.refcount_bypass_claim` | Refcount claim script (turns off follow-me during banter) |
| `bypass_release_script` | `script.refcount_bypass_release` | Refcount release script (restores follow-me after banter) |
| `theatrical_mode_entity` | `input_boolean.ai_theatrical_mode_active` | Boolean tracking whether theatrical mode is running |
| `last_satellite_entity` | `input_text.ai_last_satellite` | Helper storing the last-active satellite entity_id |
| `ducking_flag_entity` | `input_boolean.ai_ducking_flag` | Boolean tracking active volume ducking state |

</details>

<details><summary>⑦ Prompt</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `banter_prompt` | _(see below)_ | Creative instruction sent to Agent B. Placeholders: `{agent_a}`, `{topic}`, `{excerpt}`, `{mood}`, `{max_words}` |
| `max_words` | `25` | Maximum word count for the banter reaction |

Default prompt:
> {agent_a} just told the user: '{excerpt}'. Respond in your natural language and style, directed AT the user. If your character speaks a language other than English, respond in that language. Under {max_words} words.

</details>

<details><summary>⑧ Theatrical Escalation</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `enable_theatrical_escalation` | `false` | After successful banter, roll for escalation into a full theatrical debate |
| `escalation_probability` | `10` | Chance that banter escalates into theatrical mode (0--100%) |
| `escalation_budget_floor` | `70` | Additional budget floor gate for escalation. 0 = use theatrical blueprint's own floor |

</details>

<details><summary>⑨ User Preferences</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `enable_user_preferences` | `true` | Inject user humor, off-limits, and pet peeve preferences into banter prompts |

</details>

<details><summary>⑩ Notification Threshold</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `enable_notify_threshold` | `false` | Gate TTS against active user's notification threshold preference |
| `tts_priority` | `2` | Queue priority for banter (0=emergency, 4=low) |
| `bypass_ducking` | `false` | Skip volume ducking on other speakers during TTS |

</details>

## Technical Notes

- **Mode:** `single` / `max_exceeded: silent` -- only one banter at a time
- **Trigger paths:** Voice via `ai_conversation_response_ready` event; notifications via `tts_queue_item_completed` event (fires after TTS playback, not when queued)
- **Tool suppression:** Safety prefix on all prompts prevents Agent B from calling `handoff_agent`, `execute_service`, or other tools
- **Whisper logging:** Banter logged with `source: "automation"` to prevent re-trigger by conversation_sensor
- **Two-phase speaker wait:** Phase 1 waits for speaker to start playing, Phase 2 waits for it to finish. Without Phase 1 the wait passes immediately if checked before TTS starts
- **All device/service actions** use `continue_on_error: true`

## Changelog

- **v2.2.0** (2026-03-23): Gate 6 satellite idle check, Step 6h pre-TTS guard, direct-address prompt
- **v2.1.0** (2026-03-20): Event-driven triggers, Step 0 eliminated
- **v2.0.0** (2026-03-20): conversation.process + flexible agent pool
- **v1.0.0** (2026-03-20): Initial deployment (llm_task_call)

## Author

**madalone**

## License

See [LICENSE](../../LICENSE) in the repository root.
