from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta, timezone
from typing import Callable
from zoneinfo import ZoneInfo

from .providers.base import ToolSpec

log = logging.getLogger(__name__)

_NO_CALENDAR = "The family calendar isn't connected yet."
_MAX_PENDING = 50
_TIME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2})(?::\d{2}(?:\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?$")

HOUSEHOLD_TOOLS: list[ToolSpec] = [
    ToolSpec(
        name="set_reminder",
        description=(
            "Set a reminder that will be announced to the family at the right time. "
            "Give `message` as the short thing to remind about (e.g. \"Take out the trash\"), "
            "and exactly one of `at` (family local time, YYYY-MM-DDTHH:MM) or `in_minutes`."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Short thing to remind about, max 200 characters."},
                "at": {"type": "string", "description": "Family local time, YYYY-MM-DDTHH:MM."},
                "in_minutes": {"type": "integer", "minimum": 1, "maximum": 525600,
                               "description": "Minutes from now."},
            },
            "required": ["message"],
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        name="list_reminders",
        description="List up to 10 upcoming pending reminders, each with an id and its local time.",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
    ),
    ToolSpec(
        name="cancel_reminder",
        description="Cancel a pending reminder by its id (use list_reminders to find the id).",
        input_schema={
            "type": "object",
            "properties": {"id": {"type": "integer", "description": "Reminder id."}},
            "required": ["id"],
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        name="get_calendar_events",
        description=(
            "Read events from the family calendar starting at local midnight of `start_date` "
            "(YYYY-MM-DD, family local time) and covering `days` days (1-14, default 1)."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "start_date": {"type": "string", "description": "YYYY-MM-DD, family local date."},
                "days": {"type": "integer", "minimum": 1, "maximum": 14, "default": 1},
            },
            "required": ["start_date"],
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        name="add_calendar_event",
        description=(
            "Add an event to the family calendar. Give `title` and either `start` "
            "(family local time, YYYY-MM-DDTHH:MM; optional `end`, default one hour) or `date` "
            "(YYYY-MM-DD) for an all-day event. Optional `location`."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "start": {"type": "string", "description": "Family local time, YYYY-MM-DDTHH:MM."},
                "end": {"type": "string", "description": "Family local time, YYYY-MM-DDTHH:MM."},
                "date": {"type": "string", "description": "YYYY-MM-DD for an all-day event."},
                "location": {"type": "string"},
            },
            "required": ["title"],
            "additionalProperties": False,
        },
    ),
]

HOUSEHOLD_NAMES: frozenset[str] = frozenset(t.name for t in HOUSEHOLD_TOOLS)


class _ToolError(Exception):
    pass


def _fmt_day(d: date) -> str:
    return f"{d:%A}, {d:%B} {d.day}"


def _fmt_time(dt: datetime) -> str:
    h = dt.hour % 12 or 12
    return f"{h}:{dt.minute:02d} {'AM' if dt.hour < 12 else 'PM'}"


def _fmt_when(dt: datetime) -> str:
    return f"{_fmt_day(dt.date())} at {_fmt_time(dt)}"


class Household:
    def __init__(self, settings, store, ha, clock: Callable[[], datetime]):
        self._s = settings
        self._store = store
        self._ha = ha
        self._clock = clock
        self._tz = ZoneInfo(settings.tz)

    def run(self, name: str, args: dict) -> tuple[str, bool]:
        try:
            handler = {
                "set_reminder": self._set_reminder,
                "list_reminders": self._list_reminders,
                "cancel_reminder": self._cancel_reminder,
                "get_calendar_events": self._get_events,
                "add_calendar_event": self._add_event,
            }.get(name)
            if handler is None:
                return f"I don't have a tool called {name}.", True
            return handler(args if isinstance(args, dict) else {})
        except _ToolError as e:
            return str(e), True
        except Exception:
            log.exception("household tool failed: %s", name)
            return "Sorry, that didn't work.", True

    # -- helpers
    def _parse_local(self, value, what: str) -> datetime:
        m = _TIME_RE.match(str(value).strip())
        if not m:
            raise _ToolError(f"The {what} time must look like 2026-11-27T09:00.")
        try:
            dt = datetime.fromisoformat(m.group(1))  # any offset/Z is ignored: the time is family-local
        except ValueError:
            raise _ToolError(f"The {what} time must look like 2026-11-27T09:00.")
        return dt.replace(second=0, microsecond=0, tzinfo=self._tz)

    def _parse_date(self, value, what: str) -> date:
        try:
            return date.fromisoformat(str(value).strip())
        except ValueError:
            raise _ToolError(f"The {what} must be a date like 2026-11-27.")

    # -- reminders
    def _set_reminder(self, args: dict) -> tuple[str, bool]:
        message = args.get("message")
        message = message.strip() if isinstance(message, str) else ""
        if not message:
            raise _ToolError("The reminder needs a message.")
        if len(message) > 200:
            raise _ToolError("That reminder message is too long; keep it under 200 characters.")
        if not self._s.reminder_notify_service:
            raise _ToolError("Reminders can't be delivered yet because no phone is set up.")
        at, mins = args.get("at"), args.get("in_minutes")
        if (at is None) == (mins is None):
            raise _ToolError("Give either a time or a number of minutes, not both or neither.")
        now = self._clock()
        if mins is not None:
            if isinstance(mins, bool) or not isinstance(mins, int) or not 1 <= mins <= 525600:
                raise _ToolError("The number of minutes must be between 1 and 525600.")
            due = now + timedelta(minutes=mins)
        else:
            due = self._parse_local(at, "reminder").astimezone(timezone.utc)
            if due < now - timedelta(seconds=60):
                raise _ToolError("That time has already passed.")
            if due < now:
                due = now
            if due > now + timedelta(days=365):
                raise _ToolError("I can only set reminders up to a year ahead.")
        if self._store.pending_count() >= _MAX_PENDING:
            raise _ToolError("There are too many pending reminders already; cancel one first.")
        rid = self._store.add_reminder(message, due, now)
        return f"Reminder set for {_fmt_when(due.astimezone(self._tz))} (id {rid}): {message}.", False

    def _list_reminders(self, args: dict) -> tuple[str, bool]:
        items = self._store.pending_reminders(10)
        if not items:
            return "There are no pending reminders.", False
        lines = [f"id {r.id}: {r.message} on {_fmt_when(r.due_utc.astimezone(self._tz))}" for r in items]
        return "Pending reminders:\n" + "\n".join(lines), False

    def _cancel_reminder(self, args: dict) -> tuple[str, bool]:
        rid = args.get("id")
        if isinstance(rid, bool) or not isinstance(rid, int):
            raise _ToolError("I need the numeric id of the reminder to cancel.")
        if not self._store.cancel_reminder(rid):
            raise _ToolError(f"There is no pending reminder with id {rid}.")
        return f"Cancelled reminder id {rid}.", False

    # -- calendar
    def _get_events(self, args: dict) -> tuple[str, bool]:
        cal = self._ha.find_calendar(self._s.calendar_entity)
        if not cal:
            return _NO_CALENDAR, False
        start_date = self._parse_date(args.get("start_date"), "start date")
        days = args.get("days", 1)
        if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 14:
            raise _ToolError("The number of days must be between 1 and 14.")
        start = datetime.combine(start_date, datetime.min.time(), tzinfo=self._tz)
        end = datetime.combine(start_date + timedelta(days=days), datetime.min.time(), tzinfo=self._tz)
        events = self._ha.calendar_events(cal, start, end)
        if events is None:
            raise _ToolError("I couldn't reach the family calendar.")
        rows = []
        for ev in events:
            try:
                rows.append(self._event_row(ev))
            except Exception:
                log.warning("skipping unreadable calendar event")
        if not rows:
            return "No events on the calendar for that time.", False
        rows.sort(key=lambda r: r[0])
        return "\n".join(r[1] for r in rows), False

    def _event_row(self, ev: dict) -> tuple[datetime, str]:
        st = ev.get("start") or {}
        title = str(ev.get("summary") or "Untitled event")
        if st.get("dateTime"):
            dt = datetime.fromisoformat(str(st["dateTime"]).replace("Z", "+00:00"))
            dt = dt.astimezone(self._tz) if dt.tzinfo else dt.replace(tzinfo=self._tz)
            when = _fmt_time(dt)
        else:
            d = date.fromisoformat(str(st["date"])[:10])
            dt = datetime.combine(d, datetime.min.time(), tzinfo=self._tz)
            when = "all day"
        line = f"{_fmt_day(dt.date())}: {when} {title}"
        if ev.get("location"):
            line += f" (at {ev['location']})"
        return dt, line

    def _add_event(self, args: dict) -> tuple[str, bool]:
        cal = self._ha.find_calendar(self._s.calendar_entity)
        if not cal:
            return _NO_CALENDAR, False
        title = args.get("title")
        title = title.strip() if isinstance(title, str) else ""
        if not title:
            raise _ToolError("The event needs a title.")
        location = args.get("location") or None
        start_s, day_s = args.get("start"), args.get("date")
        if (start_s is None) == (day_s is None):
            raise _ToolError("Give either a start time or an all-day date, not both or neither.")
        if day_s is not None:
            d = self._parse_date(day_s, "date")
            ok = self._ha.create_calendar_event(
                cal, title, start_date=d, end_date=d + timedelta(days=1), location=location)
            what = f"{_fmt_day(d)} (all day)"
        else:
            start = self._parse_local(start_s, "start")
            end = self._parse_local(args["end"], "end") if args.get("end") else start + timedelta(hours=1)
            if end <= start:
                raise _ToolError("The event must end after it starts.")
            ok = self._ha.create_calendar_event(cal, title, start=start, end=end, location=location)
            what = _fmt_when(start)
        if not ok:
            raise _ToolError("I couldn't add that to the family calendar.")
        return f"Added {title} to the family calendar for {what}.", False
