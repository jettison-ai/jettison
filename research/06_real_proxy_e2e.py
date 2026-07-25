"""Drive the real Jettison proxy with real MCP schemas.

A scripted provider stands in for the model (no API key, deterministic),
but everything else is the production path: the real proxy app, the real
rewrite, the real interception loop, the real verifier.
"""

import asyncio
import concurrent.futures as cf
import json
import sys
from pathlib import Path

import httpx

from jettison.proxy.server import JettisonProxyConfig, create_app
from jettison.registry.metatools import LOAD_TOOL, SEARCH_TOOL
from jettison.scanner import mcp as mcp_mod
from jettison.tokens import count_text

project = Path(sys.argv[1]).resolve()

specs = mcp_mod.discover_claude_code(project)
tools = []
with cf.ThreadPoolExecutor(max_workers=8) as ex:
    futs = {ex.submit(mcp_mod.introspect_stdio_server, s, 120): s for s in specs if s.transport == "stdio"}
    for f in cf.as_completed(futs):
        try:
            tools += [
                {"name": f"mcp__{t.server}__{t.name}", "description": t.description,
                 "input_schema": t.input_schema}
                for t in f.result()
            ]
        except mcp_mod.MCPIntrospectionError:
            pass
tools.sort(key=lambda t: t["name"])
print(f"real tools on the wire: {len(tools)}")

SYSTEM = (
    "You are working in the OpenMC repository. Never modify an existing "
    "migration. All neutron transport runs must use a tolerance of 1e-6. "
    "Respond in JSON format when reporting results."
)

captured = []


def provider_app():
    from fastapi import FastAPI, Request

    globals()["Request"] = Request
    app = FastAPI()

    @app.post("/v1/messages")
    async def messages(request: Request):
        body = await request.json()
        captured.append(body)
        n = len(captured)
        if n == 1:
            content = [{"type": "tool_use", "id": "c1", "name": SEARCH_TOOL,
                        "input": {"query": "take a screenshot of a web page"}}]
        elif n == 2:
            content = [{"type": "tool_use", "id": "c2", "name": LOAD_TOOL,
                        "input": {"names": ["mcp__playwright__browser_take_screenshot"]}}]
        else:
            content = [{"type": "tool_use", "id": "c3",
                        "name": "mcp__playwright__browser_take_screenshot",
                        "input": {"filename": "shot.png"}}]
        return {"id": f"msg{n}", "type": "message", "role": "assistant",
                "model": body.get("model"), "content": content,
                "stop_reason": "tool_use",
                "usage": {"input_tokens": 100, "output_tokens": 20}}

    return app


async def main():
    upstream = httpx.AsyncClient(transport=httpx.ASGITransport(app=provider_app()),
                                 base_url="http://upstream")
    app = create_app(JettisonProxyConfig(anthropic_upstream="http://upstream",
                                         client_label="demo"), http_client=upstream)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://jettison")

    body = {"model": "claude-sonnet-4-5", "max_tokens": 2048, "system": SYSTEM,
            "messages": [{"role": "user", "content": "screenshot the docs page for me"}],
            "tools": tools}

    sent_before = count_text(json.dumps(body, separators=(",", ":"))).tokens
    resp = await client.post("/v1/messages", json=body)
    final = resp.json()

    first_upstream = captured[0]
    sent_after = count_text(json.dumps(first_upstream, separators=(",", ":"))).tokens

    print(f"\n{'—'*66}\nREQUEST ON THE WIRE (real proxy, real schemas)\n{'—'*66}")
    print(f"  client sent            {sent_before:>8,} tokens  ({len(body['tools'])} tool schemas)")
    print(f"  proxy forwarded        {sent_after:>8,} tokens  ({len(first_upstream['tools'])} tools: the meta-tools)")
    print(f"  reduction              {100*(1-sent_after/sent_before):>7.1f}%")

    print(f"\n  upstream calls made:   {len(captured)}  (1 client request -> search -> load -> answer)")
    names = [b["name"] for b in final["content"] if b["type"] == "tool_use"]
    print(f"  tools the CLIENT saw:  {names}")
    print(f"  -> client never sees jettison meta-tools: "
          f"{all(not n.startswith('jettison_') for n in names)}")

    # the loaded capability is sticky: next request carries it for real
    resp2 = await client.post("/v1/messages", json=body)
    later = [t["name"] for t in captured[3]["tools"]]
    print(f"  next request's tools:  {later}")
    print(f"  -> loaded tool stuck around: "
          f"{'mcp__playwright__browser_take_screenshot' in later}")

    # verifier: are the system commitments still intact in what was sent?
    sent_system = json.dumps(first_upstream.get("system", ""))
    for fact in ["1e-6", "Never modify an existing", "JSON format"]:
        print(f"  commitment {fact!r:32} preserved: {fact in sent_system}")


asyncio.run(main())
