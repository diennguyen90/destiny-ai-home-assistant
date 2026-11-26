import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from destiny_brain.config import Settings
from destiny_brain.costs import Usage
from destiny_brain.engine import BRIDGES, ERROR_LINE, ConverseRequest, Engine
from destiny_brain.ha import HAClient
from destiny_brain.prompts import DESTINY_BASE, ESCALATE_TOOL, WEB_SEARCH_TOOL
from destiny_brain.providers.base import HEARTBEAT, SEARCH_STARTED, ProviderError
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
    assert p.calls[2]["messages"][1]["role"] == "system"
    assert p.calls[2]["messages"][2] == {"role": "assistant",
                                         "content": [{"type": "text", "text": "Deep answer."}]}


def test_followup_keeps_history(env):
    first = make_result("Blue.")
    e, p, *_ = build(env, first, make_result("Red."))
    cid = e.handle(req("favorite color")).conversation_id
    e.handle(req("another", cid))
    msgs = p.calls[1]["messages"]
    assert msgs[0] == {"role": "user", "content": "favorite color"}
    assert msgs[1]["role"] == "system"
    assert msgs[2] == {"role": "assistant", "content": first.content}
    assert msgs[3] == {"role": "user", "content": "another"}
    assert msgs[4]["role"] == "system"


def test_unknown_id_is_adopted_and_isolated(env):
    e, p, *_ = build(env)
    e.handle(req("secret apple", "A"))
    e.handle(req("hello b", "B"))
    e.handle(req("more a", "A"))
    assert all("hello b" not in json.dumps(m) for m in p.calls[2]["messages"])
    assert any("secret apple" in json.dumps(m) for m in p.calls[2]["messages"])
    r = e.handle(req("who am i", "abc"))
    assert r.conversation_id == "abc"
    assert [m["role"] for m in p.calls[3]["messages"]] == ["user", "system"]


def test_missing_or_oversized_id_generates_uuid(env):
    e, *_ = build(env)
    assert len(e.handle(req("hi")).conversation_id) == 32
    assert len(e.handle(req("hi", "")).conversation_id) == 32
    long_id = "x" * 129
    assert e.handle(req("hi", long_id)).conversation_id != long_id
    assert e.handle(req("hi", "y" * 128)).conversation_id == "y" * 128


def test_same_caller_id_twice_keeps_history(env):
    e, p, *_ = build(env)
    e.handle(req("first thing", "01JHAULID"))
    r = e.handle(req("second thing", "01JHAULID"))
    assert r.conversation_id == "01JHAULID"
    assert any("first thing" in json.dumps(m) for m in p.calls[1]["messages"])


def test_history_expires_after_10_min(env):
    e, p, _, _, clock = build(env)
    cid = e.handle(req("one")).conversation_id
    clock.now += timedelta(minutes=9)
    assert e.handle(req("two", cid)).conversation_id == cid
    assert len(p.calls[1]["messages"]) == 5
    clock.now += timedelta(minutes=11)
    r = e.handle(req("three", cid))
    assert r.conversation_id == cid
    assert len(p.calls[2]["messages"]) == 2


def test_history_never_starts_with_non_user(env):
    e, p, *_ = build(env)
    cid = e.handle(req("m0", "H1")).conversation_id
    for i in range(1, 15):
        e.handle(req(f"m{i}", cid))
    for c in p.calls:
        msgs = c["messages"]
        assert msgs[0]["role"] == "user"
        assert len(msgs) % 3 == 2
        assert msgs[-2]["role"] == "user" and msgs[-1]["role"] == "system"


def test_history_resets_after_max_turns(env):
    e, p, *_ = build(env)
    cid = "R1"
    for i in range(13):
        assert e.handle(req(f"m{i}", cid)).conversation_id == cid
    assert len(p.calls[11]["messages"]) == 35  # 12th turn still sees 11 full turns
    assert [m["role"] for m in p.calls[12]["messages"]] == ["user", "system"]
    e.handle(req("m13", cid))
    assert len(p.calls[13]["messages"]) == 5


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
    assert p.calls[2]["messages"][0] == {"role": "user", "content": "again"}
    assert len(p.calls[2]["messages"]) == 2


