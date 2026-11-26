from types import SimpleNamespace as NS

import anthropic
import httpx
import pytest

from destiny_brain.costs import Usage
from destiny_brain.providers.anthropic_provider import AnthropicProvider
from destiny_brain.prompts import WEB_SEARCH_TOOL
from destiny_brain.providers.base import SEARCH_STARTED, ProviderError, ToolSpec


def make_response(blocks=None, usage=None, stop="end_turn", model="m"):
    class Block:
        def __init__(self, d):
            self.d = d
            self.type = d["type"]
            for k, v in d.items():
                setattr(self, k, v)

        def model_dump(self):
            return dict(self.d)

    blocks = blocks if blocks is not None else [{"type": "text", "text": "Hi there."}]
    usage = usage or NS(
        input_tokens=10,
        output_tokens=5,
        cache_read_input_tokens=None,
        cache_creation_input_tokens=None,
    )
    return NS(content=[Block(b) for b in blocks], usage=usage, stop_reason=stop, model=model)


class FakeClient:
    def __init__(self, response=None, exc=None):
        self.calls = []
        self.response = response or make_response()
        self.exc = exc
        outer = self

        class Msgs:
            def __init__(self, kind):
                self.kind = kind

            def create(self, **kw):
                outer.calls.append((self.kind, kw))
                if outer.exc:
                    raise outer.exc
                return outer.response

        self.messages = Msgs("plain")
        self.beta = NS(messages=Msgs("beta"))


SYSTEM = [{"type": "text", "text": "sys"}]
MSGS = [{"role": "user", "content": "hello"}]


def run(client, model="claude-haiku-5-5", tools=(), effort="low"):
    return AnthropicProvider(client).complete(
        model=model, system=SYSTEM, messages=MSGS, tools=list(tools), effort=effort
    )


THINKING = {"type": "adaptive", "block_binding": {"prefix_mismatch_behavior": "drop_block"}}


def test_haiku_uses_beta_create():
    c = FakeClient()
    run(c)
    kind, kw = c.calls[0]
    assert kind == "beta"
    assert kw["model"] == "claude-haiku-5-5"
    assert kw["output_config"] == {"effort": "low"}
    assert kw["max_tokens"] == 1024
    assert kw["thinking"] == THINKING
    assert kw["betas"] == ["thinking-binding-controls-2026-08-01"]
    assert "fallbacks" not in kw
    assert kw["system"] == SYSTEM and kw["messages"] == MSGS


def test_sonnet_uses_beta_fallbacks():
    c = FakeClient()
    run(c, model="claude-sonnet-5-5", effort="medium")
    kind, kw = c.calls[0]
    assert kind == "beta"
    assert kw["betas"] == [
        "thinking-binding-controls-2026-08-01",
        "server-side-fallback-2026-07-01",
    ]
    assert kw["fallbacks"] == "default"
    assert kw["output_config"] == {"effort": "medium"}
    assert kw["thinking"] == THINKING


def test_haiku_and_sonnet_send_drop_block_binding():
    for model in ("claude-haiku-5-5", "claude-sonnet-5-5"):
        c = FakeClient()
        run(c, model=model)
        kind, kw = c.calls[0]
        assert kind == "beta"
        assert kw["thinking"]["block_binding"] == {"prefix_mismatch_behavior": "drop_block"}
        assert kw["thinking"]["type"] == "adaptive"
        assert "budget_tokens" not in kw["thinking"]
        assert "thinking-binding-controls-2026-08-01" in kw["betas"]


def test_tools_auto():
    c = FakeClient()
    run(c, tools=[ToolSpec("t", "d", {"type": "object"})])
    kw = c.calls[0][1]
    assert kw["tool_choice"] == {"type": "auto"}
    assert kw["tools"] == [{"name": "t", "description": "d", "input_schema": {"type": "object"}}]


def test_no_tools_omits_tool_keys():
    c = FakeClient()
    run(c)
    kw = c.calls[0][1]
    assert "tools" not in kw and "tool_choice" not in kw


def test_usage_mapping():
    u = NS(input_tokens=10, output_tokens=5, cache_read_input_tokens=3, cache_creation_input_tokens=2)
    r = run(FakeClient(make_response(usage=u)))
    assert r.usage == Usage(10, 5, 3, 2)
    r = run(FakeClient(make_response()))
    assert r.usage == Usage(10, 5, 0, 0)


