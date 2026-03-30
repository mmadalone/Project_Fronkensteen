# Home Assistant Style Guide — Music Assistant Patterns

Section 7 — MA players, play_media, TTS duck/restore, volume sync, voice bridges, and multi-room coordination.

---

## 7. MUSIC ASSISTANT PATTERNS

> **Compatibility:** Patterns in this section are verified against **Music Assistant 2.7** (December 2025). MA has undergone significant API changes between major versions — `enqueue` modes, `radio_mode` behavior, and service parameters may differ in older or future versions. When upgrading MA, re-verify these patterns against the current MA docs.
>
> **MA 2.7 notable changes:** User management with per-user music providers and speaker permissions (may affect which players are visible per profile). Sendspin protocol for synchronized multi-room streaming (see §7.10). AirPlay 2 as a full player provider with multi-room sync. Remote streaming via WebRTC/Nabu Casa. Smart crossfade (BPM-aware track transitions). Scrobbling support (LastFM, ListenBrainz, Subsonic). DSP presets for per-player audio configuration. Spotify Connect and AirPlay as external audio sources — MA can receive streams and redistribute to all players.

Music Assistant (MA) is the primary music integration. It runs as a separate server and exposes its own `media_player` entities and services. These patterns cover targeting, queue management, TTS interruption/resume, and multi-room coordination.

### 7.1 MA players vs generic media_players
MA exposes its own `media_player` entities alongside the underlying platform players (Alexa, ESPHome, Sonos, etc.). Always target the **MA player entity** when controlling music — not the underlying platform entity.

**Blueprint input selectors MUST filter by integration:**

```yaml
target_player:
  name: Music Assistant player
  description: The MA speaker to play on.
  selector:
    entity:
      filter:
        - integration: music_assistant
          domain:
            - media_player
```

When a blueprint needs both MA players and platform players (e.g., Alexa for volume sync), use separate inputs with separate filters:

```yaml
alexa_players:
  name: Alexa media players
  selector:
    entity:
      filter:
        - integration: alexa_media
          domain:
            - media_player
      multiple: true

ma_players:
  name: Music Assistant players (same order as Alexa players)
  selector:
    entity:
      filter:
        - integration: music_assistant
          domain:
            - media_player
      multiple: true
```

> 📋 **QA Check CQ-9:** Actions targeting media players from blueprint inputs must include availability guards (`state != unavailable`) before use. See `09_qa_audit_checklist.md`.

```yaml
# Availability guard — place before any action targeting the player
- alias: "Verify player is available"
  condition: template
  value_template: "{{ states(player) not in ['unavailable', 'unknown'] }}"
```

> **ESPHome player reliability caveat:** MA players backed by ESPHome devices (including Voice Preview Edition satellites) can exhibit playback reliability issues — dropped streams, delayed responses to play/pause commands, and occasional failure to resume after TTS interruption. These issues stem from the ESPHome media player component's limited buffering and network handling compared to native targets like Sonos, Chromecast, or DLNA receivers. For critical automations (alarms, announcements), build in retry logic or verify playback state after issuing commands. For music-follow-me patterns (§7.6), prefer non-ESPHome targets when available.

> **Player provider landscape (MA 2.7+):** MA supports a wide range of player providers: Alexa (via Alexa Media Player), Sonos, Chromecast/Google Cast, DLNA, ESPHome, Snapcast, SLIMPROTO, and — as of 2.7 — AirPlay 2 and Sendspin. AirPlay 2 speakers (including HomePods) now appear as full MA player providers with multi-room sync support, though behavior varies by device — check MA docs for limitations. Sendspin is an open-source protocol by the Open Home Foundation for synchronized multi-room streaming with metadata (album art, visualizations). It works on Voice PE satellites (beta firmware), web browsers, Google Cast devices (experimental), and custom ESPHome hardware. For automations, Sendspin players are targeted the same way as any other MA player — no special service calls needed. When using Sendspin on Cast devices, a separate player entity (`PlayerName (Sendspin)`) appears alongside the standard Cast player — use the Sendspin entity for cross-protocol sync groups.

### 7.2 `music_assistant.play_media` — not `media_player.play_media`
Always use the MA-specific play action. The generic `media_player.play_media` lacks MA features and may not resolve media correctly.

**Correct pattern:**

```yaml
- alias: "Play radio on target speaker"
  action: music_assistant.play_media
  target:
    entity_id: "{{ target_player }}"
  data:
    media_id: "Radio Klara"
    media_type: radio
    enqueue: replace
```

**Available `enqueue` modes:**

| Mode | Behavior | Use when... |
|---|---|---|
| `replace` | Clear queue, play immediately | Starting a new radio stream or replacing current content |
| `add` | Append to end of queue | Adding tracks to an existing session |
| `next` | Insert after current track | Queueing something to play next without interrupting |
| `play` | Play immediately, keep rest of queue | Starting playback of a specific item within an existing queue |
| `replace_next` | Replace upcoming queue items but keep current track playing | Changing what comes next without interrupting the current track |

**`radio_mode` parameter** — controls continuous playback:

```yaml
# Force continuous playback regardless of player settings
- action: music_assistant.play_media
  target:
    entity_id: "{{ target_player }}"
  data:
    media_id: "{{ chosen_media_id }}"
    enqueue: play
    radio_mode: true  # Keeps adding tracks when queue ends
```

> **Provider caveat:** Radio mode relies on the music provider's ability to generate similar-track recommendations. Streaming providers (Spotify, Qobuz, Tidal) generally support this well. Local-only libraries without metadata enrichment may produce poor or no recommendations, causing the queue to simply stop when it runs out. Test radio mode with your specific provider before relying on it in automations.

