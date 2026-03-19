# LLM Script for Music Assistant voice requests (modified)

![Image](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/llm_voice_script-header.jpeg)

![Image](https://github.com/music-assistant/voice-support/blob/main/assets/music-assistant.png?raw=true)

Modified version of the [official Music Assistant LLM Voice Script](https://github.com/music-assistant/voice-support/blob/main/llm-script-blueprint/llm_voice_script.yaml) by TheFes. This script is exposed to Assist as a tool function, allowing voice assistants to play music via Music Assistant based on natural language requests. The LLM parses the voice command into structured fields (media_type, artist, album, media_id, area, shuffle) and the script handles target resolution, radio mode, and playback. Local modifications include alias coverage, error handling, section naming, min_version correction, and header image.

## How It Works

```
START (called by LLM with media_type, artist, album, media_id, area, etc.)
  |
  v
[Initialize: resolve default_player, shuffle, player_data]
  |
  v
[Resolve target_data: area_id + entity_id from LLM input]
  |
  v
<Valid target found?>
  |         |
 YES        NO
  |         |
  |         v
  |    [STOP: "No valid target"]
  |
  v
[Build action_data: media_id, media_type, artist, album, radio_mode]
  |
  v
[music_assistant.play_media with resolved target + action data]
  |
  v
[media_player.shuffle_set on target]
  |
  v
[Run user-defined additional actions]
  |
  v
END
```

## Features

- Natural language music playback via LLM tool function
- Supports track, album, artist, playlist, and radio media types
- Smart target resolution: area, media player entity, or default player
- Media player name-to-entity resolution (handles friendly names from LLM)
- Radio mode control: Use player settings / Always / Never
- Shuffle support based on voice request analysis
- Multi-value media_id support (semicolon-separated track lists)
- Customizable LLM prompts for all parameters
- Additional post-playback actions hook
- Parallel mode for concurrent requests

## Prerequisites

- Home Assistant **2024.8.0** or newer
- Music Assistant integration
- A conversation agent / LLM that supports tool functions
- Script must be **exposed to Assist** after creation
- Script must have a **clear description** (see blueprint for example)

## Installation

1. Copy `llm_voice_script.yaml` to `config/blueprints/script/madalone/`
2. Create script: **Settings > Automations & Scenes > Scripts > Add > Use Blueprint**
3. **Expose the script to Assist** (Settings > Voice Assistants > Expose entities)
4. **Add a clear description** to the script so the LLM knows when to use it

## Configuration

<details>
<summary><strong>Section 1 -- Settings for Music Assistant playback</strong></summary>

| Input | Default | Description |
|---|---|---|
| `default_player` | _(empty)_ | Default MA player when area/player not specified in request |
| `play_continuously` | `Use player settings` | Radio mode: Use player settings / Always / Never |

</details>

<details>
<summary><strong>Section 2 -- Prompt settings for the LLM</strong></summary>

| Input | Default | Description |
|---|---|---|
| `media_type_prompt` | _(detailed prompt)_ | LLM prompt for media_type (track/album/artist/playlist/radio) |
| `artist_prompt` | _(detailed prompt)_ | LLM prompt for artist extraction |
| `album_prompt` | _(detailed prompt)_ | LLM prompt for album extraction |
| `media_id_prompt` | _(detailed prompt)_ | LLM prompt for media_id extraction |
| `media_description_prompt` | _(detailed prompt)_ | LLM prompt for media description |
| `area_prompt` | _(detailed prompt)_ | LLM prompt for area resolution |
| `media_player_prompt` | _(detailed prompt)_ | LLM prompt for media player resolution |
| `shuffle_prompt` | _(detailed prompt)_ | LLM prompt for shuffle detection |

</details>

<details>
<summary><strong>Section 3 -- Additional actions</strong></summary>

| Input | Default | Description |
|---|---|---|
| `actions` | `[]` | Additional actions to run after Music Assistant play_media |

</details>

### Script Fields (populated by LLM)

| Field | Required | Description |
|---|---|---|
| `media_type` | Yes | track / album / artist / playlist / radio |
| `artist` | Yes | Artist name (empty string if unknown) |
| `album` | Yes | Album name (empty string if unknown) |
| `media_id` | Yes | Track/album/artist/playlist/radio name; semicolon-separated for multiple |
| `media_description` | Yes | Human-readable description of the media request |
| `area` | No | Area(s) for playback |
| `media_player` | No | Specific MA media player entity_id(s) |
| `shuffle` | Yes | Whether to enable shuffle (true/false) |

### Available Variables for Additional Actions

| Variable | Description |
|---|---|
| `media_id` | General media description (semicolon-separated if multiple) |
| `media_type` | track / album / artist / playlist / radio |
| `artist` | Requested artist |
| `album` | Requested album |
| `media_description` | Description from voice request |
| `area` | Area(s) for playback (may be undefined) |
| `media_player` | MA media player(s) (may be undefined) |
| `default_player` | Default player from setup or `none` |
| `target_data` | Dict with `area_id` and `entity_id` keys |
| `shuffle` | true / false |

## Technical Notes

- **Mode:** `parallel` / `max_exceeded: silent`
- **Error handling:** `continue_on_error: true` on shuffle_set action
- **Target resolution priority:** area > media_player entity > default_player
- **Player name resolution:** If LLM provides friendly names instead of entity_ids, the script resolves them via `integration_entities('music_assistant')` lookup
- **NA filtering:** Uses `rejectattr('1', 'eq', 'NA')` to strip unused fields from action and target data
- **Upstream:** Check the [original repository](https://github.com/music-assistant/voice-support) for upstream updates

## Changelog

- **Current:** Modified version with alias coverage, error handling, section naming, min_version correction, header image
- **Upstream:** See [TheFes/music-assistant voice-support](https://github.com/music-assistant/voice-support) for original changelog

## Author

**TheFes** (original) / **madalone** (modifications)

## License

See repository for license details.
