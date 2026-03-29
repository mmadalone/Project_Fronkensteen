![Refcount Bypass -- Release](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/refcount_bypass_release-header.jpeg)

# Refcount Bypass -- Release

Generic refcount bypass for any shared boolean toggle. Decrements an HA `counter` helper. The last release (1 to 0 transition) turns ON the protected toggle. Safe to call even if counter is already at 0 (counter `minimum: 0` prevents negative values).

Part of the I-45b refcount bypass system. Pair with **Refcount Bypass -- Claim**.

## How It Works

```
Start (owner = caller entity_id)
  |
  v
+----------------------------+
| Read current counter value |
+----------------------------+
  |
  v
+----------------------------+
| Counter > 0?               |
+----------------------------+
  | yes                 | no
  v                     v
+------------------+   |
| Decrement counter|   |
+------------------+   |
  |                    |
  v                    |
+----------------------------+
| Counter now 0?             |
+----------------------------+
  | yes (1->0)          | no
  v                     |
+------------------+    |
| Turn ON the      |    |
| protected toggle |    |
+------------------+    |
  |                     |
  +--------+------------+
           |
           v
+----------------------------+
| Remove owner from debug log|
+----------------------------+
  |
  v
Done
```

## Features

- Atomic counter decrement via HA `counter` helper (zero JSON parsing)
- Last-release (1 to 0) transition turns ON the protected toggle
- Safe to call when counter is already at 0 (no-op)
- Generic -- works with any `input_boolean` / `counter` pair
- Default configuration targets `notification_follow_me` but easily overridden for other toggles
- Optional debug log helper for owner visibility
- `mode: queued` with `max: 10` prevents race conditions from concurrent callers

## Prerequisites

- Home Assistant **2024.10.0** or newer
- `counter.ai_notification_follow_me_bypass_refcount` (or custom counter helper)
- `input_boolean.ai_notification_follow_me` (or custom toggle to protect)

## Installation

1. Copy `refcount_bypass_release.yaml` to `config/blueprints/script/madalone/`
2. Create script: **Settings -> Automations & Scenes -> Scripts -> Add -> Use Blueprint**

## Configuration

| Input | Default | Description |
|-------|---------|-------------|
| `refcount_entity` | `counter.ai_notification_follow_me_bypass_refcount` | Counter entity that tracks active bypass claims |
| `toggle` | `input_boolean.ai_notification_follow_me` | input_boolean turned ON on last release |
| `debug_log_entity` | `input_text.ai_notification_follow_me_bypass_log` | Optional input_text for owner visibility debugging |

### Script Fields (passed at call time)

| Field | Required | Description |
|-------|----------|-------------|
| `owner` | Yes | Entity ID of the releasing automation (use `{{ this.entity_id }}`) |

## Technical Notes

- **Mode:** `queued` / `max: 10`
- Call from automation blueprints: `action: script.refcount_bypass_release` with `data: { owner: "{{ this.entity_id }}" }`
- Deploy a **Refcount Watchdog** automation to catch crashed automations that never release their claims (TTL-based eviction)

## Changelog

- **v2.0.0** -- Replaced JSON owner list (`input_text`) with HA `counter` helper. Atomic increment/decrement, zero Jinja2 JSON parsing. Added optional debug log helper.
- **v1.0.0** -- Initial release, extracted from scripts.yaml to shareable blueprint

## Author

**madalone**

## License

See repository for license details.
