from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
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
        self._cal_cache: tuple[datetime, str | None] | None = None
        self._cal_choice: str | None = None

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

    def find_calendar(self, preferred: str = "") -> str | None:
        if preferred:
            return preferred
        now = self._clock()
        if self._cal_cache and now - self._cal_cache[0] < _CACHE_TTL:
            return self._cal_cache[1]
        try:
            resp = self._http.get(f"{self._base}/api/states", headers=self._headers, timeout=5)
            resp.raise_for_status()
            cals = [s for s in resp.json() if str(s.get("entity_id", "")).startswith("calendar.")]
        except Exception:
            log.warning("calendar discovery failed")
            return None

        def skip(s: dict) -> bool:
            name = f"{s['entity_id']} {(s.get('attributes') or {}).get('friendly_name', '')}".lower()
            return "holiday" in name or "birthday" in name

        def writable(s: dict) -> bool:
            try:
                return bool(int((s.get("attributes") or {}).get("supported_features") or 0) & 1)
            except (TypeError, ValueError):
                return False

        cals.sort(key=lambda s: str(s["entity_id"]))
        found = None
        for pick in (lambda s: writable(s) and not skip(s), lambda s: not skip(s), lambda s: True):
            match = next((s for s in cals if pick(s)), None)
            if match:
                found = str(match["entity_id"])
                break
        if found != self._cal_choice:
            self._cal_choice = found
            if found:
                log.warning("calendar auto-selected: %s (set DESTINY_CALENDAR_ENTITY to override)", found)
        self._cal_cache = (now, found)
        return found

    def calendar_events(self, entity_id: str, start: datetime, end: datetime) -> list[dict] | None:
        try:
            resp = self._http.get(
                f"{self._base}/api/calendars/{entity_id}",
                headers=self._headers,
                params={"start": start.isoformat(), "end": end.isoformat()},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else None
        except Exception:
            log.warning("calendar lookup failed")
            return None

    def create_calendar_event(
        self,
        entity_id: str,
        summary: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        location: str | None = None,
    ) -> bool:
        body: dict = {"entity_id": entity_id, "summary": summary}
        if start_date is not None and end_date is not None:
            body["start_date"] = start_date.isoformat()
            body["end_date"] = end_date.isoformat()
        elif start is not None and end is not None:
            body["start_date_time"] = start.isoformat()
            body["end_date_time"] = end.isoformat()
        else:
            return False
        if location:
            body["location"] = location
        try:
            resp = self._http.post(
                f"{self._base}/api/services/calendar/create_event",
                headers=self._headers, json=body, timeout=10,
            )
            resp.raise_for_status()
            return True
        except Exception:
            log.warning("calendar create failed")
            return False
