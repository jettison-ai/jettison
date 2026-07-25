"""Does resident-context management pay for itself on real sessions?

Mutating conversation history invalidates the provider prefix cache from
the mutation point onward: you save cache-READ on every later turn but pay
one cache-WRITE for the rebuilt suffix. This replays real sessions to find
whether that trade is positive, and which strategy wins.

Strategies compared, per session:
  shape_new   compress large tool results as they ARRIVE (newest turn only).
              Cache-safe by construction: never touches a cached prefix.
  evict_old   drop tool results older than K turns, paying the re-cache cost.
"""

import json
from pathlib import Path

from jettison.pricing import get_price

ROOT = Path.home() / ".claude" / "projects"
P = get_price("claude-sonnet-4-5")
READ = P.cache_read_per_m / 1e6
WRITE = P.cache_write_per_m / 1e6

# Only results above this are worth touching at all.
BIG_RESULT_TOKENS = 2_000
# What a compressed placeholder costs (CCR marker + summary).
PLACEHOLDER_TOKENS = 60
# How many turns a tool result stays "live" before it is almost certainly
# not being referenced again.
EVICT_AFTER_TURNS = 12


def result_tokens(block) -> int:
    c = block.get("content")
    if isinstance(c, str):
        return len(c) // 4
    if isinstance(c, list):
        return sum(len(b.get("text", "")) for b in c if isinstance(b, dict)) // 4
    return len(json.dumps(c or "")) // 4


tot_baseline = tot_shape = tot_evict = 0.0
sessions = 0
shaped_items = evicted_items = 0

for path in sorted(ROOT.rglob("*.jsonl")):
    turns = []          # per assistant turn: billed input tokens
    events = []         # (turn_index, tokens) for big tool results
    pending = {}
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
            billed = (u.get("cache_read_input_tokens", 0) or 0) + \
                     (u.get("cache_creation_input_tokens", 0) or 0) + \
                     (u.get("input_tokens", 0) or 0)
            if billed:
                turns.append(billed)
                turn = len(turns) - 1
            c = m.get("content")
            if isinstance(c, list):
                for b in c:
                    if isinstance(b, dict) and b.get("type") == "tool_use":
                        pending[b.get("id")] = b.get("name")
        elif d.get("type") == "user":
            c = m.get("content")
            if isinstance(c, list):
                for b in c:
                    if isinstance(b, dict) and b.get("type") == "tool_result" and turn >= 0:
                        n = result_tokens(b)
                        if n >= BIG_RESULT_TOKENS:
                            events.append((turn, n))

    if len(turns) < 5 or not events:
        continue
    sessions += 1
    n_turns = len(turns)

    # Baseline: what the session actually cost on input.
    baseline = sum(t * READ for t in turns)
    tot_baseline += baseline

    # shape_new: a big result arriving at turn t is replaced by a placeholder,
    # so every turn AFTER t carries (n - placeholder) fewer tokens. The
    # arriving turn itself is not yet cached, so there is no re-cache cost.
    saved_shape = 0.0
    for t, n in events:
        remaining = n_turns - t - 1
        saved_shape += (n - PLACEHOLDER_TOKENS) * remaining * READ
        shaped_items += 1
    tot_shape += saved_shape

    # evict_old: at turn t + K we drop the result. We save on the turns after
    # that, but pay one cache-write for the suffix that must be re-cached.
    saved_evict = 0.0
    for t, n in events:
        evict_turn = t + EVICT_AFTER_TURNS
        if evict_turn >= n_turns - 1:
            continue
        remaining = n_turns - evict_turn - 1
        gain = (n - PLACEHOLDER_TOKENS) * remaining * READ
        # everything resident at eviction time after the drop point must be
        # rewritten once; approximate with that turn's billed size.
        cost = turns[evict_turn] * WRITE
        if gain > cost:
            saved_evict += gain - cost
            evicted_items += 1
    tot_evict += saved_evict

print(f"sessions with big tool results: {sessions}")
print(f"baseline input spend on those:  ${tot_baseline:,.2f}\n")
print(f"  shape-on-arrival (cache-safe): ${tot_shape:,.2f}  "
      f"= {100*tot_shape/tot_baseline:.1f}%   ({shaped_items:,} results shaped)")
print(f"  evict-old (pays re-cache):     ${tot_evict:,.2f}  "
      f"= {100*tot_evict/tot_baseline:.1f}%   ({evicted_items:,} evictions cleared break-even)")
print(f"\ncache-read ${READ*1e6:.2f}/M vs cache-write ${WRITE*1e6:.2f}/M "
      f"-> one eviction must save {WRITE/READ:.1f} turns of reads to pay for itself")
