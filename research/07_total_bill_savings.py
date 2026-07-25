"""What Jettison saves as a share of the REAL bill.

This is the headline number and the one most easily overstated. Savings
measured against "resident content cost" are a share of a *slice*; this
script prices the actual four billing tiers from real usage records and
reports savings against their sum.

Run: .venv/bin/python research/07_total_bill_savings.py
Reads ~/.claude/projects/**/*.jsonl read-only. Prints aggregates only.
"""

import json
from pathlib import Path

from jettison.horizon.economics import evaluate_shape
from jettison.horizon.manager import CONTENT_ARG_FIELDS
from jettison.pricing import get_price

P = get_price("claude-sonnet-4-5")
READ = P.cache_read_per_m / 1e6
WRITE = P.cache_write_per_m / 1e6
INP = P.input_per_m / 1e6
OUT = P.output_per_m / 1e6
ROOT = Path.home() / ".claude" / "projects"

cr = cw = fi = out = 0
saved_tt = 0
shaped_tokens = 0

for path in sorted(ROOT.rglob("*.jsonl")):
    ev = []
    n_turns = 0
    turn = -1
    for line in path.read_text(errors="replace").splitlines():
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        m = d.get("message")
        if not isinstance(m, dict):
            continue
        if d.get("type") == "assistant":
            u = m.get("usage") or {}
            a = u.get("cache_read_input_tokens", 0) or 0
            b = u.get("cache_creation_input_tokens", 0) or 0
            c_ = u.get("input_tokens", 0) or 0
            o = u.get("output_tokens", 0) or 0
            cr += a
            cw += b
            fi += c_
            out += o
            if a or b or c_:
                n_turns += 1
                turn = n_turns - 1
            cc = m.get("content")
            if isinstance(cc, list):
                for bl in cc:
                    if isinstance(bl, dict) and bl.get("type") == "tool_use":
                        args = bl.get("input") or {}
                        for f in CONTENT_ARG_FIELDS:
                            v = args.get(f)
                            if isinstance(v, str):
                                ev.append((turn, len(v) // 4))
        elif d.get("type") == "user":
            cc = m.get("content")
            if isinstance(cc, list):
                for bl in cc:
                    if isinstance(bl, dict) and bl.get("type") == "tool_result":
                        inn = bl.get("content")
                        if isinstance(inn, str):
                            n = len(inn) // 4
                        elif isinstance(inn, list):
                            n = sum(len(x.get("text", "")) // 4 for x in inn if isinstance(x, dict))
                        else:
                            n = 0
                        ev.append((turn, n))
    if n_turns < 5:
        continue
    for t, n in ev:
        if t < 0 or n <= 0:
            continue
        rem = n_turns - t
        d = evaluate_shape(n, rem)
        if d.should_shape:
            saved_tt += d.tokens_freed * rem
            shaped_tokens += d.tokens_freed

total = cr * READ + cw * WRITE + fi * INP + out * OUT
save_read = saved_tt * READ
save_write = shaped_tokens * WRITE

print(f"ACTUAL BILL           ${total:,.2f}")
print(f"  cache read  {cr:>15,}  ${cr * READ:>8.2f}")
print(f"  cache write {cw:>15,}  ${cw * WRITE:>8.2f}")
print(f"  output      {out:>15,}  ${out * OUT:>8.2f}")
print(f"  fresh input {fi:>15,}  ${fi * INP:>8.2f}")
print("\nJETTISON SAVES")
print(f"  fewer cache reads   ${save_read:>8.2f}   ({saved_tt:,} token-turns)")
print(f"  fewer cache writes  ${save_write:>8.2f}   ({shaped_tokens:,} tokens never cached)")
print(
    f"  TOTAL               ${save_read + save_write:>8.2f}"
    f"  = {100 * (save_read + save_write) / total:.1f}% OF THE REAL BILL"
)
print(f"\n  output tokens ({100 * out * OUT / total:.0f}% of bill) are untouched")
