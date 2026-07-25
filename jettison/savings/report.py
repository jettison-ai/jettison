"""`jettison savings` rendering: Jettison + Headroom ledgers combined,
cache-aware dollars, fallback rate, measured/estimated labels, export."""

from __future__ import annotations

import csv
import json
import time
from pathlib import Path

from jettison.savings import ledger
from jettison.verifier import fallback_rate, read_records


def _headroom_lifetime() -> dict | None:
    """Pull Headroom's runtime-compression savings when its ledger exists."""
    try:
        from headroom.savings_ledger import aggregate_savings

        report = aggregate_savings()
        life = report.lifetime if hasattr(report, "lifetime") else None
        if life is None:
            return None
        d = life.to_dict() if hasattr(life, "to_dict") else dict(life)
        return d if d.get("calls") else None
    except Exception:
        return None


def collect() -> dict:
    week = ledger.aggregate(window_days=7)
    life = ledger.aggregate()
    records = read_records()
    hr = _headroom_lifetime()
    data = {
        "jettison": {
            "last_7_days": {
                "tokens_saved": week.tokens_saved,
                "tokens_before": week.tokens_before,
                "savings_percent": round(week.savings_percent, 1),
                "cost_usd": round(week.cost_usd, 4),
                "events": week.events,
            },
            "lifetime": {
                "tokens_saved": life.tokens_saved,
                "tokens_before": life.tokens_before,
                "savings_percent": round(life.savings_percent, 1),
                "cost_usd": round(life.cost_usd, 4),
                "events": life.events,
                "by_model": life.by_model,
                "by_client": life.by_client,
            },
            "cost_note": "dollars priced at the cache tier avoided tokens would have billed at (see docs/CACHE_SAFETY.md)",
        },
        "quality": {
            "requests_audited": len(records),
            "fallback_rate_percent": round(100 * fallback_rate(records), 2),
            "commitments_checked": sum(r.get("commitments_checked", 0) for r in records),
            "reinflations": sum(1 for r in records if r.get("reinflated")),
        },
        "headroom_runtime_compression": hr or "no headroom ledger found",
        "labels": "cost figures are 'measured' when provider pricing resolved, else 'estimated'",
    }
    return data


def render_savings(as_json: bool = False, export_path: str | None = None) -> None:
    from rich.console import Console

    data = collect()
    if export_path:
        _export(data, export_path)

    if as_json:
        print(json.dumps(data, indent=2))
        return

    console = Console()
    j = data["jettison"]
    q = data["quality"]
    console.print("\n[bold]Jettison savings[/bold] [dim](standing context)[/dim]")
    for window in ("last_7_days", "lifetime"):
        w = j[window]
        if not w["events"]:
            console.print(f"  {window.replace('_', ' ')}: [dim]no optimized requests yet[/dim]")
            continue
        console.print(
            f"  {window.replace('_', ' ')}: [green]{w['tokens_saved']:,}[/green] tokens avoided "
            f"({w['savings_percent']}% of {w['tokens_before']:,}) ≈ ${w['cost_usd']:.2f} "
            f"across {w['events']} requests"
        )
    console.print(
        f"\n[bold]Quality[/bold]: {q['requests_audited']} requests audited, "
        f"fallback rate [{'green' if q['fallback_rate_percent'] < 3 else 'yellow'}]"
        f"{q['fallback_rate_percent']}%[/] "
        f"({q['reinflations']} re-inflations / {q['commitments_checked']} commitments checked)"
    )
    hr = data["headroom_runtime_compression"]
    if isinstance(hr, dict):
        console.print(
            f"\n[bold]Headroom runtime compression[/bold] (retained, attributed): "
            f"{hr.get('tokens_saved', 0):,} tokens, ${hr.get('cost_usd', 0):.2f}"
        )
    console.print(f"\n[dim]{data['labels']}[/dim]\n")


def _export(data: dict, path: str) -> None:
    p = Path(path)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    if p.suffix.lower() == ".csv":
        rows = []
        for window in ("last_7_days", "lifetime"):
            w = data["jettison"][window]
            rows.append(
                {
                    "window": window,
                    "tokens_saved": w["tokens_saved"],
                    "tokens_before": w["tokens_before"],
                    "savings_percent": w["savings_percent"],
                    "cost_usd": w["cost_usd"],
                    "events": w["events"],
                    "fallback_rate_percent": data["quality"]["fallback_rate_percent"],
                    "exported_at": stamp,
                }
            )
        with p.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
    else:
        payload = {"exported_at": stamp, **data}
        p.write_text(json.dumps(payload, indent=2))
    print(f"exported -> {p}")
