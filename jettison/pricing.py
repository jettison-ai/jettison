"""Cache-aware dollar accounting (see docs/CACHE_SAFETY.md).

Provider-cached input tokens are ~10x cheaper than fresh input tokens.
Naive "tokens_saved * input_price" accounting overstates savings on
cache-hit-heavy agents and can even hide *negative* savings when an
optimizer breaks prefix caching. Jettison therefore always prices the
three tiers separately: cache_read, input (uncached), cache_write.

Prices are USD per million tokens. The built-in table is a fallback;
when Headroom's pricing module (LiteLLM-backed, 100+ providers) is
importable we defer to it. All dollar figures produced from the builtin
table are labeled "estimated".
"""

from __future__ import annotations

from dataclasses import dataclass

# Fallback price table (USD / 1M tokens): (input, cache_read, cache_write_5m, output)
_FALLBACK_PRICES: dict[str, tuple[float, float, float, float]] = {
    "claude-opus": (15.0, 1.50, 18.75, 75.0),
    "claude-sonnet": (3.0, 0.30, 3.75, 15.0),
    "claude-haiku": (0.80, 0.08, 1.0, 4.0),
    "gpt-5": (1.25, 0.125, 1.25, 10.0),
    "gpt-4o": (2.50, 1.25, 2.50, 10.0),
    "gpt-4o-mini": (0.15, 0.075, 0.15, 0.60),
}
_DEFAULT_PRICE_KEY = "claude-sonnet"


@dataclass(frozen=True)
class Price:
    input_per_m: float
    cache_read_per_m: float
    cache_write_per_m: float
    output_per_m: float
    label: str  # "measured" (provider-derived) | "estimated" (fallback table)


def _match_fallback(model: str) -> tuple[float, float, float, float]:
    m = model.lower()
    for key, prices in _FALLBACK_PRICES.items():
        if key in m:
            return prices
    return _FALLBACK_PRICES[_DEFAULT_PRICE_KEY]


def get_price(model: str) -> Price:
    try:
        # Raw litellm cost map is the only layer carrying cache-tier prices.
        from headroom.pricing.litellm_pricing import (
            get_litellm_model_cost,
            resolve_litellm_model,
        )

        cost_map = get_litellm_model_cost()
        entry = cost_map.get(resolve_litellm_model(model)) or cost_map.get(model)
        if entry and entry.get("input_cost_per_token"):
            inp = float(entry["input_cost_per_token"])
            return Price(
                input_per_m=inp * 1e6,
                cache_read_per_m=float(entry.get("cache_read_input_token_cost", inp)) * 1e6,
                cache_write_per_m=float(entry.get("cache_creation_input_token_cost", inp)) * 1e6,
                output_per_m=float(entry.get("output_cost_per_token", 0.0)) * 1e6,
                label="measured",
            )
    except Exception:
        pass
    i, cr, cw, o = _match_fallback(model)
    return Price(i, cr, cw, o, label="estimated")


@dataclass(frozen=True)
class DollarSavings:
    dollars: float
    label: str


def cache_aware_savings(
    model: str,
    *,
    input_tokens_avoided: int = 0,
    cache_read_tokens_avoided: int = 0,
    cache_write_tokens_avoided: int = 0,
    output_tokens_avoided: int = 0,
) -> DollarSavings:
    """Price avoided tokens at the tier they would actually have billed at.

    Callers MUST classify avoided tokens by tier before calling. Standing
    context that was previously a stable cached prefix must be priced at
    cache_read (cheap), not input — otherwise savings are overstated ~10x.
    """
    p = get_price(model)
    dollars = (
        input_tokens_avoided * p.input_per_m
        + cache_read_tokens_avoided * p.cache_read_per_m
        + cache_write_tokens_avoided * p.cache_write_per_m
        + output_tokens_avoided * p.output_per_m
    ) / 1e6
    return DollarSavings(dollars=dollars, label=p.label)
