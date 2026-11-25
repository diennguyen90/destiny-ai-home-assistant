from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Iterator
from typing import Protocol

from ..costs import Usage


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict


@dataclass
class ProviderResult:
    text: str
    content: list[dict]
    tool_calls: list[tuple[str, dict]]
    stop_reason: str
    usage: Usage
    model: str


class ProviderError(Exception):
    """kind in {"rate_limit", "server", "timeout", "connection", "bad_request"}."""

    def __init__(self, kind: str):
        super().__init__(kind)
        self.kind = kind


class ChatProvider(Protocol):
    def complete(
        self,
        *,
        model: str,
        system: list[dict],
        messages: list[dict],
        tools: list[ToolSpec],
        effort: str,
        max_tokens: int = 1024,
        timeout: float | None = None,
    ) -> ProviderResult: ...

    def stream(
        self,
        *,
        model: str,
        system: list[dict],
        messages: list[dict],
        tools: list[ToolSpec],
        effort: str,
        max_tokens: int = 1024,
        timeout: float | None = None,
    ) -> Iterator[str]:
        """Yield text deltas; the generator's return value is a ProviderResult."""
        ...
