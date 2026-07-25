"""Expired-context elision.

The Horizon Manager's first design shaped content by *size*, which
measured -74% on real coding tasks: the agent re-fetched what we hid,
because the context we removed was still live working memory. The
literature points the other way — AgentDiet (Xiao et al. 2025) reports
39.9-59.7% input reduction and 21.1-35.9% total cost reduction by
removing *expired* information, and SWE-Pruner (Wang et al. 2026) finds
23-54% reduction with success rates going slightly **up**. The recurring
result across that work is that removing redundant, expired or
non-actionable content preserves or improves task success.

So this module removes only content that is provably dead — where
referring to it would be a bug, not a saving:

  superseded_read   the agent read file X, then later wrote or edited X.
                    The earlier copy no longer describes the file. An
                    agent acting on it would be acting on stale state.
  duplicate_read    a byte-identical re-read of the same file. Two
                    copies cannot both be needed.

Nothing live is ever touched, so there is nothing for the agent to
re-fetch — which is exactly why this can pay when size-based shaping
could not.

Cache discipline (learned the hard way, and from Headroom's prefix-freeze
design): removing content from the middle of a conversation invalidates
the provider cache from that point on, and cache-write costs ~12.5x
cache-read. Every elision is therefore gated on the break-even in
`economics.eviction_break_even_turns` — it must stay resident long enough
to repay its own re-cache — and once taken, a decision is permanent, so
the bytes we send never oscillate.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from jettison.horizon.economics import eviction_break_even_turns
from jettison.tokens import DEFAULT_MODEL, count_text

READ_TOOLS = {"Read", "read_file", "view"}
WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit", "create_file", "str_replace"}

# Below this an elision cannot repay a re-cache no matter how long it sits.
MIN_EXPIRABLE_TOKENS = 1_500


@dataclass
class ExpiryStats:
    superseded: int = 0
    duplicates: int = 0
    tokens_freed: int = 0
    skipped_break_even: int = 0

    @property
    def elided(self) -> int:
        return self.superseded + self.duplicates


@dataclass
class ExpiryElider:
    """Per-conversation record of what has been ruled expired.

    Decisions are sticky: once a read is expired it stays expired, so the
    outgoing bytes for a given turn stop changing after one transition.
    """

    model: str = DEFAULT_MODEL
    # tool_use_id -> the exact marker already sent. Storing the rendered
    # text, not just the id, is what makes replays byte-identical: the
    # reason string can differ between passes and that alone would move
    # the cached prefix.
    expired: dict[str, str] = field(default_factory=dict)

    def _marker(self, path: str, tokens: int, why: str) -> str:
        return (
            f"[jettison: {tokens:,} tokens of an earlier view of {path} removed — {why}. "
            f"Read the file again if you need its current contents.]"
        )

    def elide(
        self, body: dict[str, Any], provider: str, expected_turns: int = 30
    ) -> ExpiryStats:
        stats = ExpiryStats()
        messages = body.get("messages")
        if provider != "anthropic" or not isinstance(messages, list):
            return stats

        break_even = eviction_break_even_turns(self.model)

        # Pass 1: map tool_use ids to (tool, path) and record the first turn
        # index at which each file is written.
        calls: dict[str, tuple[str, str]] = {}
        first_write_at: dict[str, int] = {}
        for i, msg in enumerate(messages):
            if not isinstance(msg, dict) or msg.get("role") != "assistant":
                continue
            for block in msg.get("content") or []:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                name = block.get("name", "")
                args = block.get("input") or {}
                path = str(args.get("file_path") or args.get("path") or "")
                if not path:
                    continue
                calls[block.get("id", "")] = (name, path)
                if name in WRITE_TOOLS and path not in first_write_at:
                    first_write_at[path] = i

        # Pass 2: elide reads that a later write superseded, and exact
        # duplicate reads of the same file.
        seen_read: dict[tuple[str, str], int] = {}
        total = len(messages)
        for i, msg in enumerate(messages):
            if not isinstance(msg, dict) or msg.get("role") != "user":
                continue
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_result":
                    continue
                tool, path = calls.get(block.get("tool_use_id", ""), ("", ""))
                if tool not in READ_TOOLS or not path:
                    continue
                inner = block.get("content")
                if not isinstance(inner, str):
                    continue

                digest = hashlib.sha256(inner.encode(errors="replace")).hexdigest()[:12]
                marker_key = str(block.get("tool_use_id"))
                if marker_key in self.expired:
                    block["content"] = self.expired[marker_key]
                    continue

                tokens = count_text(inner, self.model).tokens
                if tokens < MIN_EXPIRABLE_TOKENS:
                    continue

                why = ""
                wrote_at = first_write_at.get(path)
                if wrote_at is not None and wrote_at > i:
                    why = "the agent edited this file afterwards"
                    kind = "superseded"
                elif (path, digest) in seen_read:
                    why = "an identical copy of this read is already in context"
                    kind = "duplicate"
                else:
                    seen_read[(path, digest)] = i
                    continue

                # Break-even: the freed tokens are saved on every remaining
                # turn, but re-caching the suffix costs ~12.5x one turn of
                # reads. Skip anything that cannot repay that.
                remaining = max(0, expected_turns - i)
                if remaining < break_even:
                    stats.skipped_break_even += 1
                    continue

                marker = self._marker(path, tokens, why)
                self.expired[marker_key] = marker
                block["content"] = marker
                stats.tokens_freed += tokens
                if kind == "superseded":
                    stats.superseded += 1
                else:
                    stats.duplicates += 1

        return stats
