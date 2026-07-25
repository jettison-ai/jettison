"""Request rewriting: swap the full tool catalog for the capability
registry, compile the system prompt, keep everything byte-stable.

Cache-safety rules enforced here (docs/CACHE_SAFETY.md):
- the injected capability index + compiled system live in the STABLE
  PREFIX: byte-identical for identical inputs (no timestamps/ids)
- the outgoing tools list is meta-tools + session-loaded real tools,
  sorted by name; it grows monotonically per session (one cache bust per
  newly loaded tool, then stable)
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from jettison.compiler.instructions_min import compile_instructions
from jettison.proxy.interceptor import SessionState
from jettison.registry import anthropic_tool_defs, openai_tool_defs
from jettison.registry.store import CapabilityStore
from jettison.tokens import count_text


def session_key(body: dict[str, Any], provider: str) -> str:
    """Stable conversation identity: model + first user text (CCR-style)."""
    model = str(body.get("model", ""))
    first_user = ""
    for msg in body.get("messages") or []:
        if msg.get("role") == "user":
            c = msg.get("content")
            if isinstance(c, str):
                first_user = c[:512]
            elif isinstance(c, list):
                for block in c:
                    if isinstance(block, dict) and block.get("type") == "text":
                        first_user = str(block.get("text", ""))[:512]
                        break
                else:
                    continue
            break
    return hashlib.sha256(f"{model}:{first_user}".encode()).hexdigest()[:24]


@dataclass
class RewriteResult:
    body: dict[str, Any]
    tokens_before: int
    tokens_after: int
    original_tools: list[dict[str, Any]] = field(default_factory=list)
    original_system_text: str = ""
    compiled_system_text: str = ""
    rewrote_tools: bool = False
    rewrote_system: bool = False

    @property
    def tokens_saved(self) -> int:
        return max(0, self.tokens_before - self.tokens_after)


def _tool_list_tokens(tools: list[dict[str, Any]], model: str) -> int:
    if not tools:
        return 0
    return count_text(json.dumps(tools, separators=(",", ":"), ensure_ascii=False), model).tokens


def _system_as_text(system: Any) -> str:
    if isinstance(system, str):
        return system
    if isinstance(system, list):  # anthropic system blocks
        return "\n\n".join(
            str(b.get("text", "")) for b in system if isinstance(b, dict) and b.get("type") == "text"
        )
    return ""


def rewrite_request(
    body: dict[str, Any],
    provider: str,
    store: CapabilityStore,
    session: SessionState,
    *,
    optimize_system: bool = True,
    min_tools_to_optimize: int = 5,
) -> RewriteResult:
    """Rewrite a request body in place-safe copy. Returns before/after."""
    model = str(body.get("model", ""))
    new_body = dict(body)

    tokens_before = 0
    tokens_after = 0
    result = RewriteResult(body=new_body, tokens_before=0, tokens_after=0)

    # ---- tools ----
    tools = body.get("tools") or []
    client_tool_names = {_tool_name(t, provider) for t in tools}
    # Step-aside rule (§8.3): tiny tool lists aren't worth a registry
    # indirection, and a client that already ships deferred loading will
    # present few/no tools here.
    if len(tools) >= min_tools_to_optimize:
        result.original_tools = tools
        tokens_before += _tool_list_tokens(tools, model)

        meta = anthropic_tool_defs() if provider == "anthropic" else openai_tool_defs()
        loaded_real = [
            _find_original_tool(tools, name, provider)
            for name in session.loaded_capabilities
        ]
        loaded_real = [t for t in loaded_real if t is not None]
        new_tools = meta + sorted(loaded_real, key=lambda t: _tool_name(t, provider))
        new_body["tools"] = new_tools
        tokens_after += _tool_list_tokens(new_tools, model)
        result.rewrote_tools = True

        # The registry index goes into the system prompt (stable prefix).
        index_text = store.bundle.capability_index_text
        _append_system(new_body, provider, index_text)
        tokens_after += count_text(index_text, model).tokens

    # ---- system prompt compilation ----
    if optimize_system:
        sys_text = _system_as_text(body.get("system") if provider == "anthropic" else _openai_system(body))
        if sys_text and len(sys_text) > 2000:
            compiled = compile_instructions([("system", sys_text)])
            if compiled.text != sys_text and len(compiled.text) < len(sys_text):
                result.original_system_text = sys_text
                result.compiled_system_text = compiled.text
                tokens_before += count_text(sys_text, model).tokens
                tokens_after += count_text(compiled.text, model).tokens
                _replace_system(new_body, provider, sys_text, compiled.text)
                result.rewrote_system = True

    result.tokens_before = tokens_before
    result.tokens_after = tokens_after
    return result


def _tool_name(tool: dict[str, Any], provider: str) -> str:
    if provider == "openai":
        return ((tool.get("function") or {}).get("name")) or tool.get("name", "")
    return tool.get("name", "")


def _find_original_tool(tools: list[dict[str, Any]], name: str, provider: str) -> dict[str, Any] | None:
    for t in tools:
        if _tool_name(t, provider) == name:
            return t
    return None


def _openai_system(body: dict[str, Any]) -> str:
    for msg in body.get("messages") or []:
        if msg.get("role") in ("system", "developer"):
            c = msg.get("content")
            return c if isinstance(c, str) else ""
    return ""


def _append_system(body: dict[str, Any], provider: str, extra: str) -> None:
    if provider == "anthropic":
        system = body.get("system")
        if isinstance(system, str):
            body["system"] = f"{system}\n\n{extra}" if system else extra
        elif isinstance(system, list):
            body["system"] = [*system, {"type": "text", "text": extra}]
        else:
            body["system"] = extra
    else:
        messages = list(body.get("messages") or [])
        for i, msg in enumerate(messages):
            if msg.get("role") in ("system", "developer") and isinstance(msg.get("content"), str):
                messages[i] = {**msg, "content": f"{msg['content']}\n\n{extra}"}
                break
        else:
            messages.insert(0, {"role": "system", "content": extra})
        body["messages"] = messages


def _replace_system(body: dict[str, Any], provider: str, old: str, new: str) -> None:
    if provider == "anthropic":
        system = body.get("system")
        if isinstance(system, str):
            body["system"] = system.replace(old, new, 1)
        elif isinstance(system, list):
            body["system"] = [
                (
                    {**b, "text": str(b.get("text", "")).replace(old, new, 1)}
                    if isinstance(b, dict) and b.get("type") == "text"
                    else b
                )
                for b in system
            ]
    else:
        messages = list(body.get("messages") or [])
        for i, msg in enumerate(messages):
            if msg.get("role") in ("system", "developer") and isinstance(msg.get("content"), str):
                messages[i] = {**msg, "content": msg["content"].replace(old, new, 1)}
                break
        body["messages"] = messages
