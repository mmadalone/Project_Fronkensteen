# Therapy Session (v1.0)

Persona-agnostic therapy session management supporting individual and couple modes. Manages the full session lifecycle: entry via toggle/handoff/schedule, continuous conversation loop with the therapist agent, session tracking with memory persistence, and graceful exit with optional session summary and markdown reports.

## How It Works

```
┌──────────────────────────────────────────────────┐
│  TRIGGERS                                         │
│  • Toggle ON (input_boolean)                     │
│  • Toggle OFF (cleanup path)                     │
│  • Scheduled time (day-of-week gated)            │
└──────────────────┬───────────────────────────────┘
                   │
          ┌────────┴────────┐
          │                 │
          ▼                 ▼
   ┌──────────┐      ┌──────────┐
   │  STOP    │      │  START   │
   │  path    │      │  path    │
   └──────────┘      └────┬─────┘
   Restore toggles        │
   Deactivate cont.       ▼
   conversation     ┌──────────────────────────┐
                    │  0. Pre-session checks    │
                    │  • Resolve user            │
                    │  • Budget gate             │
                    │  • Privacy gate            │
                    │  • Suppress notifications  │
                    │  • Suppress follow-me      │
                    └────────────┬──────────────┘
                                │
                                ▼
                    ┌──────────────────────────┐
                    │  1. Pipeline switch       │
                    │  Save current → switch    │
                    │  to therapy variant       │
                    │  Register restore         │
                    └────────────┬──────────────┘
                                │
                                ▼
                    ┌──────────────────────────┐
                    │  2. Session start         │
                    │  • pyscript.therapy_      │
                    │    session_start           │
                    │  • Activate continuous     │
                    │    conversation            │
                    │  • Speak opening message   │
                    │  • Build ESP + open mic    │
                    └────────────┬──────────────┘
                                │
                                ▼
                    ┌──────────────────────────┐
                    │  4. Continuous loop       │
                    │  while: timeout + budget  │
                    │  + toggle + no_speech < 3 │
                    │                           │
                    │  A. Wait for satellite    │
                    │  B. No-speech detection   │
                    │  D. Echo guard            │
                    │  E. Wait for speaker idle │
                    │  G. Build ESP (+ couple)  │
                    │  H. Reopen mic            │
                    └────────────┬──────────────┘
                                │ loop exit
                                ▼
                    ┌──────────────────────────┐
                    │  5. Session end & cleanup │
                    │  • pyscript.therapy_      │
                    │    session_end             │
                    │  • Auto-generate report   │
                    │  • Deactivate continuous  │
                    │  • Turn off therapy toggle │
                    │  • Restore suppressed     │
                    │    toggles + follow-me    │
                    └──────────────────────────┘
```

## Features

- **Individual and couple therapy** with configurable session type
- **4 entry points:** toggle, voice handoff, natural language trigger, scheduled time
- **Session continuity:** remembers session count and last summary across sessions
- **Couple mode:** LLM-driven speaker identification with turn tracking history
- **Session recovery:** checkpoint-based crash recovery (resume interrupted sessions)
- **QS-5 isolation:** individual memories scoped to user, couple memories scoped to couple
- **Markdown reports:** auto-generate on session end or on-demand via voice/dashboard
- **All prompts configurable** via blueprint inputs (therapy ESP, couple ESP, session context, speaker tracking)
- Continuous conversation loop with timeout, budget, and no-speech exit conditions
- Pipeline switch to therapy variant with automatic restore via voice_handoff
- Notification suppression during therapy (configurable toggle list)
- Privacy gate with tier-based identity confidence check
- Test mode with compressed timeout, single-cycle exit, and state transition announcements

## Prerequisites

- Home Assistant 2025.4.0+
- Pyscript modules: `therapy_session` (`therapy_session_start`, `therapy_session_end`, `therapy_session_report`), `voice_handoff` (`voice_handoff_register_restore`), `tts_queue` (`tts_queue_speak`), `voice_session`
- A therapy pipeline variant (e.g., "Doctor Portuondo - Therapy") configured in Assist Pipelines
- `input_boolean.ai_therapy_mode` (session toggle)
- `input_boolean.ai_continuous_conversation_active` (mic cycling)
- Assist Satellite entity + media player speaker

## Installation

1. Copy `therapy_session.yaml` to `config/blueprints/automation/madalone/`
2. Create the therapy pipeline variant in Assist Pipelines
3. Create automation: **Settings -> Automations -> Create -> Use Blueprint**

## Configuration

<details><summary>① Core</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `enable` | `true` | Kill switch for this automation instance |
| `therapy_toggle` | `input_boolean.ai_therapy_mode` | Input boolean that activates therapy mode. ON = start, OFF = stop |
| `satellite` | _(empty)_ | Voice satellite to run the session on |
| `speaker` | _(empty)_ | Media player for the satellite speaker. Used to detect when TTS finishes |
| `therapist_persona` | `Doctor Portuondo` | Pipeline display name of the therapist |
| `therapy_variant` | `Therapy` | Pipeline variant suffix (combined with persona to form pipeline name) |
| `pipeline_select` | _(empty)_ | The satellite's pipeline selector entity |

</details>

