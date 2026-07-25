"""The arithmetic that decides what is worth shaping.

A tool result is not billed once. It lands in the conversation and is then
re-sent on every later turn of the session, so its true cost is
``tokens x remaining_turns``, priced at the cache-read rate. That makes an
early large result worth far more to shape than an identical one arriving
near the end — the same 8k-token file read is worth 40x more at turn 3 of a
50-turn session than at turn 49.

The counterpart matters just as much: mutating content that is already in
a cached prefix invalidates the cache from that point on, and cache-WRITE
costs ~12.5x cache-READ. Measured on 101 real sessions, evicting from
history cleared break-even only 17 times and returned 2.6%, while shaping
results as they arrive — which never touches a cached prefix — returned
6.0%. Hence the rule this module encodes: shape on arrival, do not evict.
"""

from __future__ import annotations

from dataclasses import dataclass

from jettison.pricing import Price, get_price

# Below this a result is not worth a placeholder + retrieval round-trip.
MIN_SHAPEABLE_TOKENS = 2_000
# What the replacement costs: marker, retrieval key, and a short summary.
PLACEHOLDER_TOKENS = 60
# Don't bother for trivial gains; the model pays a comprehension cost for
# every placeholder it has to reason around.
MIN_VALUE_USD = 0.0005
# Sessions we have no length estimate for: assume a short remaining horizon
# so we shape conservatively rather than optimistically.
DEFAULT_REMAINING_TURNS = 8


@dataclass(frozen=True)
class ShapeDecision:
    should_shape: bool
    reason: str
    projected_usd: float
    tokens_freed: int


def resident_value_usd(tokens: int, remaining_turns: int, price: Price) -> float:
    """What keeping `tokens` resident for `remaining_turns` more turns costs."""
    return max(0, tokens) * max(0, remaining_turns) * price.cache_read_per_m / 1e6


def evaluate_shape(
    tokens: int,
    remaining_turns: int = DEFAULT_REMAINING_TURNS,
    model: str = "claude-sonnet-4-5",
    *,
    min_tokens: int = MIN_SHAPEABLE_TOKENS,
    min_value_usd: float = MIN_VALUE_USD,
) -> ShapeDecision:
    price = get_price(model)
    if tokens < min_tokens:
        return ShapeDecision(False, f"below {min_tokens}-token floor", 0.0, 0)
    freed = tokens - PLACEHOLDER_TOKENS
    if freed <= 0:
        return ShapeDecision(False, "placeholder is no smaller than the content", 0.0, 0)
    value = resident_value_usd(freed, remaining_turns, price)
    if value < min_value_usd:
        return ShapeDecision(
            False, f"projected ${value:.5f} below ${min_value_usd} floor", value, 0
        )
    return ShapeDecision(True, f"frees {freed:,} tokens for {remaining_turns} turns", value, freed)


def eviction_break_even_turns(model: str = "claude-sonnet-4-5") -> float:
    """How many turns of cache-reads one re-cache must displace to pay off.

    This is why history eviction is not implemented: on current Anthropic
    pricing the answer is ~12.5 turns, and most large results are not
    resident that much longer once they go stale.
    """
    p = get_price(model)
    if p.cache_read_per_m <= 0:
        return float("inf")
    return p.cache_write_per_m / p.cache_read_per_m
