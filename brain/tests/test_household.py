from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from destiny_brain.config import Settings
from destiny_brain.household import HOUSEHOLD_NAMES, HOUSEHOLD_TOOLS, Household
from destiny_brain.store import Store
from tests.fakes import FakeHA

TZ = ZoneInfo("America/Los_Angeles")


def local(y, mo, d, h, mi, s=0):
    return datetime(y, mo, d, h, mi, s, tzinfo=TZ).astimezone(timezone.utc)


@pytest.fixture
def env(tmp_path):
    settings = Settings(anthropic_api_key="k", brain_shared_key="s", parent_pin="p", tz="America/Los_Angeles",
                        reminder_notify_service="notify.phone")
    store = Store(str(tmp_path / "b.db"), settings.tz)
    store.init()
    ha = FakeHA()
    now = {"t": local(2026, 11, 26, 16, 0)}
    hh = Household(settings, store, ha, lambda: now["t"])
    return hh, store, ha, now


def test_tool_order_and_names():
    assert [t.name for t in HOUSEHOLD_TOOLS] == [
        "set_reminder", "list_reminders", "cancel_reminder", "get_calendar_events", "add_calendar_event"]
    assert HOUSEHOLD_NAMES == {t.name for t in HOUSEHOLD_TOOLS}
    assert all(t.input_schema["additionalProperties"] is False for t in HOUSEHOLD_TOOLS)


def test_set_reminder_in_minutes(env):
    hh, store, _, _ = env
    text, err = hh.run("set_reminder", {"message": "Take out the trash", "in_minutes": 20})
    assert not err and "4:20 PM" in text
    assert store.pending_reminders()[0].due_utc == local(2026, 11, 26, 16, 20)


def test_set_reminder_at_is_local_time(env):
    hh, store, _, now = env
    now["t"] = local(2026, 11, 26, 23, 58)
    text, err = hh.run("set_reminder", {"message": "Call Grandma", "at": "2026-11-27T09:00"})
    assert not err and "Friday, November 27 at 9:00 AM" in text
    assert store.pending_reminders()[0].due_utc == datetime(2026, 11, 27, 17, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("args", [
    {"message": "x", "at": "2026-11-27T09:00", "in_minutes": 5},
    {"message": "x"},
    {"message": "x", "at": "tomorrow 9am"},
    {"message": "x", "at": "2026-11-26T15:58"},
    {"message": "x", "at": "2027-11-28T09:00"},
    {"message": "x", "in_minutes": 525601},
    {"message": "", "in_minutes": 5},
    {"message": "y" * 201, "in_minutes": 5},
])
def test_set_reminder_errors(env, args):
    hh, store, _, _ = env
    _, err = hh.run("set_reminder", args)
    assert err and store.pending_count() == 0


def test_set_reminder_limit(env):
    hh, store, _, now = env
    for _ in range(50):
        store.add_reminder("m", local(2026, 12, 1, 9, 0), now["t"])
    _, err = hh.run("set_reminder", {"message": "x", "in_minutes": 5})
    assert err and store.pending_count() == 50


def test_set_reminder_slightly_past_clamped(env):
    hh, store, _, now = env
    _, err = hh.run("set_reminder", {"message": "x", "at": "2026-11-26T15:59"})
    assert not err
    assert store.pending_reminders()[0].due_utc == now["t"]


def test_list_and_cancel(env):
    hh, store, _, _ = env
    assert hh.run("list_reminders", {}) == ("There are no pending reminders.", False)
    hh.run("set_reminder", {"message": "Trash", "in_minutes": 20})
    text, err = hh.run("list_reminders", {})
    assert not err and "id 1" in text and "Trash" in text
    assert hh.run("cancel_reminder", {"id": 1})[1] is False
    assert hh.run("cancel_reminder", {"id": 1})[1] is True
    assert hh.run("cancel_reminder", {"id": 99})[1] is True


def test_unknown_tool(env):
    assert env[0].run("nope", {})[1] is True


def test_calendar_not_connected(env):
    hh, _, ha, _ = env
    ha.calendar = None
    exp = ("The family calendar isn't connected yet.", False)
    assert hh.run("get_calendar_events", {"start_date": "2026-11-27"}) == exp
    assert hh.run("add_calendar_event", {"title": "x", "date": "2026-11-27"}) == exp


def test_calendar_read(env):
    hh, _, ha, _ = env
    ha.events = [
        {"summary": "Birthday", "start": {"date": "2026-11-27"}, "end": {"date": "2026-11-28"}},
        {"summary": "Dentist", "location": "Main St",
         "start": {"dateTime": "2026-11-27T15:00:00-08:00"}, "end": {"dateTime": "2026-11-27T16:00:00-08:00"}},
    ]
    text, err = hh.run("get_calendar_events", {"start_date": "2026-11-27"})
    assert not err
    assert "Friday, November 27: all day Birthday" in text
    assert "Friday, November 27: 3:00 PM Dentist (at Main St)" in text
    ha.events = []
    assert hh.run("get_calendar_events", {"start_date": "2026-11-27"}) == (
        "No events on the calendar for that time.", False)


def test_calendar_read_uses_aware_window(env):
    hh, _, ha, _ = env
    seen = {}
    ha.calendar_events = lambda cal, s, e: seen.update(s=s, e=e) or []
    hh.run("get_calendar_events", {"start_date": "2026-11-27", "days": 2})
    assert seen["s"].tzinfo is not None and seen["s"].hour == 0 and seen["s"].day == 27
    assert seen["e"].day == 29


def test_calendar_add_default_end(env):
    hh, _, ha, _ = env
    _, err = hh.run("add_calendar_event", {"title": "Dentist", "start": "2026-11-27T15:00", "location": "Main St"})
    assert not err
    c = ha.created[0]
    assert c["start"] == datetime(2026, 11, 27, 15, 0, tzinfo=TZ)
    assert c["end"] == datetime(2026, 11, 27, 16, 0, tzinfo=TZ)
    assert c["location"] == "Main St"


def test_calendar_add_all_day(env):
    hh, _, ha, _ = env
    _, err = hh.run("add_calendar_event", {"title": "Trip", "date": "2026-11-27"})
    assert not err
    assert ha.created[0]["start_date"] == date(2026, 11, 27)
    assert ha.created[0]["end_date"] == date(2026, 11, 28)


def test_calendar_add_failure(env):
    hh, _, ha, _ = env
    ha.create_calendar_event = lambda *a, **k: False
    assert hh.run("add_calendar_event", {"title": "x", "date": "2026-11-27"})[1] is True


def test_time_with_seconds_accepted(env):
    hh, store, _, _ = env
    _, err = hh.run("set_reminder", {"message": "x", "at": "2026-11-27T09:00:30"})
    assert not err
    assert store.pending_reminders()[0].due_utc == datetime(2026, 11, 27, 17, 0, tzinfo=timezone.utc)


def test_time_offset_ignored_as_local(env):
    hh, _, ha, _ = env
    _, err = hh.run("add_calendar_event", {"title": "x", "start": "2026-11-27T17:00:00Z"})
    assert not err
    assert ha.created[0]["start"] == datetime(2026, 11, 27, 17, 0, tzinfo=TZ)


def test_set_reminder_errors_without_notify_service(env):
    from dataclasses import replace
    hh, store, _, _ = env
    hh._s = replace(hh._s, reminder_notify_service="")
    text, err = hh.run("set_reminder", {"message": "x", "in_minutes": 5})
    assert err and text == "Reminders can't be delivered yet because no phone is set up."
    assert store.pending_reminders() == []