Expose `radio_mode` as a user choice, not a hardcoded value:

```yaml
radio_mode:
  name: Radio mode (Don't stop the music)
  selector:
    select:
      options:
        - Use player settings
        - Always
        - Never
  default: Use player settings
```

Then conditionally include it in the data payload. **Use a `choose` block** rather than a templated `data:` dict — it's more robust and avoids YAML/Jinja dict coercion issues across HA versions:

```yaml
- alias: "Play media with radio mode preference"
  choose:
    - alias: "Radio mode: Always"
      conditions:
        - condition: template
          value_template: "{{ radio_mode_value == 'Always' }}"
      sequence:
        - action: music_assistant.play_media
          target:
            entity_id: "{{ target_player }}"
          data:
            media_id: "{{ media_id_value }}"
            media_type: "{{ media_type_value }}"
            enqueue: "{{ enqueue_mode_value }}"
            radio_mode: true

    - alias: "Radio mode: Never"
      conditions:
        - condition: template
          value_template: "{{ radio_mode_value == 'Never' }}"
      sequence:
        - action: music_assistant.play_media
          target:
            entity_id: "{{ target_player }}"
          data:
            media_id: "{{ media_id_value }}"
            media_type: "{{ media_type_value }}"
            enqueue: "{{ enqueue_mode_value }}"
            radio_mode: false

  default:
    - alias: "Radio mode: Use player settings"
      action: music_assistant.play_media
      target:
        entity_id: "{{ target_player }}"
      data:
        media_id: "{{ media_id_value }}"
        media_type: "{{ media_type_value }}"
        enqueue: "{{ enqueue_mode_value }}"
```

Yes, it's more verbose than a templated dict. But each branch is valid YAML with proper `alias` labels, shows up cleanly in traces, and won't break if HA's template engine changes how it coerces dicts.

**`media_type` parameter** — helps MA disambiguate when a name could match multiple types:

Valid values: `playlist`, `album`, `track`, `artist`, `radio`. There is no `auto` value — if you omit `media_type` entirely, MA will attempt to guess the type from the `media_id` string, but this is unreliable for ambiguous names. Always specify `media_type` explicitly when possible. For blueprint inputs, expose this as a dropdown.

**Other MA-specific actions:**

Beyond `music_assistant.play_media`, MA exposes several actions that are useful in automations and scripts. These are not covered in detail here but should be used where appropriate instead of reinventing them with templates:

| Action | Purpose | Example use case |
|---|---|---|
| `music_assistant.play_announcement` | Play an audio URL as an announcement with automatic duck/restore | TTS-like notifications over active music without manual volume management |
| `music_assistant.transfer_queue` | Move the active queue from one player to another | Follow-me music triggered by presence sensors (§7.6) |
| `music_assistant.search` | Search MA library and all providers programmatically | Building dynamic dashboards, voice search results |
| `music_assistant.get_library` | Query the MA library with filters (type, limit, sort) | Random playlist generation, listing favorites |

**Quick-reference YAML for the less common actions:**

```yaml
# Transfer queue — move playback from one player to another
- alias: "Transfer music to kitchen"
  action: music_assistant.transfer_queue
  data:
    source: media_player.ma_living_room
    target: media_player.ma_kitchen

# Get library items — query MA library with filters
- alias: "Fetch 10 recent playlists"
  action: music_assistant.get_library
  data:
    media_type: playlist
    limit: 10
  response_variable: library_results
```

> **`play_announcement` vs manual duck/restore:** If your use case is simply playing a notification sound or TTS URL over active music, `play_announcement` handles the volume ducking and restoration natively — no helpers, no flags, no race conditions. The manual duck/restore pattern in §7.4 is still needed for complex multi-step TTS flows (e.g., alarm sequences with snooze logic), but for simple one-shot announcements, prefer the MA-native action.

### 7.3 Stop vs Pause — when to use which

| Action | What happens | Queue preserved? | Use when... |
|---|---|---|---|
| `media_player.media_stop` | Stops playback, clears active state | No — queue is gone | Shutting down completely, TTS interruption you don't want to resume |
| `media_player.media_pause` | Pauses playback in place | Yes — resume with `media_play` | Temporary interruption, voice interaction, TTS duck/restore |

**Rule of thumb:** If there's any chance you'll want to resume, use `pause`. Only use `stop` when you're done-done.

For "stop radio" voice commands, expose the choice as a blueprint input:

```yaml
also_pause_instead_of_stop:
  name: Pause instead of stop
  description: >
    If enabled, players will be paused instead of stopped.
    This preserves the queue so playback can be resumed later.
  default: false
  selector:
    boolean: {}
```

### 7.4 TTS interruption and resume (duck/restore pattern)
When TTS needs to speak over active music, the automation must duck the music volume, speak, then restore. This is the single most common source of bugs in MA blueprints.

> **Note:** All blueprints MUST delegate ducking to the centralized `duck_manager` via `tts_queue_speak` (§14.5 Pattern 8). As of 2026-03-20, no blueprint-level inline ducking remains — NFM, EFM, and 3 other blueprints were fully consolidated. The manual pattern below is for understanding the mechanics only. Do not reimplement it in new blueprints.

**The ducking flag pattern:**

Use a shared `input_boolean` (e.g., `input_boolean.voice_pe_ducking`) as a coordination flag. Set it ON before ducking, OFF after restoring. Other automations (like volume sync) check this flag and pause their behavior.

```yaml
# Volume sync blueprint checks this before syncing
- condition: template
  alias: "Voice PE ducking not active"
  value_template: "{{ states(ducking_flag_entity) | default('off') != 'on' }}"
```

**Volume save → duck → TTS → restore pattern:**

