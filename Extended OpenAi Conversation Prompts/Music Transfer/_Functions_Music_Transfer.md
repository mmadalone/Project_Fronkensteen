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