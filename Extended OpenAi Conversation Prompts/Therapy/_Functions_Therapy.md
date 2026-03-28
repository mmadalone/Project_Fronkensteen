- spec:
    name: memory_tool
    description: >-
      Store, retrieve, search, or delete long-term memories in a local
      SQLite database. Use this when the user asks you to remember
      something, recall something previously stored, search memories,
      or forget a specific memory. Memories persist across conversations
      and HA restarts. Memories with scope "user" are private to the
      active user. In search results, entries marked [restricted] belong
      to another user — acknowledge their existence but never reveal
      their content. If you receive an "identity_uncertain" response,
      ask the user to confirm who they are before saving personal data.
    parameters:
      type: object
      properties:
        operation:
          type: string
          enum: [set, get, search, forget]
          description: >-
            "set" to store a memory, "get" to recall by exact key,
            "search" to find by keyword, "forget" to delete.
        key:
          type: string
          description: >-
            The memory key or label. Use short, descriptive snake_case
            names like "wifi_password", "parking_spot", "dentist_address".
        value:
          type: string
          description: >-
            The value to store (only used with "set"). Keep it concise
            and useful — not a transcript, just the fact.
        scope:
          type: string
          enum: [user, household, session, couple]
          description: >-
            "user" for personal memories (default), "household" for
            shared info, "session" for temporary within one conversation,
            "couple" for couple therapy memories (visible to both partners).
        expiration_days:
          type: integer
          description: >-
            Days until the memory expires. 0 means never. Default is 180.
        tags:
          type: string
          description: >-
            Optional comma-separated tags for categorization,
            e.g. "home,network" or "car,parking".
        query:
          type: string
          description: >-
            Search query string (only used with "search" operation).
        search_limit:
          type: integer
          description: >-
            Max number of search results to return (1-50, default 5).
        owner:
          type: string
          description: >-
            Optional. The username this memory belongs to (e.g., miquel,
            jessica). Only set this if the user explicitly identifies
            themselves or if you received an identity_uncertain response
            and the user confirmed. Leave empty to auto-detect.
      required:
        - operation
        - key
  function:
    type: script
    sequence:
      - service: script.voice_memory_tool
        data:
          operation: "{{operation}}"
          key: "{{key|default('')}}"
          value: "{{value|default('')}}"
          scope: "{{scope|default('user')}}"
          expiration_days: "{{expiration_days|default(180)}}"
          tags: "{{tags|default('')}}"
          query: "{{query|default('')}}"
          search_limit: "{{search_limit|default(5)}}"
          owner: "{{owner|default('')}}"
        response_variable: _function_result

- spec:
    name: memory_related
    description: >-
      Explore memories related to a given memory key. Traverses the
      memory graph to find connected information. Call when the user
      asks "what else do you know about...", "what's related to...",
      or when you want to enrich context around a memory you just
      retrieved.
    parameters:
      type: object
      properties:
        key:
          type: string
          description: "The memory key to find relationships for"
        limit:
          type: integer
          description: "Max results (1-50, default 10)"
        depth:
          type: integer
          description: "Traversal depth: 1=direct links, 2=friends-of-friends, 3=max (default 1)"
      required:
        - key
  function:
    type: script
    sequence:
      - service: pyscript.memory_related
        data:
          key: "{{key}}"
          limit: "{{limit|default(10)}}"
          depth: "{{depth|default(1)}}"
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
      - action: input_boolean.turn_off
        target:
          entity_id: input_boolean.ai_continuous_conversation_active

- spec:
    name: save_therapy_turn
    description: >-
      Log who spoke and what they said. Call after each patient speaks.
      In couple mode, always identify the speaker. Silent tool — do not
      mention logging to the user.
    parameters:
      type: object
      properties:
        speaker:
          type: string
          description: "Who spoke (e.g., miquel, jessica)"
        content:
          type: string
          description: "Brief 5-10 word summary of what was said"
      required:
        - speaker
        - content
  function:
    type: script
    sequence:
      - service: pyscript.therapy_save_turn
        data:
          speaker: "{{speaker}}"
          content: "{{content}}"
        response_variable: _function_result

- spec:
    name: therapy_report
    description: >-
      Generate a therapy session report in markdown format. Call when the
      user asks for their session report, session summary, or session notes.
      Returns a confirmation. Never speak the file path aloud — just confirm
      that the report is ready.
    parameters:
      type: object
      properties:
        session_number:
          type: integer
          description: "Session number to report on. 0 = most recent."
      required: []
  function:
    type: script
    sequence:
      - service: pyscript.therapy_session_report
        data:
          session_number: "{{session_number|default(0)}}"
        response_variable: _function_result