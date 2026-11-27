# Calendar and Reminders Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Destiny sets, lists and cancels one-time reminders by voice and pushes them to the phone on time. She reads the family calendar and adds events to it through Home Assistant.

**Architecture:**
- Reminders live in the brain's SQLite store, and a daemon scheduler thread sends due ones through `HAClient.notify`.
- Five client tools (in a new `household.py`) are offered on both tiers.
- The engine gains a bounded tool loop (blocking and streaming) that runs those tools locally and appends `tool_result` turns to history.
- Calendar access goes through HA's calendar REST API and `calendar.create_event` service.

**Tech Stack:** Python 3.12, FastAPI, sqlite3, httpx, the Anthropic SDK (beta messages), pytest. Everything runs in Docker.

**Spec:** `docs/superpowers/specs/2026-11-26-calendar-reminders-design.md`

## Global Constraints

- **Tests:** run tests only in Docker, from `C:\dev\Destiny`. Run `docker compose build brain`, then `docker compose run --rm --no-deps brain pytest -q`. The image bakes in the code, so rebuild before every test run.
- **Secrets:** never read, print or edit `.env`. New settings must have defaults so no `.env` change is needed.
- **Git:**
  - Stage files by explicit path. Never `git add -A`, never stage `.claude/`.
  - Commit trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
  - No pushing.
- **No subagents:** implementers never dispatch subagents.
- **Time zone:** family local time is `Settings.tz` (America/Los_Angeles in production). Times without an offset are read in that zone. Store UTC ISO strings in SQLite, following `store._iso`.
- **Limits:**
  - Reminder `message` is 1–200 characters after strip.
  - `in_minutes` is 1–525600.
  - `at` must be no more than 60 s in the past (past within 60 s is clamped to now) and at most 365 days ahead.
  - At most 50 pending reminders.
  - `days` is 1–14.
- **Tool rounds:** at most 3 per answer (`MAX_TOOL_ROUNDS = 3`).
- **Scheduler timing:**
  - Tick every 15 s.
  - More than 5 minutes late: prefix the message with `"(Late) "`.
  - More than 24 h late: mark `expired`, don't send.
  - Notify failure: retry, then mark `failed` after 20 attempts.
  - Notify title is exactly `"Destiny reminder"`.
- **Notify service:** `DESTINY_REMINDER_NOTIFY` if set, else `DESTINY_NOTIFY_SERVICE`.
- **Calendar entity:** `DESTINY_CALENDAR_ENTITY` if set, else the first `calendar.*` entity id (sorted) from HA `/api/states`, cached 5 minutes. When there is none, the calendar tools return exactly `"The family calendar isn't connected yet."`.
- **History:** stays append-only. Never slice or rewrite earlier messages, because thinking replay requires byte-identical prefixes.

## Review Focus

1. **"Remind me tomorrow at 9" said at 11:58 PM.** The model passes `at` as a local time. The tool must interpret it in `Settings.tz`, not UTC, and confirm the local day and time it actually stored. *(Test in Task 2: `test_set_reminder_at_is_local_time`.)*
2. **Haiku calls `set_reminder` and `needs_deeper_answer` in the same turn.** Escalation wins and no reminder is stored, so nothing happens twice when Sonnet retries. *(Test in Task 3: `test_escalation_wins_over_household_tools`.)*
3. **The model keeps calling tools.** After 3 rounds the engine stops. It speaks the text it has, or `ERROR_LINE`, and never loops forever. *(Test in Task 3: `test_tool_rounds_capped`.)*
4. **The brain restarts with a reminder due during the downtime.** It is sent once with "(Late) " if under 24 h late, and never sent twice even if two ticks overlap. *(Tests in Task 4: `test_late_reminder_prefixed`, `test_tick_serialized_no_double_send`.)*
5. **HA is down when a reminder fires.** The reminder stays pending and goes out on a later tick. *(Test in Task 4: `test_notify_failure_retries_then_fails`.)*

---

### Task 1: Reminder store, settings, and HA calendar client

**Files:**
- Modify: `brain/destiny_brain/store.py`, `brain/destiny_brain/config.py`, `brain/destiny_brain/ha.py`
- Modify: `brain/tests/fakes.py` (FakeHA gains calendar methods)
- Test: `brain/tests/test_store.py`, `brain/tests/test_config.py` (or wherever config is tested), `brain/tests/test_ha.py` (existing HA tests file; create if absent)

