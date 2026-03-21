- spec:
    name: execute_service
    description: >-
      Use this function to execute service of devices in Home Assistant.
      NEVER use this for notification services — phone notifications cannot
      be cleared, dismissed, or marked as read from HA. No such services
      exist. Just summarize notifications and move on.
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
    name: execute_service

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
      X-API-KEY: "5f19c27b1a07e6fe814a7db514d6521b4a195322"
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
    name: voice_set_bedtime_countdown
    description: >-
      Sets the bedtime countdown timer. The lights will turn off
      automatically when the countdown expires. Minimum 1 minute,
      maximum 15 minutes.
    parameters:
      type: object
      properties:
        minutes:
          type: integer
          description: >-
            Number of minutes until lights out. Must be between 1 and 15.
      required:
        - minutes
  function:
    type: script
    sequence:
      - service: script.voice_set_bedtime_countdown
        data:
          minutes: "{{minutes}}"
        response_variable: _function_result

- spec:
    name: voice_play_bedtime_audiobook
    description: >-
      Starts audiobook playback on the bedroom speaker. Pass the
      exact title of the audiobook to play.
    parameters:
      type: object
      properties:
        title:
          type: string
          description: >-
            The title of the audiobook to play on the bedroom speaker.
      required:
        - title
  function:
    type: script
    sequence:
      - service: script.voice_play_bedtime_audiobook
        data:
          title: "{{title}}"
        response_variable: _function_result

- spec:
    name: voice_skip_audiobook
    description: >-
      Signals that no audiobook is wanted for tonight. Call this when
      the user declines a bedtime story.
    parameters:
      type: object
      properties: {}
  function:
    type: script
    sequence:
      - service: script.voice_skip_audiobook
        data: {}
        response_variable: _function_result

- spec:
    name: end_conversation
    description: >-
      End the continuous conversation session. Call when the user says goodbye,
      goodnight, stop, that's enough, we're done, or any clear farewell.
      Do NOT call for topic changes or handoff requests.
    parameters:
      type: object
      properties: {}
  function:
    type: script
    sequence:
      - action: input_boolean.turn_off
        target:
          entity_id: input_boolean.ai_continuous_conversation_active