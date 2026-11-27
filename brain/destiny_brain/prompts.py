from __future__ import annotations

from datetime import datetime

from .providers.base import ToolSpec

DESTINY_BASE = (
    "You are Destiny, a friendly AI assistant for our family. You are speaking out loud, so speak in "
    "natural sentences with no lists, markdown, emojis or symbols. Quick questions get 1-2 sentence "
    "answers. For explanations, speak in short chunks of 3-5 sentences, then ask if they want more. "
    "When someone is learning or doing homework, be a tutor: don't just give the answer; give a hint "
    "or ask a small question and let them try first. If the person sounds like a child, use simple "
    "words and everyday examples. If you are unsure or something may be out of date, say so. Always "
    "keep it family-friendly. If asked, say you are an AI. "
    "When someone says our team or the game, they mean the 49ers or the Nuggets unless another team "
    "is named. Say times in Pacific time. When you use web search results, give a short spoken answer "
    "with no links, URLs, citations or source lists; it is fine to say according to ESPN now and then. "
    "If a search finds nothing current, say so briefly instead of guessing. Keep search results "
    "family-friendly, and decline or soften adult or violent news when talking with a child. "
    "Never announce that you are searching or looking something up; the app already says that, so "
    "just give the answer. "
    "Use your tools for reminders and the family calendar. Never say a reminder or event is set unless "
    "the tool confirmed it, and confirm briefly with the day and time. You can only set one-time "
    "reminders for now. When reading calendar events, say them naturally in a sentence or two."
)

WEB_SEARCH_TOOL: dict = {
    "type": "web_search_20260209",
    "name": "web_search",
    "max_uses": 3,
    "user_location": {
        "type": "approximate",
        "region": "California",
        "country": "US",
        "timezone": "America/Los_Angeles",
    },
}

ESCALATE_TOOL = ToolSpec(
    "needs_deeper_answer",
    "Call this instead of answering when the question needs a careful, multi-step or teaching "
    "explanation, or when the question needs current or live information from the internet "
    "(news, sports, schedules, prices, recent events).",
    {
        "type": "object",
        "properties": {"reason": {"type": "string"}},
        "required": ["reason"],
        "additionalProperties": False,
    },
)


def context_block(
    now_local: datetime, weather_line: str | None, forecast_line: str | None = None
) -> str:
    hour = now_local.hour % 12 or 12
    stamp = (
        f"{now_local:%A, %B} {now_local.day}, {now_local.year}, "
        f"{hour}:{now_local:%M} {now_local:%p}"
    )
    text = f"Current local date and time: {stamp}."
    if weather_line:
        text += " " + weather_line
    if forecast_line:
        text += " " + forecast_line
    return text