```yaml
variables:
  player: !input media_player
  original_volume: "{{ state_attr(player, 'volume_level') | float(0.4) }}"
  tts_volume: !input tts_volume

actions:
  # 0) Log the ducking cycle for observability
  - alias: "Log duck/restore start"
    action: logbook.log
    data:
      name: "Duck/Restore"
      message: "Ducking {{ player }} from {{ original_volume }} to {{ tts_volume }}"

  # 1) Set ducking flag — pauses volume sync and other watchers
  - alias: "Set ducking flag"
    action: input_boolean.turn_on
    target:
      entity_id: !input ducking_flag

  # 2) Save what's playing and duck volume
  - alias: "Duck volume for TTS"
    action: media_player.volume_set
    target:
      entity_id: "{{ player }}"
    data:
      volume_level: "{{ tts_volume }}"

  # 3) Speak the TTS message
  - alias: "Speak TTS"
    action: tts.speak
    target:
      entity_id: !input tts_engine
    data:
      media_player_entity_id: "{{ player }}"
      message: "{{ tts_message }}"

  # 4) Wait for TTS to finish — ElevenLabs may still be streaming
  #    even when the player looks idle
  - alias: "Post-TTS buffer"
    delay:
      seconds: "{{ post_tts_delay | int(5) }}"

  # 5) Restore volume — continue_on_error ensures the ducking flag
  #    always gets cleared even if the player is unavailable.
  - alias: "Restore volume after TTS"
    action: media_player.volume_set
    target:
      entity_id: "{{ player }}"
    data:
      volume_level: "{{ original_volume }}"
    continue_on_error: true

  # 6) Clear ducking flag
  - alias: "Clear ducking flag"
    action: input_boolean.turn_off
    target:
      entity_id: !input ducking_flag
```