def test_refusal_line(env):
    e, _, store, *_ = build(env, make_result("", stop_reason="refusal"))
    assert e.handle(req("bad")).speech == REFUSAL
    assert store.recent()[0].outcome == "refusal"


def test_system_is_frozen_base_only(env):
    e, p, *_ = build(env)
    e.handle(req("hi"))
    assert p.calls[0]["system"] == [
        {"type": "text", "text": DESTINY_BASE, "cache_control": {"type": "ephemeral"}}]


def test_context_sent_as_system_message_after_user(env):
    e, p, *_ = build(env)
    e.handle(req("hi"))
    msgs = p.calls[0]["messages"]
    assert msgs[-2] == {"role": "user", "content": "hi"}
    assert msgs[-1]["role"] == "system"
    ctx = msgs[-1]["content"]
    assert "Home weather now: sunny, 69°F, humidity 26%." in ctx
    assert "November 17, 2026" in ctx
    assert "2:30 PM" in ctx  # 22:30 UTC is 14:30 in Los Angeles


def test_history_replays_thinking_block_unchanged(env):
    turn1 = make_result("Blue.")
    turn1.content = [{"type": "thinking", "thinking": "", "signature": "sig"},
                     {"type": "text", "text": "Blue."}]
    e, p, _, _, clock = build(env, turn1, make_result("Red."))
    cid = e.handle(req("favorite color", "C1")).conversation_id
    clock.now += timedelta(minutes=2)
    e.handle(req("another", cid))
    m1, m2 = p.calls[0]["messages"], p.calls[1]["messages"]
    assert m2[2]["content"] == turn1.content
    assert json.dumps(m2[2]["content"]) == json.dumps(turn1.content)
    assert m2[1] == m1[1]
    assert p.calls[0]["system"] == p.calls[1]["system"]


def test_empty_model_text_returns_error_line(env):
    e, p, store, *_ = build(env, make_result("  "), make_result("ok"))
    r = e.handle(req("hello", "E1"))
    assert r.speech == ERROR
    rec = store.recent()[0]
    assert rec.outcome == "error" and rec.route_reason == "default:empty_text"
    e.handle(req("again", "E1"))
    assert [m["role"] for m in p.calls[1]["messages"]] == ["user", "system"]


def test_deadline_passes_timeout_and_skips_spent_tier2(env):
    esc = make_result("", tool_calls=[("needs_deeper_answer", {"reason": "x"})], stop_reason="tool_use")
    e, p, store, _, clock = build(env, esc, make_result("never"))
    orig = p.complete

    def slow(**kw):
        r = orig(**kw)
        clock.now += timedelta(seconds=13)
        return r

    p.complete = slow
    r = e.handle(req("what is a black hole"))
    assert r.speech == ERROR
    assert len(p.calls) == 1 and p.calls[0]["timeout"] == pytest.approx(13.5)
    assert store.recent()[0].outcome == "error"
    assert store.recent()[0].route_reason.endswith(":deadline")


def test_cost_attributed_to_returned_model(env):
    from destiny_brain.costs import cost_usd
    e, p, store, *_ = build(env, make_result("hi", model="claude-sonnet-5-5"))
    e.handle(req("what is two plus two"))
    rec = store.recent()[0]
    assert rec.model == "claude-sonnet-5-5"
    sonnet = env[0].prices["claude-sonnet-5-5"]
    assert rec.cost_usd == pytest.approx(cost_usd(sonnet, Usage(100, 20)))


def test_continue_conversation_on_question(env):
    e, *_ = build(env, make_result("Want more?"), make_result("Done."))
    assert e.handle(req("hi")).continue_conversation is True
    assert e.handle(req("hi")).continue_conversation is False


