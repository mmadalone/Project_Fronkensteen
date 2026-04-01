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
    name: play_media
    description: >-
      Search for and play media via Music Assistant. Use when the user
      asks to play a song, album, artist, playlist, podcast, audiobook,
      or radio station. Do NOT use execute_service for media playback —
      always use this function. For stopping or pausing, use stop_radio,
      shut_up, or pause_media instead. IMPORTANT: pass the user's
      spoken title verbatim — never strip, rewrite, or substitute
      words even if the title resembles a previous request.
    parameters:
      type: object
      properties:
        title:
          type: string
          description: >-
            The title, name, or search query for the media to play.
            Pass the user's spoken title exactly as heard — do not
            interpret, correct, or substitute titles from prior context.
        media_type:
          type: string
          enum:
            - track
            - album
            - artist
            - playlist
            - audiobook
            - podcast
            - radio
          description: >-
            The type of media to search for. Use "track" for songs,
            "album" for full albums, "artist" to play an artist's catalog,
            "playlist" for playlists, "audiobook" for audiobooks,
            "podcast" for podcasts, "radio" for radio stations.
        player:
          type: string
          description: >-
            Media player entity to play on (e.g. media_player.workshop_sonos).
            If omitted, plays on the default speaker.
      required:
        - title
        - media_type
  function:
    type: script
    sequence:
      - service: script.voice_play_media
        data:
          title: "{{title}}"
          media_type: "{{media_type}}"
          player: "{{player|default('')}}"
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
      X-API-KEY: "YOUR_API_KEY"
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
        owner:
          type: string
          description: >-
            Optional. The username this memory belongs to (e.g., miquel,
            jessica). Only set this if the user explicitly identifies
            themselves or if you received an identity_uncertain response
            and the user confirmed. Leave empty to auto-detect.
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
          owner: "{{owner|default('')}}"
        response_variable: _function_result

- spec:
    name: calendar_event
    description: >-
      Manage calendar events. Supports four operations:
      "create" — add new event. Provide summary + start_date_time (or start_date
      for all-day). Omit end times — system adds default duration.
      "find" — search for events by title/date. Returns matching events with IDs.
      "delete" — remove an event. Provide summary + approximate date to find it,
      or uid if known from a previous find. For recurring events, set scope:
      "this_instance" (default), "this_and_future", or "entire_series".
      "edit" — modify an event. Provide summary + date to find it, then new_*
      fields for changes (new_summary, new_start_date_time, new_location, etc.).
      Only supports editing single instances — series editing not available via voice.
      Format dates as YYYY-MM-DD HH:MM (24h local time). For all-day events use
      start_date (YYYY-MM-DD) instead of start_date_time — do NOT provide both.
      After success, confirm naturally what happened. Do NOT use execute_service
      for calendar operations. Never name this function.
    parameters:
      type: object
      properties:
        operation:
          type: string
          enum: [create, find, delete, edit]
          description: "What to do: create, find, delete, or edit"
        summary:
          type: string
          description: "Event title (create) or search term (find/delete/edit)"
        start_date_time:
          type: string
          description: "Timed event start: YYYY-MM-DD HH:MM (create, or approximate date for find/delete/edit)"
        end_date_time:
          type: string
          description: "Timed event end: YYYY-MM-DD HH:MM (create only, optional)"
        start_date:
          type: string
          description: "All-day event or date filter: YYYY-MM-DD"
        description:
          type: string
          description: "Event description (create/edit, optional)"
        location:
          type: string
          description: "Event location (create/edit, optional)"
        uid:
          type: string
          description: "Event UID from a previous find result (delete/edit — omit to auto-find by summary)"
        recurrence_id:
          type: string
          description: "Recurring event instance ID from find result (delete/edit recurring)"
        scope:
          type: string
          enum: [this_instance, this_and_future, entire_series]
          description: "Delete scope for recurring events (default: this_instance)"
        new_summary:
          type: string
          description: "Updated title (edit only)"
        new_start_date_time:
          type: string
          description: "Updated start time: YYYY-MM-DD HH:MM (edit only)"
        new_end_date_time:
          type: string
          description: "Updated end time: YYYY-MM-DD HH:MM (edit only)"
        new_start_date:
          type: string
          description: "Updated all-day date: YYYY-MM-DD (edit only)"
        new_description:
          type: string
          description: "Updated description (edit only)"
        new_location:
          type: string
          description: "Updated location (edit only)"
      required:
        - operation
        - summary
  function:
    type: script
    sequence:
      - service: script.voice_calendar_event
        data:
          operation: "{{operation}}"
          summary: "{{summary}}"
          start_date_time: "{{start_date_time|default('')}}"
          end_date_time: "{{end_date_time|default('')}}"
          start_date: "{{start_date|default('')}}"
          description: "{{description|default('')}}"
          location: "{{location|default('')}}"
          uid: "{{uid|default('')}}"
          recurrence_id: "{{recurrence_id|default('')}}"
          scope: "{{scope|default('this_instance')}}"
          new_summary: "{{new_summary|default('')}}"
          new_start_date_time: "{{new_start_date_time|default('')}}"
          new_end_date_time: "{{new_end_date_time|default('')}}"
          new_start_date: "{{new_start_date|default('')}}"
          new_description: "{{new_description|default('')}}"
          new_location: "{{new_location|default('')}}"
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
      Play an audiobook on the bedroom speaker at bedtime volume.
      Use this when the user asks to play an audiobook, a bedtime
      story, or any spoken-word book content. Always prefer this
      over play_media for audiobook requests — it handles volume,
      restart, and ducking automatically. IMPORTANT: pass the
      user's spoken title verbatim as the title parameter — never
      strip, rewrite, or substitute words even if the title
      resembles a previous request. "More Bedtime Stories" and
      "Bedtime Stories" are different audiobooks.
    parameters:
      type: object
      properties:
        title:
          type: string
          description: >-
            The title of the audiobook to play. Pass the user's
            spoken title exactly as heard — do not interpret,
            correct, or substitute titles from prior context.
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
      - action: pyscript.set_sensor_value
        data:
          entity_id: sensor.ai_continuous_conversation_active
          value: "off"