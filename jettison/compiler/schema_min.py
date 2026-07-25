"""Deterministic JSON-Schema / tool-definition minification.

Why no ML here: schemas are exact contracts. A learned compressor risks
silently corrupting a parameter name and breaking every call to that
tool. Deterministic compilation achieves ~90% reduction with zero risk
and byte-stable output (a hard cache-safety requirement — see
docs/CACHE_SAFETY.md). Headroom makes the same split (SmartCrusher is
deterministic for JSON; ML only for prose).

The annotation-key drop list follows Headroom's request-time
tool_schema_compaction (Apache 2.0, see NOTICE); Jettison applies it
at compile time and adds shared-type deduplication on top.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

# JSON-Schema annotation keys that models don't need to call a tool
# correctly. Lossless with respect to the call contract.
DROP_KEYS = frozenset(
    {
        "$id",
        "$schema",
        "$comment",
        "deprecated",
        "examples",
        "example",
        "markdownDescription",
        "readOnly",
        "writeOnly",
        "title",
    }
)

# Filler openers that add no information about *this* tool.
_BOILERPLATE_PATTERNS = [
    re.compile(r"^this tool (allows you to|is used to|can be used to|lets you)\s*", re.I),
    re.compile(r"^use this tool (to|whenever|when you want to)\s*", re.I),
    re.compile(r"^(a|an) tool (that|which|to)\s*", re.I),
]

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")

# Sub-schemas smaller than this aren't worth a $ref indirection.
_MIN_SHARED_SCHEMA_CHARS = 120


def compress_description(desc: str, max_sentences: int = 2, max_chars: int = 280) -> str:
    """Deterministic prose squeeze: strip boilerplate, keep leading sentences."""
    text = " ".join(desc.split())
    for pat in _BOILERPLATE_PATTERNS:
        stripped = pat.sub("", text)
        if stripped != text:
            text = stripped[:1].upper() + stripped[1:] if stripped else stripped
            break
    sentences = _SENTENCE_END.split(text)
    text = " ".join(sentences[:max_sentences]).strip()
    if len(text) > max_chars:
        cut = text[:max_chars]
        # cut at last word boundary; no ellipsis (tokens) unless mid-word
        cut = cut.rsplit(" ", 1)[0] if " " in cut else cut
        text = cut.rstrip(",;: ") + "…"
    return text


# Keys whose *values* are maps of caller-chosen names to schemas. Inside
# them every key is a parameter name, so the annotation drop-list must not
# apply — a tool with a parameter named `description` or `title` would
# otherwise lose it and every call to that tool would be malformed.
_NAME_MAP_KEYS = frozenset({"properties", "$defs", "definitions", "patternProperties"})


def _strip_annotations(node: Any, *, keep_description: bool, is_name_map: bool = False) -> Any:
    if isinstance(node, dict):
        out = {}
        for k, v in node.items():
            if not is_name_map:
                if k in DROP_KEYS:
                    continue
                if k == "description":
                    if not keep_description or not isinstance(v, str):
                        continue
                    compressed = compress_description(v, max_sentences=1, max_chars=140)
                    if compressed:
                        out[k] = compressed
                    continue
            out[k] = _strip_annotations(
                v,
                keep_description=keep_description,
                is_name_map=(not is_name_map) and k in _NAME_MAP_KEYS,
            )
        return out
    if isinstance(node, list):
        return [
            _strip_annotations(v, keep_description=keep_description, is_name_map=False)
            for v in node
        ]
    return node


def _canonical(node: Any) -> str:
    return json.dumps(node, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


@dataclass
class MinifiedTool:
    name: str
    description: str
    input_schema: dict[str, Any]

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


@dataclass
class MinifyResult:
    tools: list[MinifiedTool]
    shared_defs: dict[str, Any] = field(default_factory=dict)
    content_hash: str = ""


def minify_tools(
    tools: list[dict[str, Any]],
    *,
    param_descriptions: bool = True,
    dedupe_shared_types: bool = True,
) -> MinifyResult:
    """Minify a list of tool definitions ({name, description, input_schema}).

    Deterministic and byte-stable: identical input always produces
    byte-identical serialized output (sorted keys, canonical separators,
    dedup dictionary keyed by content hash, tools in input order).
    """
    minified: list[MinifiedTool] = []
    for t in tools:
        schema = _strip_annotations(
            t.get("input_schema") or t.get("inputSchema") or {},
            keep_description=param_descriptions,
        )
        minified.append(
            MinifiedTool(
                name=t.get("name", ""),
                description=compress_description(t.get("description", "") or ""),
                input_schema=schema,
            )
        )

    shared: dict[str, Any] = {}
    if dedupe_shared_types:
        shared = _dedupe_shared(minified)

    payload = _canonical(
        {
            "tools": [m.to_json() for m in minified],
            "$defs": shared,
        }
    )
    return MinifyResult(
        tools=minified,
        shared_defs=shared,
        content_hash=hashlib.sha256(payload.encode()).hexdigest()[:16],
    )


def _dedupe_shared(tools: list[MinifiedTool]) -> dict[str, Any]:
    """Hoist identical sub-schemas appearing in 2+ tools into a $defs dict.

    Def names derive from the sub-schema's own content hash, so output is
    stable regardless of tool ordering or discovery timing.
    """
    counts: dict[str, tuple[int, Any]] = {}

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            canon = _canonical(node)
            if len(canon) >= _MIN_SHARED_SCHEMA_CHARS and node.get("type") in ("object", "array"):
                n, _ = counts.get(canon, (0, node))
                counts[canon] = (n + 1, node)
            for v in node.values():
                visit(v)
        elif isinstance(node, list):
            for v in node:
                visit(v)

    for t in tools:
        for prop in (t.input_schema.get("properties") or {}).values():
            visit(prop)

    shared: dict[str, Any] = {}
    replacements: dict[str, str] = {}
    for canon, (n, node) in counts.items():
        if n < 2:
            continue
        name = "T" + hashlib.sha256(canon.encode()).hexdigest()[:8]
        shared[name] = node
        replacements[canon] = name

    if not replacements:
        return {}

    def replace(node: Any) -> Any:
        if isinstance(node, dict):
            canon = _canonical(node)
            if canon in replacements:
                return {"$ref": f"#/$defs/{replacements[canon]}"}
            return {k: replace(v) for k, v in node.items()}
        if isinstance(node, list):
            return [replace(v) for v in node]
        return node

    for t in tools:
        props = t.input_schema.get("properties")
        if props:
            t.input_schema["properties"] = {k: replace(v) for k, v in props.items()}
    return shared
