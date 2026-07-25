"""What is the maximum a context optimizer could save a mainstream user?

Reconstructs each real session turn by turn and prices what the resident
context is made of in token-turns (tokens x turns resident). That
upper-bounds any optimizer: you cannot save more than a category costs.
"""

import json
from collections import Counter
from pathlib import Path

from jettison.pricing import get_price

ROOT = Path.home() / ".claude" / "projects"
P = get_price("claude-sonnet-4-5")
READ = P.cache_read_per_m / 1e6
BUCKET_MIN = {"<500": 0, "500-2k": 500, "2k-8k": 2000, "8k-20k": 8000, ">20k": 20000}


def tok(s: str) -> int:
    return len(s) // 4


tt = Counter()
size_buckets = Counter()
sessions = 0
grand_tt = 0

for path in sorted(ROOT.rglob("*.jsonl")):
    events = []
    pending = {}
    turn = -1
    n_turns = 0
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
            if u.get("cache_read_input_tokens") or u.get("input_tokens") or u.get("cache_creation_input_tokens"):
                n_turns += 1
                turn = n_turns - 1
            c = m.get("content")
            if isinstance(c, list):
                for b in c:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "text":
                        events.append((turn, "assistant text", tok(b.get("text", ""))))
                    elif b.get("type") == "thinking":
                        events.append((turn, "thinking", tok(b.get("thinking", ""))))
                    elif b.get("type") == "tool_use":
                        pending[b.get("id")] = b.get("name")
                        events.append((turn, "tool call args", tok(json.dumps(b.get("input", {})))))
        elif d.get("type") == "user":
            c = m.get("content")
            if isinstance(c, str):
                events.append((turn, "user text", tok(c)))
            elif isinstance(c, list):
                for b in c:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "text":
                        events.append((turn, "user text", tok(b.get("text", ""))))
                    elif b.get("type") == "tool_result":
                        inner = b.get("content")
                        if isinstance(inner, str):
                            n = tok(inner)
                        elif isinstance(inner, list):
                            n = sum(tok(x.get("text", "")) for x in inner if isinstance(x, dict))
                        else:
                            n = tok(json.dumps(inner or ""))
                        events.append((turn, f"tool_result:{pending.get(b.get('tool_use_id'), '?')}", n))

    if n_turns < 5:
        continue
    sessions += 1
    for t, cat, n in events:
        if t < 0 or n <= 0:
            continue
        cost = n * (n_turns - t)
        grand_tt += cost
        base = cat.split(":")[0]
        key = "TOOL RESULTS" if base == "tool_result" else cat
        tt[key] += cost
        if base == "tool_result":
            b = ("<500" if n < 500 else "500-2k" if n < 2000 else "2k-8k" if n < 8000
                 else "8k-20k" if n < 20000 else ">20k")
            size_buckets[b] += cost

print(f"sessions: {sessions}   resident cost: {grand_tt:,} token-turns (${grand_tt*READ:,.2f})\n")
print(f"{'category':22} {'token-turns':>16} {'share':>7} {'$':>9}")
for cat, v in tt.most_common():
    print(f"  {cat:20} {v:>16,} {100*v/grand_tt:>6.1f}% ${v*READ:>8.2f}")

tr = sum(size_buckets.values()) or 1
print(f"\nTOOL RESULTS by size ({100*tr/grand_tt:.1f}% of all resident cost)")
for b in ("<500", "500-2k", "2k-8k", "8k-20k", ">20k"):
    v = size_buckets[b]
    print(f"  {b:8} {v:>16,} {100*v/tr:>6.1f}% of tool cost   ${v*READ:>8.2f}")

print(f"\nCEILING — shaping tool results at 80% size cut:")
for thr, label in ((20000, ">20k only"), (8000, ">8k"), (2000, ">2k (shipped today)"),
                   (500, ">500"), (0, "every tool result")):
    addressable = sum(v for b, v in size_buckets.items() if BUCKET_MIN[b] >= thr)
    saved = addressable * 0.8
    print(f"  {label:22} -> ${saved*READ:>8.2f}  = {100*saved/grand_tt:>4.1f}% of the input bill")