def test_weather_line_none_on_ha_failure(env):
    e, p, *_ = build(env, ha=FakeHA(weather=None))
    assert e.handle(req("hi")).speech
    assert "weather" not in p.calls[0]["messages"][-1]["content"].lower()


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


# -- handle_stream --

from destiny_brain.fillers import FILLERS, WEB_FILLERS  # noqa: E402

LOST = " Sorry, I lost my train of thought."


class FixedFillers:
    def pick(self, device_id, kind="normal"):
        return WEB_FILLERS[0] if kind == "web" else FILLERS[0]


def sbuild(env, *results, streams=()):
    settings, store = env
    provider = FakeProvider(*results, streams=streams)
    clock = Clock()
    e = Engine(settings, store, provider, FakeHA(), clock=clock, fillers=FixedFillers())
    return e, provider, store, clock


def run(e, r):
    events = list(e.handle_stream(r))
    assert events[-1]["type"] == "end" and all(x["type"] in ("delta", "ping") for x in events[:-1])
    return [x["text"] for x in events[:-1] if x["type"] == "delta"], events[-1]


def test_stream_tier1_single_delta_no_filler(env):
    e, p, *_ = sbuild(env, make_result("It is four."))
    deltas, end = run(e, req("what is two plus two"))
    assert deltas == ["It is four."]
    assert end["speech"] == "It is four." and end["continue_conversation"] is False
    assert p.stream_calls == []


def test_stream_tier2_filler_then_deltas(env):
    res = make_result("Because light scatters.", model="claude-sonnet-5-5")
    e, p, *_ = sbuild(env, streams=[(["Because ", "light scatters."], res)])
    deltas, end = run(e, req("explain the water cycle"))
    assert deltas == [FILLERS[0] + " ", "Because ", "light scatters."]
    assert p.stream_calls[0]["model"] == "claude-sonnet-5-5" and p.stream_calls[0]["tools"] == []
    assert p.calls == []


def test_stream_escalation_filler_then_sonnet(env):
    esc = make_result("", tool_calls=[("needs_deeper_answer", {"reason": "x"})], stop_reason="tool_use")
    res = make_result("Deep answer.", model="claude-sonnet-5-5")
    e, p, store, _ = sbuild(env, esc, streams=[(["Deep answer."], res)])
    deltas, end = run(e, req("what is a black hole"))
    assert deltas == [FILLERS[0] + " ", "Deep answer."]
    assert p.calls[0]["model"] == "claude-haiku-5-5" and p.stream_calls[0]["model"] == "claude-sonnet-5-5"
    assert p.calls[0]["messages"] == p.stream_calls[0]["messages"]
    assert len(store.recent()) == 2


def test_stream_history_excludes_filler(env):
    res = make_result("Because.", model="claude-sonnet-5-5")
    e, p, *_ = sbuild(env, streams=[(["Because."], res),
                                    (["Sure."], make_result("Sure.", model="claude-sonnet-5-5"))])
    _, end = run(e, req("explain the water cycle"))
    run(e, req("and then", end["conversation_id"]))
    msgs = p.stream_calls[1]["messages"]
    assert msgs[2] == {"role": "assistant", "content": res.content}
    assert FILLERS[0] not in json.dumps(msgs)


def test_stream_end_speech_is_full_text(env):
    res = make_result("Want more?", model="claude-sonnet-5-5")
    e, *_ = sbuild(env, streams=[(["Want ", "more?"], res)])
    deltas, end = run(e, req("explain the water cycle"))
    assert end["speech"] == "".join(deltas) == FILLERS[0] + " Want more?"
    assert end["continue_conversation"] is True and len(end["conversation_id"]) == 32


