"""Horizon Manager tests: economics, cache safety, reversibility, verification."""

from __future__ import annotations

from jettison.horizon import (
    HorizonManager,
    HorizonStats,
    evaluate_shape,
    eviction_break_even_turns,
    resident_value_usd,
)
from jettison.horizon.manager import RETRIEVE_TOOL

BIG = "def handler(request):\n    return process(request)\n" * 500  # ~large file read
SMALL = "ok\n"


def test_value_scales_with_remaining_turns():
    """The same content is worth far more to shape early in a session."""
    from jettison.pricing import get_price

    p = get_price("claude-sonnet-4-5")
    early = resident_value_usd(10_000, 47, p)
    late = resident_value_usd(10_000, 1, p)
    assert early > late * 40


def test_small_results_are_left_alone():
    d = evaluate_shape(500, remaining_turns=40)
    assert not d.should_shape
    assert "floor" in d.reason


def test_large_early_result_is_shaped():
    d = evaluate_shape(20_000, remaining_turns=40)
    assert d.should_shape
    assert d.tokens_freed > 19_000
    assert d.projected_usd > 0


def test_large_result_at_session_end_is_not_worth_it():
    """No remaining turns means no repeated billing to avoid."""
    d = evaluate_shape(20_000, remaining_turns=0)
    assert not d.should_shape


def test_eviction_break_even_is_why_we_do_not_evict():
    assert eviction_break_even_turns("claude-sonnet-4-5") > 10


def test_shaping_is_reversible():
    m = HorizonManager()
    stats = HorizonStats()
    shaped, decision = m.shape_result(BIG, remaining_turns=40, stats=stats)
    assert decision.should_shape
    assert len(shaped) < len(BIG)
    assert RETRIEVE_TOOL in shaped
    key = shaped.split("key=")[1].split("]")[0].strip()
    assert m.retrieve(key) == BIG


def test_shaping_refuses_when_a_commitment_would_be_lost():
    """Tool output carrying an exact value must survive intact."""
    content = (
        "preamble line\n" * 400
        + "\nrequest aborted after a timeout of 30 seconds\n"
        + "trailing\n" * 400
    )
    m = HorizonManager()
    stats = HorizonStats()
    shaped, decision = m.shape_result(content, remaining_turns=40, stats=stats)
    assert shaped == content
    assert not decision.should_shape
    assert stats.skipped_commitments == 1


def test_shape_newest_turn_only_anthropic():
    """History must not be touched — it is already in the provider cache."""
    m = HorizonManager()
    body = {
        "messages": [
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "old", "content": BIG}]},
            {"role": "assistant", "content": [{"type": "text", "text": "thinking"}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "new", "content": BIG}]},
        ]
    }
    stats = m.shape_newest_turn(body, "anthropic", remaining_turns=40)
    assert stats.shaped == 1
    assert body["messages"][0]["content"][0]["content"] == BIG          # history intact
    assert body["messages"][2]["content"][0]["content"] != BIG          # newest shaped


def test_shape_newest_turn_openai():
    m = HorizonManager()
    body = {
        "messages": [
            {"role": "tool", "tool_call_id": "old", "content": BIG},
            {"role": "assistant", "content": "…"},
            {"role": "tool", "tool_call_id": "new", "content": BIG},
        ]
    }
    stats = m.shape_newest_turn(body, "openai", remaining_turns=40)
    assert stats.shaped == 1
    assert body["messages"][0]["content"] == BIG
    assert body["messages"][2]["content"] != BIG


def test_non_tool_turn_is_untouched():
    m = HorizonManager()
    body = {"messages": [{"role": "user", "content": "just a question"}]}
    stats = m.shape_newest_turn(body, "anthropic", remaining_turns=40)
    assert stats.shaped == 0
    assert body["messages"][0]["content"] == "just a question"


def test_retrieve_meta_tool_returns_original():
    from jettison.compiler import build_bundle, compile_instructions, minify_tools
    from jettison.registry import CapabilityStore
    from jettison.registry.metatools import resolve_meta_call

    m = HorizonManager()
    stats = HorizonStats()
    shaped, _ = m.shape_result(BIG, remaining_turns=40, stats=stats)
    key = shaped.split("key=")[1].split("]")[0].strip()
    store = CapabilityStore(build_bundle(minify_tools([]), compile_instructions([]), [], ""))
    assert resolve_meta_call(store, RETRIEVE_TOOL, {"key": key}, m) == BIG
    missing = resolve_meta_call(store, RETRIEVE_TOOL, {"key": "nope"}, m)
    assert "no held content" in missing
