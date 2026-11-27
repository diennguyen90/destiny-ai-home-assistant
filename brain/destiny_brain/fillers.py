from __future__ import annotations

import random
import threading
from collections import deque

# Spoken instantly on long questions while the model thinks. Home Assistant only starts
# streaming TTS after more than 60 characters, so each one is at least 61 characters.
FILLERS: tuple[str, ...] = (
    "Ooh, that's a good question, let me think about it for a second.",
    "Hmm, let me put my thinking cap on for that one, just a moment.",
    "Okay, give me a little second while I work that one out for you.",
    "Let me think about that for a moment, I want to get it right.",
    "Alright, hang on just a second while I figure that out for you.",
    "Hmm, that's an interesting one, let me think it through quickly.",
    "One moment please, I'm putting my thoughts together for you now.",
    "Oh, I like that question, give me just a moment to think on it.",
    "Okay, let me chew on that for a second and see what I come up with.",
    "Give me a moment, I'm thinking that one over so I can help you.",
    "Hmm, let me see, I'm going to think about that for a little bit.",
    "That's a fun one, hold on a second while I work out an answer.",
    "Let me take a quick moment to think that through properly for you.",
    "Okay, one second, I'm gathering my thoughts so I can answer well.",
    "Hmm, good thinking, let me dig into that one for you right now.",
    "Just a moment, friend, I'm working on the best answer I can give.",
    "Alright, let me mull that over for a second before I answer you.",
    "Ooh, let me think, I want to give you a proper answer on that.",
)

# Spoken instead of FILLERS when a question needs a web search. Same 61-character minimum.
WEB_FILLERS: tuple[str, ...] = (
    "One sec, I'm surfing through the web to find that out for you.",
    "Ooh, let me hop on the internet real quick and check on that one.",
    "Hang on, I'm zooming around the web to dig up the latest for you.",
    "Give me a moment, I'm riding the information superhighway for you.",
    "Okay, let me go ask the internet about that, back in just a sec.",
    "Hold tight, I'm scouring the web to get you a fresh answer on that.",
    "Let me look that up online real quick, I'll be right back with it.",
    "One moment, I'm diving into the web to see what's happening now.",
    "Ooh, good one, let me search the internet and see what I can find.",
    "Just a sec, my web surfboard is out and I'm hunting for your answer.",
    "Alright, let me peek at the internet for the newest word on that.",
    "Hang tight, I'm checking the web so I can get you the freshest answer.",
)


class FillerPicker:
    """Random filler per device and kind, never repeating among the last `recent` picks."""

    def __init__(self, recent: int = 5):
        self._recent = recent
        self._history: dict[tuple[str, str], deque[str]] = {}
        self._lock = threading.Lock()

    def pick(self, device_id: str | None, kind: str = "normal") -> str:
        """kind is "normal" (FILLERS) or "web" (WEB_FILLERS)."""
        pool = WEB_FILLERS if kind == "web" else FILLERS
        key = (device_id or "_", kind)
        with self._lock:
            hist = self._history.setdefault(key, deque(maxlen=self._recent))
            choices = [f for f in pool if f not in hist] or list(pool)
            choice = random.choice(choices)
            hist.append(choice)
            return choice
