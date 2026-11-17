from __future__ import annotations

import anthropic

from ..costs import Usage
from .base import ProviderError, ProviderResult, ToolSpec

FALLBACK_BETA = "server-side-fallback-2026-07-01"
SONNET_PREFIX = "claude-sonnet"


def build_client(api_key: str) -> anthropic.Anthropic:
    # 6 s x (1 retry + 1 attempt) keeps the total under the connector's 15 s.
    return anthropic.Anthropic(api_key=api_key, timeout=6.0, max_retries=1)


def _map_error(exc: Exception) -> ProviderError | None:
    # Most specific first: APITimeoutError subclasses APIConnectionError.
    if isinstance(exc, anthropic.APITimeoutError):
        return ProviderError("timeout")
    if isinstance(exc, anthropic.APIConnectionError):
        return ProviderError("connection")
    if isinstance(exc, anthropic.RateLimitError):
        return ProviderError("rate_limit")
    if isinstance(exc, anthropic.BadRequestError):
        return ProviderError("bad_request")
    if isinstance(exc, anthropic.InternalServerError):
        return ProviderError("server")
    if isinstance(exc, anthropic.APIStatusError):
        return ProviderError("server")
    return None


class AnthropicProvider:
    def __init__(self, client):
        self._client = client

    def complete(
        self,
        *,
        model: str,
        system: list[dict],
        messages: list[dict],
        tools: list[ToolSpec],
        effort: str,
        max_tokens: int = 1024,
    ) -> ProviderResult:
        kwargs: dict = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": messages,
            "output_config": {"effort": effort},
        }
        if tools:
            kwargs["tools"] = [
                {"name": t.name, "description": t.description, "input_schema": t.input_schema}
                for t in tools
            ]
            kwargs["tool_choice"] = {"type": "auto"}
        try:
            if model.startswith(SONNET_PREFIX):
                resp = self._client.beta.messages.create(
                    **kwargs, betas=[FALLBACK_BETA], fallbacks="default"
                )
            else:
                resp = self._client.messages.create(**kwargs)
        except anthropic.APIError as exc:
            mapped = _map_error(exc)
            if mapped is None:
                raise
            raise mapped from exc

        content = [b.model_dump() for b in resp.content]
        text = " ".join(b["text"] for b in content if b.get("type") == "text")
        tool_calls = [
            (b["name"], b.get("input") or {}) for b in content if b.get("type") == "tool_use"
        ]
        u = resp.usage
        usage = Usage(
            u.input_tokens or 0,
            u.output_tokens or 0,
            getattr(u, "cache_read_input_tokens", None) or 0,
            getattr(u, "cache_creation_input_tokens", None) or 0,
        )
        return ProviderResult(
            text=text,
            content=content,
            tool_calls=tool_calls,
            stop_reason=resp.stop_reason or "",
            usage=usage,
            model=resp.model,
        )
