from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from .config import Settings
from .fillers import FillerPicker
from .costs import Usage, cost_usd
from .prompts import DESTINY_BASE, ESCALATE_TOOL, WEB_SEARCH_TOOL, context_block
from .providers.base import HEARTBEAT, SEARCH_STARTED, ProviderResult
from .router import clean_text, route
from .store import RequestRecord

log = logging.getLogger(__name__)

EMPTY_LINE = "I didn't catch that. Could you say it again?"
CAPPED_LINE = "I've done a lot of thinking today. Let's talk again tomorrow."
ERROR_LINE = "Sorry, something went wrong in my head. Please try again."
REFUSAL_LINE = "I can't help with that one. Let's ask a grown-up."
LOST_LINE = " Sorry, I lost my train of thought."
WEB_LINE = " Let me check the web real quick."
# Spoken on the 2nd and 3rd search of one answer (before any model text) so the line never goes silent.
BRIDGES = (" Still digging, almost there.", " Just a little longer, I'm nearly there.")

MAX_TURNS = 12  # complete [user, system, assistant] turns kept before a fresh start
MAX_CONVERSATION_ID = 128
TOTAL_BUDGET_S = 13.5
MIN_CALL_S = 1.0
HISTORY_TTL = timedelta(minutes=10)


@dataclass
class ConverseRequest:
    text: str
    conversation_id: str | None
    device_id: str | None
    satellite_id: str | None
    language: str = "en"


@dataclass
class ConverseResponse:
    speech: str
    conversation_id: str
    continue_conversation: bool


class _DeadlineExceeded(Exception):
    pass


@dataclass
class _Plan:
    cid: str
    req: ConverseRequest
    chars: int
    tier: int
    reason: str
    messages: list[dict]
    system: list[dict]
    now: datetime
    mono0: float


@dataclass
class _StreamState:
    cid: str
    cont: bool = False
    model_text: bool = False
    web_line: bool = False
    searches: int = 0
    bridges: int = 0
    last_text: str = ""
    seam_pending: bool = False
    spoken: list[str] = field(default_factory=list)


@dataclass
class _Conversation:
    history: list[dict]
    last_ts: datetime
    tier: int | None = None


