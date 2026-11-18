from __future__ import annotations

from dataclasses import dataclass

import httpx

from .config import Settings
from .engine import Engine
from .ha import HAClient
from .providers.anthropic_provider import AnthropicProvider, build_client
from .store import Store


@dataclass
class Deps:
    engine: Engine
    store: Store


def build_deps(settings: Settings) -> Deps:
    store = Store(settings.db_path, settings.tz)
    store.init()
    ha = HAClient(settings.ha_url, settings.ha_token, httpx.Client(timeout=5.0), tz=settings.tz)
    provider = AnthropicProvider(build_client(settings.anthropic_api_key))
    return Deps(engine=Engine(settings, store, provider, ha), store=store)