**Interfaces (produces):**
- `@dataclass Reminder(id: int, message: str, due_utc: datetime, status: str, attempts: int, created_utc: datetime, sent_utc: datetime | None)`. Status is one of `"pending" | "sent" | "cancelled" | "expired" | "failed"`.
- `Store` methods:
  - `add_reminder(message: str, due_utc: datetime, now_utc: datetime) -> int`
  - `pending_reminders(limit: int = 10) -> list[Reminder]`, ordered by due ascending
  - `pending_count() -> int`
  - `due_reminders(now_utc: datetime) -> list[Reminder]`, pending with `due_utc <= now`
  - `cancel_reminder(rid: int) -> bool`, true only if it was pending
  - `mark_reminder(rid: int, status: str, now_utc: datetime) -> None`, sets `sent_utc` when the status is `"sent"`
  - `bump_reminder_attempts(rid: int) -> int`, returns the new count
  - The `reminders` table is created in `init()` with `CREATE TABLE IF NOT EXISTS`.
- `Settings` fields:
  - `reminder_notify_service: str = ""`, loaded from `DESTINY_REMINDER_NOTIFY`, falling back to `DESTINY_NOTIFY_SERVICE`.
  - `calendar_entity: str = ""`, loaded from `DESTINY_CALENDAR_ENTITY`.
- `HAClient` methods:
  - `find_calendar(preferred: str = "") -> str | None`. Returns `preferred` if non-empty. Otherwise it uses `GET /api/states` and returns the sorted-first entity id starting with `calendar.`, cached 5 min. It returns `None` on error or when there is none.
  - `calendar_events(entity_id: str, start: datetime, end: datetime) -> list[dict] | None`. Sends `GET /api/calendars/{entity_id}` with params `start` and `end` as ISO 8601 strings, and returns the JSON list. It returns `None` on error.
  - `create_calendar_event(entity_id: str, summary: str, *, start: datetime | None = None, end: datetime | None = None, start_date: date | None = None, end_date: date | None = None, location: str | None = None) -> bool`. Sends `POST /api/services/calendar/create_event` with JSON `{"entity_id", "summary", "start_date_time", "end_date_time"}` (ISO strings) or `{"start_date", "end_date"}` (ISO dates), plus `"location"` when given.
- `FakeHA` additions:
  - `calendar = "calendar.family"`, `events = []`, `created = []`, `notify_ok = True`
  - `find_calendar(preferred="")`
  - `calendar_events(...)`, which returns `events`
  - `create_calendar_event(...)`, which records its kwargs and returns True
  - `notify` returns `notify_ok`

- [ ] **Step 1: Write the failing tests.**
  - Store round trip: add, pending order, due, cancel (true once, false after), mark sent sets `sent_utc`, attempts increment.
  - Settings fallback: only `DESTINY_NOTIFY_SERVICE=mobile_app_iphone` gives `reminder_notify_service == "mobile_app_iphone"`.
  - HA (httpx `MockTransport`): exact URL, params and JSON for both calendar calls, `find_calendar` selection and cache, and `None` on a 500.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the full suite. All tests pass.**
- [ ] **Step 5: Commit** with `feat(brain): reminder store and HA calendar client`.

### Task 2: Household tools

**Files:**
- Create: `brain/destiny_brain/household.py`
- Test: `brain/tests/test_household.py`

**Interfaces:**
- Consumes: the Task 1 Store, HAClient and Settings methods.
- Produces:
  - `HOUSEHOLD_TOOLS: list[ToolSpec]`, in this order: `set_reminder`, `list_reminders`, `cancel_reminder`, `get_calendar_events`, `add_calendar_event`. Schemas follow the spec's §4.1 table, with `"additionalProperties": False`.
  - `HOUSEHOLD_NAMES: frozenset[str]`.
  - `class Household(settings, store, ha, clock)` with `run(name: str, args: dict) -> tuple[str, bool]`, which returns `(result_text, is_error)` and never raises. Unknown names and exceptions become `(sentence, True)`.
- **Result text:**
  - Short, plain sentences the model can speak from.
  - Local times are formatted like `Friday, November 27 at 5:00 PM`.
  - `list_reminders` includes `id N` for each item.
  - Calendar events are given as lines like `Friday, November 27: 3:00 PM Dentist (at Main St)`, with all-day events written as `all day`.
  - No events: `No events on the calendar for that time.`

