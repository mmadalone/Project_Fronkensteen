- spec:
    name: execute_services
    description: Use this function to execute service of devices in Home Assistant.
    parameters:
      type: object
      properties:
        list:
          type: array
          items:
            type: object
            properties:
              domain:
                type: string
                description: The domain of the service
              service:
                type: string
                description: The service to be called
              service_data:
                type: object
                description: The service data object to indicate what to control.
                properties:
                  entity_id:
                    type: string
                    description: The entity_id retrieved from available devices. It
                      must start with domain, followed by dot character.
                required:
                - entity_id
            required:
            - domain
            - service
            - service_data
  function:
    type: native
    name: execute_services

- spec:
    name: stop_radio
    description: >-
      Stop or pause Music Assistant radio playback on all configured radio
      players. Call this when the user says "stop the radio", "turn off the
      radio", "kill the radio", "no more radio", or any variation of wanting
      radio specifically to stop. Do NOT use execute_services for radio
      control — always use this function instead.
    parameters:
      type: object
      properties: {}
      required: []
  function:
    type: script
    sequence:
      - service: script.voice_stop_radio

- spec:
    name: shut_up
    description: >-
      Pause ALL currently playing media in the house — music, radio, TV,
      Spotify, Alexa, everything. Call this when the user says "shut up",
      "shut the fuck up", "be quiet", "stop everything", "silence",
      "kill the sound", "kill all sound", or any variation of wanting ALL
      audio to stop immediately. Do NOT confuse with conversational insults
      — only use when the user wants audio to stop. Do NOT use
      execute_services for this — always use this function.
    parameters:
      type: object
      properties: {}
      required: []
  function:
    type: script
    sequence:
      - service: script.voice_shut_up

- spec:
    name: pause_media
    description: >-
      Pause whatever media is currently playing (context-aware). Call this
      when the user says "pause", "pause it", "stop the music", "pause the
      TV", "hold it", or any variation of wanting the currently active media
      to pause. Do NOT use execute_services with media_player.media_pause —
      always use this function instead. Do NOT use this for volume changes
      or for stopping radio specifically (use stop_radio for that).
    parameters:
      type: object
      properties: {}
      required: []
  function:
    type: script
    sequence:
      - service: script.voice_pause

- spec:
    name: web_search
    description: >-
      Use this function to search the web for current information,
      news, weather, sports scores, or anything the user asks about
      that requires up-to-date information from the internet.
    parameters:
      type: object
      properties:
        query:
          type: string
          description: The search query to look up on the web
      required:
        - query
  function:
    type: rest
    resource: "https://google.serper.dev/search"
    method: POST
    headers:
      X-API-KEY: "628ed8dd04da05b96e7299edeb133714b9fa3ea8"
      Content-Type: "application/json"
    payload: '{"q": "{{query}}", "num": 5}'
    value_template: >-
      {% set results = [] %}
      {% for item in value_json.get("organic", [])[:5] %}
        {% set results = results + [item.get("title", "") ~ ": " ~ item.get("snippet", "") ~ " (" ~ item.get("link", "") ~ ")"] %}
      {% endfor %}
      {% if value_json.get("answerBox") %}
        Answer: {{ value_json.answerBox.get("answer", value_json.answerBox.get("snippet", "")) }}
        ---
      {% endif %}
      {% if value_json.get("knowledgeGraph") %}
        {{ value_json.knowledgeGraph.get("title", "") }}: {{ value_json.knowledgeGraph.get("description", "") }}
        ---
      {% endif %}
      {{ results | join("\n") }}

- spec:
    name: memory_tool
    description: >-
      Store, retrieve, search, or delete long-term memories in a local
      SQLite database. Use this when the user asks you to remember
      something, recall something previously stored, search memories,
      or forget a specific memory. Memories persist across conversations
      and HA restarts.
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
          enum: [user, household, session]
          description: >-
            "user" for personal memories (default), "household" for
            shared info, "session" for temporary within one conversation.
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
    name: escalate_action
    description: >-
      Follow through on an escalation you threatened. Call this ONLY when
      you've already warned the user at least once and want to attempt the
      threatened action. There's a random probability gate — you might be
      bluffing. Types: persona_switch (hand conversation to another agent),
      play_media (play an attention-getting audio clip).
    parameters:
      type: object
      properties:
        action_type:
          type: string
          description: "Type of escalation"
          enum:
            - persona_switch
            - play_media
        target:
          type: string
          description: "For persona_switch: which agent to switch to"
          enum:
            - deadpool
            - quark
            - kramer
            - rick
            - doctor portuondo
        clip:
          type: string
          description: "For play_media: clip name (e.g. show_tune, ferengi_rules)"
      required:
        - action_type
  function:
    type: script
    sequence:
      - event: ai_escalation_request
        event_data:
          action_type: "{{action_type}}"
          target: "{{target}}"
          clip: "{{clip}}"

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
    name: email_clear_count
    description: >-
      Reset the priority email counter to zero. Call this when the user
      says "I've read my emails", "clear my emails", "emails done", or
      any variation indicating they've caught up on email.
      Confirm briefly (e.g. "emails cleared"). Never name this function.
    parameters:
      type: object
      properties: {}
  function:
    type: script
    sequence:
      - service: pyscript.email_clear_count
        response_variable: _function_result

