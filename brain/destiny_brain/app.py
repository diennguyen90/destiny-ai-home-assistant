from __future__ import annotations

import anyio
import hmac
import json
import os
import secrets
import time
from html import escape
from pathlib import Path
from string import Template
from typing import Any
from urllib.parse import parse_qs

from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import iterate_in_threadpool, run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel

from .config import Settings, load_settings

COOKIE = "destiny_parent"
SESSION_TTL_S = 12 * 3600
_TEMPLATE = Template((Path(__file__).parent / "templates" / "parent.html").read_text(encoding="utf-8"))

_LOGIN_FORM = (
    '<form method="post" action="/parent/login"><label>PIN '
    '<input type="password" name="pin" autocomplete="off" autofocus></label> '
    '<button type="submit">Sign in</button></form>'
)


class ConverseBody(BaseModel):
    text: str
    conversation_id: str | None = None
    device_id: str | None = None
    satellite_id: str | None = None
    language: str = "en"


def _eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def _page(body: str, status: int = 200) -> HTMLResponse:
    return HTMLResponse(_TEMPLATE.substitute(body=body), status_code=status)


def _dashboard(settings: Settings, store: Any) -> str:
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    spend = store.spend_today(now)
    parts = [
        "<h2>Today</h2>",
        f"<p>Spent ${spend:.4f} of soft cap ${settings.soft_cap_usd:.2f} / "
        f"hard cap ${settings.hard_cap_usd:.2f}</p>",
        "<h2>Cost by day</h2><table><tr><th>Day</th><th>Cost (USD)</th></tr>",
    ]
    for day, cost in store.cost_by_day(14, now):
        parts.append(f"<tr><td>{escape(day.isoformat())}</td><td>${cost:.4f}</td></tr>")
    parts.append("</table><h2>Last 50 requests</h2><table><tr><th>Time (UTC)</th><th>Tier</th>"
                 "<th>Model</th><th>Reason</th><th>Tokens in/out</th><th>Cost</th>"
                 "<th>Latency ms</th><th>First word (ms)</th><th>Outcome</th></tr>")
    for r in store.recent(50):
        u = r.usage
        parts.append(
            "<tr>"
            f"<td>{escape(r.ts_utc.strftime('%Y-%m-%d %H:%M:%S'))}</td><td>{r.tier}</td>"
            f"<td>{escape(r.model or '-')}</td><td>{escape(r.route_reason)}</td>"
            f"<td>{u.input_tokens}/{u.output_tokens}</td><td>${r.cost_usd:.4f}</td>"
            f"<td>{r.latency_ms}</td>"
            f"<td>{'' if r.first_token_ms is None else escape(str(r.first_token_ms))}</td>"
            f"<td>{escape(r.outcome)}</td></tr>"
        )
    parts.append("</table>")
    return "".join(parts)


def create_app(settings: Settings, deps: Any = None) -> FastAPI:
    app = FastAPI(title="Destiny brain")
    app.state.settings = settings
    app.state.deps = deps
    sessions: dict[str, float] = {}

    def _authed(request: Request) -> bool:
        token = request.cookies.get(COOKIE)
        if not token:
            return False
        exp = sessions.get(token)
        if exp is None:
            return False
        if exp < time.monotonic():
            sessions.pop(token, None)
            return False
        return True

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/converse")
    async def converse(request: Request, body: ConverseBody):
        if not _eq(request.headers.get("X-Destiny-Key", ""), settings.brain_shared_key):
            raise HTTPException(status_code=401, detail="unauthorized")
        from .engine import ConverseRequest

        req = ConverseRequest(text=body.text, conversation_id=body.conversation_id,
                              device_id=body.device_id, satellite_id=body.satellite_id,
                              language=body.language)
        resp = await run_in_threadpool(app.state.deps.engine.handle, req)
        return JSONResponse({"speech": resp.speech, "conversation_id": resp.conversation_id,
                             "continue_conversation": resp.continue_conversation})

    @app.post("/v1/converse/stream")
    async def converse_stream(request: Request, body: ConverseBody):
        if not _eq(request.headers.get("X-Destiny-Key", ""), settings.brain_shared_key):
            raise HTTPException(status_code=401, detail="unauthorized")
        from .engine import ConverseRequest

        req = ConverseRequest(text=body.text, conversation_id=body.conversation_id,
                              device_id=body.device_id, satellite_id=body.satellite_id,
                              language=body.language)
        events = app.state.deps.engine.handle_stream(req)

        async def lines():
            try:
                async for ev in iterate_in_threadpool(events):
                    yield json.dumps(ev, ensure_ascii=False) + "\n"
            finally:
                # Runs on normal end and on client disconnect (cancellation); shielded so the
                # close still happens while the task is being cancelled.
                with anyio.CancelScope(shield=True):
                    await run_in_threadpool(events.close)

        return StreamingResponse(lines(), media_type="application/x-ndjson")

    @app.get("/parent", response_class=HTMLResponse)
    async def parent(request: Request):
        if not _authed(request):
            return _page(_LOGIN_FORM)
        body = await run_in_threadpool(_dashboard, settings, app.state.deps.store)
        return _page(body)

    @app.post("/parent/login")
    async def parent_login(request: Request):
        raw = (await request.body()).decode("utf-8", errors="replace")
        pin = parse_qs(raw).get("pin", [""])[0]
        if not _eq(pin, settings.parent_pin):
            return _page("<p>Wrong PIN.</p>" + _LOGIN_FORM, 401)
        now = time.monotonic()
        for t in [t for t, e in sessions.items() if e < now]:
            sessions.pop(t, None)
        token = secrets.token_urlsafe(32)
        sessions[token] = now + SESSION_TTL_S
        resp = RedirectResponse("/parent", status_code=303)
        resp.set_cookie(COOKIE, token, max_age=SESSION_TTL_S, httponly=True, samesite="strict", path="/")
        return resp

    return app


def main_app() -> FastAPI:
    from .deps import build_deps

    settings = load_settings(os.environ)
    return create_app(settings, build_deps(settings))