class Engine:
    def __init__(self, settings: Settings, store, provider, ha, clock=lambda: datetime.now(UTC),
                 fillers=None):
        self._s = settings
        self._store = store
        self._provider = provider
        self._ha = ha
        self._clock = clock
        self._fillers = fillers or FillerPicker()
        self._tz = ZoneInfo(settings.tz)
        self._lock = threading.Lock()
        self._convs: dict[str, _Conversation] = {}

    # -- public --

    def handle(self, req: ConverseRequest) -> ConverseResponse:
        cid = req.conversation_id or ""
        try:
            return self._handle(req)
        except Exception:
            log.exception("engine failure")
            try:
                return self._respond(ERROR_LINE, cid or uuid.uuid4().hex, req, 0, None, "unexpected", "error", 0)
            except Exception:
                return ConverseResponse(ERROR_LINE, cid or uuid.uuid4().hex, False)

    def handle_stream(self, req: ConverseRequest) -> Iterator[dict]:
        """NDJSON event dicts: `delta` and `ping` events, then exactly one `end`. Never raises."""
        st = _StreamState(req.conversation_id or "")
        inner = self._stream(req, st)
        try:
            for text in inner:
                if text is HEARTBEAT:
                    yield {"type": "ping"}
                    continue
                st.spoken.append(text)
                yield {"type": "delta", "text": text}
        except Exception:
            log.exception("engine stream failure")
            st.cont = False
            st.cid = st.cid or uuid.uuid4().hex
            try:
                self._log(st.cid, req, 0, None, "unexpected", Usage(0, 0), 0, "error", 0)
            except Exception:
                log.exception("error logging failed")
            line = LOST_LINE if st.model_text else ERROR_LINE
            st.spoken.append(line)
            yield {"type": "delta", "text": line}
        finally:
            inner.close()
        yield {"type": "end", "speech": "".join(st.spoken), "conversation_id": st.cid or uuid.uuid4().hex,
               "continue_conversation": st.cont}

    # -- internals --

    def _plan(self, req: ConverseRequest) -> _Plan | ConverseResponse:
        """Shared first steps: resolve conversation, caps, routing, request build. Early-outs are final."""
        text = clean_text(req.text or "")
        now = self._clock()
        cid, history, previous_tier = self._resolve(req.conversation_id, now)
        if not text:
            return self._respond(EMPTY_LINE, cid, req, 0, None, "empty", "empty", 0)
        if self._store.spend_today(now) >= self._s.hard_cap_usd:
            return self._respond(CAPPED_LINE, cid, req, 0, None, "hard_cap", "capped", len(text))

        decision = route(text, previous_tier)
        tier, reason = decision.tier, decision.reason
        if (tier == 2 and self._store.spend_today(now) >= self._s.soft_cap_usd
                and not self._has_server_blocks(history)):
            # (a history with server-tool blocks must stay on tier 2: Haiku has no web search tool)
            tier, reason = 1, "soft_cap"
            self._notify_soft_cap(now)

        # Volatile context is an append-only mid-conversation system message after the user turn,
        # so the top-level system and all earlier messages stay byte-identical (thinking replay).
        messages = history + [{"role": "user", "content": text},
                              {"role": "system", "content": self._context(now)}]
        system = [{"type": "text", "text": DESTINY_BASE, "cache_control": {"type": "ephemeral"}}]
        return _Plan(cid, req, len(text), tier, reason, messages, system, now, time.monotonic())

    @staticmethod
    def _has_server_blocks(history: list[dict]) -> bool:
        return any(
            isinstance(b, dict) and b.get("type") in ("server_tool_use", "web_search_tool_result")
            for m in history if m.get("role") == "assistant" and isinstance(m.get("content"), list)
            for b in m["content"]
        )

    def _handle(self, req: ConverseRequest) -> ConverseResponse:
        plan = self._plan(req)
        if isinstance(plan, ConverseResponse):
            return plan
        tier, reason = plan.tier, plan.reason
        result: ProviderResult | None = None
        try:
            if tier == 1:
                result = self._tier1(plan)
                if self._escalated(result):
                    tier, reason, result = 2, "escalated", None
            if result is None:
                result = self._call_paused(plan, tier, reason)
        except Exception as exc:
            return self._fail(exc, plan, tier, reason)
        return self._finish(plan, tier, reason, result)

    def _call_paused(self, plan: _Plan, tier: int, reason: str) -> ProviderResult:
        """Tier-2 call; a pause_turn is continued once (if time allows) and merged into one result."""
        first = self._call(tier, reason, plan.system, plan.messages, [], plan.cid, plan.req, plan.chars, plan.now)
        if first.stop_reason != "pause_turn":
            return first
        try:
            second = self._call(tier, reason, plan.system, self._continuation(plan, first), [], plan.cid,
                                plan.req, plan.chars, plan.now)
        except _DeadlineExceeded:
            log.warning("pause_turn not continued: deadline")
            return first
        return self._merge(first, second)

    @staticmethod
    def _continuation(plan: _Plan, first: ProviderResult) -> list[dict]:
        return plan.messages + [{"role": "assistant", "content": first.content}]

    @staticmethod
    def _merge(first: ProviderResult, second: ProviderResult) -> ProviderResult:
        a, b = first.usage, second.usage
        usage = Usage(a.input_tokens + b.input_tokens, a.output_tokens + b.output_tokens,
                      a.cache_read_tokens + b.cache_read_tokens, a.cache_write_tokens + b.cache_write_tokens,
                      a.web_search_requests + b.web_search_requests)
        a_txt, b_txt = first.text, second.text
        seam = " " if a_txt and b_txt and not a_txt[-1].isspace() and not b_txt[0].isspace() else ""
        return replace(second, text=a_txt + seam + b_txt, content=first.content + second.content,
                       usage=usage, tool_calls=first.tool_calls + second.tool_calls)

    @staticmethod
    def _escalated(result: ProviderResult) -> bool:
        return any(name == ESCALATE_TOOL.name for name, _ in result.tool_calls)

    def _tier1(self, plan: _Plan) -> ProviderResult:
        return self._call(1, plan.reason, plan.system, plan.messages, [ESCALATE_TOOL], plan.cid, plan.req,
                          plan.chars, plan.now)

    def _fail(self, exc: Exception, plan: _Plan, tier: int, reason: str) -> ConverseResponse:
        if isinstance(exc, _DeadlineExceeded):
            log.warning("model call skipped: deadline")
            reason += ":deadline"
        else:
            detail = str(exc.__cause__ or exc)[:500]
            log.warning("model call failed: %s: %s", getattr(exc, "kind", type(exc).__name__), detail)
        return self._respond(ERROR_LINE, plan.cid, plan.req, tier, self._model(tier), reason, "error", plan.chars)

    def _finish(self, plan: _Plan, tier: int, reason: str, result: ProviderResult) -> ConverseResponse:
        cid, req, chars = plan.cid, plan.req, plan.chars
        if result.stop_reason == "refusal":
            return self._respond(REFUSAL_LINE, cid, req, tier, result.model, reason, "refusal", chars, log_it=False)
        if result.stop_reason == "pause_turn":  # could not be continued: speak what we have, store nothing
            if result.text.strip():
                return ConverseResponse(result.text, cid, False)
            return self._respond(ERROR_LINE, cid, req, tier, result.model, reason + ":paused", "error", chars)
        if not result.text.strip():
            return self._respond(ERROR_LINE, cid, req, tier, result.model, reason + ":empty_text", "error", chars)
        with self._lock:
            conv = self._convs.get(cid)
            if conv is not None:
                conv.history = plan.messages + [{"role": "assistant", "content": result.content}]
                conv.last_ts = self._clock()
                conv.tier = tier
        speech = result.text
        return ConverseResponse(speech, cid, speech.rstrip().endswith("?"))

    def _stream(self, req: ConverseRequest, st: _StreamState) -> Iterator[str]:
        """Yields spoken text pieces; sets st.cid / st.cont / st.model_text."""
        plan = self._plan(req)
        if isinstance(plan, ConverseResponse):
            st.cid = plan.conversation_id
            yield plan.speech
            return
        st.cid = plan.cid
        tier, reason = plan.tier, plan.reason
        if tier == 1:
            try:
                result = self._tier1(plan)
            except Exception as exc:
                yield self._fail(exc, plan, 1, reason).speech
                return
            if not self._escalated(result):
                resp = self._finish(plan, 1, reason, result)
                st.cont = resp.continue_conversation
                yield resp.speech
                return
            tier, reason = 2, "escalated"
        yield self._fillers.pick(req.device_id, "web" if reason == "live" else "normal") + " "
        try:
            result = yield from self._stream_paused(plan, tier, reason, st)
        except Exception as exc:
            resp = self._fail(exc, plan, tier, reason)
            yield LOST_LINE if st.model_text else resp.speech
            return
        resp = self._finish(plan, tier, reason, result)
        st.cont = resp.continue_conversation
        if st.model_text and resp.speech != result.text:
            st.cont = False  # refusal/empty after partial speech: nothing was committed to history
            yield LOST_LINE
        elif not st.model_text:
            yield resp.speech

    def _stream_paused(self, plan: _Plan, tier: int, reason: str, st: _StreamState) -> Iterator[str]:
        """Streamed tier-2 call; a pause_turn is continued once (streaming too) and merged."""
        first = yield from self._stream_call(plan, tier, reason, st, plan.messages)
        if first.stop_reason != "pause_turn":
            return first
        st.seam_pending = bool(st.last_text) and not st.last_text[-1].isspace()
        try:
            second = yield from self._stream_call(plan, tier, reason, st, self._continuation(plan, first))
        except _DeadlineExceeded:
            log.warning("pause_turn not continued: deadline")
            return first
        return self._merge(first, second)

    def _stream_call(self, plan: _Plan, tier: int, reason: str, st: _StreamState,
                     messages: list[dict]) -> Iterator[str]:
        """One streamed model call (server tools on tier 2), logged. Returns the ProviderResult."""
        model = self._model(tier)
        effort = self._s.tier1_effort if tier == 1 else self._s.tier2_effort
        remaining = TOTAL_BUDGET_S - (self._clock() - plan.now).total_seconds()  # deadline: first token
        if remaining < MIN_CALL_S:
            raise _DeadlineExceeded()
        call_start = time.monotonic()
        gen = self._provider.stream(
            model=model, system=plan.system, messages=messages, tools=[], effort=effort, max_tokens=1024,
            timeout=max(MIN_CALL_S, remaining), server_tools=[WEB_SEARCH_TOOL] if tier == 2 else None,
        )
        first_ms = None
        result: ProviderResult | None = None
        try:
            while True:
                try:
                    delta = next(gen)
                except StopIteration as stop:
                    result = stop.value
                    break
                if delta is HEARTBEAT:
                    yield HEARTBEAT
                    continue
                if delta is SEARCH_STARTED:
                    st.searches += 1
                    if st.model_text:
                        pass
                    elif st.searches == 1 and reason != "live" and not st.web_line:
                        st.web_line = True
                        yield WEB_LINE  # spoken, but not model text and never stored in history
                    elif st.searches >= 2 and st.bridges < len(BRIDGES):
                        st.bridges += 1
                        yield BRIDGES[st.bridges - 1]  # keeps the connector's idle timer alive
                    continue
                if not delta:
                    continue
                if st.seam_pending:
                    st.seam_pending = False
                    if not delta[0].isspace():
                        yield " "  # pause_turn continuation starts a new text block
                if first_ms is None:
                    first_ms = int((time.monotonic() - plan.mono0) * 1000)
                st.model_text = True
                st.last_text = delta
                yield delta
        finally:
            gen.close()  # stops provider billing if we were closed early
        latency = int((time.monotonic() - call_start) * 1000)
        outcome = "refusal" if result.stop_reason == "refusal" else "ok"
        self._log(plan.cid, plan.req, tier, result.model or model, reason, result.usage, latency, outcome,
                  plan.chars, requested=model, first_token_ms=first_ms)
        return result

    def _model(self, tier: int) -> str:
        return self._s.tier1_model if tier == 1 else self._s.tier2_model

    def _call(self, tier, reason, system, messages, tools, cid, req, chars, started) -> ProviderResult:
        """One model call, logged. A tier-1 call that escalates is logged with reason 'escalated'."""
        model = self._model(tier)
        effort = self._s.tier1_effort if tier == 1 else self._s.tier2_effort
        remaining = TOTAL_BUDGET_S - (self._clock() - started).total_seconds()
        if remaining < MIN_CALL_S:
            raise _DeadlineExceeded()
        start = time.monotonic()
        result = self._provider.complete(
            model=model, system=system, messages=messages, tools=tools, effort=effort, max_tokens=1024,
            timeout=max(MIN_CALL_S, remaining), server_tools=[WEB_SEARCH_TOOL] if tier == 2 else None,
        )
        latency = int((time.monotonic() - start) * 1000)
        escalated = self._escalated(result)
        outcome = "refusal" if result.stop_reason == "refusal" else "ok"
        self._log(cid, req, tier, result.model or model, "escalated" if escalated else reason, result.usage, latency,
                  outcome, chars, requested=model)
        return result

    def _log(self, cid, req, tier, model, reason, usage: Usage, latency, outcome, chars, requested=None,
             first_token_ms=None) -> None:
        price = self._price(model, requested)
        cost = cost_usd(price, usage) if price else 0.0
        self._store.log(RequestRecord(
            ts_utc=self._clock(), conversation_id=cid, device_id=req.device_id, tier=tier, model=model,
            route_reason=reason, usage=usage, cost_usd=cost, latency_ms=latency, outcome=outcome,
            text_chars=chars, first_token_ms=first_token_ms,
            web_searches=usage.web_search_requests or None,
        ))

    def _price(self, model, requested):
        if not model:
            return None
        return self._s.prices.get(model, self._s.prices.get(requested) if requested else None)

    def _respond(self, speech, cid, req, tier, model, reason, outcome, chars, log_it=True) -> ConverseResponse:
        if log_it:
            self._log(cid, req, tier, model, reason, Usage(0, 0), 0, outcome, chars)
        return ConverseResponse(speech, cid, False)

    def _resolve(self, conversation_id, now) -> tuple[str, list[dict], int | None]:
        with self._lock:
            for k in [k for k, c in self._convs.items() if now - c.last_ts > HISTORY_TTL]:
                del self._convs[k]
            if not (isinstance(conversation_id, str) and 0 < len(conversation_id) <= MAX_CONVERSATION_ID):
                conversation_id = uuid.uuid4().hex
            conv = self._convs.get(conversation_id)
            if conv is not None and len(conv.history) >= MAX_TURNS * 3:
                conv.history = []  # never slice: history is append-only, so start fresh at the cap
            if conv is None:
                conv = self._convs[conversation_id] = _Conversation([], now)
            return conversation_id, list(conv.history), conv.tier

    def _context(self, now: datetime) -> str:
        try:
            weather = self._ha.weather_line(self._s.ha_weather_entity)
        except Exception:
            weather = None
        try:
            forecast = self._ha.forecast_line(self._s.ha_weather_entity)
        except Exception:
            forecast = None
        return context_block(now.astimezone(self._tz), weather, forecast)

    def _notify_soft_cap(self, now: datetime) -> None:
        day = now.astimezone(self._tz).date()
        with self._lock:
            if not self._s.notify_service or self._store.soft_cap_notified(day):
                return
            self._store.mark_soft_cap_notified(day)
        self._ha.notify(
            self._s.notify_service,
            "Destiny",
            f"Destiny reached today's soft spending cap (${self._s.soft_cap_usd:.2f}). "
            "Long answers use the faster model until tomorrow.",
        )
