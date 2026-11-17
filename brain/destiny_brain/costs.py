from __future__ import annotations

from dataclasses import dataclass

from .config import ModelPrice


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


def cost_usd(price: ModelPrice, usage: Usage) -> float:
    """Cost in USD; prices are per million tokens."""
    return (
        usage.input_tokens * price.input
        + usage.output_tokens * price.output
        + usage.cache_read_tokens * price.cache_read
        + usage.cache_write_tokens * price.cache_write
    ) / 1_000_000
