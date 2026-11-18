import dataclasses
from datetime import date, datetime, timezone

import pytest

from destiny_brain.costs import Usage
from destiny_brain.store import RequestRecord, Store


def rec(ts, cost, **kw):
    base = dict(
        ts_utc=ts, conversation_id="c1", device_id="d1", tier=1, model="claude-haiku-5-5",
        route_reason="test", usage=Usage(10, 5, 2, 1), cost_usd=cost, latency_ms=120,
        outcome="ok", text_chars=42,
    )
    base.update(kw)
    return RequestRecord(**base)


@pytest.fixture
def store(tmp_path):
    s = Store(str(tmp_path / "b.db"), "America/Los_Angeles")
    s.init()
    return s


def utc(*a):
    return datetime(*a, tzinfo=timezone.utc)


def test_spend_today_sums_local_day(store):
    store.log(rec(utc(2026, 11, 17, 7, 30), 0.40))  # Nov 16 23:30 local
    store.log(rec(utc(2026, 11, 17, 9, 0), 0.25))   # Nov 17 01:00 local
    assert store.spend_today(utc(2026, 11, 17, 20, 0)) == pytest.approx(0.25)
    assert store.spend_today(utc(2026, 11, 17, 7, 45)) == pytest.approx(0.40)


def test_recent_roundtrip_and_order(store):
    store.log(rec(utc(2026, 11, 17, 9, 0), 0.1, conversation_id="a"))
    store.log(rec(utc(2026, 11, 17, 10, 0), 0.2, conversation_id="b", device_id=None, model=None, tier=0))
    got = store.recent(1)
    assert len(got) == 1 and got[0].conversation_id == "b" and got[0].device_id is None
    both = store.recent()
    assert [r.conversation_id for r in both] == ["b", "a"]
    assert both[1].usage == Usage(10, 5, 2, 1) and both[1].ts_utc == utc(2026, 11, 17, 9, 0)


def test_recent_has_no_text_fields(store):
    names = [f.name for f in dataclasses.fields(RequestRecord)]
    assert [n for n in names if "text" in n] == ["text_chars"]
    store.log(rec(utc(2026, 11, 17, 9, 0), 0.1))
    assert not [n for n in vars(store.recent()[0]) if "text" in n and n != "text_chars"]


def test_cost_by_day(store):
    store.log(rec(utc(2026, 11, 17, 7, 30), 0.40))
    store.log(rec(utc(2026, 11, 17, 9, 0), 0.25))
    store.log(rec(utc(2026, 11, 17, 10, 0), 0.05))
    out = store.cost_by_day(days=3, now_utc=utc(2026, 11, 17, 20, 0))
    assert out == [(date(2026, 11, 15), 0.0), (date(2026, 11, 16), pytest.approx(0.40)),
                   (date(2026, 11, 17), pytest.approx(0.30))]


def test_soft_cap_notified_once_per_day(store):
    d = date(2026, 11, 17)
    assert store.soft_cap_notified(d) is False
    store.mark_soft_cap_notified(d)
    store.mark_soft_cap_notified(d)
    assert store.soft_cap_notified(d) is True
    assert store.soft_cap_notified(date(2026, 11, 18)) is False
