from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI

from .config import Settings, load_settings


def create_app(settings: Settings, deps: Any = None) -> FastAPI:
    """Build the FastAPI app. `deps` (type Deps, defined in a later task) is unused for now."""
    app = FastAPI(title="Destiny brain")
    app.state.settings = settings
    app.state.deps = deps

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


def main_app() -> FastAPI:
    return create_app(load_settings(os.environ))