def test_text_content_and_stop_reason():
    blocks = [{"type": "text", "text": "A."}, {"type": "text", "text": "B."}]
    r = run(FakeClient(make_response(blocks, stop="refusal", model="x")))
    assert r.text == "A.B."
    assert r.content == blocks
    assert r.stop_reason == "refusal"
    assert r.model == "x"


def test_tool_calls_parsed():
    blocks = [
        {"type": "text", "text": "Let me think."},
        {"type": "tool_use", "id": "t1", "name": "needs_deeper_answer", "input": {"why": "hard"}},
    ]
    r = run(FakeClient(make_response(blocks, stop="tool_use")))
    assert r.tool_calls == [("needs_deeper_answer", {"why": "hard"})]
    assert r.content == blocks


_req = httpx.Request("POST", "https://x")


def _status(cls, code):
    return cls("e", response=httpx.Response(code, request=_req), body=None)


@pytest.mark.parametrize(
    "exc,kind",
    [
        (_status(anthropic.RateLimitError, 429), "rate_limit"),
        (_status(anthropic.InternalServerError, 500), "server"),
        (_status(anthropic.BadRequestError, 400), "bad_request"),
        (anthropic.APITimeoutError(request=_req), "timeout"),
        (anthropic.APIConnectionError(request=_req), "connection"),
    ],
)
def test_errors_map(exc, kind):
    with pytest.raises(ProviderError) as ei:
        run(FakeClient(exc=exc))
    assert ei.value.kind == kind


def test_rate_limit_maps_to_provider_error():
    with pytest.raises(ProviderError) as ei:
        run(FakeClient(exc=_status(anthropic.RateLimitError, 429)))
    assert ei.value.kind == "rate_limit"


def test_other_status_error_is_server():
    with pytest.raises(ProviderError) as ei:
        run(FakeClient(exc=_status(anthropic.APIStatusError, 418)))
    assert ei.value.kind == "server"


def test_timeout_passed_via_with_options():
    client = FakeClient()
    seen = []

    def with_options(**kw):
        seen.append(kw)
        return client

    client.with_options = with_options
    AnthropicProvider(client).complete(
        model="claude-haiku-5-5", system=SYSTEM, messages=MSGS, tools=[], effort="low", timeout=4.5)
    assert seen == [{"timeout": 4.5}]
    assert len(client.calls) == 1


def test_no_timeout_does_not_call_with_options():
    client = FakeClient()

    def boom(**kw):
        raise AssertionError("unexpected")

    client.with_options = boom
    run(client)


def test_build_client_no_retries():
    from destiny_brain.providers.anthropic_provider import build_client
    c = build_client("k")
    assert c.max_retries == 0 and c.timeout == 6.0


# ---- streaming ----


SERVER_BLOCK_START = NS(type="content_block_start", content_block=NS(type="server_tool_use"))
TEXT_BLOCK_START = NS(type="content_block_start", content_block=NS(type="text"))


def text_event(t):
    return NS(type="content_block_delta", delta=NS(type="text_delta", text=t))


class FakeStream:
    """Iterates raw SDK-shaped events; plain strings become text_delta events."""

    def __init__(self, deltas, final, exc=None):
        self._events = self._gen(deltas, exc)
        self._final = final
        self.closed = False

    def _gen(self, deltas, exc):
        for d in deltas:
            yield text_event(d) if isinstance(d, str) else d
        if exc:
            raise exc

    def __iter__(self):
        return self._events

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.closed = True

    def get_final_message(self):
        return self._final


class FakeStreamClient:
    def __init__(self, deltas, final=None, exc=None):
        self.calls = []
        self.last = None
        outer = self

        class Msgs:
            def stream(self, **kw):
                outer.calls.append(kw)
                outer.last = FakeStream(deltas, final or make_response(), exc)
                return outer.last

        self.beta = NS(messages=Msgs())


def run_stream(client, model="claude-haiku-5-5", tools=()):
    return AnthropicProvider(client).stream(
        model=model, system=SYSTEM, messages=MSGS, tools=list(tools), effort="low"
    )


def drain(gen):
    out = []
    while True:
        try:
            out.append(next(gen))
        except StopIteration as stop:
            return out, stop.value