def test_stream_midstream_failure_lost_line_no_history(env):
    e, p, store, _ = sbuild(env, streams=[(["Partial "], ProviderError("connection")),
                                          (["Ok."], make_result("Ok.", model="claude-sonnet-5-5"))])
    deltas, end = run(e, req("explain the water cycle", "c1"))
    assert deltas == [FILLERS[0] + " ", "Partial ", LOST]
    assert end["speech"].endswith(LOST) and end["continue_conversation"] is False
    assert store.recent()[0].outcome == "error"
    run(e, req("explain it again", "c1"))
    assert [m["role"] for m in p.stream_calls[1]["messages"]] == ["user", "system"]


def test_stream_failure_before_first_token_error_line(env):
    e, *_ = sbuild(env, streams=[([], ProviderError("timeout"))])
    deltas, end = run(e, req("explain the water cycle"))
    assert deltas == [FILLERS[0] + " ", ERROR]


def test_stream_refusal_after_filler(env):
    res = make_result("", model="claude-sonnet-5-5", stop_reason="refusal")
    e, p, store, _ = sbuild(env, streams=[([], res)])
    deltas, end = run(e, req("explain the water cycle", "c2"))
    assert deltas == [FILLERS[0] + " ", REFUSAL]
    assert end["continue_conversation"] is False


def test_stream_empty_hard_cap_soft_cap_paths(env):
    e, p, store, clock = sbuild(env)
    deltas, end = run(e, req("   "))
    assert deltas == [EMPTY] and end["speech"] == EMPTY and end["continue_conversation"] is False
    spend(store, 3.0)
    deltas, end = run(e, req("explain the water cycle"))
    assert deltas == [CAPPED] and p.calls == [] and p.stream_calls == []


def test_stream_soft_cap_downgrades_to_tier1_blocking(env):
    e, p, store, _ = sbuild(env, make_result("Short."))
    spend(store, env[0].soft_cap_usd + 0.01)
    deltas, end = run(e, req("explain the water cycle"))
    assert deltas == ["Short."] and p.stream_calls == []


def test_stream_logs_first_token_ms(env):
    res = make_result("Because.", model="claude-sonnet-5-5")
    e, p, store, _ = sbuild(env, streams=[(["Because."], res)])
    run(e, req("explain the water cycle"))
    rec = store.recent()[0]
    assert rec.tier == 2 and rec.outcome == "ok" and rec.first_token_ms is not None and rec.first_token_ms >= 0
    e2, p2, store2, _ = sbuild(env, make_result("Hi."))
    run(e2, req("hello"))
    assert store2.recent()[0].first_token_ms is None


def test_stream_deadline_skips_call(env):
    e, p, store, clock = sbuild(env)
    calls = {"n": 0}

    def late():
        calls["n"] += 1
        return T0 if calls["n"] <= 1 else T0 + timedelta(seconds=14)
    e._clock = late
    deltas, end = run(e, req("explain the water cycle"))
    assert deltas[-1] == ERROR and p.stream_calls == []


def test_stream_generator_close_stops_provider(env):
    res = make_result("One two three.", model="claude-sonnet-5-5")
    e, p, store, _ = sbuild(env, streams=[(["One ", "two ", "three."], res)])
    g = e.handle_stream(req("explain the water cycle"))
    assert next(g)["type"] == "delta"      # filler
    assert next(g)["text"] == "One "
    g.close()
    assert p.stream_closed == [True] and p.stream_yielded == [1]


def test_stream_refusal_after_partial_text_uses_lost_line(env):
    res = make_result("Partial", model="claude-sonnet-5-5", stop_reason="refusal")
    e, p, store, _ = sbuild(env, streams=[(["Partial"], res), (["Ok."], make_result("Ok.", model="claude-sonnet-5-5"))])
    deltas, end = run(e, req("explain the water cycle", "c3"))
    assert deltas == [FILLERS[0] + " ", "Partial", LOST]
    assert end["continue_conversation"] is False
    run(e, req("explain more", "c3"))
    assert [m["role"] for m in p.stream_calls[1]["messages"]] == ["user", "system"]