- spec:
    name: focus_guard_mark_meal
    description: >-
      Record that the user just ate a meal. Resets the meal reminder
      timer so focus guard stops nagging about eating. Call when the
      user says "I just ate", "had lunch", "finished dinner", "grabbed
      a snack", or any variation of having eaten.
      Confirm briefly (e.g. "noted"). Never name this function.
    parameters:
      type: object
      properties:
        meal_time:
          type: string
          description: >-
            Optional meal time in HH:MM format. If omitted, uses current
            time. Only provide if the user mentions a specific past time
            (e.g., "I ate at 2pm").
  function:
    type: script
    sequence:
      - service: pyscript.focus_guard_mark_meal
        data:
          meal_time: "{{meal_time|default('')}}"
        response_variable: _function_result

- spec:
    name: focus_guard_snooze
    description: >-
      Snooze all non-critical focus guard nudges for a specified duration.
      Call when the user says "stop nagging", "remind me later", "snooze
      reminders", "give me 30 minutes", or any variation of wanting
      nudges to pause temporarily. Critical calendar reminders still
      come through.
      Confirm briefly (e.g. "snoozed for 30 minutes"). Never name this function.
    parameters:
      type: object
      properties:
        minutes:
          type: integer
          description: >-
            Minutes to snooze (5-120, default 30). Match what the user
            asks for — "an hour" = 60, "half hour" = 30.
  function:
    type: script
    sequence:
      - service: pyscript.focus_guard_snooze
        data:
          minutes: "{{minutes|default(30)}}"
        response_variable: _function_result

- spec:
    name: schedule_optimal_timing
    description: >-
      Calculate when to start preparing for an upcoming event, factoring
      in prep time and travel. Call when the user asks "when should I
      leave?", "when do I need to start getting ready?", "what time
      should I wake up for my appointment?", or similar planning questions.
    parameters:
      type: object
      properties:
        event_description:
          type: string
          description: "What the event is (e.g., dentist appointment, flight)"
        event_time:
          type: string
          description: "Event start time in HH:MM format (24h)"
        prep_minutes:
          type: integer
          description: "Minutes needed to prepare (default 30)"
        travel_minutes:
          type: integer
          description: "Travel time in minutes (default 0, use 0 for home events)"
      required:
        - event_time
  function:
    type: script
    sequence:
      - service: pyscript.schedule_optimal_timing
        data:
          event_description: "{{event_description|default('')}}"
          event_time: "{{event_time}}"
          prep_minutes: "{{prep_minutes|default(30)}}"
          travel_minutes: "{{travel_minutes|default(0)}}"
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
    name: memory_link
    description: >-
      Create a bidirectional link between two existing memories in the
      knowledge graph. Call when you notice two memories are related
      and should be connected, or when the user says "these are related",
      "connect X and Y", "link my dentist to my calendar".
    parameters:
      type: object
      properties:
        from_key:
          type: string
          description: "First memory key"
        to_key:
          type: string
          description: "Second memory key"
        rel_type:
          type: string
          enum: [manual, tag_overlap, content_match]
          description: "Relationship type (default: manual)"
      required:
        - from_key
        - to_key
  function:
    type: script
    sequence:
      - service: pyscript.memory_link
        data:
          from_key: "{{from_key}}"
          to_key: "{{to_key}}"
          rel_type: "{{rel_type|default('manual')}}"
        response_variable: _function_result

- spec:
    name: memory_archive_search
    description: >-
      Search archived (expired) memories. Use when the regular memory
      search doesn't find something the user is sure they stored, or
      when they ask "do you remember something from a while ago about...",
      "check old memories for...", "search the archive".
    parameters:
      type: object
      properties:
        query:
          type: string
          description: "Search term to match against key, value, or tags"
        limit:
          type: integer
          description: "Max results (1-50, default 20)"
        scope:
          type: string
          enum: [user, household, session, all]
          description: "Scope filter (default: all)"
      required:
        - query
  function:
    type: script
    sequence:
      - service: pyscript.memory_archive_search
        data:
          query: "{{query}}"
          limit: "{{limit|default(20)}}"
          scope: "{{scope|default('all')}}"
        response_variable: _function_result
