import pytest

from destiny_brain.config import Settings
from destiny_brain.costs import Usage, cost_usd

SONNET = Settings(anthropic_api_key="k", brain_shared_key="k", parent_pin="1").prices["claude-sonnet-5-5"]


def test_cost_usd_sonnet():
    assert cost_usd(SONNET, Usage(1_000_000, 100_000)) == pytest.approx(3.0)


def test_cost_includes_cache():
    u = Usage(0, 0, cache_read_tokens=1_000_000, cache_write_tokens=1_000_000)
    assert cost_usd(SONNET, u) == pytest.approx(0.10 + 2.50)


def test_cost_includes_web_search():
    assert cost_usd(SONNET, Usage(0, 0, web_search_requests=3)) == pytest.approx(0.03)
