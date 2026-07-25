"""Compiler unit tests: determinism, contract preservation, dedup."""

from __future__ import annotations

import json

from jettison.compiler import (
    build_bundle,
    compile_instructions,
    compress_description,
    minify_tools,
    summarize_skill,
)
from jettison.registry.prompt import render_capability_index


def verbose_tool(name: str, extra_desc: str = "") -> dict:
    return {
        "name": name,
        "description": "This tool allows you to frobnicate the widget. "
        "It should be used whenever frobnication is required. " + extra_desc,
        "input_schema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "title": "Frob",
            "properties": {
                "target": {"type": "string", "title": "Target", "description": "The widget to frobnicate."},
                "opts": {
                    "type": "object",
                    "description": "A large shared options object used by many tools in this family.",
                    "properties": {
                        "retries": {"type": "integer", "default": 3},
                        "timeout_ms": {"type": "integer", "default": 30000},
                        "verbose": {"type": "boolean", "default": False},
                    },
                },
            },
            "required": ["target"],
            "examples": [{"target": "w1"}],
        },
    }


def test_minify_preserves_contract():
    tools = [verbose_tool("frob_a"), verbose_tool("frob_b")]
    r = minify_tools(tools)
    for t in r.tools:
        assert t.input_schema["required"] == ["target"]
        assert set(t.input_schema["properties"].keys()) == {"target", "opts"}
        payload = json.dumps(t.to_json())
        assert "title" not in payload
        assert "$schema" not in payload
        assert "examples" not in payload


def test_minify_is_byte_stable_and_order_independent_defs():
    tools = [verbose_tool("frob_a"), verbose_tool("frob_b")]
    r1 = minify_tools(tools)
    r2 = minify_tools(tools)
    assert r1.content_hash == r2.content_hash
    # shared opts object hoisted under a content-hash name
    assert r1.shared_defs
    name = next(iter(r1.shared_defs))
    r3 = minify_tools(list(reversed(tools)))
    assert name in r3.shared_defs  # same def name regardless of tool order


def test_description_boilerplate_stripped():
    out = compress_description(
        "This tool allows you to search the catalog. Second sentence stays. Third goes."
    )
    assert out.startswith("Search the catalog")
    assert "Third" not in out


def test_instruction_dedup_and_critical_verbatim():
    critical = "Never deploy to production without approval from the release manager."
    dup = "Use conventional commit messages for every commit in this repository."
    a = f"# A\n\n{critical}\n\n{dup}\n\nSome    spaced   filler paragraph about code style preferences here."
    b = f"# B\n\n{dup}\n\nAnother unique paragraph about testing conventions that is long enough."
    ci = compile_instructions([("a.md", a), ("b.md", b)])
    assert ci.dropped_duplicates == 1
    assert critical in ci.text  # verbatim
    assert "Some spaced filler" in ci.text  # whitespace-normalized
    assert ci.text.count("conventional commit") == 1


def test_bundle_hash_stable():
    tools = [verbose_tool("frob_a")]
    r = minify_tools(tools)
    ci = compile_instructions([("x", "A paragraph long enough to survive the length filter easily.")])
    skills = [summarize_skill("s", "---\ndescription: does s things\n---\nbody")]
    idx = render_capability_index([(t.name, t.description) for t in r.tools], skills)
    b1 = build_bundle(r, ci, skills, idx)
    b2 = build_bundle(minify_tools(tools), ci, skills, idx)
    assert b1.content_hash == b2.content_hash
    assert b1.stable_prefix_text() == b2.stable_prefix_text()