def test_stream_latency_measures_call_only(env, monkeypatch):
    import itertools
    from destiny_brain import engine as eng
    ticks = itertools.chain([100.0, 110.0, 111.0, 112.0], itertools.repeat(112.0))
    monkeypatch.setattr(eng.time, "monotonic", lambda: next(ticks))
    res = make_result("Because.", model="claude-sonnet-5-5")
    e, p, store, _ = sbuild(env, streams=[(["Because."], res)])
    run(e, req("explain the water cycle"))
    rec = store.recent()[0]
    assert rec.first_token_ms == 11000 and rec.latency_ms == 2000


def test_stream_unexpected_error_is_logged_and_log_failure_is_safe(env):
    e, p, store, _ = sbuild(env)

    def boom(*a, **k):
        raise RuntimeError("x")
    e._resolve = boom
    deltas, end = run(e, req("hello"))
    assert deltas == [ERROR] and end["speech"] == ERROR
    rec = store.recent()[0]
    assert rec.outcome == "error" and rec.route_reason == "unexpected"
    e._log = boom
    deltas, end = run(e, req("hello"))
    assert deltas == [ERROR]


# -- web search --

WEB_LINE = " Let me check the web real quick."
SEARCH_CONTENT = [
    {"type": "server_tool_use", "id": "s1", "name": "web_search", "input": {"query": "nuggets"}},
    {"type": "web_search_tool_result", "tool_use_id": "s1", "content": [{"type": "web_search_result"}]},
    {"type": "text", "text": "Nuggets play at 7."},
]


def test_tier2_calls_get_web_search_blocking(env):
    e, p, *_ = build(env, make_result("Because.", model="claude-sonnet-5-5"))
    e.handle(req("explain the water cycle"))
    assert p.calls[0]["server_tools"] == [WEB_SEARCH_TOOL]


def test_tier1_has_no_server_tools(env):
    e, p, *_ = build(env, make_result("Four."))
    e.handle(req("what is two plus two"))
    assert not p.calls[0]["server_tools"] and p.calls[0]["tools"] == [ESCALATE_TOOL]


def test_tier2_stream_gets_web_search(env):
    e, p, *_ = sbuild(env)
    run(e, req("explain the water cycle"))
    assert p.stream_calls[0]["server_tools"] == [WEB_SEARCH_TOOL]


def test_escalated_call_gets_web_search(env):
    esc = make_result("", tool_calls=[("needs_deeper_answer", {"reason": "x"})], stop_reason="tool_use")
    e, p, *_ = build(env, esc, make_result("Deep.", model="claude-sonnet-5-5"))
    e.handle(req("hmm"))
    assert not p.calls[0]["server_tools"] and p.calls[1]["server_tools"] == [WEB_SEARCH_TOOL]


def test_stream_live_route_uses_web_filler(env):
    res = make_result("Nuggets play at 7.", model="claude-sonnet-5-5")
    e, p, *_ = sbuild(env, streams=[(["Nuggets play at 7."], res)])
    deltas, end = run(e, req("do the nuggets play tonight"))
    assert deltas[0] == WEB_FILLERS[0] + " " and deltas[1:] == ["Nuggets play at 7."]


def test_stream_unplanned_search_line_once(env):
    res = make_result("Answer.", model="claude-sonnet-5-5")
    e, p, store, _ = sbuild(env, streams=[([SEARCH_STARTED, SEARCH_STARTED, "Answer."], res)])
    deltas, end = run(e, req("why is the sky blue"))
    assert deltas == [FILLERS[0] + " ", WEB_LINE, BRIDGES[0], "Answer."]
    assert end["speech"] == FILLERS[0] + " " + WEB_LINE + BRIDGES[0] + "Answer."


