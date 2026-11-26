from destiny_brain.prompts import DESTINY_BASE, ESCALATE_TOOL, WEB_SEARCH_TOOL


def test_prompt_mentions_teams_and_no_links():
    for word in ("49ers", "Nuggets", "Pacific time", "links"):
        assert word in DESTINY_BASE


def test_escalate_description_mentions_live_info():
    assert "current or live information" in ESCALATE_TOOL.description


def test_web_search_tool_verbatim():
    assert WEB_SEARCH_TOOL == {
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
