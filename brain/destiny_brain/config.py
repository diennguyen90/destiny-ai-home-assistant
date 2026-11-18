from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


@dataclass(frozen=True)
class ModelPrice:
    """USD per million tokens."""

    input: float
    output: float
    cache_read: float
    cache_write: float


def _default_prices() -> dict[str, ModelPrice]:
    return {
        "claude-haiku-5-5": ModelPrice(input=0.10, output=0.50, cache_read=0.01, cache_write=0.125),
        "claude-sonnet-5-5": ModelPrice(input=2.00, output=10.00, cache_read=0.10, cache_write=2.50),
    }


@dataclass(frozen=True)
class Settings:
    anthropic_api_key: str
    brain_shared_key: str
    parent_pin: str
    ha_url: str = "http://homeassistant:8123"
    ha_token: str = ""
    ha_weather_entity: str = "weather.home"
    notify_service: str = ""
    tz: str = "Etc/UTC"
    db_path: str = "/data/brain.db"
    soft_cap_usd: float = 1.0
    hard_cap_usd: float = 3.0
    tier1_model: str = "claude-haiku-5-5"
    tier2_model: str = "claude-sonnet-5-5"
    tier1_effort: str = "low"
    tier2_effort: str = "medium"
    prices: dict[str, ModelPrice] = field(default_factory=_default_prices)


_REQUIRED = ("ANTHROPIC_API_KEY", "BRAIN_SHARED_KEY", "DESTINY_PARENT_PIN")


def load_settings(env: Mapping[str, str]) -> Settings:
    missing = [k for k in _REQUIRED if not env.get(k)]
    if missing:
        raise ValueError("missing required environment variables: " + ", ".join(missing))
    g = env.get
    return Settings(
        anthropic_api_key=env["ANTHROPIC_API_KEY"],
        brain_shared_key=env["BRAIN_SHARED_KEY"],
        parent_pin=env["DESTINY_PARENT_PIN"],
        ha_url=g("BRAIN_HA_URL") or "http://homeassistant:8123",
        ha_token=g("BRAIN_HA_TOKEN") or "",
        ha_weather_entity=g("HA_WEATHER_ENTITY") or "weather.home",
        notify_service=g("DESTINY_NOTIFY_SERVICE") or "",
        tz=g("TZ") or "Etc/UTC",
        db_path=g("DESTINY_DB_PATH") or "/data/brain.db",
        soft_cap_usd=float(g("DESTINY_SOFT_CAP_USD") or 1.0),
        hard_cap_usd=float(g("DESTINY_HARD_CAP_USD") or 3.0),
        tier1_effort=g("DESTINY_TIER1_EFFORT") or "low",
        tier2_effort=g("DESTINY_TIER2_EFFORT") or "medium",
    )
