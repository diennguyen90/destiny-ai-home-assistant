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
from .costs import Usage, cost_usd
from .fillers import FillerPicker
from .household import HOUSEHOLD_TOOLS, Household
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

MAX_TURNS = 12  # complete [user, system, assistant] turns kept before a fresh start
MAX_CONVERSATION_ID = 128
TOTAL_BUDGET_S = 13.5
MIN_CALL_S = 1.0
HISTORY_TTL = timedelta(minutes=10)
MAX_TOOL_ROUNDS = 3


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
                 fillers=None, household=None):
        self._s = settings
        self._store = store
        self._provider = provider
        self._ha = ha
        self._clock = clock
        self._fillers = fillers or FillerPicker()
        self._household = household or Household(settings, store, ha, clock)
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
        chain = plan.messages
        try:
            if tier == 1:
                result, chain = self._run_blocking(plan, 1, reason)
                if self._escalated(result):
                    tier, reason, result = 2, "escalated", None  # tier 2 resumes from chain: tools never re-run
            if result is None:
                result, chain = self._run_blocking(plan, tier, reason, chain)
        except Exception as exc:
            return self._fail(exc, plan, tier, reason)
        return self._finish(replace(plan, messages=chain), tier, reason, result)

    @staticmethod
    def _tools(tier: int) -> list:
        return [ESCALATE_TOOL, *HOUSEHOLD_TOOLS] if tier == 1 else list(HOUSEHOLD_TOOLS)

    def _run_blocking(self, plan: _Plan, tier: int, reason: str,
                      start: list[dict] | None = None) -> tuple[ProviderResult, list[dict]]:
        """Model call plus household tool rounds and one pause_turn continuation, merged into one result.

        Returns (result, messages that produced the final call); history is that chain plus result.content.
        A tier-1 result that escalates is returned as is.
        """
        messages, acc, rounds, paused = start or plan.messages, None, 0, False
        tools = self._tools(tier)
        while True:
            try:
                result = self._call(tier, reason, plan.system, messages, tools, plan.cid, plan.req, plan.chars,
                                    plan.now)
            except _DeadlineExceeded:
                if acc is None:
                    raise
                log.warning("continuation skipped: deadline")
                return acc, messages
            if tier == 1 and self._escalated(result):
                return result, messages
            acc = self._accumulate(acc, result)
            step = self._advance(result, messages, tier, rounds, paused)
            if step is None:
                return acc, messages
            messages, rounds, paused = step

    @staticmethod
    def _accumulate(acc: ProviderResult | None, result: ProviderResult) -> ProviderResult:
        if acc is None:
            return result
        return replace(Engine._merge(acc, result), content=result.content)  # history keeps only the last turn

    def _advance(self, result: ProviderResult, messages: list[dict], tier: int, rounds: int,
                 paused: bool) -> tuple[list[dict], int, bool] | None:
        """Decide what follows a result: None when done (or out of rounds), else the next messages."""
        if result.stop_reason == "tool_use":
            uses = [b for b in result.content if isinstance(b, dict) and b.get("type") == "tool_use"]
            if not uses or rounds >= MAX_TOOL_ROUNDS:
                return None
            blocks = []
            for b in uses:
                text, is_err = self._household.run(b.get("name", ""), b.get("input") or {})
                blocks.append({"type": "tool_result", "tool_use_id": b.get("id"), "content": text,
                               "is_error": is_err})
            return (messages + [{"role": "assistant", "content": result.content},
                                {"role": "user", "content": blocks}], rounds + 1, paused)
        if result.stop_reason == "pause_turn" and tier == 2 and not paused:
            return messages + [{"role": "assistant", "content": result.content}], rounds, True
        return None

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
        if result.stop_reason in ("pause_turn", "tool_use"):  # unfinished: speak what we have, store nothing
            if result.text.strip():
                return ConverseResponse(result.text, cid, False)
            done = self._last_tool_texts(plan.messages)
            if done:
                return ConverseResponse(done, cid, False)
            return self._respond(ERROR_LINE, cid, req, tier, result.model, reason + ":paused", "error", chars)
        if not result.text.strip():
            done = self._last_tool_texts(plan.messages)  # tool round succeeded: never say "error" (no duplicates)
            if done:
                return ConverseResponse(done, cid, False)
            return self._respond(ERROR_LINE, cid, req, tier, result.model, reason + ":empty_text", "error", chars)
        if any(isinstance(b, dict) and b.get("type") == "tool_use" for b in result.content):
            return ConverseResponse(result.text, cid, False)  # unanswered tool_use: store nothing
        with self._lock:
            conv = self._convs.get(cid)
            if conv is not None:
                conv.history = self._history(plan.messages, result.content)
                conv.last_ts = self._clock()
                conv.tier = tier
        speech = result.text
        return ConverseResponse(speech, cid, speech.rstrip().endswith("?"))

    @staticmethod
    def _last_tool_texts(chain: list[dict]) -> str:
        """Spoken-friendly results of the last completed tool round (the chain ends with them)."""
        last = chain[-1] if chain else None
        if not last or last["role"] != "user" or not isinstance(last["content"], list):
            return ""
        return " ".join(b["content"] for b in last["content"]
                        if b.get("type") == "tool_result" and not b.get("is_error") and b.get("content"))

    @staticmethod
    def _history(chain: list[dict], content: list) -> list[dict]:
        if chain and chain[-1]["role"] == "assistant":  # pause_turn continuation: one assistant turn
            return chain[:-1] + [{"role": "assistant", "content": chain[-1]["content"] + content}]
        return chain + [{"role": "assistant", "content": content}]

    def _stream(self, req: ConverseRequest, st: _StreamState) -> Iterator[str]:
        """Yields spoken text pieces; sets st.cid / st.cont / st.model_text."""
        plan = self._plan(req)
        if isinstance(plan, ConverseResponse):
            st.cid = plan.conversation_id
            yield plan.speech
            return
        st.cid = plan.cid
        tier, reason = plan.tier, plan.reason
        start = plan.messages
        if tier == 1:
            try:
                result, chain = self._run_blocking(plan, 1, reason)
            except Exception as exc:
                yield self._fail(exc, plan, 1, reason).speech
                return
            if not self._escalated(result):
                resp = self._finish(replace(plan, messages=chain), 1, reason, result)
                st.cont = resp.continue_conversation
                yield resp.speech
                return
            tier, reason = 2, "escalated"
            start = chain
        yield self._fillers.pick(req.device_id, "web" if reason == "live" else "normal") + " "
        try:
            result, chain = yield from self._stream_loop(plan, tier, reason, st, start)
        except Exception as exc:
            resp = self._fail(exc, plan, tier, reason)
            yield LOST_LINE if st.model_text else resp.speech
            return
        resp = self._finish(replace(plan, messages=chain), tier, reason, result)
        st.cont = resp.continue_conversation
        if st.model_text and resp.speech != result.text:
            st.cont = False  # refusal/empty after partial speech: nothing was committed to history
            yield LOST_LINE
        elif not st.model_text:
            yield resp.speech

    def _stream_loop(self, plan: _Plan, tier: int, reason: str, st: _StreamState,
                     start: list[dict]) -> Iterator[str]:
        """Streamed counterpart of _run_blocking. Returns (result, messages of the final call)."""
        messages, acc, rounds, paused = start, None, 0, False
        while True:
            try:
                result = yield from self._stream_call(plan, tier, reason, st, messages)
            except _DeadlineExceeded:
                if acc is None:
                    raise
                log.warning("continuation skipped: deadline")
                return acc, messages
            acc = self._accumulate(acc, result)
            step = self._advance(result, messages, tier, rounds, paused)
            if step is None:
                return acc, messages
            yield HEARTBEAT  # every continuation: keep the connection alive
            st.seam_pending = bool(st.last_text) and not st.last_text[-1].isspace()
            messages, rounds, paused = step

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
            model=model, system=plan.system, messages=messages, tools=self._tools(tier), effort=effort,
            max_tokens=1024, timeout=max(MIN_CALL_S, remaining),
            server_tools=[WEB_SEARCH_TOOL] if tier == 2 else None,
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
                    yield HEARTBEAT  # silent keep-alive (ping event); never spoken or stored
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
