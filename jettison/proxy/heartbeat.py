"""OpenClaw heartbeat profile: minimal context for cache-warming turns.

OpenClaw pings the provider every ~5–55 minutes to keep the prompt cache
warm. Each ping is a full API call carrying the whole standing context,
so it bills like a real turn while asking for nothing.

What this module deliberately does NOT strip, and why
(docs/CACHE_SAFETY.md):

A heartbeat exists to make the provider re-serve *the exact prefix the
real turns use*. Prefix caching matches bytes from the start of the
request, so a heartbeat that dropped the capability index or the
compiled instructions would warm a *different* entry: the real prefix
would expire on schedule and every following real turn would pay a
cache-write. That is the dollar-pessimizer failure mode rule 1 exists to
prevent — token savings up, dollars down. The same argument rules out
dropping the tool catalog, which the task suggested as the fallback:
Anthropic serializes tools ahead of the system blocks, so a tools-free
heartbeat warms a tools-free prefix and leaves the real one to die.
Under Jettison the outbound catalog is the compact registry anyway — the
heartbeat's bytes are not there.

What IS safe is the tail. Nothing after the last cache breakpoint is
part of a warmed prefix, and truncating a suffix cannot change a prefix
under either explicit-breakpoint (Anthropic) or automatic (OpenAI)
caching. So a heartbeat keeps `system`, `tools` and every message up to
and including the last `cache_control` block byte-identical, and drops
only the uncached conversation tail it does not need — a turn whose
answer is discarded does not need history. Requests whose final message
carries a breakpoint therefore keep everything: by construction we drop
only what is provably outside the warmed prefix.

Detection is deterministic and biased hard toward precision: a real user
turn that got trimmed would lose conversation history, so a templated
message never fires on its own — the turn must also be shaped like a
machine ping (a token budget too small to answer with, or tools
explicitly switched off) or carry an explicit marker.
"""

from __future__ import annotations

import json
import re
from typing import Any

from jettison.tokens import count_text

MARKER_KEYS = ("jettison_heartbeat", "heartbeat", "keepalive")
MAX_HEARTBEAT_CHARS = 64
TINY_MAX_TOKENS = 16

_HEARTBEAT_TEXT = re.compile(
    r"^(?:heart\s?beat|keep\s?alive|cache\s?warm(?:ing|er)?|warm\s?cache|ping|noop|no\s?op)"
    r"[\s.!:_,-]*$"
)
_TRUTHY = frozenset({"1", "true", "yes", "on"})


def is_heartbeat(body: dict[str, Any], provider: str) -> bool:
    """True when this request is a cache-warming ping, not a real turn.

    `provider` is part of the contract for symmetry with the other body
    inspectors; every signal here happens to read the same on both wire
    formats.
    """
    if _explicit_marker(body):
        return True
    text = _final_user_text(body)
    if not text or len(text) > MAX_HEARTBEAT_CHARS:
        return False
    if not _HEARTBEAT_TEXT.match(text.strip().lower()):
        return False
    return _tiny_max_tokens(body) or _tools_switched_off(body)


def minimal_context_body(body: dict[str, Any]) -> dict[str, Any]:
    """Heartbeat-shaped copy of `body`: cached prefix byte-identical, the
    uncached conversation tail dropped.

    Returns `body` itself (same object) when nothing can be dropped
    safely — no tail, or a boundary that would leave a dangling
    `tool_use` or a non-alternating message sequence upstream.
    """
    messages = body.get("messages")
    if not isinstance(messages, list) or len(messages) < 2:
        return body

    final = messages[-1]
    keep = _cached_prefix_end(messages[:-1])
    head = messages[:keep]
    if head and not _can_precede_user(head[-1]):
        return body

    trimmed = [*head, final]
    if len(trimmed) >= len(messages):
        return body
    return {**body, "messages": trimmed}


def message_tokens(body: dict[str, Any], model: str) -> int:
    """Token size of the messages array — the only part a heartbeat trims."""
    messages = body.get("messages") or []
    if not messages:
        return 0
    return count_text(json.dumps(messages, separators=(",", ":"), ensure_ascii=False), model).tokens


def _explicit_marker(body: dict[str, Any]) -> bool:
    meta = body.get("metadata")
    if not isinstance(meta, dict):
        return False
    for key in MARKER_KEYS:
        value = meta.get(key)
        if value is True or (isinstance(value, str) and value.strip().lower() in _TRUTHY):
            return True
    return False


def _final_user_text(body: dict[str, Any]) -> str:
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        return ""
    last = messages[-1]
    if not isinstance(last, dict) or last.get("role") != "user":
        return ""
    content = last.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            str(b.get("text", ""))
            for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        ]
        # A tool_result block means the model is mid-task, never a ping.
        if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
            return ""
        return "\n".join(parts)
    return ""


def _tiny_max_tokens(body: dict[str, Any]) -> bool:
    raw = body.get("max_tokens") or body.get("max_completion_tokens")
    try:
        return 0 < int(raw) <= TINY_MAX_TOKENS
    except (TypeError, ValueError):
        return False


def _tools_switched_off(body: dict[str, Any]) -> bool:
    choice = body.get("tool_choice")
    if isinstance(choice, str):
        return choice == "none"
    if isinstance(choice, dict):
        return choice.get("type") == "none"
    return False


def _cached_prefix_end(messages: list[Any]) -> int:
    """Index one past the last message that may be inside a warmed prefix.

    Leading system/developer messages always count (OpenAI carries the
    system prompt in the messages array — dropping it would rewrite the
    prefix, not the tail).
    """
    end = 0
    for i, msg in enumerate(messages):
        if not isinstance(msg, dict):
            break
        if msg.get("role") not in ("system", "developer"):
            break
        end = i + 1
    for i, msg in enumerate(messages):
        if isinstance(msg, dict) and _has_cache_breakpoint(msg):
            end = max(end, i + 1)
    return end


def _has_cache_breakpoint(msg: dict[str, Any]) -> bool:
    if msg.get("cache_control"):
        return True
    content = msg.get("content")
    if isinstance(content, list):
        return any(isinstance(b, dict) and b.get("cache_control") for b in content)
    return False


def _can_precede_user(msg: Any) -> bool:
    if not isinstance(msg, dict):
        return False
    role = msg.get("role")
    if role in ("system", "developer"):
        return True
    if role != "assistant":
        return False  # user-before-user would break role alternation
    if msg.get("tool_calls"):
        return False
    content = msg.get("content")
    if isinstance(content, list):
        return not any(isinstance(b, dict) and b.get("type") == "tool_use" for b in content)
    return True
