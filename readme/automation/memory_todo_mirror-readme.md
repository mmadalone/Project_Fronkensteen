# AI Memory -- Todo List Mirror (I-6)

Bidirectional sync between L2 memory and a native HA todo list. L2 entries matching configured filters are mirrored to the todo list so users can browse memories in the sidebar, companion app, and Assist. New items added directly to the todo list (without an L2 marker) are automatically created as L2 memory entries on the next sync cycle. Checking off a synced item deletes the L2 entry and removes the todo item.

## How It Works

```
┌──────────────────────────┐
│  Time pattern trigger    │
│  (default every 30 min)  │
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│  Kill switch check       │
│  Privacy gate check      │
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│  pyscript.memory_todo_   │
│  sync                    │
│  ├─ L2 → todo (mirror)  │
│  ├─ todo → L2 (create)  │
│  └─ completed → delete   │
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│  Log sync stats          │
│  (+added, -removed,      │
│   +L2, -L2)              │
└──────────────────────────┘
```

## Features

- Bidirectional sync: L2 to todo and todo to L2
- Completion-based deletion: checking off a synced item removes the L2 entry
- Configurable sync interval (5/10/15/30/60 minutes)
- Scope filtering (all, user, miquel, jessica, household)
- Tag filtering (comma-separated, entry must match at least one)
- Full-text search query filter
- Max age and max items limits
- Always-include option for entries tagged "remember" or "important"
- Configurable default scope for user-created todo items
- Kill switch support
- Privacy gate integration with per-person tier suppression

## Prerequisites

- Pyscript integration with `memory_todo_sync` service deployed
- Local To-do integration added via UI (Settings -> Integrations)
- A todo list entity created (e.g. "AI Memory" -> `todo.ai_memory`)

## Installation

1. Add the Local To-do integration and create an "AI Memory" list
2. Copy `memory_todo_mirror.yaml` to `config/blueprints/automation/madalone/`
3. Create automation: **Settings -> Automations -> Create -> Use Blueprint**
4. Configure the todo entity and sync filters

## Configuration

<details>
<summary><strong>① Core</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| `todo_entity` | *(required)* | The todo entity to mirror memories to |
| `sync_interval` | `/30` | Sync interval: /5, /10, /15, /30, /60 minutes |

</details>

<details>
<summary><strong>② Filters</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| `scope_filter` | `all` | Only sync entries with this scope |
| `tag_filter` | *(empty)* | Comma-separated tags (entry must have at least one) |
| `query_filter` | *(empty)* | FTS search query |
| `max_age_days` | `0` | Only sync entries within this many days (0 = no limit) |
| `max_items` | `50` | Maximum items synced to the todo list (10-200) |
| `include_important` | `true` | Always include entries tagged "remember" or "important" |

</details>

<details>
<summary><strong>③ Bidirectional sync</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| `default_scope` | `user` | Scope assigned when a user-created todo item syncs to L2 |

</details>

<details>
<summary><strong>④ Safety</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| `kill_switch` | *(empty)* | input_boolean entity -- when ON, sync is disabled |

</details>

<details>
<summary><strong>Privacy</strong></summary>

| Input | Default | Description |
|-------|---------|-------------|
| `privacy_gate_enabled` | `input_boolean.ai_privacy_gate_enabled` | Boolean that enables the privacy gate system |
| `privacy_gate_mode` | `input_select.ai_privacy_gate_mode` | Privacy gate behavior (auto/force_suppress/force_allow) |
| `privacy_gate_person` | `miquel` | Person name for tier suppression lookups |

</details>

## Technical Notes

- **Mode:** `single` / `max_exceeded: silent`
- Sync call and log step both use `continue_on_error: true`
- Kill switch supports empty/none value (disabled state)
- Privacy gate evaluates per-automation override via `input_select.ai_privacy_gate_memory_todo_mirror`

## Changelog

- **v1.0:** Initial release (I-6) -- bidirectional sync with filters, privacy gate, and kill switch

## Author

**Madalone + Assistant**

## License

See repository for license details.
