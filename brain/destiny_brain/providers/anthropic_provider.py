from __future__ import annotations

from collections.abc import Iterator

import anthropic

from ..costs import Usage
from .base import HEARTBEAT, SEARCH_STARTED, ProviderError, ProviderResult, ToolSpec

FALLBACK_BETA = "server-side-fallback-2026-07-01"
BINDING_BETA = "thinking-binding-controls-2026-08-01"
SONNET_PREFIX = "claude-sonnet"


def build_client(api_key: str) -> anthropic.Anthropic:
    # One attempt per call; the engine enforces the overall deadline via per-call timeouts.
    return anthropic.Anthropic(api_key=api_key, timeout=6.0, max_retries=0)


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


def _build_kwargs(model, system, messages, tools, effort, max_tokens, server_tools=None) -> dict:
    kwargs: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": messages,
        "output_config": {"effort": effort},
        "thinking": {
            "type": "adaptive",
            "block_binding": {"prefix_mismatch_behavior": "drop_block"},
        },
    }
    all_tools = [
        {"name": t.name, "description": t.description, "input_schema": t.input_schema}
        for t in tools or ()
    ]
    if all_tools:
        kwargs["tool_choice"] = {"type": "auto"}
    all_tools += list(server_tools or ())
    if all_tools:
        kwargs["tools"] = all_tools
    if model.startswith(SONNET_PREFIX):
        kwargs["betas"] = [BINDING_BETA, FALLBACK_BETA]
        kwargs["fallbacks"] = "default"
    else:
        kwargs["betas"] = [BINDING_BETA]
    return kwargs


def _join_text(content: list[dict]) -> str:
    """Join text blocks with ""; a single space at a seam that spans non-text blocks."""
    out = ""
    gap = False
    for b in content:
        if b.get("type") != "text":
            gap = bool(out) or gap
            continue
        t = b["text"]
        if gap and out and t and not out[-1].isspace() and not t[0].isspace():
            out += " "
        out += t
        gap = False
    return out


def _to_result(resp) -> ProviderResult:
    content = [b.model_dump() for b in resp.content]
    text = _join_text(content)
    tool_calls = [
        (b["name"], b.get("input") or {}) for b in content if b.get("type") == "tool_use"
    ]
    u = resp.usage
    usage = Usage(
        u.input_tokens or 0,
        u.output_tokens or 0,
        getattr(u, "cache_read_input_tokens", None) or 0,
        getattr(u, "cache_creation_input_tokens", None) or 0,
        getattr(getattr(u, "server_tool_use", None), "web_search_requests", None) or 0,
    )
    return ProviderResult(
        text=text,
        content=content,
        tool_calls=tool_calls,
        stop_reason=resp.stop_reason or "",
        usage=usage,
        model=resp.model,
    )


class AnthropicProvider:
    def __init__(self, client):
        self._client = client

    def _with_timeout(self, timeout):
        return self._client.with_options(timeout=timeout) if timeout is not None else self._client

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
        server_tools: list[dict] | None = None,
    ) -> ProviderResult:
        kwargs = _build_kwargs(model, system, messages, tools, effort, max_tokens, server_tools)
        client = self._with_timeout(timeout)
        try:
            resp = client.beta.messages.create(**kwargs)
        except anthropic.APIError as exc:
            mapped = _map_error(exc)
            if mapped is None:
                raise
            raise mapped from exc
        return _to_result(resp)

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
        server_tools: list[dict] | None = None,
    ) -> Iterator[str | object]:
        """Yield text deltas (str) and SEARCH_STARTED per server_tool_use block; the generator's return value is the ProviderResult.

        Closing the generator early exits the SDK stream context, closing the HTTP response.
        """
        kwargs = _build_kwargs(model, system, messages, tools, effort, max_tokens, server_tools)
        client = self._with_timeout(timeout)
        last_text = ""  # last text yielded, to tell whether a seam needs a space
        gap = False  # a non-text block has started since the last text
        try:
            with client.beta.messages.stream(**kwargs) as stream:
                for event in stream:
                    etype = event.type
                    if etype == "content_block_delta":
                        if event.delta.type == "text_delta":
                            if event.delta.text:
                                last_text = event.delta.text
                                gap = False
                                yield event.delta.text
                        else:
                            yield HEARTBEAT
                    elif etype == "content_block_start":
                        btype = event.content_block.type
                        if btype == "server_tool_use":
                            gap = True
                            yield SEARCH_STARTED
                        elif btype == "text":
                            if gap and last_text and not last_text[-1].isspace():
                                last_text = " "
                                yield " "
                            gap = False
                            yield HEARTBEAT
                        else:
                            gap = True
                            yield HEARTBEAT
                    elif etype in ("content_block_stop", "message_start", "message_delta", "message_stop"):
                        yield HEARTBEAT
                final = stream.get_final_message()
        except anthropic.APIError as exc:
            mapped = _map_error(exc)
            if mapped is None:
                raise
            raise mapped from exc
        return _to_result(final)