- [ ] **Step 1: Write the failing tests.**
  - `test_set_reminder_in_minutes`: clock at 2026-11-26 16:00 local, `in_minutes=20` stores due 16:20 local (as UTC), and the text contains `4:20 PM`.
  - `test_set_reminder_at_is_local_time`: clock at 2026-11-26 23:58 local, `at="2026-11-27T09:00"` stores due 2026-11-27 17:00 UTC, and the text contains `Friday, November 27 at 9:00 AM`.
  - Errors, each with `is_error` set and nothing stored:
    - both or neither of `at`/`in_minutes`;
    - a bad format;
    - `at` more than 60 s in the past;
    - more than 365 days ahead;
    - an empty message, or one over 200 characters;
    - a 51st pending reminder.
  - `at` 30 s in the past is clamped to now.
  - List and cancel: cancelling an unknown or already-sent id gives an error.
  - Calendar with `FakeHA.calendar=None` gives exactly `The family calendar isn't connected yet.`, not as an error.
  - Calendar read formatting covers a timed event and an all-day event (`{"start": {"date": ...}}`).
  - Calendar add:
    - default end is +1 h;
    - `date` makes an all-day event with `end_date` the next day;
    - an HA failure gives an error.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the full suite. All tests pass.**
- [ ] **Step 5: Commit** with `feat(brain): household reminder and calendar tools`.

### Task 3: Engine tool loop, router, and prompt

**Files:**
- Modify: `brain/destiny_brain/engine.py`, `brain/destiny_brain/router.py`, `brain/destiny_brain/prompts.py`, `brain/destiny_brain/deps.py`
- Modify (optional): `brain/tests/fakes.py`, e.g. unique tool_use ids in `make_result`
- Test: `brain/tests/test_engine.py`, `brain/tests/test_router.py`, `brain/tests/test_prompts.py`

**Interfaces:**
- Consumes: `HOUSEHOLD_TOOLS`, `HOUSEHOLD_NAMES` and `Household.run` from Task 2.
- **Engine constructor:** `Engine(settings, store, provider, ha, clock=..., fillers=None, household=None)`. When `household` is `None`, it builds `Household(settings, store, ha, clock)`. `deps.build_deps` lets this default happen.
- **Tools on each tier:**
  - Tier 1 calls pass `tools=[ESCALATE_TOOL, *HOUSEHOLD_TOOLS]`.
  - Tier 2 calls, blocking and streaming, pass `tools=list(HOUSEHOLD_TOOLS)` plus the existing `server_tools`.
- **Tool loop:** when a result has `stop_reason == "tool_use"` and every tool_use block is a household tool:
  - Run each tool, matching ids to the `tool_use` blocks in `result.content`.
  - Next messages are the previous messages, then `{"role":"assistant","content": result.content}`, then `{"role":"user","content":[{"type":"tool_result","tool_use_id": id, "content": text, "is_error": err}, ...]}`.
  - Call again on the same tier, up to `MAX_TOOL_ROUNDS = 3` rounds.
  - On Tier 1, any `needs_deeper_answer` call escalates first, without running household tools.
  - On Tier 2 the single `pause_turn` continuation still works. Tool rounds and pause share one loop, at most 3 tool rounds plus 1 pause.
  - Text from all calls joins with the existing seam rule (`_merge`).
  - On success, history becomes all of those messages plus the final assistant content.
  - If the rounds run out while still on `tool_use`, speak the joined text if any, else `ERROR_LINE`, and store nothing.
- **Streaming:** text deltas from every call stream as they come. Tool execution happens between calls. Yield one `HEARTBEAT` before each continuation call.
- **Router:** add `HOUSEHOLD_RE = r"\b(?:remind|reminders?|calendar|appointments?)\b|\b(?:my|our) schedule\b"`. In `route`, after sticky and before live: if it matches and no team name matches (with chicken nuggets stripped), return `RouteDecision(1, "household")`.
- **Prompt:** append to `DESTINY_BASE`:

  > Use your tools for reminders and the family calendar. Never say a reminder or event is set unless the tool confirmed it, and confirm briefly with the day and time. You can only set one-time reminders for now. When reading calendar events, say them naturally in a sentence or two.

