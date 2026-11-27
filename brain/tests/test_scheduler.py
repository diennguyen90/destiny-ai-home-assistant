import threading
from datetime import datetime, timedelta, timezone

import pytest

from destiny_brain.config import Settings
from destiny_brain.scheduler import ReminderScheduler
from destiny_brain.store import Store
from tests.fakes import FakeHA

NOW = datetime(2026, 11, 26, 12, 0, tzinfo=timezone.utc)
SVC = "notify.mobile_app_phone"


@pytest.fixture
def env(tmp_path):
    store = Store(str(tmp_path / "s.db"), "Etc/UTC")
    store.init()
    ha = FakeHA()
    settings = Settings(anthropic_api_key="k", brain_shared_key="s", parent_pin="p",
                        reminder_notify_service=SVC)
    sched = ReminderScheduler(settings, store, ha, clock=lambda: NOW)
    return store, ha, sched


def status(store, rid):
    return store._exec("SELECT status, attempts FROM reminders WHERE id = ?", (rid,))[0]


def test_on_time_send(env):
    store, ha, sched = env
    rid = store.add_reminder("take pills", NOW - timedelta(seconds=30), NOW)
    assert sched.tick() == 1
    assert ha.notifications == [(SVC, "Destiny reminder", "take pills")]
    assert status(store, rid)[0] == "sent"
    assert sched.tick() == 0


def test_late_reminder_prefixed(env):
    store, ha, sched = env
    store.add_reminder("take pills", NOW - timedelta(minutes=6), NOW)
    sched.tick()
    assert ha.notifications[0][2] == "(Late) take pills"


def test_over_24h_expired(env):
    store, ha, sched = env
    rid = store.add_reminder("old", NOW - timedelta(hours=25), NOW)
    assert sched.tick() == 0
    assert ha.notifications == []
    assert status(store, rid)[0] == "expired"


def test_future_not_sent(env):
    store, ha, sched = env
    rid = store.add_reminder("later", NOW + timedelta(minutes=1), NOW)
    assert sched.tick() == 0
    assert ha.notifications == []
    assert status(store, rid)[0] == "pending"


def test_notify_failure_retries_until_expiry(env):
    store, ha, sched = env
    ha.notify_ok = False
    rid = store.add_reminder("x", NOW - timedelta(seconds=1), NOW)
    for n in range(1, 61):
        sched.tick()
        assert tuple(status(store, rid)) == ("pending", n)
    ha.notify_ok = True
    assert sched.tick() == 1
    assert status(store, rid)[0] == "sent"
    ha.notify_ok = False
    rid2 = store.add_reminder("y", NOW - timedelta(hours=25), NOW)
    sched.tick()
    assert status(store, rid2)[0] == "expired"


def test_tick_serialized_no_double_send(env):
    store, ha, sched = env
    store.add_reminder("once", NOW - timedelta(seconds=1), NOW)
    barrier = threading.Barrier(2)

    def go():
        barrier.wait()
        sched.tick()

    ts = [threading.Thread(target=go) for _ in range(2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert len(ha.notifications) == 1


def test_no_service_sends_nothing(tmp_path):
    store = Store(str(tmp_path / "n.db"), "Etc/UTC")
    store.init()
    ha = FakeHA()
    settings = Settings(anthropic_api_key="k", brain_shared_key="s", parent_pin="p")
    sched = ReminderScheduler(settings, store, ha, clock=lambda: NOW)
    store.add_reminder("x", NOW - timedelta(seconds=1), NOW)
    assert sched.tick() == 0
    assert ha.notifications == []
