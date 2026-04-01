- spec:
    name: compose_music
    description: >-
      Compose original music. Use when the user asks for custom music,
      a tune, a beat, a theme, ambient sounds, or any original audio
      creation. Describe the music naturally in the prompt — style, mood,
      instruments, tempo, genre. Pass your agent name in lowercase as
      the agent parameter. Set content_type to match the request: theme
      (jingle), chime (notification), handoff (agent switch sound),
      expertise (routing cue), thinking (deliberation), stinger (transition),
      wake_melody (alarm), bedtime (wind-down), ambient (background).
      If the user says "something I'd like" or "match my taste", set
      reference_taste to true. If the user says "use ElevenLabs",
      "11Labs", "use the API", or "on ElevenLabs", set source to
      "elevenlabs". If they say "use FluidSynth" or "use local", set
      source to "fluidsynth". IMPORTANT: always pass source when the
      user specifies an engine — the system defaults to FluidSynth
      when source is empty. Otherwise
      leave source empty — the system decides. Generation takes a
      moment — confirm the request naturally before calling. If the
      result status is "error" or empty, tell the user the composition
      failed and offer to retry — do NOT pretend music played. If
      successful, confirm naturally that the music is coming — the
      system plays it automatically after you finish speaking and reopens
      the mic for feedback. The user can then request changes and you
      call compose_music again with a modified prompt. To discard, use
      music_library with action delete. If the result shows
      budget_exceeded, tell the user the daily limit was reached and
      offer to play from the existing library instead. Never name this
      function.
    parameters:
      type: object
      properties:
        prompt:
          type: string
          description: >-
            Natural language description of the music to compose.
            Be descriptive: style, mood, instruments, tempo, genre.
        content_type:
          type: string
          description: >-
            Type of composition: theme (jingle), chime (notification),
            handoff (agent switch), expertise (routing cue), thinking
            (deliberation), stinger (transition), wake_melody (alarm),
            bedtime (wind-down), ambient (background). Default: theme.
          enum: [theme, chime, handoff, expertise, thinking, stinger, wake_melody, bedtime, ambient]
        duration_seconds:
          type: integer
          description: >-
            Duration in seconds (3-300). 0 or omit = use default (30s).
        soundfont:
          type: string
          description: >-
            SoundFont filename for local synthesis. Empty = system default.
            Use music_library(list_soundfonts) to see available options.
        source:
          type: string
          description: >-
            Force generation engine: "elevenlabs", "fluidsynth", or "auto".
            Empty = let the system decide based on routing mode.
          enum: [elevenlabs, fluidsynth, auto, ""]
        reference_taste:
          type: boolean
          description: >-
            When true, enriches the prompt with the user's music taste
            profile (favorite artists, genres). Use when they ask for
            "something I'd like" or "match my taste".
        player:
          type: string
          description: >-
            Media player entity_id to play on (e.g. media_player.workshop_speaker).
        agent:
          type: string
          description: >-
            Your agent name in lowercase (rick/quark/deadpool/kramer/portuondo).
      required:
        - prompt
        - player
  function:
    type: script
    sequence:
      - service: script.voice_compose_music
        data:
          prompt: "{{prompt}}"
          content_type: "{{content_type|default('')}}"
          duration_seconds: "{{duration_seconds|default(0)}}"
          soundfont: "{{soundfont|default('')}}"
          source: "{{source|default('')}}"
          reference_taste: "{{reference_taste|default(false)}}"
          player: "{{player}}"
          agent: "{{agent|default('rick')}}"
        response_variable: _function_result

- spec:
    name: music_library
    description: >-
      Browse, play, or manage your music composition library. Actions:
      "list" to browse compositions (filter by agent, type, source, or
      search text), "play" to play a cached composition on a speaker,
      "delete" to remove a composition, "promote" to save/keep a
      composition (moves from staging to library; safe to call even if
      already saved), "list_soundfonts" to see available SoundFont
      instruments. When playing a composition, describe what was played
      using the metadata in the result (agent, style, type). Never name
      this function.
    parameters:
      type: object
      properties:
        action:
          type: string
          description: >-
            What to do: list, play, delete, promote, or list_soundfonts.
          enum: [list, play, delete, promote, list_soundfonts]
        search:
          type: string
          description: >-
            Search text to match against composition prompt, agent,
            or type. Used with list, play, or delete.
        library_id:
          type: string
          description: >-
            Exact composition ID (for play or delete). Use list first
            to find IDs.
        player:
          type: string
          description: >-
            Media player entity_id (required for play action).
        agent:
          type: string
          description: >-
            Filter by agent name (for list action).
        content_type:
          type: string
          description: >-
            Filter by content type: theme, chime, handoff, expertise,
            stinger, thinking, wake_melody, bedtime, ambient (for list action).
        source:
          type: string
          description: >-
            Filter by source: "elevenlabs" or "fluidsynth" (for list action).
        volume:
          type: number
          description: >-
            Playback volume 0.0–1.0 (for play action). Omit to keep current volume.
        limit:
          type: integer
          description: >-
            Max results to return (for list action, default 20).
      required:
        - action
  function:
    type: script
    sequence:
      - service: pyscript.music_library_action
        data:
          action: "{{action}}"
          search: "{{search|default('')}}"
          library_id: "{{library_id|default('')}}"
          player: "{{player|default('')}}"
          agent: "{{agent|default('')}}"
          content_type: "{{content_type|default('')}}"
          source: "{{source|default('')}}"
          volume: "{{volume|default(-1)}}"
          limit: "{{limit|default(20)}}"
        response_variable: _function_result