**What wrong duck/restore ordering looks like (the #1 MA bug):**

```yaml
# ❌ BROKEN — three common duck/restore mistakes in one automation

# Mistake 1: Saving volume AFTER ducking
- action: media_player.volume_set
  target: { entity_id: "{{ player }}" }
  data: { volume_level: 0.15 }
- variables:
    saved_vol: "{{ state_attr(player, 'volume_level') | float(0.4) }}"
# saved_vol is now 0.15 (the ducked value), not the original.
# Restore sets volume to 0.15 — user's music is permanently quiet.

# Mistake 2: No ducking flag — volume sync fires during TTS
- action: media_player.volume_set   # Duck to 0.15
  data: { volume_level: 0.15 }
# Meanwhile: volume sync automation sees Alexa at 0.6, MA at 0.15,
# "corrects" MA back to 0.6 MID-TTS. User hears TTS at full blast.

# Mistake 3: Restoring volume without post-TTS delay
- action: tts.speak
  data: { message: "Welcome home" }
- action: media_player.volume_set   # Restore immediately
  data: { volume_level: "{{ saved_vol }}" }
# ElevenLabs streams asynchronously — tts.speak returns BEFORE audio finishes.
# Volume jumps to full while TTS is still talking. Blasts user's ears.
```

**Correct order (see full pattern above):** save volume → set flag → duck → TTS → delay → restore → clear flag.

**Critical gotcha — post-TTS delay:** Some TTS engines (particularly ElevenLabs custom) stream audio asynchronously. The `tts.speak` action returns *before* the audio finishes playing. Always include a configurable post-TTS delay before restoring volume or starting the next action. Expose this as an input (default 5 seconds).

**Race condition mitigation — alternatives to fixed delay:**

The fixed delay is the simplest approach but it's a guess — a 5-second delay is too long for "Welcome home" and too short for a 20-second weather report. Three alternatives in increasing order of robustness:

*1. `media_player.is_playing` polling (more accurate, more complex):*

```yaml
# After tts.speak, poll until the player stops playing (TTS finished)
- alias: "Wait for TTS to finish playing"
  repeat:
    while:
      - condition: state
        entity_id: "{{ player }}"
        state: "playing"
    sequence:
      - delay:
          seconds: 1
  # Safety cap — don't poll forever
  # Combine with a timeout wrapper if using in production:
  # wait_for_trigger with timeout: 30 on the player going idle
```

*Caveat:* State updates from the player are not instantaneous. Some players (especially ESPHome-backed ones) may briefly show "idle" between TTS audio chunks, causing premature restore. Add a 1–2 second post-polling buffer.

*2. `music_assistant.play_announcement` (MA-native, recommended for simple announcements):*

If your use case is "speak text over music and restore," MA's `play_announcement` action handles ducking, playback, and volume restoration natively — no helpers, no flags, no race conditions. This is the right answer for one-shot announcements:

```yaml
- action: music_assistant.play_announcement
  target:
    entity_id: "{{ ma_player }}"
  data:
    url: "{{ tts_audio_url }}"
    # MA handles: duck volume → play audio → wait for completion → restore volume
```

The catch: `play_announcement` takes an audio URL, not a text message. You'd need to call `tts.speak` first to generate the audio, extract the URL, then pass it — or use an automation that generates a media URL from text. For complex multi-step TTS flows (alarm with snooze logic, bedtime negotiator), the manual duck/restore pattern above is still necessary.

*3. Fixed delay with dynamic estimation (pragmatic middle ground):*

Estimate delay from message length. Rough formula: `characters / 15` seconds (average TTS speaking rate is ~15 characters/second for English). Cap between 3 and 30 seconds:

```yaml
post_tts_delay: >-
  {{ [3, ([tts_message | length / 15, 30] | min) | int] | max }}
```

**`assist_satellite.announce` as a duck-friendly alternative:**

When using Voice PE satellites, `assist_satellite.announce` puts the satellite into the "responding" state, which naturally triggers ducking automations. This is cleaner than manual duck/restore for simple announcements:

```yaml
- alias: "Announce via satellite (duck-friendly)"
  action: assist_satellite.announce
  target:
    entity_id: "{{ satellite_entity }}"
  data:
    message: "{{ announcement_text }}"
    preannounce: false
```

Use `assist_satellite.announce` for one-shot announcements. Use the manual duck/restore pattern for complex flows where you need fine-grained volume control or are targeting non-satellite speakers.

### 7.5 Volume sync between platforms (Alexa ↔ MA)
When MA plays through a platform speaker (e.g., Echo via Alexa Media Player), the volume can be changed on either side. Keeping them in sync requires careful handling.

> **⚠️ Stability caveat:** This entire pattern is a **workaround for a platform limitation** — Alexa Media Player and Music Assistant don't natively share volume state. The paired-list approach with tolerance thresholds and cooldowns is the most robust community-developed solution, but it is inherently fragile. Alexa Media Player integration updates, MA version bumps, or changes to how either platform reports `volume_level` can silently break sync. If volume sync stops working after an update, check: (1) whether `volume_level` attribute format changed (some updates switch between 0.0–1.0 and 0–100 scales), (2) whether state reporting latency increased (may need to bump cooldown), (3) whether the Alexa integration changed how it handles rapid volume commands. Periodically check if native volume sync has been added to either integration — if it has, rip this pattern out and use the native solution.

**Architecture:** One automation handles bidirectional sync with:
- Paired device lists (same-order indexing)
- Tolerance threshold to prevent feedback loops from rounding differences (recommended: 0.02–0.05, i.e., 2–5%)
- Cooldown delay to absorb rapid changes, e.g., holding the volume button (recommended: 1–3 seconds)
- Ducking flag check to skip sync during voice interactions
- Optional direction restriction (Alexa→MA only, MA→Alexa only, or both)

**Trigger pattern — attribute-based state triggers:**

```yaml
triggers:
  - alias: "Alexa volume changed"
    trigger: state
    entity_id: !input alexa_players
    attribute: volume_level
    id: alexa_vol_changed
    for:
      seconds: 1    # Debounce — waits for volume to settle (e.g., button hold)

  - alias: "MA speaker volume changed"
    trigger: state
    entity_id: !input ma_players
    attribute: volume_level
    id: ma_vol_changed
    for:
      seconds: 1
```

**Pair resolution pattern** — maps the triggering entity to its partner via list index:

```yaml
variables:
  alexa_list: !input alexa_players
  ma_list: !input ma_players
  changed_entity: "{{ trigger.entity_id }}"
  is_alexa_source: "{{ trigger.id in ['alexa_vol_changed', 'alexa_mute_changed'] }}"

  pair_index: >
    {% if is_alexa_source %}
      {{ alexa_list.index(changed_entity) if changed_entity in alexa_list else -1 }}
    {% else %}
      {{ ma_list.index(changed_entity) if changed_entity in ma_list else -1 }}
    {% endif %}

  target_entity: >
    {% set idx = pair_index | int(-1) %}
    {% if idx >= 0 %}
      {% if is_alexa_source %}{{ ma_list[idx] }}{% else %}{{ alexa_list[idx] }}{% endif %}
    {% else %}{{ '' }}{% endif %}
```

**Mode:** Always use `mode: queued` with `max: 4` and `max_exceeded: silent` for volume sync — rapid changes will stack up.

### 7.6 Presence-aware player selection
For "play music where I am" scenarios, use priority-ordered presence sensor ↔ player pairs:

```yaml
variables:
  presence_list: !input presence_sensors   # Ordered by priority
  player_list: !input target_players       # Same order
  fallback_player_entity: !input fallback_player

  detected_index: >
    {% set ns = namespace(idx=-1) %}
    {% for sensor in presence_list %}
      {% if ns.idx == -1 and states(sensor) | default('off') == 'on' %}
        {% set ns.idx = loop.index0 %}
      {% endif %}
    {% endfor %}
    {{ ns.idx }}

  target_player: >
    {% set idx = detected_index | int(-1) %}
    {% if idx >= 0 and idx < player_list | length %}
      {{ player_list[idx] }}
    {% elif fallback_player_entity %}
      {{ fallback_player_entity }}
    {% else %}{{ '' }}{% endif %}
```

**Rules for presence-aware targeting:**
- Order matters — first sensor with presence wins. Document this clearly in the input description.
- Always provide a fallback player option for when no presence is detected.
- Include `min_presence_time` input to filter out walk-throughs.
- Offer `protect_active_playback` option to skip rooms already playing something. **Bypass when enqueue is `replace`** — replace explicitly means "override what's playing," so the guard should not block it.
- Offer `stop_other_players` option to stop all other configured players before starting.

```yaml
# protect_active_playback — skip if target is already playing
# Bypass when enqueue is 'replace' — override intent is explicit
- alias: "Skip if target player is active"
  condition: template
  value_template: >-
    {% if not protect_active_playback %}
      true
    {% elif enqueue_mode == 'replace' %}
      true
    {% else %}
      {{ states(target_player) not in ['playing', 'buffering'] }}
    {% endif %}

# stop_other_players — stop all other configured players before starting
- alias: "Stop other players if configured"
  choose:
    - conditions: "{{ stop_other_players }}"
      sequence:
        - alias: "Stop all players except target"
          action: media_player.media_stop
          target:
            entity_id: >-
              {{ player_list | reject('eq', target_player) | list }}
```

### 7.7 Voice command → MA playback bridge (input_boolean pattern)
Alexa can't call MA services directly. Bridge with an `input_boolean` exposed to Alexa:

```
"Alexa, turn on Radio Klara"  →  input_boolean.radio_klara ON
        →  automation triggers  →  presence detection  →  MA play
```

**Critical: auto-reset the boolean FIRST, before conditions.**

If the boolean stays ON because a condition aborted the run, the next voice command won't toggle it (it's already ON). Reset it as the very first action:

