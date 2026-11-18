from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Callable

import httpx

log = logging.getLogger(__name__)

_CACHE_TTL = timedelta(minutes=5)


class HAClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        http: httpx.Client,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ):
        self._base = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {token}"}
        self._http = http
        self._clock = clock
        self._cache: dict[str, tuple[datetime, str]] = {}

    def weather_line(self, entity_id: str) -> str | None:
        now = self._clock()
        hit = self._cache.get(entity_id)
        if hit and now - hit[0] < _CACHE_TTL:
            return hit[1]
        try:
            resp = self._http.get(
                f"{self._base}/api/states/{entity_id}", headers=self._headers, timeout=5
            )
            resp.raise_for_status()
            data = resp.json()
            attrs = data["attributes"]
            condition = str(data["state"]).replace("_", " ").replace("-", " ")
            unit = str(attrs.get("temperature_unit") or "°F").lstrip("°")
            line = (
                f"Home weather now: {condition}, {round(float(attrs['temperature']))}°{unit}, "
                f"humidity {round(float(attrs['humidity']))}%."
            )
        except Exception:
            log.warning("weather lookup failed")
            return None
        self._cache[entity_id] = (now, line)
        return line

    def notify(self, service: str, title: str, message: str) -> bool:
        service = service.removeprefix("notify.")
        try:
            resp = self._http.post(
                f"{self._base}/api/services/notify/{service}",
                headers=self._headers,
                json={"title": title, "message": message},
                timeout=5,
            )
            resp.raise_for_status()
            return True
        except Exception:
            log.warning("notify failed")
            return False