def test_stream_web_line_never_enters_history(env):
    res = make_result("Answer.", model="claude-sonnet-5-5")
    e, p, *_ = sbuild(env, streams=[([SEARCH_STARTED, "Answer."], res), (["More."], make_result("More."))])
    run(e, req("why is the sky blue", cid="c"))
    run(e, req("and then", cid="c"))
    assert all(WEB_LINE not in str(m["content"]) for m in p.stream_calls[1]["messages"])


def test_stream_no_search_line_after_text(env):
    res = make_result("Part two.", model="claude-sonnet-5-5")
    e, p, *_ = sbuild(env, streams=[(["Part", SEARCH_STARTED, " two."], res)])
    deltas, _ = run(e, req("why is the sky blue"))
    assert deltas == [FILLERS[0] + " ", "Part", " two."]


def test_stream_live_route_no_extra_line(env):
    res = make_result("Nuggets win.", model="claude-sonnet-5-5")
    e, p, *_ = sbuild(env, streams=[([SEARCH_STARTED, "Nuggets win."], res)])
    deltas, _ = run(e, req("do the nuggets play tonight"))
    assert deltas == [WEB_FILLERS[0] + " ", "Nuggets win."]


def test_search_blocks_kept_in_history(env):
    first = make_result("Nuggets play at 7.", model="claude-sonnet-5-5", content=SEARCH_CONTENT)
    e, p, *_ = build(env, first, make_result("Sure.", model="claude-sonnet-5-5"))
    r = e.handle(req("do the nuggets play tonight", cid="c"))
    assert r.speech == "Nuggets play at 7."
    e.handle(req("and tomorrow", cid="c"))
    assert p.calls[1]["messages"][2] == {"role": "assistant", "content": SEARCH_CONTENT}


def test_followup_after_search_stays_tier2(env):
    first = make_result("Nuggets play at 7.", model="claude-sonnet-5-5", content=SEARCH_CONTENT)
    e, p, store, *_ = build(env, first, make_result("Sure.", model="claude-sonnet-5-5"))
    e.handle(req("do the nuggets play tonight", cid="c"))
    e.handle(req("and tomorrow", cid="c"))
    assert store.recent()[0].route_reason == "sticky"
    assert p.calls[1]["server_tools"] == [WEB_SEARCH_TOOL]


def _paused(text="Part one."):
    content = [{"type": "server_tool_use", "id": "s1", "name": "web_search", "input": {}},
               {"type": "text", "text": text}]
    return make_result(text, model="claude-sonnet-5-5", stop_reason="pause_turn", content=content,
                       usage=Usage(10, 5, web_search_requests=1))


def test_pause_turn_continued_once(env):
    first = _paused()
    second = make_result("Part two.", model="claude-sonnet-5-5", usage=Usage(20, 7, web_search_requests=1))
    e, p, store, *_ = build(env, first, second, make_result("Ok.", model="claude-sonnet-5-5"))
    r = e.handle(req("explain the water cycle", cid="c"))
    assert len(p.calls) == 2
    assert r.speech == "Part one. Part two."  # seam space added across the search block
    assert p.calls[1]["messages"][-1] == {"role": "assistant", "content": first.content}
    assert p.calls[1]["server_tools"] == [WEB_SEARCH_TOOL]
    e.handle(req("and more", cid="c"))
    hist = p.calls[2]["messages"]
    assert hist[2] == {"role": "assistant", "content": first.content + second.content}
    rows = store.recent()
    assert len(rows) == 3 and sorted(x.web_searches for x in rows[1:]) == [1, 1]


def test_stream_pause_turn_continues_and_streams(env):
    first = _paused()
    second = make_result("Part two.", model="claude-sonnet-5-5")
    e, p, *_ = sbuild(env, streams=[(["Part one. "], first), (["Part two."], second)])
    deltas, end = run(e, req("explain the water cycle", cid="c"))
    assert deltas == [FILLERS[0] + " ", "Part one. ", "Part two."]
    assert len(p.stream_calls) == 2
    assert p.stream_calls[1]["messages"][-1] == {"role": "assistant", "content": first.content}
    assert end["speech"].endswith("Part one. Part two.")


