# Universal Proactive Briefing Assembly and Delivery

Aggregates content from all architecture layers -- weather, calendar, email, schedule, household state, memory highlights, and projects -- into a personalized briefing. Supports full mode (LLM reformulation + ElevenLabs TTS) and stripped mode (raw text + fallback TTS) based on remaining budget. Driven by the unified `proactive_briefing.yaml` blueprint. Part of Task 19 of the Voice Context Architecture.

## Services

| Service | Parameters | Returns | Description |
|---------|-----------|---------|-------------|
| `pyscript.proactive_build_briefing` | `sections_override` (str, default ""), `download_window` (str, default "since_midnight") | `{status, op, assembled, sections, section_count, enabled_sections, test_mode, elapsed_ms}` | Assemble briefing content from all layers. Each section fails independently. No TTS, no LLM. For inspection/testing. |
| `pyscript.proactive_briefing_now` | `briefing_label` (str, default "briefing"), `sections_override` (str), `household_entities_override` (str), `output_speaker_override` (str), `use_dispatcher` (bool, default true), `pipeline_name` (str), `pipeline_id` (str), `tts_volume` (float, default 0.0), `briefing_prompt` (str), `extra_context` (str), `download_window` (str, default "since_midnight") | `{status, delivered, persona, stripped_mode, section_count, total_elapsed_ms, ...}` | Full delivery pipeline: build -> agent dispatch -> LLM reformulation -> TTS playback -> dedup register -> whisper context. |

Both services use `supports_response="only"`.

## Triggers

| Trigger | Function | Condition |
|---------|----------|-----------|
| `@time_trigger("startup")` | `_startup` | Initialize briefing status sensor |

Note: No cron triggers in the pyscript module. All scheduling (morning, afternoon, evening triggers) is handled by the `proactive_briefing.yaml` blueprint which calls `proactive_briefing_now`.

## Key Functions

### Section Assemblers (each independently failable)
- `_section_greeting(hour)` -- Time-aware greeting (pure Python, no external calls)
- `_section_weather()` -- Weather from `weather.forecast_home` entity
- `_section_calendar(hour)` -- Calendar from `input_text.ai_calendar_today_summary` (L1 helper populated by calendar_promote)
- `_section_email(hour)` -- From `input_number.ai_email_priority_count`
- `_section_schedule()` -- Next upcoming event advisory with prep timing
- `_section_household(entities_override)` -- Monitored entity states
- `_section_memory()` -- Memory highlights from L2 search
- `_section_projects()` -- Active project summaries from L2
- `_section_media(upcoming_days, download_window)` -- Radarr/Sonarr from `media_promote_now` or `sensor.ai_media_upcoming` attrs fallback

### Core Pipeline
- `_assemble_briefing(sections_override, download_window)` -- Orchestrate all section assemblers, collect results
- `_deliver_briefing(test_mode, ...)` -- Full delivery: assemble -> dispatcher -> LLM -> TTS -> dedup -> whisper
- `_briefing_framing_for_hour(hour)` -- Time-appropriate framing context
- `_briefing_prompt_for_hour(hour)` -- Time-appropriate LLM prompt
- `_extract_speech_from_response(resp)` -- Extract speech text from conversation.process response
- `_get_budget_stripped_threshold()` -- Budget threshold for stripped (no-LLM) mode

## State Dependencies

- `input_boolean.ai_proactive_briefing_enabled` -- Kill switch
- `input_boolean.ai_test_mode` -- Test mode
- `input_text.ai_last_briefing_summary` -- Output: last briefing summary text
- `weather.forecast_home` -- Weather data
- `input_number.ai_email_priority_count` -- Email count
- `sensor.ai_predictive_schedule_status` attr `bedtime_recommendation` -- Bedtime advisory
- `input_datetime.ai_predicted_wake_time` -- Wake time
- `input_boolean.ai_context_work_day_tomorrow` -- Work day status
- `sensor.ai_llm_budget_remaining` -- Budget remaining percentage for stripped mode check
- `input_number.ai_budget_personality_threshold` -- Budget threshold
- Various household monitoring entities (configurable per instance)

## Package Pairing

Pairs with `packages/ai_proactive_briefing.yaml` (kill switch, last briefing summary, per-instance delivered flags for morning/afternoon/evening). Status sensor: `sensor.ai_proactive_briefing_status`.

## Called By

- **Blueprints**: `proactive_briefing.yaml` (unified blueprint with per-instance scheduling, presence gating, content config) calls `proactive_briefing_now`
- **LLM agents**: "Give me my briefing" voice command triggers via automation
- **Depends on**: `pyscript/memory.py` (L2), `pyscript/tts_queue.py` (TTS), `pyscript/notification_dedup.py` (dedup), `pyscript/agent_dispatcher.py` (persona selection), `pyscript/common_utilities.py` (budget tracking)

## Notes

- **Section independence**: Each section assembler is wrapped in try/except. A failed section produces an empty string but does not block other sections. Partial briefings are normal.
- **Stripped mode**: When daily budget exceeds the threshold, briefing skips LLM reformulation and uses raw assembled text with fallback TTS voice (`tts.home_assistant_cloud`).
- **Media sections**: Supports `media_today`, `media_tomorrow`, `media_weekly` as separate section names (or `media` for today-only). Uses Radarr/Sonarr sensors.
- **Custom prompts**: `briefing_prompt` supports `{content}` (assembled sections), `{framing}` (time-appropriate tone hint), and `{context}` (evaluated Jinja2 context template) placeholders. Default prompt instructs the agent to deliver conversationally and mention every item without skipping.
- **Dispatcher mode**: When `use_dispatcher=True`, the dispatcher picks the agent based on the time-of-day era setting — topic affinity is intentionally skipped for system-initiated briefings.
- **Media format**: Episode labels use TTS-friendly format ("season 3, episode 7") instead of coded format ("S03E07"). Scene release metadata (resolution, codec, release group) is stripped from download titles.
- **Dedup integration**: After delivery, registers the briefing topic with the dedup system to prevent repeat announcements from other delivery channels.
- **TTS calls**: `tts_queue.py` uses `service.call('tts', 'speak')` for TTS delivery. The `duck` parameter controls whether volume ducking is applied during playback.
- **Time-of-day blocks**: Four tone blocks (late night, morning, afternoon, evening) controlled by per-instance `time` selector inputs or global `input_number` helpers as fallback. Late night = midnight to morning start; boundaries in minutes-since-midnight internally.
