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
