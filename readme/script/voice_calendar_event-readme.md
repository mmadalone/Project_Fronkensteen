![Voice Calendar Event](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/voice_calendar_event-header.jpeg)

# Voice — Calendar Event (unified)

Full CRUD for Google Calendar events via voice. Create, find, delete, and edit events through the agent tool system.

## How It Works

```
┌──────────────────────────────────────────┐
│  Agent tool: calendar_event              │
│  LLM picks operation + parses fields     │
└──────────────┬───────────────────────────┘
               │
┌──────────────▼───────────────────────────┐
│  Blueprint: voice_calendar_event.yaml    │
│  Dispatches by operation (choose block)  │
└──────────────┬───────────────────────────┘
               │
  ┌────────────┼────────────┬──────────────┐
  ▼            ▼            ▼              ▼
CREATE       FIND        DELETE          EDIT
pyscript.    pyscript.   pyscript.      pyscript.
calendar_    calendar_   calendar_      calendar_
create_      find_       delete_        edit_
event        events      event          event
  │            │            │              │
  │            │       calendar_utils  delete+recreate
  │         calendar_  delete_event_   via calendar_
  │         utils.     by_uid          utils + calendar.
  │         get_events                 create_event
  └────────────┼────────────┴──────────────┘
               │
┌──────────────▼───────────────────────────┐
│  Common: Memory + Whisper + TTS confirm  │
│  (per-operation prompts, skip for find)  │
└──────────────────────────────────────────┘
```

## Operations

| Operation | User says | What happens |
|-----------|-----------|-------------|
| **create** | "Add dentist tomorrow at 2pm" | Validates, creates event, refreshes L2/L1 |
| **find** | "What's on my calendar Friday?" | Returns matching events with UIDs |
| **delete** | "Delete my dentist appointment" | Finds by summary, deletes by UID |
| **edit** | "Move my meeting to 3pm" | Finds, deletes, recreates with new fields |

## Recurring Event Support

| Scope | Effect | Example |
|-------|--------|---------|
| `this_instance` (default) | Delete/edit only this occurrence | "Delete my dentist tomorrow" |
| `this_and_future` | Delete this + all future | "Cancel all future yoga classes" |
| `entire_series` | Delete the entire recurring series | "Delete all my work events" |

## Limitations

- **Edit propagation**: Only single-instance edit supported. Series/future editing not available (Google Calendar lacks UPDATE_EVENT)
- **Recurring creation**: Cannot create recurring events via voice (no `rrule` in `calendar.create_event`)
- **Edit = delete + recreate**: Event UID changes after edit (transparent to user)

## Dependencies

| Component | Purpose |
|-----------|---------|
| HACS `calendar_utils` | UID retrieval (`get_events`) + delete (`delete_event_by_uid`) |
| `calendar.create_event` | HA Core — create + recreate-after-edit |
| `pyscript/calendar_promote.py` | All 4 pyscript services + L2/L1 refresh |

## Blueprint Inputs

| Section | Input | Default |
|---------|-------|---------|
| **Defaults** | `default_calendar` | *(required)* |
| | `default_duration_minutes` | 60 |
| **TTS** | `enable_confirmation_tts` | true |
| | `confirmation_prompt_create` | *(brief confirm)* |
| | `confirmation_prompt_delete` | *(brief confirm)* |
| | `confirmation_prompt_edit` | *(brief confirm)* |
| | `conversation_agent` | "" |
| | `use_dispatcher` | true |
| | `tts_speaker` | "" |
| **Memory** | `enable_memory` | true |
| | `enable_whisper` | true |
| **Infra** | `post_tts_delay` | 3 |

## Agent Tool Availability

| Variant | Available |
|---------|-----------|
| Standard | Yes (all 5 personas) |
| Bedtime | Yes (all 5 personas) |
