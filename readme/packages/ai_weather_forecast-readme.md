# AI Weather Forecast

Provides helper entities for tomorrow's weather forecast summary, populated by the weather forecast promotion blueprint. This is a minimal package — the forecast logic lives entirely in the blueprint.

## What's Inside

| Type | Count |
|------|-------|
| Input helpers (external) | 2 |

## Entity Reference

| Entity ID | Type | Purpose |
|-----------|------|---------|
| `input_text.ai_weather_tomorrow_summary` | Input Text | Tomorrow's weather summary text (max 255 chars) |
| `input_button.ai_weather_forecast_rebuild` | Input Button | Manual trigger to rebuild weather forecast |

## Dependencies

- **Blueprint:** `weather_forecast_promote.yaml` — populates the summary helper on schedule
- **Integration:** Weather integration (provides forecast data)
- **Helper files:** `helpers_input_text.yaml`, `helpers_input_button.yaml`

## Cross-References

- **ai_context_hot.yaml** — weather summary is likely injected into hot context for voice agents
- **pyscript/proactive_briefing.py** — briefing content may include tomorrow's weather forecast
- **pyscript/calendar_promote.py** — calendar promotion may coordinate with weather data for schedule recommendations

## Notes

- This is one of the smallest packages in the collection — two helpers with a comment header. All logic is in the `weather_forecast_promote.yaml` blueprint.
- The I-47 prefix in the file header indicates this is part of the contact/forecast promotion integration milestone.
