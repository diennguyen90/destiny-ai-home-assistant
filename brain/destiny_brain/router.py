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

# Team names and strong terms always mean live info; generic terms and a time word plus an event
# word only count when the speaker is not talking about themselves ("I won my game today").
LIVE_TEAM_RE = re.compile(r"\b(?:49ers|niners|nuggets)\b")
LIVE_STRONG_RE = re.compile(r"\b(?:standings|price of|stock price|open now)\b")
LIVE_GENERIC_RE = re.compile(r"\b(?:news|headlines|scores?|latest)\b")
FIRST_PERSON_RE = re.compile(r"\b(?:i|we|my|me|us)\b")
CHICKEN_NUGGETS_RE = re.compile(r"\bchicken nuggets\b")
LIVE_TIME_RE = re.compile(
    r"\b(?:today|tonight|tomorrow|yesterday|last night|this week|this weekend|right now)\b"
)
LIVE_EVENT_RE = re.compile(
    r"\b(?:games?|match|plays?|playing|played|won|win|lost|beat|kickoff|schedule)\b"
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


def _is_live(lowered: str) -> bool:
    if LIVE_TEAM_RE.search(CHICKEN_NUGGETS_RE.sub(" ", lowered)) or LIVE_STRONG_RE.search(lowered):
        return True
    if FIRST_PERSON_RE.search(lowered):
        return False
    return bool(LIVE_GENERIC_RE.search(lowered)) or bool(
        LIVE_TIME_RE.search(lowered) and LIVE_EVENT_RE.search(lowered)
    )


def route(text: str, previous_tier: int | None) -> RouteDecision:
    if previous_tier == 2:
        return RouteDecision(2, "sticky")
    lowered = text.lower()
    if _is_live(lowered) and not WEATHER_RE.search(lowered):
        return RouteDecision(2, "live")
    if any(k in lowered for k in KEYWORDS):
        return RouteDecision(2, "keyword")
    if len(text.split()) >= LONG_WORDS:
        return RouteDecision(2, "long")
    return RouteDecision(1, "default")
