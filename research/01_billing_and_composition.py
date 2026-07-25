"""Where do tokens actually go in real Claude Code sessions?

Reads local session transcripts read-only and reports the billing-tier
split plus what the conversation is actually made of. No content is
printed or transmitted — only aggregate sizes and tool names.
"""

import json
from collections import Counter
from pathlib import Path

from jettison.pricing import get_price
from jettison.tokens import count_text

ROOT = Path.home() / ".claude" / "projects"

fresh = cache_read = cache_write = output = 0
requests = 0
sessions = 0
first_req_inputs = []

# content composition
bytes_by_kind = Counter()
bytes_by_tool = Counter()
calls_by_tool = Counter()


def text_len(content) -> int:
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        n = 0
        for b in content:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "text":
                n += len(b.get("text", "") or "")
            elif b.get("type") == "thinking":
                n += len(b.get("thinking", "") or "")
            elif b.get("type") == "tool_use":
                n += len(json.dumps(b.get("input", {})))
            elif b.get("type") == "tool_result":
                c = b.get("content")
                n += len(c) if isinstance(c, str) else len(json.dumps(c or ""))
        return n
    return 0


for path in sorted(ROOT.rglob("*.jsonl")):
    sessions += 1
    seen_first = False
    pending_tool = {}  # tool_use_id -> tool name
    try:
        lines = path.read_text(errors="replace").splitlines()
    except OSError:
        continue
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        typ = d.get("type")
        msg = d.get("message")
        if not isinstance(msg, dict):
            continue

        if typ == "assistant":
            u = msg.get("usage") or {}
            i = u.get("input_tokens", 0) or 0
            cr = u.get("cache_read_input_tokens", 0) or 0
            cw = u.get("cache_creation_input_tokens", 0) or 0
            o = u.get("output_tokens", 0) or 0
            if i or cr or cw or o:
                requests += 1
                fresh += i
                cache_read += cr
                cache_write += cw
                output += o
                if not seen_first and (i + cr + cw) > 0:
                    first_req_inputs.append(i + cr + cw)
                    seen_first = True
            content = msg.get("content")
            bytes_by_kind["assistant text/thinking"] += text_len(
                [b for b in content if isinstance(b, dict) and b.get("type") in ("text", "thinking")]
                if isinstance(content, list) else content
            )
            if isinstance(content, list):
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "tool_use":
                        pending_tool[b.get("id")] = b.get("name", "?")
                        bytes_by_kind["tool call args"] += len(json.dumps(b.get("input", {})))
                        calls_by_tool[b.get("name", "?")] += 1

        elif typ == "user":
            content = msg.get("content")
            if isinstance(content, list):
                for b in content:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "tool_result":
                        c = b.get("content")
                        n = len(c) if isinstance(c, str) else len(json.dumps(c or ""))
                        bytes_by_kind["TOOL RESULTS"] += n
                        bytes_by_tool[pending_tool.get(b.get("tool_use_id"), "?")] += n
                    elif b.get("type") == "text":
                        bytes_by_kind["user text"] += len(b.get("text", "") or "")
            elif isinstance(content, str):
                bytes_by_kind["user text"] += len(content)

total_in = fresh + cache_read + cache_write
p = get_price("claude-sonnet-4-5")
usd_fresh = fresh * p.input_per_m / 1e6
usd_cr = cache_read * p.cache_read_per_m / 1e6
usd_cw = cache_write * p.cache_write_per_m / 1e6
usd_out = output * p.output_per_m / 1e6
usd_total = usd_fresh + usd_cr + usd_cw + usd_out

print(f"\n{'='*68}\nREAL CLAUDE CODE USAGE — {sessions} sessions, {requests:,} model requests\n{'='*68}")
print(f"\nINPUT TOKENS BY BILLING TIER")
for label, tok, usd in (
    ("fresh input (full price)", fresh, usd_fresh),
    ("cache READ (~0.1x)", cache_read, usd_cr),
    ("cache WRITE (1.25x)", cache_write, usd_cw),
):
    print(f"  {label:26} {tok:>14,}  {100*tok/total_in:>5.1f}%   ${usd:>8.2f}")
print(f"  {'output tokens':26} {output:>14,}  {'':>6}   ${usd_out:>8.2f}")
print(f"  {'TOTAL':26} {total_in:>14,}  {'':>6}   ${usd_total:>8.2f}")

print(f"\nWHAT THE CONTEXT IS MADE OF (characters of conversation content)")
tot_b = sum(bytes_by_kind.values()) or 1
for kind, n in bytes_by_kind.most_common():
    print(f"  {kind:26} {n:>14,}  {100*n/tot_b:>5.1f}%   ≈{count_text('x'*0).tokens + n//4:>10,} tok")

print(f"\nTOP TOOL-RESULT PRODUCERS (the stuff that fills your window)")
for tool, n in bytes_by_tool.most_common(12):
    print(f"  {tool:26} {n:>14,} chars  ≈{n//4:>9,} tok   ({calls_by_tool[tool]:,} calls)")

if first_req_inputs:
    first_req_inputs.sort()
    mid = first_req_inputs[len(first_req_inputs) // 2]
    print(f"\nSTANDING CONTEXT PROXY (first request of each session, median): {mid:,} tokens")
    print(f"  across {len(first_req_inputs)} sessions; min {first_req_inputs[0]:,} / max {first_req_inputs[-1]:,}")
