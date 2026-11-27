from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

log = logging.getLogger("destiny.scheduler")

LATE_AFTER = timedelta(minutes=5)
EXPIRE_AFTER = timedelta(hours=24)
MAX_ATTEMPTS = 20
TITLE = "Destiny reminder"


class ReminderScheduler:
    def __init__(self, settings: Any, store: Any, ha: Any,
                 clock: Callable[[], datetime] | None = None, interval: float = 15.0) -> None:
        self._settings = settings
        self._store = store
        self._ha = ha
        self._clock = clock or (lambda: datetime.now(UTC))
        self._interval = interval
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._warned_no_service = False

    def tick(self) -> int:
        with self._lock:
            service = self._settings.reminder_notify_service
            if not service:
                if not self._warned_no_service:
                    self._warned_no_service = True
                    log.warning("No reminder notify service configured; reminders will not be sent")
                return 0
            now = self._clock()
            sent = 0
            for r in self._store.due_reminders(now):
                lateness = now - r.due_utc
                if lateness > EXPIRE_AFTER:
                    self._store.mark_reminder(r.id, "expired", now)
                    log.info("reminder %s expired", r.id)
                    continue
                message = ("(Late) " + r.message) if lateness > LATE_AFTER else r.message
                if self._ha.notify(service, TITLE, message):
                    self._store.mark_reminder(r.id, "sent", now)
                    sent += 1
                    log.info("reminder %s sent", r.id)
                else:
                    if self._store.bump_reminder_attempts(r.id) >= MAX_ATTEMPTS:
                        self._store.mark_reminder(r.id, "failed", now)
                        log.info("reminder %s failed", r.id)
            return sent

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:
                log.exception("reminder scheduler tick failed")
            self._stop.wait(self._interval)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="reminder-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
