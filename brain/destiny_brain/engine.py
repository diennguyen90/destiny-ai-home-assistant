from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from .config import Settings
from .costs import Usage, cost_usd
from .prompts import DESTINY_BASE, ESCALATE_TOOL, context_block
from .providers.base import ProviderResult
from .router import clean_text, route
from .store import RequestRecord

log = logging.getLogger(__name__)

EMPTY_LINE = "I didn't catch that. Could you say it again?"
CAPPED_LINE = "I've done a lot of thinking today. Let's talk again tomorrow."
ERROR_LINE = "Sorry, something went wrong in my head. Please try again."
REFUSAL_LINE = "I can't help with that one. Let's ask a grown-up."

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
class _Conversation:
    history: list[dict]
    last_ts: datetime
    tier: int | None = None


class Engine:
    def __init__(self, settings: Settings, store, provider, ha, clock=lambda: datetime.now(UTC)):
        self._s = settings
        self._store = store
        self._provider = provider
        self._ha = ha
        self._clock = clock
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

    # -- internals --

    def _handle(self, req: ConverseRequest) -> ConverseResponse:
        text = clean_text(req.text or "")
        now = self._clock()
        cid, history, previous_tier = self._resolve(req.conversation_id, now)
        if not text:
            return self._respond(EMPTY_LINE, cid, req, 0, None, "empty", "empty", 0)
        if self._store.spend_today(now) >= self._s.hard_cap_usd:
            return self._respond(CAPPED_LINE, cid, req, 0, None, "hard_cap", "capped", len(text))

        decision = route(text, previous_tier)
        tier, reason = decision.tier, decision.reason
        if tier == 2 and self._store.spend_today(now) >= self._s.soft_cap_usd:
            tier, reason = 1, "soft_cap"
            self._notify_soft_cap(now)

        # Volatile context is an append-only mid-conversation system message after the user turn,
        # so the top-level system and all earlier messages stay byte-identical (thinking replay).
        messages = history + [{"role": "user", "content": text},
                              {"role": "system", "content": self._context(now)}]
        system = [{"type": "text", "text": DESTINY_BASE, "cache_control": {"type": "ephemeral"}}]
        result: ProviderResult | None = None
        try:
            if tier == 1:
                result = self._call(1, reason, system, messages, [ESCALATE_TOOL], cid, req, len(text), now)
                if any(name == ESCALATE_TOOL.name for name, _ in result.tool_calls):
                    tier, reason, result = 2, "escalated", None
            if result is None:
                result = self._call(tier, reason, system, messages, [], cid, req, len(text), now)
        except _DeadlineExceeded:
            log.warning("model call skipped: deadline")
            return self._respond(ERROR_LINE, cid, req, tier, self._model(tier), reason + ":deadline",
                                 "error", len(text))
        except Exception as exc:
            log.warning("model call failed: %s", getattr(exc, "kind", type(exc).__name__))
            return self._respond(ERROR_LINE, cid, req, tier, self._model(tier), reason, "error", len(text))

        if result.stop_reason == "refusal":
            return self._respond(REFUSAL_LINE, cid, req, tier, result.model, reason, "refusal", len(text),
                                 log_it=False)
        if not result.text.strip():
            return self._respond(ERROR_LINE, cid, req, tier, result.model, reason + ":empty_text", "error",
                                 len(text))
        with self._lock:
            conv = self._convs.get(cid)
            if conv is not None:
                conv.history = messages + [{"role": "assistant", "content": result.content}]
                conv.last_ts = self._clock()
                conv.tier = tier
        speech = result.text
        return ConverseResponse(speech, cid, speech.rstrip().endswith("?"))

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
            timeout=max(MIN_CALL_S, remaining),
        )
        latency = int((time.monotonic() - start) * 1000)
        escalated = any(n == ESCALATE_TOOL.name for n, _ in result.tool_calls)
        outcome = "refusal" if result.stop_reason == "refusal" else "ok"
        self._log(cid, req, tier, result.model or model, "escalated" if escalated else reason, result.usage, latency,
                  outcome, chars, requested=model)
        return result

    def _log(self, cid, req, tier, model, reason, usage: Usage, latency, outcome, chars, requested=None) -> None:
        price = self._price(model, requested)
        cost = cost_usd(price, usage) if price else 0.0
        self._store.log(RequestRecord(
            ts_utc=self._clock(), conversation_id=cid, device_id=req.device_id, tier=tier, model=model,
            route_reason=reason, usage=usage, cost_usd=cost, latency_ms=latency, outcome=outcome,
            text_chars=chars,
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
        return context_block(now.astimezone(self._tz), weather)

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
