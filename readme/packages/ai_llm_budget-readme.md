# AI LLM Budget — Cost Control & API Monitoring

Comprehensive budget tracking and cost control for all AI services: LLM calls/tokens, TTS characters, STT calls, ElevenLabs credits, OpenRouter spend, and Serper web search credits. Includes multi-metric budget gating (calls, tokens, cost), per-agent breakdown tracking, daily usage logging, and automatic fallback to degraded mode on exhaustion (I-46).

## What's Inside

- **REST sensors:** 4 (ElevenLabs subscription, USD/EUR exchange rate, OpenRouter credits, Serper account)
- **Template sensors:** 12 (`ai_llm_budget_remaining`, `ai_tts_budget_remaining`, `ai_total_daily_cost`, `elevenlabs_credits_remaining`, `elevenlabs_daily_usage`, `serper_daily_usage`, `ai_cost_per_serper_credit`, `ai_tts_cost_per_1k_chars_derived`, `openrouter_daily_usage`, `ai_budget_daily_average`, `ai_budget_monthly_projection`, `ai_budget_fallback_status`)
- **Scripts:** 3 (`ai_llm_budget_check`, `ai_llm_budget_increment`, `ai_budget_reset`)
- **Automations:** 4 (`ai_budget_reset_trigger`, `ai_llm_call_counter`, `ai_budget_fallback_manager`, `ai_rest_sensor_recovery`)
- **Input helpers:** Many (moved to consolidated helper files) -- numbers, booleans, texts, selects, buttons

## Entity Reference

| Entity ID | Type | Purpose |
|---|---|---|
| `sensor.elevenlabs_subscription` | REST sensor | ElevenLabs API: remaining chars, tier, reset date (hourly poll) |
| `sensor.usd_eur_exchange_rate` | REST sensor | Frankfurter API: USD to EUR rate (daily poll) |
| `sensor.openrouter_credits` | REST sensor | OpenRouter API: total usage/credits in EUR (30-min poll) |
| `sensor.serper_account` | REST sensor | Serper API: remaining search credits (hourly poll) |
| `sensor.ai_llm_budget_remaining` | template sensor | Multi-metric budget % remaining (min of calls, tokens, cost) |
| `sensor.ai_tts_budget_remaining` | template sensor | TTS budget % remaining |
| `sensor.ai_total_daily_cost` | template sensor | Aggregated daily cost from all services (EUR) |
| `sensor.elevenlabs_credits_remaining` | template sensor | ElevenLabs chars remaining (API or manual cap) |
| `sensor.elevenlabs_daily_usage` | template sensor | ElevenLabs chars used today (delta from midnight) |
| `sensor.serper_daily_usage` | template sensor | Serper credits used today (delta from midnight) |
| `sensor.ai_cost_per_serper_credit` | template sensor | Serper cost per credit in EUR |
| `sensor.openrouter_daily_usage` | template sensor | OpenRouter daily spend in EUR (delta from midnight) |
| `sensor.ai_tts_cost_per_1k_chars_derived` | template sensor | Derived TTS cost per 1K chars from ElevenLabs plan (C5) |
| `sensor.ai_budget_daily_average` | template sensor | 7-day rolling daily average cost in EUR (C5) |
| `sensor.ai_budget_monthly_projection` | template sensor | Monthly cost projection from daily average (C5) |
| `sensor.ai_budget_fallback_status` | template sensor | Fallback mode status (normal/fallback_active) |
| `script.ai_llm_budget_check` | script | Budget gate: returns `{allowed, budget_remaining, ...}` for priority tier |
| `script.ai_llm_budget_increment` | script | Increments daily call counter (optional `cost` param for multi-call patterns) |
| `script.ai_budget_reset` | script | Full reset: L2 log, zero counters, snapshot APIs, clear breakdown, deactivate fallback |
| `automation.ai_budget_reset_trigger` | automation | Midnight + manual button + startup catch-up trigger for reset script |
| `automation.ai_llm_call_counter` | automation | Counts LLM + STT calls from pipeline runs and conversation state changes |
| `automation.ai_budget_fallback_manager` | automation | Activates/deactivates fallback mode on exhaustion/recovery (I-46) |
| `automation.ai_rest_sensor_recovery` | automation | Retries REST sensors after 5 min when they go unavailable |

## Dependencies

- **Pyscript:** `pyscript/memory.py` (`memory_set` for daily usage logging to L2, `budget_history_record` for daily usage history)
- **Pyscript:** `pyscript/common_utilities.py` (`budget_track_call` for per-agent breakdown)
- **Pyscript:** `pyscript/tts_queue.py` (TTS char counting, ElevenLabs credit gating)
- **APIs:** ElevenLabs (API key in `secrets.yaml`), OpenRouter (API key in `secrets.yaml`), Frankfurter (free, no key), Serper (API key in `secrets.yaml`)
- **Voice agents:** All conversation agents tracked by the call counter automation

## Cross-References

- **Package:** `ai_context_hot.yaml` -- budget data could be injected into agent context
- **Package:** `ai_focus_guard.yaml` -- uses budget gate for agent-personality nudges
- **Blueprint:** `budget_fallback.yaml` -- per-satellite pipeline switching on fallback activation
- **Pyscript:** `pyscript/agent_dispatcher.py` -- early return when fallback flag is ON
- **Pyscript:** `pyscript/tts_queue.py` -- swaps to HA Cloud TTS when fallback active or ElevenLabs credits below floor

## Notes

- Budget gate thresholds: Essential (wake-up, direct voice, bedtime) = always allowed; Standard (proactive, notifications) = allowed if budget > 30%; Luxury (banter, deliberation) = allowed if budget > 60%.
- The budget remaining sensor uses a min-of-three-metrics approach: whichever metric (calls, tokens, cost) is most constrained determines the overall budget percentage.
- Currency is EUR. The `input_select.ai_budget_currency` is a display label only (no conversion logic).
- REST sensor recovery automation retries unavailable sensors after 5 minutes to prevent stale data for the full scan interval.
- I-46 fallback mode: on exhaustion, dispatcher returns homeassistant agent, TTS swaps to HA Cloud, persistent notification created, auto-restores at midnight. Setting `ai_elevenlabs_credit_floor` to a negative value disables the ElevenLabs credit gate (allows overage usage).
- Deployed: 2026-03-01. Major updates: I-33 (TTS/STT/cost tracking), I-32 (OpenRouter/exchange rate), I-46 (fallback mode).
