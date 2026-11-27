import json
from datetime import date, datetime, timedelta, timezone

import httpx

from destiny_brain.ha import HAClient

NOW = datetime(2026, 11, 26, 12, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.now = NOW

    def __call__(self):
        return self.now


def make(handler, clock=None):
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return HAClient("http://ha:8123/", "tok", http, clock=clock or Clock())


def test_find_calendar_preferred_skips_http():
    def handler(request):
        raise AssertionError("no request expected")
    assert make(handler).find_calendar("calendar.mine") == "calendar.mine"


def test_find_calendar_discovers_sorted_first_and_caches():
    hits = []

    def handler(request):
        hits.append(request)
        assert request.url.path == "/api/states"
        assert request.headers["authorization"] == "Bearer tok"
        return httpx.Response(200, json=[
            {"entity_id": "weather.home"}, {"entity_id": "calendar.zeta"},
            {"entity_id": "calendar.alpha"},
        ])
    clock = Clock()
    ha = make(handler, clock)
    assert ha.find_calendar() == "calendar.alpha"
    assert ha.find_calendar() == "calendar.alpha"
    assert len(hits) == 1
    clock.now = NOW + timedelta(minutes=6)
    assert ha.find_calendar() == "calendar.alpha"
    assert len(hits) == 2


def test_find_calendar_none_on_error_and_when_missing():
    assert make(lambda r: httpx.Response(500)).find_calendar() is None
    assert make(lambda r: httpx.Response(200, json=[{"entity_id": "light.a"}])).find_calendar() is None


def test_calendar_events_request_and_result():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=[{"summary": "Dentist"}])
    start = datetime(2026, 11, 26, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 11, 27, 0, 0, tzinfo=timezone.utc)
    assert make(handler).calendar_events("calendar.family", start, end) == [{"summary": "Dentist"}]
    req = seen[0]
    assert req.method == "GET"
    assert req.url.path == "/api/calendars/calendar.family"
    assert req.url.params["start"] == start.isoformat()
    assert req.url.params["end"] == end.isoformat()
    assert req.headers["authorization"] == "Bearer tok"


def test_calendar_events_none_on_500():
    assert make(lambda r: httpx.Response(500)).calendar_events("calendar.f", NOW, NOW) is None


def test_create_event_timed_and_all_day():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=[])
    ha = make(handler)
    start = datetime(2026, 11, 27, 15, 0, tzinfo=timezone.utc)
    end = start + timedelta(hours=1)
    assert ha.create_calendar_event("calendar.f", "Soccer", start=start, end=end, location="Park")
    assert ha.create_calendar_event("calendar.f", "Trip", start_date=date(2026, 12, 1),
                                    end_date=date(2026, 12, 2))
    r1, r2 = seen
    assert r1.method == "POST" and r1.url.path == "/api/services/calendar/create_event"
    assert json.loads(r1.content) == {
        "entity_id": "calendar.f", "summary": "Soccer", "start_date_time": start.isoformat(),
        "end_date_time": end.isoformat(), "location": "Park"}
    assert json.loads(r2.content) == {
        "entity_id": "calendar.f", "summary": "Trip", "start_date": "2026-12-01",
        "end_date": "2026-12-02"}


def test_create_event_false_on_500():
    assert make(lambda r: httpx.Response(500)).create_calendar_event(
        "calendar.f", "x", start=NOW, end=NOW) is False


def _states(*cals):
    return lambda r: httpx.Response(200, json=[
        {"entity_id": e, "attributes": {"supported_features": f, "friendly_name": n or e}} for e, f, n in cals])


def test_find_calendar_prefers_writable_non_holiday():
    h = _states(("calendar.a_holidays", 1, "Holidays in US"), ("calendar.b_ro", 0, None),
                ("calendar.c_family", 1, None), ("calendar.d_family", 1, None))
    assert make(h).find_calendar() == "calendar.c_family"


def test_find_calendar_then_non_holiday_then_any():
    h = _states(("calendar.a_birthdays", 1, None), ("calendar.b_ro", 0, None), ("calendar.c_x", 0, None))
    assert make(h).find_calendar() == "calendar.b_ro"
    h = _states(("calendar.z_holiday", 0, None), ("calendar.b_birthdays", 1, "Birthdays"))
    assert make(h).find_calendar() == "calendar.b_birthdays"
    h = _states(("calendar.a", 0, "Our Holiday plans"), ("calendar.b", 1, "Family"))
    assert make(h).find_calendar() == "calendar.b"


def test_find_calendar_logs_choice_on_change(caplog):
    import logging
    clock = Clock()
    ha = make(_states(("calendar.a", 1, None)), clock)
    with caplog.at_level(logging.WARNING):
        ha.find_calendar()
        clock.now = NOW + timedelta(minutes=6)
        ha.find_calendar()
    assert len([r for r in caplog.records if "calendar.a" in r.getMessage()]) == 1
