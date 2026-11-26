"""Rules-first tier router. Pure, no I/O."""

import re
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

LIVE_RE = re.compile(
    r"\b(?:today|tonight|tomorrow|yesterday|this week|this weekend|latest|current|right now|news"
    r"|scores?|games?|playing|schedule|won|win|lost|standings|price of|stock|open now"
    r"|49ers|niners|nuggets)\b"
)
# Weather is already in the context block, so weather questions never trigger a search.
WEATHER_RE = re.compile(
    r"\b(?:weather|forecast|rain|snow|temperature|hot|cold|sunny|wind|humid)\b"
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
    if LIVE_RE.search(lowered) and not WEATHER_RE.search(lowered):
        return RouteDecision(2, "live")
    if any(k in lowered for k in KEYWORDS):
        return RouteDecision(2, "keyword")
    if len(text.split()) >= LONG_WORDS:
        return RouteDecision(2, "long")
    return RouteDecision(1, "default")