def _late_clock(e):
    """Clock that jumps past the deadline once the first model call has started."""
    state = {"on": False}

    def clock():
        return T0 + timedelta(seconds=14) if state["on"] else T0
    orig = e._provider.complete, e._provider.stream

    def complete(**kw):
        r = orig[0](**kw)
        state["on"] = True
        return r

    def stream(**kw):
        gen = orig[1](**kw)
        state["on"] = True
        return gen
    e._provider.complete, e._provider.stream = complete, stream
    e._clock = clock


def test_pause_turn_no_time_left_partial_text(env):
    e, p, store, *_ = build(env, _paused("Part one."))
    _late_clock(e)
    r = e.handle(req("explain the water cycle", cid="c"))
    assert len(p.calls) == 1 and r.speech == "Part one."


def test_pause_turn_no_time_left_no_text(env):
    first = _paused("")
    first.content[:] = first.content[:1]
    e, p, *_ = build(env, first)
    _late_clock(e)
    r = e.handle(req("explain the water cycle", cid="c"))
    assert len(p.calls) == 1 and r.speech == ERROR_LINE


def test_stream_pause_turn_no_time_left(env):
    e, p, *_ = sbuild(env, streams=[(["Part one."], _paused("Part one."))])
    _late_clock(e)
    deltas, end = run(e, req("explain the water cycle", cid="c"))
    assert len(p.stream_calls) == 1 and deltas == [FILLERS[0] + " ", "Part one."]
    assert end["continue_conversation"] is False


def test_logs_web_searches(env):
    res = make_result("Hi.", model="claude-sonnet-5-5", usage=Usage(0, 0, web_search_requests=2))
    e, p, store, *_ = build(env, res)
    e.handle(req("explain the water cycle"))
    rec = store.recent()[0]
    assert rec.web_searches == 2 and rec.cost_usd == pytest.approx(0.02)
    e.handle(req("hello", cid="z"))
    assert store.recent()[0].web_searches is None


def test_soft_cap_live_downgrades(env):
    e, p, store, *_ = build(env, make_result("Maybe."))
    spend(env[1], env[0].soft_cap_usd)
    e.handle(req("do the nuggets play tonight"))
    assert store.recent()[0].route_reason == "soft_cap" and store.recent()[0].tier == 1
    assert not p.calls[0]["server_tools"]


# -- review fixes --


def test_merge_seam_rules():
    from destiny_brain.engine import Engine
    m = lambda a, b: Engine._merge(make_result(a), make_result(b)).text  # noqa: E731
    assert m("One.", "Two.") == "One. Two."
    assert m("One. ", "Two.") == "One. Two."
    assert m("One.", " Two.") == "One. Two."
    assert m("", "Two.") == "Two."
    assert m("One.", "") == "One."


def test_stream_pause_turn_seam_space(env):
    first = _paused("Part one.")
    second = make_result("Part two.", model="claude-sonnet-5-5")
    e, p, *_ = sbuild(env, streams=[(["Part one."], first), (["Part two."], second)])
    deltas, end = run(e, req("explain the water cycle", cid="c"))
    assert deltas == [FILLERS[0] + " ", "Part one.", " ", "Part two."]
    assert end["speech"].endswith("Part one. Part two.")


def test_stream_bridges_non_live(env):
    res = make_result("Answer.", model="claude-sonnet-5-5")
    e, p, *_ = sbuild(env, streams=[([SEARCH_STARTED] * 4 + ["Answer."], res)])
    deltas, end = run(e, req("why is the sky blue"))
    assert deltas == [FILLERS[0] + " ", WEB_LINE, BRIDGES[0], BRIDGES[1], "Answer."]
    assert end["speech"] == FILLERS[0] + " " + WEB_LINE + BRIDGES[0] + BRIDGES[1] + "Answer."


