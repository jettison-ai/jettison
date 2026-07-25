"""`jettison share` — a savings receipt people actually want to paste."""

from __future__ import annotations

from jettison.savings.report import collect


def render_share(as_md: bool = False) -> None:
    data = collect()
    week = data["jettison"]["last_7_days"]
    q = data["quality"]
    tokens = week["tokens_saved"]
    pct = week["savings_percent"]

    if not week["events"]:
        print("No optimized requests recorded yet — run `jettison wrap <client>` first.")
        return

    if as_md:
        print(
            f"[![jettison](https://img.shields.io/badge/jettison-"
            f"{tokens:,}%20tokens%20saved%20this%20week-blue)](https://github.com/jettison-ai/jettison)\n"
        )
        print(
            f"> 🪂 This repo saved **{tokens:,} AI tokens** ({pct}%) this week with "
            f"[Jettison](https://github.com/jettison-ai/jettison) — verified task parity, "
            f"{q['fallback_rate_percent']}% fallback rate."
        )
        return

    bar = "█" * min(40, max(1, int(pct * 0.4)))
    print(
        "\n┌────────────────────────── jettison receipt ──────────────────────────┐"
    )
    print(f"  This setup saved {tokens:>12,} tokens this week  ({pct}% of standing context)")
    print(f"  ≈ ${week['cost_usd']:.2f} avoided · verified task parity · fallback {q['fallback_rate_percent']}%")
    print(f"  {bar}")
    print("  jettison audit → see your own number in 30 seconds")
    print(
        "└───────────────────────────────────────────────────────────────────────┘\n"
    )
