"""Rules-first tier router. Pure, no I/O."""

from dataclasses import dataclass

MAX_CHARS = 2000
LONG_WORDS = 25

KEYWORDS = (
    "explain",
    "why does",
    "why do",
    "why is",
    "why are",
    "how does",
    "how do",
    "help me understand",
    "teach me",
    "what's the difference",
    "what is the difference",
    "homework",
)


@dataclass(frozen=True)
class RouteDecision:
    tier: int
    reason: str


def clean_text(text: str) -> str:
    """Strip, collapse whitespace and truncate to 2,000 characters."""
    return " ".join(text.split())[:MAX_CHARS]


def route(text: str, previous_tier: int | None) -> RouteDecision:
    if previous_tier == 2:
        return RouteDecision(2, "sticky")
    lowered = text.lower()
    if any(k in lowered for k in KEYWORDS):
        return RouteDecision(2, "keyword")
    if len(text.split()) >= LONG_WORDS:
        return RouteDecision(2, "long")
    return RouteDecision(1, "default")
