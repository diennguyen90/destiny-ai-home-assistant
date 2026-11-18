from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from .costs import Usage


@dataclass
class RequestRecord:
    ts_utc: datetime
    conversation_id: str
    device_id: str | None
    tier: int  # 0 means no model call
    model: str | None
    route_reason: str
    usage: Usage
    cost_usd: float
    latency_ms: int
    outcome: str  # ok | refusal | error | capped | empty
    text_chars: int  # only the length; text itself is never stored


_SCHEMA = """
CREATE TABLE IF NOT EXISTS requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    device_id TEXT,
    tier INTEGER NOT NULL,
    model TEXT,
    route_reason TEXT NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    cache_read_tokens INTEGER NOT NULL,
    cache_write_tokens INTEGER NOT NULL,
    cost_usd REAL NOT NULL,
    latency_ms INTEGER NOT NULL,
    outcome TEXT NOT NULL,
    text_chars INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_requests_ts ON requests(ts_utc);
CREATE TABLE IF NOT EXISTS flags (
    day TEXT PRIMARY KEY,
    soft_cap_notified INTEGER NOT NULL DEFAULT 0
);
"""


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="microseconds")


class Store:
    def __init__(self, db_path: str, tz: str):
        self._db_path = db_path
        self._tz = ZoneInfo(tz)
        self._lock = threading.Lock()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path, timeout=10)

    def init(self) -> None:
        c = self._connect()
        try:
            with self._lock, c:
                c.executescript(_SCHEMA)
        finally:
            c.close()

    def _exec(self, sql: str, params: tuple = ()) -> list[tuple]:
        c = self._connect()
        try:
            with self._lock, c:
                return c.execute(sql, params).fetchall()
        finally:
            c.close()

    def log(self, rec: RequestRecord) -> None:
        u = rec.usage
        self._exec(
            "INSERT INTO requests (ts_utc, conversation_id, device_id, tier, model, route_reason,"
            " input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, cost_usd,"
            " latency_ms, outcome, text_chars) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (_iso(rec.ts_utc), rec.conversation_id, rec.device_id, rec.tier, rec.model,
             rec.route_reason, u.input_tokens, u.output_tokens, u.cache_read_tokens,
             u.cache_write_tokens, rec.cost_usd, rec.latency_ms, rec.outcome, rec.text_chars),
        )

    def _day_bounds(self, day: date) -> tuple[str, str]:
        start = datetime.combine(day, time.min, tzinfo=self._tz)
        end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=self._tz)
        return _iso(start), _iso(end)

    def _sum(self, day: date) -> float:
        lo, hi = self._day_bounds(day)
        rows = self._exec(
            "SELECT COALESCE(SUM(cost_usd), 0) FROM requests WHERE ts_utc >= ? AND ts_utc < ?",
            (lo, hi),
        )
        return float(rows[0][0])

    def spend_today(self, now_utc: datetime) -> float:
        return self._sum(now_utc.astimezone(self._tz).date())

    def recent(self, limit: int = 50) -> list[RequestRecord]:
        rows = self._exec(
            "SELECT ts_utc, conversation_id, device_id, tier, model, route_reason, input_tokens,"
            " output_tokens, cache_read_tokens, cache_write_tokens, cost_usd, latency_ms, outcome,"
            " text_chars FROM requests ORDER BY ts_utc DESC, id DESC LIMIT ?",
            (limit,),
        )
        return [
            RequestRecord(
                ts_utc=datetime.fromisoformat(r[0]), conversation_id=r[1], device_id=r[2],
                tier=r[3], model=r[4], route_reason=r[5], usage=Usage(r[6], r[7], r[8], r[9]),
                cost_usd=r[10], latency_ms=r[11], outcome=r[12], text_chars=r[13],
            )
            for r in rows
        ]

    def cost_by_day(self, days: int = 14, now_utc: datetime | None = None) -> list[tuple[date, float]]:
        now = now_utc or datetime.now(timezone.utc)
        today = now.astimezone(self._tz).date()
        return [
            (d, self._sum(d))
            for d in (today - timedelta(days=i) for i in range(days - 1, -1, -1))
        ]

    def soft_cap_notified(self, day: date) -> bool:
        rows = self._exec("SELECT soft_cap_notified FROM flags WHERE day = ?", (day.isoformat(),))
        return bool(rows and rows[0][0])

    def mark_soft_cap_notified(self, day: date) -> None:
        self._exec(
            "INSERT INTO flags (day, soft_cap_notified) VALUES (?, 1)"
            " ON CONFLICT(day) DO UPDATE SET soft_cap_notified = 1",
            (day.isoformat(),),
        )
