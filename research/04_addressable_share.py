"""How much of real spend can Jettison actually address today?

Splits real Claude Code sessions into what the standing-context layer can
touch versus what the runtime layer can, and prices both at the tier they
actually bill at.
"""

import json
from collections import Counter, defaultdict
from pathlib import Path

from jettison.pricing import get_price

ROOT = Path.home() / ".claude" / "projects"
p = get_price("claude-sonnet-4-5")

# 1. How many MCP servers does this developer actually have?
cfg = json.loads((Path.home() / ".claude.json").read_text())
global_mcp = list((cfg.get("mcpServers") or {}).keys())
per_project = {
    k: list((v.get("mcpServers") or {}).keys())
    for k, v in (cfg.get("projects") or {}).items()
    if (v.get("mcpServers") or {})
}
print(f"MCP servers configured globally: {len(global_mcp)} {global_mcp}")
print(f"Projects with their own MCP servers: {len(per_project)}")
print(f"Total projects in config: {len(cfg.get('projects') or {})}")

# 2. Resident-context growth: cache reads are (resident context x turns).
cache_read = cache_write = fresh = out = 0
read_results = []          # (path, chars) for Read tool results
dup_bytes = 0
per_session_reads = defaultdict(Counter)

for path in sorted(ROOT.rglob("*.jsonl")):
    pending = {}
    sid = path.stem
    try:
        lines = path.read_text(errors="replace").splitlines()
    except OSError:
        continue
    for line in lines:
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        msg = d.get("message")
        if not isinstance(msg, dict):
            continue
        if d.get("type") == "assistant":
            u = msg.get("usage") or {}
            cache_read += u.get("cache_read_input_tokens", 0) or 0
            cache_write += u.get("cache_creation_input_tokens", 0) or 0
            fresh += u.get("input_tokens", 0) or 0
            out += u.get("output_tokens", 0) or 0
            c = msg.get("content")
            if isinstance(c, list):
                for b in c:
                    if isinstance(b, dict) and b.get("type") == "tool_use":
                        pending[b.get("id")] = (b.get("name"), b.get("input") or {})
        elif d.get("type") == "user":
            c = msg.get("content")
            if isinstance(c, list):
                for b in c:
                    if isinstance(b, dict) and b.get("type") == "tool_result":
                        name, args = pending.get(b.get("tool_use_id"), (None, {}))
                        if name != "Read":
                            continue
                        body = b.get("content")
                        n = len(body) if isinstance(body, str) else len(json.dumps(body or ""))
                        fp = str(args.get("file_path", "?"))
                        read_results.append((fp, n))
                        per_session_reads[sid][fp] += 1

# duplicate reads: same file read more than once in one session
dup_reads = 0
for sid, counter in per_session_reads.items():
    for fp, n in counter.items():
        if n > 1:
            dup_reads += n - 1
sizes = {}
for fp, n in read_results:
    sizes.setdefault(fp, n)
dup_bytes = sum(
    sizes.get(fp, 0) * (n - 1)
    for sid, c in per_session_reads.items()
    for fp, n in c.items()
    if n > 1
)

usd_total = (
    fresh * p.input_per_m + cache_read * p.cache_read_per_m + cache_write * p.cache_write_per_m
) / 1e6 + out * p.output_per_m / 1e6

print(f"\n{'='*66}\nSPEND: ${usd_total:,.2f}  (cache-read tokens: {cache_read:,})\n{'='*66}")

# --- Jettison standing-context layer, priced honestly ---
STANDING = 11_055          # measured median first-request input
requests = sum(1 for _ in read_results) or 1
# every turn re-reads the standing context out of cache
turns = 10_665
for pct in (0.5, 0.6, 0.85):
    saved_tok = int(STANDING * pct) * turns
    usd = saved_tok * p.cache_read_per_m / 1e6
    print(f"  standing context cut {pct*100:>4.0f}%  -> {saved_tok:>12,} tok  "
          f"${usd:>7.2f}  = {100*usd/usd_total:>4.1f}% of spend")

# --- runtime layer: Read output volume ---
read_bytes = sum(n for _, n in read_results)
read_tok = read_bytes // 4
print(f"\n  Read tool output total: {read_bytes:,} chars ≈ {read_tok:,} tokens "
      f"from {len(read_results):,} calls")
print(f"  duplicate re-reads in the same session: {dup_reads:,} calls, "
      f"≈{dup_bytes//4:,} tokens of pure repeat")
print(f"\n  Those bytes sit in context and are re-billed as cache reads on EVERY")
print(f"  later turn of the session — that is what makes cache reads {cache_read:,}.")
for pct in (0.3, 0.5, 0.7):
    # halving resident tool output roughly scales the cache-read volume it drives
    usd = cache_read * pct * p.cache_read_per_m / 1e6
    print(f"  cut resident context {pct*100:>4.0f}% -> ${usd:>8.2f}  "
          f"= {100*usd/usd_total:>4.1f}% of spend")