def test_stream_bridges_live_route_from_second_search(env):
    res = make_result("Nuggets win.", model="claude-sonnet-5-5")
    e, p, *_ = sbuild(env, streams=[([SEARCH_STARTED, SEARCH_STARTED, SEARCH_STARTED, "Nuggets win."], res)])
    deltas, _ = run(e, req("do the nuggets play tonight"))
    assert deltas == [WEB_FILLERS[0] + " ", BRIDGES[0], BRIDGES[1], "Nuggets win."]


def test_stream_no_bridge_after_model_text(env):
    res = make_result("A B.", model="claude-sonnet-5-5")
    e, p, *_ = sbuild(env, streams=[(["A", SEARCH_STARTED, SEARCH_STARTED, " B."], res)])
    deltas, _ = run(e, req("why is the sky blue"))
    assert deltas == [FILLERS[0] + " ", "A", " B."]


def test_stream_bridges_not_in_history(env):
    res = make_result("Answer.", model="claude-sonnet-5-5")
    e, p, *_ = sbuild(env, streams=[([SEARCH_STARTED, SEARCH_STARTED, "Answer."], res), (["More."], make_result("More."))])
    run(e, req("why is the sky blue", cid="c"))
    run(e, req("and then", cid="c"))
    assert all(BRIDGES[0] not in str(m["content"]) for m in p.stream_calls[1]["messages"])


def test_stream_heartbeats_become_pings(env):
    res = make_result("Hi.", model="claude-sonnet-5-5")
    e, p, store, _ = sbuild(env, streams=[([HEARTBEAT, SEARCH_STARTED, HEARTBEAT, "Hi.", HEARTBEAT], res)])
    events = list(e.handle_stream(req("do the nuggets play tonight")))
    assert [x["type"] for x in events] == ["delta", "ping", "ping", "delta", "ping", "end"]
    assert events[-1]["speech"] == WEB_FILLERS[0] + " " + "Hi."
    assert events[-1]["type"] == "end"


def test_heartbeat_is_not_first_token(env):
    res = make_result("", model="claude-sonnet-5-5")
    e, p, store, _ = sbuild(env, streams=[([HEARTBEAT], res)])
    run(e, req("explain the water cycle"))
    assert store.recent()[0].first_token_ms is None


def test_soft_cap_keeps_tier2_when_history_has_search_blocks(env):
    first = make_result("Nuggets play at 7.", model="claude-sonnet-5-5", content=SEARCH_CONTENT)
    e, p, store, ha, _ = build(env, first, make_result("Sure.", model="claude-sonnet-5-5"))
    e.handle(req("do the nuggets play tonight", cid="c"))
    spend(store, env[0].soft_cap_usd + 0.01)
    e.handle(req("and tomorrow", cid="c"))
    assert p.calls[1]["server_tools"] == [WEB_SEARCH_TOOL]
    assert store.recent()[0].tier == 2 and store.recent()[0].route_reason == "sticky"
    assert ha.notifications == []


def test_hard_cap_still_applies_with_search_history(env):
    first = make_result("Nuggets play at 7.", model="claude-sonnet-5-5", content=SEARCH_CONTENT)
    e, p, store, *_ = build(env, first)
    e.handle(req("do the nuggets play tonight", cid="c"))
    spend(store, env[0].hard_cap_usd + 0.01)
    assert e.handle(req("and tomorrow", cid="c")).speech == CAPPED


def test_soft_cap_still_downgrades_without_search_blocks(env):
    e, p, store, ha, _ = build(env, make_result("Because.", model="claude-sonnet-5-5"), make_result("Ok."))
    e.handle(req("explain the water cycle", cid="c"))
    spend(store, env[0].soft_cap_usd + 0.01)
    e.handle(req("and more", cid="c"))
    assert store.recent()[0].tier == 1 and store.recent()[0].route_reason == "soft_cap"