def test_stream_kwargs_match_complete_per_model():
    tool = ToolSpec("t", "d", {"type": "object"})
    for model in ("claude-haiku-5-5", "claude-sonnet-5-5"):
        c = FakeClient()
        run(c, model=model, tools=[tool])
        sc = FakeStreamClient(["a"])
        drain(run_stream(sc, model=model, tools=[tool]))
        assert sc.calls[0] == c.calls[0][1]
    assert sc.calls[0]["fallbacks"] == "default"


def test_stream_yields_deltas_and_returns_result():
    final = make_response(
        blocks=[{"type": "text", "text": "Hi there."}],
        usage=NS(
            input_tokens=7,
            output_tokens=3,
            cache_read_input_tokens=2,
            cache_creation_input_tokens=1,
        ),
        stop="end_turn",
        model="mm",
    )
    deltas, res = drain(run_stream(FakeStreamClient(["Hi ", "there."], final)))
    assert deltas == ["Hi ", "there."]
    assert res.content == [{"type": "text", "text": "Hi there."}]
    assert res.text == "Hi there."
    assert res.usage == Usage(7, 3, 2, 1)
    assert res.model == "mm" and res.stop_reason == "end_turn"


def test_stream_error_mid_stream_maps():
    exc = anthropic.APIConnectionError(request=httpx.Request("POST", "http://x"))
    gen = run_stream(FakeStreamClient(["a"], exc=exc))
    assert next(gen) == "a"
    with pytest.raises(ProviderError) as ei:
        next(gen)
    assert ei.value.kind == "connection"


def test_stream_close_exits_context():
    sc = FakeStreamClient(["a", "b", "c"])
    gen = run_stream(sc)
    assert next(gen) == "a"
    gen.close()
    assert sc.last.closed


# ---- server tools / search signal ----


def test_server_tools_passed_through_sonnet():
    c = FakeClient()
    AnthropicProvider(c).complete(model="claude-sonnet-5-5", system=SYSTEM, messages=MSGS,
                                  tools=[], effort="low", server_tools=[WEB_SEARCH_TOOL])
    kw = c.calls[0][1]
    assert kw["tools"] == [WEB_SEARCH_TOOL]
    assert "tool_choice" not in kw
    assert kw["betas"] == ["thinking-binding-controls-2026-08-01", "server-side-fallback-2026-07-01"]
    assert kw["fallbacks"] == "default"


def test_custom_plus_server_tools():
    tool = ToolSpec("t", "d", {"type": "object"})
    c = FakeClient()
    AnthropicProvider(c).complete(model="claude-sonnet-5-5", system=SYSTEM, messages=MSGS,
                                  tools=[tool], effort="low", server_tools=[WEB_SEARCH_TOOL])
    kw = c.calls[0][1]
    assert [t["name"] for t in kw["tools"]] == ["t", "web_search"]
    assert kw["tools"][1] == WEB_SEARCH_TOOL
    assert kw["tool_choice"] == {"type": "auto"}


def test_stream_yields_search_started():
    sc = FakeStreamClient([SERVER_BLOCK_START, TEXT_BLOCK_START, "Tonight", " at 7."])
    gen = AnthropicProvider(sc).stream(model="claude-sonnet-5-5", system=SYSTEM, messages=MSGS,
                                       tools=[], effort="low", server_tools=[WEB_SEARCH_TOOL])
    deltas, _ = drain(gen)
    assert deltas == [SEARCH_STARTED, "Tonight", " at 7."]
    assert sc.calls[0]["tools"] == [WEB_SEARCH_TOOL]


def test_text_join_no_spaces():
    usage = NS(input_tokens=10, output_tokens=5, cache_read_input_tokens=None,
               cache_creation_input_tokens=None, server_tool_use=NS(web_search_requests=1))
    resp = make_response(blocks=[{"type": "text", "text": "The Nuggets play"},
                                 {"type": "text", "text": " at 7 PM."}], usage=usage)
    res = run(FakeClient(response=resp))
    assert res.text == "The Nuggets play at 7 PM."
    assert res.usage.web_search_requests == 1


def test_missing_server_tool_use_is_zero_searches():
    assert run(FakeClient()).usage.web_search_requests == 0
    usage = NS(input_tokens=1, output_tokens=1, server_tool_use=None)
    assert run(FakeClient(response=make_response(usage=usage))).usage.web_search_requests == 0
