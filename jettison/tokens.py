"""Token counting facade.

Uses Headroom's tokenizer registry when available (exact tiktoken /
provider-calibrated estimators), otherwise falls back to a chars/4
estimate. Every count carries a ``measured`` vs ``estimated`` label —
Jettison keeps Headroom's honest-measurement convention everywhere.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

DEFAULT_MODEL = "claude-sonnet-4-5"


@dataclass(frozen=True)
class TokenCount:
    tokens: int
    label: str  # "measured" | "estimated"


class _CharEstimator:
    """chars/4 fallback when no tokenizer backend is importable."""

    label = "estimated"

    def count_text(self, text: str) -> int:
        return max(1, len(text) // 4)


class _HeadroomCounter:
    def __init__(self, model: str) -> None:
        from headroom.tokenizers import get_tokenizer

        self._counter = get_tokenizer(model)
        # EstimatingTokenCounter is calibrated but still an estimate;
        # TiktokenCounter is exact for OpenAI-family models.
        self.label = (
            "measured" if type(self._counter).__name__ == "TiktokenCounter" else "estimated"
        )

    def count_text(self, text: str) -> int:
        return self._counter.count_text(text)


_COUNTER_CACHE: dict[str, Any] = {}


def get_counter(model: str = DEFAULT_MODEL):
    if model not in _COUNTER_CACHE:
        try:
            _COUNTER_CACHE[model] = _HeadroomCounter(model)
        except Exception:
            _COUNTER_CACHE[model] = _CharEstimator()
    return _COUNTER_CACHE[model]


def count_text(text: str, model: str = DEFAULT_MODEL) -> TokenCount:
    c = get_counter(model)
    return TokenCount(tokens=c.count_text(text), label=c.label)


def count_json(value: Any, model: str = DEFAULT_MODEL) -> TokenCount:
    """Count a JSON value as it would appear serialized in a request body."""
    return count_text(json.dumps(value, separators=(",", ":"), ensure_ascii=False), model)
