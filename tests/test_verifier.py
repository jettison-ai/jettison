"""Commitment verifier unit tests."""

from __future__ import annotations

from jettison.compiler import compile_instructions, minify_tools
from jettison.verifier import (
    CommitmentKind,
    TextVerifier,
    extract_text_commitments,
    verify_tool_registry,
)

SYSTEM = """You are the deploy assistant for acme-web.

Never deploy to production without an approval from the release manager.

All API calls must go through src/api/client.ts with a timeout of 30 seconds.

Set RETRY_LIMIT to 5 attempts before giving up.

Respond in JSON format with keys status and detail.
"""


def test_extraction_covers_taxonomy():
    cs = extract_text_commitments(SYSTEM)
    kinds = {c.kind for c in cs}
    assert CommitmentKind.SECURITY_RULE in kinds
    assert CommitmentKind.NUMERIC in kinds
    assert CommitmentKind.PATH in kinds
    assert CommitmentKind.IDENTIFIER in kinds
    assert CommitmentKind.OUTPUT_FORMAT in kinds
    keys = {c.key for c in cs}
    assert "30 seconds" in keys
    assert "src/api/client.ts" in keys
    assert "RETRY_LIMIT" in keys


def test_verifier_passes_faithful_compile():
    compiled = compile_instructions([("system", SYSTEM)])
    v = TextVerifier().verify_and_repair(SYSTEM, compiled.text)
    assert v.ok, [f"{x.commitment.kind}:{x.commitment.key}" for x in v.violations]
    assert v.commitments_checked >= 5


def test_verifier_reinflates_dropped_rule():
    # Simulate an over-aggressive optimizer that dropped the security rule.
    broken = SYSTEM.replace(
        "Never deploy to production without an approval from the release manager.\n\n", ""
    )
    v = TextVerifier().verify_and_repair(SYSTEM, broken)
    assert not v.ok
    assert v.restored_text is not None
    assert "Never deploy to production" in v.restored_text


def test_tool_registry_contract_roundtrip():
    tools = [
        {
            "name": "deploy_service",
            "description": "This tool allows you to deploy a service to an environment.",
            "input_schema": {
                "type": "object",
                "title": "Deploy",
                "properties": {
                    "service": {"type": "string", "description": "Service name."},
                    "environment": {"type": "string"},
                },
                "required": ["service", "environment"],
            },
        }
    ]
    r = minify_tools(tools)
    store = {t.name: t.to_json() for t in r.tools}
    v = verify_tool_registry(tools, set(store), store, "anthropic")
    assert v.ok, [x.reason for x in v.violations]


def test_tool_registry_detects_param_loss():
    tools = [
        {
            "name": "deploy_service",
            "description": "d",
            "input_schema": {
                "type": "object",
                "properties": {"service": {"type": "string"}, "environment": {"type": "string"}},
                "required": ["service"],
            },
        }
    ]
    corrupted = {
        "deploy_service": {
            "name": "deploy_service",
            "description": "d",
            "input_schema": {
                "type": "object",
                "properties": {"service": {"type": "string"}},  # environment lost
                "required": ["service"],
            },
        }
    }
    v = verify_tool_registry(tools, {"deploy_service"}, corrupted, "anthropic")
    assert not v.ok
    assert "contract drift" in v.violations[0].reason
