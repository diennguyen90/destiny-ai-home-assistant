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
