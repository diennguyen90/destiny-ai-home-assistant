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


def test_store_migrates_first_token_ms(tmp_path):
    import sqlite3
    path = str(tmp_path / "old.db")
    c = sqlite3.connect(path)
    c.executescript("""
    CREATE TABLE requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT, ts_utc TEXT NOT NULL, conversation_id TEXT NOT NULL,
        device_id TEXT, tier INTEGER NOT NULL, model TEXT, route_reason TEXT NOT NULL,
        input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL,
        cache_read_tokens INTEGER NOT NULL, cache_write_tokens INTEGER NOT NULL,
        cost_usd REAL NOT NULL, latency_ms INTEGER NOT NULL, outcome TEXT NOT NULL,
        text_chars INTEGER NOT NULL);
    INSERT INTO requests (ts_utc, conversation_id, tier, route_reason, input_tokens, output_tokens,
        cache_read_tokens, cache_write_tokens, cost_usd, latency_ms, outcome, text_chars)
        VALUES ('2026-11-17T09:00:00.000000+00:00','old',1,'x',1,1,0,0,0.1,5,'ok',3);
    """)
    c.commit()
    c.close()
    s = Store(path, "America/Los_Angeles")
    s.init()
    s.init()  # idempotent
    s.log(rec(utc(2026, 11, 17, 10, 0), 0.2, conversation_id="new", first_token_ms=420))
    got = {r.conversation_id: r for r in s.recent()}
    assert got["new"].first_token_ms == 420
    assert got["old"].first_token_ms is None


def test_store_migrates_web_searches(tmp_path):
    import sqlite3
    path = str(tmp_path / "old2.db")
    c = sqlite3.connect(path)
    c.executescript("""
    CREATE TABLE requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT, ts_utc TEXT NOT NULL, conversation_id TEXT NOT NULL,
        device_id TEXT, tier INTEGER NOT NULL, model TEXT, route_reason TEXT NOT NULL,
        input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL,
        cache_read_tokens INTEGER NOT NULL, cache_write_tokens INTEGER NOT NULL,
        cost_usd REAL NOT NULL, latency_ms INTEGER NOT NULL, outcome TEXT NOT NULL,
        text_chars INTEGER NOT NULL, first_token_ms INTEGER);
    INSERT INTO requests (ts_utc, conversation_id, tier, route_reason, input_tokens, output_tokens,
        cache_read_tokens, cache_write_tokens, cost_usd, latency_ms, outcome, text_chars)
        VALUES ('2026-11-17T09:00:00.000000+00:00','old',1,'x',1,1,0,0,0.1,5,'ok',3);
    """)
    c.commit()
    c.close()
    s = Store(path, "America/Los_Angeles")
    s.init()
    s.init()  # idempotent
    s.log(rec(utc(2026, 11, 17, 10, 0), 0.2, conversation_id="new", web_searches=2))
    got = {r.conversation_id: r for r in s.recent()}
    assert got["new"].web_searches == 2
    assert got["old"].web_searches is None


def test_reminder_round_trip(store):
    now = utc(2026, 11, 26, 12, 0)
    late = store.add_reminder("later", utc(2026, 11, 26, 15, 0), now)
    early = store.add_reminder("early", utc(2026, 11, 26, 13, 0), now)
    assert store.pending_count() == 2
    assert [r.id for r in store.pending_reminders()] == [early, late]
    assert store.pending_reminders(limit=1)[0].message == "early"
    assert store.due_reminders(utc(2026, 11, 26, 12, 30)) == []
    due = store.due_reminders(utc(2026, 11, 26, 13, 0))
    assert [r.id for r in due] == [early]
    assert due[0].status == "pending" and due[0].attempts == 0 and due[0].sent_utc is None
    assert store.cancel_reminder(late) is True
    assert store.cancel_reminder(late) is False
    assert store.pending_count() == 1
    assert store.bump_reminder_attempts(early) == 1
    assert store.bump_reminder_attempts(early) == 2
    sent_at = utc(2026, 11, 26, 13, 1)
    store.mark_reminder(early, "sent", sent_at)
    assert store.pending_count() == 0
    assert store.cancel_reminder(early) is False
    rows = store._exec("SELECT status, sent_utc, attempts FROM reminders WHERE id = ?", (early,))
    assert rows[0][0] == "sent" and datetime.fromisoformat(rows[0][1]) == sent_at and rows[0][2] == 2


def test_mark_reminder_does_not_overwrite_cancelled(store):
    now = utc(2026, 11, 26, 12, 0)
    rid = store.add_reminder("x", utc(2026, 11, 26, 13, 0), now)
    assert store.cancel_reminder(rid) is True
    store.mark_reminder(rid, "sent", now)
    assert store._exec("SELECT status, sent_utc FROM reminders WHERE id = ?", (rid,))[0] == ("cancelled", None)
