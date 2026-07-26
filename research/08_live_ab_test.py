"""Analyze a live A/B run: identical coding tasks, direct vs through Jettison.

Unlike the replay scripts, this measures real Claude Code sessions doing
real work. Each run's token usage and cost are taken from Claude Code's own
`--output-format json` telemetry, not from our estimates, so the comparison
is independent of Jettison's accounting.

Usage: python research/08_live_ab_test.py <results_dir>
Expects task<i>_direct.json and task<i>_jettison.json per task.
"""

import json
import statistics
import sys
from pathlib import Path

results = Path(sys.argv[1] if len(sys.argv) > 1 else "ab/results")


def load(p: Path) -> dict | None:
    try:
        return json.loads(p.read_text(), strict=False)
    except Exception:
        return None


def tokens(d: dict) -> dict:
    """Session totals, from `modelUsage`.

    The top-level `usage` block reports only the FINAL request of the
    session, while `total_cost_usd` is the session total. Comparing the two
    is apples to oranges and silently corrupted every earlier measurement —
    one task showed 89% "fewer tokens" alongside a 40% cost increase, which
    is arithmetically impossible and is what exposed the error. `modelUsage`
    aggregates across the whole session, including subagents.
    """
    mu = d.get("modelUsage") or {}
    cr = cw = fi = out = 0
    for stats in mu.values():
        if not isinstance(stats, dict):
            continue
        cr += stats.get("cacheReadInputTokens", 0) or 0
        cw += stats.get("cacheCreationInputTokens", 0) or 0
        fi += stats.get("inputTokens", 0) or 0
        out += stats.get("outputTokens", 0) or 0
    if not mu:  # older captures without modelUsage
        u = d.get("usage") or {}
        cr = u.get("cache_read_input_tokens", 0) or 0
        cw = u.get("cache_creation_input_tokens", 0) or 0
        fi = u.get("input_tokens", 0) or 0
        out = u.get("output_tokens", 0) or 0
    return {"cache_read": cr, "cache_write": cw, "input": fi, "output": out,
            "total_input": cr + cw + fi}


rows = []
for i in range(50):
    a, b = load(results / f"task{i}_direct.json"), load(results / f"task{i}_jettison.json")
    if not a or not b:
        continue
    ta, tb = tokens(a), tokens(b)
    rows.append({
        "task": i,
        "d_err": bool(a.get("is_error")), "j_err": bool(b.get("is_error")),
        "d_cost": a.get("total_cost_usd", 0.0), "j_cost": b.get("total_cost_usd", 0.0),
        "d_turns": a.get("num_turns", 0), "j_turns": b.get("num_turns", 0),
        "d_ms": a.get("duration_ms", 0), "j_ms": b.get("duration_ms", 0),
        "d": ta, "j": tb,
    })

if not rows:
    print(f"no paired results in {results}")
    raise SystemExit(1)

ok = [r for r in rows if not r["d_err"] and not r["j_err"]]
print(f"paired tasks: {len(rows)}   both arms succeeded: {len(ok)}")
failed = [r for r in rows if r["d_err"] or r["j_err"]]
for r in failed:
    print(f"  task{r['task']}: direct_error={r['d_err']} jettison_error={r['j_err']}")

print(f"\n{'task':>4} {'direct $':>9} {'jettison $':>11} {'saved':>8} "
      f"{'direct in-tok':>14} {'jettison in-tok':>16} {'saved':>8}")
d_cost = j_cost = d_tok = j_tok = 0.0
for r in ok:
    dt, jt = r["d"]["total_input"], r["j"]["total_input"]
    d_cost += r["d_cost"]; j_cost += r["j_cost"]; d_tok += dt; j_tok += jt
    pct_c = 100 * (r["d_cost"] - r["j_cost"]) / r["d_cost"] if r["d_cost"] else 0
    pct_t = 100 * (dt - jt) / dt if dt else 0
    print(f"{r['task']:>4} {r['d_cost']:>9.4f} {r['j_cost']:>11.4f} {pct_c:>7.1f}% "
          f"{dt:>14,} {jt:>16,} {pct_t:>7.1f}%")

print(f"\n{'TOTAL':>4} {d_cost:>9.4f} {j_cost:>11.4f} "
      f"{100*(d_cost-j_cost)/d_cost if d_cost else 0:>7.1f}% "
      f"{d_tok:>14,.0f} {j_tok:>16,.0f} "
      f"{100*(d_tok-j_tok)/d_tok if d_tok else 0:>7.1f}%")

if len(ok) > 1:
    per = [100 * (r["d_cost"] - r["j_cost"]) / r["d_cost"] for r in ok if r["d_cost"]]
    mean = statistics.mean(per)
    sd = statistics.stdev(per)
    half = 1.96 * sd / (len(per) ** 0.5)
    print(f"\nper-task cost saving: mean {mean:.1f}%  sd {sd:.1f}  "
          f"95% CI [{mean-half:.1f}%, {mean+half:.1f}%]  n={len(per)}")
    print("(wide CI is expected: the agent is non-deterministic, so each pair "
          "differs in which files it reads and writes)")

print(f"\n{'':>4} {'cache_read':>14} {'cache_write':>13} {'output':>10} {'turns':>7} {'sec':>7}")
for arm, key in (("direct", "d"), ("jettison", "j")):
    cr = sum(r[key]["cache_read"] for r in ok)
    cw = sum(r[key]["cache_write"] for r in ok)
    out = sum(r[key]["output"] for r in ok)
    tn = sum(r[f"{key}_turns"] for r in ok)
    ms = sum(r[f"{key}_ms"] for r in ok)
    print(f"{arm:>4} {cr:>14,} {cw:>13,} {out:>10,} {tn:>7} {ms/1000:>7.0f}")
