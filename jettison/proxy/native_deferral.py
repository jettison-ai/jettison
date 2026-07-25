"""Native deferred-loading detection — the real §8.3 tool step-aside.

Clients are shipping their own tool search: Anthropic's server-side
tool-search tool plus per-tool `defer_loading`, Claude Code behind
`ENABLE_TOOL_SEARCH`, Codex/OpenAI-style deferred tool loading. When the
client already withholds schemas, a second registry indirection buys no
tokens and costs round-trips, so Jettison steps aside for the TOOL
surface. Instructions are a different surface with a different cost and
keep compiling — stepping aside is per-surface, not per-request.

Until now the only step-aside was the min-tools floor, which is a proxy
for the real question. These signals answer it directly:

1. provider-native deferral entries in the tools list — versioned
   Anthropic server tool types (`tool_search_tool_regex_20251119` and
   successors), tool-search function names, or tools carrying a
   `defer_loading` flag;
2. an unusually small tools list paired with a very large system prompt —
   the shape a deferring client produces, because the catalog has been
   replaced by an in-prompt index;
3. an explicit `x-jettison-native-deferral` request header, for clients
   that would rather tell us than be guessed at.

Detection is deterministic — no clock, no RNG, no network, prefix/
substring matching so new dated tool types work without a release. The
verdict decides request bytes, so it obeys the same determinism rule as
the compiler and the index renderer (docs/CACHE_SAFETY.md).
"""

from __future__ import annotations

from typing import Any

# Deliberate reuse of the rewriter's system-text readers: detection must
# see exactly the text the rewriter would have compiled.
from jettison.proxy.rewrite import _openai_system, _system_as_text, _tool_name

NATIVE_DEFERRAL_HEADER = "x-jettison-native-deferral"

# Anthropic ships tool search as a versioned server tool type; matching on
# the stable stem keeps later dated variants recognized.
_NATIVE_TOOL_TYPE_STEMS = ("tool_search_tool", "tool_search_results", "deferred_tool")
# Kept narrow on purpose: a false positive costs savings on a setup that
# would have optimized fine, so generic names like "list_tools" (which
# real MCP servers export) are not signals.
_NATIVE_TOOL_NAME_STEMS = ("tool_search", "search_tools", "defer_tool")
_DEFER_FLAGS = ("defer_loading", "deferred_loading", "defer")

_SMALL_TOOL_LIST = 3
_LARGE_SYSTEM_CHARS = 20_000

_TRUTHY_HEADER = frozenset({"1", "true", "yes", "on"})


def detects_native_deferral(
    body: dict[str, Any], provider: str, headers: Any = None
) -> tuple[bool, str]:
    """Returns (detected, reason); reason is "" when nothing fired.

    `headers` is optional so the detector stays callable on a bare body
    (tests, offline replay) — the header signal is simply unavailable
    then.
    """
    if headers is not None and _header_says_deferred(headers):
        return True, "client_header"

    tools = body.get("tools")
    if not isinstance(tools, list) or not tools:
        return False, ""

    for tool in tools:
        if not isinstance(tool, dict):
            continue
        tool_type = str(tool.get("type", ""))
        if any(stem in tool_type for stem in _NATIVE_TOOL_TYPE_STEMS):
            return True, "native_tool_search_entry"
        name = _tool_name(tool, provider)
        if any(stem in name for stem in _NATIVE_TOOL_NAME_STEMS):
            return True, "native_tool_search_entry"
        if _defers_loading(tool):
            return True, "defer_loading_flag"

    if len(tools) <= _SMALL_TOOL_LIST and _system_chars(body, provider) >= _LARGE_SYSTEM_CHARS:
        return True, "small_tool_list_large_system"

    return False, ""


def _header_says_deferred(headers: Any) -> bool:
    try:
        value = headers.get(NATIVE_DEFERRAL_HEADER, "")
    except AttributeError:
        return False
    return str(value).strip().lower() in _TRUTHY_HEADER


def _defers_loading(tool: dict[str, Any]) -> bool:
    scopes = [tool]
    fn = tool.get("function")
    if isinstance(fn, dict):
        scopes.append(fn)
    return any(bool(scope.get(flag)) for scope in scopes for flag in _DEFER_FLAGS)


def _system_chars(body: dict[str, Any], provider: str) -> int:
    text = (
        _system_as_text(body.get("system"))
        if provider == "anthropic"
        else _openai_system(body)
    )
    return len(text)
