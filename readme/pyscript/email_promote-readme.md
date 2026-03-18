# Email Priority Filter — IMAP Email to L2 Promotion

Task 18b of the Voice Context Architecture. Filters incoming IMAP emails and promotes only priority messages to L2 memory. Matches sender against known contacts and subject against priority keywords. Urgent matches also trigger TTS announcements via `dedup_announce` with persona LLM reformulation. Three filter modes: whitelist, blacklist, and hybrid.

## Services

| Service | Parameters | Returns | Description |
|---------|-----------|---------|-------------|
| `pyscript.email_promote_process` | `sender`, `subject`, `suppress_tts` | `{status, op, promoted, filter_result, reason, sender, subject, l2_key, count, tts_announced, llm_used, elapsed_ms, test_mode}` | Process an incoming email through the priority filter. Checks sender against known contacts, subject against keywords. Priority emails are written to L2. Urgent emails also get TTS via `dedup_announce`. `supports_response="only"` |
| `pyscript.email_clear_count` | _(none)_ | `{status, op, count, elapsed_ms}` | Reset priority email counter to zero. Also clears the rolling count in L2 memory. `supports_response="only"` |

## Triggers

| Trigger | Function | Condition |
|---------|----------|-----------|
| `@time_trigger("startup")` | `email_promote_startup` | Initializes status sensor, runs IMAP health check after 30s delay |
| `@time_trigger("cron(2 0 * * *)")` | `email_promote_midnight` | Midnight reset: clears email count, runs IMAP health check |

## Key Functions

- `_extract_sender_parts()` — Parses email sender field into (name, email) tuple. Handles "Name <email>", "<email>", and bare email formats.
- `_check_contacts()` — Matches sender email/domain against known contacts CSV. Supports exact email, domain match, and domain suffix match.
- `_check_keywords()` — Checks subject against built-in + custom priority keywords
- `_check_urgent()` — Checks subject against urgent keyword subset (triggers TTS)
- `_check_blocked_keywords()` — Checks subject against blocked keywords (blacklist/hybrid modes)
- `_process_email()` — Core processing: identity gate, filter mode routing, L2 write, counter increment, TTS announcement
- `_check_imap_health()` — Verifies IMAP sensor availability, creates persistent notification on failure

## State Dependencies

- `input_boolean.ai_email_promotion_enabled` — Kill switch
- `input_select.ai_email_filter_mode` — Filter mode: `whitelist`, `blacklist`, or `hybrid`
- `input_text.ai_email_known_contacts` — CSV of known contact emails/domains
- `input_text.ai_email_priority_keywords` — CSV of custom priority keywords
- `input_text.ai_email_blocked_senders` — CSV of blocked sender emails/domains (blacklist/hybrid)
- `input_text.ai_email_blocked_keywords` — CSV of blocked subject keywords (blacklist/hybrid)
- `input_number.ai_email_priority_count` — Rolling priority email counter
- `input_text.ai_email_last_priority` — Last priority email subject
- `sensor.identity_confidence_miquel` — Identity confidence gate (suppressed below 70%)
- `sensor.ai_llm_budget_remaining` — Budget gate for LLM reformulation
- `sensor.gmail_messages` — IMAP sensor (health check target)

## Package Pairing

Pairs with `packages/ai_email_promotion.yaml` which defines all email filter helpers, the counter, the blocked lists, and the IMAP trigger automation. Also depends on `packages/ai_identity.yaml` for identity confidence and `packages/ai_llm_budget.yaml` for budget gating.

## Called By

- **email_priority_filter.yaml (automation)** — calls `email_promote_process` on `imap_content` event
- **email_follow_me.yaml (blueprint)** — may call with `suppress_tts="true"` when handling its own announcements
- **Morning briefing** — reads the priority count from the helper or calls `email_clear_count` after reading

## Notes

- Privacy by design: only sender name and subject are stored in L2 -- email body is NEVER persisted.
- Identity gate: emails are suppressed entirely when identity confidence is below 70%, preventing email leaks when the wrong person is home.
- Three filter modes: `whitelist` (only known contacts + keywords), `blacklist` (everything except blocked), `hybrid` (blocked filtered first, then whitelist pass for the rest).
- Urgent TTS pipeline: dispatches to get the active agent's voice, runs the announcement text through `conversation.process` for persona reformulation (budget-gated at 20%), then sends via `dedup_announce` for deduplication.
- Built-in priority keywords include: shipping, delivery, appointment, urgent, invoice, confirmation, password reset, security alert, payment, receipt.
- Urgent keywords (TTS triggers): urgent, security alert, password reset, immediate.
- The `suppress_tts` parameter allows callers (like `email_follow_me`) to promote to L2 without triggering TTS when they handle announcements themselves.
