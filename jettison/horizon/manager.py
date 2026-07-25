"""Horizon Manager: keep long sessions from re-billing everything forever.

Shapes oversized tool results and file-content arguments, replacing the
body with a compact, retrievable placeholder.

The transform is applied at **every** position in the conversation, and
identically each time. That is the cache-safety rule here
(docs/CACHE_SAFETY.md): the client never sees our rewriting, so it replays
the original bytes every turn. Shaping only the newest turn sent the
provider a shaped body once and originals thereafter, mismatching the
cached prefix and forcing a full re-cache on every subsequent turn —
measured live, that doubled cache-write tokens and turned a 27% token
saving into a 36% cost increase. Determinism is what makes this safe:
placeholders are a pure function of content, and the shape/skip decision
is frozen on first sight.

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

# Argument fields that carry file *content* — the only ones safe to hold
# out, because the write has already landed on disk. Paths, commands,
# patterns and every other field are left alone: they are what the call
# means, and shortening them would change behaviour.
CONTENT_ARG_FIELDS = ("content", "new_string", "new_str", "file_text", "text")


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
    # content hash -> whether we shape it. Frozen on first sight: the
    # economics depend on remaining turns, which changes every request, so
    # re-deciding would emit different bytes for the same content and break
    # the prefix cache. See shape_messages.
    decisions: dict[str, bool] = field(default_factory=dict)

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
    def _placeholder(self, text: str, key: str, tokens: int, kind: str = "tool output") -> str:
        head = text[:HEAD_CHARS]
        tail = text[-TAIL_CHARS:] if len(text) > HEAD_CHARS + TAIL_CHARS else ""
        body = head + ("\n…\n" + tail if tail else "")
        # The key sits immediately before the closing bracket, never mid
        # sentence: both the model and our own tooling have to pull it back
        # out unambiguously.
        return (
            f"{body}\n"
            f"[jettison: {tokens:,} tokens of {kind} held out of context to keep this "
            f"session cheap. The full text is unchanged on disk; retrieve it here by "
            f"calling {RETRIEVE_TOOL} with key={key}]"
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
        self,
        text: str,
        remaining_turns: int,
        stats: HorizonStats,
        kind: str = "tool output",
    ) -> tuple[str, ShapeDecision]:
        content_key = hashlib.sha256(text.encode(errors="replace")).hexdigest()[:12]
        tokens = count_text(text, self.model).tokens

        prior = self.decisions.get(content_key)
        if prior is False:
            return text, ShapeDecision(False, "previously declined; decision is frozen", 0.0, 0)
        if prior is True:
            decision = ShapeDecision(True, "previously shaped; decision is frozen", 0.0, 0)
        else:
            decision = evaluate_shape(tokens, remaining_turns, self.model)
            if not decision.should_shape:
                self.decisions[content_key] = False
                stats.skipped_value += 1
                return text, decision

        key = self._remember(text, tokens)
        placeholder = self._placeholder(text, key, tokens, kind)
        if not self._preserves_commitments(text, placeholder):
            self.decisions[content_key] = False
            stats.skipped_commitments += 1
            return text, ShapeDecision(False, "would drop a commitment", 0.0, 0)
        self.decisions[content_key] = True

        stats.shaped += 1
        stats.tokens_freed += decision.tokens_freed
        stats.projected_usd += decision.projected_usd
        return placeholder, decision

    # -- tool-call arguments --------------------------------------------
    def shape_tool_call_args(
        self, message: dict[str, Any], provider: str, remaining_turns: int, stats: HorizonStats
    ) -> None:
        """Shape oversized file-content *arguments* of tool calls.

        Measured on 101 real sessions, tool-call arguments are the single
        largest category of resident cost — larger than tool results — and
        Write/Edit are two thirds of it, because the full text of every
        file the agent writes stays in the conversation for the rest of the
        session.

        That text is uniquely safe to hold out: the write already happened,
        so the content is on disk. The agent can re-read the file, or pull
        the exact bytes back with the retrieve meta-tool. Only argument
        fields that carry file *content* are touched — never paths,
        commands, patterns or any other field, because those are what the
        call means.
        """
        content = message.get("content")
        blocks = content if isinstance(content, list) else []
        for block in blocks:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            args = block.get("input")
            if not isinstance(args, dict):
                continue
            for field_name in CONTENT_ARG_FIELDS:
                value = args.get(field_name)
                if not isinstance(value, str):
                    continue
                shaped, decision = self.shape_result(
                    value, remaining_turns, stats, kind="written file content"
                )
                if decision.should_shape:
                    args[field_name] = shaped

    # -- request integration --------------------------------------------
    def shape_messages(
        self, body: dict[str, Any], provider: str, remaining_turns: int
    ) -> HorizonStats:
        """Shape oversized tool results and file-content arguments, everywhere.

        This applies to the WHOLE message list, not just the newest turn,
        and that is a cache-safety requirement rather than a violation of
        one. The client never sees our shaping — we rewrite on the way out —
        so it replays the original bytes on every subsequent request. Shaping
        only the newest turn therefore sent the provider a shaped body once
        and the original forever after, mismatching the cached prefix and
        forcing a full re-cache every turn. Measured live, that roughly
        doubled cache-write tokens and turned a 27% token saving into a 36%
        cost *increase*.

        Applying the same deterministic transform at every position keeps the
        bytes we send byte-identical turn over turn, which is what the
        provider cache actually requires. Determinism is load-bearing:
        placeholders derive purely from content (hash-keyed), and the
        shape/skip decision is frozen on first sight in `decisions` because
        the economics depend on remaining turns, which changes per request.
        """
        stats = HorizonStats()
        messages = body.get("messages")
        if not isinstance(messages, list):
            return stats

        for msg in messages:
            if not isinstance(msg, dict):
                continue
            role = msg.get("role")
            content = msg.get("content")

            if role == "assistant":
                self.shape_tool_call_args(msg, provider, remaining_turns, stats)
                continue

            if provider == "anthropic":
                if role != "user" or not isinstance(content, list):
                    continue
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
                if role == "tool" and isinstance(content, str):
                    shaped, _ = self.shape_result(content, remaining_turns, stats)
                    msg["content"] = shaped

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