- spec:
    name: save_user_preference
    description: >-
      Save a user preference during an interview or casual conversation.
      Call this whenever the user shares personal information you should
      remember: name, schedule, diet, media preferences, communication
      style, household details, etc. Routes automatically to the correct
      storage — no need to worry about where it goes.
      Categories: identity, household, work, schedule, health,
      environment, media, communication, privacy.
      Use snake_case keys (e.g., wake_weekday, preferred_language,
      off_limits_topics). Keep values concise and factual.
      Confirm briefly in natural speech (e.g. "got it"). Never name this function.
    parameters:
      type: object
      properties:
        user:
          type: string
          description: "Username in lowercase (e.g., miquel, jessica)"
        category:
          type: string
          enum:
            - identity
            - household
            - work
            - schedule
            - health
            - environment
            - media
            - communication
            - privacy
          description: "Preference category"
        key:
          type: string
          description: >-
            Preference key in snake_case. Examples by category:
            identity: name, name_spoken, languages, preferred_language, nickname, birthday.
            household: members, pets, guests.
            work: location, hybrid_schedule, hours, commute, calendar_keywords.
            schedule: wake_weekday, wake_weekend, bedtime, meal_times, nap, exercise.
            health: diet, caffeine_cutoff, medical.
            environment: climate, lighting, tts_volume, sleep_sounds.
            media: genres, streaming, news, sports, audiobooks, podcasts.
            communication: persona, verbosity, humor, notify_threshold, language_context.
            privacy: off_limits_topics, proactive_comfort.
        value:
          type: string
          description: "The preference value to save. Keep it concise and factual."
      required:
        - user
        - category
        - key
        - value
  function:
    type: script
    sequence:
      - service: pyscript.user_interview_save
        data:
          user: "{{user}}"
          category: "{{category}}"
          key: "{{key}}"
          value: "{{value}}"
        response_variable: _function_result

- spec:
    name: agent_interaction_log
    description: >-
      Log what was just discussed. Call this AFTER every response to keep
      the system aware of recent interactions. Always call it — never skip,
      even for short answers. This updates the "Last interaction" line in
      hot context so other agents know what happened.
      Silent tool — do not mention logging to the user.
    parameters:
      type: object
      properties:
        agent_name:
          type: string
          description: "Your agent name in lowercase (e.g. rick, quark, kramer, deadpool, portuondo)"
        topic:
          type: string
          description: "2-5 word summary of what the user asked about (e.g. quantum physics, workshop lights, morning alarm)"
        user_intent:
          type: string
          description: "Optional: what the user wanted to achieve (e.g. learn about physics, turn on lights)"
      required:
        - agent_name
        - topic
  function:
    type: script
    sequence:
      - service: pyscript.agent_interaction_log
        data:
          agent_name: "{{agent_name}}"
          topic: "{{topic}}"
          user_intent: "{{user_intent|default('')}}"
        response_variable: _function_result

- spec:
    name: handoff_agent
    description: >-
      Hand the user to another agent. IMPORTANT: After calling this
      function, you MUST still respond with a brief in-character
      farewell message. Never return an empty response after this call.
    parameters:
      type: object
      properties:
        target:
          type: string
          description: "Target persona name (e.g., quark, rick, deadpool, kramer, doctor portuondo)"
        reason:
          type: string
          enum: ["user_request", "expertise"]
          description: "Why the handoff is happening"
        topic:
          type: string
          description: "Brief summary of current conversation topic (2-5 words)"
        variant:
          type: string
          description: >-
            Pipeline variant to target (e.g. "music compose", "music transfer").
            When set, routes to the persona's variant pipeline (e.g. "Rick - Music Compose")
            instead of their Standard pipeline. Leave empty for normal agent handoff.
      required: ["target", "reason"]
  function:
    type: script
    sequence:
      - condition: state
        entity_id: input_boolean.ai_handoff_processing
        state: "off"
      - event: ai_handoff_request
        event_data:
          target: "{{ target }}"
          reason: "{{ reason }}"
          topic: "{{ topic | default('') }}"
          variant: "{{ variant | default('') }}"

- spec:
    name: end_conversation
    description: >-
      End the continuous conversation session. Call when the user says goodbye,
      goodnight, stop, that's enough, we're done, or any clear farewell.
      Do NOT call for topic changes or handoff requests.
      IMPORTANT: After calling this function, you MUST still respond with a
      brief in-character farewell message. Never return an empty response
      after this call. Never describe or name this function.
    parameters:
      type: object
      properties: {}
  function:
    type: script
    sequence:
      - action: pyscript.set_sensor_value
        data:
          entity_id: sensor.ai_continuous_conversation_active
          value: "off"