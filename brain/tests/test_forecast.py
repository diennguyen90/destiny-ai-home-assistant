from datetime import datetime, timedelta, timezone

import httpx

from destiny_brain.ha import HAClient
from destiny_brain.prompts import context_block

from .fakes import FakeHA, FakeProvider, make_result
from .test_engine import build, env, req  # noqa: F401

NOW = datetime(2026, 11, 17, 22, 30, tzinfo=timezone.utc)  # Tue 14:30 in Los Angeles


class Clock:
    def __init__(self):
        self.now = NOW

    def __call__(self):
        return self.now


FORECAST = [
    {"datetime": "2026-11-17T08:00:00-08:00", "condition": "partlycloudy", "temperature": 70.2,
     "templow": 52, "precipitation_probability": 10},
    {"datetime": "2026-11-18T00:00:00-08:00", "condition": "rainy", "temperature": 61,
     "templow": 50, "precipitation_probability": 80},
    {"datetime": "2026-11-19T00:00:00-08:00", "condition": "sunny", "temperature": 68,
     "templow": 49},
    {"datetime": "2026-11-20T00:00:00-08:00", "condition": "sunny", "temperature": 99},
]


def make(forecast=FORECAST, wrapper=True, unit="°F", hits=None, clock=None):
    def handler(request):
        if hits is not None:
            hits.append(request)
        assert request.headers["authorization"] == "Bearer tok"
        if request.method == "GET":
            return httpx.Response(200, json={"state": "sunny", "attributes": {
                "temperature_unit": unit}})
        assert request.url.path == "/api/services/weather/get_forecasts"
        assert request.url.query == b"return_response"
        import json
        assert json.loads(request.content) == {"entity_id": "weather.home", "type": "daily"}
        body = {"weather.home": {"forecast": forecast}}
        return httpx.Response(200, json={"changed_states": [], "service_response": body}
                              if wrapper else body)

    return HAClient("http://ha:8123", "tok", httpx.Client(transport=httpx.MockTransport(handler)),
                    clock=clock or Clock(), tz="America/Los_Angeles")


def test_forecast_format_today_tomorrow_weekday():
    assert make().forecast_line("weather.home") == (
        "Forecast: Today partlycloudy, high 70°F low 52°F, 10% chance of rain; "
        "Tomorrow rainy, high 61°F low 50°F, 80% chance of rain; "
        "Thursday sunny, high 68°F low 49°F.")


def test_forecast_bare_response_unit_and_missing_fields():
    fc = [{"datetime": "2026-11-18T00:00:00-08:00", "condition": "snowy-rainy", "temperature": 3}]
    assert make(fc, wrapper=False, unit="°C").forecast_line("weather.home") == (
        "Forecast: Tomorrow snowy rainy, high 3°C.")


def test_forecast_days_param():
    assert make().forecast_line("weather.home", days=1).count(";") == 0


def test_forecast_cache_30_minutes():
    hits, clock = [], Clock()
    ha = make(hits=hits, clock=clock)
    ha.forecast_line("weather.home")
    n = len(hits)
    ha.forecast_line("weather.home")
    assert len(hits) == n
    clock.now += timedelta(minutes=31)
    ha.forecast_line("weather.home")
    assert len(hits) > n


def test_forecast_none_on_failure():
    def mk(handler):
        return HAClient("http://ha:8123", "tok", httpx.Client(transport=httpx.MockTransport(handler)))

    def boom(r):
        raise httpx.ConnectError("x")

    assert mk(lambda r: httpx.Response(403)).forecast_line("weather.home") is None
    assert mk(lambda r: httpx.Response(200, json={"nope": 1})).forecast_line("weather.home") is None
    assert mk(lambda r: httpx.Response(200, json={"weather.home": {"forecast": []}})
              ).forecast_line("weather.home") is None
    assert mk(boom).forecast_line("weather.home") is None


def test_context_block_forecast():
    now = NOW.astimezone(timezone(timedelta(hours=-8)))
    assert context_block(now, "W.", "Forecast: X.").endswith("W. Forecast: X.")
    assert "Forecast" not in context_block(now, "W.", None)


def test_engine_context_includes_forecast_or_omits(env):
    e, p, *_ = build(env, ha=FakeHA(forecast="Forecast: Today sunny."))
    e.handle(req("hi"))
    assert "Home weather now: sunny, 69°F, humidity 26%. Forecast: Today sunny." in p.calls[0]["messages"][-1]["content"]
    e, p, *_ = build(env, ha=FakeHA(forecast=None))
    e.handle(req("hi"))
    assert "Forecast" not in p.calls[0]["messages"][-1]["content"]
