"""Native deferred-loading detection + the §8.3 tool step-aside end to end."""

from __future__ import annotations

import json

import httpx
import pytest

from jettison.proxy.native_deferral import NATIVE_DEFERRAL_HEADER, detects_native_deferral
from jettison.proxy.server import JettisonProxyConfig, create_app
from jettison.registry.metatools import LOAD_TOOL, SEARCH_TOOL
from jettison.verifier.audit_record import read_records
from test_proxy_e2e import make_client_tools


@pytest.fixture(autouse=True)
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("JETTISON_WORKSPACE_DIR", str(tmp_path))
    return tmp_path


class FakeProvider:
    """Answers every call with plain text — nothing to intercept."""

    def __init__(self) -> None:
        self.requests: list[dict] = []

    def app(self):
        from fastapi import FastAPI, Request

        globals()["Request"] = Request
        app = FastAPI()

        @app.post("/v1/messages")
        async def messages(request: Request):
            self.requests.append(await request.json())
            return {
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "content": [{"type": "text", "text": "ok"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 10, "output_tokens": 2},
            }

        return app


def proxy_for(fake: FakeProvider, **config_kwargs):
    upstream = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=fake.app()), base_url="http://upstream"
    )
    app = create_app(
        JettisonProxyConfig(anthropic_upstream="http://upstream", client_label="test", **config_kwargs, horizon=False),
        http_client=upstream,
    )
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://jettison")


def test_anthropic_tool_search_entry_detected():
    body = {
        "tools": [
            {"type": "tool_search_tool_regex_20251119", "name": "tool_search"},
            *make_client_tools(6),
        ]
    }
    assert detects_native_deferral(body, "anthropic") == (True, "native_tool_search_entry")


def test_defer_loading_flag_detected():
    tools = make_client_tools(6)
    tools[2]["defer_loading"] = True
    assert detects_native_deferral({"tools": tools}, "anthropic") == (True, "defer_loading_flag")


def test_openai_tool_search_function_detected():
    body = {
        "tools": [
            {"type": "function", "function": {"name": "tool_search", "parameters": {}}},
            {"type": "function", "function": {"name": "read_file", "parameters": {}}},
        ]
    }
    assert detects_native_deferral(body, "openai") == (True, "native_tool_search_entry")


def test_small_tool_list_with_huge_system_detected():
    body = {"tools": make_client_tools(2), "system": "x" * 25_000}
    assert detects_native_deferral(body, "anthropic") == (True, "small_tool_list_large_system")


def test_explicit_header_detected():
    detected, reason = detects_native_deferral(
        {"tools": make_client_tools(6)}, "anthropic", {NATIVE_DEFERRAL_HEADER: "true"}
    )
    assert (detected, reason) == (True, "client_header")


def test_plain_mcp_heavy_body_is_not_deferring():
    body = {
        "tools": make_client_tools(12),
        "system": "You are a helpful assistant.",
        "messages": [{"role": "user", "content": "hi"}],
    }
    assert detects_native_deferral(body, "anthropic") == (False, "")
    assert detects_native_deferral(body, "anthropic", {"x-other-header": "1"}) == (False, "")


def test_common_mcp_tool_names_do_not_misfire():
    body = {"tools": [{"name": "list_tools", "description": "list", "input_schema": {}}] * 6}
    assert detects_native_deferral(body, "anthropic") == (False, "")


def test_records_written_before_the_new_field_still_read():
    from jettison.verifier.audit_record import AuditRecord, records_path

    legacy = {"request_id": "old", "provider": "anthropic", "model": "m", "tokens_before": 1, "tokens_after": 0}
    records_path().write_text(json.dumps(legacy) + "\n")
    AuditRecord(request_id="new", provider="anthropic", model="m", tokens_before=1, tokens_after=0).write()

    old, new = read_records()
    assert old.get("native_deferral_reason", "") == ""
    assert new["native_deferral_reason"] == "" and new["heartbeat"] is False


async def test_native_deferral_steps_aside_for_tools():
    fake = FakeProvider()
    client = proxy_for(fake)
    tools = [{"type": "tool_search_tool_regex_20251119", "name": "tool_search"}, *make_client_tools(8)]
    resp = await client.post(
        "/v1/messages",
        json={
            "model": "claude-sonnet-4-5",
            "max_tokens": 512,
            "system": "You are a helpful assistant.",
            "messages": [{"role": "user", "content": "find red shoes"}],
            "tools": tools,
        },
    )
    assert resp.status_code == 200

    sent = fake.requests[0]
    assert sent["tools"] == tools  # tool surface untouched
    assert SEARCH_TOOL not in json.dumps(sent["tools"])
    assert "Capability registry" not in json.dumps(sent.get("system", ""))

    record = read_records()[-1]
    assert record["native_deferral_reason"] == "native_tool_search_entry"
    assert record["rewrote_tools"] is False


async def test_step_aside_still_compiles_instructions():
    fake = FakeProvider()
    client = proxy_for(fake)
    # Duplicated paragraphs are what the instruction compiler removes.
    system = ("Follow the house style guide when writing code.\n\n" * 40) + "x" * 500
    resp = await client.post(
        "/v1/messages",
        json={
            "model": "claude-sonnet-4-5",
            "max_tokens": 512,
            "system": system,
            "messages": [{"role": "user", "content": "hi"}],
            "tools": [{"type": "tool_search_tool_regex_20251119", "name": "tool_search"}, *make_client_tools(8)],
        },
    )
    assert resp.status_code == 200
    assert len(fake.requests[0]["system"]) < len(system)
    assert read_records()[-1]["rewrote_system"] is True


async def test_plain_mcp_body_is_optimized_normally():
    fake = FakeProvider()
    client = proxy_for(fake)
    resp = await client.post(
        "/v1/messages",
        json={
            "model": "claude-sonnet-4-5",
            "max_tokens": 512,
            "system": "You are a helpful assistant.",
            "messages": [{"role": "user", "content": "find red shoes"}],
            "tools": make_client_tools(8),
        },
    )
    assert resp.status_code == 200

    sent_tools = [t["name"] for t in fake.requests[0]["tools"]]
    assert set(sent_tools) == {SEARCH_TOOL, LOAD_TOOL}
    assert "Capability registry" in fake.requests[0]["system"]

    record = read_records()[-1]
    assert record["native_deferral_reason"] == ""
    assert record["rewrote_tools"] is True
