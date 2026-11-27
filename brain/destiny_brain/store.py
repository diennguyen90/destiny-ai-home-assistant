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
    first_token_ms: int | None = None
    web_searches: int | None = None


@dataclass
class Reminder:
    id: int
    message: str
    due_utc: datetime
    status: str  # pending | sent | cancelled | expired | failed
    attempts: int
    created_utc: datetime
    sent_utc: datetime | None = None


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
CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message TEXT NOT NULL,
    due_utc TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    created_utc TEXT NOT NULL,
    sent_utc TEXT
);
CREATE INDEX IF NOT EXISTS idx_reminders_status_due ON reminders(status, due_utc);
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
                cols = {r[1] for r in c.execute("PRAGMA table_info(requests)")}
                if "first_token_ms" not in cols:
                    c.execute("ALTER TABLE requests ADD COLUMN first_token_ms INTEGER")
                if "web_searches" not in cols:
                    c.execute("ALTER TABLE requests ADD COLUMN web_searches INTEGER")
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
            " latency_ms, outcome, text_chars, first_token_ms, web_searches) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (_iso(rec.ts_utc), rec.conversation_id, rec.device_id, rec.tier, rec.model,
             rec.route_reason, u.input_tokens, u.output_tokens, u.cache_read_tokens,
             u.cache_write_tokens, rec.cost_usd, rec.latency_ms, rec.outcome, rec.text_chars,
             rec.first_token_ms, rec.web_searches),
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
            " text_chars, first_token_ms, web_searches FROM requests ORDER BY ts_utc DESC, id DESC LIMIT ?",
            (limit,),
        )
        return [
            RequestRecord(
                ts_utc=datetime.fromisoformat(r[0]), conversation_id=r[1], device_id=r[2],
                tier=r[3], model=r[4], route_reason=r[5], usage=Usage(r[6], r[7], r[8], r[9]),
                cost_usd=r[10], latency_ms=r[11], outcome=r[12], text_chars=r[13],
                first_token_ms=r[14], web_searches=r[15],
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

    _REMINDER_COLS = "id, message, due_utc, status, attempts, created_utc, sent_utc"

    @staticmethod
    def _reminder(r: tuple) -> Reminder:
        return Reminder(
            id=r[0], message=r[1], due_utc=datetime.fromisoformat(r[2]), status=r[3],
            attempts=r[4], created_utc=datetime.fromisoformat(r[5]),
            sent_utc=datetime.fromisoformat(r[6]) if r[6] else None,
        )

    def add_reminder(self, message: str, due_utc: datetime, now_utc: datetime) -> int:
        c = self._connect()
        try:
            with self._lock, c:
                cur = c.execute(
                    "INSERT INTO reminders (message, due_utc, status, attempts, created_utc)"
                    " VALUES (?, ?, 'pending', 0, ?)",
                    (message, _iso(due_utc), _iso(now_utc)),
                )
                return int(cur.lastrowid)
        finally:
            c.close()

    def pending_reminders(self, limit: int = 10) -> list[Reminder]:
        rows = self._exec(
            f"SELECT {self._REMINDER_COLS} FROM reminders WHERE status = 'pending'"
            " ORDER BY due_utc ASC, id ASC LIMIT ?",
            (limit,),
        )
        return [self._reminder(r) for r in rows]

    def pending_count(self) -> int:
        return int(self._exec("SELECT COUNT(*) FROM reminders WHERE status = 'pending'")[0][0])

    def due_reminders(self, now_utc: datetime) -> list[Reminder]:
        rows = self._exec(
            f"SELECT {self._REMINDER_COLS} FROM reminders WHERE status = 'pending' AND due_utc <= ?"
            " ORDER BY due_utc ASC, id ASC",
            (_iso(now_utc),),
        )
        return [self._reminder(r) for r in rows]

    def cancel_reminder(self, rid: int) -> bool:
        c = self._connect()
        try:
            with self._lock, c:
                cur = c.execute(
                    "UPDATE reminders SET status = 'cancelled' WHERE id = ? AND status = 'pending'",
                    (rid,),
                )
                return cur.rowcount > 0
        finally:
            c.close()

    def mark_reminder(self, rid: int, status: str, now_utc: datetime) -> None:
        self._exec(
            "UPDATE reminders SET status = ?, sent_utc = CASE WHEN ? = 'sent' THEN ? ELSE sent_utc END"
            " WHERE id = ? AND status = 'pending'",
            (status, status, _iso(now_utc), rid),
        )

    def bump_reminder_attempts(self, rid: int) -> int:
        c = self._connect()
        try:
            with self._lock, c:
                c.execute("UPDATE reminders SET attempts = attempts + 1 WHERE id = ?", (rid,))
                row = c.execute("SELECT attempts FROM reminders WHERE id = ?", (rid,)).fetchone()
                return int(row[0]) if row else 0
        finally:
            c.close()
