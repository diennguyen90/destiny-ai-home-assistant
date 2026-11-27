# Destiny — Calendar and Reminders (Design)

Date: 2026-11-26
Status: Approved 2026-11-26 (the user confirmed the direction and asked to proceed while away; the calls marked *builder's call* were made by the architect)
Builds on: [Internet answers](2026-11-26-web-search-design.md)

## 1. Intent

This is project 2 of 3. The goal is household management by voice:
- "Remind me at 5 to take out the trash."
- "Remind me in 20 minutes to check the oven."
- "What's on our calendar tomorrow?"
- "Add the dentist on Friday at 3."

Reminders arrive as a push notification on the family phone (the HA Companion app, `notify.mobile_app_iphone`). The family Google Calendar is connected in Home Assistant with the family's Google account.

## 2. Goals, non-goals, anti-goals

- **Goals:**
  - One-time reminders by voice, delivered on time to the phone, surviving brain restarts.
  - List and cancel reminders by voice.
  - Read calendar events for a day or a range.
  - Add calendar events by voice.
- **Non-goals (v1):**
  - Repeating reminders. She says she can only do one-time reminders for now.
  - Per-person routing. Every reminder goes to the one phone until profiles exist (milestone 2).
  - Spoken announcements on the Voice PE.
  - Editing or deleting calendar events.
  - A parent-page reminder list.
- **Anti-goals:**
  - Reminders cluttering the Google Calendar. The user chose separate, Destiny-only pings.
  - A reminder silently lost.
  - A reminder firing at the wrong time because of time-zone confusion.
  - She claims she set something when she didn't.

## 3. Approaches

- **A. Reminders as Google Calendar events.** Google's own app would alert. Rejected by the user: it clutters the calendar.
- **B. Brain-owned reminders plus HA calendar entities. Chosen.**
  - The brain stores reminders in its SQLite database and a background scheduler pushes each one through HA `notify` when due.
  - Calendar reads and writes go through Home Assistant's calendar API, so any HA calendar works, Google included.
- **C. HA automations or timers created per reminder.** Fragile: it writes HA config at runtime and is hard to list or cancel. Rejected.

## 4. Design

### 4.1 Tools (client tools, offered on both tiers)

| Tool | Input | Effect |
|---|---|---|
| `set_reminder` | `message` (short reminder text) and exactly one of `at` (`YYYY-MM-DDTHH:MM`, family local time) or `in_minutes` (1–525600) | Stores a pending reminder and returns a confirmation with its local time. |
| `list_reminders` | none | Returns up to 10 upcoming pending reminders, each with an id and local time. |
| `cancel_reminder` | `id` | Cancels a pending reminder. |
| `get_calendar_events` | `start_date` (`YYYY-MM-DD`) and `days` (1–14, default 1) | Returns events as spoken-friendly lines. |
| `add_calendar_event` | `title`; `start` (`YYYY-MM-DDTHH:MM`) or `date` (`YYYY-MM-DD`, all day); optional `end`; optional `location` | Creates an event on the family calendar. |

- **Fixed tool set (*builder's call*).** All five tools are always offered, which keeps the tool list fixed so caching and thinking replay stay stable. If no calendar is connected, the calendar tools return "The family calendar isn't connected yet."
- **Validation:**
  - `message` is 1–200 characters.
  - `at` must be in the future (up to 60 s in the past is treated as now) and at most 365 days ahead.
  - At most 50 pending reminders.
  - Times without an offset are read in the brain's `TZ` (America/Los_Angeles).
- **Errors** come back as a `tool_result` with `is_error: true` and a plain sentence, so the model can say what went wrong instead of claiming success.

### 4.2 Engine tool loop

- **The loop:** when a call stops with `stop_reason == "tool_use"` for household tools, the engine runs each tool locally. It appends the assistant content and a user message of `tool_result` blocks, then calls again.
  - At most 3 tool rounds per answer.
  - It stays within the existing deadline rules.
  - History stays append-only and the full chain is stored.
- **Tier 1 (Haiku):** gets `[ESCALATE_TOOL] + household tools`. If any call is `needs_deeper_answer`, escalation wins, as today.
- **Tier 2 (Sonnet):** gets the household tools plus web search, streaming. Tool rounds and the single `pause_turn` continuation share one continuation loop.
- **Tool use ids** are read from the `tool_use` blocks in `ProviderResult.content`.

### 4.3 Router

- **New rule:** reminder and calendar words route to Tier 1 with reason `"household"`.
  - Words: remind, reminder(s), calendar, appointment(s), and "my/our schedule".
  - Position: after sticky, before live.
- **Exception:** team names still win, so "Nuggets schedule" stays live.

### 4.4 Prompt

Add to `DESTINY_BASE`:
- Use the tools for reminders and the calendar. Never say a reminder or event is set unless the tool confirmed it.
- Confirm briefly with the day and time.
- Only one-time reminders are possible.
- Read calendar events naturally, with no lists.

### 4.5 Scheduler

- **Loop:** a daemon thread started with the app ticks every 15 s and sends due reminders via `HAClient.notify(service, "Destiny reminder", message)`.
- **Service:** `DESTINY_REMINDER_NOTIFY`, falling back to `DESTINY_NOTIFY_SERVICE` (today `mobile_app_iphone`).
- **Late reminders:**
  - More than 5 minutes late (for example, the brain was down): the message is prefixed "(Late) ".
  - More than 24 h late: marked `expired` and not sent.
- **Notify failure:** stays pending and is retried next tick. It keeps retrying every tick until it is more than 24 h late, then it is marked `expired`. A WARNING is logged on the 1st failure and every 20th after.
- **Locking:** a row is marked sent only after notify succeeds, and ticks are serialized.

### 4.6 Calendar via Home Assistant

- **Entity:** `DESTINY_CALENDAR_ENTITY` if set. Otherwise the first `calendar.*` entity in HA states (*builder's call*: zero configuration after Google is linked), cached for 5 minutes.
- **Read:** `GET /api/calendars/<entity>?start=…&end=…`.
- **Write:** `POST /api/services/calendar/create_event` with `start_date_time`/`end_date_time` (default end +1 h) or `start_date`/`end_date` (all day, end = next day).
- **Google setup:** the user links Google Calendar in HA (a Google Cloud OAuth client plus sign-in). Covered by `docs/google-calendar-setup.md`. The brain needs no change once it's linked.

## 5. Testing

- **Unit tests:**
  - Store CRUD and status transitions.
  - Tool validation (past, too far, bad format, both or neither time fields, the 50 cap).
  - Calendar unconnected message.
  - HA calendar requests (exact URLs and payloads).
  - Tool loop on Tier 1 and Tier 2 (blocking and streaming), including max rounds, escalation precedence and history chain.
  - Router household rule and team-name exception.
  - Scheduler due, late, expired and retry behaviour.
- **Live:**
  - "Remind me in 1 minute to test Destiny" arrives on the phone.
  - "What reminders do I have?" and cancel work.
  - Calendar reads after Google is linked.
  - The smoke test still passes 7/7.

## 6. Left to the builder

- The exact tool descriptions and result wording.
- Module layout.
- The scheduler's start and stop wiring.