<details><summary>② Session Configuration</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `session_type_default` | `individual` | Default session type (individual or couple) |
| `ask_session_type` | `true` | Ask "Individual or couple's session?" before starting |
| `timeout_minutes` | `45` | Auto-end session after this many minutes |
| `therapy_language` | _(empty)_ | Language override. Empty = therapist's natural language |
| `start_message` | `The session is open. What brings you here today?` | Opening TTS message for individual sessions |
| `start_message_couple` | `The session is open. I'm here for both of you. Who would like to start?` | Opening TTS message for couple sessions |
| `goodbye_detection` | `true` | Allow user to end session by saying goodbye |
| `therapist_end_session` | `true` | Allow therapist to end session via end_conversation tool |
| `voice_mood_during_therapy` | `true` | Whether voice mood modulation stays active during therapy |
| `therapy_trigger_phrases` | `need therapy, couples therapy, necesito terapia, terapia de pareja, emotional support, need to talk to someone` | Phrases that trigger therapy handoff from any agent |

</details>

<details><summary>②b Test Mode</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `test_mode_enabled` | `false` | When ON: 3-min timeout, skip privacy/budget gates, prefix memory keys with test_, announce state transitions via TTS |
| `test_single_cycle` | `false` | Exit the session after one mic open/close cycle |

</details>

<details><summary>③ Prompts</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `therapy_system_prompt` | _(see below)_ | Injected as extra_system_prompt every mic cycle. Defines session behavior rules |
| `couple_system_prompt` | _(see below)_ | Additional ESP block injected during couple sessions |
| `session_context_template` | _(see below)_ | Template with session continuity info. Variables: `{session_number}`, `{last_session_summary}`, `{session_type}`, `{user}` |
| `session_type_question` | `Individual or couple's session?` | Question asked to determine session type |
| `session_end_prompt` | _(see below)_ | Guidance for the therapist when ending the session naturally |
| `speaker_tracking_prompt` | _(see below)_ | ESP instructions for speaker identification in couple mode |

Default therapy system prompt:
> You are conducting a therapy session. Stay focused on the patient. Do NOT hand off to other agents unless the user explicitly asks. Do NOT proactively route during therapy. The session stays with you. If the conversation drifts to non-therapy topics, gently redirect. After each patient turn, call save_therapy_turn with the speaker name and a brief summary of what they said.

</details>

<details><summary>④ Privacy & Memory</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `privacy_tier` | `t1` | Identity confidence tier required (off/t1/t2/t3). T1 recommended for therapy |
| `privacy_gate_person` | _(empty)_ | Person entity for identity confidence check |
| `budget_floor` | `20` | Minimum remaining LLM budget %. Lower than other features because therapy is high-value |
| `memory_scope_individual` | `user` | Memory scope for individual therapy sessions |
| `memory_scope_couple` | `couple` | Memory scope for couple therapy sessions |
| `session_memory_expiration` | `0` | Days until session summaries expire. 0 = never |
| `auto_generate_report` | `false` | Automatically generate a .md report when session ends |
| `report_output_dir` | `/config/www/therapy_reports` | Directory for .md report files |

</details>

<details><summary>⑤ Infrastructure</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `use_dispatcher` | `true` | Resolve TTS voice via the AI dispatcher |
| `tts_voice` | _(empty)_ | TTS entity used when dispatcher is disabled |
| `silence_media_url` | _(empty)_ | URL to a silent audio file for echo-free mic reopen |
| `suppress_toggles` | `[]` | Input booleans to turn OFF during therapy. Restored on session end |
| `continuous_conversation_entity` | `input_boolean.ai_continuous_conversation_active` | Input boolean that keeps the mic cycling |
| `follow_me_entity` | _(empty)_ | Input boolean for follow-me notification system |
| `voice_mood_entity` | _(empty)_ | Input boolean for voice mood modulation |

</details>

<details><summary>⑥ Couple Mode</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `couple_users` | _(empty)_ | Comma-separated user slugs for couple session |
| `speaker_id_phrases` | _(empty)_ | Phrases users say to identify themselves |
| `couple_directed_questions` | `true` | Therapist can address specific person by name |
| `turn_history_size` | `15` | Max recent turns to include in ESP for couple mode |

</details>

<details><summary>⑦ Schedule</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `schedule_enabled` | `false` | Enable scheduled therapy sessions |
| `scheduled_time` | `20:00:00` | Time to start scheduled sessions |
| `scheduled_days` | all days | Days of the week for scheduled sessions |

</details>

## Technical Notes

- **Mode:** `single` / `max_exceeded: silent` -- only one therapy session at a time
- **Continuous loop:** Repeats while timeout not reached, toggle ON, budget above floor, continuous conversation active, no-speech count < 3, TTS fail count < 3
- **No-speech detection:** 3-strike exit. If satellite cycle completes in < 12 seconds, increments counter. Longer interactions reset it
- **Pipeline switch:** Saves current pipeline, switches to therapy variant, registers restore with voice_handoff for automatic recovery
- **ESP injection:** Extra system prompt rebuilt every mic cycle with session context, couple turn history, and active speaker
- **Test mode:** 3-minute timeout, skips privacy/budget gates, prefixes memory keys, announces state transitions, optional single-cycle exit
- **All pyscript/service actions** use `continue_on_error: true`

## Author

**madalone**

## License

See [LICENSE](../../LICENSE) in the repository root.
