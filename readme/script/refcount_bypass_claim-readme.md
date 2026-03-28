![Refcount Bypass -- Claim](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/refcount_bypass_claim-header.jpeg)

# Refcount Bypass -- Claim

Generic refcount bypass for any shared boolean toggle. Registers an owner in a JSON owner list stored in an `input_text` helper. The first claim (0 to 1 transition) turns OFF the protected toggle. Subsequent claims from different owners are stacked. Duplicate claims from the same owner are silently ignored, making it safe for `mode: restart` automations.

Part of the I-45b refcount bypass system. Pair with **Refcount Bypass -- Release**.

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
| Owner already claimed?     |
+----------------------------+
  | no                  | yes
  v                     v
+------------------+   Done (no-op)
| Append owner +   |
| timestamp to list|
+------------------+
  |
  v
+----------------------------+
| Write updated list back    |
| to input_text helper       |
+----------------------------+
  |
  v
+----------------------------+
| Was list empty before?     |
+----------------------------+
  | yes (0->1)          | no
  v                     v
+------------------+   Done
| Turn OFF the     |
| protected toggle |
+------------------+
  |
  v
Done
```

## Features

- JSON owner list with timestamps for audit trail (`{"o": "entity_id", "t": unix_timestamp}`)
- First-claim (0 to 1) transition turns OFF the protected toggle
- Idempotent -- duplicate claims from the same owner are ignored
- Generic -- works with any `input_boolean` / `input_text` pair
- Default configuration targets `notification_follow_me` but easily overridden for other toggles (e.g. ducking)
- `mode: queued` with `max: 10` prevents race conditions from concurrent callers

## Prerequisites

- Home Assistant
- `input_text.notification_follow_me_bypass_owners` (or custom JSON owner list helper)
- `input_boolean.notification_follow_me` (or custom toggle to protect)

## Installation

1. Copy `refcount_bypass_claim.yaml` to `config/blueprints/script/madalone/`
2. Create script: **Settings -> Automations & Scenes -> Scripts -> Add -> Use Blueprint**

## Configuration

| Input | Default | Description |
|-------|---------|-------------|
| `owners_helper` | `input_text.notification_follow_me_bypass_owners` | input_text that holds the JSON owner list |
| `toggle` | `input_boolean.notification_follow_me` | input_boolean turned OFF on first claim |

### Script Fields (passed at call time)

| Field | Required | Description |
|-------|----------|-------------|
| `owner` | Yes | Entity ID of the claiming automation (use `{{ this.entity_id }}`) |

## Technical Notes

- **Mode:** `queued` / `max: 10`
- Call from automation blueprints: `action: script.refcount_bypass_claim` with `data: { owner: "{{ this.entity_id }}" }`
- Deploy a **Refcount Watchdog** automation to catch crashed automations that never release their claims (TTL-based eviction)
- The owner list is stored as a JSON array string in an `input_text` helper (max 255 characters)

## Changelog

- **v1.0.0** -- Initial release, extracted from scripts.yaml to shareable blueprint

## Author

**madalone**

## License

See repository for license details.
