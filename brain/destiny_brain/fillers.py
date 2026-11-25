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


class FillerPicker:
    """Random filler per device, never repeating among that device's last `recent` picks."""

    def __init__(self, recent: int = 5):
        self._recent = recent
        self._history: dict[str, deque[str]] = {}
        self._lock = threading.Lock()

    def pick(self, device_id: str | None) -> str:
        key = device_id or "_"
        with self._lock:
            hist = self._history.setdefault(key, deque(maxlen=self._recent))
            choices = [f for f in FILLERS if f not in hist] or list(FILLERS)
            choice = random.choice(choices)
            hist.append(choice)
            return choice
