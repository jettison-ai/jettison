"""OpenClaw heartbeat profile: detection precision + prefix byte-stability.

The expensive mistake here is not a missed heartbeat, it's a real turn
mistaken for one (history dropped) or a heartbeat that warms a different
prefix than the real turns use (docs/CACHE_SAFETY.md). Both are asserted.
"""

from __future__ import annotations

import json

import httpx
import pytest

from jettison.proxy.heartbeat import is_heartbeat, minimal_context_body
from jettison.proxy.server import JettisonProxyConfig, create_app
from jettison.verifier.audit_record import read_records
from test_native_deferral import FakeProvider
from test_proxy_e2e import make_client_tools


@pytest.fixture(autouse=True)
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("JETTISON_WORKSPACE_DIR", str(tmp_path))
    return tmp_path


def history(n: int = 6) -> list[dict]:
    msgs: list[dict] = []
    for i in range(n):
        msgs.append({"role": "user", "content": f"question {i} " + "detail " * 50})
        msgs.append({"role": "assistant", "content": f"answer {i} " + "detail " * 50})
    return msgs


def heartbeat_body(**overrides) -> dict:
    body = {
        "model": "claude-sonnet-4-5",
        "max_tokens": 1,
        "system": [{"type": "text", "text": "standing context", "cache_control": {"type": "ephemeral"}}],
        "tools": make_client_tools(8),
        "messages": [*history(), {"role": "user", "content": "ping"}],
    }
    body.update(overrides)
    return body


def test_ping_with_tiny_budget_is_a_heartbeat():
    assert is_heartbeat(heartbeat_body(), "anthropic")


def test_templated_variants_are_heartbeats():
    for text in ("ping", "PING", "heartbeat", "heart beat", "keepalive", "keep alive", "cache warm", "noop", "ping."):
        assert is_heartbeat(heartbeat_body(messages=[{"role": "user", "content": text}]), "anthropic"), text


def test_tools_switched_off_corroborates():
    body = heartbeat_body(max_tokens=4096, tool_choice={"type": "none"})
    assert is_heartbeat(body, "anthropic")


def test_explicit_marker_is_enough():
    body = heartbeat_body(
        max_tokens=4096,
        metadata={"jettison_heartbeat": True},
        messages=[{"role": "user", "content": "anything at all"}],
    )
    assert is_heartbeat(body, "anthropic")


def test_real_user_turns_are_not_heartbeats():
    real = [
        "ping the staging server and tell me if it is up",
        "why is the cache warm path so slow?",
        "keep alive connections are leaking in prod, find the bug",
        "ok",
        "continue",
        "hi",
    ]
    for text in real:
        body = heartbeat_body(max_tokens=4096, messages=[*history(), {"role": "user", "content": text}])
        assert not is_heartbeat(body, "anthropic"), text


def test_short_ping_with_a_normal_budget_is_not_a_heartbeat():
    # Text alone never fires: a human typing "ping" keeps their history.
    assert not is_heartbeat(heartbeat_body(max_tokens=4096), "anthropic")


def test_tool_result_turns_are_never_heartbeats():
    body = heartbeat_body(
        messages=[
            *history(),
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ping"}]},
        ]
    )
    assert not is_heartbeat(body, "anthropic")


def test_minimal_context_keeps_prefix_and_drops_tail():
    body = heartbeat_body()
    minimal = minimal_context_body(body)

    assert minimal["system"] == body["system"]
    assert minimal["tools"] == body["tools"]
    assert minimal["messages"] == [body["messages"][-1]]
    assert body["messages"] == [*history(), {"role": "user", "content": "ping"}]  # input untouched


def test_messages_inside_the_cached_prefix_are_kept():
    msgs = history()
    msgs[3]["cache_control"] = {"type": "ephemeral"}  # breakpoint on an assistant turn
    body = heartbeat_body(messages=[*msgs, {"role": "user", "content": "ping"}])
    minimal = minimal_context_body(body)
    assert minimal["messages"] == [*msgs[:4], {"role": "user", "content": "ping"}]


def test_openai_system_message_is_never_dropped():
    body = {
        "model": "gpt-5",
        "max_tokens": 1,
        "messages": [
            {"role": "system", "content": "standing context"},
            {"role": "user", "content": "question"},
            {"role": "assistant", "content": "answer"},
            {"role": "user", "content": "ping"},
        ],
    }
    minimal = minimal_context_body(body)
    assert minimal["messages"] == [
        {"role": "system", "content": "standing context"},
        {"role": "user", "content": "ping"},
    ]


def test_dangling_tool_use_boundary_is_left_alone():
    # The cached prefix ends on an unanswered tool_use: trimming there would
    # send a tool_use with no tool_result, so nothing is trimmed at all.
    msgs = [
        {"role": "user", "content": "do the thing"},
        {
            "role": "assistant",
            "content": [{"type": "tool_use", "id": "t1", "name": "x", "input": {}}],
            "cache_control": {"type": "ephemeral"},
        },
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "done"}]},
        {"role": "assistant", "content": "finished"},
        {"role": "user", "content": "ping"},
    ]
    body = heartbeat_body(messages=msgs)
    assert minimal_context_body(body) is body


def test_nothing_to_trim_returns_the_same_body():
    body = heartbeat_body(messages=[{"role": "user", "content": "ping"}])
    assert minimal_context_body(body) is body


def proxy_for(fake: FakeProvider, **config_kwargs):
    upstream = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=fake.app()), base_url="http://upstream"
    )
    app = create_app(
        JettisonProxyConfig(
            anthropic_upstream="http://upstream", client_label="openclaw", **config_kwargs
        ),
        http_client=upstream,
    )
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://jettison")


async def test_prefix_is_byte_identical_across_heartbeat_and_normal_turns():
    fake = FakeProvider()
    client = proxy_for(fake, heartbeat_profile=True)

    normal = heartbeat_body(
        max_tokens=4096, messages=[*history(), {"role": "user", "content": "what did we decide?"}]
    )
    beat = heartbeat_body()

    assert (await client.post("/v1/messages", json=normal)).status_code == 200
    assert (await client.post("/v1/messages", json=beat)).status_code == 200

    sent_normal, sent_beat = fake.requests
    dumps = lambda obj: json.dumps(obj, sort_keys=False, separators=(",", ":"))  # noqa: E731
    assert dumps(sent_beat["system"]) == dumps(sent_normal["system"])
    assert dumps(sent_beat["tools"]) == dumps(sent_normal["tools"])
    # Only the uncached tail differs.
    assert len(sent_beat["messages"]) == 1
    assert len(sent_normal["messages"]) == len(normal["messages"])

    record = read_records()[-1]
    assert record["heartbeat"] is True


async def test_heartbeat_profile_is_off_unless_enabled():
    fake = FakeProvider()
    client = proxy_for(fake)
    assert (await client.post("/v1/messages", json=heartbeat_body())).status_code == 200
    assert len(fake.requests[0]["messages"]) == len(heartbeat_body()["messages"])
    assert read_records()[-1]["heartbeat"] is False
