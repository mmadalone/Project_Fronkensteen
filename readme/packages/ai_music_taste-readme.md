# AI Music Taste — Listening Profile Extraction

Kill switch package for the music taste logging and profile aggregation system (I-34). The taste profile itself lives on `sensor.ai_music_taste_status` (created by pyscript), which tracks listening patterns and genre preferences.

## What's Inside

- **Input helpers:** 2 (moved to consolidated helper files) -- 1 boolean, 1 button

## Entity Reference

| Entity ID | Type | Purpose |
|---|---|---|
| `input_boolean.ai_music_taste_enabled` | input_boolean | Kill switch for music taste logging |
| `input_button.ai_music_taste_rebuild` | input_button | Manual trigger for taste profile rebuild |
| `sensor.ai_music_taste_status` | sensor (pyscript) | Taste profile with `genre_summary`, `top_artists`, `top_tracks`, `total_plays`, `has_spotify`, `last_updated` attributes (created by pyscript) |

## Dependencies

- **Pyscript:** `pyscript/music_taste.py` (listening event capture, genre aggregation, profile generation)
- **Media players:** Music Assistant and Sonos players (listening source)

## Cross-References

- **Package:** `ai_context_hot.yaml` -- music taste summary injected into the Media component (`genre_summary` attribute with `summary` fallback)

## Notes

- This is one of the thinnest packages in the system -- just a single kill switch boolean. All logic lives in the pyscript module.
- The hot context reads `genre_summary` first, falling back to `summary` if the genre breakdown is not available.
- Deployed as part of I-34.
