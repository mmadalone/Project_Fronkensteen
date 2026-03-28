![Refcount Bypass -- Release](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/refcount_bypass_release-header.jpeg)

# Refcount Bypass -- Release

Generic refcount bypass for any shared boolean toggle. Removes an owner from a JSON owner list stored in an `input_text` helper. The last release (1 to 0 transition) turns ON the protected toggle. Safe to call even if the owner was never claimed (no-op).

Part of the I-45b refcount bypass system. Pair with **Refcount Bypass -- Claim**.

## How It Works

```
Start (owner = caller entity_id)
  |
  v
+----------------------------+
| Read JSON owner list from  |
| input_text helper          |
+----------------------------+
  |
  v
+----------------------------+
| Remove owner from list     |
+----------------------------+
  |
  v
+----------------------------+
| Write updated list back    |
| to input_text helper       |
+----------------------------+
  |
  v
+----------------------------+
| List now empty AND         |
| list was non-empty before? |
+----------------------------+
  | yes (1->0)          | no
  v                     v
+------------------+   Done
| Turn ON the      |
| protected toggle |
+------------------+
  |
  v
Done
```

## Features

- Removes the caller's entry from the JSON owner list
- Last-release (1 to 0) transition turns ON the protected toggle
- Safe to call when owner was never claimed -- silently writes back the unchanged list
- Generic -- works with any `input_boolean` / `input_text` pair
- Default configuration targets `notification_follow_me` but easily overridden for other toggles
- `mode: queued` with `max: 10` prevents race conditions from concurrent callers

## Prerequisites

- Home Assistant
- `input_text.notification_follow_me_bypass_owners` (or custom JSON owner list helper)
- `input_boolean.notification_follow_me` (or custom toggle to protect)

## Installation

1. Copy `refcount_bypass_release.yaml` to `config/blueprints/script/madalone/`
2. Create script: **Settings -> Automations & Scenes -> Scripts -> Add -> Use Blueprint**

## Configuration

| Input | Default | Description |
|-------|---------|-------------|
| `owners_helper` | `input_text.notification_follow_me_bypass_owners` | input_text that holds the JSON owner list |
| `toggle` | `input_boolean.notification_follow_me` | input_boolean turned ON on last release |

### Script Fields (passed at call time)

| Field | Required | Description |
|-------|----------|-------------|
| `owner` | Yes | Entity ID of the releasing automation (use `{{ this.entity_id }}`) |

## Technical Notes

- **Mode:** `queued` / `max: 10`
- Call from automation blueprints: `action: script.refcount_bypass_release` with `data: { owner: "{{ this.entity_id }}" }`
- Deploy a **Refcount Watchdog** automation to catch crashed automations that never release their claims (TTL-based eviction)
- The owner list is stored as a JSON array string in an `input_text` helper (max 255 characters)

## Changelog

- **v1.0.0** -- Initial release, extracted from scripts.yaml to shareable blueprint

## Author

**madalone**

## License

See repository for license details.
