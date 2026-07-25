"""Provider-format normalization for the interception loop.

Modeled on Headroom's ccr/tool_calls.py (Apache 2.0, see NOTICE): one
place that knows how Anthropic `tool_use` blocks and OpenAI `tool_calls`
differ, so the loop itself stays provider-agnostic.

Supported providers: "anthropic", "openai".
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from jettison.registry.metatools import META_TOOL_NAMES


@dataclass
class ToolCall:
    call_id: str
    name: str
    arguments: dict[str, Any]


def extract_tool_calls(response: dict[str, Any], provider: str) -> list[ToolCall]:
    calls: list[ToolCall] = []
    if provider == "anthropic":
        for block in response.get("content") or []:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                calls.append(
                    ToolCall(
                        call_id=block.get("id", ""),
                        name=block.get("name", ""),
                        arguments=block.get("input") or {},
                    )
                )
    elif provider == "openai":
        choices = response.get("choices") or []
        message = (choices[0].get("message") or {}) if choices else {}
        for tc in message.get("tool_calls") or []:
            fn = tc.get("function") or {}
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            calls.append(ToolCall(call_id=tc.get("id", ""), name=fn.get("name", ""), arguments=args))
    else:
        raise ValueError(f"unsupported provider: {provider}")
    return calls


def split_meta_calls(calls: list[ToolCall]) -> tuple[list[ToolCall], list[ToolCall]]:
    meta = [c for c in calls if c.name in META_TOOL_NAMES]
    other = [c for c in calls if c.name not in META_TOOL_NAMES]
    return meta, other


def extract_assistant_message(response: dict[str, Any], provider: str) -> dict[str, Any]:
    if provider == "anthropic":
        return {"role": "assistant", "content": response.get("content") or []}
    choices = response.get("choices") or []
    message = (choices[0].get("message") or {}) if choices else {}
    return {k: v for k, v in message.items() if v is not None}


def build_tool_result_message(
    results: list[tuple[ToolCall, str]], provider: str
) -> list[dict[str, Any]]:
    """Messages to append after the assistant turn carrying our results."""
    if provider == "anthropic":
        return [
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": call.call_id,
                        "content": content,
                    }
                    for call, content in results
                ],
            }
        ]
    return [
        {"role": "tool", "tool_call_id": call.call_id, "content": content}
        for call, content in results
    ]


def stop_reason_is_tool_use(response: dict[str, Any], provider: str) -> bool:
    if provider == "anthropic":
        return response.get("stop_reason") == "tool_use"
    choices = response.get("choices") or []
    return bool(choices) and choices[0].get("finish_reason") == "tool_calls"


# ---------------------------------------------------------------------------
# SSE re-synthesis: buffered JSON response -> stream the client expects.
# Mirrors Headroom's stream-downgrade pattern (CCR call site B).
# ---------------------------------------------------------------------------


def anthropic_response_to_sse(response: dict[str, Any]) -> list[bytes]:
    def ev(name: str, data: dict[str, Any]) -> bytes:
        return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode()

    events: list[bytes] = []
    message_head = {k: v for k, v in response.items() if k != "content"}
    message_head["content"] = []
    usage = response.get("usage") or {}
    message_head.setdefault("usage", {"input_tokens": usage.get("input_tokens", 0), "output_tokens": 0})
    events.append(ev("message_start", {"type": "message_start", "message": {**message_head, "stop_reason": None, "stop_sequence": None}}))

    for i, block in enumerate(response.get("content") or []):
        btype = block.get("type")
        if btype == "text":
            events.append(ev("content_block_start", {"type": "content_block_start", "index": i, "content_block": {"type": "text", "text": ""}}))
            events.append(ev("content_block_delta", {"type": "content_block_delta", "index": i, "delta": {"type": "text_delta", "text": block.get("text", "")}}))
        elif btype == "tool_use":
            events.append(
                ev(
                    "content_block_start",
                    {
                        "type": "content_block_start",
                        "index": i,
                        "content_block": {"type": "tool_use", "id": block.get("id", ""), "name": block.get("name", ""), "input": {}},
                    },
                )
            )
            events.append(
                ev(
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": i,
                        "delta": {"type": "input_json_delta", "partial_json": json.dumps(block.get("input") or {}, ensure_ascii=False)},
                    },
                )
            )
        elif btype == "thinking":
            events.append(ev("content_block_start", {"type": "content_block_start", "index": i, "content_block": {"type": "thinking", "thinking": ""}}))
            events.append(ev("content_block_delta", {"type": "content_block_delta", "index": i, "delta": {"type": "thinking_delta", "thinking": block.get("thinking", "")}}))
        else:
            events.append(ev("content_block_start", {"type": "content_block_start", "index": i, "content_block": block}))
        events.append(ev("content_block_stop", {"type": "content_block_stop", "index": i}))

    events.append(
        ev(
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": response.get("stop_reason"), "stop_sequence": response.get("stop_sequence")},
                "usage": {"output_tokens": usage.get("output_tokens", 0)},
            },
        )
    )
    events.append(ev("message_stop", {"type": "message_stop"}))
    return events


def openai_response_to_sse(response: dict[str, Any]) -> list[bytes]:
    def chunk(delta: dict[str, Any], finish: str | None = None) -> bytes:
        choices = response.get("choices") or [{}]
        payload = {
            "id": response.get("id", ""),
            "object": "chat.completion.chunk",
            "created": response.get("created", 0),
            "model": response.get("model", ""),
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        }
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode()

    events: list[bytes] = []
    choices = response.get("choices") or []
    message = (choices[0].get("message") or {}) if choices else {}
    finish = choices[0].get("finish_reason") if choices else "stop"

    events.append(chunk({"role": "assistant"}))
    if message.get("content"):
        events.append(chunk({"content": message["content"]}))
    if message.get("tool_calls"):
        deltas = []
        for i, tc in enumerate(message["tool_calls"]):
            deltas.append(
                {
                    "index": i,
                    "id": tc.get("id"),
                    "type": "function",
                    "function": {
                        "name": (tc.get("function") or {}).get("name", ""),
                        "arguments": (tc.get("function") or {}).get("arguments", ""),
                    },
                }
            )
        events.append(chunk({"tool_calls": deltas}))
    events.append(chunk({}, finish=finish))
    events.append(b"data: [DONE]\n\n")
    return events
