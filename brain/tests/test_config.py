import pytest

from destiny_brain.config import load_settings

REQUIRED = {"ANTHROPIC_API_KEY": "k", "BRAIN_SHARED_KEY": "s", "DESTINY_PARENT_PIN": "1234"}


def test_defaults():
    s = load_settings(REQUIRED)
    assert s.tier1_model == "claude-haiku-5-5"
    assert s.prices["claude-sonnet-5-5"].output == 10.0
    assert s.soft_cap_usd == 1.0
    assert s.hard_cap_usd == 3.0


def test_missing_required_raises():
    with pytest.raises(ValueError) as e:
        load_settings({})
    assert "ANTHROPIC_API_KEY" in str(e.value)


def test_missing_required_does_not_leak_values():
    with pytest.raises(ValueError) as e:
        load_settings({"BRAIN_SHARED_KEY": "supersecret"})
    assert "supersecret" not in str(e.value)


def test_overrides():
    s = load_settings({**REQUIRED, "DESTINY_SOFT_CAP_USD": "2.5"})
    assert s.soft_cap_usd == 2.5


def test_default_prices_and_efforts():
    s = load_settings(REQUIRED)
    h = s.prices["claude-haiku-5-5"]
    assert (h.input, h.output, h.cache_read, h.cache_write) == (0.10, 0.50, 0.01, 0.125)
    so = s.prices["claude-sonnet-5-5"]
    assert (so.input, so.output, so.cache_read, so.cache_write) == (2.00, 10.00, 0.10, 2.50)
    assert (s.tier1_effort, s.tier2_effort) == ("low", "medium")
    assert (s.soft_cap_usd, s.hard_cap_usd) == (1.0, 3.0)


def test_reminder_notify_falls_back_to_notify_service():
    s = load_settings({**REQUIRED, "DESTINY_NOTIFY_SERVICE": "mobile_app_iphone"})
    assert s.reminder_notify_service == "mobile_app_iphone"
    s = load_settings({**REQUIRED, "DESTINY_NOTIFY_SERVICE": "a", "DESTINY_REMINDER_NOTIFY": "b",
                       "DESTINY_CALENDAR_ENTITY": "calendar.x"})
    assert s.reminder_notify_service == "b"
    assert s.calendar_entity == "calendar.x"
    assert load_settings(REQUIRED).calendar_entity == ""