```yaml
actions:
  # 0) Reset trigger boolean IMMEDIATELY — before any condition can abort
  #    ⚠️ When auto_off_flag is false, the boolean stays ON after triggering.
  #    This means the automation won't re-trigger on the next voice command
  #    until the user (or another automation) manually turns it OFF then ON.
  #    Only disable auto-reset when you have an explicit OFF mechanism elsewhere.
  - alias: "Auto-reset trigger boolean"
    choose:
      - conditions:
          - condition: template
            value_template: "{{ auto_off_flag }}"
        sequence:
          - action: input_boolean.turn_off
            target:
              entity_id: !input trigger_entity

  # 1) Now check conditions — safe to bail here, boolean is already reset
  - condition: template
    alias: "Person must be home (optional)"
    value_template: "{{ ... }}"
```

### 7.8 Voice playback initiation (LLM script-as-tool)

> **Recommended starting point:** The official [Music Assistant voice-support LLM Script Blueprint](https://github.com/music-assistant/voice-support/blob/main/llm-script-blueprint/llm_voice_script.yaml) handles the hard parts of this pattern — area resolution, shuffle detection, radio mode, and LLM prompt tuning. Import it and customize. The guidance below documents the architecture so you can extend it or build a compatible alternative.

When a user says *"Play Pink Floyd in the kitchen"*, the LLM needs a single, richly-described script it can call with structured fields. This is fundamentally different from the thin-wrapper control scripts in §7.9 — playback initiation requires the LLM to extract multiple parameters from a natural-language request and pass them as structured data.

**Architecture: one script, many fields.**

The script is exposed as an LLM tool. The conversation agent fills in the fields based on the voice request and calls the script directly — no intermediate automation needed.

```yaml
# Blueprint-generated script (simplified representation)
script:
  voice_play_music:
    alias: "Voice – Play Music"
    description: >-
      Play music based on a voice request. Arguments: media_type (required),
      media_id (required), artist, album, radio_mode, shuffle, area.
      media_id and media_type must always be supplied.
    mode: parallel
    max: 10
    fields:
      media_type:
        description: >-
          The type of music to play. Must be one of: artist, album,
          track, playlist, radio.
        required: true
        selector:
          select:
            options:
              - artist
              - album
              - track
              - playlist
              - radio
      media_id:
        description: >-
          The name or URI of the item to play.
          For "Play Dark Side of the Moon" → media_id: "Dark Side of the Moon".
        required: true
        selector:
          text:
      artist:
        description: >-
          When media_type is album or track, optionally restrict results
          by artist name for disambiguation.
          For "Play Greatest Hits by Queen" → artist: "Queen".
        required: false
        selector:
          text:
      album:
        description: >-
          When media_type is track, optionally restrict results
          by album name for disambiguation.
          For "Play Bohemian Rhapsody from A Night at the Opera" →
          album: "A Night at the Opera".
        required: false
        selector:
          text:
      radio_mode:
        description: >-
          Whether to enable radio mode (auto-fill queue with similar tracks).
          Set true when the user wants continuous similar music.
        required: false
        selector:
          boolean:
      shuffle:
        description: >-
          Whether to shuffle playback. Set true when the request
          mentions "shuffle", "random", or "mix up".
          "Shuffle songs by Muse" → true.
          "Play the artist Guns and Roses" → false.
        required: false
        selector:
          boolean:
      area:
        description: >-
          The area/room where music should play. If not specified by
          the user, the system resolves from the voice command source.
        required: false
        selector:
          area:
    sequence:
      # 1. Resolve target player from area (voice source or explicit)
      - variables:
          target_player: >
            {% set area_players = area_entities(area)
               | select('match', 'media_player.ma_')
               | list %}
            {{ area_players[0] if area_players else default_player }}
      # 2. Set shuffle before playback if requested
      - choose:
          - conditions: "{{ shuffle | default(false) }}"
            sequence:
              - alias: "Enable shuffle before playback"
                action: media_player.shuffle_set
                target:
                  entity_id: "{{ target_player }}"
                data:
                  shuffle: true
      # 3. Play via MA service
      - alias: "Play requested media via MA"
        action: music_assistant.play_media
        target:
          entity_id: "{{ target_player }}"
        data:
          media_id: "{{ media_id }}"
          media_type: "{{ media_type }}"
          artist: "{{ artist | default('') }}"
          album: "{{ album | default('') }}"
          radio_mode: "{{ radio_mode | default(false) }}"
          enqueue: replace
        continue_on_error: true
      # 4. Log playback request for observability
      - alias: "Log voice playback request"
        action: logbook.log
        data:
          name: "Voice Play Music"
          message: "{{ media_type }}: {{ media_id }} → {{ target_player }}"
      # 5. Additional actions hook (volume, scene, etc.)
```

**Key architectural decisions:**

**1. `mode: parallel, max: 10`.** Multiple household members can request music simultaneously on different speakers. This is NOT appropriate for control commands (§7.9), where `mode: single` or `mode: restart` prevents race conditions.

**2. Area-based player resolution.** The official blueprint resolves the target player from the voice satellite's area — if you say "play jazz" to the kitchen satellite, it finds the MA player assigned to the kitchen area. This is different from the priority-based resolution in §7.6 (which uses presence sensors) and the `expand() + selectattr` pattern in §7.9 (which finds currently-playing players). Area-from-voice is the right approach for playback initiation because nothing is playing yet.

**3. Artist/album disambiguation fields.** `music_assistant.play_media` accepts `artist` and `album` parameters to narrow ambiguous searches. Without them, "Play Greatest Hits" could match dozens of albums. The LLM extracts these from natural language — the field descriptions teach it how.

**4. Shuffle via `media_player.shuffle_set` BEFORE playback.** Shuffle is a queue property, not a play_media parameter. The script calls `media_player.shuffle_set` before `music_assistant.play_media`. The LLM detects shuffle intent from phrasing like "shuffle my jazz playlist" vs. "play my jazz playlist."

**5. Radio mode is a `play_media` parameter.** Unlike shuffle, radio mode IS passed directly to `music_assistant.play_media`. The blueprint offers three default strategies: "Use player settings" (omit the parameter), "Always on", or "Never on" — with per-request override from the LLM.

**Writing effective LLM tool descriptions:**

The `description` field on the script and on each field is the primary interface between the conversation agent and the tool. Write these for the LLM, not for humans.

```yaml
# GOOD — tells the LLM when and how to use it
description: >-
  Play music based on a voice request. media_id and media_type
  are always required and must always be supplied as arguments.

# BAD — vague, no usage guidance
description: "Plays music."
```

Per-field descriptions should include concrete examples of how to extract the value from natural language:

```yaml
# GOOD — teaches the LLM the extraction pattern
description: >-
  When media_type is album or track, restrict results by artist name.
  For "Play Greatest Hits by Queen" → artist: "Queen".
  For "Play some Beatles" → media_type: "artist", media_id: "The Beatles"
  (no separate artist field needed when media_type is already artist).

# BAD — states the obvious
description: "The artist name."
```

> **Tuning tip:** Different LLM integrations (OpenAI, Google, local models) interpret field descriptions differently. The official blueprint exposes per-field prompt inputs (`media_type_prompt`, `shuffle_prompt`, etc.) so you can tune descriptions without editing the blueprint YAML. If your LLM consistently misclassifies "play some jazz" as `media_type: artist` instead of `media_type: playlist` or `media_type: track` with `radio_mode: true`, adjust the `media_type_prompt` input.

### 7.8.1 Search → select → play pattern (disambiguation)

For ambiguous voice commands like "play something by Radiohead" or "play Greatest Hits," the LLM can use MA's `music_assistant.search` action to find candidates before committing to playback. This is especially useful when `media_type` is uncertain or the `media_id` could match multiple items.

**Pattern: search first, then play the best match.**

```yaml
script:
  voice_search_and_play:
    alias: "Voice – Search and Play Music"
    description: >-
      Search Music Assistant for a media item, then play the best result.
      Use this when the user's request is ambiguous and you're not sure
      of the exact media_type or media_id. Searches across all providers
      and returns structured results you can pick from.
    mode: single
    fields:
      query:
        description: "Search query — artist name, album title, track name, etc."
        required: true
        selector:
          text:
      media_type:
        description: >-
          Optional type hint to narrow search. If omitted, searches
          across all types (artist, album, track, playlist, radio).
        required: false
        selector:
          select:
            options: [artist, album, track, playlist, radio]
      area:
        description: "Target area for playback."
        required: false
        selector:
          area:
    sequence:
      # 1. Search MA library + providers
      - alias: "Search MA for matching media"
        action: music_assistant.search
        data:
          name: "{{ query }}"
          media_type: "{{ media_type | default('') }}"
          limit: 5
        response_variable: search_results
        continue_on_error: true

      # 2. Pick the best result (first match)
      - variables:
          best_match: >-
            {% if search_results and search_results | length > 0 %}
              {{ search_results[0] }}
            {% else %}
              {{ none }}
            {% endif %}

      # 3. Play the best match, or report nothing found
      - choose:
          - conditions: "{{ best_match is not none }}"
            sequence:
              - alias: "Play best search result"
                action: music_assistant.play_media
                target:
                  entity_id: "{{ target_player }}"
                data:
                  media_id: "{{ best_match.name | default(query) }}"
                  media_type: "{{ best_match.media_type | default('track') }}"
                  enqueue: replace
                continue_on_error: true
        default:
          - stop: "I couldn't find anything matching '{{ query }}' in Music Assistant."
            response_variable: result
```

**When to use search-first vs direct play:**
- **Direct `play_media`** (§7.8): Use when the LLM is confident about `media_type` and `media_id` — e.g., "play Dark Side of the Moon" is clearly an album.
- **Search-first**: Use when the query is vague ("play something chill"), when the `media_type` is ambiguous ("play Radiohead" could mean artist radio or a specific album), or when the LLM wants to confirm what's available before committing.

> **Note:** `music_assistant.search` is a `return_response` action — it returns structured data. The exact response schema depends on the MA version. Test with Developer Tools → Services to inspect the response structure for your MA installation.

**Additional actions hook:**

The official blueprint includes a configurable `additional_actions` input that runs after `play_media` succeeds. Use this to chain volume normalization, scene activation, or notification suppression:

```yaml
# Example additional_actions: set volume after playback starts
additional_actions:
  - delay:
      seconds: 1
  - action: media_player.volume_set
    target:
      entity_id: "{{ target_player }}"
    data:
      volume_level: 0.35
```

This replaces the need for a separate "play then set volume" script.

**Relationship to other patterns:**
- §7.2 (`radio_mode` and queue behavior) — radio mode mechanics apply here; the LLM script is just the voice entry point.
- §7.6 (presence-based targeting) — use area-from-voice for playback initiation, presence sensors for follow-me / automated playback.
- §7.7 (input_boolean bridge) — use for Alexa-initiated playback where LLM tools aren't available.
- §7.9 (voice media control) — complementary pattern for pause/stop/skip commands.
- §14.5 (Layer 4 tool scripts) — the playback script is one of several tools exposed to the conversation agent.

---

### 7.9 Voice media control (thin-wrapper pattern)

For LLM-driven voice agents that need to **control** already-playing media (pause, stop, skip), expose thin single-purpose wrapper scripts as tools. Each script calls a single centralized automation with a `command` variable.

This is the complement to §7.8 (playback initiation). The playback script starts music; these scripts control it after it's started. The LLM sees both the playback script and these control scripts as separate tools and picks based on user intent.

**Architecture: many thin scripts → one automation.**

```yaml
# Script (exposed as LLM tool)
script:
  voice_media_pause:
    alias: "Voice – Pause Active Media"
    description: >-
      Pauses whatever is currently playing on the nearest speaker.
      Call this when the user says "pause", "stop the music", or "shut up".
      Do NOT call this for volume changes — use voice_volume_set instead.
      Do NOT call this to start music — use voice_play_music instead.
    mode: single
    sequence:
      - action: automation.trigger
        target:
          entity_id: automation.voice_active_media_controls
        data:
          skip_condition: true
          variables:
            command: "pause_active"
```

**Standard commands:**

| Command | Behavior | Suggested LLM description keywords |
|---|---|---|
| `pause_active` | Find highest-priority playing/paused player, pause it | "pause", "stop the music", "quiet" |
| `stop_radio` | Pause all configured MA radio players | "stop radio", "turn off radio" |
| `shut_up` | Pause ALL playing candidates | "shut up", "silence", "stop everything" |

> **Why thin wrappers?** The LLM needs clean, single-purpose tools with unambiguous descriptions. A single "media_control" script with a `command` field forces the LLM to understand an internal routing enum. Separate scripts with descriptive names and focused descriptions let the LLM match intent to tool reliably. See §14.5 for the broader tool script philosophy.

**Priority resolution uses `expand()` with `selectattr`:**

```yaml
active_target: >
  {% set active = expand(candidates)
     | selectattr('state', 'in', ['playing', 'paused'])
     | list %}
  {{ active[0].entity_id if active | count > 0 else 'none' }}
```

This approach finds the **currently active** player — the right strategy for control commands where something is already playing. For playback initiation where nothing is playing yet, use area-based resolution instead (§7.8).

**Mode selection for control scripts:**

Control scripts should use `mode: single` (drop concurrent calls) or `mode: restart` (cancel previous, run new). Never `mode: parallel` — two simultaneous pause commands on the same player create race conditions. This is the opposite of §7.8's playback script, which uses `mode: parallel` because different users target different players.

**Writing control tool descriptions:**

Each thin wrapper needs a description that tells the LLM exactly when to call it AND when NOT to:

```yaml
# GOOD — clear boundaries
description: >-
  Pauses whatever is currently playing on the nearest speaker.
  Call this when the user says "pause", "stop the music", or "shut up".
  Do NOT call this for volume changes — use voice_volume_set instead.
  Do NOT call this to start playing music — use voice_play_music instead.

# BAD — ambiguous, overlaps with other tools
description: "Controls media playback."
```

The "do NOT call this for X" pattern is critical. Without negative examples, LLMs frequently call the wrong tool — especially for adjacent concepts like "stop" (pause) vs. "turn off" (power) vs. "lower" (volume).

The centralized automation handles all commands, validation, and optional persistent notifications for misconfiguration. The thin scripts give the LLM clean, single-purpose tools.

---

### 7.10 MA + TTS coexistence on Voice PE speakers
Voice PE satellites use their MA player for both music playback and TTS output. This creates an inherent conflict: TTS interrupts music, and both compete for the same audio output. Understanding which method to use in which scenario is critical.

> **Sendspin on Voice PE (MA 2.7+, beta firmware):** Voice PE satellites can now receive audio via the Sendspin protocol, which provides synchronized multi-room playback with metadata (album art, track info). When using Sendspin, the same TTS coexistence patterns below still apply — the satellite's `assist_satellite` entity still handles ducking, and `tts.speak` still targets the satellite's `media_player`. Sendspin does not change how TTS interacts with the speaker; it changes how *music* gets there. The decision matrix below remains valid regardless of whether music arrives via the standard MA player provider or via Sendspin.

**Decision matrix — choosing the right TTS method for Voice PE:**

| Scenario | Music playing? | Method | Why |
|---|---|---|---|
| One-shot announcement | Yes | `assist_satellite.announce` | Auto-ducks; satellite enters "responding" state |
| One-shot announcement | No | `tts.speak` | No ducking needed; simpler |
| Audio URL notification | Yes | `music_assistant.play_announcement` | MA handles duck/restore natively |
| Interactive conversation | Either | `assist_satellite.start_conversation` | Pipeline handles ducking automatically |
| Structured Q&A | Either | `assist_satellite.ask_question` | Pipeline handles ducking automatically |
| Complex multi-step flow (alarm) | Either | Manual duck/restore (§7.4) | Need fine-grained volume control per step |

**For alarm/wake-up flows (TTS then music):**
1. Set volume for TTS.
2. Speak via `tts.speak` targeting the satellite's media player.
3. Wait for snooze/stop input (with `wait_for_trigger` on mobile notification actions).
4. On timeout or snooze expiry, call a music script.
5. Restore volume to the music level.

**For goodnight/interactive flows (music after conversation):**
1. Use `assist_satellite.ask_question` for the interactive part — this naturally ducks music.
2. After the conversation completes, start music via `music_assistant.play_media`.
3. Set music volume separately from TTS volume — they're different use cases.

**For proactive messages over active music:**
1. Check if music is playing.
2. If yes, use `assist_satellite.announce` (duck-friendly) instead of `tts.speak`.
3. If no active music, `tts.speak` is fine.

**Concrete check-before-speak pattern:**

```yaml
- alias: "Choose TTS method based on active playback"
  choose:
    - alias: "Music is playing — use announce (auto-ducks)"
      conditions:
        - condition: state
          entity_id: "{{ satellite_media_player }}"
          state: "playing"
      sequence:
        - action: assist_satellite.announce
          target:
            entity_id: "{{ satellite_entity }}"
          data:
            message: "{{ tts_message }}"
            preannounce: false
  default:
    - alias: "Nothing playing — use tts.speak directly"
      action: tts.speak
      target:
        entity_id: !input tts_engine
      data:
        media_player_entity_id: "{{ satellite_media_player }}"
        message: "{{ tts_message }}"
```

> **Key insight:** The satellite's `media_player` entity and its `assist_satellite` entity are different things. `tts.speak` targets the `media_player`; `assist_satellite.announce` targets the `assist_satellite`. Get the entity IDs right or you'll get cryptic "entity not found" errors.

> **Alternative:** For audio URL announcements (not text-to-speech), `music_assistant.play_announcement` handles ducking and restoration natively without manual volume management. See the action reference in §7.2.

**Voice profile routing for ElevenLabs:**

```yaml
# Conditional voice_profile — only include options when profile is set
- choose:
    - alias: "TTS with voice_profile"
      conditions:
        - condition: template
          value_template: "{{ voice_profile | default('') | string | length > 0 }}"
      sequence:
        - action: tts.speak
          target:
            entity_id: !input tts_engine
          data:
            media_player_entity_id: "{{ player }}"
            message: "{{ message }}"
            options:
              voice_profile: !input voice_profile
  default:
    - action: tts.speak
      target:
        entity_id: !input tts_engine
      data:
        media_player_entity_id: "{{ player }}"
        message: "{{ message }}"
```

This pattern avoids sending an empty `voice_profile` to non-ElevenLabs TTS engines that would choke on an unexpected option.

### 7.11 Extra zone mappings for shared speakers
When multiple zones share a speaker (kitchen → workshop speaker, shower → bathroom speaker), use individual dropdown pairs instead of parallel lists.

**Complete implementation example — two extra zone slots:**

**Blueprint inputs:**

```yaml
input:
  # Primary zones (required)
  primary_sensors:
    name: "Primary presence sensors"
    selector:
      entity:
        domain: binary_sensor
        multiple: true
  primary_players:
    name: "Primary MA players (same order as sensors)"
    selector:
      entity:
        filter:
          - integration: music_assistant
            domain: [media_player]
        multiple: true

  # Extra zone 1 (optional)
  extra_sensor_1:
    name: "Extra zone 1 — Presence sensor"
    default:
    selector:
      entity:
        domain: binary_sensor
        multiple: false
  extra_player_1:
    name: "Extra zone 1 — Music Assistant player"
    description: >-
      The speaker for extra zone 1. Can be the same speaker as a primary zone
      (e.g., kitchen presence → workshop speaker).
    default:
    selector:
      entity:
        filter:
          - integration: music_assistant
            domain: [media_player]
        multiple: false

  # Extra zone 2 (optional)
  extra_sensor_2:
    name: "Extra zone 2 — Presence sensor"
    default:
    selector:
      entity:
        domain: binary_sensor
        multiple: false
  extra_player_2:
    name: "Extra zone 2 — Music Assistant player"
    default:
    selector:
      entity:
        filter:
          - integration: music_assistant
            domain: [media_player]
        multiple: false
```

**Variables — build the merged list, filtering out empty slots:**

```yaml
variables:
  extra_s1: !input extra_sensor_1
  extra_p1: !input extra_player_1
  extra_s2: !input extra_sensor_2
  extra_p2: !input extra_player_2
  primary_s: !input primary_sensors
  primary_p: !input primary_players

  extra_pairs: >-
    {% set pairs = [
      (extra_s1, extra_p1),
      (extra_s2, extra_p2)
    ] %}
    {% set ns = namespace(sensors=[], players=[]) %}
    {% for s, p in pairs %}
      {% if s and p %}
        {% set ns.sensors = ns.sensors + [s] %}
        {% set ns.players = ns.players + [p] %}
      {% endif %}
    {% endfor %}
    {{ {"sensors": ns.sensors, "players": ns.players} }}

  presence_list: "{{ primary_s + extra_pairs.sensors }}"
  player_list: "{{ primary_p + extra_pairs.players }}"
```

**Usage in presence-aware targeting (§7.6):**

```yaml
  # Now use presence_list and player_list exactly as in §7.6:
  detected_index: >-
    {% set ns = namespace(idx=-1) %}
    {% for sensor in presence_list %}
      {% if ns.idx == -1 and states(sensor) | default('off') == 'on' %}
        {% set ns.idx = loop.index0 %}
      {% endif %}
    {% endfor %}
    {{ ns.idx }}

  target_player: >-
    {% set idx = detected_index | int(-1) %}
    {% if idx >= 0 and idx < player_list | length %}
      {{ player_list[idx] }}
    {% else %}
      {{ fallback_player }}
    {% endif %}
```

This allows the same speaker to appear in multiple zones without list-ordering headaches. The kitchen sensor can map to the workshop speaker, and the workshop sensor can also map to the workshop speaker — both appear in the merged list, and the first presence match wins.

> 📋 **QA Check INT-3:** Music Assistant pattern completeness — verify media_type verification, enqueue modes, TTS duck/restore race condition, Alexa↔MA volume sync, search→select→play, MA+TTS coexistence, and extra zone mappings are all documented. See `09_qa_audit_checklist.md`.
