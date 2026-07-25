"""Jettison savings ledger — append-only JSONL, schema v1.

Follows Headroom's savings_events.jsonl conventions (cost frozen at
write time; never raises; retention on read). Separate file from
Headroom's so `jettison savings` composes both: Jettison's standing-
context savings + Headroom's runtime-compression savings.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from jettison.pricing import cache_aware_savings

SCHEMA_VERSION = 1
RETENTION_DAYS = 90


def ledger_path() -> Path:
    root = Path(os.environ.get("JETTISON_WORKSPACE_DIR", Path.home() / ".jettison"))
    root.mkdir(parents=True, exist_ok=True)
    return root / "savings_events.jsonl"


def record_event(
    *,
    tokens_before: int,
    tokens_after: int,
    model: str = "unknown",
    client: str = "unknown",
    source: str = "proxy",
    cache_tier: str = "cache_read",  # tier the avoided tokens would have billed at
) -> bool:
    saved = tokens_before - tokens_after
    if saved <= 0:
        return False
    kwargs = {f"{cache_tier}_tokens_avoided": saved}
    cost = cache_aware_savings(model, **kwargs)
    event = {
        "v": SCHEMA_VERSION,
        "ts": time.time(),
        "before": tokens_before,
        "after": tokens_after,
        "saved": saved,
        "cost_usd": round(cost.dollars, 6),
        "cost_label": cost.label,
        "cache_tier": cache_tier,
        "model": model,
        "client": client,
        "source": source,
    }
    try:
        with ledger_path().open("a") as f:
            f.write(json.dumps(event, separators=(",", ":")) + "\n")
        return True
    except OSError:
        return False


@dataclass
class Aggregate:
    events: int = 0
    tokens_saved: int = 0
    tokens_before: int = 0
    cost_usd: float = 0.0
    by_model: dict[str, int] = field(default_factory=dict)
    by_client: dict[str, int] = field(default_factory=dict)

    @property
    def savings_percent(self) -> float:
        return 100.0 * self.tokens_saved / self.tokens_before if self.tokens_before else 0.0


def aggregate(window_days: float | None = None) -> Aggregate:
    path = ledger_path()
    agg = Aggregate()
    if not path.exists():
        return agg
    cutoff = time.time() - (window_days or RETENTION_DAYS) * 86400
    try:
        with path.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if e.get("ts", 0) < cutoff:
                    continue
                agg.events += 1
                agg.tokens_saved += e.get("saved", 0)
                agg.tokens_before += e.get("before", 0)
                agg.cost_usd += e.get("cost_usd", 0.0)
                agg.by_model[e.get("model", "unknown")] = (
                    agg.by_model.get(e.get("model", "unknown"), 0) + e.get("saved", 0)
                )
                agg.by_client[e.get("client", "unknown")] = (
                    agg.by_client.get(e.get("client", "unknown"), 0) + e.get("saved", 0)
                )
    except OSError:
        pass
    return agg
