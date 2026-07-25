"""The meta-tool interception loop.

Semantics follow Headroom's CCRResponseHandler precedent (see NOTICE):

- round cap against infinite model<->proxy loops
- pure meta-tool turns resolve fully inside one client request
- MIXED turns (meta-tool called alongside a client-owned tool) cannot be
  continued by the proxy — every tool_use needs a matching tool_result
  and the proxy only has results for its own tools. Unlike CCR we cannot
  just pass the turn through (the client has never seen our meta-tools),
  so we resolve our calls, remember them, pass the turn to the client,
  and patch the client's error tool_results on its NEXT request.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from jettison.proxy import formats
from jettison.registry.metatools import resolve_meta_call
from jettison.registry.store import CapabilityStore

logger = logging.getLogger(__name__)

ApiCallFn = Callable[[list[dict[str, Any]], Any], Awaitable[dict[str, Any]]]

MAX_ROUNDS = 4


@dataclass
class SessionState:
    """Per-conversation memory the loop needs across client requests."""

    loaded_capabilities: list[str] = field(default_factory=list)  # sticky, grow-only
    # call_id -> locally-resolved result content, for mixed-turn patching
    pending_results: dict[str, str] = field(default_factory=dict)

    def remember_loaded(self, names: list[str]) -> None:
        for n in names:
            if n not in self.loaded_capabilities:
                self.loaded_capabilities.append(n)
        self.loaded_capabilities.sort()


@dataclass
class LoopOutcome:
    response: dict[str, Any]
    rounds: int = 0
    meta_calls_resolved: int = 0
    mixed_turn: bool = False


class InterceptionLoop:
    def __init__(
        self, store: CapabilityStore, max_rounds: int = MAX_ROUNDS, horizon: Any = None
    ) -> None:
        self.store = store
        # Horizon Manager owns jettison_retrieve_content; the loop resolves it
        # through the same path as the capability meta-tools.
        self.horizon = horizon
        self.max_rounds = max_rounds

    def patch_incoming_messages(
        self, messages: list[dict[str, Any]], session: SessionState, provider: str
    ) -> int:
        """Replace client-fabricated tool_results for our meta-tool call ids
        (mixed-turn recovery). Returns number of patches applied."""
        if not session.pending_results:
            return 0
        patched = 0
        for msg in messages:
            if provider == "anthropic":
                content = msg.get("content")
                if not isinstance(content, list):
                    continue
                for block in content:
                    if (
                        isinstance(block, dict)
                        and block.get("type") == "tool_result"
                        and block.get("tool_use_id") in session.pending_results
                    ):
                        block["content"] = session.pending_results.pop(block["tool_use_id"])
                        patched += 1
            else:
                if msg.get("role") == "tool" and msg.get("tool_call_id") in session.pending_results:
                    msg["content"] = session.pending_results.pop(msg["tool_call_id"])
                    patched += 1
        return patched

    async def run(
        self,
        response: dict[str, Any],
        messages: list[dict[str, Any]],
        tools: Any,
        api_call_fn: ApiCallFn,
        provider: str,
        session: SessionState,
    ) -> LoopOutcome:
        current = response
        current_messages = list(messages)
        rounds = 0
        resolved = 0

        while rounds < self.max_rounds:
            calls = formats.extract_tool_calls(current, provider)
            meta, other = formats.split_meta_calls(calls)
            if not meta:
                break

            results: list[tuple[formats.ToolCall, str]] = []
            for call in meta:
                try:
                    content = resolve_meta_call(self.store, call.name, call.arguments, self.horizon)
                except Exception as e:  # resolution must never kill the turn
                    logger.warning("meta-tool %s failed: %s", call.name, e)
                    content = f'{{"error": "capability resolution failed: {e}"}}'
                if call.name.endswith("load_capabilities"):
                    session.remember_loaded([str(n) for n in call.arguments.get("names", [])])
                results.append((call, content))
            resolved += len(results)

            if other:
                # Mixed turn: hand to the client, patch on its next request.
                for call, content in results:
                    session.pending_results[call.call_id] = content
                return LoopOutcome(response=current, rounds=rounds, meta_calls_resolved=resolved, mixed_turn=True)

            current_messages.append(formats.extract_assistant_message(current, provider))
            current_messages.extend(formats.build_tool_result_message(results, provider))
            rounds += 1
            try:
                current = await api_call_fn(current_messages, tools)
            except Exception:
                logger.exception("continuation call failed; returning last response")
                # Fail like a mixed turn: stash results so the client's next
                # request can still be patched.
                for call, content in results:
                    session.pending_results[call.call_id] = content
                return LoopOutcome(response=current, rounds=rounds, meta_calls_resolved=resolved, mixed_turn=True)

        return LoopOutcome(response=current, rounds=rounds, meta_calls_resolved=resolved)
