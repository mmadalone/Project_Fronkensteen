# Voice Mood Modulation (v3 Audio Tag Pivot)

Shifts a character's ElevenLabs voice throughout the day using the two mechanisms v3 supports: the stability VoiceSettings parameter and audio tag prefixes (`[slurring]`, `[whispers]`, `[excited]`, etc.). Five configurable time blocks, each with a stability value and a tag prefix string. Values are written to `input_number` (stability) and `input_text` (tags) helpers that `tts_queue` and the patched `tts.py` read on every TTS call. One instance per character.

## How It Works

```
┌───────────────────────────────┐
│  TRIGGERS                      │
│  • Hourly time pattern (/1)   │
│  • HA startup                  │
└──────────────┬────────────────┘
               │
               ▼
┌───────────────────────────────┐
│  CONDITIONS                    │
│  • Per-instance enabled        │
│  • Global kill switch ON       │
└──────────────┬────────────────┘
               │ pass
               ▼
┌───────────────────────────────┐
│  Resolve current time block    │
│                                │
│  B5 (late night) ──► B1 ──►   │
│  B2 ──► B3 ──► B4 ──► B5     │
│  (B5 wraps past midnight)      │
└──────────────┬────────────────┘
               │
        ┌──────┴──────┐
        │             │
        ▼             ▼
┌────────────┐  ┌────────────┐
│  Write     │  │  Write     │
│  stability │  │  tag prefix│
│  to        │  │  to        │
│  input_    │  │  input_    │
│  number    │  │  text      │
└────────────┘  └────────────┘

  input_number.ai_voice_mood_{agent}_stability
  input_text.ai_voice_mood_{agent}_tags
```

## Features

- Five configurable time blocks with customizable boundary hours
- Per-block stability value (0.0 = Creative, 1.0 = Robust) for ElevenLabs v3 VoiceSettings
- Per-block audio tag prefix for v3 text injection (`[happy]`, `[whispers]`, `[slurring]`, etc.)
- Late night block (Block 5) wraps past midnight automatically
- One instance per character -- helper names derived from agent name
- Hourly refresh + HA startup trigger ensures values are always current
- Per-instance and global kill switches
- Agent conversation responses are NOT double-tagged (guard in `tts.py`: `"[" not in message`)

## Prerequisites

- Home Assistant 2024.6.0+
- ElevenLabs custom TTS component (patched `tts.py` v0.6.3+)
- Per-agent helpers (created for each character):
  - `input_number.ai_voice_mood_{agent}_stability`
  - `input_text.ai_voice_mood_{agent}_tags`
- `input_boolean.ai_voice_mood_enabled` (global kill switch)
- `pyscript/tts_queue.py` (reads stability + tags helpers at TTS time)

## Installation

1. Copy `voice_mood_modulation.yaml` to `config/blueprints/automation/madalone/`
2. Create the per-agent helper entities
3. Create automation: **Settings -> Automations -> Create -> Use Blueprint**
4. Create one instance per character (e.g., Rick, Quark, Deadpool)

## Configuration

<details><summary>① Character & Control</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `agent_name` | _(required)_ | Character identifier (e.g., "rick", "quark"). Used to construct helper entity names |
| `enabled` | `true` | Per-instance kill switch |
| `global_kill_switch` | `input_boolean.ai_voice_mood_enabled` | Boolean helper that gates all mood modulation system-wide |

</details>

<details><summary>② Time Block Boundaries</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `block_1_start` | `5` | Hour (0--23) when Block 1 (Early Morning) begins |
| `block_2_start` | `9` | Hour (0--23) when Block 2 (Morning) begins |
| `block_3_start` | `12` | Hour (0--23) when Block 3 (Afternoon) begins |
| `block_4_start` | `17` | Hour (0--23) when Block 4 (Evening) begins |
| `block_5_start` | `21` | Hour (0--23) when Block 5 (Late Night) begins. Wraps past midnight until Block 1 start |

</details>

<details><summary>③ Block 1: Early Morning</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `b1_stability` | `0.25` | ElevenLabs v3 stability (0=Creative, 1=Robust) |
| `b1_tags` | _(empty)_ | Audio tag prefix for non-agent TTS text. Empty = no prefix |

</details>

<details><summary>④ Block 2: Morning</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `b2_stability` | `0.35` | ElevenLabs v3 stability |
| `b2_tags` | _(empty)_ | Audio tag prefix |

</details>

<details><summary>⑤ Block 3: Afternoon</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `b3_stability` | `0.45` | ElevenLabs v3 stability |
| `b3_tags` | _(empty)_ | Audio tag prefix |

</details>

<details><summary>⑥ Block 4: Evening</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `b4_stability` | `0.30` | ElevenLabs v3 stability |
| `b4_tags` | _(empty)_ | Audio tag prefix |

</details>

<details><summary>⑦ Block 5: Late Night</summary>

| Input | Default | Description |
|-------|---------|-------------|
| `b5_stability` | `0.20` | ElevenLabs v3 stability |
| `b5_tags` | _(empty)_ | Audio tag prefix |

</details>

### Available Audio Tags (ElevenLabs v3)

**Emotions:** `[happy]`, `[sad]`, `[angry]`, `[annoyed]`, `[excited]`, `[sarcastic]`, `[curious]`, `[mischievously]`, `[surprised]`, `[appalled]`, `[thoughtful]`, `[crying]`

**Speech:** `[whispers]`, `[sighs]`, `[laughs]`, `[chuckles]`, `[snorts]`, `[wheezing]`, `[muttering]`, `[clears throat]`, `[exhales]`, `[exhales sharply]`, `[inhales deeply]`, `[swallows]`, `[gulps]`

**Pacing:** `[short pause]`, `[long pause]`

**Experimental:** `[slurring]`, `[sings]`, `[strong X accent]`

## Technical Notes

- **Mode:** `single` -- only one execution at a time
- **Trigger:** Hourly time pattern (`/1`) + HA startup. Ensures values are set on boot and refreshed each hour
- **Block resolution:** Current hour checked against boundaries in order: B5 (wraps midnight), then B4, B3, B2, B1
- **v3 pivot:** ElevenLabs v3 ignores `similarity_boost`, `style`, and `speed`. Voice modulation works through audio tags in text and the `stability` VoiceSettings parameter only
- **Double-tag guard:** `tts.py` checks `"[" not in message` before prepending tags, so agent responses that already contain tags are not double-tagged
- **Helper naming:** Stability written to `input_number.ai_voice_mood_{agent}_stability`, tags to `input_text.ai_voice_mood_{agent}_tags`

## Author

**madalone**

## License

See [LICENSE](../../LICENSE) in the repository root.
