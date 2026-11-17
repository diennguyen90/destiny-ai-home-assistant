import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from destiny_brain.config import Settings
from destiny_brain.costs import Usage
from destiny_brain.engine import ConverseRequest, Engine
from destiny_brain.ha import HAClient
from destiny_brain.prompts import DESTINY_BASE
from destiny_brain.providers.base import ProviderError
from destiny_brain.store import RequestRecord, Store

from .fakes import FakeHA, FakeProvider, make_result

EMPTY = "I didn't catch that. Could you say it again?"
CAPPED = "I've done a lot of thinking today. Let's talk again tomorrow."
ERROR = "Sorry, something went wrong in my head. Please try again."
REFUSAL = "I can't help with that one. Let's ask a grown-up."
T0 = datetime(2026, 11, 17, 22, 30, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.now = T0

    def __call__(self):
        return self.now


@pytest.fixture
def env(tmp_path):
    settings = Settings(anthropic_api_key="k", brain_shared_key="s", parent_pin="1",
                        tz="America/Los_Angeles", notify_service="mobile_app_x")
    store = Store(str(tmp_path / "b.db"), settings.tz)
    store.init()
    return settings, store


def build(env, *results, ha=None):
    settings, store = env
    provider = FakeProvider(*results)
    clock = Clock()
    ha = ha or FakeHA()
    return Engine(settings, store, provider, ha, clock=clock), provider, store, ha, clock


def req(text, cid=None, device="d1"):
    return ConverseRequest(text=text, conversation_id=cid, device_id=device, satellite_id=None)


def spend(store, usd, now=T0):
    store.log(RequestRecord(ts_utc=now, conversation_id="x", device_id=None, tier=2, model="m",
                            route_reason="t", usage=Usage(0, 0), cost_usd=usd, latency_ms=1,
                            outcome="ok", text_chars=1))


def test_empty_text_no_model_call(env):
    e, p, store, *_ = build(env)
    r = e.handle(req("   "))
    assert r.speech == EMPTY and p.calls == []
    rec = store.recent()[0]
    assert rec.outcome == "empty" and rec.tier == 0


def test_simple_question_tier1(env):
    e, p, store, *_ = build(env, make_result("It is four."))
    r = e.handle(req("what is two plus two"))
    assert r.speech == "It is four."
    assert len(p.calls) == 1 and p.calls[0]["model"] == "claude-haiku-5-5"
    assert p.calls[0]["effort"] == "low" and p.calls[0]["max_tokens"] == 1024
    assert [t.name for t in p.calls[0]["tools"]] == ["needs_deeper_answer"]
    assert store.recent()[0].cost_usd > 0


def test_keyword_goes_tier2(env):
    e, p, *_ = build(env, make_result("Because.", model="claude-sonnet-5-5"))
    e.handle(req("explain the water cycle"))
    assert len(p.calls) == 1 and p.calls[0]["model"] == "claude-sonnet-5-5"
    assert p.calls[0]["tools"] == [] and p.calls[0]["effort"] == "medium"


def test_escalation_runs_sonnet_and_logs_two_records(env):
    esc = make_result("", tool_calls=[("needs_deeper_answer", {"reason": "teaching"})],
                      stop_reason="tool_use")
    e, p, store, *_ = build(env, esc, make_result("Deep answer.", model="claude-sonnet-5-5"))
    cid = e.handle(req("what is a black hole")).conversation_id
    assert [c["model"] for c in p.calls] == ["claude-haiku-5-5", "claude-sonnet-5-5"]
    assert p.calls[1]["tools"] == []
    assert p.calls[0]["messages"] == p.calls[1]["messages"]
    recs = store.recent()
    assert len(recs) == 2
    assert any(r.route_reason == "escalated" and r.tier == 1 for r in recs)
    assert any(r.tier == 2 for r in recs)
    # escalated tool-use result is not in history; next turn is sticky tier 2
    e.handle(req("and then", cid))
    assert p.calls[2]["model"] == "claude-sonnet-5-5"
    assert p.calls[2]["messages"][0] == {"role": "user", "content": "what is a black hole"}
    assert p.calls[2]["messages"][1] == {"role": "assistant",
                                         "content": [{"type": "text", "text": "Deep answer."}]}


def test_followup_keeps_history(env):
    first = make_result("Blue.")
    e, p, *_ = build(env, first, make_result("Red."))
    cid = e.handle(req("favorite color")).conversation_id
    e.handle(req("another", cid))
    msgs = p.calls[1]["messages"]
    assert msgs[0] == {"role": "user", "content": "favorite color"}
    assert msgs[1] == {"role": "assistant", "content": first.content}
    assert msgs[2] == {"role": "user", "content": "another"}


def test_unknown_conversation_id_gets_new_and_isolated(env):
    e, p, *_ = build(env)
    a = e.handle(req("secret apple")).conversation_id
    b = e.handle(req("hello b")).conversation_id
    assert a != b
    e.handle(req("more a", a))
    assert all("hello b" not in json.dumps(m) for m in p.calls[2]["messages"])
    assert any("secret apple" in json.dumps(m) for m in p.calls[2]["messages"])
    r = e.handle(req("who am i", "unknown-id"))
    assert r.conversation_id != "unknown-id"
    assert len(p.calls[3]["messages"]) == 1


def test_history_expires_after_10_min(env):
    e, p, _, _, clock = build(env)
    cid = e.handle(req("one")).conversation_id
    clock.now += timedelta(minutes=9)
    assert e.handle(req("two", cid)).conversation_id == cid
    assert len(p.calls[1]["messages"]) == 3
    clock.now += timedelta(minutes=11)
    r = e.handle(req("three", cid))
    assert r.conversation_id != cid
    assert len(p.calls[2]["messages"]) == 1


def test_history_capped_at_20_messages(env):
    e, p, *_ = build(env)
    cid = e.handle(req("m0")).conversation_id
    for i in range(1, 15):
        e.handle(req(f"m{i}", cid))
    assert len(p.calls[-1]["messages"]) <= 21


def test_hard_cap_blocks(env):
    e, p, store, *_ = build(env)
    spend(store, 3.0)
    r = e.handle(req("hi"))
    assert r.speech == CAPPED and p.calls == []
    assert store.recent()[0].outcome == "capped"


def test_soft_cap_downgrades_and_notifies_once(env):
    e, p, store, ha, _ = build(env)
    spend(store, 1.5)
    e.handle(req("explain gravity"))
    e.handle(req("explain magnets"))
    assert [c["model"] for c in p.calls] == ["claude-haiku-5-5"] * 2
    assert len(ha.notifications) == 1
    service, title, msg = ha.notifications[0]
    assert service == "mobile_app_x" and title == "Destiny"
    assert msg == ("Destiny reached today's soft spending cap ($1.00). "
                   "Long answers use the faster model until tomorrow.")
    assert any(r.route_reason == "soft_cap" for r in store.recent())


def test_soft_cap_no_notify_without_service(tmp_path):
    settings = Settings(anthropic_api_key="k", brain_shared_key="s", parent_pin="1")
    store = Store(str(tmp_path / "c.db"), settings.tz)
    store.init()
    spend(store, 1.5)
    ha = FakeHA()
    Engine(settings, store, FakeProvider(), ha, clock=Clock()).handle(req("explain gravity"))
    assert ha.notifications == []


def test_provider_error_returns_line_and_logs_error(env):
    e, p, store, *_ = build(env, ProviderError("rate_limit"), RuntimeError("boom"), make_result("ok"))
    cid = e.handle(req("hello")).conversation_id
    assert store.recent()[0].outcome == "error"
    r = e.handle(req("hello", cid))
    assert r.speech == ERROR
    assert store.recent()[0].outcome == "error"
    r3 = e.handle(req("again", cid))
    assert r3.speech == "ok"
    assert p.calls[2]["messages"] == [{"role": "user", "content": "again"}]


def test_refusal_line(env):
    e, _, store, *_ = build(env, make_result("", stop_reason="refusal"))
    assert e.handle(req("bad")).speech == REFUSAL
    assert store.recent()[0].outcome == "refusal"


def test_context_has_weather_and_local_time(env):
    e, p, *_ = build(env)
    e.handle(req("hi"))
    system = p.calls[0]["system"]
    assert system[0] == {"type": "text", "text": DESTINY_BASE, "cache_control": {"type": "ephemeral"}}
    assert "cache_control" not in system[1]
    assert "Home weather now: sunny, 69°F, humidity 26%." in system[1]["text"]
    assert "November 17, 2026" in system[1]["text"]
    assert "2:30 PM" in system[1]["text"]  # 22:30 UTC is 14:30 in Los Angeles


def test_continue_conversation_on_question(env):
    e, *_ = build(env, make_result("Want more?"), make_result("Done."))
    assert e.handle(req("hi")).continue_conversation is True
    assert e.handle(req("hi")).continue_conversation is False


def test_weather_line_none_on_ha_failure(env):
    e, p, *_ = build(env, ha=FakeHA(weather=None))
    assert e.handle(req("hi")).speech
    assert "weather" not in p.calls[0]["system"][1]["text"].lower()


def test_non_ascii_round_trip(env):
    e, p, *_ = build(env)
    e.handle(req("café 你好 🎉"))
    assert p.calls[0]["messages"][0]["content"] == "café 你好 🎉"


# --- HAClient ---

def ha_client(handler, clock=None):
    return HAClient("http://ha:8123", "tok", httpx.Client(transport=httpx.MockTransport(handler)),
                    **({"clock": clock} if clock else {}))


def test_ha_weather_line_and_cache():
    hits = []

    def handler(request):
        hits.append(request)
        assert request.headers["authorization"] == "Bearer tok"
        assert request.url.path == "/api/states/weather.home"
        return httpx.Response(200, json={"state": "sunny", "attributes": {
            "temperature": 68.6, "temperature_unit": "°F", "humidity": 26}})

    clock = Clock()
    ha = ha_client(handler, clock)
    assert ha.weather_line("weather.home") == "Home weather now: sunny, 69°F, humidity 26%."
    ha.weather_line("weather.home")
    assert len(hits) == 1
    clock.now += timedelta(minutes=6)
    ha.weather_line("weather.home")
    assert len(hits) == 2


def test_ha_weather_none_on_failure():
    assert ha_client(lambda r: httpx.Response(500)).weather_line("weather.home") is None

    def boom(r):
        raise httpx.ConnectError("x")

    assert ha_client(boom).weather_line("weather.home") is None


def test_ha_notify():
    seen = []

    def handler(request):
        seen.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json=[])

    assert ha_client(handler).notify("mobile_app_x", "Destiny", "hi") is True
    assert seen == [("/api/services/notify/mobile_app_x", {"title": "Destiny", "message": "hi"})]
    assert ha_client(lambda r: httpx.Response(401)).notify("s", "t", "m") is False

    def boom(r):
        raise httpx.ConnectError("x")

    assert ha_client(boom).notify("s", "t", "m") is False
