import pytest

from destiny_brain.router import RouteDecision, clean_text, route

THIRTY = " ".join(["word"] * 30)


@pytest.mark.parametrize(
    "text,prev,expected",
    [
        ("what time is it in Tokyo", None, (1, "default")),
        ("Why is the sky blue?", None, (2, "keyword")),
        ("Can you EXPLAIN photosynthesis", None, (2, "keyword")),
        (THIRTY, None, (2, "long")),
        ("ok", 2, (2, "sticky")),
        ("ok", 1, (1, "default")),
        ("What's the difference between a frog and a toad", None, (2, "keyword")),
    ],
)
def test_route(text, prev, expected):
    d = route(text, prev)
    assert isinstance(d, RouteDecision)
    assert (d.tier, d.reason) == expected


def test_clean_text_collapses_whitespace():
    assert clean_text("  a \n b ") == "a b"


def test_clean_text_truncates():
    assert len(clean_text("x" * 5000)) == 2000


def test_clean_text_keeps_unicode():
    assert clean_text("¿Qué tal? 🚗") == "¿Qué tal? 🚗"


@pytest.mark.parametrize(
    "text",
    [
        "do the nuggets play tonight",
        "who won the 49ers game",
        "what's in the news today",
        "what time is the niners game",
        "latest score",
    ],
)
def test_live_words_route_tier2(text):
    d = route(text, None)
    assert (d.tier, d.reason) == (2, "live")


def test_live_sticky_wins():
    assert route("do the nuggets play tonight", 2).reason == "sticky"


@pytest.mark.parametrize(
    "text",
    [
        "what's the weather tomorrow",
        "is it going to rain today",
        "how hot is it right now",
        "what's the forecast this weekend",
    ],
)
def test_weather_questions_not_live(text):
    assert route(text, None).reason != "live"


@pytest.mark.parametrize(
    "text",
    [
        "I wonder why cats purr",
        "open the windows",
        "currently learning fractions",
        "let's go to the playground",
    ],
)
def test_live_word_boundaries(text):
    assert route(text, None).reason != "live"
