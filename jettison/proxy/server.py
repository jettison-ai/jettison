"""Jettison interception proxy.

Chains in FRONT of Headroom's proxy (or straight to the provider):

    agent client -> jettison (standing context + meta-tool loop + verifier)
                 -> headroom proxy (runtime compression, CCR, caching)   [optional]
                 -> provider

Owning the front position means the meta-tool loop does not depend on
upstream hook placement, and Headroom still compresses tool *results*
flowing through both.

Endpoints: POST /v1/messages (Anthropic), POST /v1/chat/completions
(OpenAI). Everything else passes through byte-faithful. Bypass with
header `x-jettison-bypass: true`.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx

from jettison.compiler import build_bundle, compile_instructions, minify_tools
from jettison.compiler.instructions_min import SkillSummary
from jettison.proxy import formats
from jettison.proxy.interceptor import InterceptionLoop, SessionState
from jettison.proxy.rewrite import RewriteResult, rewrite_request, session_key
from jettison.registry.prompt import render_capability_index
from jettison.registry.store import CapabilityStore
from jettison.savings import ledger
from jettison.verifier import AuditRecord, TextVerifier, verify_tool_registry

logger = logging.getLogger(__name__)

DEFAULT_ANTHROPIC_UPSTREAM = "https://api.anthropic.com"
DEFAULT_OPENAI_UPSTREAM = "https://api.openai.com"

_HOP_HEADERS = {"content-length", "content-encoding", "transfer-encoding", "accept-encoding", "host", "connection"}


@dataclass
class JettisonProxyConfig:
    anthropic_upstream: str = DEFAULT_ANTHROPIC_UPSTREAM
    openai_upstream: str = DEFAULT_OPENAI_UPSTREAM
    client_label: str = "unknown"
    optimize_tools: bool = True
    optimize_system: bool = True
    min_tools_to_optimize: int = 5
    # skills discovered at wrap time; merged into every bundle
    skills: list[SkillSummary] = field(default_factory=list)
    request_timeout_s: float = 600.0


class BundleCache:
    """CapabilityStore per unique client tool list (keyed by content hash).

    Deterministic: the same tool list bytes always produce the same
    bundle, index text and hash — a cache-safety requirement.
    """

    def __init__(self, config: JettisonProxyConfig, max_entries: int = 32) -> None:
        self._config = config
        self._stores: dict[str, CapabilityStore] = {}
        self._verified: dict[str, bool] = {}
        self._max = max_entries

    def _normalize(self, tools: list[dict[str, Any]], provider: str) -> list[dict[str, Any]]:
        if provider != "openai":
            return tools
        out = []
        for t in tools:
            fn = t.get("function") or {}
            out.append(
                {
                    "name": fn.get("name", t.get("name", "")),
                    "description": fn.get("description", ""),
                    "input_schema": fn.get("parameters") or {},
                }
            )
        return out

    def store_for(self, tools: list[dict[str, Any]], provider: str) -> tuple[CapabilityStore, bool]:
        """Returns (store, contract_ok). contract_ok=False means the tool
        registry failed commitment verification and callers must not
        optimize the tool list (fail safe)."""
        canon = json.dumps(tools, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        key = hashlib.sha256(canon.encode()).hexdigest()[:24]
        if key in self._stores:
            return self._stores[key], self._verified[key]

        normalized = self._normalize(tools, provider)
        minified = minify_tools(normalized)
        index_text = render_capability_index(
            [(t.name, t.description[:80]) for t in minified.tools], self._config.skills
        )
        bundle = build_bundle(minified, compile_instructions([]), self._config.skills, index_text)
        store = CapabilityStore(bundle)

        check = verify_tool_registry(
            normalized, set(store.capability_names), bundle.schema_store, provider
        )
        if not check.ok:
            logger.warning(
                "tool registry failed verification (%d violations); optimization disabled for this tool list",
                len(check.violations),
            )

        if len(self._stores) >= self._max:
            self._stores.clear()
            self._verified.clear()
        self._stores[key] = store
        self._verified[key] = check.ok
        return store, check.ok


def create_app(config: JettisonProxyConfig | None = None, http_client: httpx.AsyncClient | None = None):
    # Module-level import would make fastapi a hard dependency of the whole
    # package; a local import breaks FastAPI's annotation resolution under
    # `from __future__ import annotations`. Import here and publish the
    # names to module globals so get_type_hints can see them.
    from fastapi import FastAPI, Request, Response
    from fastapi.responses import StreamingResponse

    globals()["Request"] = Request
    globals()["Response"] = Response

    config = config or JettisonProxyConfig()
    app = FastAPI(title="jettison", docs_url=None, redoc_url=None)
    bundles = BundleCache(config)
    sessions: dict[str, SessionState] = {}
    text_verifier = TextVerifier()
    http_client = http_client or httpx.AsyncClient(timeout=config.request_timeout_s)

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        await http_client.aclose()

    def _upstream(provider: str, path: str) -> str:
        base = config.anthropic_upstream if provider == "anthropic" else config.openai_upstream
        return base.rstrip("/") + path

    def _fwd_headers(request: Request) -> dict[str, str]:
        return {
            k: v
            for k, v in request.headers.items()
            if k.lower() not in _HOP_HEADERS and not k.lower().startswith("x-jettison")
        }

    async def _handle(request: Request, provider: str, path: str) -> Response:
        raw = await request.body()
        headers = _fwd_headers(request)

        bypass = request.headers.get("x-jettison-bypass", "").lower() == "true"
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            body = None
        if bypass or not isinstance(body, dict):
            resp = await http_client.post(_upstream(provider, path), content=raw, headers=headers)
            return Response(
                content=resp.content,
                status_code=resp.status_code,
                headers={k: v for k, v in resp.headers.items() if k.lower() not in _HOP_HEADERS},
            )

        request_id = uuid.uuid4().hex[:12]
        model = str(body.get("model", "unknown"))
        stream_requested = bool(body.get("stream"))
        skey = session_key(body, provider)
        session = sessions.setdefault(skey, SessionState())

        # 1. Mixed-turn recovery: patch client-fabricated results for our ids.
        messages = body.get("messages") or []
        patched = InterceptionLoop(_dummy_store(), 0).patch_incoming_messages(messages, session, provider) if session.pending_results else 0
        if patched:
            body["messages"] = messages

        # 2. Rewrite: tools -> registry, system -> compiled. Fail safe at
        # every step.
        rewrite = RewriteResult(body=body, tokens_before=0, tokens_after=0)
        store: CapabilityStore | None = None
        if config.optimize_tools and body.get("tools"):
            store, contract_ok = bundles.store_for(body["tools"], provider)
            if contract_ok:
                rewrite = rewrite_request(
                    body,
                    provider,
                    store,
                    session,
                    optimize_system=config.optimize_system,
                    min_tools_to_optimize=config.min_tools_to_optimize,
                )
                body = rewrite.body

        # 3. Verify compiled system text; re-inflate on violation.
        reinflated = False
        violations = 0
        commitments = 0
        if rewrite.rewrote_system:
            check = text_verifier.verify_and_repair(rewrite.original_system_text, rewrite.compiled_system_text)
            commitments = check.commitments_checked
            violations = len(check.violations)
            if not check.ok and check.restored_text is not None:
                from jettison.proxy.rewrite import _replace_system  # deliberate reuse

                _replace_system(body, provider, rewrite.compiled_system_text, check.restored_text)
                reinflated = True

        optimized = rewrite.rewrote_tools or rewrite.rewrote_system

        # 4. Stream downgrade when we own tools in the outbound list
        # (Headroom CCR pattern): resolve buffered, re-synthesize SSE.
        downgraded = stream_requested and rewrite.rewrote_tools
        if downgraded:
            body["stream"] = False

        upstream_url = _upstream(provider, path)

        async def api_call(msgs: list[dict[str, Any]], tls: Any) -> dict[str, Any]:
            cont = {**body, "messages": msgs}
            if tls is not None:
                cont["tools"] = tls
            r = await http_client.post(upstream_url, json=cont, headers=headers)
            r.raise_for_status()
            return r.json()

        if stream_requested and not downgraded:
            # Nothing of ours in play: transparent streaming passthrough.
            upstream_req = http_client.build_request(
                "POST", upstream_url, content=json.dumps(body).encode(), headers=headers
            )
            upstream_resp = await http_client.send(upstream_req, stream=True)

            async def relay():
                try:
                    async for chunk in upstream_resp.aiter_bytes():
                        yield chunk
                finally:
                    await upstream_resp.aclose()

            return StreamingResponse(
                relay(),
                status_code=upstream_resp.status_code,
                media_type=upstream_resp.headers.get("content-type", "text/event-stream"),
            )

        resp = await http_client.post(upstream_url, json=body, headers=headers)
        if resp.status_code != 200:
            return Response(
                content=resp.content,
                status_code=resp.status_code,
                headers={k: v for k, v in resp.headers.items() if k.lower() not in _HOP_HEADERS},
            )
        resp_json = resp.json()

        # 5. Meta-tool interception loop.
        outcome_rounds = 0
        meta_resolved = 0
        mixed = False
        if store is not None and rewrite.rewrote_tools:
            loop = InterceptionLoop(store)
            outcome = await loop.run(
                resp_json, body.get("messages") or [], body.get("tools"), api_call, provider, session
            )
            resp_json = outcome.response
            outcome_rounds = outcome.rounds
            meta_resolved = outcome.meta_calls_resolved
            mixed = outcome.mixed_turn

        # 6. Bookkeeping.
        if optimized and rewrite.tokens_saved > 0:
            ledger.record_event(
                tokens_before=rewrite.tokens_before,
                tokens_after=rewrite.tokens_after,
                model=model,
                client=config.client_label,
                source="proxy",
                cache_tier="cache_read",
            )
        AuditRecord(
            request_id=request_id,
            provider=provider,
            model=model,
            tokens_before=rewrite.tokens_before,
            tokens_after=rewrite.tokens_after,
            commitments_checked=commitments,
            violations=violations,
            reinflated=reinflated,
            meta_calls_resolved=meta_resolved,
            loop_rounds=outcome_rounds,
            mixed_turn=mixed,
            rewrote_tools=rewrite.rewrote_tools,
            rewrote_system=rewrite.rewrote_system,
        ).write()

        if downgraded:
            synth = (
                formats.anthropic_response_to_sse(resp_json)
                if provider == "anthropic"
                else formats.openai_response_to_sse(resp_json)
            )

            async def synth_stream():
                for ev in synth:
                    yield ev

            return StreamingResponse(synth_stream(), media_type="text/event-stream")

        return Response(content=json.dumps(resp_json).encode(), media_type="application/json")

    @app.post("/v1/messages")
    async def anthropic_messages(request: Request):
        return await _handle(request, "anthropic", "/v1/messages")

    @app.post("/v1/chat/completions")
    async def openai_chat(request: Request):
        return await _handle(request, "openai", "/v1/chat/completions")

    @app.get("/jettison/health")
    async def health():
        return {"ok": True, "sessions": len(sessions)}

    @app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
    async def passthrough(request: Request, path: str):
        provider = "openai" if path.startswith(("v1/chat", "v1/models", "v1/responses")) else "anthropic"
        url = _upstream(provider, "/" + path)
        raw = await request.body()
        resp = await http_client.request(request.method, url, content=raw or None, headers=_fwd_headers(request))
        return Response(
            content=resp.content,
            status_code=resp.status_code,
            headers={k: v for k, v in resp.headers.items() if k.lower() not in _HOP_HEADERS},
        )

    return app


_DUMMY_STORE: CapabilityStore | None = None


def _dummy_store() -> CapabilityStore:
    """Store-independent use of patch_incoming_messages (it never touches
    the store); avoids building a real bundle just to patch messages."""
    global _DUMMY_STORE
    if _DUMMY_STORE is None:
        _DUMMY_STORE = CapabilityStore(
            build_bundle(minify_tools([]), compile_instructions([]), [], "")
        )
    return _DUMMY_STORE


def run_server(config: JettisonProxyConfig | None = None, host: str = "127.0.0.1", port: int = 8977) -> None:
    import uvicorn

    uvicorn.run(create_app(config), host=host, port=port, log_level="warning")
