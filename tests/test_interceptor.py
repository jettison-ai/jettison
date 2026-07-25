"""Interception-loop unit tests: mixed turns, round caps, message patching."""

from __future__ import annotations

import json

from jettison.compiler import build_bundle, compile_instructions, minify_tools, summarize_skill
from jettison.proxy.interceptor import InterceptionLoop, SessionState
from jettison.registry.metatools import LOAD_TOOL, SEARCH_TOOL
from jettison.registry.prompt import render_capability_index
from jettison.registry.store import CapabilityStore


def make_store() -> CapabilityStore:
    tools = [
        {
            "name": "alpha_tool",
            "description": "Does alpha things with files.",
            "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
        }
    ]
    r = minify_tools(tools)
    skills = [summarize_skill("demo", "---\ndescription: demo skill\n---\nBody here.")]
    idx = render_capability_index([(t.name, t.description) for t in r.tools], skills)
    return CapabilityStore(build_bundle(r, compile_instructions([]), skills, idx))


def anthropic_response(blocks):
    return {"role": "assistant", "content": blocks, "stop_reason": "tool_use"}


async def test_mixed_turn_stashes_results_and_bails():
    store = make_store()
    loop = InterceptionLoop(store)
    session = SessionState()
    resp = anthropic_response(
        [
            {"type": "tool_use", "id": "m1", "name": SEARCH_TOOL, "input": {"query": "alpha"}},
            {"type": "tool_use", "id": "c1", "name": "client_tool", "input": {}},
        ]
    )

    async def api_call(msgs, tools):
        raise AssertionError("must not re-invoke on mixed turn")

    out = await loop.run(resp, [], None, api_call, "anthropic", session)
    assert out.mixed_turn
    assert out.response is resp  # passed through
    assert "m1" in session.pending_results
    assert "alpha_tool" in session.pending_results["m1"]


async def test_patch_incoming_messages_replaces_client_error_results():
    store = make_store()
    loop = InterceptionLoop(store)
    session = SessionState()
    session.pending_results["m1"] = '{"results": [{"name": "alpha_tool"}]}'
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "m1", "content": "Error: unknown tool"},
                {"type": "tool_result", "tool_use_id": "c1", "content": "client stuff"},
            ],
        }
    ]
    patched = loop.patch_incoming_messages(messages, session, "anthropic")
    assert patched == 1
    assert "alpha_tool" in messages[0]["content"][0]["content"]
    assert messages[0]["content"][1]["content"] == "client stuff"
    assert not session.pending_results


async def test_round_cap_stops_infinite_loop():
    store = make_store()
    loop = InterceptionLoop(store, max_rounds=2)
    session = SessionState()
    calls = {"n": 0}

    resp = anthropic_response(
        [{"type": "tool_use", "id": "s", "name": SEARCH_TOOL, "input": {"query": "x"}}]
    )

    async def api_call(msgs, tools):
        calls["n"] += 1
        return anthropic_response(
            [{"type": "tool_use", "id": f"s{calls['n']}", "name": SEARCH_TOOL, "input": {"query": "x"}}]
        )

    out = await loop.run(resp, [], None, api_call, "anthropic", session)
    assert out.rounds == 2
    assert calls["n"] == 2


async def test_load_marks_session_sticky():
    store = make_store()
    loop = InterceptionLoop(store)
    session = SessionState()
    resp = anthropic_response(
        [{"type": "tool_use", "id": "l1", "name": LOAD_TOOL, "input": {"names": ["alpha_tool"]}}]
    )

    async def api_call(msgs, tools):
        # tool_result content must carry the full schema
        content = msgs[-1]["content"][0]["content"]
        loaded = json.loads(content)["loaded"]
        assert loaded[0]["name"] == "alpha_tool"
        return anthropic_response([{"type": "text", "text": "done"}])

    out = await loop.run(resp, [], None, api_call, "anthropic", session)
    assert out.meta_calls_resolved == 1
    assert session.loaded_capabilities == ["alpha_tool"]
