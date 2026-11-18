from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Callable
from zoneinfo import ZoneInfo

import httpx

log = logging.getLogger(__name__)

_CACHE_TTL = timedelta(minutes=5)
_FORECAST_TTL = timedelta(minutes=30)


class HAClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        http: httpx.Client,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        tz: str = "Etc/UTC",
    ):
        self._base = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {token}"}
        self._http = http
        self._clock = clock
        self._tz = ZoneInfo(tz)
        self._fcache: dict[tuple[str, int], tuple[datetime, str]] = {}
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

    def forecast_line(self, entity_id: str, days: int = 3) -> str | None:
        now = self._clock()
        key = (entity_id, days)
        hit = self._fcache.get(key)
        if hit and now - hit[0] < _FORECAST_TTL:
            return hit[1]
        try:
            resp = self._http.post(
                f"{self._base}/api/services/weather/get_forecasts?return_response",
                headers=self._headers,
                json={"entity_id": entity_id, "type": "daily"},
                timeout=5,
            )
            resp.raise_for_status()
            data = resp.json()
            sr = data.get("service_response", data)
            entries = sr[entity_id]["forecast"]
            unit = self._temperature_unit(entity_id)
            today = now.astimezone(self._tz).date()
            parts = []
            for e in entries[:days]:
                dt = datetime.fromisoformat(str(e["datetime"]).replace("Z", "+00:00"))
                if dt.tzinfo is not None:
                    dt = dt.astimezone(self._tz)
                offset = (dt.date() - today).days
                label = "Today" if offset == 0 else "Tomorrow" if offset == 1 else f"{dt:%A}"
                bits = []
                if e.get("condition"):
                    bits.append(str(e["condition"]).replace("_", " ").replace("-", " "))
                temps = []
                if e.get("temperature") is not None:
                    temps.append(f"high {round(float(e['temperature']))}\u00b0{unit}")
                if e.get("templow") is not None:
                    temps.append(f"low {round(float(e['templow']))}\u00b0{unit}")
                if temps:
                    bits.append(" ".join(temps))
                if e.get("precipitation_probability") is not None:
                    bits.append(f"{round(float(e['precipitation_probability']))}% chance of rain")
                if bits:
                    parts.append(f"{label} " + ", ".join(bits))
            if not parts:
                return None
            line = "Forecast: " + "; ".join(parts) + "."
        except Exception:
            log.warning("forecast lookup failed")
            return None
        self._fcache[key] = (now, line)
        return line

    def _temperature_unit(self, entity_id: str) -> str:
        try:
            resp = self._http.get(
                f"{self._base}/api/states/{entity_id}", headers=self._headers, timeout=5
            )
            resp.raise_for_status()
            return str(resp.json()["attributes"].get("temperature_unit") or "\u00b0F").lstrip("\u00b0")
        except Exception:
            return "F"

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
