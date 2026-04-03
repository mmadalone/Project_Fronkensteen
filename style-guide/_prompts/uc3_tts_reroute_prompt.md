# Claude Code Prompt: UC3 Assist TTS Reroute to Room Speakers

## Goal
The Unfolded Circle Remote 3's onboard speaker is physically too small for
voice assistant audio. Build a mechanism that intercepts Assist pipeline TTS
responses triggered from the UC3 and plays them on the room speaker instead,
using the existing Fronkensteen TTS and presence infrastructure.

## The Architecture You're Working Inside
This is Project Fronkensteen. Read the README.md in the git repo root if you
haven't already. The relevant systems:

### TTS Queue (`pyscript/tts_queue.py`)
- 5-priority queue (emergency → ambient) with dynamic speaker discovery
- Reads zone-to-speaker mapping from a JSON config
- Injects voice mood tags (ElevenLabs v3 audio tags + stability) per-agent
- Fires `tts_queue_item_completed` events on playback finish
- Already handles speaker ranking, volume ducking, and caching
- **This is your primary delivery mechanism — do NOT bypass it**

### Duck Manager (`pyscript/duck_manager.py`)
- Refcount-based volume ducking coordinator (3 modes: volume, pause, both)
- Snapshot/restore with user-adjustment protection
- Auto-discovers Music Assistant volume aliases via entity registry
- Shared across 7+ automations via the refcount bypass watchdog

### Presence Identity (`pyscript/presence_identity.py`)
- Anchor-and-Track algorithm: FP2 zones + WiFi + voice satellite + Markov
- Already knows which room the user is in with confidence scoring
- Powers the 3-tier privacy gate and notification routing

### Notification Follow-Me (`notification_follow_me.yaml`)
- 4,800-line routing engine that already solves "which speaker for this user"
- LLM announcement generation, burst combining, multi-player ducking
- **Study its speaker selection logic — don't reinvent it**

### Agent Dispatcher (`pyscript/agent_dispatcher.py`)
- 7-priority routing engine for persona selection
- Dynamically discovers personas from Assist Pipelines

### Music Assistant Integration
- `music_assistant.play_announcement` handles ducking and resume natively
- Already the established pattern for TTS-over-speakers in this system
- Multi-room audio routing with follow-me presence detection

### Budget Tracking
- Every LLM call and TTS call is tracked per-agent
- Graceful degradation: ElevenLabs → HA Cloud TTS on budget exhaust
- Whatever you build must not add untracked cost

## The Problem (Verified)
- HA Assist pipelines have NO native "TTS output device" setting
- Audio always returns to the requesting device (confirmed — I was wrong
  about this initially, the user corrected me with receipts)
- The UC3 speaker is maxed at 100% and still faint as hell
- The proven workaround: intercept the TTS response URL after pipeline
  completion and play it on a real speaker

## Key Reference
GitHub Discussion `home-assistant/discussions/689` has a working script that:
1. Maps device names → speaker entities
2. Captures the TTS audio URL from pipeline events
3. Plays via `music_assistant.play_announcement` with room routing
4. Handles ducking and resume automatically

Study this, but adapt it to Fronkensteen's existing infrastructure rather
than reimplementing speaker selection from scratch.

## What to Build

### Step 1 — Recon (before writing any code)
- Read `pyscript/tts_queue.py` — understand the queue's speaker selection,
  zone config, and `tts_queue_item_completed` event structure
- Read the zone-to-speaker JSON config (find it via ripgrep for
  `zone.*speaker.*json` or `speaker.*mapping`)
- Read `pyscript/presence_identity.py` — understand how it resolves current
  room for the active user
- Check what `assist_pipeline` events look like — specifically `tts-end`
  event data and whether it contains the audio URL
- Identify how the UC3 appears in pipeline events (device_id from the
  `unfoldedcircle` integration)
- Read the notification_follow_me blueprint's speaker selection logic —
  it already maps presence → speaker, reuse that pattern
- Check existing automations/scripts to avoid conflicts

### Step 2 — Implementation
Two possible approaches — pick the one that fits cleaner:

**Option A — Pyscript service (preferred if it fits)**
Add a `uc3_tts_reroute` handler in an existing or new pyscript module that:
- Listens for `assist_pipeline` `tts-end` events where the source device
  matches the UC3's device_id
- Extracts the TTS audio URL from event data
- Resolves current room via `presence_identity` (already knows where user is)
- Routes the audio through `tts_queue` or directly via
  `music_assistant.play_announcement` to the room's speaker
- Respects budget state and duck manager

**Option B — Automation + script**
- Automation triggers on `assist_pipeline` event
- Calls a script that does the speaker resolution and playback
- If blueprint-worthy (reusable for anyone with a UC remote + Fronkensteen),
  make it a `madalone` namespace blueprint

### Step 3 — Integration points
- The UC3's tiny speaker will still play its own copy — that's fine, it's
  inaudible compared to a real speaker. No need to silence it.
- Register any new pyscript services with the system health sensor's
  service count validation
- If adding helpers, use the correct `helpers_input_*.yaml` file
- Follow Rules of Acquisition style guide for all code

## Paths
- HA config: `/Users/madalone/Library/Containers/nz.co.pixeleyes.AutoMounter/Data/Mounts/Home Assistant/SMB/config/`
- Project dir: `/Users/madalone/_Claude Projects/HA Master Style Guide/`
- Git repo: `/Users/madalone/_Claude Projects/Project_Fronkensteen/`
- Pyscript modules: `HA_CONFIG/pyscript/`
- Blueprints: `HA_CONFIG/blueprints/automation/madalone/` and `.../script/madalone/`
- Zone config: search for it — likely in `HA_CONFIG/www/` or `HA_CONFIG/pyscript/`

## Constraints
- Do NOT bypass the TTS queue for delivery — it handles priority, ducking,
  mood injection, and completion events that other systems depend on
- Do NOT reimplement speaker selection — presence_identity and the zone config
  already solve this
- Do NOT modify ESPHome YAML — this is UC3-specific
- Do NOT add untracked LLM or TTS costs
- Use HA MCP tools for file reads/writes
- Check for conflicts with existing automations before creating new ones
- The existing `notification_follow_me` refcount bypass system is shared
  across 7+ automations — respect the duck manager's state
