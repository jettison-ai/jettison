"""Horizon Manager: keep long sessions from re-billing everything forever.

Shapes oversized tool results **in the newest turn only**, replacing the
body with a compact, retrievable placeholder. Newest-turn-only is not a
simplification — it is the cache-safety rule (docs/CACHE_SAFETY.md): the
newest turn is not yet in any provider cache, so rewriting it costs
nothing, while rewriting history would force a cache-write at ~12.5x the
read rate.

Nothing is destroyed. Originals are held locally and can be pulled back
with the `jettison_retrieve_content` meta-tool, so the model can always
recover what was shaped — the same fail-safe reversibility Headroom's CCR
provides for its own compression.

Every shaping decision is checked by the Commitment Verifier first: if the
placeholder would drop a commitment the original made (a path, a number, a
security rule, an error code), the result is left untouched.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from jettison.horizon.economics import ShapeDecision, evaluate_shape
from jettison.tokens import DEFAULT_MODEL, count_text
from jettison.verifier.commitments import extract_text_commitments

RETRIEVE_TOOL = "jettison_retrieve_content"

# How much of the original to keep inline. Head carries structure (imports,
# signatures, headers); tail carries recent/most-referenced content.
HEAD_CHARS = 400
TAIL_CHARS = 200


@dataclass
class ShapedContent:
    key: str
    original: str
    tokens: int


@dataclass
class HorizonStats:
    shaped: int = 0
    tokens_freed: int = 0
    projected_usd: float = 0.0
    skipped_commitments: int = 0
    skipped_value: int = 0


@dataclass
class HorizonManager:
    """Per-process store of shaped content, keyed by content hash."""

    model: str = DEFAULT_MODEL
    store: dict[str, ShapedContent] = field(default_factory=dict)
    max_entries: int = 512

    # -- retrieval -------------------------------------------------------
    def retrieve(self, key: str) -> str | None:
        entry = self.store.get(key)
        return entry.original if entry else None

    def _remember(self, text: str, tokens: int) -> str:
        key = hashlib.sha256(text.encode(errors="replace")).hexdigest()[:12]
        if key not in self.store:
            if len(self.store) >= self.max_entries:
                self.store.pop(next(iter(self.store)))
            self.store[key] = ShapedContent(key=key, original=text, tokens=tokens)
        return key

    # -- shaping ---------------------------------------------------------
    def _placeholder(self, text: str, key: str, tokens: int) -> str:
        head = text[:HEAD_CHARS]
        tail = text[-TAIL_CHARS:] if len(text) > HEAD_CHARS + TAIL_CHARS else ""
        body = head + ("\n…\n" + tail if tail else "")
        # The key sits immediately before the closing bracket, never mid
        # sentence: both the model and our own tooling have to pull it back
        # out unambiguously.
        return (
            f"{body}\n"
            f"[jettison: {tokens:,} tokens held out of context to keep this session cheap. "
            f"Retrieve the full content by calling {RETRIEVE_TOOL} with key={key}]"
        )

    def _preserves_commitments(self, original: str, placeholder: str) -> bool:
        """Refuse to shape when the placeholder would drop a commitment.

        Deliberately strict: tool output is where paths, error codes and
        exact values live, and a silently dropped one changes answers.
        """
        for c in extract_text_commitments(original, source="tool_result"):
            if c.span not in placeholder:
                return False
        return True

    def shape_result(
        self, text: str, remaining_turns: int, stats: HorizonStats
    ) -> tuple[str, ShapeDecision]:
        tokens = count_text(text, self.model).tokens
        decision = evaluate_shape(tokens, remaining_turns, self.model)
        if not decision.should_shape:
            stats.skipped_value += 1
            return text, decision

        key = self._remember(text, tokens)
        placeholder = self._placeholder(text, key, tokens)
        if not self._preserves_commitments(text, placeholder):
            stats.skipped_commitments += 1
            return text, ShapeDecision(False, "would drop a commitment", 0.0, 0)

        stats.shaped += 1
        stats.tokens_freed += decision.tokens_freed
        stats.projected_usd += decision.projected_usd
        return placeholder, decision

    # -- request integration --------------------------------------------
    def shape_newest_turn(
        self, body: dict[str, Any], provider: str, remaining_turns: int
    ) -> HorizonStats:
        """Rewrite oversized tool results in the final message only.

        Walking backwards and stopping at the first non-tool_result message
        keeps us strictly inside the turn the client just produced, which is
        the only part of the request no provider has cached yet.
        """
        stats = HorizonStats()
        messages = body.get("messages")
        if not isinstance(messages, list) or not messages:
            return stats

        for msg in reversed(messages):
            if not isinstance(msg, dict):
                break
            content = msg.get("content")
            if provider == "anthropic":
                if msg.get("role") != "user" or not isinstance(content, list):
                    break
                if not any(
                    isinstance(b, dict) and b.get("type") == "tool_result" for b in content
                ):
                    break
                for block in content:
                    if not isinstance(block, dict) or block.get("type") != "tool_result":
                        continue
                    inner = block.get("content")
                    if isinstance(inner, str):
                        shaped, _ = self.shape_result(inner, remaining_turns, stats)
                        block["content"] = shaped
                    elif isinstance(inner, list):
                        for part in inner:
                            if isinstance(part, dict) and part.get("type") == "text":
                                shaped, _ = self.shape_result(
                                    part.get("text", ""), remaining_turns, stats
                                )
                                part["text"] = shaped
            else:
                if msg.get("role") != "tool" or not isinstance(content, str):
                    break
                shaped, _ = self.shape_result(content, remaining_turns, stats)
                msg["content"] = shaped
            break  # newest turn only

        return stats


def retrieve_tool_def(provider: str) -> dict[str, Any]:
    d = {
        "name": RETRIEVE_TOOL,
        "description": (
            "Retrieve the full content of a tool result that was held out of "
            "context. Use the key shown in the [jettison: …] marker."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"key": {"type": "string", "description": "The key from the marker."}},
            "required": ["key"],
        },
    }
    if provider == "openai":
        return json.loads(
            json.dumps(
                {
                    "type": "function",
                    "function": {
                        "name": d["name"],
                        "description": d["description"],
                        "parameters": d["input_schema"],
                    },
                },
                sort_keys=True,
            )
        )
    return json.loads(json.dumps(d, sort_keys=True))
