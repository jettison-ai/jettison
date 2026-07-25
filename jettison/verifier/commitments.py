"""Commitment extraction (v1: deterministic, structured content only).

A *commitment* is a fact in the original context that the optimized
context must still entail, or answers may silently change. v1 extracts:

  tool_contract   — tool exists; its required params and param names survive
  numeric         — numbers with their immediate unit/context word
  path            — file paths, URLs
  identifier      — error codes, env vars, UPPER_SNAKE constants, version pins
  security_rule   — paragraphs carrying critical markers (never/must/secret…)
  output_format   — explicit response-format requirements

Prose entailment via a small local NLI model is the v2 upgrade; the
extraction interface here is its seam.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any


class CommitmentKind(str, Enum):
    TOOL_CONTRACT = "tool_contract"
    NUMERIC = "numeric"
    PATH = "path"
    IDENTIFIER = "identifier"
    SECURITY_RULE = "security_rule"
    OUTPUT_FORMAT = "output_format"


@dataclass(frozen=True)
class Commitment:
    kind: CommitmentKind
    key: str  # short identity (tool name, the number, the path)
    span: str  # the exact original text that must remain entailed
    source: str  # where it came from ("system", "tool:<name>")


_NUMERIC = re.compile(
    r"\b\d+(?:\.\d+)?\s?(?:%|percent|seconds?|minutes?|hours?|days?|ms|MB|GB|KB|"
    r"tokens?|items?|lines?|chars?|characters?|retries|attempts|times)\b",
    re.I,
)
_PATH = re.compile(r"(?:^|[\s`(])((?:~?/|\./|[A-Za-z_][\w.-]*/)[\w./-]+\.\w{1,8}|https?://\S+)")
_IDENTIFIER = re.compile(r"\b([A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+|E[A-Z]{2,}\d*|[a-z-]+@\d+\.\d+[\w.]*)\b")
_SECURITY = re.compile(
    r"\b(never|must not|do not|don't|forbidden|secret|credential|password|api.?key|"
    r"production|destructive|irreversible|without (?:an )?approval)\b",
    re.I,
)
_OUTPUT_FORMAT = re.compile(
    r"\b(respond|reply|answer|output|format|return)\b.*\b(json|yaml|markdown|xml|csv|table|bullet)\b",
    re.I,
)


def _paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


def extract_text_commitments(text: str, source: str = "system") -> list[Commitment]:
    out: list[Commitment] = []
    seen: set[tuple[CommitmentKind, str]] = set()

    def add(kind: CommitmentKind, key: str, span: str) -> None:
        ident = (kind, key)
        if ident not in seen:
            seen.add(ident)
            out.append(Commitment(kind=kind, key=key, span=span, source=source))

    for para in _paragraphs(text):
        if _SECURITY.search(para):
            add(CommitmentKind.SECURITY_RULE, para[:60], para)
        if _OUTPUT_FORMAT.search(para):
            add(CommitmentKind.OUTPUT_FORMAT, para[:60], para)
        for m in _NUMERIC.finditer(para):
            add(CommitmentKind.NUMERIC, m.group(0), m.group(0))
        for m in _PATH.finditer(para):
            add(CommitmentKind.PATH, m.group(1), m.group(1))
        for m in _IDENTIFIER.finditer(para):
            add(CommitmentKind.IDENTIFIER, m.group(1), m.group(1))
    return out


def extract_tool_commitments(tools: list[dict[str, Any]]) -> list[Commitment]:
    """Contract per tool: name survives; required list and param names survive."""
    out: list[Commitment] = []
    for t in tools:
        fn = t.get("function") if "function" in t else None
        name = (fn or t).get("name", "")
        schema = (fn or {}).get("parameters") or t.get("input_schema") or t.get("inputSchema") or {}
        params = sorted((schema.get("properties") or {}).keys())
        required = sorted(schema.get("required") or [])
        span = f"{name} required={required} params={params}"
        out.append(
            Commitment(kind=CommitmentKind.TOOL_CONTRACT, key=name, span=span, source=f"tool:{name}")
        )
    return out
