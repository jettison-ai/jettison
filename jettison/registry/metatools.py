"""Meta-tool definitions and local resolution.

Two meta-tools ship in v1 (`execute_capability` direct dispatch is
v1.1 — it complicates the continuation protocol and the two-tool flow
already covers the token win):

  jettison_search_capabilities(query) -> ranked names + one-line summaries
  jettison_load_capabilities(names)   -> full schemas / skill bodies

The `jettison_` prefix mirrors Headroom's `headroom_retrieve` naming so
collisions with client tools are implausible, and the proxy can claim
ownership of the namespace when intercepting.

Definitions are module-level constants serialized with sorted keys —
the tool-list bytes must never vary between requests (cache safety;
see SessionCcrTracker's golden-bytes rationale upstream).
"""

from __future__ import annotations

import json
from typing import Any

from jettison.registry.store import CapabilityStore

SEARCH_TOOL = "jettison_search_capabilities"
LOAD_TOOL = "jettison_load_capabilities"
# Owned by the Horizon Manager, resolved through the same interception loop.
RETRIEVE_TOOL = "jettison_retrieve_content"
META_TOOL_NAMES = frozenset({SEARCH_TOOL, LOAD_TOOL, RETRIEVE_TOOL})

_SEARCH_DEF = {
    "name": SEARCH_TOOL,
    "description": (
        "Search the capability registry for tools and skills relevant to a task. "
        "Returns ranked capability names with one-line summaries. "
        "Call this before assuming a capability does not exist."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What you need to do."}
        },
        "required": ["query"],
    },
}

_LOAD_DEF = {
    "name": LOAD_TOOL,
    "description": (
        "Load full definitions for named capabilities (tool schemas or skill "
        "instructions) so they can be used. Load only what the task needs."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "names": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Capability names from the index or search results.",
            }
        },
        "required": ["names"],
    },
}


def anthropic_tool_defs() -> list[dict[str, Any]]:
    return [json.loads(json.dumps(d, sort_keys=True)) for d in (_SEARCH_DEF, _LOAD_DEF)]


def openai_tool_defs() -> list[dict[str, Any]]:
    out = []
    for d in (_SEARCH_DEF, _LOAD_DEF):
        out.append(
            json.loads(
                json.dumps(
                    {
                        "type": "function",
                        "function": {
                            "name": d["name"],
                            "description": d["description"],
                            "parameters": d["input_schema"],
                        },
                    },
                    sort_keys=True,
                )
            )
        )
    return out


def resolve_meta_call(
    store: CapabilityStore,
    tool_name: str,
    arguments: dict[str, Any],
    horizon: Any = None,
) -> str:
    """Execute a meta-tool locally; returns the tool_result content string."""
    if tool_name == RETRIEVE_TOOL:
        key = str(arguments.get("key", ""))
        original = horizon.retrieve(key) if horizon is not None else None
        if original is None:
            return json.dumps(
                {"error": f"no held content for key {key!r}", "hint": "it may have aged out"}
            )
        return original
    if tool_name == SEARCH_TOOL:
        hits = store.search(str(arguments.get("query", "")), limit=8)
        if not hits:
            return json.dumps({"results": [], "hint": "No matches; try broader terms or list capabilities via load."})
        return json.dumps(
            {"results": [{"name": h.name, "summary": h.summary} for h in hits]},
            ensure_ascii=False,
        )
    if tool_name == LOAD_TOOL:
        names = [str(n) for n in arguments.get("names", [])]
        found, missing = store.load(names)
        payload: dict[str, Any] = {"loaded": found}
        if missing:
            payload["missing"] = missing
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)
    raise ValueError(f"not a jettison meta-tool: {tool_name}")
