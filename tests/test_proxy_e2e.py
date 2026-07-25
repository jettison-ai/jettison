"""End-to-end interception-loop test against a scripted fake provider.

Proves the whole chain: request rewrite (tools -> registry), meta-tool
resolution, model re-invocation, and that the client only ever sees
tools it owns.
"""

from __future__ import annotations

import json

import httpx
import pytest

from jettison.proxy.server import JettisonProxyConfig, create_app
from jettison.registry.metatools import LOAD_TOOL, SEARCH_TOOL

VERBOSE_DESC = (
    "This tool allows you to search the product catalog for items matching a query. "
    "It should be used whenever the user asks about products. " * 3
)


def make_client_tools(n: int = 8) -> list[dict]:
    return [
        {
            "name": f"catalog_tool_{i}",
            "description": VERBOSE_DESC + f" Variant {i}.",
            "input_schema": {
                "type": "object",
                "title": f"Tool{i}",
                "properties": {
                    "query": {"type": "string", "description": "Search query for the catalog."},
                    "limit": {"type": "integer", "default": 10, "examples": [5, 10]},
                },
                "required": ["query"],
            },
        }
        for i in range(n)
    ]


class FakeAnthropic:
    """Scripted provider: 1st call -> search meta-call, 2nd -> load,
    3rd -> real tool call, capturing every request body."""

    def __init__(self) -> None:
        self.requests: list[dict] = []

    def app(self):
        from fastapi import FastAPI, Request

        globals()["Request"] = Request
        app = FastAPI()

        @app.post("/v1/messages")
        async def messages(request: Request):
            body = await request.json()
            self.requests.append(body)
            n = len(self.requests)
            if n == 1:
                content = [
                    {"type": "tool_use", "id": "call_1", "name": SEARCH_TOOL, "input": {"query": "search catalog"}}
                ]
                stop = "tool_use"
            elif n == 2:
                content = [
                    {"type": "tool_use", "id": "call_2", "name": LOAD_TOOL, "input": {"names": ["catalog_tool_3"]}}
                ]
                stop = "tool_use"
            else:
                content = [
                    {"type": "tool_use", "id": "call_3", "name": "catalog_tool_3", "input": {"query": "red shoes"}}
                ]
                stop = "tool_use"
            return {
                "id": f"msg_{n}",
                "type": "message",
                "role": "assistant",
                "model": body.get("model"),
                "content": content,
                "stop_reason": stop,
                "usage": {"input_tokens": 100, "output_tokens": 20},
            }

        return app


@pytest.fixture
def env_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("JETTISON_WORKSPACE_DIR", str(tmp_path))
    return tmp_path


async def test_interception_loop_resolves_meta_tools(env_workspace):
    fake = FakeAnthropic()
    upstream_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=fake.app()), base_url="http://upstream"
    )
    config = JettisonProxyConfig(anthropic_upstream="http://upstream", client_label="test")
    app = create_app(config, http_client=upstream_client)

    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://jettison")
    body = {
        "model": "claude-sonnet-4-5",
        "max_tokens": 1024,
        "system": "You are a helpful shopping assistant.",
        "messages": [{"role": "user", "content": "find me red shoes"}],
        "tools": make_client_tools(),
    }
    resp = await client.post("/v1/messages", json=body)
    assert resp.status_code == 200
    final = resp.json()

    # The client sees only its own tool being called — meta-tools resolved internally.
    calls = [b for b in final["content"] if b["type"] == "tool_use"]
    assert [c["name"] for c in calls] == ["catalog_tool_3"]

    # Provider was called 3 times (initial + 2 loop continuations).
    assert len(fake.requests) == 3

    # First upstream request: full catalog replaced by meta-tools.
    first_tools = [t["name"] for t in fake.requests[0]["tools"]]
    assert SEARCH_TOOL in first_tools and LOAD_TOOL in first_tools
    assert not any(t.startswith("catalog_tool") for t in first_tools)

    # Capability index landed in the system prompt (stable prefix).
    assert "Capability registry" in json.dumps(fake.requests[0].get("system", ""))

    # Continuations carried synthesized tool_results for our meta calls.
    cont = fake.requests[1]["messages"]
    assert cont[-1]["content"][0]["type"] == "tool_result"
    assert cont[-1]["content"][0]["tool_use_id"] == "call_1"

    # Sticky session: capability loaded in round 2 joins the tools list of
    # the *next* client request.
    resp2 = await client.post("/v1/messages", json=body)
    assert resp2.status_code == 200
    later_tools = [t["name"] for t in fake.requests[3]["tools"]]
    assert "catalog_tool_3" in later_tools


async def test_bypass_header_forwards_untouched(env_workspace):
    fake = FakeAnthropic()
    upstream_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=fake.app()), base_url="http://upstream"
    )
    app = create_app(
        JettisonProxyConfig(anthropic_upstream="http://upstream"), http_client=upstream_client
    )
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://jettison")
    body = {
        "model": "claude-sonnet-4-5",
        "messages": [{"role": "user", "content": "hi"}],
        "tools": make_client_tools(),
    }
    resp = await client.post("/v1/messages", json=body, headers={"x-jettison-bypass": "true"})
    assert resp.status_code == 200
    assert [t["name"] for t in fake.requests[0]["tools"]] == [t["name"] for t in body["tools"]]


async def test_small_tool_lists_left_alone(env_workspace):
    fake = FakeAnthropic()
    upstream_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=fake.app()), base_url="http://upstream"
    )
    app = create_app(
        JettisonProxyConfig(anthropic_upstream="http://upstream"), http_client=upstream_client
    )
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://jettison")
    body = {
        "model": "claude-sonnet-4-5",
        "messages": [{"role": "user", "content": "hi"}],
        "tools": make_client_tools(3),  # below min_tools_to_optimize
    }
    resp = await client.post("/v1/messages", json=body)
    assert resp.status_code == 200
    assert [t["name"] for t in fake.requests[0]["tools"]] == [f"catalog_tool_{i}" for i in range(3)]


def test_thinking_block_sse_roundtrip_preserves_signature():
    """Regression: a thinking block replayed without its signature 400s.

    Found against live Claude Code traffic. The failure surfaces on the
    NEXT request, when the client sends the reconstructed turn back, so no
    fake-provider test caught it.
    """
    from jettison.proxy.formats import anthropic_response_to_sse

    resp = {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "content": [
            {"type": "thinking", "thinking": "step one, then two", "signature": "SIGabc123"},
            {"type": "text", "text": "done"},
        ],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 5, "output_tokens": 2},
    }
    wire = b"".join(anthropic_response_to_sse(resp)).decode()
    assert "thinking_delta" in wire
    assert "step one, then two" in wire
    assert "signature_delta" in wire
    assert "SIGabc123" in wire
    # signature must follow the thinking text, as the API emits it
    assert wire.index("SIGabc123") > wire.index("step one, then two")


def test_thinking_block_without_signature_emits_no_empty_delta():
    from jettison.proxy.formats import anthropic_response_to_sse

    resp = {
        "id": "m",
        "type": "message",
        "role": "assistant",
        "content": [{"type": "thinking", "thinking": "no sig here"}],
        "stop_reason": "end_turn",
        "usage": {},
    }
    wire = b"".join(anthropic_response_to_sse(resp)).decode()
    assert "thinking_delta" in wire
    assert "signature_delta" not in wire
