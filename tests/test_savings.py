"""Savings ledger + cache-aware pricing tests."""

from __future__ import annotations

import pytest

from jettison.pricing import cache_aware_savings, get_price
from jettison.savings import ledger


@pytest.fixture(autouse=True)
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("JETTISON_WORKSPACE_DIR", str(tmp_path))
    return tmp_path


def test_cache_read_pricing_is_much_cheaper_than_input():
    p = get_price("claude-sonnet-4-5")
    assert p.cache_read_per_m < p.input_per_m / 2
    read = cache_aware_savings("claude-sonnet-4-5", cache_read_tokens_avoided=1_000_000)
    inp = cache_aware_savings("claude-sonnet-4-5", input_tokens_avoided=1_000_000)
    assert inp.dollars > read.dollars * 2


def test_ledger_roundtrip_and_windows():
    assert ledger.record_event(tokens_before=10_000, tokens_after=1_000, model="claude-sonnet-4-5", client="t")
    assert not ledger.record_event(tokens_before=100, tokens_after=100)  # zero savings dropped
    agg = ledger.aggregate()
    assert agg.events == 1
    assert agg.tokens_saved == 9_000
    assert agg.cost_usd > 0
    assert agg.by_client == {"t": 9_000}
    assert 89 < agg.savings_percent < 91


def test_unknown_model_falls_back_estimated():
    p = get_price("totally-made-up-model-xyz")
    assert p.label == "estimated"
    assert p.input_per_m > 0
