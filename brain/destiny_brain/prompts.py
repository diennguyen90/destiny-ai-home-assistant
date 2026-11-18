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
    "keep it family-friendly. If asked, say you are an AI."
)

ESCALATE_TOOL = ToolSpec(
    "needs_deeper_answer",
    "Call this instead of answering when the question needs a careful, multi-step or teaching explanation.",
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