- [ ] **Step 1: Write the failing tests.** Use FakeProvider and a fake or real `Household` with `FakeHA` and the real store.
  - `test_tier1_runs_household_tool_then_answers`:
    - The first result is `tool_use` `set_reminder`; the second is the text "Okay, reminder set for 5 PM."
    - Two provider calls, the second containing a `tool_result` with the matching id.
    - The spoken text is the second text.
    - The stored history has the full chain.
  - `test_escalation_wins_over_household_tools`: one result with both tool calls escalates to Tier 2, and the store has no reminder.
  - `test_tool_rounds_capped`: 4 `tool_use` results in a row give exactly 4 provider calls (3 rounds) and `ERROR_LINE`.
  - `test_tier2_stream_tool_round`:
    - The first stream ends with `stop_reason="tool_use"`; the second streams text.
    - The NDJSON has a ping between them, the filler is spoken once, and the final text is spoken.
  - Tier 2 tools include `HOUSEHOLD_TOOLS`, and `server_tools` still has web search.
  - Router: "remind me tomorrow to call grandma" gives `(1, "household")`; "what's on our calendar today" gives household; "when is the next Nuggets game, remind me" gives live; sticky still wins.
  - The prompt contains the new sentence.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the full suite. All tests pass**, including every existing test.
- [ ] **Step 5: Commit** with `feat(brain): tool loop for household tools`.

### Task 4: Reminder scheduler

**Files:**
- Create: `brain/destiny_brain/scheduler.py`
- Modify: `brain/destiny_brain/app.py` (start and stop with the app lifespan), `brain/destiny_brain/deps.py` (Deps gains `scheduler`)
- Test: `brain/tests/test_scheduler.py`

**Interfaces:**
- Consumes: the Task 1 store methods and `HAClient.notify`.
- `class ReminderScheduler(settings, store, ha, clock, interval: float = 15.0)` with:
  - `tick() -> int`, which returns the number sent and is serialized by a lock;
  - `start()`, which starts a daemon thread looping `tick()` every interval and catching all exceptions;
  - `stop()`.
- **No service configured:** `tick()` sends nothing and logs a warning once.
- **Lifecycle:** the app starts the scheduler on startup only when deps provide one. Tests that build the app with fake deps must not start threads.

- [ ] **Step 1: Write the failing tests.**
  - On-time send: `(service, "Destiny reminder", message)` is sent and the row is marked sent.
  - `test_late_reminder_prefixed`: 6 min late gives `"(Late) "` plus the message.
  - More than 24 h late is expired and not sent.
  - `test_notify_failure_retries_then_fails`: `notify_ok=False` keeps it pending with attempts bumped; on the 20th failure it becomes `failed`.
  - `test_tick_serialized_no_double_send`: two threads call `tick()` at once and exactly one notification goes out.
  - Future reminders are not sent.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the full suite. All tests pass.**
- [ ] **Step 5: Commit** with `feat(brain): reminder scheduler`.

### Task 5: Docs

**Files:**
- Create: `docs/google-calendar-setup.md`
- Modify: `docs/troubleshooting.md`, `docs/project-log.md`, `README.md` (spec link)

- [ ] **Step 1: Write `docs/google-calendar-setup.md`.**
  - Step-by-step: create a Google Cloud project, enable the Google Calendar API, set up the OAuth consent screen (External, add yourself as a test user), and create an OAuth client of type "Web application". Wait: HA's Google Calendar uses Application Credentials with "TVs and Limited Input devices" or "Web application" per the current HA docs. Check https://www.home-assistant.io/integrations/google/ and follow it exactly.
  - In HA: Settings → Devices & Services → Add Integration → Google Calendar → enter the client ID and secret → sign in.
  - Then say "What's on our calendar today?" to verify.
  - Optional: `DESTINY_CALENDAR_ENTITY` if several calendars exist.
- [ ] **Step 2: Add a "Reminders and calendar" troubleshooting section.**
  - A reminder didn't arrive: check the Companion app notifications, `DESTINY_NOTIFY_SERVICE`, and brain logs for "notify failed".
  - She says the calendar isn't connected.
- [ ] **Step 3: Add a project-log entry and the README spec link.**
- [ ] **Step 4: Commit** with `docs: calendar and reminders setup`.
